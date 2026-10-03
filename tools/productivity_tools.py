"""Local-first calendar and email integrations.

Calendar events are emitted as standard ICS files. Email uses SMTP only when
explicitly configured, so a fresh install never sends anything accidentally.
"""
from __future__ import annotations

import os
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path


def create_calendar_event(
    title: str,
    start: str,
    duration_minutes: int = 60,
    description: str = "",
    output: str = "memory/event.ics",
) -> str:
    """Create an RFC 5545 calendar event that can be imported into Google Calendar, Apple Calendar, or Outlook."""
    begin = datetime.fromisoformat(start.replace('Z', '+00:00'))
    end = begin + timedelta(minutes=int(duration_minutes))

    def stamp(d):
        return d.strftime('%Y%m%dT%H%M%SZ')

    def esc(s):
        return (
            str(s)
            .replace('\\', '\\\\')
            .replace(';', '\\;')
            .replace(',', '\\,')
            .replace('\n', '\\n')
        )

    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//FRIDAY AI//EN\nBEGIN:VEVENT\nUID:'
        + stamp(begin) + '-' + esc(title) + '@friday\nDTSTAMP:' + stamp(datetime.utcnow())
        + '\nDTSTART:' + stamp(begin) + '\nDTEND:' + stamp(end)
        + '\nSUMMARY:' + esc(title) + '\nDESCRIPTION:' + esc(description)
        + '\nEND:VEVENT\nEND:VCALENDAR\n'
    )
    return f'Calendar event created: {path.resolve()}'


def send_email(to: str, subject: str, body: str) -> str:
    """Send email through configured SMTP; requires SMTP_HOST, SMTP_USER, and SMTP_PASSWORD."""
    host = os.getenv('SMTP_HOST')
    user = os.getenv('SMTP_USER')
    password = os.getenv('SMTP_PASSWORD')
    if not all((host, user, password)):
        return (
            'Email is not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD, '
            'and optionally SMTP_PORT/SMTP_FROM.'
        )
    msg = EmailMessage()
    msg['From'] = os.getenv('SMTP_FROM', user)
    msg['To'] = to
    msg['Subject'] = subject
    msg.set_content(body)
    with smtplib.SMTP(host, int(os.getenv('SMTP_PORT', '587')), timeout=30) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(msg)
    return f'Email sent to {to}.'


def register_tools(registry):
    defs = [
        (
            'create_calendar_event',
            create_calendar_event,
            {
                'title': {'type': 'string'},
                'start': {'type': 'string'},
                'duration_minutes': {'type': 'integer'},
                'description': {'type': 'string'},
                'output': {'type': 'string'},
            },
            ['title', 'start'],
        ),
        (
            'send_email',
            send_email,
            {
                'to': {'type': 'string'},
                'subject': {'type': 'string'},
                'body': {'type': 'string'},
            },
            ['to', 'subject', 'body'],
        ),
    ]
    for n, fn, props, required in defs:
        registry.register_tool(n, fn, {
            'name': n,
            'description': fn.__doc__,
            'parameters': {'type': 'object', 'properties': props, 'required': required},
        })
