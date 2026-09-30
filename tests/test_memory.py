"""Tests for the SQLite memory layer."""
from __future__ import annotations


def test_messages_round_trip_in_order(tmp_memory):
    s = "sess-a"
    tmp_memory.add_message(s, "user", "hello")
    tmp_memory.add_message(s, "model", "hi Boss")
    hist = tmp_memory.get_history(s)
    assert [m["role"] for m in hist] == ["user", "model"]
    assert hist[0]["content"] == "hello"


def test_history_window_keeps_the_newest(tmp_memory):
    for i in range(10):
        tmp_memory.add_message("s", "user", f"msg-{i}")
    hist = tmp_memory.get_history("s", last_n=3)
    assert [m["content"] for m in hist] == ["msg-7", "msg-8", "msg-9"]


def test_sessions_are_isolated(tmp_memory):
    tmp_memory.add_message("a", "user", "in a")
    tmp_memory.add_message("b", "user", "in b")
    assert len(tmp_memory.get_history("a")) == 1
    assert tmp_memory.get_history("b")[0]["content"] == "in b"


def test_clear_session_keeps_facts(tmp_memory):
    tmp_memory.add_message("a", "user", "x")
    tmp_memory.save_fact("Name", "Sagar")
    removed = tmp_memory.clear_session("a")
    assert removed == 1
    assert tmp_memory.get_history("a") == []
    assert tmp_memory.get_fact("name") == "Sagar"


def test_facts_are_case_insensitive_and_upsert(tmp_memory):
    tmp_memory.save_fact("Favourite Language", "Python")
    tmp_memory.save_fact("favourite language", "Rust")
    assert tmp_memory.get_fact("FAVOURITE LANGUAGE") == "Rust"
    assert len(tmp_memory.get_all_facts()) == 1


def test_get_fact_missing_returns_none(tmp_memory):
    assert tmp_memory.get_fact("nope") is None


def test_task_lifecycle(tmp_memory):
    tid = tmp_memory.log_task("summarise a PDF")
    tmp_memory.complete_task(tid, "done in 5 lines")
    task = tmp_memory.get_recent_tasks(1)[0]
    assert task["status"] == "done"
    assert task["result_summary"] == "done in 5 lines"


def test_search_history_matches_substring(tmp_memory):
    tmp_memory.add_message("s", "user", "tell me about quantum tunnelling")
    assert tmp_memory.search_history("quantum")
    assert tmp_memory.search_history("zzz") == []


def test_tool_usage_counts_feed_the_summary(tmp_memory):
    tmp_memory.log_tool_call("read_file", {"path": "a.txt"}, "ok", True)
    tmp_memory.log_tool_call("read_file", {"path": "b.txt"}, "boom", False)
    s = tmp_memory.get_session_summary()
    assert s["tool_calls"] == 2
    assert s["tool_success"] == 1


def test_tool_call_with_unserialisable_args_does_not_raise(tmp_memory):
    tmp_memory.log_tool_call("weird", {"f": object()}, "r", True)
    assert tmp_memory.get_session_summary()["tool_calls"] == 1
