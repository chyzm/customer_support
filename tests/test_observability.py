import json
import re

from app.core.observability import JsonFormatter, select_request_id


def test_safe_request_id_is_preserved_and_returned(client):
    response = client.get("/health", headers={"X-Request-ID": "order-123.test"})
    assert response.headers["x-request-id"] == "order-123.test"


def test_unsafe_request_id_is_replaced(client):
    response = client.get("/health", headers={"X-Request-ID": "bad value\nforged"})
    assert response.headers["x-request-id"] != "bad value\nforged"
    assert re.fullmatch(r"[0-9a-f-]{36}", response.headers["x-request-id"])


def test_request_id_selector_rejects_long_or_unsafe_values():
    assert select_request_id("safe_ID-1.2") == "safe_ID-1.2"
    assert select_request_id("x" * 65) != "x" * 65
    assert select_request_id("spaces are unsafe") != "spaces are unsafe"


def test_json_logs_do_not_contain_ticket_body_or_headers(client):
    import io
    import logging

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    app_logger = logging.getLogger("app")
    app_logger.handlers[:] = [handler]

    marker = "PRIVATE-TICKET-CONTENT-123"
    client.post(
        "/api/v1/triage",
        headers={"X-Request-ID": "safe-log-test", "X-API-Key": "PRIVATE-KEY-456"},
        json={"subject": "Marker subject", "message": f"A valid message with {marker}"},
    )
    output = stream.getvalue()
    records = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    access = [r for r in records if r.get("event") == "request_completed"]
    assert access
    assert access[-1]["request_id"] == "safe-log-test"
    assert marker not in output
    assert "PRIVATE-KEY-456" not in output


def test_unexpected_error_is_generic_and_correlated(client):
    from app.api.deps import get_evaluator
    from app.main import app

    class BrokenEvaluator:
        async def evaluate_ticket(self, subject, message):
            raise RuntimeError("PRIVATE-EXCEPTION-CONTENT")

    app.dependency_overrides[get_evaluator] = lambda: BrokenEvaluator()
    # Starlette normally re-raises handled server exceptions in tests. Disable
    # that behavior here so we can inspect the production HTTP response.
    client._transport.raise_server_exceptions = False
    response = client.post(
        "/api/v1/triage",
        headers={"X-Request-ID": "failure-123"},
        json={"subject": "Valid subject", "message": "A sufficiently long private message."},
    )
    assert response.status_code == 500
    assert response.headers["x-request-id"] == "failure-123"
    assert response.json() == {
        "error": {"code": "internal_error", "message": "An unexpected error occurred."}
    }
    assert "PRIVATE-EXCEPTION-CONTENT" not in response.text
