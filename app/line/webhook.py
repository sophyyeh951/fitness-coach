import logging

from fastapi import APIRouter, Header, Request, HTTPException
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent

from app.config import LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN
from app.line.handlers import handle_text_message, handle_image_message

logger = logging.getLogger(__name__)

router = APIRouter()

config = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(LINE_CHANNEL_SECRET)


def get_line_api() -> AsyncMessagingApi:
    return AsyncMessagingApi(AsyncApiClient(config))


@router.post("/webhook")
async def line_webhook(
    request: Request,
    x_line_signature: str = Header(...),
):
    body = (await request.body()).decode("utf-8")

    try:
        events = parser.parse(body, x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    line_api = get_line_api()

    for event in events:
        if not isinstance(event, MessageEvent):
            continue

        try:
            if isinstance(event.message, TextMessageContent):
                reply_text = await handle_text_message(event.message.text)
            elif isinstance(event.message, ImageMessageContent):
                reply_text = await handle_image_message(
                    event.message.id, line_api
                )
            else:
                reply_text = "目前支援文字和圖片訊息喔！"

            await line_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)],
                )
            )
        except Exception:
            logger.exception("Error handling LINE event")
            await line_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="抱歉，處理時發生錯誤，請稍後再試 🙏")],
                )
            )

    return "OK"
