"""The decision engine: turns Jev's probabilities into actions.

Jev answers narrow questions. THIS module owns the workflow and the rules, as
the TypeSafe docs recommend. It is a pure function: same evaluation + same
policy always gives the same decision. No network, no database, no FastAPI.
That makes it trivial to test and to reuse in someone else's product.

Rule order matters, and each step appends a Reason:
  1. Queue      from category, gated by category confidence
  2. Priority   from urgency score
  3. Sentiment  can raise priority, never lower it
  4. Escalation from the Noul probability (high bar to act, lower bar to flag)
  5. Fail-safe  when urgency is uncertain, never allow a low priority

Design principle: errors are asymmetric. Wrongly marking an emergency as low
priority costs far more than asking a person to double-check. Every uncertain
case therefore moves toward MORE human attention, never less.
"""

from app.decision.confidence import choice_confidence, score_confidence
from app.decision.policy import DEFAULT_POLICY, DecisionPolicy
from app.schemas.decision import (
    Handling,
    Priority,
    Reason,
    Signals,
    TriageDecision,
)
from app.schemas.evaluation import TicketEvaluation

# Lower rank = more important. P1 is rank 1.
_RANK_TO_PRIORITY = {1: Priority.P1, 2: Priority.P2, 3: Priority.P3, 4: Priority.P4}
_HANDLING_ORDER = [Handling.AUTO_ROUTE, Handling.REVIEW, Handling.HUMAN_TRIAGE]


def _stricter(current: Handling, other: Handling) -> Handling:
    """Handling only ever moves toward more human involvement."""
    return max(current, other, key=_HANDLING_ORDER.index)


def _priority_rank_from_urgency(score: float, policy: DecisionPolicy) -> int:
    if score >= policy.p1_min_score:
        return 1
    if score >= policy.p2_min_score:
        return 2
    if score >= policy.p3_min_score:
        return 3
    return 4


def decide(evaluation: TicketEvaluation, policy: DecisionPolicy = DEFAULT_POLICY) -> TriageDecision:
    reasons: list[Reason] = []
    handling = Handling.AUTO_ROUTE

    category_conf = choice_confidence(evaluation.category.probabilities)
    urgency_conf = score_confidence(evaluation.urgency.probabilities)
    sentiment_conf = score_confidence(evaluation.sentiment.probabilities)
    escalation_p = evaluation.needs_escalation.noul

    # 1. Queue -------------------------------------------------------------
    category = evaluation.category.choice
    if category_conf < policy.category_min_confidence:
        queue = policy.fallback_queue
        handling = _stricter(handling, Handling.HUMAN_TRIAGE)
        reasons.append(Reason(
            code="category_unclear",
            detail=f"Category confidence {category_conf:.2f} is below {policy.category_min_confidence:.2f}; "
                   f"not guessing a queue.",
        ))
    elif category not in policy.queues:
        # The provider answered with an option our policy does not know about.
        queue = policy.fallback_queue
        handling = _stricter(handling, Handling.REVIEW)
        reasons.append(Reason(
            code="category_unmapped",
            detail=f"Category '{category}' has no queue in policy {policy.version}.",
        ))
    else:
        queue = policy.queues[category]
        if category_conf < policy.category_auto_confidence:
            handling = _stricter(handling, Handling.REVIEW)
            reasons.append(Reason(
                code="category_needs_review",
                detail=f"Routed to '{queue}' but category confidence {category_conf:.2f} is below "
                       f"{policy.category_auto_confidence:.2f}.",
            ))
        else:
            reasons.append(Reason(
                code="category_confident",
                detail=f"Routed to '{queue}' with category confidence {category_conf:.2f}.",
            ))

    # 2. Priority from urgency ----------------------------------------------
    rank = _priority_rank_from_urgency(evaluation.urgency.score, policy)
    reasons.append(Reason(
        code="priority_from_urgency",
        detail=f"Urgency score {evaluation.urgency.score:.2f} maps to {_RANK_TO_PRIORITY[rank].value}.",
    ))

    # 3. Sentiment can raise priority, never lower it -----------------------
    if (
        evaluation.sentiment.score >= policy.hostile_min_score
        and sentiment_conf >= policy.sentiment_min_confidence
        and rank > 1
    ):
        rank -= 1
        reasons.append(Reason(
            code="hostile_sentiment_bump",
            detail=f"Hostile sentiment (score {evaluation.sentiment.score:.2f}) raised priority to "
                   f"{_RANK_TO_PRIORITY[rank].value}.",
        ))

    # 4. Escalation: high bar to act, lower bar to flag ----------------------
    escalate = False
    if escalation_p >= policy.escalate_min_probability:
        escalate = True
        rank = 1
        reasons.append(Reason(
            code="escalated",
            detail=f"Escalation probability {escalation_p:.2f} reached {policy.escalate_min_probability:.2f}; "
                   f"priority set to P1.",
        ))
    elif escalation_p >= policy.escalation_review_min_probability:
        handling = _stricter(handling, Handling.REVIEW)
        reasons.append(Reason(
            code="escalation_uncertain",
            detail=f"Escalation probability {escalation_p:.2f} is in the review band "
                   f"({policy.escalation_review_min_probability:.2f}-{policy.escalate_min_probability:.2f}); "
                   f"a person should decide.",
        ))

    # 5. Fail-safe: an uncertain urgency reading cannot justify a LOW priority ---
    if urgency_conf < policy.urgency_min_confidence:
        handling = _stricter(handling, Handling.REVIEW)
        if rank > 3:
            rank = 3
            reasons.append(Reason(
                code="urgency_uncertain_floor",
                detail=f"Urgency confidence {urgency_conf:.2f} is below {policy.urgency_min_confidence:.2f}; "
                       f"priority floored at P3 instead of P4.",
            ))
        else:
            reasons.append(Reason(
                code="urgency_uncertain",
                detail=f"Urgency confidence {urgency_conf:.2f} is below {policy.urgency_min_confidence:.2f}.",
            ))

    return TriageDecision(
        queue=queue,
        priority=_RANK_TO_PRIORITY[rank],
        escalate=escalate,
        handling=handling,
        reasons=reasons,
        signals=Signals(
            category_confidence=round(category_conf, 3),
            urgency_score=evaluation.urgency.score,
            urgency_confidence=round(urgency_conf, 3),
            sentiment_score=evaluation.sentiment.score,
            sentiment_confidence=round(sentiment_conf, 3),
            escalation_probability=escalation_p,
        ),
        policy_version=policy.version,
    )
