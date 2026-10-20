import os
import tempfile
import unittest

import pandas as pd

from prop_sim.book import Signal, VirtualBook, ExecutionModel
from prop_sim.ftmo import FtmoRules, evaluate, prague_day
from prop_sim.risk_engine import RiskEngine, RiskLimits, OpenRisk


def T(s):
    return pd.Timestamp(s, tz="UTC")


class RiskTests(unittest.TestCase):
    def test_cap_cannot_exceed_060(self):
        with self.assertRaises(ValueError):
            RiskLimits(max_risk_per_trade_pct=0.8)

    def ev(self, **kw):
        base = dict(pair="EURUSD", direction="long", risk_pct=0.25, equity=100_000,
                    day_start_equity=100_000, initial_balance=100_000, open_risks=[], signals_today=0)
        base.update(kw)
        return RiskEngine(RiskLimits()).evaluate(**base)

    def test_ok(self):
        self.assertTrue(self.ev().approved)

    def test_correlated_usd_exposure(self):
        opens = [OpenRisk("GBPUSD", "long", 0.5), OpenRisk("AUDUSD", "long", 0.5)]
        d = self.ev(open_risks=opens, risk_pct=0.25)  # EURUSD long: USD -0.75 -> -1.25
        self.assertIn("correlated_exposure_USD", d.reasons)

    def test_floating_loss_counts_against_daily_budget(self):
        d = self.ev(equity=97_500)  # -2.5 % flottant + 0.25 > 3 %? 2.75 -> ok
        self.assertTrue(d.approved)
        d = self.ev(equity=97_000, risk_pct=0.25)  # 3.0 + .25 > 3
        self.assertIn("daily_loss_budget", d.reasons)


class FtmoTests(unittest.TestCase):
    def test_prague_midnight_is_not_utc_midnight(self):
        # 23:30 UTC en hiver = 00:30 Prague le lendemain ; en été 22:30 UTC l'est déjà.
        self.assertEqual(str(prague_day(T("2026-01-10 23:30"))), "2026-01-11")
        self.assertEqual(str(prague_day(T("2026-07-10 21:30"))), "2026-07-10")
        self.assertEqual(str(prague_day(T("2026-07-10 22:30"))), "2026-07-11")

    def snaps(self, rows):
        return pd.DataFrame(rows, columns=["ts", "balance", "equity"]).assign(
            ts=lambda d: pd.to_datetime(d.ts, utc=True)).set_index("ts")

    def test_floating_loss_triggers_daily_fail_even_if_balance_ok(self):
        s = self.snaps([("2026-03-02 09:00", 100_000, 100_000), ("2026-03-02 10:00", 100_000, 94_900)])
        r = evaluate(s, set(), FtmoRules())
        self.assertEqual(r.status, "failed_daily_loss")

    def test_pass_requires_min_days(self):
        s = self.snaps([("2026-03-05 09:00", 110_500, 110_500)])
        d = {pd.Timestamp("2026-03-02").date()}
        self.assertEqual(evaluate(s, d, FtmoRules()).status, "incomplete")
        days = {pd.Timestamp(f"2026-03-0{i}").date() for i in range(2, 6)}
        self.assertEqual(evaluate(s, days, FtmoRules()).status, "passed")

    def test_max_loss(self):
        s = self.snaps([("2026-03-02 09:00", 97_000, 97_000), ("2026-03-03 09:00", 93_000, 93_000),
                        ("2026-03-04 09:00", 90_000, 89_900)])
        self.assertEqual(evaluate(s, set(), FtmoRules()).status, "failed_max_loss")


class BookTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "b.db")
        self.exe = ExecutionModel(slippage_pips=0.0, commission_per_lot=0.0)

    def book(self, status="forward_test"):
        b = VirtualBook(self.path, execution=self.exe)
        b.register_strategy("s", {"a": 1})
        if status:
            b.set_strategy_status("s", status)
        return b

    def sig(self, sid="x1", d="long", stop=1.0950, target=1.1100, ts="2026-03-02 09:00"):
        return Signal(sid, T(ts), "EURUSD", d, stop, target, "s")

    def feed(self, b, bars):
        for ts, o, h, l, c in bars:
            b.on_bar("EURUSD", T(ts), o, h, l, c, 0.0)

    def test_unapproved_strategy_rejected(self):
        b = self.book(status=None)
        self.assertTrue(b.submit_signal(self.sig()).startswith("rejected:strategy_not_in_forward_test"))

    def test_param_change_invalidates_approval(self):
        b = self.book()
        b.register_strategy("s", {"a": 2})
        self.assertTrue(b.submit_signal(self.sig()).startswith("rejected:strategy_not_in_forward_test"))

    def test_dedupe_and_fill_at_next_open_and_target(self):
        b = self.book()
        self.feed(b, [("2026-03-02 09:00", 1.1, 1.1, 1.1, 1.1)])
        self.assertEqual(b.submit_signal(self.sig()), "queued")
        self.assertEqual(b.submit_signal(self.sig()), "duplicate")
        self.feed(b, [("2026-03-02 09:01", 1.1, 1.101, 1.099, 1.1), ("2026-03-02 09:02", 1.1, 1.111, 1.1, 1.11)])
        t = b.trades()
        self.assertEqual(len(t), 1)
        self.assertEqual(t.reason[0], "target")
        self.assertGreater(b.balance, 100_000)

    def test_stop_first_on_collision(self):
        b = self.book()
        self.feed(b, [("2026-03-02 09:00", 1.1, 1.1, 1.1, 1.1)])
        b.submit_signal(self.sig())
        self.feed(b, [("2026-03-02 09:01", 1.1, 1.12, 1.09, 1.1)])
        self.assertEqual(b.trades().reason[0], "stop")
        self.assertLess(b.balance, 100_000)

    def test_gap_through_stop_fills_at_open(self):
        b = self.book()
        self.feed(b, [("2026-03-02 09:00", 1.1, 1.1, 1.1, 1.1), ("2026-03-02 09:01", 1.1, 1.1, 1.1, 1.1)])
        b.submit_signal(self.sig(ts="2026-03-02 09:01"))
        self.feed(b, [("2026-03-02 09:02", 1.1, 1.1, 1.1, 1.1), ("2026-03-02 09:03", 1.08, 1.08, 1.08, 1.08)])
        t = b.trades()
        self.assertEqual(t.reason[0], "stop_gap")
        self.assertAlmostEqual(t.exit[0], 1.08)
        # la perte dépasse le risque prévu (gap) : c'est le comportement attendu
        self.assertLess(b.balance, 100_000 - 0.25 / 100 * 100_000)

    def test_risk_at_stop_matches_request(self):
        b = self.book()
        self.feed(b, [("2026-03-02 09:00", 1.1, 1.1, 1.1, 1.1)])
        b.submit_signal(self.sig())
        self.feed(b, [("2026-03-02 09:01", 1.1, 1.1, 1.1, 1.1), ("2026-03-02 09:02", 1.1, 1.1, 1.09, 1.1)])
        loss = 100_000 - b.balance
        self.assertLessEqual(loss, 250.0 + 1e-6)
        self.assertGreater(loss, 240.0)  # arrondi au pas de 0,01 lot

    def test_resume_is_idempotent(self):
        bars = [("2026-03-02 09:00", 1.1, 1.1, 1.1, 1.1), ("2026-03-02 09:01", 1.1, 1.1, 1.1, 1.1),
                ("2026-03-02 09:02", 1.1, 1.111, 1.1, 1.11)]
        b = self.book()
        self.feed(b, bars[:1])
        b.submit_signal(self.sig(ts="2026-03-02 09:00"))
        b.close()
        b = self.book()
        self.feed(b, bars)  # rejeu complet après redémarrage
        self.assertEqual(b.submit_signal(self.sig(ts="2026-03-02 09:00")), "duplicate")
        self.assertEqual(len(b.trades()), 1)
        n = len(b.equity_curve())
        self.feed(b, bars)
        self.assertEqual(len(b.equity_curve()), n)

    def test_limits_change_refused_on_resume(self):
        self.book().close()
        with self.assertRaises(RuntimeError):
            VirtualBook(self.path, limits=RiskLimits(max_concurrent=1))


if __name__ == "__main__":
    unittest.main()
