"""Inbound API-key authentication.

Provider credentials (`TYPESAFE_API_KEY`) and client credentials are separate.
Only SHA-256 digests of inbound secrets remain in this object after startup.
"""

from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest


@dataclass(frozen=True)
class ApiClient:
    client_id: str


class ApiAccessError(Exception):
    code = "api_access_error"
    status_code = 401

    def __init__(self, message: str, *, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.message = message
        self.headers = headers or {}


class ApiAuthenticationError(ApiAccessError):
    code = "invalid_api_key"


class ApiRateLimitError(ApiAccessError):
    code = "rate_limit_exceeded"
    status_code = 429

    def __init__(self, retry_after: int):
        super().__init__(
            "Request limit exceeded. Retry later.",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(retry_after),
            },
        )
        self.retry_after = retry_after


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


class ApiKeyAuthenticator:
    """Maps a presented secret to a safe client ID.

    Digest comparison means request processing never needs stored plaintext keys.
    `compare_digest` verifies the final digest without content-dependent string
    comparison. Authentication can be disabled only for mock/local mode.
    """

    def __init__(self, enabled: bool, keys: dict[str, str]):
        self.enabled = enabled
        self._clients = tuple((client_id, _digest(secret)) for client_id, secret in keys.items())

    def authenticate(self, presented_key: str | None) -> ApiClient:
        if not self.enabled:
            return ApiClient(client_id="anonymous")
        if not presented_key:
            raise ApiAuthenticationError(
                "A valid X-API-Key header is required.",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        candidate = _digest(presented_key)
        for client_id, expected in self._clients:
            if compare_digest(candidate, expected):
                return ApiClient(client_id=client_id)

        # The generic response intentionally does not reveal whether a key exists.
        raise ApiAuthenticationError(
            "A valid X-API-Key header is required.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
