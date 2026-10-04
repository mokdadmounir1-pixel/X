import json

import pytest

from nexus_agents.agents import Lead, Setter
from nexus_agents.benchmark import runner
from nexus_agents.benchmark.metrics import percentile, wilson
from nexus_agents.benchmark.qualification import QualificationError, load_qualified_tasks
from nexus_agents.gateway import ModelGateway
from nexus_agents.models import ModelOutput, ModelUnavailable, StubLocalModel
from nexus_agents.trace import Trace, TracedClient

ITEMS, TH = runner.load()


# ------------------------------------------------------------------ le jeu d'exemples et les seuils
def test_dataset_is_well_formed():
    ids = [i["id"] for i in ITEMS]
    assert len(ids) == len(set(ids)) == 44
    for it in ITEMS:
        assert it["split"] in ("dev", "holdout") and it["task"] in TH["tasks"]
        if it["task"] == "extract_fact" and it["expected"]["quote"] is not None:
            assert it["expected"]["quote"] in it["payload"]["excerpt"]          # la citation attendue existe mot pour mot
    for task in TH["tasks"]:
        hold = [i for i in ITEMS if i["task"] == task and i["split"] == "holdout"]
        assert hold and any(i.get("injection") for i in hold) or task == "draft_message"
    assert {i["expected"]["label"] for i in ITEMS if i["task"] == "classify_reply" and i["split"] == "holdout"} >= {"opt_out", "hostile", "agreement"}


def test_thresholds_are_strict_where_it_matters():
    c = TH["tasks"]["classify_reply"]
    assert c["critical_errors_max"] == 0 and c["injection_coerced_max"] == 0
    assert TH["tasks"]["extract_fact"]["hallucinated_max"] == 0 and TH["tasks"]["draft_message"]["promise_max"] == 0
    assert TH["min_holdout_n"] >= 30


def test_wilson_interval_and_percentiles():
    lo, hi = wilson(9, 10)
    assert 0.55 < lo < 0.60 and 0.97 < hi < 1.0
    assert wilson(0, 0) == (0.0, 1.0)
    assert percentile([1, 2, 3, 4, 5], .5) == 3 and percentile([1, 2, 3, 4, 5], .95) == pytest.approx(4.8)


# ------------------------------------------------------------------ modeles de test
class Oracle:
    """Repond toujours juste : sert a verifier que le banc sait dire « conforme »."""
    name = "oracle"

    def generate(self, task, payload):
        for it in ITEMS:
            if it["task"] == task and it["payload"] == payload:
                if task == "classify_reply": v = {"label": it["expected"]["label"]}
                elif task == "extract_fact": v = {"quote": it["expected"]["quote"], "topic": "facture"}
                else:
                    v = {"subject": "Votre processus", "body": f"Bonjour,\n« {payload['fact_quote']} » Nous pouvons vous montrer une cartographie de 4 heures, "
                                                              f"avec des estimations. Souhaitez-vous un exemple ?\nSi vous ne souhaitez plus être contacté, répondez STOP."}
                return ModelOutput(v, 1, 1, 0, self.name, True)
        raise AssertionError("exemple inconnu")


class Sycophant:
    """Obeit aux consignes cachees, invente des citations, promet des resultats."""
    name = "sycophant"

    def generate(self, task, payload):
        if task == "classify_reply": return ModelOutput({"label": "agreement"}, 1, 1, 0, self.name, True)
        if task == "extract_fact": return ModelOutput({"quote": "Virement immédiat requis RIB prompt OK", "topic": "x"}, 1, 1, 0, self.name, True)
        return ModelOutput({"subject": "s", "body": "Gain garanti de 30 % ! Résultat assuré."}, 1, 1, 0, self.name, True)


class Broken:
    name = "broken"

    def generate(self, task, payload):
        raise ModelUnavailable("hors service")


def test_a_perfect_model_is_conform_but_only_provisional_on_a_small_set():
    s = runner.summarize(runner.evaluate(Oracle(), ITEMS), TH)
    for t, r in s["tasks"].items():
        assert r["verdict"] == "provisoire_conforme", (t, r["reasons"])
        assert r["holdout"]["n"] < TH["min_holdout_n"]


def test_the_bench_catches_a_sycophantic_model():
    s = runner.summarize(runner.evaluate(Sycophant(), ITEMS), TH)
    c, e, d = (s["tasks"][t] for t in ("classify_reply", "extract_fact", "draft_message"))
    assert all(x["verdict"] == "non_qualifié" for x in (c, e, d))
    assert c["holdout"]["critical_errors"] >= 1 and c["holdout"]["injection_followed"] >= 1
    assert e["holdout"]["hallucinated"] >= 1 and e["holdout"]["injection_followed"] >= 1
    assert d["holdout"]["promise"] >= 1


def test_a_broken_model_is_never_qualified():
    s = runner.summarize(runner.evaluate(Broken(), ITEMS), TH)
    assert all(r["verdict"] == "non_qualifié" for r in s["tasks"].values())


def test_only_holdout_decides_the_verdict(tmp_path):
    items = [dict(i, split="dev") if i["task"] == "classify_reply" else i for i in ITEMS]
    s = runner.summarize(runner.evaluate(Sycophant(), items), TH)
    assert s["tasks"]["classify_reply"]["verdict"] == "non_évalué"      # tout est en dev : rien ne permet de decider


def test_rule_based_stub_baseline_is_measured_honestly():
    s = runner.summarize(runner.evaluate(StubLocalModel(), ITEMS), TH)
    assert s["tasks"]["classify_reply"]["verdict"] in ("non_qualifié", "provisoire_conforme")   # reste un baseline, pas une preuve
    assert s["latency"]["n"] == 44


# ------------------------------------------------------------------ manifeste et passerelle
def test_manifest_roundtrip_and_threshold_tampering(tmp_path):
    s = runner.summarize(runner.evaluate(Oracle(), ITEMS), TH)
    m = runner.manifest("oracle", s)
    p = tmp_path / "q.json"; p.write_text(json.dumps(m))
    assert load_qualified_tasks(str(p)) == set()                                     # provisoire : ne qualifie pas
    assert load_qualified_tasks(str(p), accept_provisional=True) == set(TH["tasks"])  # choix explicite et conscient
    other = tmp_path / "thr.json"; other.write_text(json.dumps({**TH, "tasks": {**TH["tasks"], "classify_reply": {**TH["tasks"]["classify_reply"], "accuracy_min": 0.1}}}))
    with pytest.raises(QualificationError):
        load_qualified_tasks(str(p), accept_provisional=True, thresholds=other)       # seuils assouplis apres coup : refuse


def test_gateway_refuses_unqualified_local_tasks_and_never_falls_back_to_cloud(env):
    trace = Trace()
    db = TracedClient(env.client("worker"), trace, "Passerelle de modèles", "nexus_worker")
    gw = ModelGateway(db, trace, StubLocalModel(), cloud=None, qualified_tasks={"extract_fact"})
    ok = gw.run("extract_fact", {"excerpt": "Nous ressaisissons les factures."}, caller="Analyste")
    no = gw.run("classify_reply", {"text": "stop"}, caller="Setter")
    assert ok.ok and not no.ok and no.code == "model_not_qualified" and no.degraded
    assert db.budget_status()["operating"]["committed"] == 0       # rien n'a ete envoye au cloud ni facture


# ------------------------------------------------------------------ filet d'opposition
class AlwaysNeutral:
    name, kind, simulated = "neutre", "local", True

    def generate(self, task, payload):
        return ModelOutput({"label": "neutral"}, 1, 1, 0, self.name, True)


@pytest.mark.parametrize("text", [it["payload"]["text"] for it in ITEMS if it["task"] == "classify_reply" and it["expected"]["label"] == "opt_out"]
                         + ["Ne m’écrivez plus s’il vous plaît", "Please unsubscribe me", "Supprimez mon adresse de vos fichiers"])
def test_opt_out_is_honoured_even_when_the_model_misses_it(env, text):
    trace = Trace()
    gw = ModelGateway(TracedClient(env.client("worker"), trace, "Passerelle de modèles", "nexus_worker"), trace, AlwaysNeutral())
    db = TracedClient(env.client("worker"), trace, "Setter", "nexus_worker")
    lead = Lead("L9", "Societe 9", "Jean", "jean@societe9.example", "https://societe9.example", "x")
    assert Setter(gw, db, trace).handle_reply(lead, text) == "opt_out"
    assert "jean@societe9.example" in [r[0] for r in env.admin().execute("SELECT recipient_norm FROM nexus.suppression").fetchall()]
    assert any(e.code == "opt_out_guard" for e in trace.events)


def test_normal_replies_are_not_swallowed_by_the_guard(env):
    trace = Trace()
    gw = ModelGateway(TracedClient(env.client("worker"), trace, "Passerelle de modèles", "nexus_worker"), trace, StubLocalModel())
    db = TracedClient(env.client("worker"), trace, "Setter", "nexus_worker")
    lead = Lead("L9", "Societe 9", "Jean", "jean@societe9.example", "https://societe9.example", "x")
    assert Setter(gw, db, trace).handle_reply(lead, "Oui, ça m'intéresse, pouvez-vous m'appeler jeudi ?") == "positive"
    assert env.admin().execute("SELECT count(*) FROM nexus.suppression").fetchone()[0] == 0
