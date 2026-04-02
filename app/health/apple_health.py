"""API endpoint for receiving Apple Health data from iOS Shortcuts."""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException
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
async def receive_health_data(data: HealthData):
    """
    Receive health data from iOS Shortcuts automation.

    The iOS Shortcut reads Apple Health data daily and POSTs here.
    PICOOC data flows: PICOOC app → Apple Health → this endpoint.
    """
    try:
        metrics = data.dict(exclude_none=True)
        result = db.upsert_body_metrics(metrics)
        logger.info("Saved health data for %s: %s", data.date, metrics)
        return {"status": "ok", "saved": result}
    except Exception:
        logger.exception("Failed to save health data")
        raise HTTPException(status_code=500, detail="Failed to save health data")
