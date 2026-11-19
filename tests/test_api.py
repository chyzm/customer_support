import pytest
from pydantic import ValidationError

from app.api.deps import get_evaluator
from app.core.config import Settings
from app.main import app
from app.services.errors import JevUnavailableError

VALID = {
    "subject": "Payment processing failure",
    "message": "We have been unable to process customer payments since yesterday. Every transaction returns an error.",
}


def triage(client, subject, message):
    response = client.post("/api/v1/triage", json={"subject": subject, "message": message})
    assert response.status_code == 200, response.text
    return response.json()


def test_health_reports_mode(client):
    body = client.get("/health").json()
    assert body["status"] == "healthy"
    assert body["jev_mode"] == "mock"


def test_triage_returns_decision_and_evidence(client):
    body = triage(client, **VALID)
    assert set(body) == {"decision", "evaluation"}
    assert body["evaluation"]["model"] == "mock"
    assert sum(body["evaluation"]["category"]["probabilities"].values()) == pytest.approx(1.0, abs=0.01)

    decision = body["decision"]
    assert decision["priority"] in {"P1", "P2", "P3", "P4"}
    assert decision["handling"] in {"auto_route", "review", "human_triage"}
    assert decision["reasons"], "every decision must explain itself"
    assert decision["policy_version"] == client.get("/api/v1/policy").json()["version"]


def test_outage_is_p1_and_escalated(client):
    body = triage(
        client,
        "Production outage",
        "Our API is down and every transaction fails. We are losing sales and need help immediately, this is critical.",
    )
    assert body["decision"]["priority"] == "P1"
    assert body["decision"]["escalate"] is True


def test_vague_ticket_is_not_guessed(client):
    body = triage(client, "Hello there", "Just wanted to say hi and ask about something when you have time.")
    assert body["decision"]["handling"] == "human_triage"
    assert body["decision"]["queue"] == "triage_desk"


def test_clear_feature_request_is_low_priority_and_auto_routed(client):
    body = triage(
        client,
        "Feature idea",
        "It would be great if you could add a new feature: please add support for dark mode in the dashboard.",
    )
    d = body["decision"]
    assert d["queue"] == "product"
    assert d["priority"] == "P4"
    assert d["escalate"] is False
    assert d["handling"] == "auto_route"


def test_policy_endpoint_exposes_thresholds(client):
    body = client.get("/api/v1/policy").json()
    assert body["escalate_min_probability"] == 0.8
    assert body["queues"]["technical"] == "technical_support"


@pytest.mark.parametrize(
    "payload",
    [
        {"subject": "ab", "message": "long enough message here"},
        {"subject": "Valid subject", "message": "short"},
        {"subject": "Valid subject", "message": "x" * 5001},
        {"subject": "Valid subject"},
    ],
)
def test_invalid_input_rejected_before_reaching_provider(client, payload):
    assert client.post("/api/v1/triage", json=payload).status_code == 422


def test_provider_outage_becomes_503(client):
    class Failing:
        async def evaluate_ticket(self, subject, message):
            raise JevUnavailableError("Jev is rate limiting or overloaded", provider_status=429)

    app.dependency_overrides[get_evaluator] = lambda: Failing()
    response = client.post("/api/v1/triage", json=VALID)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_provider_unavailable"
    assert response.json()["error"]["provider_status"] == 429


def test_live_mode_without_key_fails_fast():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jev_mode="live", typesafe_api_key=None)


def test_api_key_is_masked_in_repr():
    settings = Settings(_env_file=None, jev_mode="live", typesafe_api_key="sk-super-secret")
    assert "sk-super-secret" not in repr(settings)
