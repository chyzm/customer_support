import pytest

from app.decision.engine import decide
from app.decision.policy import DEFAULT_POLICY, DecisionPolicy
from app.schemas.decision import Handling, Priority
from tests.factories import CATEGORY_NAMES, category, evaluation, peaked


def codes(decision):
    return [r.code for r in decision.reasons]


def test_clear_calm_low_urgency_ticket_is_auto_routed_p4():
    d = decide(evaluation())
    assert d.queue == "billing"
    assert d.priority == Priority.P4
    assert d.handling == Handling.AUTO_ROUTE
    assert d.escalate is False
    assert "category_confident" in codes(d)


def test_critical_ticket_with_high_escalation_probability_is_p1_and_escalated():
    d = decide(evaluation(
        cat=category("technical", 0.9),
        urgency=peaked(3, strength=0.95),
        escalation=0.93,
    ))
    assert d.queue == "technical_support"
    assert d.priority == Priority.P1
    assert d.escalate is True
    assert "escalated" in codes(d)


def test_flat_category_distribution_goes_to_human_triage_and_is_never_guessed():
    flat = category("billing", p_top=1 / len(CATEGORY_NAMES))
    d = decide(evaluation(cat=flat))
    assert d.queue == DEFAULT_POLICY.fallback_queue
    assert d.handling == Handling.HUMAN_TRIAGE
    assert "category_unclear" in codes(d)


def test_moderate_category_confidence_routes_but_asks_for_review():
    # p_top 0.55 over 5 options -> confidence (0.55-0.2)/0.8 = 0.4375: between 0.30 and 0.60
    d = decide(evaluation(cat=category("billing", 0.55)))
    assert d.queue == "billing"
    assert d.handling == Handling.REVIEW
    assert "category_needs_review" in codes(d)


def test_unknown_category_from_provider_uses_fallback_queue():
    names = CATEGORY_NAMES + ["brand_new_option"]
    d = decide(evaluation(cat=category("brand_new_option", 0.95, names=names)))
    assert d.queue == DEFAULT_POLICY.fallback_queue
    assert d.handling == Handling.REVIEW
    assert "category_unmapped" in codes(d)


def test_hostile_sentiment_raises_priority_one_level():
    # Urgency level 1 -> score ~1.1 -> P3. Hostile bumps to P2.
    base = decide(evaluation(urgency=peaked(1, strength=0.95)))
    angry = decide(evaluation(urgency=peaked(1, strength=0.95), sentiment=peaked(3, strength=0.95, count=4)))
    assert base.priority == Priority.P3
    assert angry.priority == Priority.P2
    assert "hostile_sentiment_bump" in codes(angry)


def test_sentiment_never_lowers_priority():
    calm = decide(evaluation(urgency=peaked(2, strength=0.95), sentiment=peaked(0, strength=0.95)))
    assert calm.priority == Priority.P2


def test_sentiment_bump_requires_sentiment_confidence():
    # Score 2.35 is "hostile" under a looser threshold, but the mass is spread (confidence ~0.45).
    spread = [0.0, 0.1, 0.45, 0.45]
    urgency = peaked(1, strength=0.95)  # P3 before any bump

    loose = DecisionPolicy(hostile_min_score=2.0)  # sentiment_min_confidence stays 0.40
    assert decide(evaluation(urgency=urgency, sentiment=spread), loose).priority == Priority.P2

    gated = DecisionPolicy(hostile_min_score=2.0, sentiment_min_confidence=0.60)
    d = decide(evaluation(urgency=urgency, sentiment=spread), gated)
    assert d.priority == Priority.P3
    assert "hostile_sentiment_bump" not in codes(d)


def test_uncertain_low_urgency_is_floored_at_p3_and_flagged_for_review():
    # Weighted score 0.72 would be P4, but 24% of the mass sits on the "critical" level.
    d = decide(evaluation(urgency=[0.76, 0.0, 0.0, 0.24]))
    assert d.signals.urgency_confidence < DEFAULT_POLICY.urgency_min_confidence
    assert d.priority == Priority.P3
    assert d.handling == Handling.REVIEW
    assert "urgency_uncertain_floor" in codes(d)


def test_uncertain_urgency_flags_review_but_does_not_downgrade_a_high_priority():
    # Score 2.1 -> P2, confidence low. The floor only blocks P4; it must not touch P2.
    d = decide(evaluation(urgency=[0.3, 0.0, 0.0, 0.7]))
    assert d.signals.urgency_confidence < DEFAULT_POLICY.urgency_min_confidence
    assert d.priority == Priority.P2
    assert d.handling == Handling.REVIEW
    assert "urgency_uncertain" in codes(d)
    assert "urgency_uncertain_floor" not in codes(d)


@pytest.mark.parametrize(
    ("p", "escalate", "handling"),
    [
        (0.10, False, Handling.AUTO_ROUTE),
        (0.39, False, Handling.AUTO_ROUTE),
        (0.40, False, Handling.REVIEW),  # review band starts (inclusive)
        (0.79, False, Handling.REVIEW),
        (0.80, True, Handling.AUTO_ROUTE),  # escalation threshold (inclusive)
        (0.95, True, Handling.AUTO_ROUTE),
    ],
)
def test_escalation_bands(p, escalate, handling):
    d = decide(evaluation(escalation=p))
    assert d.escalate is escalate
    assert d.handling == handling
    if escalate:
        assert d.priority == Priority.P1


def test_handling_only_gets_stricter_never_looser():
    # Unclear category (HUMAN_TRIAGE) must survive a later confident escalation.
    flat = category("billing", p_top=0.2)
    d = decide(evaluation(cat=flat, escalation=0.95))
    assert d.handling == Handling.HUMAN_TRIAGE
    assert d.escalate is True


def test_policy_is_data_a_stricter_policy_changes_the_outcome():
    ev = evaluation(cat=category("billing", 0.75))  # confidence 0.6875
    assert decide(ev).handling == Handling.AUTO_ROUTE
    strict = DecisionPolicy(version="strict", category_auto_confidence=0.9)
    d = decide(ev, strict)
    assert d.handling == Handling.REVIEW
    assert d.policy_version == "strict"


def test_decision_is_deterministic():
    ev = evaluation(escalation=0.5)
    assert decide(ev) == decide(ev)


def test_every_decision_explains_itself():
    d = decide(evaluation(cat=category("technical", 0.7), urgency=peaked(2, strength=0.9), escalation=0.6))
    assert len(d.reasons) >= 2
    assert all(r.code and r.detail for r in d.reasons)
