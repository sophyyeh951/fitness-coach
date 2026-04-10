"""API endpoint for receiving Apple Health data from iOS Shortcuts."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.db import queries as db

logger = logging.getLogger(__name__)

router = APIRouter()


class HealthData(BaseModel):
    date: date
    weight: Optional[float] = None
    body_fat_pct: Optional[float] = None
    muscle_mass: Optional[float] = None
    bmi: Optional[float] = None
    steps: Optional[int] = None
    active_calories: Optional[float] = None
    resting_heart_rate: Optional[int] = None


@router.post("/health-data")
async def receive_health_data(request: Request):
    """
    Receive health data from iOS Shortcuts automation.

    The iOS Shortcut reads Apple Health data daily and POSTs here.
    PICOOC data flows: PICOOC app → Apple Health → this endpoint.
    """
    # Log raw body for debugging
    raw_body = await request.json()
    logger.info("Raw health data received: %s", raw_body)

    try:
        data = HealthData(**raw_body)
    except Exception as e:
        logger.error("Validation error: %s", e)
        return {"status": "error", "detail": str(e), "received": raw_body}

    try:
        metrics = data.dict(exclude_none=True)
        metrics["date"] = data.date.isoformat()
        result = db.upsert_body_metrics(metrics)
        logger.info("Saved health data for %s: %s", data.date, metrics)
        return {"status": "ok", "saved": result}
    except Exception as e:
        logger.exception("Failed to save health data")
        return {"status": "error", "detail": str(e), "received": raw_body}


@router.get("/health-debug")
async def health_debug():
    """Debug endpoint to check what data exists in body_metrics."""
    try:
        from datetime import timedelta
        from app.config import today_tw
        today = today_tw()
        metrics = db.get_body_metrics_range(today - timedelta(days=7), today)
        return {"status": "ok", "recent_metrics": metrics}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
