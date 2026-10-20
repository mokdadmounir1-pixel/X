"""Catalogue des types de tâches. Une tâche ne peut exister que si son type est ici :
l'application n'exécute jamais de code ou de commande fournis par un utilisateur ou un modèle."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class P(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NoteParams(P):
    text: str = Field(min_length=1, max_length=500)


class SummarizeParams(P):
    text: str = Field(min_length=1, max_length=4000)


class ProspectRef(P):
    prospect_id: UUID


class SendProposalParams(P):
    proposal_id: UUID
    body_sha256: str = Field(min_length=64, max_length=64)


class QuantDatasetParams(P):
    seed: int = Field(ge=0, le=10_000_000)
    bars: int = Field(default=1500, ge=300, le=20000)


class QuantBacktestParams(P):
    seed: int = Field(ge=0, le=10_000_000)
    bars: int = Field(default=1500, ge=300, le=20000)
    fast: int = Field(ge=2, le=50)
    slow: int = Field(ge=5, le=200)
    fee_bps: float = Field(default=2.0, ge=0, le=50)
    slippage_bps: float = Field(default=1.0, ge=0, le=50)

    @model_validator(mode="after")
    def _order(self):
        if self.slow <= self.fast:
            raise ValueError("slow doit être supérieur à fast")
        return self


class EmptyParams(P):
    pass


class CouncilRoleParams(P):
    session_id: UUID
    role: Literal["proposal", "counter"]


class CouncilSessionRef(P):
    session_id: UUID


class StopWorkflowsParams(P):
    reason: str = Field(min_length=3, max_length=300)


@dataclass(frozen=True)
class KindSpec:
    model: type[P]
    level: int            # 0 lecture, 1 interne, 2 engageante : approbation du Fondateur obligatoire
    timeout_s: int = 60
    direct: bool = False  # créable directement par POST /tasks
    owner: str = "operateur"


KINDS: dict[str, KindSpec] = {
    "note": KindSpec(NoteParams, 1, 10, True),
    "llm_summarize": KindSpec(SummarizeParams, 1, 120, True, "conseil"),
    "agency.analyze": KindSpec(ProspectRef, 1, 30, False, "redacteur-agence"),
    "agency.draft_proposal": KindSpec(ProspectRef, 1, 30, False, "redacteur-agence"),
    "agency.review": KindSpec(ProspectRef, 1, 30, False, "relecteur"),
    "agency.send_proposal": KindSpec(SendProposalParams, 2, 30, False, "redacteur-agence"),
    "quant.dataset": KindSpec(QuantDatasetParams, 1, 60, False, "analyste-quant"),
    "quant.backtest": KindSpec(QuantBacktestParams, 1, 120, False, "analyste-quant"),
    "quant.report": KindSpec(EmptyParams, 1, 30, False, "analyste-quant"),
    "council.role": KindSpec(CouncilRoleParams, 1, 180, False, "conseil"),
    "council.synthesis": KindSpec(CouncilSessionRef, 1, 180, False, "conseil"),
    "stop_workflows": KindSpec(StopWorkflowsParams, 2, 30, False, "operateur"),
}


def validate_params(kind: str, params: dict) -> dict:
    from .errors import Invalid
    spec = KINDS.get(kind)
    if spec is None:
        raise Invalid(f"Type de tâche inconnu : {kind}", code="unknown_kind")
    try:
        return spec.model(**params).model_dump(mode="json")
    except Exception as e:  # ValidationError, TypeError
        raise Invalid(f"Paramètres invalides pour {kind} : {e}", code="invalid_params") from e
