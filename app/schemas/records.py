"""API shapes for stored tickets (what clients send and receive)."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.decision import Priority, TriageDecision
from app.schemas.evaluation import TicketEvaluation


class TicketStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"


class TriageState(str, Enum):
    PENDING = "pending"  # saved, AI not run yet
    TRIAGED = "triaged"
    FAILED = "failed"  # saved, but the AI call failed. Safe to retry.


class ReviewAction(str, Enum):
    CONFIRM = "confirm"  # the reviewer agreed with the AI decision
    CORRECT = "correct"  # the reviewer changed something


class TicketSummary(BaseModel):
    """One row in a ticket list."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    subject: str
    status: TicketStatus
    triage_state: TriageState
    queue: str | None
    priority: Priority | None
    escalated: bool
    needs_review: bool
    created_at: datetime
    updated_at: datetime


class ReviewRequest(BaseModel):
    """A person's verdict on the AI decision.

    Send nothing but `reviewer` to confirm the current effective decision. Send
    any of queue / priority / escalate to correct them. Fields left out preserve
    the ticket's current values, including an earlier human correction.
    """

    reviewer: str = Field(min_length=1, max_length=100)
    queue: str | None = None
    priority: Priority | None = None
    escalate: bool | None = None
    note: str | None = Field(default=None, max_length=1000)


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    decision_id: int
    reviewer: str
    action: ReviewAction
    queue: str
    priority: Priority
    escalate: bool
    agreed: bool
    note: str | None
    created_at: datetime


class StatusUpdate(BaseModel):
    status: TicketStatus
    note: str | None = Field(default=None, max_length=2000)


class TicketDetail(TicketSummary):
    message: str
    resolution_note: str | None
    resolved_at: datetime | None
    triage_error: str | None
    evaluation: TicketEvaluation | None  # latest AI evidence
    decision: TriageDecision | None  # latest AI decision
    reviews: list[ReviewOut]


class TicketList(BaseModel):
    items: list[TicketSummary]
    total: int
    limit: int
    offset: int
