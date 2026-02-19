"""Scheduler tool for creating and managing scheduled tasks."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from panda_bot.ai.tools.base import Tool
from panda_bot.log import get_logger
from panda_bot.services.scheduler import SchedulerService

logger = get_logger(__name__)


class SchedulerTool(Tool):
    """Tool for scheduling recurring or one-shot tasks with AI execution."""

    def __init__(self, scheduler_service: SchedulerService):
        super().__init__()
        self._scheduler = scheduler_service
        # Current conversation context (set before each tool execution)
        self._current_bot_id: str = ""
        self._current_chat_id: str = ""

    def set_context(self, bot_id: str, chat_id: str) -> None:
        """Set the current conversation context for auto-filling bot_id/chat_id."""
        self._current_bot_id = bot_id
        self._current_chat_id = chat_id

    @property
    def name(self) -> str:
        return "scheduler"

    @property
    def description(self) -> str:
        return (
            "Schedule AI tasks to run at specific times or on a cron schedule. "
            "Scheduled tasks will execute the given prompt using AI and send the result "
            "back to the current chat. Can also list and remove scheduled tasks."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add_cron", "add_once", "list", "remove"],
                    "description": (
                        "'add_cron' = add recurring cron job, "
                        "'add_once' = add one-time job, "
                        "'list' = list all jobs, "
                        "'remove' = remove a job by ID"
                    ),
                },
                "cron_expr": {
                    "type": "string",
                    "description": "Cron expression (minute hour day month weekday) for add_cron",
                },
                "run_at": {
                    "type": "string",
                    "description": "ISO datetime string for add_once (e.g. '2025-01-15T14:30:00')",
                },
                "task_prompt": {
                    "type": "string",
                    "description": (
                        "The AI prompt to execute when the job runs. "
                        "The result will be sent to the current chat. "
                        "Example: 'Check nate.com mail for new emails and summarize them.'"
                    ),
                },
                "job_id": {
                    "type": "string",
                    "description": "Job ID for remove action",
                },
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action", "list")

        try:
            match action:
                case "add_cron":
                    cron_expr = kwargs.get("cron_expr", "")
                    task_prompt = kwargs.get("task_prompt", "")
                    if not cron_expr:
                        return "Error: cron_expr is required for add_cron"
                    if not task_prompt:
                        return "Error: task_prompt is required for add_cron"

                    bot_id = self._current_bot_id
                    chat_id = self._current_chat_id
                    if not bot_id or not chat_id:
                        return "Error: no conversation context available"

                    job_id = self._scheduler.add_ai_cron_job(
                        cron_expr=cron_expr,
                        bot_id=bot_id,
                        chat_id=chat_id,
                        task_prompt=task_prompt,
                    )
                    return (
                        f"AI cron job created with ID: {job_id}\n"
                        f"Schedule: {cron_expr}\n"
                        f"Task: {task_prompt}\n"
                        f"Results will be sent to this chat."
                    )

                case "add_once":
                    run_at_str = kwargs.get("run_at", "")
                    task_prompt = kwargs.get("task_prompt", "")
                    if not run_at_str:
                        return "Error: run_at is required for add_once"
                    if not task_prompt:
                        return "Error: task_prompt is required for add_once"

                    bot_id = self._current_bot_id
                    chat_id = self._current_chat_id
                    if not bot_id or not chat_id:
                        return "Error: no conversation context available"

                    run_at = datetime.fromisoformat(run_at_str)
                    job_id = self._scheduler.add_ai_one_shot_job(
                        run_at=run_at,
                        bot_id=bot_id,
                        chat_id=chat_id,
                        task_prompt=task_prompt,
                    )
                    return (
                        f"AI one-shot job created with ID: {job_id}\n"
                        f"Scheduled for: {run_at_str}\n"
                        f"Task: {task_prompt}\n"
                        f"Result will be sent to this chat."
                    )

                case "list":
                    jobs = self._scheduler.list_jobs()
                    if not jobs:
                        return "No scheduled jobs."
                    return json.dumps(jobs, indent=2, default=str)

                case "remove":
                    job_id = kwargs.get("job_id", "")
                    if not job_id:
                        return "Error: job_id is required for remove"
                    removed = self._scheduler.remove_job(job_id)
                    if removed:
                        return f"Job {job_id} removed successfully."
                    return f"Job {job_id} not found."

                case _:
                    return f"Error: unknown action '{action}'"

        except Exception as e:
            return f"Scheduler error: {e}"
