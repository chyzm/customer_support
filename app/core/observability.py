"""Request correlation and safe JSON logging."""

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from fastapi import Request, Response

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_LOG_FIELDS = (
    "event",
    "request_id",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "client_id",
    "attempt",
    "max_attempts",
    "delay_seconds",
    "provider_status",
    "error_type",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_context.get()),
        }
        for field in _LOG_FIELDS:
            if field != "request_id" and hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_logging(level: str) -> None:
    """Configure only the application logger; leave Uvicorn's logging alone."""
    logger = logging.getLogger("app")
    logger.handlers.clear()  # lifespan runs once per TestClient in tests
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def select_request_id(value: str | None) -> str:
    """Accept a safe caller ID or generate one. Never reflect arbitrary headers."""
    if value and _SAFE_REQUEST_ID.fullmatch(value):
        return value
    return str(uuid4())


async def request_observability_middleware(request: Request, call_next) -> Response:
    request_id = select_request_id(request.headers.get("X-Request-ID"))
    request.state.request_id = request_id
    token = request_id_context.set(request_id)
    started = perf_counter()
    status_code = 500
    logger = logging.getLogger("app.http")

    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception:
        # Starlette's outer error handler emits one safe application_error event
        # and builds the generic 500 response. Avoid logging the same failure twice.
        raise
    finally:
        duration_ms = round((perf_counter() - started) * 1000, 2)
        logger.info(
            "Request completed",
            extra={
                "event": "request_completed",
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "client_id": getattr(request.state, "api_client_id", "unknown"),
            },
        )
        request_id_context.reset(token)
