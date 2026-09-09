from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from ..core.indicators import adx, atr, ema, rsi
from ..core.liquidity import LiquidityTracker, primary_session
from ..core.regime import detect_regime
from ..instruments import PIP_SIZE


def prepare_dataframe(df: pd.DataFrame, cfg) -> pd.DataFrame:
    df = df.copy()
    df["ema_fast"] = ema(df["close"], cfg.ema_fast)
    df["ema_slow"] = ema(df["close"], cfg.ema_slow)
    df["atr"] = atr(df, cfg.atr_period)
    df["rsi"] = rsi(df["close"], cfg.rsi_period)
    df["adx"] = adx(df, cfg.adx_period)
    df["regime"] = detect_regime(df, cfg)

    w = cfg.swing_fractal_width
    high, low = df["high"], df["low"]
    is_high = pd.Series(True, index=df.index)
    is_low = pd.Series(True, index=df.index)
    for k in range(1, w + 1):
        is_high &= (high > high.shift(k)) & (high > high.shift(-k))
        is_low &= (low < low.shift(k)) & (low < low.shift(-k))
    df["is_swing_high"] = is_high.fillna(False)
    df["is_swing_low"] = is_low.fillna(False)

    sl_lb = cfg.structure_lookback
    df["struct_high"] = high.shift(1).rolling(sl_lb).max()
    df["struct_low"] = low.shift(1).rolling(sl_lb).min()
    df["recent_high"] = high.shift(1).rolling(cfg.recent_extreme_lookback).max()
    df["recent_low"] = low.shift(1).rolling(cfg.recent_extreme_lookback).min()
    return df


@dataclass
class SetupCandidate:
    pair: str
    direction: str
    signal_idx: int
    signal_time: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float
    tp_source: str
    rr: float
    score: float
    score_breakdown: dict
    sweep_level: float
    sweep_kind: str
    fvg_zone: tuple
    regime: str
    session: str


class PairSignalEngine:
    """Bar-by-bar finite-state machine for one pair:
    idle -> pending_sweep -> pending_displacement -> pending_fvg -> pending_retest
    -> (emit SetupCandidate or reject with a reason) -> idle.
    Every stage transition -- accepted or rejected -- is written to `journal`.
    """

    def __init__(self, pair: str, cfg):
        self.pair = pair
        self.cfg = cfg
        self.pip = PIP_SIZE[pair]
        self.liquidity = LiquidityTracker(cfg)
        self.state = "idle"
        self._pending: dict = {}
        self.journal: list[dict] = []

    def _log(self, df, j, stage, status, reason="", extra=None):
        row = df.iloc[j]
        entry = {"pair": self.pair, "time": row.name, "idx": j,
                  "stage": stage, "status": status, "reason": reason}
        if extra:
            entry.update(extra)
        self.journal.append(entry)

    def _reset(self):
        self.state = "idle"
        self._pending = {}

    def process_bar(self, df: pd.DataFrame, j: int) -> Optional[SetupCandidate]:
        self.liquidity.update(df, j)

        if self.state == "idle":
            self._scan_for_sweep(df, j)
            return None
        if self.state == "pending_sweep":
            return self._check_sweep_confirmation(df, j)
        if self.state == "pending_displacement":
            return self._check_displacement(df, j)
        if self.state == "pending_fvg":
            return self._check_fvg(df, j)
        if self.state == "pending_retest":
            return self._check_retest(df, j)
        return None

    # -- stage 1: liquidity sweep -------------------------------------------------
    def _scan_for_sweep(self, df, j):
        cfg = self.cfg
        row = df.iloc[j]
        best_high, best_low = self.liquidity.find_breaches(df, j, self.pip, cfg.sweep_min_pip_breach)

        recent_high, recent_low = row.get("recent_high"), row.get("recent_low")
        prev_high = df["high"].iloc[j - 1] if j > 0 else np.nan
        prev_low = df["low"].iloc[j - 1] if j > 0 else np.nan

        candidates = []
        if best_high is not None:
            candidates.append(("high", best_high.price, best_high.kind, best_high))
        elif (pd.notna(recent_high) and row.high > recent_high + cfg.sweep_min_pip_breach * self.pip
              and not (pd.notna(prev_high) and prev_high > recent_high)):
            candidates.append(("high", float(recent_high), "recent_high", None))

        if best_low is not None:
            candidates.append(("low", best_low.price, best_low.kind, best_low))
        elif (pd.notna(recent_low) and row.low < recent_low - cfg.sweep_min_pip_breach * self.pip
              and not (pd.notna(prev_low) and prev_low < recent_low)):
            candidates.append(("low", float(recent_low), "recent_low", None))

        if not candidates:
            return

        direction, level_price, kind, level_obj = candidates[0]
        if level_obj is not None:
            level_obj.swept = True

        self.state = "pending_sweep"
        self._pending = {
            "breach_idx": j, "breach_dir": direction, "level_price": level_price,
            "level_kind": kind, "breach_extreme": row.high if direction == "high" else row.low,
            "deadline": j + cfg.sweep_confirmation_bars,
        }
        self._log(df, j, "sweep", "breach_detected", extra={"level": level_price, "kind": kind})

    def _check_sweep_confirmation(self, df, j):
        p = self._pending
        row = df.iloc[j]
        reintegrated = (row.close < p["level_price"] if p["breach_dir"] == "high"
                        else row.close > p["level_price"])

        if reintegrated:
            direction = "short" if p["breach_dir"] == "high" else "long"
            self.state = "pending_displacement"
            self._pending.update({
                "direction": direction, "sweep_confirm_idx": j,
                "deadline": j + self.cfg.displacement_max_bars,
            })
            self._log(df, j, "sweep", "confirmed", extra={"direction": direction})
            return None

        if j >= p["deadline"]:
            self._log(df, j, "sweep", "rejected", reason="no_reintegration")
            self._reset()
        return None

    # -- stage 2: displacement -----------------------------------------------------
    def _check_displacement(self, df, j):
        cfg = self.cfg
        p = self._pending
        row = df.iloc[j]
        direction = p["direction"]

        body = abs(row.close - row.open)
        rng = max(row.high - row.low, 1e-12)
        body_ratio = body / rng
        atr_val = row.atr if pd.notna(row.atr) and row.atr > 0 else np.nan
        strong_enough = pd.notna(atr_val) and body >= cfg.displacement_atr_mult * atr_val
        right_direction = (row.close > row.open) if direction == "long" else (row.close < row.open)

        structure_ok = True
        if cfg.displacement_break_structure:
            ref = row.struct_high if direction == "long" else row.struct_low
            structure_ok = pd.notna(ref) and (row.close > ref if direction == "long" else row.close < ref)

        if strong_enough and right_direction and body_ratio >= cfg.displacement_min_body_ratio and structure_ok:
            self.state = "pending_fvg"
            self._pending.update({
                "displacement_start": p["sweep_confirm_idx"], "displacement_end": j,
                "body_ratio": body_ratio, "atr_mult": body / atr_val,
            })
            self._log(df, j, "displacement", "confirmed", extra={"body_ratio": round(body_ratio, 2)})
            return self._check_fvg(df, j)

        if j >= p["deadline"]:
            self._log(df, j, "displacement", "rejected", reason="no_displacement")
            self._reset()
        return None

    # -- stage 3: fair value gap ----------------------------------------------------
    def _check_fvg(self, df, j):
        cfg = self.cfg
        p = self._pending
        direction = p["direction"]
        start, end = p["displacement_start"], p["displacement_end"]
        atr_val = df["atr"].iloc[end]

        gaps = []
        for k in range(max(start - 1, 1), max(end, max(start - 1, 1) + 1)):
            if k + 1 > end or k - 1 < 0:
                continue
            c1_high, c1_low = df["high"].iloc[k - 1], df["low"].iloc[k - 1]
            c3_high, c3_low = df["high"].iloc[k + 1], df["low"].iloc[k + 1]
            if direction == "long" and c3_low > c1_high:
                size = c3_low - c1_high
                if atr_val and size >= cfg.fvg_min_size_atr_mult * atr_val:
                    gaps.append((c1_high, c3_low, size))
            elif direction == "short" and c3_high < c1_low:
                size = c1_low - c3_high
                if atr_val and size >= cfg.fvg_min_size_atr_mult * atr_val:
                    gaps.append((c3_high, c1_low, size))

        if not gaps:
            self._log(df, j, "fvg", "rejected", reason="no_fvg")
            self._reset()
            return None

        chosen = max(gaps, key=lambda g: g[2]) if cfg.fvg_pick == "largest" else gaps[0]
        zone_low, zone_high, size = chosen

        self.state = "pending_retest"
        self._pending.update({
            "fvg_zone": (zone_low, zone_high), "fvg_size": size,
            "retest_deadline": end + cfg.fvg_retest_max_bars,
        })
        self._log(df, j, "fvg", "confirmed", extra={"zone": (round(zone_low, 5), round(zone_high, 5))})
        return None

    # -- stage 4: retest into the FVG -----------------------------------------------
    def _check_retest(self, df, j):
        cfg = self.cfg
        p = self._pending
        row = df.iloc[j]
        zone_low, zone_high = p["fvg_zone"]

        if cfg.fvg_retest_requires_close_inside:
            touched = zone_low <= row.close <= zone_high
        else:
            touched = row.low <= zone_high and row.high >= zone_low

        if not touched:
            if j >= p["retest_deadline"]:
                self._log(df, j, "retest", "rejected", reason="fvg_not_retested")
                self._reset()
            return None

        candidate = self._evaluate_entry(df, j)
        self._reset()
        return candidate

    # -- stage 5: final gates + scoring ----------------------------------------------
    def _evaluate_entry(self, df, j):
        cfg = self.cfg
        p = self._pending
        row = df.iloc[j]
        direction = p["direction"]

        rng = max(row.high - row.low, 1e-12)
        rsi_ok = row.rsi <= cfg.rsi_long_max if direction == "long" else row.rsi >= cfg.rsi_short_min
        rejection_ok = ((row.close - row.low) / rng >= 0.5 if direction == "long"
                         else (row.high - row.close) / rng >= 0.5)
        momentum_ok = rsi_ok and (rejection_ok if cfg.require_rejection_candle else True)
        if not momentum_ok:
            self._log(df, j, "momentum", "rejected", reason="momentum_filter_failed")
            return None

        regime = row.regime
        if direction == "long" and regime == "down":
            self._log(df, j, "regime", "rejected", reason="counter_trend_downtrend")
            return None
        if direction == "short" and regime == "up":
            self._log(df, j, "regime", "rejected", reason="counter_trend_uptrend")
            return None

        spread_pips = row.get("spread_pips", cfg.typical_spread_pips.get(self.pair, 1.5))
        max_spread = cfg.max_spread_pips.get(self.pair, 2.0)
        if spread_pips > max_spread:
            self._log(df, j, "spread", "rejected", reason="spread_too_high", extra={"spread": spread_pips})
            return None

        entry_price = row.close
        sweep_extreme = p["breach_extreme"]
        buffer = cfg.sl_atr_buffer_mult * row.atr
        stop_price = sweep_extreme - buffer if direction == "long" else sweep_extreme + buffer
        risk_dist = abs(entry_price - stop_price)
        if risk_dist <= 0 or pd.isna(risk_dist):
            self._log(df, j, "levels", "rejected", reason="invalid_stop_distance")
            return None

        target_price, tp_source = self._pick_target(df, j, direction, entry_price, risk_dist)
        if target_price is None:
            self._log(df, j, "rr", "rejected", reason="rr_unreachable")
            return None
        rr = abs(target_price - entry_price) / risk_dist

        session = primary_session(self.liquidity._current_session_names)
        score, breakdown = self._score_setup(df, j, direction, rr, spread_pips)
        if score < cfg.score_threshold:
            self._log(df, j, "score", "rejected", reason="score_below_threshold",
                       extra={"score": round(score, 1), **breakdown})
            return None

        self._log(df, j, "entry", "accepted",
                   extra={"score": round(score, 1), "rr": round(rr, 2), **breakdown})
        return SetupCandidate(
            pair=self.pair, direction=direction, signal_idx=j, signal_time=row.name,
            entry_price=entry_price, stop_price=stop_price, target_price=target_price,
            tp_source=tp_source, rr=rr, score=score, score_breakdown=breakdown,
            sweep_level=p["level_price"], sweep_kind=p["level_kind"], fvg_zone=p["fvg_zone"],
            regime=regime, session=session,
        )

    def _pick_target(self, df, j, direction, entry_price, risk_dist):
        cfg = self.cfg
        row = df.iloc[j]
        sign = 1 if direction == "long" else -1

        if direction == "long":
            liq = [lv.price for lv in self.liquidity.pool if lv.direction == "high" and lv.price > entry_price]
            liq_target = min(liq) if liq else None
            struct_target = row.struct_high if pd.notna(row.struct_high) and row.struct_high > entry_price else None
        else:
            liq = [lv.price for lv in self.liquidity.pool if lv.direction == "low" and lv.price < entry_price]
            liq_target = max(liq) if liq else None
            struct_target = row.struct_low if pd.notna(row.struct_low) and row.struct_low < entry_price else None

        for target, source in ((liq_target, "liquidity"), (struct_target, "structure")):
            if target is not None and abs(target - entry_price) / risk_dist >= cfg.min_rr:
                return target, source

        fallback_dist = cfg.min_rr * risk_dist
        max_reach = cfg.max_target_atr_mult * row.atr if pd.notna(row.atr) else 0
        if fallback_dist <= max_reach:
            return entry_price + sign * fallback_dist, "min_rr_fallback"
        return None, "unreachable"

    def _score_setup(self, df, j, direction, rr, spread_pips):
        cfg = self.cfg
        p = self._pending
        row = df.iloc[j]
        w = cfg.score_weights
        total_w = (w.sweep_quality + w.displacement_quality + w.fvg_quality + w.regime_alignment
                   + w.volatility + w.momentum + w.liquidity_room + w.reward_risk + w.spread)

        atr_val = row.atr if pd.notna(row.atr) and row.atr > 0 else 1e-9

        breach_size = abs(p["breach_extreme"] - p["level_price"])
        sweep_q = min(1.0, breach_size / (1.5 * atr_val))

        disp_q = min(1.0, 0.5 * min(1.0, p.get("body_ratio", 0) / cfg.displacement_min_body_ratio)
                     + 0.5 * min(1.0, p.get("atr_mult", 0) / (2 * cfg.displacement_atr_mult)))

        fvg_atr = p["fvg_size"] / atr_val
        fvg_q = min(1.0, fvg_atr / (3 * cfg.fvg_min_size_atr_mult))

        if (direction == "long" and row.regime == "up") or (direction == "short" and row.regime == "down"):
            regime_align = 1.0
        elif row.regime == "range":
            regime_align = 0.6
        else:
            regime_align = 0.0

        atr_pct = atr_val / row.close if row.close else 0
        vol_q = max(0.0, min(1.0, atr_pct / (2 * cfg.regime_slope_min_pct))) if cfg.regime_slope_min_pct else 0.5

        if direction == "long":
            momentum_q = max(0.0, min(1.0, (cfg.rsi_long_max - row.rsi) / cfg.rsi_long_max + 0.3))
        else:
            momentum_q = max(0.0, min(1.0, (row.rsi - cfg.rsi_short_min) / max(100 - cfg.rsi_short_min, 1) + 0.3))

        struct_ref = row.struct_high if direction == "long" else row.struct_low
        room = abs(struct_ref - row.close) if pd.notna(struct_ref) else 0.0
        room_q = min(1.0, room / (3 * atr_val))

        rr_q = min(1.0, rr / (2 * cfg.min_rr)) if cfg.min_rr else 0.5

        max_spread = cfg.max_spread_pips.get(self.pair, 2.0)
        spread_q = max(0.0, 1.0 - spread_pips / max_spread) if max_spread else 0.5

        parts = {
            "sweep_quality": (sweep_q, w.sweep_quality),
            "displacement_quality": (disp_q, w.displacement_quality),
            "fvg_quality": (fvg_q, w.fvg_quality),
            "regime_alignment": (regime_align, w.regime_alignment),
            "volatility": (vol_q, w.volatility),
            "momentum": (momentum_q, w.momentum),
            "liquidity_room": (room_q, w.liquidity_room),
            "reward_risk": (rr_q, w.reward_risk),
            "spread": (spread_q, w.spread),
        }
        raw = sum(v * wt for v, wt in parts.values())
        score = raw * 100 / total_w if total_w else 0.0
        breakdown = {k: round(v * 100, 1) for k, (v, _) in parts.items()}
        return score, breakdown
