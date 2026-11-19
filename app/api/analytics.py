from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import enforce_rate_limit, get_session
from app.db import repository
from app.schemas.analytics import AnalyticsSummary, CalibrationLabel, CalibrationReport
from app.services import analytics

router = APIRouter(
    prefix="/api/v1/analytics",
    tags=["Analytics"],
    dependencies=[Depends(enforce_rate_limit)],
)


@router.get("/summary", response_model=AnalyticsSummary, summary="Aggregate ticket and review metrics")
async def summary(session: AsyncSession = Depends(get_session)) -> AnalyticsSummary:
    return analytics.build_summary(await repository.analytics_counts(session))


@router.get(
    "/calibration",
    response_model=CalibrationReport,
    summary="Compare confidence with the latest human labels",
)
async def calibration(
    bins: int = Query(5, ge=2, le=20),
    model: str | None = Query(None, max_length=50),
    policy_version: str | None = Query(None, max_length=50),
    session: AsyncSession = Depends(get_session),
) -> CalibrationReport:
    rows = await repository.latest_review_labels(
        session, model=model, policy_version=policy_version
    )
    return analytics.build_calibration_report(rows, bins)


@router.get(
    "/calibration/labels",
    response_model=list[CalibrationLabel],
    summary="Export sanitized latest human labels",
)
async def calibration_labels(
    model: str | None = Query(None, max_length=50),
    policy_version: str | None = Query(None, max_length=50),
    session: AsyncSession = Depends(get_session),
) -> list[CalibrationLabel]:
    rows = await repository.latest_review_labels(
        session, model=model, policy_version=policy_version
    )
    return [analytics.to_label(row) for row in rows]
