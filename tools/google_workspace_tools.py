"""Gmail, Drive, Calendar and Google Docs tools using one Google OAuth grant."""
from __future__ import annotations

import base64
import json
import mimetypes
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from core.integrations import google_service


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _header(headers: list[dict], name: str) -> str:
    wanted = name.lower()
    return next((h.get("value", "") for h in headers if h.get("name", "").lower() == wanted), "")


def _message_text(payload: dict) -> str:
    body = payload.get("body", {}).get("data")
    if payload.get("mimeType") == "text/plain" and body:
        return base64.urlsafe_b64decode(body + "===").decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        text = _message_text(part)
        if text:
            return text
    return ""


def gmail_search(query: str = "in:inbox", max_results: int = 10) -> str:
    """Search Gmail with Gmail query syntax and return message IDs, sender, date, subject and snippet."""
    service = google_service("gmail")
    result = service.users().messages().list(
        userId="me", q=query, maxResults=max(1, min(int(max_results), 50))
    ).execute()
    rows = []
    for item in result.get("messages", []):
        message = service.users().messages().get(
            userId="me", id=item["id"], format="metadata",
            metadataHeaders=["From", "To", "Subject", "Date"],
        ).execute()
        headers = message.get("payload", {}).get("headers", [])
        rows.append({
            "id": message["id"],
            "thread_id": message.get("threadId"),
            "from": _header(headers, "From"),
            "subject": _header(headers, "Subject"),
            "date": _header(headers, "Date"),
            "snippet": message.get("snippet", ""),
        })
    return _json({"query": query, "count": len(rows), "messages": rows})


def gmail_read_message(message_id: str) -> str:
    """Read one Gmail message by ID, including its plain-text body."""
    message = google_service("gmail").users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()
    payload = message.get("payload", {})
    headers = payload.get("headers", [])
    return _json({
        "id": message.get("id"),
        "thread_id": message.get("threadId"),
        "from": _header(headers, "From"),
        "to": _header(headers, "To"),
        "subject": _header(headers, "Subject"),
        "date": _header(headers, "Date"),
        "body": _message_text(payload),
    })


def gmail_send_email(to: str, subject: str, body: str, cc: str = "") -> str:
    """Send an email from the connected Gmail account. This performs the send immediately."""
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    if cc:
        message["Cc"] = cc
    message.set_content(body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    sent = google_service("gmail").users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
    return f"Email sent through Gmail (message {sent.get('id', 'unknown')})."


def gmail_create_draft(to: str, subject: str, body: str, cc: str = "") -> str:
    """Create a Gmail draft without sending it."""
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    if cc:
        message["Cc"] = cc
    message.set_content(body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    draft = google_service("gmail").users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()
    return f"Gmail draft created (draft {draft.get('id', 'unknown')})."


def drive_search(query: str = "trashed = false", max_results: int = 20) -> str:
    """Search Google Drive using Drive query syntax; returns file IDs, names, types and links."""
    result = google_service("drive").files().list(
        q=query,
        pageSize=max(1, min(int(max_results), 100)),
        fields="files(id,name,mimeType,modifiedTime,size,webViewLink,parents)",
        orderBy="modifiedTime desc",
    ).execute()
    return _json(result.get("files", []))


def drive_upload_file(local_path: str, drive_name: str = "", folder_id: str = "") -> str:
    """Upload a local file to Google Drive, optionally into a folder ID."""
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise RuntimeError("Google Workspace support is not installed. Run: pip install -e .") from exc
    path = Path(local_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    metadata = {"name": drive_name or path.name}
    if folder_id:
        metadata["parents"] = [folder_id]
    media = MediaFileUpload(str(path), mimetype=mimetypes.guess_type(path.name)[0], resumable=True)
    uploaded = google_service("drive").files().create(
        body=metadata, media_body=media, fields="id,name,mimeType,webViewLink"
    ).execute()
    return _json(uploaded)


def drive_download_file(file_id: str, output_path: str, export_format: str = "pdf") -> str:
    """Download a Drive file; Google-native files are exported (pdf, docx, xlsx or pptx)."""
    try:
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError as exc:
        raise RuntimeError("Google Workspace support is not installed. Run: pip install -e .") from exc
    service = google_service("drive")
    metadata = service.files().get(fileId=file_id, fields="name,mimeType").execute()
    google_type = metadata.get("mimeType", "").startswith("application/vnd.google-apps.")
    export_types = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "txt": "text/plain",
    }
    request = (
        service.files().export_media(fileId=file_id, mimeType=export_types.get(export_format, "application/pdf"))
        if google_type else service.files().get_media(fileId=file_id)
    )
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        downloader = MediaIoBaseDownload(handle, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    return f"Downloaded {metadata.get('name', file_id)} to {output}."


def calendar_list_events(time_min: str = "", days: int = 7, max_results: int = 20) -> str:
    """List upcoming Google Calendar events from an ISO timestamp through the requested number of days."""
    start = datetime.fromisoformat(time_min.replace("Z", "+00:00")) if time_min else datetime.now(timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    end = start + timedelta(days=max(1, int(days)))
    result = google_service("calendar").events().list(
        calendarId="primary", timeMin=start.isoformat(), timeMax=end.isoformat(),
        maxResults=max(1, min(int(max_results), 100)), singleEvents=True, orderBy="startTime",
    ).execute()
    events = [{
        "id": e.get("id"), "summary": e.get("summary", "(untitled)"),
        "start": e.get("start", {}), "end": e.get("end", {}),
        "location": e.get("location", ""), "link": e.get("htmlLink", ""),
    } for e in result.get("items", [])]
    return _json(events)


def calendar_create_event(title: str, start: str, end: str, description: str = "", location: str = "", attendees: str = "", timezone_name: str = "UTC") -> str:
    """Create an event in the primary Google Calendar; attendees is a comma-separated email list."""
    event = {
        "summary": title, "description": description, "location": location,
        "start": {"dateTime": start, "timeZone": timezone_name},
        "end": {"dateTime": end, "timeZone": timezone_name},
    }
    if attendees.strip():
        event["attendees"] = [{"email": email.strip()} for email in attendees.split(",") if email.strip()]
    created = google_service("calendar").events().insert(
        calendarId="primary", body=event, sendUpdates="all" if attendees.strip() else "none"
    ).execute()
    return _json({"id": created.get("id"), "summary": created.get("summary"), "link": created.get("htmlLink")})


def docs_read(document_id: str) -> str:
    """Read the text and basic metadata of a Google Doc by document ID."""
    document = google_service("docs").documents().get(documentId=document_id).execute()
    text = []
    for item in document.get("body", {}).get("content", []):
        for element in item.get("paragraph", {}).get("elements", []):
            text.append(element.get("textRun", {}).get("content", ""))
    return _json({"id": document.get("documentId"), "title": document.get("title"), "text": "".join(text)})


def docs_create(title: str, content: str = "") -> str:
    """Create a Google Doc and optionally insert plain text content."""
    service = google_service("docs")
    document = service.documents().create(body={"title": title}).execute()
    document_id = document["documentId"]
    if content:
        service.documents().batchUpdate(documentId=document_id, body={"requests": [{
            "insertText": {"location": {"index": 1}, "text": content}
        }]}).execute()
    return _json({"id": document_id, "title": document.get("title"), "url": f"https://docs.google.com/document/d/{document_id}/edit"})


_TOOLS = (
    (gmail_search, {"query": "string", "max_results": "integer"}, []),
    (gmail_read_message, {"message_id": "string"}, ["message_id"]),
    (gmail_send_email, {"to": "string", "subject": "string", "body": "string", "cc": "string"}, ["to", "subject", "body"]),
    (gmail_create_draft, {"to": "string", "subject": "string", "body": "string", "cc": "string"}, ["to", "subject", "body"]),
    (drive_search, {"query": "string", "max_results": "integer"}, []),
    (drive_upload_file, {"local_path": "string", "drive_name": "string", "folder_id": "string"}, ["local_path"]),
    (drive_download_file, {"file_id": "string", "output_path": "string", "export_format": "string"}, ["file_id", "output_path"]),
    (calendar_list_events, {"time_min": "string", "days": "integer", "max_results": "integer"}, []),
    (calendar_create_event, {"title": "string", "start": "string", "end": "string", "description": "string", "location": "string", "attendees": "string", "timezone_name": "string"}, ["title", "start", "end"]),
    (docs_read, {"document_id": "string"}, ["document_id"]),
    (docs_create, {"title": "string", "content": "string"}, ["title"]),
)


def register_tools(registry) -> None:
    for function, property_types, required in _TOOLS:
        properties = {name: {"type": kind} for name, kind in property_types.items()}
        registry.register_tool(function.__name__, function, {
            "name": function.__name__, "description": function.__doc__,
            "parameters": {"type": "object", "properties": properties, "required": required},
        })
