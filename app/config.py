import os
from datetime import date, datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# Taiwan timezone (UTC+8)
TW_TZ = timezone(timedelta(hours=8))


def today_tw() -> date:
    """Get today's date in Taiwan timezone."""
    return datetime.now(TW_TZ).date()


def now_tw() -> datetime:
    """Get current datetime in Taiwan timezone."""
    return datetime.now(TW_TZ)


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(
            f"Missing required env var: {key}  "
            f"(copy .env.example to .env and fill in your keys)"
        )
    return val


LINE_CHANNEL_SECRET = _require("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = _require("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = _require("LINE_USER_ID")
GEMINI_API_KEY = _require("GEMINI_API_KEY")
SUPABASE_URL = _require("SUPABASE_URL")
SUPABASE_KEY = _require("SUPABASE_KEY")
APP_ENV = os.getenv("APP_ENV", "development")
