"""Build TicketEvaluation objects from probabilities, so engine tests read like scenarios."""

from app.schemas.evaluation import (
    ChoiceAnswer,
    NoulAnswer,
    ScoreAnswer,
    TicketEvaluation,
    Usage,
)

CATEGORY_NAMES = ["billing", "technical", "account_access", "feature_request", "other"]


def category(top: str = "billing", p_top: float = 0.9, names=CATEGORY_NAMES) -> ChoiceAnswer:
    """Top option gets p_top; the remainder is split evenly."""
    rest = (1 - p_top) / (len(names) - 1)
    probs = {n: (p_top if n == top else rest) for n in names}
    return ChoiceAnswer(choice=top, confidence=0, probabilities=probs)


def scored(probs: list[float]) -> ScoreAnswer:
    """Score answer from a list of per-level probabilities."""
    return ScoreAnswer(
        score=sum(i * p for i, p in enumerate(probs)),
        confidence=0,
        legend={str(i): f"level {i}" for i in range(len(probs))},
        probabilities={str(i): p for i, p in enumerate(probs)},
    )


def peaked(level: int, count: int = 4, strength: float = 0.9) -> list[float]:
    """Confident distribution on `level`, remainder on its nearest neighbour."""
    probs = [0.0] * count
    probs[level] = strength
    neighbour = level + 1 if level + 1 < count else level - 1
    probs[neighbour] = 1 - strength
    return probs


def evaluation(
    cat: ChoiceAnswer | None = None,
    urgency: list[float] | None = None,
    sentiment: list[float] | None = None,
    escalation: float = 0.05,
) -> TicketEvaluation:
    """Defaults describe a calm, clear, low-urgency billing ticket."""
    return TicketEvaluation(
        model="test",
        category=cat or category(),
        urgency=scored(urgency or peaked(0, strength=0.95)),
        sentiment=scored(sentiment or peaked(0, strength=0.95)),
        needs_escalation=NoulAnswer(noul=escalation),
        usage=Usage(),
    )
