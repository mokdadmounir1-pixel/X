"""Exécution des tâches. Aucune de ces fonctions n'émet de message, d'ordre ou de paiement."""
from __future__ import annotations
import re, time
from dataclasses import dataclass
from typing import Callable
from . import audit, quant_engine as qe, tasks as T
from .canon import sha256_hex
from .db import J, tx
from .errors import Invalid, NexusError, NotFound
from .llm import LLM, parse_json_object


class TaskCancelled(Exception):
    pass


@dataclass
class Ctx:
    task: dict
    settings: object
    llm: LLM

    def tx(self):
        return tx(self.settings.database_url)

    def check_cancel(self) -> None:
        with self.tx() as c:
            r = c.execute("SELECT cancel_requested, status FROM tasks WHERE id=%s", (self.task["id"],)).fetchone()
        if r["cancel_requested"]:
            raise TaskCancelled()

    def dep_outputs(self) -> list[dict]:
        with self.tx() as c:
            return [d["outputs"] or {} for d in T.dependencies(c, self.task["id"])]


def h_note(ctx: Ctx) -> dict:
    return {"echo": ctx.task["params"]["text"]}


def h_llm_summarize(ctx: Ctx) -> dict:
    out = ctx.llm.chat("Résume le texte en français en 3 phrases maximum. Ne fais aucune action.",
                       ctx.task["params"]["text"])
    return {"summary": out.strip()[:2000]}


# ---------------- Agence ----------------
def _prospect(c, pid) -> dict:
    p = c.execute("SELECT * FROM prospects WHERE id=%s", (str(pid),)).fetchone()
    if not p:
        raise NotFound("Prospect introuvable")
    if not p["is_fictional"]:
        raise Invalid("v0.1 : seuls les prospects fictifs sont traités", code="real_prospect_refused")
    return p


def h_agency_analyze(ctx: Ctx) -> dict:
    with ctx.tx() as c:
        p = _prospect(c, ctx.task["params"]["prospect_id"])
    issues = p["documented_issues"]
    missing = [k for k in ("sector",) if not p.get(k)]
    return {"prospect": p["name"], "issues_documented": len(issues), "issues": issues,
            "missing_information": missing + ([] if issues else ["problèmes documentés"]),
            "note": "Analyse limitée aux informations fournies manuellement. Aucune recherche externe."}


def h_agency_draft(ctx: Ctx) -> dict:
    with ctx.tx() as c:
        p = _prospect(c, ctx.task["params"]["prospect_id"])
        issues = "\n".join(f"- {i}" for i in p["documented_issues"]) or "- (aucun problème documenté)"
        body = f"""# Proposition de collaboration — {p['name']}

Bonjour,

Voici ce que nous avons compris de votre situation, d'après les informations que vous nous avez communiquées :

{issues}

## Notre approche
Nous proposons un premier échange pour confirmer ces points et définir un périmètre d'intervention.

## Étapes proposées
1. Cadrage et confirmation des besoins
2. Plan d'action détaillé
3. Validation conjointe avant tout démarrage

## Conditions
Le budget et le calendrier seront précisés après l'échange de cadrage.

Cordialement,
L'équipe
"""
        row = c.execute("""INSERT INTO proposals(prospect_id, status, body_md, task_id)
                           VALUES (%s,'draft',%s,%s) RETURNING id""",
                        (p["id"], body, ctx.task["id"])).fetchone()
        audit.record(c, "system", "proposal.drafted", "proposal", row["id"], ctx.task["correlation_id"])
    return {"proposal_id": str(row["id"]), "body_sha256": sha256_hex(body)}


_PRICE = re.compile(r"(\d[\d\s.,]*\s?(€|eur|euros|\$|k€))|garanti|100\s?%|résultat assuré", re.I)


def h_agency_review(ctx: Ctx) -> dict:
    corr = ctx.task["correlation_id"]
    with ctx.tx() as c:
        p = _prospect(c, ctx.task["params"]["prospect_id"])
        prop = c.execute("SELECT * FROM proposals WHERE prospect_id=%s AND status='draft' ORDER BY created_at DESC LIMIT 1 FOR UPDATE",
                         (p["id"],)).fetchone()
        if not prop:
            raise Invalid("Aucun brouillon à contrôler", code="no_draft")
        body = prop["body_md"]
        checks = {
            "tous_les_problemes_documentes_cites": all(i.split()[0].lower() in body.lower() for i in p["documented_issues"] if i.split()),
            "aucun_marqueur_non_rempli": "{{" not in body and "TODO" not in body,
            "aucun_prix_ni_garantie": not _PRICE.search(body),
            "prospect_fictif": bool(p["is_fictional"]),
        }
        ok = all(checks.values())
        c.execute("UPDATE proposals SET review=%s, status=%s WHERE id=%s",
                  (J({"checks": checks, "passed": ok}), "reviewed" if ok else "draft", prop["id"]))
        audit.record(c, "system", "proposal.reviewed", "proposal", prop["id"], corr,
                     "ok" if ok else "error", {"checks": checks})
        if not ok:
            c.commit()  # conserve la trace du contrôle avant d'échouer
            raise Invalid("Contrôle du brouillon refusé : " + ", ".join(k for k, v in checks.items() if not v),
                          code="review_failed")
        sha = sha256_hex(body)
        send = T.create(c, kind="agency.send_proposal", title=f"Approbation d'envoi — {p['name']}",
                        params={"proposal_id": str(prop["id"]), "body_sha256": sha}, created_by="system",
                        correlation_id=corr, settings=ctx.settings, depends_on=[ctx.task["id"]])
        c.execute("UPDATE proposals SET status='awaiting_approval', task_id=%s WHERE id=%s", (send["id"], prop["id"]))
    return {"proposal_id": str(prop["id"]), "checks": checks, "approval_task_id": str(send["id"]),
            "note": "Demande d'approbation créée. Aucun envoi n'est effectué par cette version."}


def h_agency_send(ctx: Ctx) -> dict:
    pr = ctx.task["params"]
    with ctx.tx() as c:
        prop = c.execute("SELECT * FROM proposals WHERE id=%s FOR UPDATE", (pr["proposal_id"],)).fetchone()
        if not prop or sha256_hex(prop["body_md"]) != pr["body_sha256"]:
            raise Invalid("Le texte de la proposition a changé depuis l'approbation", code="body_changed")
        c.execute("UPDATE proposals SET status='approved_not_sent' WHERE id=%s", (prop["id"],))
        audit.record(c, "system", "proposal.approved_not_sent", "proposal", prop["id"], ctx.task["correlation_id"],
                     details={"sent": False})
    return {"sent": False, "reason": "Envoi externe désactivé en v0.1 : approbation enregistrée uniquement"}


# ---------------- Quant ----------------
def h_quant_dataset(ctx: Ctx) -> dict:
    p = ctx.task["params"]
    prices = qe.make_prices(p["seed"], p["bars"])
    sha, ver = qe.dataset_sha(prices), f"seed{p['seed']}-n{p['bars']}-v1"
    prov = {"type": "synthetic", "generator": "gbm", "seed": p["seed"], "drift": qe.DRIFT, "vol": qe.VOL,
            "note": "Données fictives : aucune valeur de marché."}
    with ctx.tx() as c:
        c.execute("""INSERT INTO dataset_versions(name,version,sha256,rows,provenance)
                     VALUES ('demo-synth',%s,%s,%s,%s) ON CONFLICT (name,version) DO NOTHING""",
                  (ver, sha, len(prices), J(prov)))
        row = c.execute("SELECT * FROM dataset_versions WHERE name='demo-synth' AND version=%s", (ver,)).fetchone()
        if row["sha256"] != sha:
            raise Invalid("Version de jeu de données existante avec une empreinte différente", code="dataset_mismatch")
        audit.record(c, "system", "dataset.versioned", "dataset", row["id"], ctx.task["correlation_id"],
                     details={"sha256": sha})
    return {"dataset_id": str(row["id"]), "dataset_version": ver, "sha256": sha, "rows": len(prices)}


def h_quant_backtest(ctx: Ctx) -> dict:
    p = ctx.task["params"]
    ds = next((o for o in ctx.dep_outputs() if "dataset_id" in o), None)
    if not ds:
        raise Invalid("Jeu de données absent", code="no_dataset")
    prices = qe.make_prices(p["seed"], p["bars"])
    if qe.dataset_sha(prices) != ds["sha256"]:
        raise Invalid("Empreinte du jeu de données différente : régénération non identique", code="dataset_mismatch")
    metrics = qe.split_backtests(prices, p["fast"], p["slow"], p["fee_bps"], p["slippage_bps"])
    assumptions = {"fee_bps": p["fee_bps"], "slippage_bps": p["slippage_bps"], "fast": p["fast"], "slow": p["slow"],
                   "long_only": True, "execution": "signal à t, position sur t+1", "optimized": False}
    with ctx.tx() as c:
        sv = c.execute("""INSERT INTO strategy_versions(name,version,definition) VALUES ('sma_cross_long',%s,%s)
                          ON CONFLICT (name,version) DO UPDATE SET name=EXCLUDED.name RETURNING id""",
                       (f"{p['fast']}-{p['slow']}", J({"type": "sma_cross", "fast": p["fast"], "slow": p["slow"]}))).fetchone()
        ex = c.execute("""INSERT INTO experiments(strategy_version_id, dataset_version_id, task_id, status, assumptions, metrics)
                          VALUES (%s,%s,%s,'backtested',%s,%s) RETURNING id""",
                       (sv["id"], ds["dataset_id"], ctx.task["id"], J(assumptions), J(metrics))).fetchone()
        audit.record(c, "system", "experiment.backtested", "experiment", ex["id"], ctx.task["correlation_id"],
                     details={"mode": "SIMULATION"})
    return {"experiment_id": str(ex["id"]), "dataset_id": ds["dataset_id"], "metrics": metrics}


def h_quant_report(ctx: Ctx) -> dict:
    bt = next((o for o in ctx.dep_outputs() if "experiment_id" in o), None)
    if not bt:
        raise Invalid("Backtest absent", code="no_backtest")
    with ctx.tx() as c:
        ex = c.execute("SELECT * FROM experiments WHERE id=%s FOR UPDATE", (bt["experiment_id"],)).fetchone()
        ds = c.execute("SELECT * FROM dataset_versions WHERE id=%s", (ex["dataset_version_id"],)).fetchone()
        sd = ex["assumptions"]
        meta = {"dataset_name": ds["name"], "dataset_version": ds["version"], "sha256": ds["sha256"],
                "seed": ds["provenance"]["seed"], "bars": ds["rows"], **{k: sd[k] for k in ("fast", "slow", "fee_bps", "slippage_bps")}}
        md = qe.report_markdown(meta, ex["metrics"])
        c.execute("UPDATE experiments SET report_md=%s, status='reported' WHERE id=%s", (md, ex["id"]))
        audit.record(c, "system", "experiment.reported", "experiment", ex["id"], ctx.task["correlation_id"])
    return {"experiment_id": str(ex["id"]), "report_chars": len(md), "mode": "SIMULATION"}


# ---------------- Council ----------------
def h_council_role(ctx: Ctx) -> dict:
    p = ctx.task["params"]
    with ctx.tx() as c:
        s = c.execute("SELECT * FROM council_sessions WHERE id=%s", (p["session_id"],)).fetchone()
    if not s:
        raise NotFound("Session du conseil introuvable")
    if p["role"] == "proposal":
        out = ctx.llm.chat("Tu es le proposant. Donne une proposition argumentée en français, 150 mots maximum. "
                           "Tu ne peux ni agir ni engager quoi que ce soit.", s["question"])
        col = "proposal"
    else:
        out = ctx.llm.chat("Tu es le contradicteur. Cherche les failles, les risques et les hypothèses non vérifiées "
                           "de la proposition, en français, 150 mots maximum.",
                           f"Question : {s['question']}\n\nProposition :\n{s['proposal']}")
        col = "counter"
    with ctx.tx() as c:
        c.execute(f"UPDATE council_sessions SET {col}=%s WHERE id=%s", (out.strip()[:4000], s["id"]))
    return {"role": p["role"], "chars": len(out)}


def h_council_synthesis(ctx: Ctx) -> dict:
    sid = ctx.task["params"]["session_id"]
    with ctx.tx() as c:
        s = c.execute("SELECT * FROM council_sessions WHERE id=%s", (sid,)).fetchone()
    raw = ctx.llm.chat(
        "Fais la synthèse. Réponds en JSON avec les clés agreements (liste), disagreements (liste), "
        "open_questions (liste), recommendation (texte). Conserve les désaccords : ne les lisse pas.",
        f"Question : {s['question']}\n\nProposition :\n{s['proposal']}\n\nContre-analyse :\n{s['counter']}", json_mode=True)
    data = parse_json_object(raw)
    for k in ("agreements", "disagreements", "open_questions"):
        if not isinstance(data.get(k), list):
            data[k] = []
    data["grants_rights"] = False
    data["note"] = "Un consensus ne donne aucun droit supplémentaire : toute action reste soumise aux permissions et approbations."
    with ctx.tx() as c:
        c.execute("UPDATE council_sessions SET synthesis=%s WHERE id=%s", (J(data), sid))
    return {"disagreements": len(data["disagreements"]), "grants_rights": False}


# ---------------- Contrôle ----------------
def h_stop_workflows(ctx: Ctx) -> dict:
    me = ctx.task["id"]
    with ctx.tx() as c:
        cancelled = c.execute(
            """UPDATE tasks SET status='cancelled', error_code='stopped_by_request', finished_at=now()
               WHERE status IN ('draft','queued','awaiting_approval') AND id<>%s RETURNING id""", (me,)).fetchall()
        running = c.execute("UPDATE tasks SET cancel_requested=true WHERE status='running' AND id<>%s RETURNING id",
                            (me,)).fetchall()
        audit.record(c, "system", "workflows.stop_executed", "task", me, ctx.task["correlation_id"],
                     details={"cancelled": len(cancelled), "stop_requested": len(running)})
    return {"cancelled": len(cancelled), "stop_requested_running": len(running)}


HANDLERS: dict[str, Callable[[Ctx], dict]] = {
    "note": h_note, "llm_summarize": h_llm_summarize,
    "agency.analyze": h_agency_analyze, "agency.draft_proposal": h_agency_draft,
    "agency.review": h_agency_review, "agency.send_proposal": h_agency_send,
    "quant.dataset": h_quant_dataset, "quant.backtest": h_quant_backtest, "quant.report": h_quant_report,
    "council.role": h_council_role, "council.synthesis": h_council_synthesis,
    "stop_workflows": h_stop_workflows,
}
