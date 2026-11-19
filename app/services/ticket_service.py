"""Ticket workflow: create, triage, review, change status.

Framework-free: it raises domain errors and the API layer maps them to HTTP.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repository
from app.db.models import DecisionRecord, EvaluationRecord, ReviewRecord, Ticket, utcnow
from app.decision.engine import decide
from app.decision.policy import DecisionPolicy
from app.schemas.decision import Handling, Priority, TriageDecision
from app.schemas.evaluation import TicketEvaluation
from app.schemas.records import (
    ReviewAction,
    ReviewOut,
    ReviewRequest,
    TicketDetail,
    TicketStatus,
    TriageState,
)
from app.services.errors import JevError
from app.services.jev import TicketEvaluator

# status -> statuses it may move to
ALLOWED_TRANSITIONS: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.OPEN: {TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED},
    TicketStatus.IN_PROGRESS: {TicketStatus.OPEN, TicketStatus.RESOLVED},
    TicketStatus.RESOLVED: {TicketStatus.OPEN},  # reopen
}


class TicketServiceError(Exception):
    code = "ticket_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class TicketNotFoundError(TicketServiceError):
    code = "ticket_not_found"


class ConflictError(TicketServiceError):
    """The request is valid, but not allowed in the ticket's current state."""

    code = "conflict"


class InvalidReviewError(TicketServiceError):
    code = "invalid_review"


async def create_ticket(
    session: AsyncSession,
    evaluator: TicketEvaluator,
    policy: DecisionPolicy,
    *,
    subject: str,
    message: str,
) -> Ticket:
    ticket = Ticket(subject=subject, message=message)
    session.add(ticket)
    # Commit BEFORE calling the AI. The customer's ticket is safe even if Jev is
    # down, and no database lock is held during a slow network call.
    await session.commit()

    await run_triage(session, evaluator, policy, ticket.id)
    return await require_ticket(session, ticket.id)


async def run_triage(
    session: AsyncSession, evaluator: TicketEvaluator, policy: DecisionPolicy, ticket_id: int
) -> Ticket:
    ticket = await require_ticket(session, ticket_id)
    if ticket.triage_state == TriageState.TRIAGED.value:
        raise ConflictError("Ticket is already triaged.")

    try:
        evaluation = await evaluator.evaluate_ticket(ticket.subject, ticket.message)
    except JevError as exc:
        ticket.triage_state = TriageState.FAILED.value
        ticket.triage_error = exc.message[:300]  # our generic message, never provider detail
        await session.commit()
        return ticket

    decision = decide(evaluation, policy)

    evaluation_row = EvaluationRecord(
        ticket_id=ticket.id, model=evaluation.model, payload=evaluation.model_dump(mode="json")
    )
    session.add(evaluation_row)
    await session.flush()  # assigns evaluation_row.id, needed by the decision row

    session.add(DecisionRecord(
        ticket_id=ticket.id,
        evaluation_id=evaluation_row.id,
        policy_version=decision.policy_version,
        queue=decision.queue,
        priority=decision.priority.value,
        escalate=decision.escalate,
        handling=decision.handling.value,
        reasons=[r.model_dump() for r in decision.reasons],
        signals=decision.signals.model_dump(),
    ))

    ticket.triage_state = TriageState.TRIAGED.value
    ticket.triage_error = None
    ticket.queue = decision.queue
    ticket.priority = decision.priority.value
    ticket.escalated = decision.escalate
    ticket.handling = decision.handling.value
    ticket.needs_review = decision.handling != Handling.AUTO_ROUTE
    await session.commit()
    return await require_ticket(session, ticket.id)


async def record_review(
    session: AsyncSession, policy: DecisionPolicy, ticket_id: int, review: ReviewRequest
) -> Ticket:
    ticket = await require_ticket(session, ticket_id)
    if not ticket.decisions:
        raise ConflictError("Ticket has no AI decision to review yet.")
    decision = ticket.decisions[-1]

    valid_queues = set(policy.queues.values()) | {policy.fallback_queue}
    if review.queue is not None and review.queue not in valid_queues:
        raise InvalidReviewError(f"Unknown queue '{review.queue}'. Valid: {sorted(valid_queues)}")

    # Unspecified fields keep the AI's value, so each row holds the complete final answer.
    final_queue = review.queue if review.queue is not None else decision.queue
    final_priority = review.priority.value if review.priority is not None else decision.priority
    final_escalate = review.escalate if review.escalate is not None else decision.escalate

    agreed = (
        final_queue == decision.queue
        and final_priority == decision.priority
        and final_escalate == decision.escalate
    )

    session.add(ReviewRecord(
        ticket_id=ticket.id,
        decision_id=decision.id,
        reviewer=review.reviewer,
        action=(ReviewAction.CONFIRM if agreed else ReviewAction.CORRECT).value,
        queue=final_queue,
        priority=final_priority,
        escalate=final_escalate,
        agreed=agreed,
        note=review.note,
    ))

    ticket.queue = final_queue
    ticket.priority = final_priority
    ticket.escalated = final_escalate
    ticket.needs_review = False
    await session.commit()
    return await require_ticket(session, ticket.id)


async def change_status(
    session: AsyncSession, ticket_id: int, new_status: TicketStatus, note: str | None
) -> Ticket:
    ticket = await require_ticket(session, ticket_id)
    current = TicketStatus(ticket.status)
    if new_status not in ALLOWED_TRANSITIONS[current]:
        allowed = sorted(s.value for s in ALLOWED_TRANSITIONS[current])
        raise ConflictError(f"Cannot move a ticket from '{current.value}' to '{new_status.value}'. Allowed: {allowed}")

    ticket.status = new_status.value
    if new_status == TicketStatus.RESOLVED:
        ticket.resolved_at = utcnow()
        ticket.resolution_note = note
    elif current == TicketStatus.RESOLVED:  # reopened
        ticket.resolved_at = None
        ticket.resolution_note = None
    await session.commit()
    return await require_ticket(session, ticket.id)


async def require_ticket(session: AsyncSession, ticket_id: int) -> Ticket:
    ticket = await repository.get_ticket(session, ticket_id)
    if ticket is None:
        raise TicketNotFoundError(f"Ticket {ticket_id} not found.")
    return ticket


def build_detail(ticket: Ticket) -> TicketDetail:
    """Assemble the API view from a stored ticket (latest evaluation and decision)."""
    evaluation = TicketEvaluation.model_validate(ticket.evaluations[-1].payload) if ticket.evaluations else None

    decision = None
    if ticket.decisions:
        row = ticket.decisions[-1]
        decision = TriageDecision(
            queue=row.queue,
            priority=Priority(row.priority),
            escalate=row.escalate,
            handling=Handling(row.handling),
            reasons=row.reasons,
            signals=row.signals,
            policy_version=row.policy_version,
        )

    return TicketDetail(
        id=ticket.id,
        subject=ticket.subject,
        status=TicketStatus(ticket.status),
        triage_state=TriageState(ticket.triage_state),
        queue=ticket.queue,
        priority=Priority(ticket.priority) if ticket.priority else None,
        escalated=ticket.escalated,
        needs_review=ticket.needs_review,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        message=ticket.message,
        resolution_note=ticket.resolution_note,
        resolved_at=ticket.resolved_at,
        triage_error=ticket.triage_error,
        evaluation=evaluation,
        decision=decision,
        reviews=[ReviewOut.model_validate(r, from_attributes=True) for r in ticket.reviews],
    )
