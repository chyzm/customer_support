"""The questions we ask Jev about every ticket.

This file is the part of the product you will tune most. Guidance from the
TypeSafe docs that shaped it:

* Each question is one atomic judgment that a person could make in a second.
* All questions run in parallel against the same state, so asking four costs
  roughly the same latency as asking one.
* Score levels are judged INDEPENDENTLY. The model does not see neighbouring
  levels, so every level must describe a concrete situation on its own. "Worse
  than the previous level" would be meaningless.
* Backticked names such as `message` point the model at fields in the state.
"""

from typing import Any

CATEGORIES: dict[str, str] = {
    "billing": "Charges, refunds, invoices, subscriptions or payment processing problems",
    "technical": "Bugs, errors, outages, performance or integration problems",
    "account_access": "Login, password, permissions or locked-account problems",
    "feature_request": "Asking for new functionality or a change in behaviour",
    "other": "Anything that fits none of the other categories",
}

URGENCY_LEVELS: list[str] = [
    "No time pressure: a general question or feedback, and nothing is broken",
    "Low: a minor inconvenience, a workaround exists, and it can wait several days",
    "High: an important function is broken or degraded and it needs attention within a day",
    "Critical: business-blocking, revenue loss, or a security or data problem happening now",
]

SENTIMENT_LEVELS: list[str] = [
    "Positive or neutral, polite and calm",
    "Mildly frustrated or disappointed, but still civil",
    "Clearly frustrated or angry",
    "Hostile: abusive language, or threats to cancel, sue or leave",
]

# Keys must match the field names on TicketEvaluation.
QUESTION_KEYS = ("category", "urgency", "sentiment", "needs_escalation")


def build_state(subject: str, message: str) -> dict[str, str]:
    """The content Jev judges. Named fields let questions refer to `subject` and `message`."""
    return {"subject": subject, "message": message}


def build_questions() -> dict[str, Any]:
    """Question definitions in the System One wire format."""
    return {
        "category": {
            "type": "choice",
            "instructions": "Which category best describes the support request in `message`?",
            "criteria": CATEGORIES,
        },
        "urgency": {
            "type": "score",
            "instructions": "How urgent is the issue reported in `message`?",
            "criteria": URGENCY_LEVELS,
        },
        "sentiment": {
            "type": "score",
            "instructions": "How negative is the customer's tone in `message`?",
            "criteria": SENTIMENT_LEVELS,
        },
        "needs_escalation": {
            "type": "noul",
            "instructions": (
                "The ticket needs a senior or human specialist right away because it "
                "describes a business-blocking outage, a security or data-loss issue, "
                "a legal threat, or a customer about to cancel."
            ),
        },
    }
