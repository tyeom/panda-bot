"""Application orchestrator - wires all components and manages lifecycle."""

from __future__ import annotations

from panda_bot.ai.client import AIClient, AnthropicClient, ClaudeCodeClient
from panda_bot.ai.handler import MessageHandler
from panda_bot.ai.tools.registry import ToolRegistry
from panda_bot.config import AppConfig, BotConfig
from panda_bot.core.bot_registry import BotRegistry
from panda_bot.core.session import SessionManager
from panda_bot.log import get_logger
from panda_bot.messenger.base import MessengerAdapter
from panda_bot.services.service_manager import ServiceManager
from panda_bot.storage.conversation_repo import ConversationRepository
from panda_bot.storage.database import Database

logger = get_logger(__name__)


class PandaBotApp:
    """Top-level application orchestrator."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.db = Database(config.storage.db_path)
        self.conversation_repo = ConversationRepository(self.db)
        self.session_manager = SessionManager(self.conversation_repo)
        self.service_manager = ServiceManager(config.services, db=self.db)
        self.tool_registry = ToolRegistry(self.service_manager)
        self.bot_registry = BotRegistry()

    async def start(self) -> None:
        """Initialize and start all components."""
        # 1. Database
        await self.db.initialize()

        # 2. Services
        await self.service_manager.start_all()

        # 3. Tools
        self.tool_registry.discover_and_register()

        # 4. Inject app context into scheduler for AI task execution
        # Build a bot_id -> AIClient factory so scheduler can create clients per bot
        bot_config_map = {b.id: b for b in self.config.bots}

        def ai_client_factory(bot_id: str) -> AIClient:
            cfg = bot_config_map.get(bot_id)
            if cfg:
                return self._create_ai_client(cfg)
            # Fallback: use first bot's config
            return self._create_ai_client(self.config.bots[0])

        self.service_manager.get_scheduler().set_app_context(
            bot_registry=self.bot_registry,
            ai_client_factory=ai_client_factory,
            tool_registry=self.tool_registry,
            session_manager=self.session_manager,
            conversation_repo=self.conversation_repo,
        )

        # 4.1 Restore persisted scheduled jobs from DB
        await self.service_manager.get_scheduler().load_persisted_jobs()

        # 5. Bot adapters
        for bot_cfg in self.config.bots:
            try:
                adapter = self._create_adapter(bot_cfg)
                ai_client = self._create_ai_client(bot_cfg)
                handler = MessageHandler(
                    adapter=adapter,
                    ai_client=ai_client,
                    session_manager=self.session_manager,
                    tool_registry=self.tool_registry,
                    bot_config=bot_cfg,
                )
                adapter.on_message(handler.handle)
                await adapter.start()
                self.bot_registry.register(bot_cfg.id, adapter)
                logger.info(
                    "bot_started",
                    bot_id=bot_cfg.id,
                    platform=bot_cfg.platform,
                    backend=bot_cfg.ai.backend,
                )
            except Exception as e:
                logger.error("bot_start_failed", bot_id=bot_cfg.id, error=str(e))

        logger.info("panda_bot_started", bot_count=len(self.bot_registry.ids()))

    async def stop(self) -> None:
        """Gracefully shut down all components."""
        for adapter in self.bot_registry.all():
            try:
                await adapter.stop()
            except Exception as e:
                logger.error("bot_stop_error", error=str(e))

        await self.service_manager.stop_all()
        await self.db.close()
        logger.info("panda_bot_stopped")

    def _create_ai_client(self, bot_cfg: BotConfig) -> AIClient:
        """Create an AI client based on the bot's backend configuration."""
        match bot_cfg.ai.backend:
            case "anthropic":
                if not self.config.anthropic:
                    raise ValueError(
                        f"Bot '{bot_cfg.id}' uses 'anthropic' backend but "
                        "no 'anthropic' section in config"
                    )
                return AnthropicClient(self.config.anthropic)
            case "claude_code":
                return ClaudeCodeClient(self.config.claude_code)
            case _:
                raise ValueError(f"Unknown AI backend: {bot_cfg.ai.backend}")

    def _create_adapter(self, cfg: BotConfig) -> MessengerAdapter:
        match cfg.platform:
            case "telegram":
                from panda_bot.messenger.telegram import TelegramAdapter

                return TelegramAdapter(cfg.id, cfg.model_dump())
            case "discord":
                from panda_bot.messenger.discord_adapter import DiscordAdapter

                return DiscordAdapter(cfg.id, cfg.model_dump())
            case _:
                raise ValueError(f"Unknown platform: {cfg.platform}")
