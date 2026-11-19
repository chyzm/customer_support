from contextlib import asynccontextmanager
import logging

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.analytics import router as analytics_router
from app.api.routes import router
from app.api.tickets import router as tickets_router
from app.core.config import get_settings
from app.core.observability import configure_logging, request_observability_middleware
from app.core.rate_limit import InMemoryRateLimiter
from app.core.security import ApiAccessError, ApiKeyAuthenticator
from app.db.session import create_engine, create_session_factory, init_db
from app.decision.policy import DEFAULT_POLICY
from app.services.errors import JevAuthError, JevError, JevUnavailableError
from app.services.jev import JevClient
from app.services.mock_jev import MockJevClient
from app.services.ticket_service import (
    ConflictError,
    InvalidReviewError,
    TicketNotFoundError,
    TicketServiceError,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build long-lived resources once and release them at shutdown."""
    settings = get_settings()
    configure_logging(settings.log_level)
    app.state.settings = settings
    app.state.policy = DEFAULT_POLICY
    app.state.authenticator = ApiKeyAuthenticator(
        settings.api_auth_enabled,
        settings.parsed_client_api_keys(),
    )
    app.state.rate_limiter = InMemoryRateLimiter(
        settings.rate_limit_requests,
        settings.rate_limit_window_seconds,
    )

    engine = create_engine(settings.database_url)
    await init_db(engine)
    app.state.session_factory = create_session_factory(engine)

    http: httpx.AsyncClient | None = None
    if settings.jev_mode == "live":
        http = httpx.AsyncClient()
        app.state.evaluator = JevClient(settings, http)
    else:
        app.state.evaluator = MockJevClient()

    try:
        yield
    finally:
        if http is not None:
            await http.aclose()
        await engine.dispose()


app = FastAPI(
    title="AI-Powered Customer Support Triage & Resolution API",
    description="Confidence-gated ticket routing with persistence and human review.",
    version="0.4.0",
    lifespan=lifespan,
)
app.middleware("http")(request_observability_middleware)


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a stable 500 without echoing exception text or customer data."""
    logging.getLogger("app.http").error(
        "Unhandled application error",
        extra={
            "event": "application_error",
            "request_id": request.state.request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": 500,
            "error_type": type(exc).__name__,
        },
    )
    return JSONResponse(
        status_code=500,
        headers={"X-Request-ID": request.state.request_id},
        content={"error": {"code": "internal_error", "message": "An unexpected error occurred."}},
    )


@app.exception_handler(ApiAccessError)
async def api_access_error_handler(request: Request, exc: ApiAccessError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(JevError)
async def jev_error_handler(request: Request, exc: JevError) -> JSONResponse:
    """Translate provider failures without leaking keys or ticket text."""
    status = 503 if isinstance(exc, JevUnavailableError) else 502
    code = "ai_provider_unavailable" if status == 503 else "ai_provider_error"
    if isinstance(exc, JevAuthError):
        code = "ai_provider_misconfigured"
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": exc.message,
                "provider_status": exc.provider_status,
            }
        },
    )


_TICKET_ERROR_STATUS = {
    TicketNotFoundError: 404,
    ConflictError: 409,
    InvalidReviewError: 422,
}


@app.exception_handler(TicketServiceError)
async def ticket_error_handler(request: Request, exc: TicketServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=_TICKET_ERROR_STATUS.get(type(exc), 400),
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.get("/health", tags=["Meta"])
async def health_check(request: Request):
    settings = request.app.state.settings
    return {
        "status": "healthy",
        "application": "AI-Powered Customer Support Triage & Resolution API",
        "version": app.version,
        "jev_mode": settings.jev_mode,
        "jev_model": settings.jev_model if settings.jev_mode == "live" else "mock",
        "api_auth_enabled": settings.api_auth_enabled,
    }


app.include_router(router)
app.include_router(tickets_router)
app.include_router(analytics_router)
