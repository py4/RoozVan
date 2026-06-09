"""Shared helpers for live pipeline progress logging."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeAlias

ProgressLogger: TypeAlias = Callable[[str], None]


def short_title(title: str | None, *, max_len: int = 72) -> str:
    text = (title or "untitled").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def log_progress(logger: ProgressLogger | None, message: str) -> None:
    if logger is not None:
        logger(message)
