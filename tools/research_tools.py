"""Deep research workflows — FRIDAY's specialty.

- deep_research:          N varied queries → unique URLs → concurrent fetch → compiled dossier
- research_and_write_report: deep research → extractive key findings → real .docx report
- summarize_document:     any txt/md/pdf/docx → structured extractive summary
- compare_sources:        fetch N URLs → key points per source + shared-term overlap
"""
from __future__ import annotations

import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tools.browser_tools import fetch_webpage, raw_search

_SENT_RE = re.compile(r"(?<=[.!?])\s+")
_DEPTH = {1: (5, 2, 2000), 2: (10, 3, 3000), 3: (15, 5, 4000)}
_FETCH_CAP = 20  # hard cap on unique pages fetched, keeps depth-3 sane
_COMPILE_CAP = 25000  # keep compiled dossiers inside fallback-model context budgets


def _unique(seq) -> list:
    seen, out = set(), []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _queries_for(topic: str, n: int) -> list[str]:
    variants = [
        topic,
        f"{topic} overview",
        f"{topic} how it works",
        f"{topic} best practices",
        f"{topic} common problems",
        f"{topic} examples",
        f"{topic} step by step",
        f"{topic} key concepts",
        f"{topic} pitfalls",
        f"{topic} comparison",
        f"{topic} advantages disadvantages",
        f"{topic} troubleshooting",
        f"{topic} latest developments",
        f"{topic} in practice",
        f"{topic} guide",
    ]
    return variants[:n]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_RE.split(text) if 40 <= len(s.strip()) <= 400]


def _score_sentences(sentences: list[str], topic_words: set[str]) -> list[str]:
    """Extractive ranking: term frequency + topic-word bonus, original order kept."""
    freq = Counter(w for s in sentences for w in re.findall(r"[a-z]{4,}", s.lower()))

    def score(s: str) -> float:
        words = re.findall(r"[a-z]+", s.lower())
        if not words:
            return 0.0
        base = sum(freq.get(w, 0) for w in words) / len(words)
        topic_hits = sum(1 for w in words if w in topic_words)
        return base * 2 + topic_hits * 3

    ranked = sorted(enumerate(sentences), key=lambda p: score(p[1]), reverse=True)
    picked = sorted(i for i, _ in ranked[:30])
    return [sentences[i] for i in picked]


def deep_research(topic: str, depth: int = 3) -> str:
    """Run a battery of searches, fetch the top sources concurrently, and
    compile a structured dossier. depth: 1 (5q) / 2 (10q) / 3 (15q)."""
    depth = max(1, min(3, int(depth)))
    n_queries, fetch_n, per_source = _DEPTH[depth]
    queries = _queries_for(topic, n_queries)

    # ---- phase 1: search (sequential — search APIs rate-limit parallelism)
    query_results: list[tuple[str, list[dict], str | None]] = []
    for q in queries:
        try:
            res = raw_search(q, fetch_n)
        except Exception as e:  # noqa: BLE001 — one bad query must not kill the run
            res, err = [], f"[search failed: {e}]"
        else:
            err = None
        query_results.append((q, res, err))

    # ---- collect unique URLs in priority order
    url_list: list[str] = []
    for _q, res, _e in query_results:
        for r in res:
            u = (r.get("href") or r.get("url") or "").strip()
            if u.startswith("http"):
                url_list.append(u)
    url_list = _unique(url_list)[:_FETCH_CAP]

    # ---- phase 2: fetch concurrently
    bodies: dict[str, str] = {}
    if url_list:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {pool.submit(fetch_webpage, u, "text"): u for u in url_list}
            for fut in as_completed(futs):
                u = futs[fut]
                try:
                    bodies[u] = fut.result()
                except Exception as e:  # noqa: BLE001
                    bodies[u] = f"[fetch failed: {e}]"

    # ---- phase 3: compile
    ok = sum(1 for v in bodies.values() if not v.startswith("[fetch failed"))
    out = [
        f"DEEP RESEARCH: {topic} (depth {depth})\n"
        f"Queries run: {len(queries)} | Unique sources: {len(url_list)} | Fetched OK: {ok}\n"
    ]
    for q, res, err in query_results:
        out.append(f"## Query: {q}")
        if err:
            out.append(err)
            continue
        if not res:
            out.append("no results")
            continue
        for r in res[:fetch_n]:
            u = (r.get("href") or r.get("url") or "").strip()
            title = (r.get("title") or "").strip()
            snippet = " ".join((r.get("body") or r.get("snippet") or "").split())[:300]
            out.append(f"- {title}\n  {u}\n  {snippet}")
            if u in bodies and not bodies[u].startswith("[fetch failed"):
                out.append(f"  CONTENT: {bodies[u][:per_source]}")
        out.append("")

    text = "\n".join(out)
    cap = _COMPILE_CAP
    if len(text) > cap:
        text = text[:cap] + f"\n... [research compiled, {len(text)} chars total]"
    return text


def research_and_write_report(topic: str, output_path: str, report_type: str = "technical") -> str:
    """Deep research + a real .docx report: exec summary, key findings,
    detailed notes, sources. Returns the created file path."""
    from tools.document_tools import create_project_report

    research = deep_research(topic, depth=2)

    sources = re.findall(r"\n  (https?://\S+)\n", research)
    sentences: list[str] = []
    for m in re.finditer(r"CONTENT: (.+?)(?=\n- |\n## |\Z)", research, re.S):
        sentences.extend(_sentences(m.group(1)))
    topic_words = set(re.findall(r"[a-z]{4,}", topic.lower()))
    scored = _score_sentences(sentences, topic_words)

    sections = {
        "Executive Summary": "\n".join(f"- {s}" for s in scored[:6]) or "- (insufficient source content)",
        "Key Findings": "\n".join(f"- {s}" for s in scored[6:24]) or "- (insufficient source content)",
        "Detailed Notes": research[:15000],
        "Sources": "\n".join(f"- {u}" for u in _unique(sources)[:25]) or "- (none captured)",
    }
    path = create_project_report(output_path, f"{topic} — {report_type.capitalize()} Report", sections)
    return f"{path}\nReport type: {report_type}. Topic: {topic}."


def summarize_document(file_path: str, max_length: int = 2000) -> str:
    """Summarize a txt/md/pdf/docx with an extractive method within max_length chars."""
    p = Path(file_path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    if not p.exists():
        raise FileNotFoundError(f"document not found: {p}")
    ext = p.suffix.lower()
    if ext == ".pdf":
        from tools.browser_tools import _extract_pdf_text

        text = _extract_pdf_text(p)
    elif ext == ".docx":
        from tools.document_tools import read_word_doc

        text = read_word_doc(str(p))
    else:
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = p.read_text(encoding="latin-1")

    sents = _sentences(text)
    if not sents:
        return f"SUMMARY OF {p.name}\n\n(no meaningful sentences found in {len(text)} chars)"
    freq = Counter(w for s in sents for w in re.findall(r"[a-z]{4,}", s.lower()))

    def score(s: str) -> float:
        words = re.findall(r"[a-z]+", s.lower()) or ["x"]
        return sum(freq.get(w, 0) for w in words) / len(words)

    ranked = sorted(enumerate(sents), key=lambda p2: score(p2[1]), reverse=True)
    budget = int(max_length)
    picked: list[int] = []
    used = 0
    for idx, _ in ranked:
        s = sents[idx]
        if used + len(s) > budget:
            continue
        picked.append(idx)
        used += len(s) + 2
        if used >= budget:
            break
    picked.sort()
    summary = " ".join(sents[i] for i in picked)
    return (
        f"SUMMARY OF {p.name} ({len(text)} chars source, {len(sents)} sentences)\n\n{summary}"
    )


def compare_sources(urls: str) -> str:
    """Fetch comma-separated URLs, extract key points per source, and report
    which terms appear across most sources (agreement surface / conflict check)."""
    parts = [u.strip() for u in urls.split(",") if u.strip().startswith("http")]
    if len(parts) < 2:
        return "Need at least 2 URLs (comma-separated) to compare, Boss."
    fetched: dict[str, str] = {}
    for u in parts[:6]:
        try:
            fetched[u] = fetch_webpage(u, "text")
        except Exception as e:  # noqa: BLE001
            fetched[u] = f"[failed: {e}]"

    stop = set(
        "the a an and or of to in for is are was were be with that this on as by it from at not you your we our they he she will would".split()
    )
    reports = []
    all_counter: Counter = Counter()
    word_sets = []
    for u, text in fetched.items():
        sents = _sentences(text)[:8]
        words = [w for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in stop]
        counter = Counter(words)
        all_counter += counter
        word_sets.append(set(words))
        reports.append(
            f"SOURCE: {u}\nKEY POINTS:\n"
            + "\n".join(f"- {s}" for s in sents)
            + "\nTOP TERMS: "
            + ", ".join(f"{w} ({c})" for w, c in counter.most_common(12))
        )
    good = len([w for w in word_sets if w])
    common = [
        w
        for w, _c in all_counter.most_common(40)
        if good >= 2 and sum(1 for ws in word_sets if w in ws) >= max(2, good // 2)
    ]
    text_out = "\n\n".join(reports)
    text_out += (
        f"\n\nSHARED TERMS (appear across most sources): {', '.join(common[:15]) or '(none)'}\n"
        "CONFLICT CHECK: review the KEY POINTS above for claims that diverge on the shared terms."
    )
    return text_out[:12000]


_DECLARATIONS: list[dict] = [
    {
        "name": "deep_research",
        "description": "Run a battery of web searches on a topic, fetch the top sources, and compile a structured dossier. Use for any serious research task.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "depth": {"type": "integer", "description": "1 = quick (5 queries), 2 = standard (10), 3 = deep (15)", "enum": [1, 2, 3]},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "research_and_write_report",
        "description": "Deep research a topic AND write a full Word .docx report (exec summary, key findings, detailed notes, sources) to output_path. Returns the file path.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "output_path": {"type": "string", "description": "Output .docx path, e.g. reports/topic_report.docx"},
                "report_type": {"type": "string", "description": "'technical' (default) or 'briefing'"},
            },
            "required": ["topic", "output_path"],
        },
    },
    {
        "name": "summarize_document",
        "description": "Summarize a local document (.txt/.md/.pdf/.docx) into key sentences within max_length characters.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "max_length": {"type": "integer", "description": "summary length budget, default 2000"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "compare_sources",
        "description": "Fetch a comma-separated list of URLs, extract key points from each, and report shared terms to surface agreement/conflict.",
        "parameters": {
            "type": "object",
            "properties": {"urls": {"type": "string", "description": "Comma-separated http(s) URLs"}},
            "required": ["urls"],
        },
    },
]


def register_tools(registry) -> None:
    for d in _DECLARATIONS:
        registry.register_tool(d["name"], globals()[d["name"]], d)
