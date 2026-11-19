"""Expected values come from the worked examples in TypeSafe's confidence docs."""

import pytest

from app.decision.confidence import choice_confidence, noul_confidence, score_confidence


def test_choice_confidence_uses_only_top_probability():
    # Docs: (0.6, 0.3, 0.1) and (0.6, 0.2, 0.2) both give 0.4
    a = choice_confidence({"x": 0.6, "y": 0.3, "z": 0.1})
    b = choice_confidence({"x": 0.6, "y": 0.2, "z": 0.2})
    assert a == pytest.approx(0.4)
    assert b == pytest.approx(0.4)


def test_choice_confidence_extremes():
    assert choice_confidence({"a": 1.0, "b": 0.0, "c": 0.0}) == pytest.approx(1.0)
    assert choice_confidence({"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}) == pytest.approx(0.0)


def test_noul_confidence():
    assert noul_confidence(0.5) == pytest.approx(0.0)  # "cannot tell"
    assert noul_confidence(1.0) == pytest.approx(1.0)
    assert noul_confidence(0.0) == pytest.approx(1.0)  # confidently false
    assert noul_confidence(0.9) == pytest.approx(0.8)


def test_score_confidence_neighbours_vs_ends():
    # Docs: three levels, (0, .5, .5) -> 0.25 ; (.5, 0, .5) -> 0
    assert score_confidence({"0": 0.0, "1": 0.5, "2": 0.5}) == pytest.approx(0.25)
    assert score_confidence({"0": 0.5, "1": 0.0, "2": 0.5}) == pytest.approx(0.0)


def test_score_confidence_docs_worked_example():
    # Docs: (0, .57, .43) -> ~0.35
    assert score_confidence({"0": 0.0, "1": 0.57, "2": 0.43}) == pytest.approx(0.355, abs=0.005)


def test_score_confidence_sorts_levels_numerically():
    # Keys are strings; "10" must sort after "2" when a rubric has 10 levels.
    probs = {str(i): (1.0 if i == 9 else 0.0) for i in range(10)}
    assert score_confidence(probs) == pytest.approx(1.0)
