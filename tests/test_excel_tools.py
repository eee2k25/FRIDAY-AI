"""Tests for the Excel (.xlsx) toolset."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl", reason="openpyxl not installed")

from tools import excel_tools as ex  # noqa: E402

ROWS = [["Region", "Q1", "Q2"], ["EMEA", 3.0, 4.1], ["APAC", 2.2, 2.7], ["AMER", 5.0, 5.5]]


@pytest.fixture()
def book(tmp_path):
    path = str(tmp_path / "book.xlsx")
    ex.create_excel(path, json.dumps(ROWS), "Sales")
    return path


def _ws(path, name=None):
    wb = openpyxl.load_workbook(path)
    return wb[name] if name else wb.active


# -------------------------------------------------------------- create ---
def test_create_writes_rows_and_names_the_sheet(book):
    ws = _ws(book)
    assert ws.title == "Sales"
    assert ws["A1"].value == "Region" and ws["C4"].value == 5.5


def test_create_bolds_and_freezes_the_header(book):
    ws = _ws(book)
    assert ws["A1"].font.bold is True
    assert ws.freeze_panes == "A2"


def test_create_autofits_columns(book):
    ws = _ws(book)
    assert ws.column_dimensions["A"].width >= 9


def test_create_makes_missing_directories(tmp_path):
    target = tmp_path / "deep" / "nested" / "b.xlsx"
    ex.create_excel(str(target), json.dumps([["a"]]))
    assert target.exists()


def test_create_rejects_bad_json(tmp_path):
    with pytest.raises(ValueError, match="must be JSON"):
        ex.create_excel(str(tmp_path / "b.xlsx"), "not json")


def test_create_rejects_empty_data(tmp_path):
    with pytest.raises(ValueError, match="non-empty"):
        ex.create_excel(str(tmp_path / "b.xlsx"), "[]")


# -------------------------------------------------------------- sheets ---
def test_add_sheet_with_data(book):
    msg = ex.add_excel_sheet(book, "Notes", json.dumps([["Note"], ["draft"]]))
    assert "Notes" in msg
    assert openpyxl.load_workbook(book).sheetnames == ["Sales", "Notes"]
    assert _ws(book, "Notes")["A2"].value == "draft"


def test_add_sheet_without_data(book):
    ex.add_excel_sheet(book, "Blank")
    assert "Blank" in openpyxl.load_workbook(book).sheetnames


def test_add_duplicate_sheet_is_refused(book):
    with pytest.raises(ValueError, match="already exists"):
        ex.add_excel_sheet(book, "Sales")


def test_unknown_sheet_lists_the_real_ones(book):
    with pytest.raises(ValueError, match="Available sheets: Sales"):
        ex.read_excel(book, "Nope")


def test_append_row(book):
    ex.append_excel_row(book, "Sales", json.dumps(["LATAM", 1.1, 1.3]))
    assert _ws(book)["A5"].value == "LATAM"


def test_append_row_rejects_non_list(book):
    with pytest.raises(ValueError, match="must be a JSON list"):
        ex.append_excel_row(book, "Sales", '{"a": 1}')


# ---------------------------------------------------------------- read ---
def test_read_returns_a_pipe_table(book):
    out = ex.read_excel(book)
    assert "Region | Q1 | Q2" in out and "EMEA | 3 | 4.1" in out


def test_read_reports_other_sheets(book):
    ex.add_excel_sheet(book, "Notes")
    assert "Other sheets: Notes" in ex.read_excel(book, "Sales")


def test_read_respects_max_rows(book):
    out = ex.read_excel(book, "Sales", max_rows=2)
    assert "showing 2" in out and "AMER" not in out


def test_read_missing_file():
    with pytest.raises(FileNotFoundError):
        ex.read_excel("/nope/missing.xlsx")


def test_legacy_xls_extension_rejected(tmp_path):
    legacy = tmp_path / "old.xls"
    legacy.write_text("nope")
    with pytest.raises(ValueError, match="not an Excel workbook"):
        ex.read_excel(str(legacy))


def test_read_range(book):
    out = ex.read_excel_range(book, "A1:B2", "Sales")
    assert "Region | Q1" in out and "EMEA | 3" in out
    assert "APAC" not in out


def test_read_single_cell_range(book):
    assert "EMEA" in ex.read_excel_range(book, "A2", "Sales")


def test_read_range_rejects_nonsense(book):
    with pytest.raises(ValueError, match="cell_range must look like"):
        ex.read_excel_range(book, "the top bit", "Sales")


# ------------------------------------------------------------ formulas ---
def test_update_cells_writes_values_and_formulas(book):
    msg = ex.update_excel_cells(book, json.dumps({"A5": "Total", "B5": "=SUM(B2:B4)"}), "Sales")
    assert "2 cell(s)" in msg and "1 formula" in msg
    ws = _ws(book)
    assert ws["A5"].value == "Total"
    assert ws["B5"].value == "=SUM(B2:B4)"


def test_uncalculated_formulas_show_as_formula_text_not_blanks(book):
    """The core openpyxl gotcha: data_only reads give None for fresh formulas."""
    ex.update_excel_cells(book, json.dumps({"B5": "=SUM(B2:B4)"}), "Sales")
    out = ex.read_excel(book, "Sales")
    assert "=SUM(B2:B4)" in out
    assert "no cached value yet" in out


def test_update_cells_rejects_bad_reference(book):
    with pytest.raises(ValueError, match="not a cell reference"):
        ex.update_excel_cells(book, json.dumps({"not a cell": 1}), "Sales")


def test_update_cells_rejects_non_object(book):
    with pytest.raises(ValueError, match="non-empty JSON object"):
        ex.update_excel_cells(book, "[]", "Sales")


def test_update_cells_lowercase_reference_is_accepted(book):
    ex.update_excel_cells(book, json.dumps({"b5": 99}), "Sales")
    assert _ws(book)["B5"].value == 99


# ---------------------------------------------------------- formatting ---
def test_format_range_applies_bold_and_number_format(book):
    ex.format_excel_range(book, "B2:C4", "Sales", bold=True, number_format="#,##0.00")
    ws = _ws(book)
    assert ws["B2"].font.bold is True
    assert ws["C4"].number_format == "#,##0.00"


def test_format_range_applies_fill_and_width(book):
    ex.format_excel_range(book, "A1:A1", "Sales", fill_color="#FFFF00", column_width=25)
    ws = _ws(book)
    assert "FFFF00" in str(ws["A1"].fill.start_color.rgb)
    assert ws.column_dimensions["A"].width == 25


def test_format_range_rejects_bad_colour(book):
    with pytest.raises(ValueError, match="hex colour"):
        ex.format_excel_range(book, "A1:A1", "Sales", fill_color="banana")


def test_format_range_rejects_bad_range(book):
    with pytest.raises(ValueError, match="cell_range must look like"):
        ex.format_excel_range(book, "somewhere", "Sales", bold=True)


# -------------------------------------------------------------- charts ---
@pytest.mark.parametrize("kind", ["bar", "column", "line", "pie", "scatter"])
def test_every_chart_type_builds(book, kind):
    ex.add_excel_chart(book, "B1:C4", "A2:A4", "Sales", kind, title="T")
    assert len(openpyxl.load_workbook(book)["Sales"]._charts) == 1


def test_chart_without_categories(book):
    ex.add_excel_chart(book, "B1:C4", "", "Sales", "line")
    assert len(openpyxl.load_workbook(book)["Sales"]._charts) == 1


def test_chart_rejects_unknown_type(book):
    with pytest.raises(ValueError, match="chart_type must be one of"):
        ex.add_excel_chart(book, "B1:C4", "A2:A4", "Sales", "radar")


def test_chart_rejects_bad_data_range(book):
    with pytest.raises(ValueError, match="data_range must look like"):
        ex.add_excel_chart(book, "not a range", "", "Sales")


def test_chart_rejects_bad_categories_range(book):
    with pytest.raises(ValueError, match="categories_range must look like"):
        ex.add_excel_chart(book, "B1:C4", "nonsense", "Sales")


def test_chart_honours_a_custom_anchor(book):
    assert "K20" in ex.add_excel_chart(book, "B1:C4", "", "Sales", "bar", anchor="K20")


# ----------------------------------------------------------------- csv ---
def test_excel_to_csv_round_trip(book, tmp_path):
    out = str(tmp_path / "out.csv")
    msg = ex.excel_to_csv(book, out, "Sales")
    assert "4 rows" in msg
    assert "Region,Q1,Q2" in Path(out).read_text()


def test_excel_to_csv_defaults_beside_the_workbook(book):
    ex.excel_to_csv(book)
    assert Path(book).with_suffix(".csv").exists()


def test_csv_to_excel_converts_numbers(tmp_path):
    csv_path = tmp_path / "in.csv"
    csv_path.write_text("Name,Qty,Price\nWidget,3,9.99\n")
    out = str(tmp_path / "out.xlsx")
    ex.csv_to_excel(str(csv_path), out, "Imported")
    ws = _ws(out)
    assert ws["B2"].value == 3 and isinstance(ws["B2"].value, int)
    assert ws["C2"].value == 9.99 and isinstance(ws["C2"].value, float)
    assert ws["A2"].value == "Widget"


def test_csv_to_excel_supports_semicolon_delimiter(tmp_path):
    csv_path = tmp_path / "in.csv"
    csv_path.write_text("a;b\n1;2\n")
    out = str(tmp_path / "out.xlsx")
    ex.csv_to_excel(str(csv_path), out, delimiter=";")
    assert _ws(out)["B2"].value == 2


def test_csv_to_excel_missing_source(tmp_path):
    with pytest.raises(FileNotFoundError):
        ex.csv_to_excel("/nope/missing.csv", str(tmp_path / "o.xlsx"))


def test_csv_to_excel_rejects_empty_file(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    with pytest.raises(ValueError, match="is empty"):
        ex.csv_to_excel(str(empty), str(tmp_path / "o.xlsx"))


def test_full_csv_round_trip_preserves_values(book, tmp_path):
    csv_out = str(tmp_path / "r.csv")
    xlsx_out = str(tmp_path / "r.xlsx")
    ex.excel_to_csv(book, csv_out, "Sales")
    ex.csv_to_excel(csv_out, xlsx_out, "Back")
    assert _ws(xlsx_out)["C4"].value == 5.5


# ------------------------------------------------------------ analysis ---
def test_summarize_profiles_numeric_columns(book):
    out = ex.summarize_excel(book, "Sales")
    assert "Q1: 3/3 filled" in out
    assert "sum 10.20" in out and "mean 3.40" in out and "max 5.00" in out


def test_summarize_profiles_text_columns(book):
    out = ex.summarize_excel(book, "Sales")
    assert "Region" in out and "3 unique" in out


def test_summarize_flags_uncalculated_formulas(book):
    ex.update_excel_cells(book, json.dumps({"B5": "=SUM(B2:B4)"}), "Sales")
    assert "count as empty above" in ex.summarize_excel(book, "Sales")


def test_summarize_header_only_sheet(tmp_path):
    path = str(tmp_path / "h.xlsx")
    ex.create_excel(path, json.dumps([["Only", "Headers"]]))
    assert "no data rows" in ex.summarize_excel(path)


def test_summarize_computes_median(tmp_path):
    path = str(tmp_path / "m.xlsx")
    ex.create_excel(path, json.dumps([["n"], [1], [2], [3], [10]]))
    assert "median 2.50" in ex.summarize_excel(path)


def test_info_reports_sheets_formulas_and_charts(book):
    ex.update_excel_cells(book, json.dumps({"B5": "=SUM(B2:B4)"}), "Sales")
    ex.add_excel_chart(book, "B1:C4", "A2:A4", "Sales", "bar")
    ex.add_excel_sheet(book, "Notes")
    info = ex.get_excel_info(book)
    assert "Sheets: 2" in info
    assert "1 formulas" in info and "1 chart(s)" in info and "frozen at A2" in info


# -------------------------------------------------------- registration ---
def test_all_excel_tools_register(registry):
    ex.register_tools(registry)
    for name in (
        "create_excel",
        "add_excel_sheet",
        "append_excel_row",
        "read_excel",
        "read_excel_range",
        "update_excel_cells",
        "format_excel_range",
        "add_excel_chart",
        "csv_to_excel",
        "excel_to_csv",
        "summarize_excel",
        "get_excel_info",
        "excel_to_pdf",
    ):
        assert name in registry.tools


def test_excel_tools_reachable_via_auto_discovery(registry):
    registry.auto_discover()
    assert "summarize_excel" in registry.tools


def test_errors_surface_as_tool_failures(registry):
    registry.auto_discover()
    out = registry.execute_tool("read_excel", {"path": "/nope/missing.xlsx"})
    assert out["success"] is False and "not found" in out["error"]


def test_excel_to_pdf_missing_file():
    with pytest.raises(FileNotFoundError):
        ex.excel_to_pdf("/nope/missing.xlsx")


def test_document_tools_shim_still_exposes_old_names():
    from tools import document_tools

    assert document_tools.create_excel is ex.create_excel
    assert callable(document_tools.create_word_doc)
    assert not hasattr(document_tools, "register_tools")
