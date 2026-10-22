import pytest
from nexus.risk import HardLimits, InstrumentSpec, Mode, Order, RiskGuardian

SPECS = {"MES": InstrumentSpec("MES", 5.0, 0.25), "MNQ": InstrumentSpec("MNQ", 2.0, 0.25)}
LIM = HardLimits(max_order_notional=60_000, max_position_notional=100_000,
                 max_gross_notional=150_000, max_risk_per_trade=100, max_daily_loss=300,
                 max_drawdown=800, max_open_orders=5, max_orders_per_minute=3,
                 max_data_age_s=2.0)


def mk(**kw):
    g = RiskGuardian(LIM, SPECS, equity=10_000)
    g.reconcile({})
    g.on_tick("MES", 100.0, 5000.0)
    g.on_tick("MNQ", 100.0, 20000.0)
    return g


def o(i="a", sym="MES", side=1, qty=1, px=5000.0, stop=4990.0, **kw):
    return Order(i, "s", sym, side, qty, px, stop, **kw)


def test_ok_entry():
    assert mk().check(o(), 100.5).approved


def test_duplicate_rejected():
    g = mk(); assert g.check(o(), 100.5).approved
    assert g.check(o(), 100.6).reasons == ("ordre_duplique",)


def test_unreconciled_blocks_entries_but_allows_reduction():
    g = RiskGuardian(LIM, SPECS, 10_000)
    g.on_tick("MES", 100.0, 5000.0)
    assert "etat_non_reconcilie" in g.check(o(), 100.1).reasons
    g.positions["MES"] = 1.0     # position inconnue heritee
    assert g.check(o("r", side=-1, stop=None), 100.1).approved


def test_stale_data_blocks():
    assert "donnees_perimees" in mk().check(o(), 103.0).reasons


def test_stop_required_wrong_side_and_risk():
    g = mk()
    assert "stop_obligatoire" in g.check(o("1", stop=None), 100.5).reasons
    assert "stop_du_mauvais_cote" in g.check(o("2", stop=5010.0), 100.5).reasons
    # 1 MES, stop 30 pts = 150 USD > 100
    assert "risque_par_trade" in g.check(o("3", stop=4970.0), 100.5).reasons


def test_wrong_multiplier_symbol_and_size_bug():
    g = mk()
    assert g.check(o("x", sym="ES"), 100.5).reasons == ("symbole_inconnu",)
    assert "notionnel_ordre" in g.check(o("y", qty=3, stop=4999.0), 100.5).reasons  # 75k > 60k
    assert g.check(o("z", qty=-1), 100.5).reasons == ("ordre_invalide",)


def test_rate_limit():
    g = mk()
    for i in range(3):
        assert g.check(o(str(i)), 100.1 + i * 0.1).approved
    assert "cadence_ordres" in g.check(o("n"), 100.9).reasons
    g.on_tick("MES", 160.0, 5000.0)
    assert g.check(o("later"), 161.0).approved


def test_gross_notional_uses_last_price_of_other_symbols():
    g = mk()
    g.on_fill("MNQ", 3)          # 3*20000*2 = 120k
    r = g.check(o("g", qty=1), 100.5)   # +25k => 145k <= 150k
    assert r.approved
    g.on_fill("MES", 2)          # 50k
    r2 = g.check(o("g2", qty=1, stop=4999.0), 100.6)
    assert "notionnel_brut" in r2.reasons


def test_daily_loss_halts_and_restart_requires_reconcile_and_operator():
    g = mk(); g.update_equity(9_690)
    assert g.mode is Mode.HALTED
    assert g.check(o(), 100.5).reasons[0].startswith("halted")
    assert not g.authorize_restart("")
    assert not g.authorize_restart("alice")     # limite toujours violee
    g.new_day(9_690)
    assert g.authorize_restart("alice") and g.mode is Mode.NORMAL


def test_restart_refused_if_unreconciled():
    g = RiskGuardian(LIM, SPECS, 10_000); g.halt("test")
    assert not g.authorize_restart("bob") and g.mode is Mode.HALTED


def test_drawdown_halt():
    g = mk(); g.update_equity(10_500); g.update_equity(9_690)
    assert g.mode is Mode.HALTED and g.halt_reason in ("max_daily_loss", "max_drawdown")


def test_position_mismatch_forces_reduce_only():
    g = mk(); g.on_fill("MES", 1)
    assert not g.reconcile({"MES": 2.0})
    assert g.mode is Mode.REDUCE_ONLY and not g.reconciled
    assert g.check(o("e"), 100.5).reasons == ("reduce_only",)
    assert g.check(o("r", side=-1, stop=None), 100.5).approved


def test_reversal_is_not_a_reduction():
    g = mk(); g.on_fill("MES", 1); g.mode = Mode.REDUCE_ONLY
    assert g.check(o("rev", side=-1, qty=2), 100.5).reasons == ("reduce_only",)


def test_liquidation_only_confirmed_by_broker():
    g = mk(); g.on_fill("MES", 2)
    req = g.request_liquidation()
    assert g.mode is Mode.HALTED and req.status == "REQUESTED"
    orders = g.liquidation_orders({"MES": 5000.0})
    assert g.check(orders[0], 100.5).approved
    assert g.check(o("sneaky", side=-1, qty=1, stop=None), 100.5).reasons[0].startswith("halted")
    assert not g.confirm(req, 0, {"MES": 2.0}) and req.status == "REQUESTED"
    assert g.confirm(req, 0, {}) and req.status == "CONFIRMED"


def test_cancel_all_not_confirmed_while_orders_remain():
    g = mk(); r = g.request_cancel_all()
    assert not g.confirm(r, 2, {}) and r.status == "REQUESTED"
    assert g.confirm(r, 0, {})


def test_limits_cannot_loosen():
    g = mk()
    with pytest.raises(ValueError):
        g.tighten(max_daily_loss=1000)
    g.tighten(max_daily_loss=100)
    assert g.limits.max_daily_loss == 100
    with pytest.raises(Exception):
        g.limits.max_daily_loss = 5       # frozen
