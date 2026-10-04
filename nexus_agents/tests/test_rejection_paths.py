"""Chaque chemin d'ecartement produit un rejection_detail complet, en base et au journal."""
import pytest

from nexus_agents import rejection as rj
from nexus_agents.agents import Analyste, Lead, Redacteur, Sourcing
from nexus_agents.gateway import ModelGateway
from nexus_agents.hermes import CircuitBreaker, Hermes
from nexus_agents.models import ModelOutput, StubLocalModel
from nexus_agents.trace import Trace, TracedClient


@pytest.fixture()
def world(env):
    trace = Trace()
    mk = lambda actor, role: TracedClient(env.client(role), trace, actor, f"nexus_{role}")
    gw = ModelGateway(mk("Passerelle de modèles", "worker"), trace, StubLocalModel())
    return env, trace, gw, mk


def raw(**kw):
    base = dict(id="X1", company="Societe X", contact_name="Jean Dupont", email="jean@societe-x.example",
                source_url="https://societe-x.example/a", excerpt="Nous ressaisissons les factures à la main.")
    return {**base, **kw}


def stored(env):
    return env.client("founder").list_rejections()


def test_detail_object_refuses_incomplete_or_overconfident_rejections():
    ok = dict(stage="sourcing", agent="Sourcing", motif_exact="motif suffisamment précis", preuve_source={"type": "regle"}, indice_confiance=1.0,
              base_confiance="regle_deterministe")
    rj.RejectionDetail(**ok)
    for field, value in [("motif_exact", "court"), ("motif_exact", "  "), ("preuve_source", {}), ("preuve_source", {"x": 1}),
                         ("indice_confiance", 1.2), ("indice_confiance", -0.1), ("base_confiance", "intuition"), ("stage", "ailleurs"), ("agent", "")]:
        with pytest.raises(ValueError):
            rj.RejectionDetail(**{**ok, field: value})
    with pytest.raises(ValueError):                       # une heuristique ne peut pas se declarer certaine
        rj.RejectionDetail(**{**ok, "base_confiance": "heuristique", "indice_confiance": 1.0})


@pytest.mark.parametrize("override,fragment,ptype,conf", [
    (dict(source_url=""), "aucune URL source https", "champ_absent", 1.0),
    (dict(source_url="http://pas-https.example"), "aucune URL source https", "champ_absent", 1.0),
    (dict(email="jean@gmail.com"), "messagerie grand public", "regle", 1.0),
    (dict(email="pas-un-mail"), "adresse non professionnelle ou invalide", "regle", 1.0),
    (dict(excerpt="Boulangerie ouverte le dimanche.", contact_name=None), "score", "score", None),
])
def test_sourcing_rejects_with_exact_reason_proof_and_confidence(world, override, fragment, ptype, conf):
    env, trace, gw, mk = world
    lead, d = Sourcing(gw, trace, mk("Sourcing", "worker")).validate(raw(**override))
    assert lead is None and fragment in d.motif_exact and d.preuve_source["type"] == ptype
    if conf is not None:
        assert d.indice_confiance == conf
    else:
        assert d.base_confiance == "heuristique" and 0.5 <= d.indice_confiance <= 0.9 and d.preuve_source["seuil"] == 3
    row = stored(env)[0]
    assert row["motif_exact"] == d.motif_exact and row["stage"] == "sourcing" and row["lead"] == "X1"
    assert any(e.detail.get("rejection_detail", {}).get("motif_exact") == d.motif_exact for e in trace.events)    # visible au journal


def test_sourcing_duplicate_names_the_lead_that_took_the_domain(world):
    env, trace, gw, mk = world
    s = Sourcing(gw, trace, mk("Sourcing", "worker"))
    assert s.validate(raw(id="A"))[0] is not None
    assert s.validate(raw(id="A"))[0] is not None                              # le meme lead relance : pas un doublon
    lead, d = s.validate(raw(id="B", email="autre@societe-x.example"))
    assert lead is None and "lead A" in d.motif_exact and d.preuve_source["lead_precedent"] == "A"


def test_low_score_lead_has_its_score_recorded_for_the_reserve(world):
    env, trace, gw, mk = world
    Sourcing(gw, trace, mk("Sourcing", "worker")).validate(raw(excerpt="Rien d'utile ici.", contact_name=None))
    assert env.client("worker").record_lead_score("X1", 5, "triche").code == "score_already_set"        # le score est fige


class Inventor(StubLocalModel):
    def _extract_fact(self, p):
        return {"quote": "Phrase inventée absente de la source (facture).", "topic": "facture"}


def test_analyst_distinguishes_no_fact_from_an_invented_quote(world):
    env, trace, gw, mk = world
    lead = Lead("X1", "Societe X", "Jean", "jean@societe-x.example", "https://societe-x.example/a", "Boulangerie. Ouvert le dimanche.")
    a, d = Analyste(gw, trace, mk("Analyste", "worker")).analyse(lead)
    assert a is None and "aucune phrase" in d.motif_exact and d.base_confiance == "heuristique" and d.indice_confiance == 0.8
    assert d.preuve_source["url"] == lead.source_url and "mots_cles_cherches" in d.preuve_source
    gw2 = ModelGateway(mk("Passerelle de modèles", "worker"), trace, Inventor())
    lead2 = Lead("X2", "Societe Y", "Jean", "j@societe-y.example", "https://societe-y.example", "Nous ressaisissons les factures.")
    a2, d2 = Analyste(gw2, trace, mk("Analyste", "worker")).analyse(lead2)
    assert a2 is None and "absente de la source mot pour mot" in d2.motif_exact and d2.indice_confiance == 1.0 and d2.base_confiance == "regle_deterministe"
    assert d2.preuve_source["citation_proposee"].startswith("Phrase inventée")


def test_writer_explains_a_suppression_with_date_and_reason_but_not_the_address(world):
    env, trace, gw, mk = world
    env.client("worker").suppress("jean@societe-x.example", "plainte reçue par téléphone")
    lead = Lead("X1", "Societe X", "Jean", "jean@societe-x.example", "https://societe-x.example/a", "Nous ressaisissons les factures.")
    from nexus_agents.agents import Analysis
    res, d = Redacteur(gw, mk("Rédacteur", "worker"), trace).draft(lead, Analysis("Nous ressaisissons les factures.", "facture", 1, 2, 3, 4, "x"))
    assert "opposition enregistrée le 2026-10-05" in d.motif_exact and "plainte reçue par téléphone" in d.motif_exact
    assert d.preuve_source["table"] == "suppression" and "jean@" not in str(stored(env))


def test_a_dismissal_without_detail_is_a_programming_error(world):
    env, trace, gw, mk = world
    h = Hermes(gateway=gw, db=mk("Hermes", "worker"), trace=trace, sourcing=None, analyste=None, redacteur=None, censeur=None,
               fondateur=None, transport=None, setter=None)
    with pytest.raises(ValueError, match="rejection_detail obligatoire"):
        h._end({"id": "X", "company": "Y"}, "écarté_sourcing", "motif trop vague")
    h._end({"id": "X", "company": "Y"}, "sent")                      # un succes n'en a pas besoin


def test_open_circuit_breaker_dismissals_carry_their_reason(world):
    env, trace, gw, mk = world
    b = CircuitBreaker(); b.record(sent=100, bounces=20)
    h = Hermes(gateway=gw, db=mk("Hermes", "worker"), trace=trace, sourcing=None, analyste=None, redacteur=None, censeur=None,
               fondateur=None, transport=None, setter=None, breaker=b)
    out = h.process_lead(raw())
    d = out["rejection_detail"]
    assert out["status"] == "pipeline_suspendu" and "rebonds 20/100" in d["motif_exact"] and d["preuve_source"]["type"] == "coupe_circuit"
    assert stored(env)[0]["stage"] == "pipeline"
