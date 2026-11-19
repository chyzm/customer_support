from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.decision.policy import DecisionPolicy
from app.services.jev import TicketEvaluator


def get_evaluator(request: Request) -> TicketEvaluator:
    """FastAPI dependency. The evaluator is built once at startup (see main.py).

    Routes ask for `Depends(get_evaluator)` and never construct a client
    themselves. Tests can replace it with `app.dependency_overrides`.
    """
    return request.app.state.evaluator


def get_policy(request: Request) -> DecisionPolicy:
    """The active decision policy. Overridable the same way as the evaluator."""
    return request.app.state.policy


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One database session per request, closed automatically afterwards."""
    async with request.app.state.session_factory() as session:
        yield session
