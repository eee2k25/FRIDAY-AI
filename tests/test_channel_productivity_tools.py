"""Tests for channel and productivity tool integrations."""
from __future__ import annotations

from tools import channel_tools, productivity_tools


def test_send_slack_requires_webhook(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    msg = channel_tools.send_slack("hi")
    assert "not configured" in msg.lower()


def test_send_imessage_requires_webhook(monkeypatch):
    monkeypatch.delenv("IMESSAGE_WEBHOOK_URL", raising=False)
    msg = channel_tools.send_imessage("hello")
    assert "not configured" in msg.lower()


def test_send_imessage_posts_payload(monkeypatch):
    calls = {}

    class Resp:
        status_code = 200
        text = "ok"

    def fake_post(url, json, timeout):
        calls["url"] = url
        calls["json"] = json
        calls["timeout"] = timeout
        return Resp()

    monkeypatch.setenv("IMESSAGE_WEBHOOK_URL", "https://relay.example/send")
    monkeypatch.setenv("IMESSAGE_RECIPIENT", "+15550001111")
    monkeypatch.setattr(channel_tools.requests, "post", fake_post)
    out = channel_tools.send_imessage("ping")
    assert "accepted" in out.lower()
    assert calls["url"] == "https://relay.example/send"
    assert calls["json"] == {"message": "ping", "recipient": "+15550001111"}
    assert calls["timeout"] == 20


def test_create_calendar_event_writes_ics(tmp_path):
    out = tmp_path / "meeting.ics"
    result = productivity_tools.create_calendar_event(
        title="Planning",
        start="2026-10-01T10:00:00Z",
        duration_minutes=30,
        description="Roadmap sync",
        output=str(out),
    )
    assert "calendar event created" in result.lower()
    content = out.read_text(encoding="utf-8")
    assert "BEGIN:VCALENDAR" in content
    assert "SUMMARY:Planning" in content
    assert "DESCRIPTION:Roadmap sync" in content


def test_send_email_requires_smtp(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    msg = productivity_tools.send_email("a@b.com", "s", "b")
    assert "not configured" in msg.lower()


def test_send_email_uses_smtp(monkeypatch):
    calls = {"starttls": 0, "login": None, "sent": None}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls["ctor"] = (host, port, timeout)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self):
            calls["starttls"] += 1

        def login(self, user, password):
            calls["login"] = (user, password)

        def send_message(self, msg):
            calls["sent"] = (msg["From"], msg["To"], msg["Subject"], msg.get_content().strip())

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM", "bot@example.com")
    monkeypatch.setattr(productivity_tools.smtplib, "SMTP", FakeSMTP)

    msg = productivity_tools.send_email("boss@example.com", "Status", "Done")
    assert "email sent" in msg.lower()
    assert calls["ctor"] == ("smtp.example.com", 2525, 30)
    assert calls["starttls"] == 1
    assert calls["login"] == ("user@example.com", "secret")
    assert calls["sent"] == ("bot@example.com", "boss@example.com", "Status", "Done")
