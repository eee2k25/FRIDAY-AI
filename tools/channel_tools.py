"""Outbound Slack, Telegram, and iMessage bridge channel adapters."""
from __future__ import annotations
import os, requests

def send_telegram(message: str, chat_id: str = "") -> str:
    """Send a Telegram message using TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."""
    token=os.getenv('TELEGRAM_BOT_TOKEN'); target=chat_id or os.getenv('TELEGRAM_CHAT_ID')
    if not token or not target: return 'Telegram is not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.'
    r=requests.post(f'https://api.telegram.org/bot{token}/sendMessage',json={'chat_id':target,'text':message},timeout=20)
    if r.status_code >= 400: return f'Telegram failed ({r.status_code}): {r.text[:300]}'
    return 'Telegram message sent.'

def send_slack(message: str) -> str:
    """Send a Slack message using SLACK_WEBHOOK_URL."""
    url=os.getenv('SLACK_WEBHOOK_URL')
    if not url: return 'Slack is not configured. Set SLACK_WEBHOOK_URL.'
    r=requests.post(url,json={'text':message},timeout=20)
    if r.status_code >= 400: return f'Slack failed ({r.status_code}): {r.text[:300]}'
    return 'Slack message sent.'

def send_imessage(message: str, recipient: str = "") -> str:
    """Send an iMessage through a configured relay webhook (IMESSAGE_WEBHOOK_URL)."""
    url = os.getenv("IMESSAGE_WEBHOOK_URL")
    if not url:
        return "iMessage relay is not configured. Set IMESSAGE_WEBHOOK_URL."
    payload = {"message": message}
    target = recipient or os.getenv("IMESSAGE_RECIPIENT")
    if target:
        payload["recipient"] = target
    try:
        r = requests.post(url, json=payload, timeout=20)
    except requests.RequestException as e:
        return f"iMessage relay failed: {e}"
    if r.status_code >= 400:
        return f"iMessage failed ({r.status_code}): {r.text[:300]}"
    return "iMessage relay accepted the message."

def register_tools(registry):
    for n,fn,props,req in [('send_telegram',send_telegram,{'message':{'type':'string'},'chat_id':{'type':'string'}},['message']),('send_slack',send_slack,{'message':{'type':'string'}},['message']),('send_imessage',send_imessage,{'message':{'type':'string'},'recipient':{'type':'string'}},['message'])]:
        registry.register_tool(n,fn,{'name':n,'description':fn.__doc__,'parameters':{'type':'object','properties':props,'required':req}})
