import asyncio
import logging

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run daily summary at 21:30 local time
    scheduler.add_job(_daily_push_job, "cron", hour=21, minute=30)
    scheduler.start()
    logger.info("Scheduler started — daily summary at 21:30")
    yield
    scheduler.shutdown()


app = FastAPI(title="Fitness Coach", version="0.1.0", lifespan=lifespan)

app.include_router(line_router, prefix="/line")
app.include_router(health_router, prefix="/api")


@app.get("/health")
async def health_check():
    return {"status": "ok"}
