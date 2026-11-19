from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.schemas.records import TicketStatus, TriageState


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """SQLite has no timezone-aware type and silently drops tzinfo.

    We store naive UTC and re-attach UTC on the way out, so application code
    only ever sees timezone-aware datetimes.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Refusing to store a naive datetime; use timezone-aware UTC.")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


class Ticket(Base):
    """A customer ticket and its CURRENT state.

    `queue`, `priority`, `escalated` and `needs_review` are the current effective
    values, copied from the latest decision or the latest human review. They are
    denormalized on purpose so agent queues can be filtered and sorted with a
    simple indexed query. The full history lives in the child tables.
    """

    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(20), default=TicketStatus.OPEN.value, index=True)
    triage_state: Mapped[str] = mapped_column(String(20), default=TriageState.PENDING.value, index=True)
    triage_error: Mapped[str | None] = mapped_column(String(300))

    queue: Mapped[str | None] = mapped_column(String(50), index=True)
    priority: Mapped[str | None] = mapped_column(String(2), index=True)
    escalated: Mapped[bool] = mapped_column(default=False)
    handling: Mapped[str | None] = mapped_column(String(20))
    needs_review: Mapped[bool] = mapped_column(default=False, index=True)

    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    evaluations: Mapped[list["EvaluationRecord"]] = relationship(
        back_populates="ticket", order_by="EvaluationRecord.id", cascade="all, delete-orphan"
    )
    decisions: Mapped[list["DecisionRecord"]] = relationship(
        back_populates="ticket", order_by="DecisionRecord.id", cascade="all, delete-orphan"
    )
    reviews: Mapped[list["ReviewRecord"]] = relationship(
        back_populates="ticket", order_by="ReviewRecord.id", cascade="all, delete-orphan"
    )


class EvaluationRecord(Base):
    """What Jev said, stored verbatim. Append-only: never edited after insert."""

    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    model: Mapped[str] = mapped_column(String(50))  # e.g. "jev-1.14.0": needed to judge threshold drift
    payload: Mapped[dict] = mapped_column(JSON)  # the full TicketEvaluation
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="evaluations")


class DecisionRecord(Base):
    """What OUR engine decided from an evaluation, under a specific policy version."""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    evaluation_id: Mapped[int] = mapped_column(ForeignKey("evaluations.id"))
    policy_version: Mapped[str] = mapped_column(String(50))
    queue: Mapped[str] = mapped_column(String(50))
    priority: Mapped[str] = mapped_column(String(2))
    escalate: Mapped[bool]
    handling: Mapped[str] = mapped_column(String(20))
    reasons: Mapped[list] = mapped_column(JSON)
    signals: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="decisions")


class ReviewRecord(Base):
    """A human verdict on a decision. Stores the FINAL values, plus whether the
    reviewer agreed. Together with the decision, each row is a labelled example:
    the training data for calibrating thresholds in Phase 4."""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decisions.id"))
    reviewer: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(10))
    queue: Mapped[str] = mapped_column(String(50))
    priority: Mapped[str] = mapped_column(String(2))
    escalate: Mapped[bool]
    agreed: Mapped[bool]
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="reviews")
