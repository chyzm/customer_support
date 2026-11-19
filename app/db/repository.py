"""Database access only. No business rules here; those live in services/ticket_service.py."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Ticket


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
