from collections.abc import AsyncIterator

from fastapi import Depends, Request, Response, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import ApiClient, ApiRateLimitError
from app.decision.policy import DecisionPolicy
from app.services.jev import TicketEvaluator

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_evaluator(request: Request) -> TicketEvaluator:
    return request.app.state.evaluator


def get_policy(request: Request) -> DecisionPolicy:
    return request.app.state.policy


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One database session per request, closed automatically afterwards."""
    async with request.app.state.session_factory() as session:
        yield session


async def require_api_client(
    request: Request,
    api_key: str | None = Security(_api_key_header),
) -> ApiClient:
    """Authenticate an inbound caller and expose only its non-secret client ID."""
    client = request.app.state.authenticator.authenticate(api_key)
    request.state.api_client_id = client.client_id
    return client


async def enforce_rate_limit(
    request: Request,
    response: Response,
    client: ApiClient = Depends(require_api_client),
) -> None:
    """Apply one process-local quota to all `/api/v1` operations."""
    result = await request.app.state.rate_limiter.check(client.client_id)
    if not result.allowed:
        raise ApiRateLimitError(result.reset_after)

    response.headers["X-RateLimit-Limit"] = str(result.limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    response.headers["X-RateLimit-Reset"] = str(result.reset_after)
