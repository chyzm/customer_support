"""Confidence statistics, recomputed from the raw probabilities.

TypeSafe publishes the exact formulas (docs: "5. Confidence"), so we compute
confidence ourselves instead of trusting a provider-reported field. Reasons:

* One definition for live and mock mode, so thresholds behave the same in both.
* Noul answers carry no confidence field at all, so we need our own anyway.
* If the provider changes how it reports confidence, our decisions don't move.

Every function returns a value in [0, 1]: 1 means all probability sits on one
outcome, 0 means it is spread as thinly as possible.

Confidence measures how concentrated the distribution is. It does NOT measure
whether the answer is correct. A confidently wrong answer is possible.
"""

from collections.abc import Mapping


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def choice_confidence(probabilities: Mapping[str, float]) -> float:
    """(p_max - 1/n) / (1 - 1/n). Only the top probability counts."""
    n = len(probabilities)
    if n < 2:
        return 1.0
    p_max = max(probabilities.values())
    return _clamp((p_max - 1 / n) / (1 - 1 / n))


def noul_confidence(p: float) -> float:
    """|2p - 1|. A Noul at 0.5 means 'cannot tell', which scores 0."""
    return _clamp(abs(2 * p - 1))


def score_confidence(probabilities: Mapping[str, float]) -> float:
    """Like choice confidence, but mass far from the most likely level hurts more.

    Levels are ordered, so being torn between neighbouring levels (1 and 2) is
    less uncertain than being torn between the two ends (0 and 3).
    """
    levels = [probabilities[key] for key in sorted(probabilities, key=int)]
    n = len(levels)
    if n < 2:
        return 1.0
    mode = levels.index(max(levels))
    spread = sum(p * abs(i - mode) for i, p in enumerate(levels))
    even_spread = sum(abs(i - (n - 1) / 2) for i in range(n)) / n
    return _clamp(1 - spread / even_spread)
