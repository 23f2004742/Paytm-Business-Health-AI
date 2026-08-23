"""Business Health Score and the raw metric set behind it."""

from __future__ import annotations

from fastapi import APIRouter

from ..services.anomaly_detection import anomalies_payload
from ..services.transaction_analytics import metrics_payload
from .deps import contexts, scored_health

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health-score")
def get_health_score() -> dict:
    ctx, prev = contexts()
    return scored_health(ctx, prev)


@router.get("/metrics")
def get_metrics() -> dict:
    ctx, _ = contexts()
    return metrics_payload(ctx)


@router.get("/anomalies")
def get_anomalies() -> dict:
    ctx, _ = contexts()
    return anomalies_payload(ctx)
