"""Boucle d'évolution. Principe : on ne change une stratégie que sur preuve, jamais sur un simple « ça a l'air mieux ».

Cycle (une fois par pas, mensuel par défaut), pour chaque algo, avec les seules données antérieures à T :
  1. SANTÉ    : espérance récente du champion contre sa référence (z-score + CUSUM) -> SAIN / DÉGRADÉ / PAUSE.
  2. OMBRE    : un candidat (autre variante et/ou exclusion de zones perdantes trouvées par `insights`) est suivi
                SANS être tradé pendant `shadow_months` ; promu seulement s'il bat le champion sur ces données
                neuves (marge + probabilité bootstrap), avec limite de fréquence et délai de carence.
  3. PROBATION: après promotion, retour arrière automatique si le nouveau champion fait pire que l'ancien.
  4. RECHERCHE: déclenchée par une dégradation (marge faible) ; sur un champion SAIN seulement tous les
                `explore_every` pas et avec une marge d'entraînement élevée (« peut-on gagner plus ? »).
Les trades sont pré-calculés par le moteur pessimiste (causal) : trancher par date d'entrée/sortie est sans fuite,
comme dans le walk-forward de la recherche. Le registre d'équité « évolutif » ne contient que des trades pris APRÈS
chaque décision, comparés à une configuration figée (« statique ») sur les mêmes fenêtres."""
from __future__ import annotations
from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd
from . import insights as ins
from .health import assess
from .journal import EvoJournal


@dataclass
class EvolveCfg:
    train_months: int = 12
    step_months: int = 1
    shadow_months: int = 2
    health_months: int = 3
    probation_months: int = 2
    embargo_days: int = 5
    min_train_n: int = 25
    shrink: int = 15
    min_recent_n: int = 15
    z_degrade: float = 1.64
    pause_z: float = 2.33
    ref_shrink: float = 0.5           # l'espérance d'entraînement est surestimée par la sélection : on la divise
    margin_degraded: float = 0.02     # avantage d'entraînement requis (score) quand le champion se dégrade
    margin_opportunity: float = 0.10  # idem quand il va bien : il faut une raison nette de toucher
    explore_every: int = 3
    min_shadow_n: int = 12
    promote_margin: float = 0.10      # R/trade d'avance en ombre
    promote_prob: float = 0.80
    max_promotions_per_year: int = 3
    cooldown_months: int = 2
    use_filters: bool = True
    insight_alpha: float = 0.10
    insight_B: int = 499
    seed: int = 0


def MS(ts):
    return int(pd.Timestamp(ts).value)


MONTH_NS = 28 * 86_400 * 10**9


class V:
    """Une variante : tableaux numpy pour trancher vite par fenêtre."""
    def __init__(self, key, df):
        self.key = key
        self.df = ins.prep(df)
        self.e = self.df.entry_t.to_numpy("int64")
        self.x = self.df.exit_t.to_numpy("int64")
        self.r = self.df.r.to_numpy("float64")

    def sel(self, excl, entry_lo=None, entry_hi=None, exit_hi=None):
        m = np.ones(len(self.e), bool)
        if entry_lo is not None:
            m &= self.e >= entry_lo
        if entry_hi is not None:
            m &= self.e < entry_hi
        if exit_hi is not None:
            m &= self.x < exit_hi
        if excl:
            m &= ins.excl_mask(self.df, excl)
        return m


def _score(r, cfg):
    n = len(r)
    return (float(r.sum()) / (n + cfg.shrink)) if n >= cfg.min_train_n else -1e9


def _boot_prob(c, h, B=2000, seed=0):
    rng = np.random.default_rng(seed)
    if len(c) == 0 or len(h) == 0:
        return 0.0
    mc = rng.choice(c, size=(B, len(c))).mean(axis=1)
    mh = rng.choice(h, size=(B, len(h))).mean(axis=1)
    return float((mc > mh).mean())


def month_grid(t0, t1, cfg: EvolveCfg):
    first = (pd.Timestamp(t0) + pd.DateOffset(months=cfg.train_months)).normalize()
    first = first.replace(day=1) + pd.DateOffset(months=1)
    out, T = [], first
    while T < pd.Timestamp(t1):
        out.append(T)
        T = T + pd.DateOffset(months=cfg.step_months)
    return out


def _new_state(v, excl, ref_exp, ref_sd, T):
    return {"variant": v, "excl": list(excl), "ref_exp": float(ref_exp), "ref_sd": float(ref_sd), "since": str(T),
            "status": "ACTIF", "shadow": None, "fallback": None, "probation_until": None, "promo_T": [],
            "last_change": None, "health": {}}


def _train_slice(T, cfg):
    return MS(T - pd.DateOffset(months=cfg.train_months)), MS(T) - cfg.embargo_days * 86_400 * 10**9


def init_champion(vs, T, cfg):
    lo, hi = _train_slice(T, cfg)
    best, bs = None, -1e9
    for k, v in vs.items():
        s = _score(v.r[v.sel(None, lo, None, hi)], cfg)
        if s > bs:
            best, bs = k, s
    if best is None:
        return None
    r = vs[best].r[vs[best].sel(None, lo, None, hi)]
    return _new_state(best, [], cfg.ref_shrink * r.mean(), r.std(ddof=1) if len(r) > 1 else 1.0, T)


def step_algo(algo, vs: dict, st: dict, T, cfg: EvolveCfg, jr: EvoJournal, k: int):
    """Un pas de décision à la date T (données < T uniquement). Modifie `st`."""
    Tn = MS(T)
    lo_t, hi_t = _train_slice(T, cfg)
    champ = vs[st["variant"]]
    # ---- 1. santé (trades virtuels du champion, même en pause)
    h_lo = MS(T - pd.DateOffset(months=cfg.health_months))
    health = assess(champ.r[champ.sel(st["excl"], h_lo, None, Tn)], st["ref_exp"], st["ref_sd"], cfg.min_recent_n,
                    cfg.z_degrade, cfg.pause_z)
    st["health"] = health
    if st["status"] == "ACTIF" and health["state"] == "PAUSE":
        st["status"] = "PAUSE"; st["last_change"] = str(T)
        jr.log("PAUSE", algo, T, raison="espérance récente nettement sous la référence", **health)
    elif st["status"] == "PAUSE" and health["state"] in ("SAIN", "INSUFFISANT") and health.get("mean_R", 0) > 0 \
            and health.get("z", 0) > -1.0:
        st["status"] = "ACTIF"; st["last_change"] = str(T)
        jr.log("REPRISE", algo, T, raison="espérance récente redevenue positive", **health)
    # ---- 2. probation / retour arrière
    if st["fallback"] is not None and st["probation_until"] and Tn >= MS(st["probation_until"]):
        fb = st["fallback"]; t_p = MS(st["promo_T"][-1])
        rn = champ.r[champ.sel(st["excl"], t_p, None, Tn)]
        rf_v = vs[fb["variant"]]
        rf = rf_v.r[rf_v.sel(fb["excl"], t_p, None, Tn)]
        if len(rn) >= cfg.min_recent_n and len(rf) and rn.mean() < rf.mean() - cfg.promote_margin:
            jr.log("RETOUR_ARRIERE", algo, T, raison="le nouveau champion fait pire que l'ancien en probation",
                   nouveau=round(float(rn.mean()), 3), ancien=round(float(rf.mean()), 3), n=len(rn), variante_rejetee=st["variant"])
            promo = st["promo_T"]
            st.update({**fb, "shadow": None, "fallback": None, "probation_until": None, "promo_T": promo, "last_change": str(T)})
            champ = vs[st["variant"]]
        else:
            jr.log("PROBATION_OK", algo, T, nouveau=round(float(rn.mean()), 3) if len(rn) else None,
                   ancien=round(float(rf.mean()), 3) if len(rf) else None, n=len(rn))
        st["fallback"] = None; st["probation_until"] = None
    # ---- 3. évaluation de l'ombre
    sh = st["shadow"]
    if sh and Tn - MS(sh["start"]) >= cfg.shadow_months * MONTH_NS:
        cv = vs[sh["variant"]]; s0 = MS(sh["start"])
        c = cv.r[cv.sel(sh["excl"], s0, None, Tn)]
        hh = champ.r[champ.sel(st["excl"], s0, None, Tn)]
        prob = _boot_prob(c, hh, seed=cfg.seed + k)
        diff = float(c.mean() - hh.mean()) if len(c) and len(hh) else float("nan")
        recent = [t for t in st["promo_T"] if Tn - MS(t) < 365 * 86_400 * 10**9]
        lc = st["last_change"]
        cool = bool(lc) and lc != str(T) and Tn - MS(lc) < cfg.cooldown_months * MONTH_NS
        ok = (len(c) >= cfg.min_shadow_n and c.mean() > 0 and diff >= cfg.promote_margin and prob >= cfg.promote_prob
              and len(recent) < cfg.max_promotions_per_year and not cool)
        info = dict(candidat=sh["variant"], exclusions=sh["excl"], n_candidat=len(c), n_champion=len(hh),
                    R_candidat=round(float(c.mean()), 3) if len(c) else None,
                    R_champion=round(float(hh.mean()), 3) if len(hh) else None, prob_meilleur=round(prob, 3),
                    declencheur=sh["trigger"])
        if ok:
            jr.log("PROMOTION", algo, T, raison="a battu le champion sur données neuves (ombre)", ancien=st["variant"],
                   anciennes_exclusions=st["excl"], **info)
            old = {kk: st[kk] for kk in ("variant", "excl", "ref_exp", "ref_sd", "since", "status")}
            old.update(shadow=None, fallback=None, probation_until=None, promo_T=[], last_change=None, health={})
            st.update(variant=sh["variant"], excl=list(sh["excl"]), ref_exp=cfg.ref_shrink * float(c.mean()),
                      ref_sd=float(c.std(ddof=1)) if len(c) > 1 else 1.0, since=str(T), status="ACTIF", fallback=old,
                      last_change=str(T), probation_until=str(T + pd.DateOffset(months=cfg.probation_months)))
            st["promo_T"] = st["promo_T"] + [str(T)]
            champ = vs[st["variant"]]
        else:
            if len(c) < cfg.min_shadow_n: why = "trop peu de trades en ombre"
            elif not c.mean() > 0: why = "espérance en ombre ≤ 0"
            elif not diff >= cfg.promote_margin: why = "avance insuffisante"
            elif prob < cfg.promote_prob: why = "probabilité de faire mieux trop faible"
            elif cool: why = "délai de carence"
            else: why = "limite de promotions annuelles"
            jr.log("REJET", algo, T, raison=why, **info)
        st["shadow"] = None
    # ---- 4. recherche d'un candidat
    degraded = st["health"].get("state") in ("DEGRADE", "PAUSE")
    explore = (not degraded) and k % cfg.explore_every == 0
    if st["shadow"] is None and (degraded or explore):
        margin = cfg.margin_degraded if degraded else cfg.margin_opportunity
        base = _score(champ.r[champ.sel(st["excl"], lo_t, None, hi_t)], cfg)
        ranked = sorted(((_score(v.r[v.sel(None, lo_t, None, hi_t)], cfg), key) for key, v in vs.items()), reverse=True)
        top = ranked[0][1] if ranked and ranked[0][0] > -1e8 else None
        pool = []
        for key in sorted({x for x in (top, st["variant"]) if x}):
            v = vs[key]
            tm = v.sel(None, lo_t, None, hi_t)
            pool.append((key, [], _score(v.r[tm], cfg)))
            if cfg.use_filters:
                a = ins.analyze(v.df[tm], cfg.insight_alpha, cfg.insight_B, seed=cfg.seed + k)
                if a["exclude"]:
                    pool.append((key, a["exclude"], _score(v.r[v.sel(a["exclude"], lo_t, None, hi_t)], cfg)))
                    jr.log("INSIGHT", algo, T, variante=key, exclure=a["exclude"], zones_positives=a["positive"],
                           m_tests=a["m_tests"], alpha_sidak=a["alpha_sidak"],
                           statut="HYPOTHÈSE (à valider en ombre, jamais appliquée directement)")
        pool = [(kk, ex, s) for kk, ex, s in pool if not (kk == st["variant"] and sorted(ex) == sorted(st["excl"]))]
        pool.sort(key=lambda x: -x[2])
        if pool and pool[0][2] > -1e8 and pool[0][2] - base >= margin:
            kk, ex, s = pool[0]
            st["shadow"] = {"variant": kk, "excl": ex, "start": str(T), "train_score": round(s, 4), "base_score": round(base, 4),
                            "trigger": "dégradation" if degraded else "opportunité"}
            jr.log("OMBRE_DEBUT", algo, T, candidat=kk, exclusions=ex, score_candidat=round(s, 4), score_champion=round(base, 4),
                   declencheur=st["shadow"]["trigger"])
    return st


def evolve_all(tv: dict, cfg: EvolveCfg | None = None, journal: EvoJournal | None = None, state: dict | None = None,
               t0=None, t1=None, epochs=None, label="SYNTHÉTIQUE") -> dict:
    """tv = {algo: {variante: DataFrame de trades}}. Rejoue (ou reprend, si `state`) la boucle sur la grille mensuelle."""
    cfg = cfg or EvolveCfg()
    jr = journal or EvoJournal(None, label)
    V_ = {a: {k: V(k, d) for k, d in d_.items() if len(d)} for a, d_ in tv.items()}
    V_ = {a: v for a, v in V_.items() if v}
    if not V_:
        raise ValueError("aucun trade à faire évoluer")
    if t0 is None:
        t0 = pd.Timestamp(min(v.e.min() for a in V_.values() for v in a.values()), tz="UTC")
    if t1 is None:
        t1 = pd.Timestamp(max(v.x.max() for a in V_.values() for v in a.values()), tz="UTC")
    epochs = list(epochs) if epochs is not None else month_grid(t0, t1, cfg)
    states = (state or {}).get("algos", {})
    done = (state or {}).get("last_epoch")
    static_cfg = (state or {}).get("static", {})
    rec = {a: {"evolving": [], "static": [], "paused_virtual": []} for a in V_}
    for k, T in enumerate(epochs):
        if done and MS(T) <= MS(done):
            continue
        Tn = MS(T); Tnext = MS(T + pd.DateOffset(months=cfg.step_months))
        for a, vs in V_.items():
            if a not in states:
                s0 = init_champion(vs, T, cfg)
                if s0 is None:
                    continue
                states[a] = s0
                static_cfg[a] = {"variant": s0["variant"]}
                jr.log("INIT", a, T, variante=s0["variant"], ref_R=round(s0["ref_exp"], 3))
            st = states[a]
            step_algo(a, vs, st, T, cfg, jr, k)
            ch = vs[st["variant"]]
            r_ch = ch.r[ch.sel(st["excl"], Tn, Tnext, None)]
            sv = vs[static_cfg[a]["variant"]]
            rec[a]["static"].append((T, sv.r[sv.sel(None, Tn, Tnext, None)]))
            if st["status"] == "ACTIF":
                rec[a]["evolving"].append((T, r_ch))
            else:
                rec[a]["paused_virtual"].append((T, r_ch))
                rec[a]["evolving"].append((T, np.array([])))
        done = str(T)
    return {"cfg": asdict(cfg), "algos": states, "static": static_cfg, "last_epoch": str(done) if done else None,
            "records": rec, "journal": jr, "label": label}


def summarize(res: dict, since=None, B=4000, seed=0) -> dict:
    """Valeur ajoutée de l'évolution = R mensuel (évolutif) − R mensuel (statique), IC bootstrap sur les mois."""
    rng = np.random.default_rng(seed)
    out, months = {}, {}
    for a, rc in res["records"].items():
        pts = [(T, e, s) for (T, e), (_, s) in zip(rc["evolving"], rc["static"]) if since is None or MS(T) >= MS(since)]
        if not pts:
            continue
        for T, e, s in pts:
            m = months.setdefault(str(T), [0.0, 0.0, 0, 0])
            m[0] += e.sum(); m[1] += s.sum(); m[2] += len(e); m[3] += len(s)
        e_m = np.array([x[1].sum() for x in pts]); s_m = np.array([x[2].sum() for x in pts])
        out[a] = _cmp(e_m, s_m, sum(len(x[1]) for x in pts), sum(len(x[2]) for x in pts), rng, B)
        st = res["algos"].get(a, {})
        j = res["journal"]
        out[a].update(config_finale=st.get("variant"), exclusions=st.get("excl"), statut=st.get("status"),
                      promotions=j.count("PROMOTION", a), rejets=j.count("REJET", a),
                      retours_arriere=j.count("RETOUR_ARRIERE", a), pauses=j.count("PAUSE", a))
    if months:
        arr = np.array(list(months.values()))
        out["_portefeuille"] = _cmp(arr[:, 0], arr[:, 1], arr[:, 2].sum(), arr[:, 3].sum(), rng, B)
    return out


def _cmp(e_m, s_m, n_e, n_s, rng, B):
    d = e_m - s_m
    bs = rng.choice(d, size=(B, len(d))).mean(axis=1)
    lo, hi = float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))
    verdict = "UTILE (IC95 > 0)" if lo > 0 else "NUISIBLE (IC95 < 0)" if hi < 0 else "NON DÉMONTRÉ (IC95 contient 0)"
    return {"mois": len(d), "trades_evolutif": int(n_e), "trades_statique": int(n_s),
            "R_total_evolutif": round(float(e_m.sum()), 1), "R_total_statique": round(float(s_m.sum()), 1),
            "gain_R_par_mois": round(float(d.mean()), 3), "IC95_gain": [round(lo, 3), round(hi, 3)],
            "verdict_evolution": verdict}


def state_to_json(res: dict) -> dict:
    return {"cfg": res["cfg"], "algos": res["algos"], "static": res["static"], "last_epoch": res["last_epoch"], "label": res["label"]}
