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
    "message": "Please add support for dark mode as a new dashboard feature when convenient.",
}


def create(client, body):
    response = client.post("/api/v1/tickets", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def review(client, ticket_id, body):
    response = client.post(f"/api/v1/tickets/{ticket_id}/review", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_empty_analytics_are_explicit_not_division_by_zero(client):
    summary = client.get("/api/v1/analytics/summary").json()
    assert summary["total_tickets"] == 0
    assert summary["review_coverage"] is None
    assert summary["agreement_rate"] is None

    report = client.get("/api/v1/analytics/calibration").json()
    assert report["sample_count"] == 0
    assert report["category_routing"]["accuracy"] is None
    assert report["escalation"]["brier_score"] is None


def test_summary_counts_latest_decision_labels(client):
    outage = create(client, OUTAGE)
    vague = create(client, VAGUE)
    create(client, FEATURE)

    review(client, outage["id"], {"reviewer": "alex"})
    review(client, vague["id"], {"reviewer": "dana", "queue": "billing", "priority": "P2"})

    summary = client.get("/api/v1/analytics/summary").json()
    assert summary["total_tickets"] == 3
    assert summary["decisions"] == 3
    assert summary["reviewed_decisions"] == 2
    assert summary["corrected_decisions"] == 1
    assert summary["review_coverage"] == 0.6667
    assert summary["agreement_rate"] == 0.5
    assert summary["priority_counts"]["P1"] == 1
    assert summary["queue_counts"]["billing"] == 1


def test_calibration_uses_latest_review_once_and_preserves_prior_correction(client):
    ticket = create(client, VAGUE)
    corrected = review(
        client,
        ticket["id"],
        {"reviewer": "dana", "queue": "billing", "priority": "P2"},
    )
    assert corrected["queue"] == "billing"

    # A later review with no replacement fields confirms the CURRENT human
    # decision; it must not silently restore the original AI values.
    second = review(client, ticket["id"], {"reviewer": "alex"})
    assert second["queue"] == "billing"
    assert second["priority"] == "P2"
    assert len(second["reviews"]) == 2

    labels = client.get("/api/v1/analytics/calibration/labels").json()
    assert len(labels) == 1
    assert labels[0]["human_queue"] == "billing"
    assert labels[0]["ai_queue"] == "triage_desk"

    report = client.get("/api/v1/analytics/calibration?bins=4").json()
    assert report["sample_count"] == 1
    assert report["category_routing"]["accuracy"] == 0.0
    assert sum(b["sample_count"] for b in report["category_routing"]["buckets"]) == 1


def test_calibration_metrics_and_filters(client):
    outage = create(client, OUTAGE)
    feature = create(client, FEATURE)
    review(client, outage["id"], {"reviewer": "alex"})
    review(client, feature["id"], {"reviewer": "dana"})

    report = client.get("/api/v1/analytics/calibration").json()
    assert report["sample_count"] == 2
    assert report["models"] == ["mock"]
    assert report["category_routing"]["accuracy"] == 1.0
    assert report["final_priority"]["accuracy"] == 1.0
    assert report["escalation"]["accuracy"] == 1.0
    assert report["escalation"]["brier_score"] == 0.01
    assert report["caveats"]

    assert client.get("/api/v1/analytics/calibration?model=not-this-model").json()["sample_count"] == 0
    policy = report["policy_versions"][0]
    assert client.get(f"/api/v1/analytics/calibration?policy_version={policy}").json()["sample_count"] == 2


def test_label_export_contains_no_ticket_or_reviewer_content(client):
    ticket = create(client, VAGUE)
    review(client, ticket["id"], {"reviewer": "PRIVATE-NAME", "note": "PRIVATE-NOTE"})

    response = client.get("/api/v1/analytics/calibration/labels")
    text = response.text
    assert "PRIVATE-NAME" not in text
    assert "PRIVATE-NOTE" not in text
    assert VAGUE["message"] not in text
    assert set(response.json()[0]) == {
        "ticket_id", "decision_id", "reviewed_at", "model", "policy_version",
        "ai_queue", "human_queue", "ai_priority", "human_priority",
        "ai_escalate", "human_escalate", "category_confidence",
        "urgency_confidence", "escalation_probability",
    }


def test_calibration_bin_count_is_validated(client):
    assert client.get("/api/v1/analytics/calibration?bins=1").status_code == 422
    assert client.get("/api/v1/analytics/calibration?bins=21").status_code == 422
