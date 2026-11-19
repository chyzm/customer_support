"""Domain errors for the Jev integration.

The service layer raises these instead of leaking httpx exceptions. The API
layer then maps them to HTTP responses, and no HTTP-client detail reaches callers.
"""


class JevError(Exception):
    """Base class for every Jev integration failure."""

    def __init__(self, message: str, *, provider_status: int | None = None):
        super().__init__(message)
        self.message = message
        self.provider_status = provider_status


class JevAuthError(JevError):
    """401: the API key is missing or invalid. Our configuration problem, not the client's."""


class JevRequestError(JevError):
    """422 or other 4xx: our request body was rejected. This is a bug in our rubric or payload."""


class JevUnavailableError(JevError):
    """429 (rate limited), 529 (overloaded), timeouts or network failures. Retryable."""


class JevUpstreamError(JevError):
    """Other 5xx from the provider."""


class JevResponseError(JevError):
    """The provider answered 200 but the body did not match the shape we expect."""
