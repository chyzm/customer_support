from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_evaluator, get_policy, get_session
from app.db import repository
from app.decision.policy import DecisionPolicy
from app.schemas.decision import Priority
from app.schemas.records import (
    ReviewRequest,
    StatusUpdate,
    TicketDetail,
    TicketList,
    TicketStatus,
    TicketSummary,
    TriageState,
)
from app.schemas.ticket import TicketRequest
from app.services import ticket_service
from app.services.jev import TicketEvaluator

router = APIRouter(prefix="/api/v1/tickets", tags=["Tickets"])


@router.post(
    "",
    response_model=TicketDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a ticket",
    description=(
        "Saves the ticket first, then triages it. If the AI provider is down the "
        "ticket is still saved with `triage_state: failed`; retry with "
        "`POST /tickets/{id}/triage`."
    ),
)
async def create_ticket(
    body: TicketRequest,
    session: AsyncSession = Depends(get_session),
    evaluator: TicketEvaluator = Depends(get_evaluator),
    policy: DecisionPolicy = Depends(get_policy),
) -> TicketDetail:
    ticket = await ticket_service.create_ticket(
        session, evaluator, policy, subject=body.subject, message=body.message
    )
    return ticket_service.build_detail(ticket)


@router.get(
    "",
    response_model=TicketList,
    summary="List tickets (work-queue order)",
    description="Most important first (P1..P4), un-triaged last, then oldest first.",
)
async def list_tickets(
    session: AsyncSession = Depends(get_session),
    status_: TicketStatus | None = Query(None, alias="status"),
    queue: str | None = None,
    priority: Priority | None = None,
    needs_review: bool | None = None,
    triage_state: TriageState | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> TicketList:
    rows, total = await repository.list_tickets(
        session,
        status=status_.value if status_ else None,
        queue=queue,
        priority=priority.value if priority else None,
        needs_review=needs_review,
        triage_state=triage_state.value if triage_state else None,
        limit=limit,
        offset=offset,
    )
    return TicketList(
        items=[TicketSummary.model_validate(r, from_attributes=True) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{ticket_id}", response_model=TicketDetail, summary="Get one ticket with its AI evidence")
async def get_ticket(ticket_id: int, session: AsyncSession = Depends(get_session)) -> TicketDetail:
    return ticket_service.build_detail(await ticket_service.require_ticket(session, ticket_id))


@router.post(
    "/{ticket_id}/triage",
    response_model=TicketDetail,
    summary="Retry triage for a ticket that is pending or failed",
)
async def retry_triage(
    ticket_id: int,
    session: AsyncSession = Depends(get_session),
    evaluator: TicketEvaluator = Depends(get_evaluator),
    policy: DecisionPolicy = Depends(get_policy),
) -> TicketDetail:
    ticket = await ticket_service.run_triage(session, evaluator, policy, ticket_id)
    return ticket_service.build_detail(ticket)


@router.post(
    "/{ticket_id}/review",
    response_model=TicketDetail,
    summary="Confirm or correct the AI decision",
    description="Send only `reviewer` to confirm. Add queue / priority / escalate to correct.",
)
async def review_ticket(
    ticket_id: int,
    body: ReviewRequest,
    session: AsyncSession = Depends(get_session),
    policy: DecisionPolicy = Depends(get_policy),
) -> TicketDetail:
    ticket = await ticket_service.record_review(session, policy, ticket_id, body)
    return ticket_service.build_detail(ticket)


@router.patch("/{ticket_id}/status", response_model=TicketDetail, summary="Move a ticket through its lifecycle")
async def update_status(
    ticket_id: int,
    body: StatusUpdate,
    session: AsyncSession = Depends(get_session),
) -> TicketDetail:
    ticket = await ticket_service.change_status(session, ticket_id, body.status, body.note)
    return ticket_service.build_detail(ticket)
