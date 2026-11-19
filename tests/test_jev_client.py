import json

import httpx
import pytest

from app.core.config import Settings
from app.services.errors import (
    JevAuthError,
    JevRequestError,
    JevResponseError,
    JevUnavailableError,
    JevUpstreamError,
)
from app.services.jev import JevClient

FAKE_KEY = "sk-test-secret"

GOOD_BODY = {
    "model": "jev-1.14.0",
    "answers": {
        "category": {
            "type": "choice",
            "choice": "billing",
            "confidence": 0.8,
            "probabilities": {"billing": 0.9, "technical": 0.1},
        },
        "urgency": {
            "type": "score",
            "score": 2.8,
            "confidence": 0.9,
            "legend": {"0": "a", "1": "b", "2": "c", "3": "d"},
            "probabilities": {"0": 0.0, "1": 0.0, "2": 0.2, "3": 0.8},
        },
        "sentiment": {
            "type": "score",
            "score": 1.0,
            "confidence": 1.0,
            "legend": {"0": "a", "1": "b"},
            "probabilities": {"0": 0.0, "1": 1.0},
        },
        "needs_escalation": {"type": "noul", "noul": 0.93},
    },
    "usage": {"input_tokens": 392, "output_tokens": 65},
}


def make_client(handler) -> JevClient:
    settings = Settings(
        _env_file=None,
        jev_mode="live",
        typesafe_api_key=FAKE_KEY,
        api_auth_enabled=True,
        client_api_keys="test-client:inbound-test-key",
        jev_retry_base_seconds=0,
        jev_retry_max_seconds=0,
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return JevClient(settings, http)


async def test_sends_expected_request_and_parses_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=GOOD_BODY)

    result = await make_client(handler).evaluate_ticket("Payment failure", "Payments are failing for all users.")

    assert seen["auth"] == f"Bearer {FAKE_KEY}"
    assert seen["url"] == "https://api.typesafe.ai/v1/systemone"
    assert seen["body"]["model"] == "jev-1.14.0"
    assert seen["body"]["state"] == {
        "subject": "Payment failure",
        "message": "Payments are failing for all users.",
    }
    assert set(seen["body"]["questions"]) == {"category", "urgency", "sentiment", "needs_escalation"}
    assert seen["body"]["questions"]["category"]["type"] == "choice"
    assert seen["body"]["questions"]["urgency"]["type"] == "score"
    assert seen["body"]["questions"]["needs_escalation"]["type"] == "noul"

    assert result.model == "jev-1.14.0"
    assert result.category.choice == "billing"
    assert result.urgency.score == 2.8
    assert result.needs_escalation.noul == 0.93
    assert result.usage.input_tokens == 392


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, JevAuthError),
        (422, JevRequestError),
        (429, JevUnavailableError),
        (529, JevUnavailableError),
        (500, JevUpstreamError),
    ],
)
async def test_status_codes_map_to_domain_errors(status, expected):
    client = make_client(lambda request: httpx.Response(status, json={"detail": "x"}))
    with pytest.raises(expected) as info:
        await client.evaluate_ticket("Subject here", "A long enough message body.")
    assert info.value.provider_status == status
    assert FAKE_KEY not in info.value.message


async def test_timeout_is_unavailable():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(JevUnavailableError):
        await make_client(handler).evaluate_ticket("Subject here", "A long enough message body.")
    assert calls == 3


async def test_missing_answer_is_response_error():
    body = {**GOOD_BODY, "answers": {"category": GOOD_BODY["answers"]["category"]}}
    client = make_client(lambda request: httpx.Response(200, json=body))
    with pytest.raises(JevResponseError):
        await client.evaluate_ticket("Subject here", "A long enough message body.")


async def test_non_json_body_is_response_error():
    client = make_client(lambda request: httpx.Response(200, text="<html>oops</html>"))
    with pytest.raises(JevResponseError):
        await client.evaluate_ticket("Subject here", "A long enough message body.")


async def test_retryable_status_eventually_succeeds():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(429 if calls == 1 else 200, json={} if calls == 1 else GOOD_BODY)

    result = await make_client(handler).evaluate_ticket("Subject here", "A long enough message body.")
    assert result.model == "jev-1.14.0"
    assert calls == 2


async def test_non_retryable_status_is_attempted_once():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(401)

    with pytest.raises(JevAuthError):
        await make_client(handler).evaluate_ticket("Subject here", "A long enough message body.")
    assert calls == 1


async def test_retryable_status_is_bounded_by_max_attempts():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    with pytest.raises(JevUpstreamError):
        await make_client(handler).evaluate_ticket("Subject here", "A long enough message body.")
    assert calls == 3


async def test_retry_after_is_honored_but_capped():
    sleeps = []
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            429 if calls == 1 else 200,
            headers={"Retry-After": "9"},
            json={} if calls == 1 else GOOD_BODY,
        )

    settings = Settings(
        _env_file=None,
        jev_mode="live",
        typesafe_api_key=FAKE_KEY,
        api_auth_enabled=True,
        client_api_keys="test:inbound",
        jev_retry_base_seconds=0.1,
        jev_retry_max_seconds=0.5,
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def record_sleep(seconds):
        sleeps.append(seconds)

    result = await JevClient(settings, http, sleep=record_sleep).evaluate_ticket(
        "Subject here", "A long enough message body."
    )
    assert result.model == "jev-1.14.0"
    assert sleeps == [0.5]


async def test_invalid_success_response_is_not_retried():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, text="not json")

    with pytest.raises(JevResponseError):
        await make_client(handler).evaluate_ticket("Subject here", "A long enough message body.")
    assert calls == 1
