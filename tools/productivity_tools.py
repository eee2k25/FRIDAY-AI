"""Local-first calendar and email integrations.

Calendar events are emitted as standard ICS files. Email uses SMTP only when
explicitly configured, so a fresh install never sends anything accidentally.
"""
from __future__ import annotations

import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path


def _as_utc_stamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y%m%dT%H%M%SZ")


def _escape_ics(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("\n", r"\n")
    )


def create_calendar_event(
    title: str,
    start: str,
    duration_minutes: int = 60,
    description: str = "",
    output: str = "memory/event.ics",
) -> str:
    """Create an RFC 5545 calendar event that can be imported into Google Calendar, Apple Calendar, or Outlook."""
    begin = datetime.fromisoformat(start.replace("Z", "+00:00"))
    end = begin + timedelta(minutes=int(duration_minutes))
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    uid = f"{_as_utc_stamp(begin)}-{_escape_ics(title)}@friday"
    content = "\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//FRIDAY AI//EN",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{_as_utc_stamp(datetime.now(timezone.utc))}",
            f"DTSTART:{_as_utc_stamp(begin)}",
            f"DTEND:{_as_utc_stamp(end)}",
            f"SUMMARY:{_escape_ics(title)}",
            f"DESCRIPTION:{_escape_ics(description)}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")
    return f"Calendar event created: {path.resolve()}"


def send_email(to: str, subject: str, body: str) -> str:
    """Send email through configured SMTP; requires SMTP_HOST, SMTP_USER, and SMTP_PASSWORD."""
    host = os.getenv("SMTP_HOST")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    if not all((host, user, password)):
        return "Email is not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD, and optionally SMTP_PORT/SMTP_FROM."
    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM", user)
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=30) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(msg)
    return f"Email sent to {to}."


def register_tools(registry):
    defs = [
        (
            "create_calendar_event",
            create_calendar_event,
            {
                "title": {"type": "string"},
                "start": {"type": "string"},
                "duration_minutes": {"type": "integer"},
                "description": {"type": "string"},
                "output": {"type": "string"},
            },
            ["title", "start"],
        ),
        (
            "send_email",
            send_email,
            {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
            ["to", "subject", "body"],
        ),
    ]
    for n, fn, props, required in defs:
        registry.register_tool(
            n,
            fn,
            {
                "name": n,
                "description": fn.__doc__,
                "parameters": {"type": "object", "properties": props, "required": required},
            },
        )
