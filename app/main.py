from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.api.tickets import router as tickets_router
from app.core.config import get_settings
from app.db.session import create_engine, create_session_factory, init_db
from app.decision.policy import DEFAULT_POLICY
from app.services.errors import (
    JevAuthError,
    JevError,
    JevUnavailableError,
)
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
    """Build long-lived resources once at startup and release them at shutdown."""
    settings = get_settings()
    app.state.settings = settings
    app.state.policy = DEFAULT_POLICY

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
    title="Jev Support Intelligence",
    description="AI-powered support ticket classification and decision intelligence using Jev.",
    version="0.3.0",
    lifespan=lifespan,
)


@app.exception_handler(JevError)
async def jev_error_handler(request: Request, exc: JevError) -> JSONResponse:
    """Translate integration failures into a stable error shape.

    The message is deliberately generic. Provider details and our API key stay
    in server logs, never in responses.
    """
    # 503 tells clients "try again later". Everything else is a bad gateway:
    # our upstream dependency failed, and the caller cannot fix it.
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
    """Same error envelope as the AI errors, so clients parse one shape."""
    return JSONResponse(
        status_code=_TICKET_ERROR_STATUS.get(type(exc), 400),
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.get("/health", tags=["Meta"])
async def health_check(request: Request):
    settings = request.app.state.settings
    return {
        "status": "healthy",
        "application": "Jev Support Intelligence",
        "jev_mode": settings.jev_mode,
        "jev_model": settings.jev_model if settings.jev_mode == "live" else "mock",
    }


app.include_router(router)
app.include_router(tickets_router)
