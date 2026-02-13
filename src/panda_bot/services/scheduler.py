"""APScheduler-based background task scheduler service."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from panda_bot.config import SchedulerServiceConfig
from panda_bot.log import get_logger
from panda_bot.services.base import Service

if TYPE_CHECKING:
    from panda_bot.ai.client import AIClient
    from panda_bot.ai.tools.registry import ToolRegistry
    from panda_bot.core.bot_registry import BotRegistry
    from panda_bot.core.session import SessionManager
    from panda_bot.messenger.models import OutgoingMessage
    from panda_bot.storage.conversation_repo import ConversationRepository

logger = get_logger(__name__)


class SchedulerService(Service):
    """Background task scheduler using APScheduler."""

    def __init__(self, config: SchedulerServiceConfig):
        self._config = config
        self._scheduler = AsyncIOScheduler(timezone=config.timezone)
        # App context for AI tasks (set after app initialization)
        self._bot_registry: BotRegistry | None = None
        self._ai_client_factory: Callable[[str], AIClient] | None = None
        self._tool_registry: ToolRegistry | None = None
        self._session_manager: SessionManager | None = None
        self._conversation_repo: ConversationRepository | None = None

    def set_app_context(
        self,
        bot_registry: BotRegistry,
        ai_client_factory: Callable[[str], AIClient],
        tool_registry: ToolRegistry,
        session_manager: SessionManager,
        conversation_repo: ConversationRepository,
    ) -> None:
        """Inject app-level dependencies for AI task execution."""
        self._bot_registry = bot_registry
        self._ai_client_factory = ai_client_factory
        self._tool_registry = tool_registry
        self._session_manager = session_manager
        self._conversation_repo = conversation_repo
        logger.info("scheduler_app_context_set")

    @property
    def service_name(self) -> str:
        return "scheduler"

    async def start(self) -> None:
        self._scheduler.start()
        logger.info("scheduler_started", timezone=self._config.timezone)

    async def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")

    async def health_check(self) -> bool:
        return self._scheduler.running

    def add_cron_job(
        self,
        cron_expr: str,
        callback: Callable[..., Coroutine[Any, Any, None]],
        job_id: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Add a cron-based recurring job. Returns the job ID."""
        job_id = job_id or uuid.uuid4().hex[:12]
        parts = cron_expr.split()
        trigger = CronTrigger(
            minute=parts[0] if len(parts) > 0 else "*",
            hour=parts[1] if len(parts) > 1 else "*",
            day=parts[2] if len(parts) > 2 else "*",
            month=parts[3] if len(parts) > 3 else "*",
            day_of_week=parts[4] if len(parts) > 4 else "*",
        )
        self._scheduler.add_job(callback, trigger, id=job_id, kwargs=kwargs)
        logger.info("cron_job_added", job_id=job_id, cron=cron_expr)
        return job_id

    def add_one_shot_job(
        self,
        run_at: datetime,
        callback: Callable[..., Coroutine[Any, Any, None]],
        job_id: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Add a one-time job at a specific datetime. Returns the job ID."""
        job_id = job_id or uuid.uuid4().hex[:12]
        trigger = DateTrigger(run_date=run_at)
        self._scheduler.add_job(callback, trigger, id=job_id, kwargs=kwargs)
        logger.info("one_shot_job_added", job_id=job_id, run_at=str(run_at))
        return job_id

    def add_ai_cron_job(
        self,
        cron_expr: str,
        bot_id: str,
        chat_id: str,
        task_prompt: str,
        job_id: Optional[str] = None,
    ) -> str:
        """Add a cron job that runs an AI task and sends results to a chat."""
        return self.add_cron_job(
            cron_expr=cron_expr,
            callback=self._run_ai_task,
            job_id=job_id,
            bot_id=bot_id,
            chat_id=chat_id,
            task_prompt=task_prompt,
        )

    def add_ai_one_shot_job(
        self,
        run_at: datetime,
        bot_id: str,
        chat_id: str,
        task_prompt: str,
        job_id: Optional[str] = None,
    ) -> str:
        """Add a one-shot job that runs an AI task and sends results to a chat."""
        return self.add_one_shot_job(
            run_at=run_at,
            callback=self._run_ai_task,
            job_id=job_id,
            bot_id=bot_id,
            chat_id=chat_id,
            task_prompt=task_prompt,
        )

    async def _run_ai_task(self, bot_id: str, chat_id: str, task_prompt: str) -> None:
        """Execute an AI task and send the result to a specific chat."""
        from panda_bot.ai.conversation import build_messages
        from panda_bot.ai.tool_runner import run_tool_loop
        from panda_bot.messenger.models import OutgoingMessage
        from panda_bot.storage.models import ConversationRecord

        if not all([self._bot_registry, self._ai_client_factory, self._tool_registry,
                     self._session_manager, self._conversation_repo]):
            logger.error("scheduler_ai_task_no_context", bot_id=bot_id)
            return

        # Get adapter for sending messages
        adapter = self._bot_registry.get(bot_id)
        if not adapter:
            logger.error("scheduler_ai_task_bot_not_found", bot_id=bot_id)
            return

        logger.info("scheduler_ai_task_start", bot_id=bot_id, chat_id=chat_id)

        try:
            # Create AI client for this bot
            ai_client = self._ai_client_factory(bot_id)

            # Use a dedicated session for scheduled tasks
            session_id = f"scheduled_{bot_id}_{chat_id}"

            # Save the task prompt as user message
            await self._conversation_repo.save_turn(
                ConversationRecord(
                    bot_id=bot_id,
                    session_id=session_id,
                    chat_id=chat_id,
                    role="user",
                    content=task_prompt,
                )
            )

            # Build messages (only use the task prompt, not full history)
            messages = [{"role": "user", "content": task_prompt}]

            if ai_client.supports_tool_loop:
                # Anthropic API: use tool runner
                tools = self._tool_registry.all_tools()
                response_text = await run_tool_loop(
                    ai_client=ai_client,
                    tool_registry=self._tool_registry,
                    conversation_repo=self._conversation_repo,
                    messages=messages,
                    system="You are a helpful assistant executing a scheduled task. Be concise.",
                    model="",
                    max_tokens=4096,
                    temperature=0.7,
                    tools=tools,
                    bot_id=bot_id,
                    session_id=session_id,
                    chat_id=chat_id,
                )
            else:
                # Claude Code CLI: single call
                response = await ai_client.chat(
                    system="You are a helpful assistant executing a scheduled task. Be concise.",
                    messages=messages,
                )
                response_text = response.text

                await self._conversation_repo.save_turn(
                    ConversationRecord(
                        bot_id=bot_id,
                        session_id=session_id,
                        chat_id=chat_id,
                        role="assistant",
                        content=response_text,
                    )
                )

            # Send result to chat
            if response_text:
                # Split long messages
                max_len = 4000
                text = response_text
                while text:
                    chunk = text[:max_len]
                    text = text[max_len:]
                    await adapter.send_message(
                        OutgoingMessage(chat_id=chat_id, text=chunk)
                    )

            logger.info("scheduler_ai_task_done", bot_id=bot_id, chat_id=chat_id)

        except Exception as e:
            logger.error("scheduler_ai_task_error", bot_id=bot_id, error=str(e))
            try:
                await adapter.send_message(
                    OutgoingMessage(
                        chat_id=chat_id,
                        text=f"Scheduled task error: {e}",
                    )
                )
            except Exception:
                pass

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job. Returns True if found and removed."""
        try:
            self._scheduler.remove_job(job_id)
            logger.info("job_removed", job_id=job_id)
            return True
        except Exception:
            return False

    def list_jobs(self) -> list[dict[str, Any]]:
        """List all scheduled jobs."""
        jobs = []
        for job in self._scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": str(job.next_run_time) if job.next_run_time else None,
                    "trigger": str(job.trigger),
                }
            )
        return jobs
