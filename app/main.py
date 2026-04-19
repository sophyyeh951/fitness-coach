import logging

import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.line.webhook import router as line_router
from app.health.apple_health import router as health_router
from app.config import TW_TZ

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def _morning_checkin():
    """Morning check-in: reads today's schedule and sends a quick-tap message."""
    try:
        from app.line.push import push_line_message
        from app.db.schedule import get_today_exercise, WEEKDAY_CN
        from app.config import today_tw
        from linebot.v3.messaging import TextMessage, QuickReply, QuickReplyItem, MessageAction

        today = today_tw()
        weekday_key = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"][today.weekday()]
        weekday_cn = WEEKDAY_CN[weekday_key]
        planned = get_today_exercise(today)

        if planned:
            body = f"早安 💪 今天{weekday_cn}，計畫：{planned}"
            confirm_text = f"✅ 就{planned}"
        else:
            body = f"早安 💪 今天{weekday_cn}，今天做什麼運動？"
            confirm_text = "✅ 按計畫"

        msg = TextMessage(
            text=body,
            quick_reply=QuickReply(items=[
                QuickReplyItem(action=MessageAction(label=confirm_text, text=f"今天{planned or '按計畫'}")),
                QuickReplyItem(action=MessageAction(label="🔄 換其他", text="今天換運動")),
                QuickReplyItem(action=MessageAction(label="😴 今天休息", text="/休息")),
            ]),
        )
        push_line_message(msg)
        logger.info("Morning check-in sent for %s: %s", weekday_cn, planned)
    except Exception:
        logger.exception("Failed to send morning check-in")


async def _evening_summary():
    """Evening job: generate and push daily summary via LINE."""
    try:
        from app.reports.daily import generate_daily_summary
        from app.line.push import push_text

        summary = await generate_daily_summary()
        push_text(summary)
        logger.info("Evening summary pushed successfully")
    except Exception:
        logger.exception("Failed to push evening summary")


async def _weekly_report():
    """Auto-send weekly report every Sunday at 20:00 Taiwan time."""
    try:
        from app.line.push import push_text
        from app.line.commands.report import handle_weekly_report
        report = await handle_weekly_report()
        push_text(report)
        logger.info("Weekly report sent")
    except Exception:
        logger.exception("Failed to send weekly report")


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
    # Morning check-in at 8:00 Taiwan time
    scheduler.add_job(
        _morning_checkin,
        CronTrigger(hour=8, minute=0, timezone=TW_TZ),
    )
    # Evening summary at 23:00 Taiwan time
    scheduler.add_job(
        _evening_summary,
        CronTrigger(hour=23, minute=0, timezone=TW_TZ),
    )
    scheduler.add_job(
        _weekly_report,
        CronTrigger(day_of_week="sun", hour=20, minute=0, timezone=TW_TZ),
    )
    scheduler.add_job(_keep_alive, "interval", minutes=10)
    scheduler.start()
    logger.info("Scheduler started — morning 8:00 + evening 21:30 (Taiwan time)")
    yield
    scheduler.shutdown()


app = FastAPI(title="Fitness Coach", version="0.1.0", lifespan=lifespan)

app.include_router(line_router, prefix="/line")
app.include_router(health_router, prefix="/api")


@app.get("/health")
async def health_check():
    return {"status": "ok"}
