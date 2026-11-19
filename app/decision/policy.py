from pydantic import BaseModel, ConfigDict, Field


class DecisionPolicy(BaseModel):
    """Every threshold the decision engine uses, as data.

    Keeping rules in a frozen object (not scattered `if x > 0.8` literals) means:
    * tuning never touches engine code,
    * each decision records which `version` produced it,
    * a plugged-in product can supply its own policy.

    IMPORTANT: thresholds do not transfer between models or questions. These are
    conservative starting values. Calibrate them on labelled tickets (Phase 4)
    and re-check whenever you change `JEV_MODEL`.
    """

    model_config = ConfigDict(frozen=True)

    version: str = "2026-11-18.1"

    # Category (Choice). Wrong routing is recoverable, so the bar is moderate.
    category_auto_confidence: float = Field(0.60, ge=0, le=1)  # at/above: route automatically
    category_min_confidence: float = Field(0.30, ge=0, le=1)  # below: do not guess a queue

    # Urgency (Score), as a probability-weighted level 0..3.
    p1_min_score: float = 2.5
    p2_min_score: float = 1.5
    p3_min_score: float = 0.75
    # Below this confidence we cannot trust a LOW urgency reading (see engine).
    urgency_min_confidence: float = Field(0.40, ge=0, le=1)

    # Sentiment (Score), level 0..3.
    hostile_min_score: float = 2.5
    sentiment_min_confidence: float = Field(0.40, ge=0, le=1)

    # Escalation (Noul). Escalating pages a senior person, so the bar is HIGH.
    # The review band is wider, because missing a real emergency costs more
    # than a person double-checking a borderline ticket.
    escalate_min_probability: float = Field(0.80, ge=0, le=1)
    escalation_review_min_probability: float = Field(0.40, ge=0, le=1)

    queues: dict[str, str] = {
        "billing": "billing",
        "technical": "technical_support",
        "account_access": "account_security",
        "feature_request": "product",
        "other": "general",
    }
    fallback_queue: str = "triage_desk"


DEFAULT_POLICY = DecisionPolicy()
