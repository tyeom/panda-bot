"""Configuration loader with YAML parsing, env-var interpolation, and Pydantic validation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class AIConfig(BaseModel):
    backend: str = "anthropic"  # "anthropic" | "claude_code"
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096
    system_prompt: str = ""
    temperature: float = 0.7
    tools: list[str] = Field(default_factory=list)


class BotConfig(BaseModel):
    id: str
    platform: str
    token: str
    guild_ids: list[int] = Field(default_factory=list)
    ai: AIConfig = Field(default_factory=AIConfig)


class AnthropicConfig(BaseModel):
    api_key: str
    base_url: Optional[str] = None
    max_retries: int = 3
    timeout: int = 120


class ClaudeCodeConfig(BaseModel):
    cli_path: str = "claude"
    model: str = "sonnet"  # e.g. "sonnet", "opus", "haiku"
    timeout: int = 300
    allowed_tools: list[str] = Field(default_factory=list)
    api_key: Optional[str] = None  # Anthropic API key; if set, uses API auth instead of OAuth
    permission_mode: str = "bypassPermissions"  # "default" | "bypassPermissions"


class BrowserServiceConfig(BaseModel):
    headless: bool = True
    browser_type: str = "chromium"
    timeout_ms: int = 30000


class SchedulerServiceConfig(BaseModel):
    timezone: str = "Asia/Seoul"
    max_concurrent_jobs: int = 5


class ServicesConfig(BaseModel):
    browser: BrowserServiceConfig = Field(default_factory=BrowserServiceConfig)
    scheduler: SchedulerServiceConfig = Field(default_factory=SchedulerServiceConfig)


class StorageConfig(BaseModel):
    db_path: str = "./data/panda_bot.db"
    fts_enabled: bool = True


class AppConfig(BaseModel):
    log_level: str = "INFO"
    data_dir: str = "./data"
    bots: list[BotConfig]
    anthropic: Optional[AnthropicConfig] = None
    claude_code: ClaudeCodeConfig = Field(default_factory=ClaudeCodeConfig)
    services: ServicesConfig = Field(default_factory=ServicesConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)


_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def _interpolate_env_vars(text: str, extra: dict[str, str] | None = None) -> str:
    """Replace ${VAR_NAME} patterns with environment variable values."""

    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        if extra and var_name in extra:
            return extra[var_name]
        value = os.environ.get(var_name)
        if value is None:
            return match.group(0)
        return value

    return _ENV_VAR_PATTERN.sub(_replace, text)


def load_config(config_path: str | Path = "config.yaml", env_path: str | Path = ".env") -> AppConfig:
    """Load and validate configuration from YAML file with env-var interpolation."""
    env_file = Path(env_path)
    if env_file.exists():
        load_dotenv(env_file)

    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_file}")

    raw_text = config_file.read_text(encoding="utf-8")

    # First pass: extract data_dir for self-referencing
    raw_data = yaml.safe_load(raw_text)
    data_dir = raw_data.get("data_dir", "./data")
    data_dir = _interpolate_env_vars(data_dir)

    # Second pass: interpolate all env vars
    interpolated = _interpolate_env_vars(raw_text, extra={"data_dir": data_dir})
    data = yaml.safe_load(interpolated)

    return AppConfig(**data)
