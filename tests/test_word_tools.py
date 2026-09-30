"""Tests for the Word (.docx) toolset."""
from __future__ import annotations

import json

import pytest

docx = pytest.importorskip("docx", reason="python-docx not installed")

from tools import word_tools as wt  # noqa: E402


@pytest.fixture()
def doc_path(tmp_path):
    return str(tmp_path / "test.docx")


def _texts(path):
    return [p.text for p in docx.Document(path).paragraphs]


def _styles(path):
    return [(p.style.name, p.text) for p in docx.Document(path).paragraphs if p.text.strip()]


# ------------------------------------------------------------- create ---
def test_create_and_read_round_trip(doc_path):
    wt.create_word_doc(doc_path, "My Title", "# Heading\nplain line\n- a bullet")
    out = wt.read_word_doc(doc_path)
    assert "My Title" in out
    assert "# Heading" in out
    assert "- a bullet" in out


def test_markdown_styles_are_applied(doc_path):
    wt.create_word_doc(doc_path, "T", "# H1\n## H2\n### H3\n- bullet\n1. numbered\n> quoted")
    styles = {text: style for style, text in _styles(doc_path)}
    assert styles["H1"] == "Heading 1"
    assert styles["H2"] == "Heading 2"
    assert styles["H3"] == "Heading 3"
    assert styles["bullet"] == "List Bullet"
    assert styles["numbered"] == "List Number"
    assert styles["quoted"] == "Quote"


def test_bold_runs_are_real_bold(doc_path):
    wt.create_word_doc(doc_path, "T", "this is **important** text")
    runs = [r for p in docx.Document(doc_path).paragraphs for r in p.runs]
    bolded = [r.text for r in runs if r.bold]
    assert "important" in bolded


def test_create_makes_missing_parent_directories(tmp_path):
    target = tmp_path / "deep" / "nested" / "report.docx"
    wt.create_word_doc(str(target), "T", "body")
    assert target.exists()


def test_append_adds_without_losing_content(doc_path):
    wt.create_word_doc(doc_path, "T", "original line")
    wt.append_to_word_doc(doc_path, "## Appended\nsecond line")
    out = wt.read_word_doc(doc_path)
    assert "original line" in out and "## Appended" in out


# -------------------------------------------------------------- tables ---
def test_pipe_table_becomes_a_real_word_table(doc_path):
    content = "Intro line\n\n| Item | Qty |\n|---|---|\n| Widget | 3 |\n| Bolt | 12 |\n"
    wt.create_word_doc(doc_path, "T", content)
    tables = docx.Document(doc_path).tables
    assert len(tables) == 1
    assert len(tables[0].rows) == 3  # header + 2 data rows (separator dropped)
    assert tables[0].cell(0, 0).text == "Item"
    assert tables[0].cell(2, 1).text == "12"


def test_table_header_row_is_bold(doc_path):
    wt.create_word_doc(doc_path, "T", "| A | B |\n|---|---|\n| 1 | 2 |")
    header = docx.Document(doc_path).tables[0].rows[0].cells[0]
    assert any(run.bold for para in header.paragraphs for run in para.runs)


def test_pipe_text_without_a_separator_stays_plain(doc_path):
    wt.create_word_doc(doc_path, "T", "| not | a table |")
    assert docx.Document(doc_path).tables == []


def test_read_word_doc_reports_tables(doc_path):
    wt.create_word_doc(doc_path, "T", "| A | B |\n|---|---|\n| 1 | 2 |")
    out = wt.read_word_doc(doc_path)
    assert "[Table 1]" in out and "| A | B |" in out


def test_add_table_to_word_appends(doc_path):
    wt.create_word_doc(doc_path, "T", "body")
    msg = wt.add_table_to_word(doc_path, json.dumps([["H1", "H2"], ["a", "b"]]), heading="Data")
    assert "2x2" in msg
    d = docx.Document(doc_path)
    assert len(d.tables) == 1
    assert "Data" in [p.text for p in d.paragraphs]


def test_add_table_pads_ragged_rows(doc_path):
    wt.create_word_doc(doc_path, "T", "body")
    wt.add_table_to_word(doc_path, json.dumps([["a", "b", "c"], ["only one"]]))
    table = docx.Document(doc_path).tables[0]
    assert len(table.columns) == 3
    assert table.cell(1, 2).text == ""


def test_add_table_rejects_non_json(doc_path):
    wt.create_word_doc(doc_path, "T", "body")
    with pytest.raises(ValueError, match="must be JSON"):
        wt.add_table_to_word(doc_path, "not json at all")


def test_add_table_rejects_empty_rows(doc_path):
    wt.create_word_doc(doc_path, "T", "body")
    with pytest.raises(ValueError, match="non-empty"):
        wt.add_table_to_word(doc_path, "[]")


# ------------------------------------------------------- find/replace ---
def test_find_replace_updates_body(doc_path):
    wt.create_word_doc(doc_path, "T", "Hello Tony, goodbye Tony")
    msg = wt.word_find_replace(doc_path, "Tony", "Boss")
    assert "Replaced 2" in msg
    assert "Tony" not in wt.read_word_doc(doc_path)


def test_find_replace_reaches_into_tables(doc_path):
    wt.create_word_doc(doc_path, "T", "| Name |\n|---|\n| Tony |")
    wt.word_find_replace(doc_path, "Tony", "Boss")
    assert docx.Document(doc_path).tables[0].cell(1, 0).text == "Boss"


def test_find_replace_is_case_sensitive_by_default(doc_path):
    wt.create_word_doc(doc_path, "T", "tony and Tony")
    wt.word_find_replace(doc_path, "Tony", "Boss")
    text = wt.read_word_doc(doc_path)
    assert "tony" in text and "Boss" in text


def test_find_replace_case_insensitive_mode(doc_path):
    wt.create_word_doc(doc_path, "T", "tony and Tony")
    msg = wt.word_find_replace(doc_path, "tony", "Boss", match_case=False)
    assert "Replaced 2" in msg


def test_find_replace_reports_when_nothing_matches(doc_path):
    wt.create_word_doc(doc_path, "T", "body text")
    assert "No occurrences" in wt.word_find_replace(doc_path, "absent", "x")


def test_find_replace_rejects_empty_needle(doc_path):
    wt.create_word_doc(doc_path, "T", "body")
    with pytest.raises(ValueError, match="must not be empty"):
        wt.word_find_replace(doc_path, "", "x")


def test_find_replace_preserves_bold_when_inside_one_run(doc_path):
    wt.create_word_doc(doc_path, "T", "keep **Tony** bold")
    wt.word_find_replace(doc_path, "Tony", "Boss")
    runs = [r for p in docx.Document(doc_path).paragraphs for r in p.runs]
    assert any(r.text == "Boss" and r.bold for r in runs)


# ---------------------------------------------------------------- info ---
def test_doc_info_counts_and_outline(doc_path):
    wt.create_word_doc(doc_path, "Title", "# Section One\nsome words here\n| A |\n|---|\n| 1 |")
    info = wt.get_word_doc_info(doc_path)
    assert "Tables:     1" in info
    assert "Section One" in info
    assert "Words:" in info


def test_doc_info_on_missing_file():
    with pytest.raises(FileNotFoundError):
        wt.get_word_doc_info("/nonexistent/nope.docx")


def test_legacy_doc_extension_is_rejected(tmp_path):
    legacy = tmp_path / "old.doc"
    legacy.write_text("not really a doc")
    with pytest.raises(ValueError, match="not a Word document"):
        wt.read_word_doc(str(legacy))


# -------------------------------------------------------------- report ---
def test_project_report_has_toc_and_sections(tmp_path):
    path = str(tmp_path / "report.docx")
    sections = {"Overview": "# Intro\nbody", "Findings": "- point one"}
    msg = wt.create_project_report(path, "Q3 Report", sections)
    assert "2 sections" in msg
    out = wt.read_word_doc(path)
    assert "Table of Contents" in out and "1. Overview" in out and "2. Findings" in out


def test_project_report_accepts_json_string_sections(tmp_path):
    path = str(tmp_path / "r.docx")
    wt.create_project_report(path, "T", json.dumps({"A": "body a"}))
    assert "body a" in wt.read_word_doc(path)


def test_project_report_rejects_empty_sections(tmp_path):
    with pytest.raises(ValueError, match="non-empty"):
        wt.create_project_report(str(tmp_path / "r.docx"), "T", {})


def test_project_report_renders_tables_in_sections(tmp_path):
    path = str(tmp_path / "r.docx")
    wt.create_project_report(path, "T", {"Data": "| A | B |\n|---|---|\n| 1 | 2 |"})
    assert len(docx.Document(path).tables) == 1


# -------------------------------------------------------------- images ---
def test_add_image_missing_file_errors(doc_path):
    wt.create_word_doc(doc_path, "T", "body")
    with pytest.raises(FileNotFoundError):
        wt.add_image_to_word(doc_path, "/nope/missing.png")


def test_add_image_inserts_and_captions(doc_path, tmp_path):
    png = tmp_path / "dot.png"
    # 1x1 transparent PNG
    png.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00"
        b"\x00\x00IEND\xaeB`\x82"
    )
    wt.create_word_doc(doc_path, "T", "body")
    msg = wt.add_image_to_word(doc_path, str(png), width_inches=1.0, caption="Figure 1")
    assert "dot.png" in msg
    d = docx.Document(doc_path)
    assert len(d.inline_shapes) == 1
    assert "Figure 1" in [p.text for p in d.paragraphs]


# ------------------------------------------------------- registration ---
def test_all_word_tools_register(registry):
    wt.register_tools(registry)
    for name in (
        "create_word_doc",
        "read_word_doc",
        "append_to_word_doc",
        "create_project_report",
        "add_table_to_word",
        "add_image_to_word",
        "word_find_replace",
        "get_word_doc_info",
        "word_to_pdf",
        "open_in_office",
        "office_status",
    ):
        assert name in registry.tools


def test_word_tools_are_reachable_through_auto_discovery(registry):
    registry.auto_discover()
    assert "word_find_replace" in registry.tools
    assert "create_word_doc" in registry.tools


def test_no_duplicate_registration_between_word_and_document_tools(registry):
    """document_tools re-exports Word functions but must not re-register them."""
    from tools import document_tools

    before = set(registry.tools)
    document_tools.register_tools(registry)
    added = set(registry.tools) - before
    assert not any("word" in name for name in added)


def test_errors_surface_as_tool_failures_not_crashes(registry):
    registry.auto_discover()
    out = registry.execute_tool("read_word_doc", {"path": "/nope/missing.docx"})
    assert out["success"] is False
    assert "not found" in out["error"]
