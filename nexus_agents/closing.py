"""Closing : du « prêt à signer » à un devis PDF + lien de paiement, déposé en file d'approbation.

GARDE-FOUS (voulus) :
- le prix du devis vient du CATALOGUE ; le texte du prospect ne peut que le CONFIRMER. Prix absent ou différent => aucun document.
- rien n'est envoyé : le message au client passe par la revue du Censeur puis par l'approbation du fondateur, liée à l'empreinte
  du texte (qui contient l'empreinte du PDF et le lien de paiement) ;
- les mentions légales de l'émetteur sont laissées « À COMPLÉTER » : la structure juridique n'existe pas encore, on ne l'invente pas ;
- le document est un PROJET généré à partir d'un modèle ; sa valeur juridique reste à faire valider par un professionnel.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional, Protocol

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import rejection as rj

TEMPLATE_VERSION = "devis-v1"
DEPOSIT_RATIO = 0.5          # acompte de 50 % du HT : hypothese du plan, a confirmer par le fondateur

# Catalogue : prix et perimetres du plan A-Z (P1 a P4). Source de verite du prix.
OFFRES = {
    "audit_4h": {"label": "Audit de processus (4 h)", "prix_eur_ht": 490, "motifs": [r"\baudit\b"],
                 "perimetre": "Un seul processus. Quatre heures estimées : entretien, analyse, cartographie, restitution. "
                              "Trois recommandations. Aucune mise en œuvre incluse."},
    "nettoyage_crm": {"label": "Nettoyage d'un export CRM (500 lignes)", "prix_eur_ht": 300, "motifs": [r"\bnettoyage\b", r"\bcrm\b"],
                      "perimetre": "Fichier CSV de 500 lignes et 2 Mo au plus, une colonne e-mail. Fusion des seules lignes identiques, "
                                   "conflits isolés, rapport. Travail sur une copie ; aucun import dans votre CRM."},
    "extraction_lot": {"label": "Extraction d'un lot de 250 documents", "prix_eur_ht": 149, "motifs": [r"\bextraction\b", r"\blot de\b"],
                       "perimetre": "Un lot de 250 documents au plus. Aucun traitement comptable, aucun paiement."},
    "maintenance_flux": {"label": "Maintenance d'un flux (par mois)", "prix_eur_ht": 90, "motifs": [r"\bmaintenance\b"],
                         "perimetre": "Un flux, une heure par mois au plus, horaires convenus. Aucune promesse de disponibilité 24 h/24."},
}
_AMOUNT = re.compile(r"(\d{1,3}(?:[   .]\d{3})+|\d+)(?:[.,](\d{1,2}))?\s*(?:€|(?:euros?|eur)\b)", re.I)


@dataclass
class TermsError:
    code: str
    motif: str
    preuve: dict


@dataclass
class Terms:
    offer_key: str
    variables: dict
    provenance: dict


def amounts_in(text: str) -> list:
    out = []
    for m in _AMOUNT.finditer(text):
        whole = re.sub(r"[   .]", "", m.group(1))
        out.append(float(f"{whole}.{m.group(2) or '0'}"))
    return out


def extract_terms(reply: str, company: str, contact_name: str, source_ref: str):
    """Variables du devis (Nom, Entreprise, Prix, Périmètre) avec la provenance de chacune, ou une erreur precise."""
    hits = [k for k, o in OFFRES.items() if any(re.search(rx, reply, re.I) for rx in o["motifs"])]
    quote = reply.strip()[:200]
    if not (contact_name or "").strip():
        return TermsError("variable_manquante:nom", "nom du contact absent de la fiche du lead : devis impossible",
                          {"type": "champ_absent", "champ": "contact_name", "lead": source_ref})
    if not hits:
        return TermsError("offre_non_identifiable", "aucune offre du catalogue n'est nommée dans la réponse du prospect",
                          {"type": "reponse_prospect", "extrait": quote, "offres_connues": sorted(OFFRES)})
    if len(hits) > 1:
        return TermsError("offres_multiples", f"la réponse évoque plusieurs offres ({', '.join(hits)}) : à clarifier avec le prospect",
                          {"type": "reponse_prospect", "extrait": quote, "offres": hits})
    key = hits[0]
    offre = OFFRES[key]
    prices = amounts_in(reply)
    if not prices:
        return TermsError("prix_non_confirme", f"le prospect n'a pas confirmé de prix par écrit (catalogue : {offre['prix_eur_ht']} €)",
                          {"type": "reponse_prospect", "extrait": quote, "prix_catalogue": offre["prix_eur_ht"]})
    wrong = [p for p in prices if abs(p - offre["prix_eur_ht"]) > 0.005]
    if wrong:
        return TermsError("prix_incoherent", f"prix cité par le prospect ({wrong[0]:g} €) différent du catalogue ({offre['prix_eur_ht']} €)",
                          {"type": "reponse_prospect", "extrait": quote, "prix_cite": wrong[0], "prix_catalogue": offre["prix_eur_ht"]})
    variables = {"nom": contact_name.strip(), "entreprise": company.strip(), "offre": offre["label"],
                 "perimetre": offre["perimetre"], "prix_eur_ht": offre["prix_eur_ht"], "offre_cle": key}
    provenance = {"nom": "fiche du lead", "entreprise": "fiche du lead", "offre": "catalogue, identifiée dans la réponse du prospect",
                  "perimetre": "catalogue", "prix_eur_ht": f"catalogue, confirmé par écrit dans la réponse ({prices[0]:g} €)"}
    return Terms(key, variables, provenance)


# ------------------------------------------------------------------ rendu du devis
def plain_text(v: dict, reference: str) -> str:
    return (f"Devis {reference}. {v['offre']}. Prix : {v['prix_eur_ht']} € HT. Périmètre : {v['perimetre']} Client : {v['entreprise']}, {v['nom']}.")


def render_pdf(v: dict, reference: str, date_iso: str) -> bytes:
    """PDF DETERMINISTE (invariant=True) : meme entree, memes octets, donc meme empreinte (relance sans doublon)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
                            title=f"Devis {reference}", author="Nexus", invariant=True)
    st = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=st["Title"], fontSize=20, alignment=0, spaceAfter=2)
    b = ParagraphStyle("b", parent=st["BodyText"], fontSize=10, leading=14)
    small = ParagraphStyle("s", parent=b, fontSize=8.5, leading=11, textColor=colors.HexColor("#555555"))
    price = v["prix_eur_ht"]
    deposit = round(price * DEPOSIT_RATIO, 2)
    rows = [["Prestation", "Prix HT"], [Paragraph(f"<b>{v['offre']}</b><br/>{v['perimetre']}", b), f"{price:g} €"]]
    t = Table(rows, colWidths=[130 * mm, 40 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EDF2")), ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#B8C2CC")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("FONTSIZE", (0, 0), (-1, 0), 9)]))
    story = [Paragraph("DEVIS — PROJET", h), Paragraph(f"Référence {reference} · émis le {date_iso}", small), Spacer(1, 8),
             Paragraph("<b>Émetteur</b>", b),
             Paragraph("[À COMPLÉTER : raison sociale, forme juridique, SIREN, adresse, n° de TVA — la structure n'est pas encore constituée]", small),
             Spacer(1, 6), Paragraph("<b>Client</b>", b), Paragraph(f"{v['entreprise']} — à l'attention de {v['nom']}", b), Spacer(1, 10), t, Spacer(1, 6),
             Paragraph(f"Total HT : <b>{price:g} €</b> · TVA : [À COMPLÉTER selon le régime de l'émetteur]", b), Spacer(1, 10),
             Paragraph("<b>Conditions</b>", b),
             Paragraph(f"Acompte de {DEPOSIT_RATIO:.0%} du montant HT ({deposit:g} €) à la commande, solde à la livraison. Devis valable 14 jours. "
                       "Les estimations chiffrées éventuellement remises sont des hypothèses, jamais des garanties de résultat. "
                       "Hors périmètre : toute prestation non décrite ci-dessus.", b), Spacer(1, 14),
             Paragraph("Ce document est un PROJET généré à partir du modèle " + TEMPLATE_VERSION + ". Il n'engage aucune partie tant qu'il n'a pas été "
                       "validé par le fondateur de Nexus et accepté par le client. Ses clauses juridiques doivent être relues par un professionnel.", small)]
    doc.build(story)
    return buf.getvalue()


# ------------------------------------------------------------------ lien de paiement
class PaymentError(Exception):
    pass


@dataclass(frozen=True)
class PaymentLink:
    url: str
    provider: str
    simulated: bool
    external_id: str
    expires_at: str


class PaymentProvider(Protocol):
    def create_link(self, *, amount_cents: int, currency: str, description: str, reference: str, document_sha256: str) -> PaymentLink: ...


class StubPaymentProvider:
    """SIMULATION : un lien factice qui ne pointe nulle part (domaine .invalid, jamais resolu)."""
    def create_link(self, *, amount_cents, currency, description, reference, document_sha256) -> PaymentLink:
        return PaymentLink(f"https://paiement.invalid/simulation/{reference}", "simulation", True, f"sim_{reference}", "24 h")


class StripeCheckoutProvider:
    """Stripe Checkout (API REST). MODE TEST uniquement par defaut : refuse toute cle autre que sk_test_/rk_test_.

    La cle ne vient jamais du code : variable d'environnement ou gestionnaire de secrets. Elle n'est ni journalisee ni affichee.
    La cle d'idempotence est la reference du devis : une relance ne cree pas un deuxieme lien.
    """
    def __init__(self, secret_key: str, *, base_url="https://api.stripe.com", live=False, timeout=15,
                 success_url="https://example.invalid/merci", cancel_url="https://example.invalid/annule"):
        if not secret_key:
            raise PaymentError("cle Stripe absente")
        if not live and not secret_key.startswith(("sk_test_", "rk_test_")):
            raise PaymentError("cle non-test refusee : le mode live exige live=True, decide explicitement par le fondateur")
        self._key, self.base, self.live, self.timeout = secret_key, base_url.rstrip("/"), live, timeout
        self.success_url, self.cancel_url = success_url, cancel_url

    def __repr__(self):
        return f"StripeCheckoutProvider(live={self.live}, key=***)"

    def create_link(self, *, amount_cents, currency, description, reference, document_sha256) -> PaymentLink:
        if amount_cents <= 0:
            raise PaymentError("montant invalide")
        expires = int(time.time()) + 23 * 3600          # Stripe : de 30 min a 24 h
        form = urllib.parse.urlencode({
            "mode": "payment", "client_reference_id": reference, "success_url": self.success_url, "cancel_url": self.cancel_url,
            "expires_at": expires, "line_items[0][quantity]": 1, "line_items[0][price_data][currency]": currency,
            "line_items[0][price_data][unit_amount]": amount_cents, "line_items[0][price_data][product_data][name]": description[:250],
            "metadata[document_sha256]": document_sha256, "metadata[reference]": reference}).encode()
        req = urllib.request.Request(f"{self.base}/v1/checkout/sessions", data=form, method="POST", headers={
            "Authorization": f"Bearer {self._key}", "Idempotency-Key": f"nexus-{reference}",
            "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:     # noqa: S310 (hote fixe, configure par le fondateur)
                data = json.loads(r.read().decode())
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise PaymentError(f"Stripe indisponible ou reponse illisible ({type(exc).__name__})") from None   # jamais le detail : il pourrait citer la cle
        if "url" not in data or "id" not in data:
            raise PaymentError("reponse Stripe sans lien")
        return PaymentLink(data["url"], "stripe", False, data["id"], str(data.get("expires_at", expires)))


# ------------------------------------------------------------------ l'agent
@dataclass
class ClosingResult:
    ok: bool
    code: str
    document_id: Optional[int] = None
    sha256: Optional[str] = None
    message_id: Optional[int] = None
    reference: Optional[str] = None
    link: Optional[PaymentLink] = None
    marker: str = ""
    rejection: Optional[rj.RejectionDetail] = None


class Closing:
    NAME = "Closing"

    def __init__(self, gateway, db, trace, payment: PaymentProvider, clock=None, sender="Nexus"):
        self.gw, self.db, self.trace, self.payment = gateway, db, trace, payment
        self.clock = clock or (lambda: dt.date.today().isoformat())
        self.sender = sender

    def _blocked(self, lead, code, detail: rj.RejectionDetail) -> ClosingResult:
        rj.emit_rejection(self.trace, self.db, self.NAME, "Hermes", lead.id, detail)
        self.db.notify_founder("closing_blocked", f"{lead.id}:{code}", f"Devis non généré pour {lead.company} : {detail.motif_exact}")
        return ClosingResult(False, code, rejection=detail)

    def prepare(self, lead, reply_text: str) -> ClosingResult:
        t = self.trace
        t.emit("Hermes", self.NAME, "tâche", f"préparer le devis de {lead.company} à partir de la réponse du prospect")
        terms = extract_terms(reply_text, lead.company, lead.contact_name, lead.id)
        if isinstance(terms, TermsError):
            return self._blocked(lead, terms.code, rj.deterministic("closing", self.NAME, terms.motif, terms.preuve))
        v = terms.variables
        t.emit(self.NAME, self.NAME, "variables", f"extraites : {v['nom']} · {v['entreprise']} · {v['offre']} · {v['prix_eur_ht']} € HT",
               ok=True, code="ok", provenance=terms.provenance)
        date_iso = self.clock()
        reference = f"DV-{lead.id}-{date_iso.replace('-', '')}"
        pdf = render_pdf(v, reference, date_iso)
        # relecture cloud facultative : si le budget la refuse, le document est tout de meme produit, et le dossier le dit
        chk = self.gw.run("closing", {"body": plain_text(v, reference), "expected_price": f"{v['prix_eur_ht']}"}, caller=self.NAME,
                          allow_cloud=True, est_cents=200, lead_ref=lead.id, idem=f"closing-check:{lead.id}:{terms.offer_key}")
        marker = ("relu par le modèle cloud (simulé) : prix et offre conformes" if chk.ok and chk.output.get("ok")
                  else "relecture cloud non faite (" + chk.code + ") : à relire à la main" if not chk.ok
                  else "relecture cloud : incohérence signalée, à vérifier")
        d = self.db.create_document(f"doc:{lead.id}:{terms.offer_key}", lead.id, "devis", TEMPLATE_VERSION,
                                    {k: x for k, x in v.items() if k != "offre_cle"}, pdf)
        t.emit(self.NAME, "Noyau Nexus", "document", f"devis {reference} enregistré (sha256 {(d.sha256 or '')[:12]}…)", ok=d.ok, code=d.code, document_id=d.id)
        if not d.ok:
            return self._blocked(lead, d.code, rj.deterministic("closing", self.NAME, f"la base a refusé le document : {d.code}",
                                                                {"type": "validation_base", "code": d.code, "variables": list(v)}))
        deposit = round(v["prix_eur_ht"] * DEPOSIT_RATIO, 2)
        try:
            link = self.payment.create_link(amount_cents=int(round(deposit * 100)), currency="eur", reference=reference,
                                            description=f"Acompte {DEPOSIT_RATIO:.0%} — {v['offre']} ({reference})", document_sha256=d.sha256)
        except PaymentError as exc:
            return self._blocked(lead, "paiement_indisponible", rj.deterministic("closing", self.NAME, f"lien de paiement non créé : {exc}",
                                                                                 {"type": "fournisseur_paiement", "erreur": str(exc)}))
        t.emit(self.NAME, "Fournisseur de paiement", "lien", f"lien d'acompte créé ({link.provider}{', SIMULÉ' if link.simulated else ''}, {deposit:g} € HT)",
               ok=True, code="ok", simulated=link.simulated)
        first = v["nom"].split(" ")[0]
        body = (f"Bonjour {first},\n\nSuite à votre accord, voici votre devis {reference} : {v['offre']}, {v['prix_eur_ht']:g} € HT.\n"
                f"Périmètre : {v['perimetre']}\n"
                f"Pièce jointe : devis-{reference}.pdf (empreinte sha256 : {d.sha256}).\n"
                f"Pour confirmer, un acompte de {deposit:g} € HT est à régler par ce lien, valable 24 h : {link.url}\n"
                f"Le devis est valable 14 jours ; la TVA applicable y est précisée.\n\n"
                f"Si vous ne souhaitez plus être contacté, répondez STOP.\n\n{self.sender}")
        m = self.db.create_message(f"closing-msg:{lead.id}:{d.sha256[:12]}", "email", lead.email, f"Votre devis {reference}", body, 0, "closing devis")
        t.emit(self.NAME, "Hermes", "livrable" if m.ok else "rejet", f"message de devis déposé pour revue et approbation ({m.code})", ok=m.ok, code=m.code, message_id=m.id)
        if not m.ok:
            return self._blocked(lead, m.code, rj.deterministic("closing", self.NAME, f"message de devis refusé par la base : {m.code}",
                                                                {"type": "validation_base", "code": m.code}))
        return ClosingResult(True, "ok", d.id, d.sha256, m.id, reference, link, marker)
