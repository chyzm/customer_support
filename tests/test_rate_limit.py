from app.core.rate_limit import InMemoryRateLimiter
from app.core.security import ApiKeyAuthenticator


async def test_sliding_window_limit_and_reset():
    now = [100.0]
    limiter = InMemoryRateLimiter(2, 10, clock=lambda: now[0])

    first = await limiter.check("a")
    second = await limiter.check("a")
    blocked = await limiter.check("a")
    assert (first.allowed, first.remaining) == (True, 1)
    assert (second.allowed, second.remaining) == (True, 0)
    assert blocked.allowed is False
    assert blocked.reset_after == 10

    now[0] = 110.0  # oldest events fall outside the rolling window
    reset = await limiter.check("a")
    assert (reset.allowed, reset.remaining) == (True, 1)


async def test_clients_have_independent_quotas():
    limiter = InMemoryRateLimiter(1, 60, clock=lambda: 0.0)
    assert (await limiter.check("a")).allowed is True
    assert (await limiter.check("a")).allowed is False
    assert (await limiter.check("b")).allowed is True


def test_api_limit_returns_headers_and_request_id(client):
    client.app.state.rate_limiter = InMemoryRateLimiter(2, 60)

    first = client.get("/api/v1/policy")
    second = client.get("/api/v1/policy")
    blocked = client.get("/api/v1/policy")

    assert first.headers["x-ratelimit-remaining"] == "1"
    assert second.headers["x-ratelimit-remaining"] == "0"
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limit_exceeded"
    assert int(blocked.headers["retry-after"]) >= 1
    assert blocked.headers["x-request-id"]
    assert client.get("/health").status_code == 200  # public health does not consume API quota


def test_api_quotas_are_per_authenticated_client(client):
    client.app.state.authenticator = ApiKeyAuthenticator(
        True, {"partner-a": "secret-a", "partner-b": "secret-b"}
    )
    client.app.state.rate_limiter = InMemoryRateLimiter(1, 60)

    assert client.get("/api/v1/policy", headers={"X-API-Key": "secret-a"}).status_code == 200
    assert client.get("/api/v1/policy", headers={"X-API-Key": "secret-a"}).status_code == 429
    assert client.get("/api/v1/policy", headers={"X-API-Key": "secret-b"}).status_code == 200
