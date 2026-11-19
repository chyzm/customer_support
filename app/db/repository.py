"""Database access only. No business rules here; those live in services/ticket_service.py."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import DecisionRecord, EvaluationRecord, ReviewRecord, Ticket


async def get_ticket(session: AsyncSession, ticket_id: int) -> Ticket | None:
    """Load a ticket with its history in three extra queries (not one per row)."""
    result = await session.execute(
        select(Ticket)
        .where(Ticket.id == ticket_id)
        .options(
            selectinload(Ticket.evaluations),
            selectinload(Ticket.decisions),
            selectinload(Ticket.reviews),
        )
        # We insert child rows by foreign key, so an already-loaded Ticket in this
        # session would keep stale (pre-insert) collections. Always refresh from the DB.
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def list_tickets(
    session: AsyncSession,
    *,
    status: str | None,
    queue: str | None,
    priority: str | None,
    needs_review: bool | None,
    triage_state: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Ticket], int]:
    filters = []
    if status is not None:
        filters.append(Ticket.status == status)
    if queue is not None:
        filters.append(Ticket.queue == queue)
    if priority is not None:
        filters.append(Ticket.priority == priority)
    if needs_review is not None:
        filters.append(Ticket.needs_review == needs_review)
    if triage_state is not None:
        filters.append(Ticket.triage_state == triage_state)

    total = await session.scalar(select(func.count()).select_from(Ticket).where(*filters))

    # Work queue order: most important first ("P1" < "P4" as text), un-triaged
    # tickets last, then oldest first so nothing waits forever.
    rows = await session.scalars(
        select(Ticket)
        .where(*filters)
        .order_by(Ticket.priority.asc().nulls_last(), Ticket.created_at.asc(), Ticket.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total or 0


async def count_grouped(session: AsyncSession, column) -> dict[str, int]:
    """Count non-null values of a Ticket column."""
    rows = await session.execute(
        select(column, func.count()).where(column.is_not(None)).group_by(column)
    )
    return {str(value): count for value, count in rows.all()}


async def analytics_counts(session: AsyncSession) -> dict[str, object]:
    total_tickets = await session.scalar(select(func.count()).select_from(Ticket)) or 0
    decisions = await session.scalar(select(func.count()).select_from(DecisionRecord)) or 0

    # One decision can have multiple audit reviews. Analytics uses only the latest
    # review for each decision so frequently reviewed tickets are not overweighted.
    latest = (
        select(ReviewRecord.decision_id, func.max(ReviewRecord.id).label("review_id"))
        .group_by(ReviewRecord.decision_id)
        .subquery()
    )
    reviewed_decisions = await session.scalar(select(func.count()).select_from(latest)) or 0
    corrected_decisions = await session.scalar(
        select(func.count())
        .select_from(ReviewRecord)
        .join(latest, ReviewRecord.id == latest.c.review_id)
        .where(ReviewRecord.agreed.is_(False))
    ) or 0

    return {
        "total_tickets": total_tickets,
        "status_counts": await count_grouped(session, Ticket.status),
        "triage_state_counts": await count_grouped(session, Ticket.triage_state),
        "priority_counts": await count_grouped(session, Ticket.priority),
        "queue_counts": await count_grouped(session, Ticket.queue),
        "decisions": decisions,
        "reviewed_decisions": reviewed_decisions,
        "corrected_decisions": corrected_decisions,
    }


async def latest_review_labels(
    session: AsyncSession,
    *,
    model: str | None = None,
    policy_version: str | None = None,
) -> list[tuple[ReviewRecord, DecisionRecord, EvaluationRecord]]:
    """Return one (latest) human label per decision, optionally stratified."""
    latest = (
        select(ReviewRecord.decision_id, func.max(ReviewRecord.id).label("review_id"))
        .group_by(ReviewRecord.decision_id)
        .subquery()
    )
    statement = (
        select(ReviewRecord, DecisionRecord, EvaluationRecord)
        .join(latest, ReviewRecord.id == latest.c.review_id)
        .join(DecisionRecord, ReviewRecord.decision_id == DecisionRecord.id)
        .join(EvaluationRecord, DecisionRecord.evaluation_id == EvaluationRecord.id)
        .order_by(ReviewRecord.id)
    )
    if model is not None:
        statement = statement.where(EvaluationRecord.model == model)
    if policy_version is not None:
        statement = statement.where(DecisionRecord.policy_version == policy_version)
    result = await session.execute(statement)
    return list(result.all())
