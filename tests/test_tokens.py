"""Tests for context token estimation and budget trimming."""
from __future__ import annotations

from core import tokens


def test_empty_text_is_zero_tokens():
    assert tokens.estimate_tokens("") == 0


def test_estimate_grows_with_length():
    assert tokens.estimate_tokens("x" * 400) > tokens.estimate_tokens("x" * 40)


def test_short_text_is_at_least_one_token():
    assert tokens.estimate_tokens("a") == 1


def test_message_tokens_handles_parts_lists():
    msg = {"role": "user", "content": [{"text": "hello there friend"}]}
    assert tokens.message_tokens(msg) > 0


def test_message_tokens_survives_unserialisable_content():
    assert tokens.message_tokens({"role": "user", "content": [object()]}) > 0


def test_conversation_tokens_is_the_sum():
    msgs = [{"role": "user", "content": "a" * 400}, {"role": "model", "content": "b" * 400}]
    assert tokens.conversation_tokens(msgs) == 200


def test_no_trim_when_within_budget():
    msgs = [{"role": "user", "content": "short"}]
    out, dropped = tokens.trim_to_budget(msgs, 1000)
    assert dropped == 0 and out == msgs


def test_trim_drops_oldest_and_reports_count():
    msgs = [{"role": "user", "content": "x" * 400} for _ in range(10)]
    out, dropped = tokens.trim_to_budget(msgs, 300)
    assert dropped > 0
    assert len(out) == 10 - dropped
    assert tokens.conversation_tokens(out) <= 300


def test_trim_always_keeps_the_original_ask_and_latest():
    first = {"role": "user", "content": "THE ORIGINAL ASK " + "x" * 400}
    last = {"role": "user", "content": "LATEST " + "y" * 400}
    msgs = [first] + [{"role": "model", "content": "z" * 4000} for _ in range(5)] + [last]
    out, _ = tokens.trim_to_budget(msgs, 250)
    assert out[0] is first
    assert out[-1] is last


def test_zero_budget_is_a_no_op():
    msgs = [{"role": "user", "content": "hi"}]
    assert tokens.trim_to_budget(msgs, 0) == (msgs, 0)


def test_empty_conversation_is_safe():
    assert tokens.trim_to_budget([], 100) == ([], 0)
