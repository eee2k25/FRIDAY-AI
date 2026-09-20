"""Code tools — static analysis, write-and-run, error fixing, git basics."""
from __future__ import annotations

import ast
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_LANG_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".html": "html",
    ".css": "css",
    ".json": "json",
    ".md": "markdown",
    ".bat": "batch",
    ".ps1": "powershell",
    ".sh": "shell",
}


def _read(path: str) -> tuple[str, Path]:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    if not p.exists():
        raise FileNotFoundError(f"file not found: {p}")
    try:
        return p.read_text(encoding="utf-8"), p
    except UnicodeDecodeError:
        return p.read_text(encoding="latin-1"), p


def analyze_code(file_path: str) -> str:
    """Analyze a source file: language, line count, functions, classes, imports."""
    source, p = _read(file_path)
    lang = _LANG_BY_EXT.get(p.suffix.lower(), "unknown")
    lines = source.splitlines()
    notes: list[str] = []
    if lang == "python":
        try:
            tree = ast.parse(source)
            funcs = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
            imports: list[str] = []
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    imports.extend(a.name for a in n.names)
                elif isinstance(n, ast.ImportFrom):
                    imports.append(f"{n.module} ({', '.join(a.name for a in n.names)})")
            notes.append(f"functions ({len(funcs)}): {', '.join(funcs[:25]) or 'none'}")
            notes.append(f"classes ({len(classes)}): {', '.join(classes[:15]) or 'none'}")
            notes.append(f"imports ({len(imports)}): {', '.join(dict.fromkeys(imports))[:300] or 'none'}")
        except SyntaxError as e:
            notes.append(f"SYNTAX ERROR at line {e.lineno}: {e.msg}")
    else:
        funcs = list(dict.fromkeys(re.findall(r"(?:function|def)\s+([A-Za-z_$][\w$]*)", source)))
        classes = list(dict.fromkeys(re.findall(r"\bclass\s+([A-Za-z_$][\w$]*)", source)))
        notes.append(f"function-like defs: {', '.join(funcs)[:300] or 'none found'}")
        notes.append(f"class-like defs: {', '.join(classes)[:300] or 'none found'}")
    notes.append(f"lines: {len(lines)}")
    head = "\n".join(lines[:10])
    return (
        f"FILE: {p}\nLANGUAGE: {lang}\n\nHEAD (first 10 lines):\n{head}\n\nANALYSIS:\n"
        + "\n".join("- " + n for n in notes)
    )


def write_and_run_code(filename: str, code: str, language: str = "python") -> str:
    """Write code to a temp file, run it, return output. Python only for now."""
    if language.lower() not in ("python", "py"):
        return (
            f"Only Python execution is wired up at the moment, Boss. I did not save "
            f"{filename!r}. If you need {language!r}, ask me to write it out to a file "
            "and I will run it through run_command."
        )
    tmp_dir = Path(tempfile.mkdtemp(prefix="friday_code_"))
    safe = re.sub(r"[^A-Za-z0-9_\-]", "_", filename) or "snippet.py"
    if not safe.endswith(".py"):
        safe += ".py"
    target = tmp_dir / safe
    target.write_text(code, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(target)],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError("code run timed out after 30s")
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    result = f"EXIT CODE: {proc.returncode}\n"
    if out:
        result += f"STDOUT:\n{out[:6000]}\n"
    if err:
        result += f"STDERR:\n{err[:3000]}\n"
    if not out and not err:
        result += "(no output)\n"
    return result + f"\n[source saved at {target} for inspection]"


_HINTS = {
    "NameError": "A variable or function is used before it exists. Check spelling, scope, or a missing import.",
    "SyntaxError": "Python can't parse the code. Look for a missing colon, bracket or mismatched indentation.",
    "IndentationError": "Inconsistent whitespace. Python needs uniform indentation — check tabs vs spaces.",
    "TypeError": "Wrong type for an operation. Check the argument types on the failing line.",
    "ImportError": "Module not installed or not on the path. Check pip list / install the package.",
    "ModuleNotFoundError": "Package missing. Install it (pip install <name>) or check the spelling.",
    "FileNotFoundError": "Path doesn't exist or is relative to the wrong working directory. Verify with list_directory.",
    "IndexError": "List/string index out of range — check the loop bound or the length.",
    "KeyError": "Dict key missing — check the key name or use .get().",
    "AttributeError": "Object doesn't have that attribute — check the method/property name.",
    "ZeroDivisionError": "Division by zero — guard the denominator.",
}


def fix_python_error(code: str, error_message: str) -> str:
    """Give the LLM structured error context: failing line ± context + diagnosis."""
    lines = code.splitlines()
    context = ""
    m = re.search(r"line (\d+)", error_message)
    if m:
        ln = int(m.group(1))
        if 1 <= ln <= len(lines):
            lo, hi = max(0, ln - 4), min(len(lines), ln + 3)
            context = "\n".join(
                f"{i + 1:>5} {'>>' if i + 1 == ln else '  '} {lines[i]}" for i in range(lo, hi)
            )
    etype = error_message.strip().splitlines()[-1] if error_message.strip() else "UnknownError"
    hint = next((h for key, h in _HINTS.items() if key in etype),
                "Inspect the failing line and the types/objects involved.")
    return (
        f"ERROR LINE CONTEXT:\n{context or '(could not locate the failing line in the provided code)'}\n\n"
        f"ERROR TYPE: {etype.strip()[:120]}\n\n"
        f"DIAGNOSIS: {hint}"
    )


def _git(repo_path: str, args: list[str], timeout: int = 30) -> str:
    p = Path(repo_path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    if not (p / ".git").exists():
        raise FileNotFoundError(f"not a git repository: {p}")
    proc = subprocess.run(
        ["git", *args], cwd=str(p), capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {err or out}")
    return out or "(no output)"


def git_status(repo_path: str = ".") -> str:
    """Git branch + short status of a repository."""
    branch = _git(repo_path, ["rev-parse", "--abbrev-ref", "HEAD"])
    status = _git(repo_path, ["status", "--short"])
    return f"branch: {branch}\n\n{status or 'working tree clean'}"


def git_add_commit(repo_path: str, message: str) -> str:
    """git add -A + git commit with the given message."""
    _git(repo_path, ["add", "-A"])
    return _git(repo_path, ["commit", "-m", message]) + "\n\n[committed]"


_DECLARATIONS: list[dict] = [
    {
        "name": "analyze_code",
        "description": "Statically analyze a source file: language, line count, functions, classes, imports.",
        "parameters": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
        },
    },
    {
        "name": "write_and_run_code",
        "description": "Write code to a temp file, run it (Python only, 30s timeout) and return the output.",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "code": {"type": "string", "description": "Full source code"},
                "language": {"type": "string", "description": "default 'python'"},
            },
            "required": ["filename", "code"],
        },
    },
    {
        "name": "fix_python_error",
        "description": "Given Python source and an error/traceback, return the failing line with context plus a diagnosis to guide the fix.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "The Python source code"},
                "error_message": {"type": "string", "description": "The traceback or error text"},
            },
            "required": ["code", "error_message"],
        },
    },
    {
        "name": "git_status",
        "description": "Show git branch and short status of a repository.",
        "parameters": {
            "type": "object",
            "properties": {"repo_path": {"type": "string", "description": "default '.'"}},
        },
    },
    {
        "name": "git_add_commit",
        "description": "git add -A and git commit with the given message in a repository.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "default '.'"},
                "message": {"type": "string"},
            },
            "required": ["repo_path", "message"],
        },
    },
]


def register_tools(registry) -> None:
    for d in _DECLARATIONS:
        registry.register_tool(d["name"], globals()[d["name"]], d)
