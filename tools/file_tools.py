"""File system tools — read, write, list, search, copy, delete, info."""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

MAX_READ_CHARS = 50000


def _p(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    return p


def read_file(path: str) -> str:
    """Read a text file. Tries UTF-8 then Latin-1. Truncates at 50,000 chars."""
    p = _p(path)
    if not p.exists():
        raise FileNotFoundError(f"file not found: {p}")
    if p.is_dir():
        raise IsADirectoryError(f"path is a directory, not a file: {p}")
    data = p.read_bytes()
    text = None
    for enc in ("utf-8", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError(f"could not decode {p} as text (binary file?)")
    if len(text) > MAX_READ_CHARS:
        return text[:MAX_READ_CHARS] + f"\n... [truncated, {len(text)} chars total]"
    return text


def write_file(path: str, content: str, mode: str = "w") -> str:
    """Write content to a file. Creates parent folders. mode: 'w' or 'a'."""
    p = _p(path)
    if not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    if mode not in ("w", "a"):
        raise ValueError(f"unsupported mode: {mode!r} (use 'w' or 'a')")
    with open(p, mode, encoding="utf-8") as f:
        f.write(content)
    return f"Written {p.stat().st_size} bytes to {p}"


def list_directory(path: str, pattern: str = "*", recursive: str = "False", depth: int = 3) -> str:
    """List entries matching a glob pattern, newest first, with size and date.

    recursive='True' walks subdirectories up to `depth` levels deep.
    """
    p = _p(path)
    if not p.is_dir():
        raise NotADirectoryError(f"not a directory: {p}")
    rec = str(recursive).strip().lower() in ("true", "1", "yes")
    max_depth = max(1, min(int(depth), 10)) if rec else 1
    entries = []
    iterator = p.rglob(pattern) if rec else p.glob(pattern)
    for item in iterator:
        if rec and len(item.relative_to(p).parts) > max_depth:
            continue
        try:
            st = item.stat()
        except OSError:
            continue
        entries.append(
            (
                str(item.relative_to(p)),
                st.st_size,
                datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                str(item),
            )
        )
    entries.sort(key=lambda e: e[2], reverse=True)
    if not entries:
        return f"No entries in {p} match {pattern!r}."
    lines = [f"{'NAME':<40} {'SIZE':>10}  {'MODIFIED':<17} PATH"]
    for name, size, mtime, full in entries[:200]:
        lines.append(f"{name[:40]:<40} {size:>10}  {mtime:<17} {full}")
    if len(entries) > 200:
        lines.append(f"... {len(entries) - 200} more entries")
    return "\n".join(lines)


def search_files(directory: str, query: str, file_types: str = ".txt,.py,.md") -> str:
    """Search file CONTENTS for a query string. Returns file:line: match (max 100)."""
    base = _p(directory)
    if not base.is_dir():
        raise NotADirectoryError(f"not a directory: {base}")
    exts = [e.strip().lstrip(".").lower() for e in file_types.split(",") if e.strip()]
    needle = query.lower()
    matches: list[str] = []
    scanned = 0
    for path in base.rglob("*"):
        if len(matches) >= 100:
            break
        if not path.is_file():
            continue
        if exts and path.suffix.lower().lstrip(".") not in exts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        for i, line in enumerate(text.splitlines(), 1):
            if needle in line.lower():
                matches.append(f"{path}:{i}: {line.strip()[:200]}")
                if len(matches) >= 100:
                    break
    if not matches:
        return f"No matches for {query!r} in {base} (scanned {scanned} files, types {exts})."
    return f"{len(matches)} match(es) for {query!r} in {base}:\n" + "\n".join(matches)


def create_folder(path: str) -> str:
    """Create a folder (and parents) if it doesn't exist."""
    p = _p(path)
    p.mkdir(parents=True, exist_ok=True)
    return f"Folder ready: {p}"


def copy_file(source: str, destination: str) -> str:
    """Copy a file. If destination is a folder, the file goes inside it."""
    s, d = _p(source), _p(destination)
    if not s.exists():
        raise FileNotFoundError(f"source not found: {s}")
    if d.is_dir():
        d = d / s.name
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(s, d)
    return f"Copied {s} -> {d}"


def delete_file(path: str, confirm: bool = True) -> str:
    """Delete a file or folder.

    confirm=true (default) ARMS the deletion but does not perform it — FRIDAY
    wants the Boss to be explicit. Only deletes when confirm=false.
    """
    p = _p(path)
    if confirm:
        return (
            "Deletion armed but I want the Boss to say it explicitly. Call delete_file "
            "again with confirm=false and I will remove it. (No deletion performed.)"
        )
    if not p.exists():
        raise FileNotFoundError(f"nothing to delete: {p}")
    if p.is_dir():
        shutil.rmtree(p)
        return f"Deleted folder: {p}"
    p.unlink()
    return f"Deleted: {p}"


def get_file_info(path: str) -> str:
    """Size, created/modified times, type and likely encoding of a file."""
    p = _p(path)
    if not p.exists():
        raise FileNotFoundError(f"file not found: {p}")
    st = p.stat()
    created = datetime.fromtimestamp(getattr(st, "st_ctime", st.st_mtime))
    modified = datetime.fromtimestamp(st.st_mtime)
    enc = "n/a (binary)"
    try:
        p.read_bytes()[:65536].decode("utf-8")
        enc = "utf-8"
    except (UnicodeDecodeError, OSError):
        enc = "latin-1 or binary"
    return (
        f"Path:     {p}\n"
        f"Type:     {'directory' if p.is_dir() else (p.suffix or 'file')}\n"
        f"Size:     {st.st_size} bytes\n"
        f"Created:  {created:%Y-%m-%d %H:%M}\n"
        f"Modified: {modified:%Y-%m-%d %H:%M}\n"
        f"Encoding: {enc}"
    )


_DECLARATIONS: list[dict] = [
    {
        "name": "read_file",
        "description": "Read a text file and return its contents (truncated at 50k chars).",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path to read"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file, creating parent folders. Returns bytes written.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Destination file path"},
                "content": {"type": "string", "description": "Full file content to write"},
                "mode": {"type": "string", "enum": ["w", "a"], "description": "'w' overwrite (default) or 'a' append"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "List files/folders in a directory (glob pattern), newest first, with size and modified date. recursive='True' walks subfolders up to `depth` levels.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory to list"},
                "pattern": {"type": "string", "description": "glob pattern, default '*'"},
                "recursive": {"type": "string", "enum": ["True", "False"], "description": "default 'False'"},
                "depth": {"type": "integer", "description": "max subfolder depth when recursive, default 3, max 10"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_files",
        "description": "Search file CONTENTS for a query string inside a directory. Returns file:line matches (max 100).",
        "parameters": {
            "type": "object",
            "properties": {
                "directory": {"type": "string"},
                "query": {"type": "string"},
                "file_types": {"type": "string", "description": "comma-separated extensions, e.g. '.txt,.py,.md' (default .txt,.py,.md)"},
            },
            "required": ["directory", "query"],
        },
    },
    {
        "name": "create_folder",
        "description": "Create a folder (and parent folders) if it doesn't exist.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "copy_file",
        "description": "Copy a file to a new location (file or folder).",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "destination": {"type": "string"},
            },
            "required": ["source", "destination"],
        },
    },
    {
        "name": "delete_file",
        "description": "Delete a file or folder. confirm=true (default) arms but does NOT delete; only deletes when confirm=false, which you may only do when the Boss explicitly asked.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "confirm": {"type": "boolean", "description": "true = require explicit confirmation (default). false = delete immediately."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "get_file_info",
        "description": "Get size, created/modified times, type and encoding of a file.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
]


def register_tools(registry) -> None:
    for d in _DECLARATIONS:
        registry.register_tool(d["name"], globals()[d["name"]], d)
