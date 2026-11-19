from fastapi import APIRouter, Depends

from app.api.deps import enforce_rate_limit, get_evaluator, get_policy
from app.decision.engine import decide
from app.decision.policy import DecisionPolicy
from app.schemas.decision import TriageResult
from app.schemas.ticket import TicketRequest
from app.services.jev import TicketEvaluator

router = APIRouter(
    prefix="/api/v1",
    tags=["Ticket Triage"],
    dependencies=[Depends(enforce_rate_limit)],
)


@router.post(
    "/triage",
    response_model=TriageResult,
    summary="Triage a support ticket",
    description=(
        "Asks Jev four questions about the ticket, then applies our decision "
        "policy. `decision` is what to do (queue, priority, escalation, how much "
        "human review). `evaluation` is the raw AI evidence behind it."
    ),
)
async def triage_ticket(
    ticket: TicketRequest,
    evaluator: TicketEvaluator = Depends(get_evaluator),
    policy: DecisionPolicy = Depends(get_policy),
) -> TriageResult:
    evaluation = await evaluator.evaluate_ticket(ticket.subject, ticket.message)
    return TriageResult(decision=decide(evaluation, policy), evaluation=evaluation)


@router.get(
    "/policy",
    response_model=DecisionPolicy,
    summary="Show the active decision thresholds",
)
async def show_policy(policy: DecisionPolicy = Depends(get_policy)) -> DecisionPolicy:
    return policy
