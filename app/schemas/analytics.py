from datetime import datetime

from pydantic import BaseModel, Field


class AnalyticsSummary(BaseModel):
    total_tickets: int
    status_counts: dict[str, int]
    triage_state_counts: dict[str, int]
    priority_counts: dict[str, int]
    queue_counts: dict[str, int]
    decisions: int
    reviewed_decisions: int
    corrected_decisions: int
    review_coverage: float | None
    agreement_rate: float | None


class ConfidenceBucket(BaseModel):
    lower_bound: float
    upper_bound: float
    sample_count: int
    average_confidence: float
    accuracy: float


class SignalCalibration(BaseModel):
    signal: str
    sample_count: int
    accuracy: float | None
    brier_score: float | None = None
    buckets: list[ConfidenceBucket]


class CalibrationReport(BaseModel):
    sample_count: int
    models: list[str]
    policy_versions: list[str]
    category_routing: SignalCalibration
    final_priority: SignalCalibration
    escalation: SignalCalibration
    caveats: list[str]


class CalibrationLabel(BaseModel):
    """Sanitized latest human label for one AI decision. No customer or reviewer PII."""

    ticket_id: int
    decision_id: int
    reviewed_at: datetime
    model: str
    policy_version: str
    ai_queue: str
    human_queue: str
    ai_priority: str
    human_priority: str
    ai_escalate: bool
    human_escalate: bool
    category_confidence: float = Field(ge=0, le=1)
    urgency_confidence: float = Field(ge=0, le=1)
    escalation_probability: float = Field(ge=0, le=1)
