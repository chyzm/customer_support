import asyncio
import logging
from collections.abc import Awaitable, Callable

from typing import Protocol

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.evaluation import TicketEvaluation
from app.services import rubric
from app.services.errors import (
    JevAuthError,
    JevError,
    JevRequestError,
    JevResponseError,
    JevUnavailableError,
    JevUpstreamError,
)

logger = logging.getLogger("app.jev")
Sleep = Callable[[float], Awaitable[None]]
_RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}


class TicketEvaluator(Protocol):
    """Structural interface implemented by live, mock, and test evaluators."""

    async def evaluate_ticket(self, subject: str, message: str) -> TicketEvaluation: ...


class JevClient:
    """Async TypeSafe System One client with bounded retries.

    The shared AsyncClient reuses connections. `jev_max_attempts` includes the
    first call, so the upper latency bound is approximately attempts × timeout
    plus backoff. A timeout can occur after the provider accepted a request;
    retries may therefore duplicate provider work even though local evaluation
    has no side effects.
    """

    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient,
        *,
        sleep: Sleep = asyncio.sleep,
    ):
        if settings.typesafe_api_key is None:
            raise ValueError("JevClient requires TYPESAFE_API_KEY")
        self._settings = settings
        self._http = http
        self._sleep = sleep

    async def evaluate_ticket(self, subject: str, message: str) -> TicketEvaluation:
        payload = {
            "model": self._settings.jev_model,
            "state": rubric.build_state(subject, message),
            "questions": rubric.build_questions(),
        }
        headers = {
            "Authorization": f"Bearer {self._settings.typesafe_api_key.get_secret_value()}",
        }

        for attempt in range(1, self._settings.jev_max_attempts + 1):
            response: httpx.Response | None = None
            try:
                response = await self._http.post(
                    self._settings.jev_api_url,
                    json=payload,
                    headers=headers,
                    timeout=self._settings.jev_timeout_seconds,
                )
                self._raise_for_status(response)
            except httpx.TimeoutException as exc:
                error: JevError = JevUnavailableError("Jev request timed out")
                error.__cause__ = exc
            except httpx.TransportError as exc:
                error = JevUnavailableError("Could not reach Jev")
                error.__cause__ = exc
            except JevError as exc:
                error = exc
            else:
                # A schema-invalid 200 response is not retried. Retrying cannot
                # repair a contract mismatch and could multiply provider cost.
                return self._parse(response)

            retryable = response is None or response.status_code in _RETRYABLE_STATUS
            if not retryable or attempt == self._settings.jev_max_attempts:
                raise error

            delay = self._retry_delay(attempt, response)
            logger.warning(
                "Retrying Jev request",
                extra={
                    "event": "jev_retry",
                    "attempt": attempt,
                    "max_attempts": self._settings.jev_max_attempts,
                    "delay_seconds": delay,
                    "provider_status": response.status_code if response is not None else None,
                    "error_type": type(error).__name__,
                },
            )
            await self._sleep(delay)

        raise AssertionError("retry loop exited unexpectedly")  # pragma: no cover

    def _retry_delay(self, failed_attempt: int, response: httpx.Response | None) -> float:
        exponential = self._settings.jev_retry_base_seconds * (2 ** (failed_attempt - 1))
        delay = exponential
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    pass  # HTTP-date and malformed forms fall back to exponential delay.
        return round(min(delay, self._settings.jev_retry_max_seconds), 3)

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        if status < 400:
            return
        # Never include headers or bodies here: they hold credentials and ticket text.
        if status == 401:
            raise JevAuthError("Jev rejected the API key", provider_status=status)
        if status in (429, 529):
            raise JevUnavailableError("Jev is rate limiting or overloaded", provider_status=status)
        if 400 <= status < 500:
            raise JevRequestError(f"Jev rejected the request ({status})", provider_status=status)
        raise JevUpstreamError(f"Jev server error ({status})", provider_status=status)

    @staticmethod
    def _parse(response: httpx.Response) -> TicketEvaluation:
        try:
            body = response.json()
            answers = body["answers"]
            return TicketEvaluation(
                model=body["model"],
                usage=body.get("usage", {}),
                **{key: answers[key] for key in rubric.QUESTION_KEYS},
            )
        except (ValueError, KeyError, TypeError, ValidationError) as exc:
            raise JevResponseError("Jev returned an unexpected response shape") from exc
