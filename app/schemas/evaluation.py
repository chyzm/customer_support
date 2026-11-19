"""Typed shapes for what Jev returns.

Parsing the raw dict into models means a malformed provider response fails
loudly at the boundary, and the rest of the app works with real types.
"""

from pydantic import BaseModel, Field


class ChoiceAnswer(BaseModel):
    """Pick one option. Carries the full probability distribution."""

    choice: str
    confidence: float = Field(ge=0, le=1)
    probabilities: dict[str, float]


class ScoreAnswer(BaseModel):
    """Position on an ordered rubric. The score is a probability-weighted mean,
    so it can fall between levels (e.g. 1.6)."""

    score: float
    confidence: float = Field(ge=0, le=1)
    legend: dict[str, str]
    probabilities: dict[str, float]


class NoulAnswer(BaseModel):
    """Probability (0-1) that a statement is true. There is no confidence field:
    the probability is the only signal, and ~0.5 means 'cannot tell'."""

    noul: float = Field(ge=0, le=1)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class TicketEvaluation(BaseModel):
    """The four judgments we ask Jev to make about a ticket."""

    model: str
    category: ChoiceAnswer
    urgency: ScoreAnswer
    sentiment: ScoreAnswer
    needs_escalation: NoulAnswer
    usage: Usage
