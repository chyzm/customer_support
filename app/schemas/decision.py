from enum import Enum

from pydantic import BaseModel

from app.schemas.evaluation import TicketEvaluation


class Priority(str, Enum):
    P1 = "P1"  # critical
    P2 = "P2"  # high
    P3 = "P3"  # normal
    P4 = "P4"  # low


class Handling(str, Enum):
    """How much human involvement the decision needs. Ordered least to most."""

    AUTO_ROUTE = "auto_route"  # safe to route without a person looking
    REVIEW = "review"  # route it, but a person should confirm
    HUMAN_TRIAGE = "human_triage"  # do not guess: a person decides the queue


class Reason(BaseModel):
    """One step of the decision, so every outcome can be explained and audited."""

    code: str
    detail: str


class Signals(BaseModel):
    """The numbers the engine actually used. Confidence is computed by us from probabilities."""

    category_confidence: float
    urgency_score: float
    urgency_confidence: float
    sentiment_score: float
    sentiment_confidence: float
    escalation_probability: float


class TriageDecision(BaseModel):
    queue: str
    priority: Priority
    escalate: bool
    handling: Handling
    reasons: list[Reason]
    signals: Signals
    policy_version: str


class TriageResult(BaseModel):
    """What the API returns: our decision, plus the raw AI evidence behind it."""

    decision: TriageDecision
    evaluation: TicketEvaluation
