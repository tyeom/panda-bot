"""Discord messenger adapter using discord.py v2+."""

from __future__ import annotations

import asyncio
import io
from datetime import datetime, timezone
from typing import Any

import discord
from discord.ext import commands

from panda_bot.core.types import Platform
from panda_bot.log import get_logger
from panda_bot.messenger.base import MessengerAdapter
from panda_bot.messenger.models import Attachment, IncomingMessage, OutgoingMessage

logger = get_logger(__name__)


class DiscordAdapter(MessengerAdapter):
    """Discord bot adapter using discord.py."""

    def __init__(self, bot_id: str, config: dict):
        super().__init__(bot_id, config)
        intents = discord.Intents.default()
        intents.message_content = True
        self._bot = commands.Bot(command_prefix="!", intents=intents)
        self._task: asyncio.Task[Any] | None = None
        self._ready = asyncio.Event()

        # Register event handlers
        @self._bot.event
        async def on_ready() -> None:
            logger.info("discord_bot_ready", user=str(self._bot.user), bot_id=self.bot_id)
            self._ready.set()

        @self._bot.event
        async def on_message(message: discord.Message) -> None:
            if message.author == self._bot.user:
                return
            if message.author.bot:
                return
            await self._on_discord_message(message)

    @property
    def platform_name(self) -> str:
        return Platform.DISCORD

    async def start(self) -> None:
        token = self.config.get("token", "")
        if not token:
            raise ValueError(f"Discord bot token not configured for bot '{self.bot_id}'")

        self._task = asyncio.create_task(self._bot.start(token))
        # Wait for the bot to be ready
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=30)
        except asyncio.TimeoutError:
            logger.warning("discord_ready_timeout", bot_id=self.bot_id)

        logger.info("discord_adapter_started", bot_id=self.bot_id)

    async def stop(self) -> None:
        await self._bot.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("discord_adapter_stopped", bot_id=self.bot_id)

    async def send_message(self, message: OutgoingMessage) -> None:
        channel = self._bot.get_channel(int(message.chat_id))
        if channel is None:
            # Try fetching the channel
            try:
                channel = await self._bot.fetch_channel(int(message.chat_id))
            except Exception:
                logger.error("discord_channel_not_found", chat_id=message.chat_id)
                return

        if not isinstance(channel, (discord.TextChannel, discord.DMChannel, discord.Thread)):
            return

        # Build file attachments
        files: list[discord.File] = []
        if message.attachments:
            for att in message.attachments:
                files.append(discord.File(io.BytesIO(att.data), filename=att.filename))

        # Discord message limit is 2000 chars
        text = message.text
        if files:
            # Send first chunk with files
            chunk = text[:2000] if text else None
            await channel.send(content=chunk, files=files)
            text = text[2000:] if text else ""

        while text:
            chunk = text[:2000]
            text = text[2000:]
            await channel.send(chunk)

    async def send_typing_indicator(self, chat_id: str) -> None:
        channel = self._bot.get_channel(int(chat_id))
        if channel and hasattr(channel, "typing"):
            await channel.typing()  # type: ignore[union-attr]

    async def _on_discord_message(self, message: discord.Message) -> None:
        """Handle incoming Discord message (text and/or images)."""
        if not self._message_callback:
            return

        text = message.content or ""
        attachments: list[Attachment] = []

        # Download all attachments (images, documents, etc.)
        for att in message.attachments:
            try:
                data = await att.read()
                media_type = att.content_type or "application/octet-stream"
                attachments.append(
                    Attachment(data=data, media_type=media_type, filename=att.filename)
                )
            except Exception as e:
                logger.warning("discord_attachment_download_error", error=str(e))

        # Skip if no text and no attachments
        if not text and not attachments:
            return

        incoming = IncomingMessage(
            platform=Platform.DISCORD,
            bot_id=self.bot_id,
            chat_id=str(message.channel.id),
            user_id=str(message.author.id),
            user_display_name=message.author.display_name,
            text=text,
            timestamp=message.created_at or datetime.now(timezone.utc),
            reply_to_message_id=(
                str(message.reference.message_id) if message.reference else None
            ),
            attachments=attachments,
        )

        try:
            await self._message_callback(incoming)
        except Exception as e:
            logger.error(
                "discord_handler_error", error=str(e), channel_id=str(message.channel.id)
            )
