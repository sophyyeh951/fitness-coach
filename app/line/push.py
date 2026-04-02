"""LINE push message utilities."""

from __future__ import annotations

import logging
import os

from linebot.v3.messaging import (
    ApiClient,
    MessagingApi,
    Configuration,
    PushMessageRequest,
    TextMessage,
    ImageMessage,
)

from app.config import LINE_CHANNEL_ACCESS_TOKEN

logger = logging.getLogger(__name__)

config = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)

# Your personal LINE user ID — set this after first webhook event
# or find it in LINE Official Account manager
LINE_USER_ID = os.getenv("LINE_USER_ID", "")


def push_text(text: str, user_id: str | None = None) -> None:
    """Send a push text message to a user."""
    target = user_id or LINE_USER_ID
    if not target:
        logger.warning("No LINE_USER_ID set, cannot push message")
        return

    with ApiClient(config) as api_client:
        api = MessagingApi(api_client)
        api.push_message(
            PushMessageRequest(
                to=target,
                messages=[TextMessage(text=text)],
            )
        )


def push_image(original_url: str, preview_url: str, user_id: str | None = None) -> None:
    """Send a push image message to a user."""
    target = user_id or LINE_USER_ID
    if not target:
        logger.warning("No LINE_USER_ID set, cannot push image")
        return

    with ApiClient(config) as api_client:
        api = MessagingApi(api_client)
        api.push_message(
            PushMessageRequest(
                to=target,
                messages=[
                    ImageMessage(
                        original_content_url=original_url,
                        preview_image_url=preview_url,
                    )
                ],
            )
        )
