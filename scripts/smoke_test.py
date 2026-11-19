r"""End-to-end API smoke test.

Run while the server is up:
    .\.venv\Scripts\python.exe scripts\smoke_test.py

This intentionally creates three demo tickets in the configured database.
"""

import argparse
import json
from urllib.request import Request, urlopen


def request(method: str, url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, headers={"Content-Type": "application/json"}, method=method)
    with urlopen(req, timeout=15) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8766")
    args = parser.parse_args()
    tickets_url = f"{args.base_url}/api/v1/tickets"

    outage = request("POST", tickets_url, {
        "subject": "Production outage",
        "message": (
            "Our API is down and every transaction fails. We are losing sales "
            "and need help immediately, this is critical."
        ),
    })
    vague = request("POST", tickets_url, {
        "subject": "Hello there",
        "message": "Just wanted to say hi and ask about something when you have time.",
    })
    feature = request("POST", tickets_url, {
        "subject": "Feature idea",
        "message": (
            "It would be great if you could add a new feature: please add support "
            "for dark mode in the dashboard."
        ),
    })

    assert outage["priority"] == "P1" and outage["escalated"] is True
    assert vague["needs_review"] is True
    assert feature["queue"] == "product"

    reviewed = request("POST", f"{tickets_url}/{vague['id']}/review", {
        "reviewer": "dana",
        "queue": "billing",
        "priority": "P2",
        "note": "Customer meant invoice.",
    })
    assert reviewed["queue"] == "billing"
    assert reviewed["priority"] == "P2"
    assert reviewed["decision"]["queue"] == "triage_desk"  # AI history unchanged
    assert reviewed["reviews"][-1]["action"] == "correct"

    resolved = request("PATCH", f"{tickets_url}/{feature['id']}/status", {
        "status": "resolved",
        "note": "Added to roadmap.",
    })
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"] is not None

    listed = request("GET", tickets_url)
    created_ids = {outage["id"], vague["id"], feature["id"]}
    listed_ids = {item["id"] for item in listed["items"]}
    assert created_ids <= listed_ids

    print("PASS: created, triaged, reviewed, corrected, resolved, and listed tickets")
    print(f"Created ticket IDs: {sorted(created_ids)}")


if __name__ == "__main__":
    main()
