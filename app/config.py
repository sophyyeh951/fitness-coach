import os
from dotenv import load_dotenv

load_dotenv()


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
GEMINI_API_KEY = _require("GEMINI_API_KEY")
SUPABASE_URL = _require("SUPABASE_URL")
SUPABASE_KEY = _require("SUPABASE_KEY")
APP_ENV = os.getenv("APP_ENV", "development")
