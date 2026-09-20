"""Web search + scraping tools. requests + BeautifulSoup + ddgs — no Selenium,
no API key. Pages: text / links / raw extraction. PDFs: pdfplumber → PyPDF2."""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

try:
    import requests
except ImportError as e:  # fail fast with a clear error
    raise ImportError("requests not installed. Run: pip install -r requirements.txt") from e

try:
    from bs4 import BeautifulSoup
except ImportError:  # bs4 is only needed at scrape time
    BeautifulSoup = None

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 FRIDAY/1.0"
    )
}


def _soup(html: str):
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 not installed. Run: pip install beautifulsoup4")
    return BeautifulSoup(html, "html.parser")


def _ddgs():
    try:
        from ddgs import DDGS
        return DDGS()
    except ImportError:
        try:
            from duckduckgo_search import DDGS
            return DDGS()
        except ImportError as e:
            raise RuntimeError("web search not available. Run: pip install ddgs") from e


def raw_search(query: str, num_results: int) -> list[dict]:
    """Raw search results (list of dicts) — used by research tools."""
    return _ddgs().text(query, max_results=int(num_results)) or []


def web_search(query: str, num_results: int = 8) -> str:
    """DuckDuckGo web search. Numbered list of title / url / snippet."""
    results = raw_search(query, num_results)
    if not results:
        return f"No results found for {query!r}. Try different keywords, Boss."
    lines = []
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "").strip()
        url = (r.get("href") or r.get("url") or "").strip()
        snippet = " ".join((r.get("body") or r.get("snippet") or "").split())[:300]
        lines.append(f"{i}. {title}\n   {url}\n   {snippet}")
    return f"{len(results)} results for {query!r}:\n" + "\n\n".join(lines)


def _clean_url(url: str) -> str:
    """Strip markdown-link wrappers the LLM sometimes passes, e.g. [title](https://…) → https://…"""
    url = url.strip()
    m = re.fullmatch(r"\[[^\]]*\]\(([^)]+)\)", url)
    if m:
        url = m.group(1).strip()
    return url


def fetch_webpage(url: str, extract_mode: str = "text") -> str:
    """Fetch a URL. extract_mode: 'text' (clean text), 'links', or 'raw' HTML."""
    url = _clean_url(url)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15, allow_redirects=True)
    except requests.exceptions.Timeout:
        raise TimeoutError(f"timed out fetching {url} (15s)")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"fetch failed for {url}: {e}")
    if resp.status_code == 404:
        raise FileNotFoundError(f"404 — {url} does not exist")
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code} fetching {url}")

    if extract_mode == "raw":
        return resp.text[:20000]
    if extract_mode == "links":
        soup = _soup(resp.text)
        seen, out = set(), []
        for a in soup.find_all("a", href=True):
            text = " ".join(a.get_text().split())[:80]
            if text:
                line = f"{text} — {a['href']}"
                if line not in seen:
                    seen.add(line)
                    out.append(line)
        if not out:
            return f"No links found at {url}."
        return f"{len(out)} links at {url}:\n" + "\n".join(out[:300])

    # default: clean text
    soup = _soup(resp.text)
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "form"]):
        tag.decompose()
    lines = [ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip()]
    text = "\n".join(lines)
    if not text.strip():
        return f"Page {url} returned no readable text."
    if len(text) > 30000:
        text = text[:30000] + f"\n... [truncated, {len(text)} chars total]"
    return f"=== {url} ===\n{text}"


def search_and_fetch(query: str, fetch_top_n: int = 3) -> str:
    """Search, then fetch the top N results. Combined content for research."""
    results = raw_search(query, fetch_top_n)
    if not results:
        return f"No results for {query!r}."
    sections = []
    for i, r in enumerate(results, 1):
        url = (r.get("href") or r.get("url") or "").strip()
        title = (r.get("title") or "").strip()
        if not url:
            continue
        try:
            body = fetch_webpage(url, "text")
        except Exception as e:  # noqa: BLE001 — keep going on per-source failures
            body = f"[could not fetch: {e}]"
        sections.append(f"=== SOURCE {i}: {title} ===\nURL: {url}\n{body[:8000]}\n")
    return f"Combined content for {query!r} from {len(sections)} source(s):\n\n" + "\n".join(sections)


def _extract_pdf_text(path: Path) -> str:
    try:
        import pdfplumber

        chunks = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages[:100]:
                t = page.extract_text() or ""
                chunks.append(t)
        return "\n".join(chunks)[:100000]
    except ImportError:
        pass
    try:
        from PyPDF2 import PdfReader

        reader = PdfReader(str(path))
        return "\n".join((p.extract_text() or "") for p in reader.pages[:100])[:100000]
    except ImportError as e:
        raise RuntimeError("PDF reading not available. Run: pip install pdfplumber PyPDF2") from e


def read_pdf_url(url: str) -> str:
    """Download a PDF from a URL and extract its text (max 100k chars)."""
    url = _clean_url(url)
    resp = requests.get(url, headers=_HEADERS, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code} downloading {url}")
    tmp = Path(tempfile.mkstemp(suffix=".pdf")[1])
    try:
        tmp.write_bytes(resp.content)
        return _extract_pdf_text(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def read_local_pdf(path: str) -> str:
    """Extract text from a local PDF (max 100k chars)."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    if not p.exists():
        raise FileNotFoundError(f"pdf not found: {p}")
    return _extract_pdf_text(p)


_DECLARATIONS: list[dict] = [
    {
        "name": "web_search",
        "description": "Search the web (DuckDuckGo). Returns numbered results with title, url and snippet.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "num_results": {"type": "integer", "description": "max results, default 8"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_webpage",
        "description": "Fetch a URL and extract clean text, all links, or raw HTML.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "extract_mode": {"type": "string", "enum": ["text", "links", "raw"], "description": "default 'text'"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "search_and_fetch",
        "description": "Search the web AND fetch the top N result pages in one call. For quick deep-dives.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "fetch_top_n": {"type": "integer", "description": "how many top results to fetch, default 3"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_pdf_url",
        "description": "Download a PDF from a URL and return its extracted text (max 100k chars).",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "read_local_pdf",
        "description": "Extract text from a local PDF file (max 100k chars).",
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
