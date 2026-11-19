"""Offline stand-in for Jev, used when JEV_MODE=mock.

It is keyword matching, NOT intelligence. Its job is to return the same shapes
as the real API so the whole pipeline (decision engine, database, UI) can be
built and tested without an API key. The model name is reported as "mock" so
results can never be mistaken for real Jev output.

It is built to be *uncertain when the evidence is weak*: a ticket with no
keyword matches produces a flat distribution, which the decision engine should
send to a human. That lets you see every decision path without a real key.
"""

import re

from app.decision.confidence import choice_confidence, score_confidence
from app.schemas.evaluation import (
    ChoiceAnswer,
    NoulAnswer,
    ScoreAnswer,
    TicketEvaluation,
    Usage,
)
from app.services import rubric

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "billing": ("payment", "charge", "refund", "invoice", "billing", "subscription", "card"),
    "technical": ("error", "bug", "crash", "outage", "down", "fail", "broken", "api", "slow"),
    "account_access": ("password", "login", "log in", "locked", "access", "2fa", "permission"),
    "feature_request": ("feature", "would be great", "please add", "wish", "support for"),
}
_URGENT_WORDS = (
    "asap", "urgent", "immediately", "outage", "down", "losing", "since yesterday",
    "critical", "unable to", "affected", "every transaction", "data loss", "breach",
)
_ANGRY_WORDS = ("unacceptable", "furious", "terrible", "worst", "ridiculous", "angry", "!!")
_THREAT_WORDS = ("cancel", "lawyer", "sue", "refund me now", "chargeback")


def _hits(text: str, words: tuple[str, ...]) -> int:
    return sum(1 for w in words if w in text)


def _category_probabilities(names: list[str], text: str) -> dict[str, float]:
    """Each keyword hit adds weight. No hits means a flat, uncertain distribution
    (with a small lean toward 'other'). A tie between two categories stays uncertain."""
    weights = {n: 1.0 + 6.0 * _hits(text, _CATEGORY_KEYWORDS.get(n, ())) for n in names}
    if all(w == 1.0 for w in weights.values()):
        weights["other"] = 2.0
    total = sum(weights.values())
    return {n: round(w / total, 3) for n, w in weights.items()}


def _level_probabilities(count: int, peak: int, strength: float) -> list[float]:
    """Mass `strength` on the peak level; the rest decays with distance from it,
    like a real ordered rubric where neighbouring levels are the likeliest mistakes."""
    decay = [0.0 if i == peak else 0.5 ** abs(i - peak) for i in range(count)]
    scale = (1 - strength) / sum(decay)
    return [strength if i == peak else d * scale for i, d in enumerate(decay)]


def _score_answer(levels: list[str], peak: int, strength: float) -> ScoreAnswer:
    probs = _level_probabilities(len(levels), peak, strength)
    probabilities = {str(i): round(p, 3) for i, p in enumerate(probs)}
    return ScoreAnswer(
        score=round(sum(i * p for i, p in enumerate(probs)), 3),
        confidence=round(score_confidence(probabilities), 3),
        legend={str(i): text for i, text in enumerate(levels)},
        probabilities=probabilities,
    )


class MockJevClient:
    async def evaluate_ticket(self, subject: str, message: str) -> TicketEvaluation:
        text = f"{subject} {message}".lower()

        names = list(rubric.CATEGORIES)
        cat_probs = _category_probabilities(names, text)
        best = max(cat_probs, key=cat_probs.get)

        # More matching evidence means a more peaked (more confident) distribution.
        urgent_hits = _hits(text, _URGENT_WORDS)
        urgency_peak = min(urgent_hits, 3)
        # No urgent wording at all reads as "not urgent" (fairly sure). One stray hit is
        # ambiguous; more hits increase certainty.
        urgency_strength = 0.8 if urgent_hits == 0 else min(0.5 + 0.15 * urgent_hits, 0.95)

        angry = _hits(text, _ANGRY_WORDS)
        threats = _hits(text, _THREAT_WORDS)
        sentiment_peak = 3 if threats else min(angry, 2)
        sentiment_strength = min(0.7 + 0.1 * (angry + threats), 0.95)

        escalate = 0.9 if (urgency_peak >= 3 or threats) else 0.5 if urgency_peak == 2 else 0.1

        return TicketEvaluation(
            model="mock",
            category=ChoiceAnswer(
                choice=best,
                confidence=round(choice_confidence(cat_probs), 3),
                probabilities=cat_probs,
            ),
            urgency=_score_answer(rubric.URGENCY_LEVELS, urgency_peak, urgency_strength),
            sentiment=_score_answer(rubric.SENTIMENT_LEVELS, sentiment_peak, sentiment_strength),
            needs_escalation=NoulAnswer(noul=escalate),
            usage=Usage(input_tokens=len(re.findall(r"\w+", text)), output_tokens=0),
        )
