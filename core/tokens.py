"""Token accounting and context budgeting.

config.MAX_CONTEXT_TOKENS existed since v1.0 but nothing ever enforced it, so a
long tool-heavy session could silently grow until the provider rejected the
request. These helpers give the agent loop a cheap, dependency-free estimate
and a way to shed the oldest turns before that happens.

The estimate is deliberately approximate (~4 characters per token, the usual
rule of thumb for English + code). It never needs to be exact — it only needs
to be monotonic and on the safe side.
"""
from __future__ import annotations

import json

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Rough token count for a string. Never negative."""
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def message_tokens(message: dict) -> int:
    """Estimated tokens for one internal-format message (str or parts list)."""
    content = message.get("content", "")
    if isinstance(content, str):
        return estimate_tokens(content)
    try:
        return estimate_tokens(json.dumps(content, default=str))
    except (TypeError, ValueError):
        return estimate_tokens(str(content))


def conversation_tokens(messages: list[dict]) -> int:
    """Estimated tokens for a whole message list."""
    return sum(message_tokens(m) for m in messages)


def trim_to_budget(messages: list[dict], max_tokens: int) -> tuple[list[dict], int]:
    """Drop the oldest messages until the estimate fits `max_tokens`.

    The first user message (the original ask) and the most recent message are
    always kept, so the model never loses the goal or the latest observation.
    Returns (messages, dropped_count).
    """
    if max_tokens <= 0 or not messages:
        return messages, 0
    if conversation_tokens(messages) <= max_tokens:
        return messages, 0

    anchor = messages[0]
    tail = messages[1:]
    dropped = 0
    while tail and conversation_tokens([anchor, *tail]) > max_tokens and len(tail) > 1:
        tail.pop(0)
        dropped += 1
    return [anchor, *tail], dropped
