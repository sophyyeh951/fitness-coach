import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Header, Request, HTTPException
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    PushMessageRequest,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent

from app.config import LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID
from app.line.handlers import handle_text_message, handle_image_message

logger = logging.getLogger(__name__)

router = APIRouter()

config = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(LINE_CHANNEL_SECRET)


def get_line_api() -> AsyncMessagingApi:
    return AsyncMessagingApi(AsyncApiClient(config))


async def _process_event(event: MessageEvent):
    """Process a LINE event in the background so webhook returns 200 quickly."""
    line_api = get_line_api()

    try:
        if isinstance(event.message, TextMessageContent):
            logger.info("Processing text: %s", event.message.text[:50])
            reply_text = await handle_text_message(event.message.text)
        elif isinstance(event.message, ImageMessageContent):
            logger.info("Processing image: %s", event.message.id)
            reply_text = await handle_image_message(event.message.id, line_api)
        else:
            reply_text = "目前支援文字和圖片訊息喔！"

        logger.info("Got reply (%d chars), sending...", len(reply_text))

        # Try reply first (free), fall back to push if token expired
        try:
            await line_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)],
                )
            )
            logger.info("Reply sent successfully")
        except Exception:
            logger.warning("Reply token expired, using push message")
            await line_api.push_message(
                PushMessageRequest(
                    to=LINE_USER_ID,
                    messages=[TextMessage(text=reply_text)],
                )
            )
            logger.info("Push message sent successfully")

    except Exception:
        logger.exception("Error handling LINE event")
        try:
            await line_api.push_message(
                PushMessageRequest(
                    to=LINE_USER_ID,
                    messages=[TextMessage(text="抱歉，處理時發生錯誤，請稍後再試 🙏")],
                )
            )
        except Exception:
            logger.exception("Failed to send error push message")


@router.post("/webhook")
async def line_webhook(
    request: Request,
    x_line_signature: str = Header(...),
):
    body = (await request.body()).decode("utf-8")
    logger.info("Webhook received (%d bytes)", len(body))

    try:
        events = parser.parse(body, x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Process events in background tasks so we return 200 immediately
    for event in events:
        if isinstance(event, MessageEvent):
            asyncio.create_task(_process_event(event))

    return "OK"


@router.get("/test-reply")
async def test_reply():
    """Test endpoint: send a test message via push to verify LINE API works."""
    line_api = get_line_api()
    try:
        await line_api.push_message(
            PushMessageRequest(
                to=LINE_USER_ID,
                messages=[TextMessage(text="✅ 測試成功！小健教練上線了！")],
            )
        )
        return {"status": "ok", "message": "Push sent"}
    except Exception as e:
        logger.exception("Test push failed")
        return {"status": "error", "message": str(e)}
