from typing import Protocol

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.evaluation import TicketEvaluation
from app.services import rubric
from app.services.errors import (
    JevAuthError,
    JevRequestError,
    JevResponseError,
    JevUnavailableError,
    JevUpstreamError,
)


class TicketEvaluator(Protocol):
    """Anything that can evaluate a ticket.

    The API layer depends on this interface, not on a concrete class. That is
    what lets us swap the live client for the mock one, or for a test double.
    """

    async def evaluate_ticket(self, subject: str, message: str) -> TicketEvaluation: ...


class JevClient:
    """Calls TypeSafe's System One endpoint over HTTP.

    We use httpx.AsyncClient because FastAPI runs on an event loop. A blocking
    client such as `requests` would stall every other request while waiting
    on the network. The AsyncClient is created once at app startup and shared,
    so TCP/TLS connections are reused instead of re-established per ticket.
    """

    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        if settings.typesafe_api_key is None:
            raise ValueError("JevClient requires TYPESAFE_API_KEY")
        self._settings = settings
        self._http = http

    async def evaluate_ticket(self, subject: str, message: str) -> TicketEvaluation:
        payload = {
            "model": self._settings.jev_model,
            "state": rubric.build_state(subject, message),
            "questions": rubric.build_questions(),
        }
        # The key is unwrapped only here, at the moment it is needed.
        headers = {
            "Authorization": f"Bearer {self._settings.typesafe_api_key.get_secret_value()}",
        }

        try:
            response = await self._http.post(
                self._settings.jev_api_url,
                json=payload,
                headers=headers,
                timeout=self._settings.jev_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise JevUnavailableError("Jev request timed out") from exc
        except httpx.TransportError as exc:
            raise JevUnavailableError("Could not reach Jev") from exc

        self._raise_for_status(response)
        return self._parse(response)

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        if status < 400:
            return
        # Never include the request headers or body in the message: they hold the key and ticket text.
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
