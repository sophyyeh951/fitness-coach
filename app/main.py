import logging

import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.line.webhook import router as line_router
from app.health.apple_health import router as health_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def _daily_push_job():
    """Nightly job: generate and push daily summary via LINE."""
    try:
        from app.reports.daily import generate_daily_summary
        from app.line.push import push_text

        summary = await generate_daily_summary()
        push_text(summary)
        logger.info("Daily summary pushed successfully")
    except Exception:
        logger.exception("Failed to push daily summary")


async def _keep_alive():
    """Ping self every 10 minutes to prevent Render free tier from sleeping."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://fitness-coach-hv3f.onrender.com/health",
                timeout=10,
            )
            logger.debug("Keep-alive ping: %s", resp.status_code)
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(_daily_push_job, "cron", hour=21, minute=30)
    scheduler.add_job(_keep_alive, "interval", minutes=10)
    scheduler.start()
    logger.info("Scheduler started — daily summary at 21:30, keep-alive every 10min")
    yield
    scheduler.shutdown()


app = FastAPI(title="Fitness Coach", version="0.1.0", lifespan=lifespan)

app.include_router(line_router, prefix="/line")
app.include_router(health_router, prefix="/api")


@app.get("/health")
async def health_check():
    return {"status": "ok"}
