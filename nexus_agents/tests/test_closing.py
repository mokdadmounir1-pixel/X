import io
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

import pypdf
import pytest

from nexus_agents import rejection as rj
from nexus_agents.agents import Lead
from nexus_agents.closing import (OFFRES, Closing, PaymentError, StripeCheckoutProvider, StubPaymentProvider, Terms, TermsError,
                                  amounts_in, extract_terms, plain_text, render_pdf)
from nexus_agents.gateway import ModelGateway
from nexus_agents.models import StubCloudModel, StubLocalModel
from nexus_agents.trace import Trace, TracedClient


def terms(reply, name="Claire Martin"):
    return extract_terms(reply, "Agence Lumière", name, "L1")


@pytest.mark.parametrize("text,expected", [
    ("D'accord pour 490 €", [490.0]), ("490€", [490.0]), ("490 euros", [490.0]), ("1 490,50 €", [1490.5]),
    ("1.490 €", [1490.0]), ("une audit de 4 h et 20 minutes", []), ("90 € puis 149 EUR", [90.0, 149.0]),
])
def test_amounts_are_parsed_including_the_euro_sign(text, expected):
    assert amounts_in(text) == expected


def test_variables_are_extracted_with_their_provenance():
    t = terms("D'accord pour l'audit de 4 h à 490 €, envoyez-moi le devis.")
    assert isinstance(t, Terms) and t.offer_key == "audit_4h"
    v = t.variables
    assert (v["nom"], v["entreprise"], v["prix_eur_ht"]) == ("Claire Martin", "Agence Lumière", 490) and v["perimetre"] and v["offre"]
    assert "catalogue" in t.provenance["prix_eur_ht"] and "fiche du lead" in t.provenance["nom"]


@pytest.mark.parametrize("reply,name,code", [
    ("D'accord pour l'audit, envoyez le devis.", "Claire", "prix_non_confirme"),          # prix absent : on n'invente pas
    ("D'accord pour l'audit à 400 €.", "Claire", "prix_incoherent"),                       # le texte du prospect ne fixe pas le prix
    ("D'accord pour l'audit à 490 € et 300 €.", "Claire", "prix_incoherent"),
    ("D'accord pour le tarif, merci.", "Claire", "offre_non_identifiable"),
    ("D'accord pour l'audit et la maintenance à 490 €.", "Claire", "offres_multiples"),
    ("D'accord pour l'audit à 490 €.", "", "variable_manquante:nom"),
    ("D'accord pour l'audit à 490 €.", "   ", "variable_manquante:nom"),
])
def test_missing_or_inconsistent_terms_yield_no_document_and_a_precise_error(reply, name, code):
    e = terms(reply, name)
    assert isinstance(e, TermsError) and e.code == code and len(e.motif) > 15 and e.preuve["type"]


def test_the_price_always_comes_from_the_catalogue():
    for key, o in OFFRES.items():
        reply = {"audit_4h": "audit", "nettoyage_crm": "nettoyage", "extraction_lot": "extraction", "maintenance_flux": "maintenance"}[key]
        t = terms(f"D'accord pour le {reply} à {o['prix_eur_ht']} €")
        assert isinstance(t, Terms) and t.variables["prix_eur_ht"] == o["prix_eur_ht"]


def test_pdf_is_deterministic_valid_and_carries_the_variables_without_inventing_the_issuer():
    v = terms("D'accord pour l'audit à 490 €").variables
    a, b = render_pdf(v, "DV-L1-20261006", "2026-10-06"), render_pdf(v, "DV-L1-20261006", "2026-10-06")
    assert a == b and a.startswith(b"%PDF-")
    assert render_pdf(v, "DV-L1-20261007", "2026-10-07") != a
    text = pypdf.PdfReader(io.BytesIO(a)).pages[0].extract_text()
    for needle in ("DEVIS", "Claire Martin", "Agence Lumière", "490 €", "Audit de processus", "À COMPLÉTER", "PROJET", "garanties de résultat"):
        assert needle in text, needle
    assert "SIREN" in text and not any(ch.isdigit() for ch in text.split("SIREN")[1][:12])      # aucun SIREN invente


# ------------------------------------------------------------------ Stripe : contre un faux serveur, en mode test
class FakeStripe(BaseHTTPRequestHandler):
    seen = []
    fail = False

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        FakeStripe.seen.append({"path": self.path, "headers": dict(self.headers), "form": parse_qs(body)})
        if FakeStripe.fail:
            self.send_response(500); self.end_headers(); return
        data = json.dumps({"id": "cs_test_123", "url": "https://checkout.stripe.test/c/pay/cs_test_123", "expires_at": 1790000000}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, *a): pass


@pytest.fixture()
def stripe_url():
    srv = HTTPServer(("127.0.0.1", 0), FakeStripe)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    FakeStripe.seen.clear(); FakeStripe.fail = False
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_stripe_session_is_created_with_idempotency_expiry_and_exact_amount(stripe_url):
    p = StripeCheckoutProvider("sk_test_abc123", base_url=stripe_url)
    link = p.create_link(amount_cents=24500, currency="eur", description="Acompte 50 %", reference="DV-L1-20261006", document_sha256="a" * 64)
    req = FakeStripe.seen[0]
    assert req["path"] == "/v1/checkout/sessions" and req["headers"]["Authorization"] == "Bearer sk_test_abc123"
    assert req["headers"]["Idempotency-Key"] == "nexus-DV-L1-20261006"          # une relance ne cree pas un 2e lien
    f = req["form"]
    assert f["line_items[0][price_data][unit_amount]"] == ["24500"] and f["line_items[0][price_data][currency]"] == ["eur"]
    assert f["mode"] == ["payment"] and f["metadata[document_sha256]"] == ["a" * 64] and f["client_reference_id"] == ["DV-L1-20261006"]
    assert 0 < int(f["expires_at"][0]) - __import__("time").time() <= 24 * 3600
    assert link.url.startswith("https://checkout.stripe.test/") and not link.simulated and link.provider == "stripe"


def test_live_keys_are_refused_unless_explicitly_enabled_and_the_key_never_leaks(stripe_url):
    with pytest.raises(PaymentError):
        StripeCheckoutProvider("sk_live_secret999", base_url=stripe_url)
    with pytest.raises(PaymentError):
        StripeCheckoutProvider("", base_url=stripe_url)
    StripeCheckoutProvider("sk_live_secret999", base_url=stripe_url, live=True)       # decision explicite
    p = StripeCheckoutProvider("sk_test_secretXYZ", base_url=stripe_url)
    assert "secretXYZ" not in repr(p) and "secretXYZ" not in str(p)
    FakeStripe.fail = True
    with pytest.raises(PaymentError) as e:
        p.create_link(amount_cents=100, currency="eur", description="x", reference="r", document_sha256="b" * 64)
    assert "secretXYZ" not in str(e.value)
    with pytest.raises(PaymentError):
        p.create_link(amount_cents=0, currency="eur", description="x", reference="r", document_sha256="b" * 64)


def test_stub_payment_link_points_nowhere():
    link = StubPaymentProvider().create_link(amount_cents=100, currency="eur", description="x", reference="DV-1", document_sha256="c" * 64)
    assert link.simulated and ".invalid" in link.url


# ------------------------------------------------------------------ l'agent Closing, sur une vraie base
@pytest.fixture()
def closing_world(env):
    trace = Trace()
    mk = lambda actor, role: TracedClient(env.client(role), trace, actor, f"nexus_{role}")
    db = mk("Closing", "worker")
    gw = ModelGateway(mk("Passerelle de modèles", "worker"), trace, StubLocalModel(), StubCloudModel())
    c = Closing(gw, db, trace, StubPaymentProvider(), clock=lambda: "2026-10-06")
    env.client("worker").record_lead_score("L1", 5, "test")
    return env, trace, c, Lead("L1", "Agence Lumière", "Claire Martin", "claire@agence-lumiere.example", "https://agence-lumiere.example", "x")


def test_closing_prepares_document_link_and_a_message_that_is_not_sent(closing_world):
    env, trace, c, lead = closing_world
    r = c.prepare(lead, "D'accord pour l'audit de 4 h à 490 €, envoyez-moi le devis.")
    assert r.ok and r.document_id and r.message_id and r.link.simulated
    doc = env.client("founder").get_document(r.document_id)
    assert doc.sha256 == r.sha256 and doc.variables["prix_eur_ht"] == 490 and doc.pdf.startswith(b"%PDF")
    msg = env.client("founder").get_message(r.message_id)
    assert msg["state"] == "draft" and r.sha256 in msg["body"] and r.link.url in msg["body"] and "STOP" in msg["body"]
    assert env.client("transport").claim() is None                                   # rien n'est parti : ni revue, ni approbation
    again = c.prepare(lead, "D'accord pour l'audit de 4 h à 490 €, envoyez-moi le devis.")
    assert again.document_id == r.document_id and again.message_id == r.message_id   # relance : aucun doublon


def test_closing_blocks_with_a_stored_rejection_and_a_founder_alert(closing_world):
    env, trace, c, lead = closing_world
    r = c.prepare(lead, "D'accord pour l'audit à 400 €.")
    assert not r.ok and r.code == "prix_incoherent" and isinstance(r.rejection, rj.RejectionDetail)
    rows = env.client("founder").list_rejections()
    assert rows[0]["stage"] == "closing" and "400" in rows[0]["motif_exact"] and rows[0]["indice_confiance"] == 1.0
    assert [n["kind"] for n in env.client("founder").notifications()] == ["closing_blocked"]
    assert env.client("founder").list_documents() == []


def test_closing_still_produces_the_quote_when_the_cloud_review_is_refused_by_the_budget(closing_world):
    env, trace, c, lead = closing_world
    env.set_policy(daily_api_cap_cents=0, priority_reserve_daily_cents=0)             # plus aucun budget cloud
    r = c.prepare(lead, "D'accord pour l'audit à 490 €.")
    # lead de score 5 (eligible) mais reserve a 0 : la base dit « reserve epuisee », et le dossier le dit au fondateur
    assert r.ok and "relecture cloud non faite" in r.marker and "priority_reserve_exhausted" in r.marker
    env.set_policy(priority_min_score=5)
    low = Lead("L9", "Societe 9", "Jean", "jean@societe9.example", "https://societe9.example", "x")
    env.client("worker").record_lead_score("L9", 3, "test")
    r2 = c.prepare(low, "D'accord pour l'audit à 490 €.")
    assert r2.ok and "budget_exceeded:daily_api" in r2.marker                    # score 3 : la reserve ne lui est meme pas ouverte
