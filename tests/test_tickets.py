import pytest

from app.api.deps import get_evaluator
from app.main import app
from app.services.errors import JevUnavailableError

OUTAGE = {
    "subject": "Production outage",
    "message": "Our API is down and every transaction fails. We are losing sales and need help immediately, this is critical.",
}
VAGUE = {
    "subject": "Hello there",
    "message": "Just wanted to say hi and ask about something when you have time.",
}
FEATURE = {
    "subject": "Feature idea",
    "message": "It would be great if you could add a new feature: please add support for dark mode in the dashboard.",
}


def create(client, payload):
    response = client.post("/api/v1/tickets", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


class FailingEvaluator:
    async def evaluate_ticket(self, subject, message):
        raise JevUnavailableError("Jev is rate limiting or overloaded", provider_status=429)


# --- creating and reading -------------------------------------------------

def test_created_ticket_is_stored_triaged_and_readable(client):
    ticket = create(client, OUTAGE)
    assert ticket["id"] == 1
    assert ticket["status"] == "open"
    assert ticket["triage_state"] == "triaged"
    assert ticket["priority"] == "P1"
    assert ticket["queue"] == "technical_support"
    assert ticket["decision"]["reasons"]
    assert ticket["evaluation"]["model"] == "mock"

    fetched = client.get(f"/api/v1/tickets/{ticket['id']}").json()
    assert fetched == ticket


def test_timestamps_are_timezone_aware_utc(client):
    ticket = create(client, OUTAGE)
    assert ticket["created_at"].endswith("Z") or ticket["created_at"].endswith("+00:00")


def test_unknown_ticket_is_404_with_standard_error_shape(client):
    response = client.get("/api/v1/tickets/999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ticket_not_found"


def test_stateless_triage_endpoint_stores_nothing(client):
    assert client.post("/api/v1/triage", json=OUTAGE).status_code == 200
    assert client.get("/api/v1/tickets").json()["total"] == 0


# --- AI outage must never lose a ticket ----------------------------------

def test_ticket_survives_ai_outage_and_can_be_retried(client):
    app.dependency_overrides[get_evaluator] = lambda: FailingEvaluator()
    ticket = create(client, OUTAGE)
    assert ticket["triage_state"] == "failed"
    assert ticket["decision"] is None
    assert ticket["priority"] is None
    assert "rate limiting" in ticket["triage_error"]

    # The customer's ticket is stored and visible to agents.
    listed = client.get("/api/v1/tickets").json()
    assert listed["total"] == 1

    # The AI recovers; retry succeeds.
    app.dependency_overrides.clear()
    retried = client.post(f"/api/v1/tickets/{ticket['id']}/triage")
    assert retried.status_code == 200
    body = retried.json()
    assert body["triage_state"] == "triaged"
    assert body["triage_error"] is None
    assert body["priority"] == "P1"


def test_retry_on_already_triaged_ticket_is_conflict(client):
    ticket = create(client, OUTAGE)
    response = client.post(f"/api/v1/tickets/{ticket['id']}/triage")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


# --- listing --------------------------------------------------------------

def test_list_is_in_work_queue_order_p1_first(client):
    create(client, FEATURE)   # P4
    create(client, VAGUE)     # P4 (human triage)
    create(client, OUTAGE)    # P1, created last
    items = client.get("/api/v1/tickets").json()["items"]
    assert [i["priority"] for i in items][0] == "P1"
    # Within the same priority, oldest first.
    p4 = [i["id"] for i in items if i["priority"] == "P4"]
    assert p4 == sorted(p4)


def test_untriaged_tickets_sort_last(client):
    app.dependency_overrides[get_evaluator] = lambda: FailingEvaluator()
    failed = create(client, OUTAGE)
    app.dependency_overrides.clear()
    ok = create(client, FEATURE)
    ids = [i["id"] for i in client.get("/api/v1/tickets").json()["items"]]
    assert ids == [ok["id"], failed["id"]]


def test_list_filters(client):
    create(client, OUTAGE)
    create(client, FEATURE)
    create(client, VAGUE)

    assert client.get("/api/v1/tickets?queue=product").json()["total"] == 1
    assert client.get("/api/v1/tickets?priority=P1").json()["total"] == 1
    review_queue = client.get("/api/v1/tickets?needs_review=true").json()
    assert review_queue["total"] == 1
    assert review_queue["items"][0]["queue"] == "triage_desk"
    assert client.get("/api/v1/tickets?status=resolved").json()["total"] == 0


def test_pagination(client):
    for _ in range(3):
        create(client, FEATURE)
    page = client.get("/api/v1/tickets?limit=2&offset=2").json()
    assert page["total"] == 3
    assert len(page["items"]) == 1


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1", "priority=P9", "status=bogus"])
def test_bad_list_params_are_rejected(client, query):
    assert client.get(f"/api/v1/tickets?{query}").status_code == 422


# --- human review ---------------------------------------------------------

def test_confirm_review_clears_review_queue_and_records_agreement(client):
    ticket = create(client, VAGUE)
    assert ticket["needs_review"] is True

    reviewed = client.post(f"/api/v1/tickets/{ticket['id']}/review", json={"reviewer": "dana"}).json()
    assert reviewed["needs_review"] is False
    assert reviewed["queue"] == ticket["queue"]
    review = reviewed["reviews"][0]
    assert review["agreed"] is True
    assert review["action"] == "confirm"
    assert review["reviewer"] == "dana"


def test_correct_review_updates_ticket_but_keeps_original_ai_decision(client):
    ticket = create(client, VAGUE)
    assert ticket["decision"]["queue"] == "triage_desk"

    reviewed = client.post(
        f"/api/v1/tickets/{ticket['id']}/review",
        json={"reviewer": "dana", "queue": "billing", "priority": "P2", "note": "Customer meant invoice."},
    ).json()

    # The ticket now shows the human's answer...
    assert reviewed["queue"] == "billing"
    assert reviewed["priority"] == "P2"
    # ...while the AI's original decision is preserved untouched as evidence.
    assert reviewed["decision"]["queue"] == "triage_desk"
    review = reviewed["reviews"][0]
    assert review["agreed"] is False
    assert review["action"] == "correct"
    assert review["escalate"] is False  # unspecified fields keep the AI's value


def test_review_with_unknown_queue_is_rejected(client):
    ticket = create(client, VAGUE)
    response = client.post(f"/api/v1/tickets/{ticket['id']}/review", json={"reviewer": "dana", "queue": "nope"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_review"


def test_cannot_review_a_ticket_with_no_ai_decision(client):
    app.dependency_overrides[get_evaluator] = lambda: FailingEvaluator()
    ticket = create(client, OUTAGE)
    response = client.post(f"/api/v1/tickets/{ticket['id']}/review", json={"reviewer": "dana"})
    assert response.status_code == 409


def test_review_requires_a_reviewer_name(client):
    ticket = create(client, VAGUE)
    assert client.post(f"/api/v1/tickets/{ticket['id']}/review", json={}).status_code == 422


# --- status lifecycle -----------------------------------------------------

def test_status_lifecycle_and_resolution_timestamps(client):
    tid = create(client, FEATURE)["id"]
    url = f"/api/v1/tickets/{tid}/status"

    assert client.patch(url, json={"status": "in_progress"}).json()["status"] == "in_progress"

    resolved = client.patch(url, json={"status": "resolved", "note": "Added to roadmap."}).json()
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"] is not None
    assert resolved["resolution_note"] == "Added to roadmap."

    reopened = client.patch(url, json={"status": "open"}).json()
    assert reopened["resolved_at"] is None
    assert reopened["resolution_note"] is None


@pytest.mark.parametrize(("start", "target"), [("open", "open"), ("resolved", "in_progress")])
def test_invalid_status_transitions_are_conflicts(client, start, target):
    tid = create(client, FEATURE)["id"]
    url = f"/api/v1/tickets/{tid}/status"
    if start == "resolved":
        client.patch(url, json={"status": "resolved"})
    response = client.patch(url, json={"status": target})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_unknown_status_value_is_rejected(client):
    tid = create(client, FEATURE)["id"]
    assert client.patch(f"/api/v1/tickets/{tid}/status", json={"status": "deleted"}).status_code == 422
