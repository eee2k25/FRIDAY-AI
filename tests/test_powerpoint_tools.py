"""Tests for the PowerPoint (.pptx) toolset."""
from __future__ import annotations

import json

import pytest

pptx = pytest.importorskip("pptx", reason="python-pptx not installed")

from tools import powerpoint_tools as pt  # noqa: E402

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00"
    b"\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture()
def deck(tmp_path):
    path = str(tmp_path / "deck.pptx")
    pt.create_presentation(path, "Test Deck")
    return path


def _slides(path):
    return list(pptx.Presentation(path).slides)


def _titles(path):
    return [s.shapes.title.text if s.shapes.title is not None else "" for s in _slides(path)]


# ------------------------------------------------------ outline parser ---
def test_outline_splits_on_headings():
    specs = pt.parse_outline("# One\n- a\n# Two\n- b")
    assert [s["title"] for s in specs] == ["One", "Two"]
    assert specs[0]["bullets"] == ["- a"]


def test_outline_captures_notes():
    specs = pt.parse_outline("# S\n- bullet\nNotes: say hello")
    assert specs[0]["notes"] == "say hello"
    assert specs[0]["bullets"] == ["- bullet"]


def test_outline_notes_continue_across_lines():
    specs = pt.parse_outline("# S\nNotes: first part\nsecond part")
    assert specs[0]["notes"] == "first part second part"


def test_outline_captures_pipe_tables_without_separator_row():
    specs = pt.parse_outline("# S\n| A | B |\n|---|---|\n| 1 | 2 |")
    assert specs[0]["table"] == [["A", "B"], ["1", "2"]]


def test_outline_content_before_first_heading_becomes_a_slide():
    specs = pt.parse_outline("- orphan bullet")
    assert len(specs) == 1 and specs[0]["title"] == ""


def test_empty_outline_yields_no_slides():
    assert pt.parse_outline("") == []


@pytest.mark.parametrize(
    "line,level",
    [("- top", 0), ("  - one", 1), ("    - two", 2), ("\t- tab", 1), ("            - deep", 4)],
)
def test_bullet_levels_from_indentation(line, level):
    assert pt._bullet_level(line) == level


# -------------------------------------------------------------- create ---
def test_create_makes_a_title_slide(tmp_path):
    path = str(tmp_path / "d.pptx")
    pt.create_presentation(path, "My Title", subtitle="A subtitle")
    slides = _slides(path)
    assert len(slides) == 1
    assert slides[0].shapes.title.text == "My Title"
    assert "A subtitle" in "\n".join(s.text_frame.text for s in slides[0].placeholders if s.has_text_frame)


def test_create_builds_one_slide_per_heading(tmp_path):
    path = str(tmp_path / "d.pptx")
    msg = pt.create_presentation(path, "T", "# Alpha\n- a\n# Beta\n- b")
    assert "3 slides" in msg  # title + 2
    assert _titles(path) == ["T", "Alpha", "Beta"]


def test_create_is_widescreen_by_default(tmp_path):
    path = str(tmp_path / "d.pptx")
    pt.create_presentation(path, "T")
    assert round(pptx.Presentation(path).slide_width.inches, 1) == 13.3


def test_create_supports_four_three(tmp_path):
    path = str(tmp_path / "d.pptx")
    pt.create_presentation(path, "T", widescreen=False)
    assert round(pptx.Presentation(path).slide_width.inches, 1) == 10.0


def test_create_makes_missing_directories(tmp_path):
    target = tmp_path / "nested" / "deep" / "d.pptx"
    pt.create_presentation(str(target), "T")
    assert target.exists()


def test_create_renders_sub_bullet_levels(tmp_path):
    path = str(tmp_path / "d.pptx")
    pt.create_presentation(path, "T", "# S\n- top\n  - nested")
    body = [s for s in _slides(path)[1].placeholders if s.placeholder_format.idx != 0][0]
    levels = [p.level for p in body.text_frame.paragraphs if p.text.strip()]
    assert levels == [0, 1]


def test_create_renders_bold_runs(tmp_path):
    path = str(tmp_path / "d.pptx")
    pt.create_presentation(path, "T", "# S\n- plain **bold** end")
    runs = [
        r
        for shape in _slides(path)[1].shapes
        if shape.has_text_frame
        for p in shape.text_frame.paragraphs
        for r in p.runs
    ]
    assert any(r.text == "bold" and r.font.bold for r in runs)


def test_create_renders_outline_tables(tmp_path):
    path = str(tmp_path / "d.pptx")
    pt.create_presentation(path, "T", "# Data\n| A | B |\n|---|---|\n| 1 | 2 |")
    tables = [s for s in _slides(path)[1].shapes if s.has_table]
    assert len(tables) == 1
    assert tables[0].table.cell(0, 0).text == "A"


def test_create_attaches_speaker_notes(tmp_path):
    path = str(tmp_path / "d.pptx")
    pt.create_presentation(path, "T", "# S\n- a\nNotes: remember this")
    assert "remember this" in _slides(path)[1].notes_slide.notes_text_frame.text


# ----------------------------------------------------------- add_slide ---
def test_add_slide_appends(deck):
    pt.add_slide(deck, "Second", "- point one")
    assert _titles(deck) == ["Test Deck", "Second"]


def test_add_slide_with_table_content(deck):
    pt.add_slide(deck, "Data", "| A | B |\n|---|---|\n| 1 | 2 |")
    assert any(s.has_table for s in _slides(deck)[1].shapes)


def test_add_slide_accepts_layout_names(deck):
    pt.add_slide(deck, "Section", "", layout="section")
    assert _titles(deck)[1] == "Section"


def test_add_slide_rejects_unknown_layout(deck):
    with pytest.raises(ValueError, match="unknown layout"):
        pt.add_slide(deck, "X", "", layout="hologram")


def test_add_slide_rejects_out_of_range_layout_index(deck):
    with pytest.raises(ValueError, match="out of range"):
        pt.add_slide(deck, "X", "", layout=99)


# --------------------------------------------------------------- media ---
def test_add_image_slide(deck, tmp_path):
    img = tmp_path / "dot.png"
    img.write_bytes(PNG_1X1)
    msg = pt.add_image_slide(deck, "Picture", str(img), caption="Figure 1")
    assert "dot.png" in msg
    shapes = _slides(deck)[1].shapes
    assert any("PICTURE" in str(s.shape_type) for s in shapes)
    assert any("Figure 1" in s.text_frame.text for s in shapes if s.has_text_frame)


def test_add_image_slide_missing_file(deck):
    with pytest.raises(FileNotFoundError):
        pt.add_image_slide(deck, "X", "/nope/missing.png")


def test_add_image_is_centred_within_the_slide(deck, tmp_path):
    img = tmp_path / "dot.png"
    img.write_bytes(PNG_1X1)
    pt.add_image_slide(deck, "Pic", str(img))
    prs = pptx.Presentation(deck)
    pic = next(s for s in list(prs.slides)[1].shapes if "PICTURE" in str(s.shape_type))
    left_gap = pic.left
    right_gap = prs.slide_width - (pic.left + pic.width)
    assert abs(left_gap - right_gap) < 20000  # within a rounding EMU of centred


def test_add_table_slide(deck):
    msg = pt.add_table_slide(deck, "Metrics", json.dumps([["A", "B"], [1, 2]]))
    assert "2x2" in msg
    table = next(s for s in _slides(deck)[1].shapes if s.has_table).table
    assert table.cell(1, 1).text == "2"


def test_add_table_slide_bolds_the_header(deck):
    pt.add_table_slide(deck, "M", json.dumps([["H"], ["v"]]))
    table = next(s for s in _slides(deck)[1].shapes if s.has_table).table
    assert any(r.font.bold for p in table.cell(0, 0).text_frame.paragraphs for r in p.runs)


def test_add_table_slide_rejects_bad_json(deck):
    with pytest.raises(ValueError, match="must be JSON"):
        pt.add_table_slide(deck, "M", "nope")


# -------------------------------------------------------------- charts ---
@pytest.mark.parametrize("kind", ["bar", "column", "line", "pie", "doughnut"])
def test_every_chart_type_builds(deck, kind):
    pt.add_chart_slide(deck, "C", '["a","b"]', '{"S":[1,2]}', kind)
    assert any(s.has_chart for s in _slides(deck)[-1].shapes)


def test_chart_rejects_unknown_type(deck):
    with pytest.raises(ValueError, match="chart_type must be one of"):
        pt.add_chart_slide(deck, "C", '["a"]', '{"S":[1]}', "radar")


def test_chart_rejects_length_mismatch(deck):
    with pytest.raises(ValueError, match="3 values but there are 2 categories"):
        pt.add_chart_slide(deck, "C", '["a","b"]', '{"S":[1,2,3]}')


def test_chart_rejects_non_list_series(deck):
    with pytest.raises(ValueError, match="must map to a list"):
        pt.add_chart_slide(deck, "C", '["a"]', '{"S": 5}')


def test_chart_rejects_empty_series(deck):
    with pytest.raises(ValueError, match="non-empty JSON object"):
        pt.add_chart_slide(deck, "C", '["a"]', "{}")


def test_chart_supports_multiple_series(deck):
    pt.add_chart_slide(deck, "C", '["a","b"]', '{"X":[1,2],"Y":[3,4]}', "column")
    chart = next(s for s in _slides(deck)[-1].shapes if s.has_chart).chart
    assert len(chart.plots[0].series) == 2


# ---------------------------------------------------------------- read ---
def test_read_presentation_includes_titles_and_bullets(tmp_path):
    path = str(tmp_path / "d.pptx")
    pt.create_presentation(path, "T", "# Agenda\n- first\n- second")
    out = pt.read_presentation(path)
    assert "Slide 2: Agenda" in out and "- first" in out


def test_read_presentation_includes_tables_and_charts(deck):
    pt.add_table_slide(deck, "Data", '[["A"],["1"]]')
    pt.add_chart_slide(deck, "Chart", '["a"]', '{"S":[1]}')
    out = pt.read_presentation(deck)
    assert "| A |" in out and "[Chart:" in out


def test_read_presentation_can_skip_notes(tmp_path):
    path = str(tmp_path / "d.pptx")
    pt.create_presentation(path, "T", "# S\n- a\nNotes: secret")
    assert "secret" in pt.read_presentation(path)
    assert "secret" not in pt.read_presentation(path, include_notes=False)


def test_read_missing_presentation():
    with pytest.raises(FileNotFoundError):
        pt.read_presentation("/nope/missing.pptx")


def test_legacy_ppt_extension_rejected(tmp_path):
    legacy = tmp_path / "old.ppt"
    legacy.write_text("nope")
    with pytest.raises(ValueError, match="not a PowerPoint file"):
        pt.read_presentation(str(legacy))


# --------------------------------------------------------------- notes ---
def test_set_speaker_notes(deck):
    pt.set_speaker_notes(deck, 1, "hello from the wings")
    assert "hello from the wings" in _slides(deck)[0].notes_slide.notes_text_frame.text


def test_set_speaker_notes_out_of_range(deck):
    with pytest.raises(ValueError, match="does not exist"):
        pt.set_speaker_notes(deck, 99, "x")


def test_set_speaker_notes_rejects_zero(deck):
    with pytest.raises(ValueError, match="does not exist"):
        pt.set_speaker_notes(deck, 0, "x")


# ---------------------------------------------------------------- info ---
def test_info_counts_everything(deck, tmp_path):
    img = tmp_path / "dot.png"
    img.write_bytes(PNG_1X1)
    pt.add_table_slide(deck, "T", '[["A"],["1"]]')
    pt.add_chart_slide(deck, "C", '["a"]', '{"S":[1]}')
    pt.add_image_slide(deck, "I", str(img))
    pt.set_speaker_notes(deck, 1, "notes here")
    info = pt.get_presentation_info(deck)
    assert "Slides:      4" in info
    assert "Images:      1" in info and "Tables: 1" in info and "Charts: 1" in info
    assert "With notes:  1/4" in info
    assert "16:9 widescreen" in info


def test_info_marks_slide_contents(deck):
    pt.add_chart_slide(deck, "Revenue", '["a"]', '{"S":[1]}')
    assert "[chart]" in pt.get_presentation_info(deck)


# -------------------------------------------------------- registration ---
def test_all_powerpoint_tools_register(registry):
    pt.register_tools(registry)
    for name in (
        "create_presentation",
        "add_slide",
        "add_image_slide",
        "add_table_slide",
        "add_chart_slide",
        "read_presentation",
        "set_speaker_notes",
        "get_presentation_info",
        "pptx_to_pdf",
    ):
        assert name in registry.tools


def test_powerpoint_tools_reachable_via_auto_discovery(registry):
    registry.auto_discover()
    assert "create_presentation" in registry.tools


def test_errors_surface_as_tool_failures(registry):
    registry.auto_discover()
    out = registry.execute_tool("read_presentation", {"path": "/nope/missing.pptx"})
    assert out["success"] is False and "not found" in out["error"]


def test_pptx_to_pdf_missing_file():
    with pytest.raises(FileNotFoundError):
        pt.pptx_to_pdf("/nope/missing.pptx")


def test_full_deck_round_trip(tmp_path):
    """Build a realistic deck end-to-end and read it back."""
    path = str(tmp_path / "quarterly.pptx")
    pt.create_presentation(
        path,
        "Q3 Review",
        "# Agenda\n- Results\n  - By region\n- Outlook\nNotes: 30 seconds\n\n"
        "# Results\n| Region | Rev |\n|---|---|\n| EMEA | 4.1 |",
        subtitle="FRIDAY",
    )
    pt.add_chart_slide(path, "Trend", '["Q1","Q2","Q3"]', '{"Rev":[3.0,3.6,4.1]}', "line")
    out = pt.read_presentation(path)
    assert "Q3 Review" in out and "By region" in out and "| EMEA | 4.1 |" in out and "[Chart:" in out
    assert "Slides:      4" in pt.get_presentation_info(path)
