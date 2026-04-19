import asyncio
import logging

from fastapi import APIRouter, Header, Request, HTTPException
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    AsyncMessagingApiBlob,
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


def get_line_blob_api() -> AsyncMessagingApiBlob:
    return AsyncMessagingApiBlob(AsyncApiClient(config))


def _split_message(text: str, max_len: int = 4500) -> list:
    """Split a long message into chunks, breaking at newlines."""
    if len(text) <= max_len:
        return [text]

    parts = []
    while text:
        if len(text) <= max_len:
            parts.append(text)
            break
        # Find last newline before max_len
        cut = text.rfind("\n", 0, max_len)
        if cut == -1:
            cut = max_len
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")

    return parts


async def _process_event(event: MessageEvent):
    """Process a LINE event in the background so webhook returns 200 quickly."""
    from linebot.v3.messaging import Message as LineMessage

    line_api = get_line_api()

    try:
        if isinstance(event.message, TextMessageContent):
            logger.info("Processing text: %s", event.message.text[:50])
            user_id = event.source.user_id if hasattr(event.source, "user_id") else LINE_USER_ID
            result = await handle_text_message(event.message.text, user_id)
        elif isinstance(event.message, ImageMessageContent):
            logger.info("Processing image: %s", event.message.id)
            user_id = event.source.user_id if hasattr(event.source, "user_id") else LINE_USER_ID
            blob_api = get_line_blob_api()
            result = await handle_image_message(event.message.id, blob_api, user_id)
        else:
            result = "目前支援文字和圖片訊息喔！"

        result_preview = result.text[:50] if hasattr(result, 'text') else str(result)[:50]
        logger.info("Got reply: %s..., sending...", result_preview)

        if isinstance(result, LineMessage):
            reply_messages = [result]
        else:
            parts = _split_message(result, max_len=4500)
            reply_messages = [TextMessage(text=p) for p in parts[:5]]

        # Try reply first (free), fall back to push if token expired
        try:
            await line_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=reply_messages,
                )
            )
            logger.info("Reply sent successfully (%d parts)", len(reply_messages))
        except Exception:
            logger.warning("Reply token expired, using push message")
            for msg in reply_messages:
                await line_api.push_message(
                    PushMessageRequest(
                        to=LINE_USER_ID,
                        messages=[msg],
                    )
                )
            logger.info("Push message sent successfully (%d parts)", len(reply_messages))

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
