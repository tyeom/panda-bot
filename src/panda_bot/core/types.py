"""Shared types and enumerations."""

from __future__ import annotations

from enum import StrEnum


class Platform(StrEnum):
    TELEGRAM = "telegram"
    DISCORD = "discord"
