"""Telegram messenger adapter using python-telegram-bot v21+."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, MessageHandler as TGMessageHandler, filters

from panda_bot.log import get_logger
from panda_bot.messenger.base import MessengerAdapter
from panda_bot.messenger.models import Attachment, IncomingMessage, OutgoingMessage
from panda_bot.core.types import Platform

logger = get_logger(__name__)


class TelegramAdapter(MessengerAdapter):
    """Telegram bot adapter using python-telegram-bot."""

    def __init__(self, bot_id: str, config: dict):
        super().__init__(bot_id, config)
        self._app: Application | None = None  # type: ignore[type-arg]
        self._task: asyncio.Task[Any] | None = None

    @property
    def platform_name(self) -> str:
        return Platform.TELEGRAM

    async def start(self) -> None:
        token = self.config.get("token", "")
        if not token:
            raise ValueError(f"Telegram bot token not configured for bot '{self.bot_id}'")

        self._app = Application.builder().token(token).build()

        # Register message handler
        self._app.add_handler(
            TGMessageHandler(filters.TEXT & ~filters.COMMAND, self._on_telegram_message)
        )
        # Also handle /reset and /search commands as text
        self._app.add_handler(
            TGMessageHandler(filters.COMMAND, self._on_telegram_message)
        )
        # Handle photo messages
        self._app.add_handler(
            TGMessageHandler(filters.PHOTO, self._on_telegram_message)
        )

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)  # type: ignore[union-attr]
        logger.info("telegram_adapter_started", bot_id=self.bot_id)

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()  # type: ignore[union-attr]
            await self._app.stop()
            await self._app.shutdown()
            logger.info("telegram_adapter_stopped", bot_id=self.bot_id)

    async def send_message(self, message: OutgoingMessage) -> None:
        if not self._app or not self._app.bot:
            return

        chat_id = int(message.chat_id)
        reply_id = int(message.reply_to_message_id) if message.reply_to_message_id else None

        # Send image attachments
        if message.attachments:
            for att in message.attachments:
                if att.media_type.startswith("image/"):
                    await self._app.bot.send_photo(
                        chat_id=chat_id,
                        photo=att.data,
                        caption=message.text or None,
                        reply_to_message_id=reply_id,
                    )
            return

        parse_mode = None
        if message.parse_mode == "markdown":
            parse_mode = "MarkdownV2"
        elif message.parse_mode == "html":
            parse_mode = "HTML"

        await self._app.bot.send_message(
            chat_id=chat_id,
            text=message.text,
            parse_mode=parse_mode,
            reply_to_message_id=reply_id,
        )

    async def send_typing_indicator(self, chat_id: str) -> None:
        if self._app and self._app.bot:
            await self._app.bot.send_chat_action(
                chat_id=int(chat_id), action=ChatAction.TYPING
            )

    async def _on_telegram_message(self, update: Update, context: Any) -> None:
        """Handle incoming Telegram message (text and/or photo)."""
        if not update.message:
            return
        if not self._message_callback:
            return

        msg = update.message
        text = msg.text or msg.caption or ""
        attachments: list[Attachment] = []

        # Download photo if present (highest resolution = last element)
        if msg.photo:
            try:
                photo = msg.photo[-1]
                tg_file = await photo.get_file()
                photo_bytes = await tg_file.download_as_bytearray()
                attachments.append(
                    Attachment(data=bytes(photo_bytes), media_type="image/jpeg", filename="photo.jpg")
                )
            except Exception as e:
                logger.warning("telegram_photo_download_error", error=str(e))

        # Skip if no text and no attachments
        if not text and not attachments:
            return

        incoming = IncomingMessage(
            platform=Platform.TELEGRAM,
            bot_id=self.bot_id,
            chat_id=str(msg.chat_id),
            user_id=str(msg.from_user.id) if msg.from_user else "unknown",
            user_display_name=(
                msg.from_user.full_name if msg.from_user else "Unknown"
            ),
            text=text,
            timestamp=msg.date or datetime.now(timezone.utc),
            reply_to_message_id=(
                str(msg.reply_to_message.message_id) if msg.reply_to_message else None
            ),
            attachments=attachments,
        )

        try:
            await self._message_callback(incoming)
        except Exception as e:
            logger.error("telegram_handler_error", error=str(e), chat_id=str(msg.chat_id))
