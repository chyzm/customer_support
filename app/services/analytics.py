"""Build privacy-safe operational and calibration reports from human reviews."""

from collections.abc import Sequence

from app.db.models import DecisionRecord, EvaluationRecord, ReviewRecord
from app.schemas.analytics import (
    AnalyticsSummary,
    CalibrationLabel,
    CalibrationReport,
    ConfidenceBucket,
    SignalCalibration,
)

ReviewRow = tuple[ReviewRecord, DecisionRecord, EvaluationRecord]


def build_summary(counts: dict[str, object]) -> AnalyticsSummary:
    reviewed = int(counts["reviewed_decisions"])
    decisions = int(counts["decisions"])
    corrected = int(counts["corrected_decisions"])
    return AnalyticsSummary(
        **counts,
        review_coverage=round(reviewed / decisions, 4) if decisions else None,
        agreement_rate=round((reviewed - corrected) / reviewed, 4) if reviewed else None,
    )


def to_label(row: ReviewRow) -> CalibrationLabel:
    review, decision, evaluation = row
    signals = decision.signals
    payload = evaluation.payload
    return CalibrationLabel(
        ticket_id=decision.ticket_id,
        decision_id=decision.id,
        reviewed_at=review.created_at,
        model=evaluation.model,
        policy_version=decision.policy_version,
        ai_queue=decision.queue,
        human_queue=review.queue,
        ai_priority=decision.priority,
        human_priority=review.priority,
        ai_escalate=decision.escalate,
        human_escalate=review.escalate,
        category_confidence=float(signals["category_confidence"]),
        urgency_confidence=float(signals["urgency_confidence"]),
        escalation_probability=float(payload["needs_escalation"]["noul"]),
    )


def _calibrate(
    signal: str,
    samples: Sequence[tuple[float, bool]],
    bins: int,
    *,
    probabilities: Sequence[tuple[float, bool]] | None = None,
) -> SignalCalibration:
    bucket_rows: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for confidence, correct in samples:
        index = min(int(confidence * bins), bins - 1)
        bucket_rows[index].append((confidence, correct))

    result: list[ConfidenceBucket] = []
    for index, rows in enumerate(bucket_rows):
        if not rows:
            continue
        lower = index / bins
        upper = (index + 1) / bins
        result.append(ConfidenceBucket(
            lower_bound=round(lower, 3),
            upper_bound=round(upper, 3),
            sample_count=len(rows),
            average_confidence=round(sum(c for c, _ in rows) / len(rows), 4),
            accuracy=round(sum(ok for _, ok in rows) / len(rows), 4),
        ))

    brier = None
    if probabilities is not None and len(probabilities) > 0:
        brier = round(
            sum((probability - int(actual)) ** 2 for probability, actual in probabilities)
            / len(probabilities),
            4,
        )

    return SignalCalibration(
        signal=signal,
        sample_count=len(samples),
        accuracy=round(sum(ok for _, ok in samples) / len(samples), 4) if samples else None,
        brier_score=brier,
        buckets=result,
    )


def build_calibration_report(rows: Sequence[ReviewRow], bins: int) -> CalibrationReport:
    labels = [to_label(row) for row in rows]

    category = [(x.category_confidence, x.ai_queue == x.human_queue) for x in labels]
    priority = [(x.urgency_confidence, x.ai_priority == x.human_priority) for x in labels]
    escalation = [
        (abs(2 * x.escalation_probability - 1), x.ai_escalate == x.human_escalate)
        for x in labels
    ]
    escalation_probabilities = [
        (x.escalation_probability, x.human_escalate) for x in labels
    ]

    return CalibrationReport(
        sample_count=len(labels),
        models=sorted({x.model for x in labels}),
        policy_versions=sorted({x.policy_version for x in labels}),
        category_routing=_calibrate("category_confidence", category, bins),
        final_priority=_calibrate("urgency_confidence", priority, bins),
        escalation=_calibrate(
            "noul_confidence",
            escalation,
            bins,
            probabilities=escalation_probabilities,
        ),
        caveats=[
            "Reviewed tickets are a selected sample; review accuracy is not overall production accuracy.",
            "Final priority combines urgency, sentiment, and escalation, so it does not directly calibrate the urgency question.",
            "Use one model and policy version at a time when selecting production thresholds.",
            "Small confidence buckets are unstable; inspect sample_count before drawing conclusions.",
        ],
    )
