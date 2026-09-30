"""Excel tools — build, read, edit, chart and convert .xlsx via openpyxl.

Covers the whole workbook lifecycle: create from rows or CSV, add sheets,
write formulas, update individual cells, format ranges, add native charts,
profile the data, and export to CSV or PDF.

One gotcha this module handles for you: **openpyxl does not evaluate
formulas.** A formula written here has no cached value until Excel (or
LibreOffice) opens and recalculates the file, so a naive data_only read gives
back None. read_excel() detects that and shows the formula text instead, with
a note, so FRIDAY never reports a blank where a calculation lives.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

MAX_READ_ROWS = 500
MAX_COL_WIDTH = 60

CHART_TYPES = ("bar", "column", "line", "pie", "scatter")


def _p(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    return p


def _xlsx():
    try:
        import openpyxl

        return openpyxl
    except ImportError as e:
        raise RuntimeError("openpyxl not installed. Run: pip install openpyxl") from e


def _open_wb(path: str, data_only: bool = False):
    """Load an existing workbook with helpful errors."""
    openpyxl = _xlsx()
    p = _p(path)
    if not p.exists():
        raise FileNotFoundError(f"workbook not found: {p}")
    if p.suffix.lower() not in (".xlsx", ".xlsm"):
        raise ValueError(f"not an Excel workbook: {p.name} (need .xlsx; .xls is not supported)")
    try:
        return openpyxl.load_workbook(str(p), data_only=data_only), p
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"could not open {p.name}: {type(e).__name__}: {e}") from e


def _sheet(wb, sheet_name: str | None):
    """Resolve a sheet by name, defaulting to the active one."""
    if not sheet_name:
        return wb.active
    if sheet_name not in wb.sheetnames:
        raise ValueError(
            f"sheet {sheet_name!r} not found. Available sheets: {', '.join(wb.sheetnames)}"
        )
    return wb[sheet_name]


def _parse_rows(data) -> list[list]:
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as e:
            raise ValueError(f'data must be JSON, e.g. [["Name","Qty"],["Widget",3]]: {e}') from e
    if not isinstance(data, list) or not data:
        raise ValueError("data must be a non-empty list of rows")
    return [r if isinstance(r, list) else [r] for r in data]


def _style_header(ws, openpyxl) -> None:
    if ws.max_row < 1:
        return
    for cell in ws[1]:
        cell.font = openpyxl.styles.Font(bold=True)
        cell.alignment = openpyxl.styles.Alignment(horizontal="center", vertical="center")
    ws.freeze_panes = "A2"


def _autofit(ws) -> None:
    """Approximate Excel's auto-fit: widen each column to its longest value."""
    from openpyxl.utils import get_column_letter

    for idx, column in enumerate(ws.iter_cols(), 1):
        longest = 0
        for cell in column:
            if cell.value is not None:
                longest = max(longest, len(str(cell.value)))
        ws.column_dimensions[get_column_letter(idx)].width = min(MAX_COL_WIDTH, max(9, longest + 2))


def _is_formula(value) -> bool:
    return isinstance(value, str) and value.startswith("=")


# --------------------------------------------------------------- create ---
def create_excel(path: str, data: str, sheet_name: str = "Sheet1") -> str:
    """Create an .xlsx from a JSON list of rows. First row becomes a bold,
    frozen header and columns are auto-fitted."""
    openpyxl = _xlsx()
    rows = _parse_rows(data)
    p = _p(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name or "Sheet1"
    for row in rows:
        ws.append(row)
    _style_header(ws, openpyxl)
    _autofit(ws)
    wb.save(str(p))
    return f"Created: {p} — sheet {ws.title!r}, {len(rows)} rows x {ws.max_column} columns"


def add_excel_sheet(path: str, sheet_name: str, data: str = "") -> str:
    """Add a new sheet to an existing workbook, optionally filled with rows."""
    openpyxl = _xlsx()
    wb, p = _open_wb(path)
    if sheet_name in wb.sheetnames:
        raise ValueError(f"sheet {sheet_name!r} already exists in {p.name}")
    ws = wb.create_sheet(title=sheet_name)
    rows = _parse_rows(data) if str(data).strip() else []
    for row in rows:
        ws.append(row)
    if rows:
        _style_header(ws, openpyxl)
        _autofit(ws)
    wb.save(str(p))
    return f"Added sheet {sheet_name!r} to {p} ({len(rows)} rows). Sheets now: {', '.join(wb.sheetnames)}"


def append_excel_row(path: str, sheet_name: str, row_data: str) -> str:
    """Append one row (JSON list) to an existing sheet."""
    try:
        row = json.loads(row_data) if isinstance(row_data, str) else row_data
    except json.JSONDecodeError as e:
        raise ValueError(f'row_data must be a JSON list, e.g. ["Widget",3,9.99]: {e}') from e
    if not isinstance(row, list):
        raise ValueError("row_data must be a JSON list")
    wb, p = _open_wb(path)
    ws = _sheet(wb, sheet_name)
    ws.append(row)
    _autofit(ws)
    wb.save(str(p))
    return f"Appended row to {ws.title!r} in {p} (now {ws.max_row} rows)"


# ----------------------------------------------------------------- read ---
def read_excel(path: str, sheet_name: str = "", max_rows: int = MAX_READ_ROWS) -> str:
    """Read a sheet as a pipe-separated table.

    Formulas with no cached value (because openpyxl wrote them and Excel has
    not recalculated yet) are shown as their formula text rather than blanks.
    """
    wb_values, p = _open_wb(path, data_only=True)
    wb_formulas, _ = _open_wb(path, data_only=False)
    ws_v = _sheet(wb_values, sheet_name)
    ws_f = _sheet(wb_formulas, sheet_name)

    limit = max(1, int(max_rows))
    lines: list[str] = []
    uncalculated = 0
    for row_v, row_f in zip(ws_v.iter_rows(), ws_f.iter_rows(), strict=False):
        cells = []
        for cv, cf in zip(row_v, row_f, strict=False):
            value = cv.value
            if value is None and _is_formula(cf.value):
                value = cf.value  # show the formula itself
                uncalculated += 1
            cells.append("" if value is None else str(value))
        if any(c.strip() for c in cells):
            lines.append(" | ".join(cells))
        if len(lines) >= limit:
            break

    if not lines:
        return f"Sheet {ws_v.title!r} is empty."
    header = f"Sheet {ws_v.title!r} ({ws_f.max_row} rows x {ws_f.max_column} cols"
    header += f", showing {len(lines)})" if ws_f.max_row > len(lines) else ")"
    out = [header, *lines]
    if uncalculated:
        out.append(
            f"\n[{uncalculated} formula cell(s) have no cached value yet — Excel/LibreOffice "
            "computes them on open. The formula text is shown instead.]"
        )
    if len(wb_values.sheetnames) > 1:
        out.append(f"[Other sheets: {', '.join(n for n in wb_values.sheetnames if n != ws_v.title)}]")
    return "\n".join(out)


def read_excel_range(path: str, cell_range: str, sheet_name: str = "") -> str:
    """Read a specific range such as 'A1:C10' as a pipe-separated table."""
    if not re.fullmatch(r"[A-Za-z]+\d+(:[A-Za-z]+\d+)?", cell_range.strip()):
        raise ValueError(f"cell_range must look like 'A1:C10' or 'B2', got {cell_range!r}")
    wb, _ = _open_wb(path, data_only=True)
    ws = _sheet(wb, sheet_name)
    try:
        region = ws[cell_range.strip()]
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"could not read range {cell_range!r}: {e}") from e
    if not isinstance(region, tuple):
        region = ((region,),)
    elif region and not isinstance(region[0], tuple):
        region = (region,)
    lines = [
        " | ".join("" if c.value is None else str(c.value) for c in row) for row in region
    ]
    return f"{ws.title}!{cell_range.upper()}:\n" + "\n".join(lines)


# ----------------------------------------------------------------- edit ---
def update_excel_cells(path: str, updates: str, sheet_name: str = "") -> str:
    """Set individual cells. `updates` is a JSON object of cell → value.

    Values beginning with '=' are written as live Excel formulas, e.g.
    {"B2": 42, "D10": "=SUM(D2:D9)", "A1": "Total"}.
    """
    try:
        mapping = json.loads(updates) if isinstance(updates, str) else updates
    except json.JSONDecodeError as e:
        raise ValueError(f'updates must be a JSON object, e.g. {{"B2": 5, "C2": "=B2*2"}}: {e}') from e
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError('updates must be a non-empty JSON object, e.g. {"B2": 5}')

    wb, p = _open_wb(path)
    ws = _sheet(wb, sheet_name)
    formulas = 0
    for ref, value in mapping.items():
        if not re.fullmatch(r"[A-Za-z]+\d+", str(ref).strip()):
            raise ValueError(f"{ref!r} is not a cell reference like 'B2'")
        ws[str(ref).strip().upper()] = value
        if _is_formula(value):
            formulas += 1
    _autofit(ws)
    wb.save(str(p))
    note = f" ({formulas} formula(s) — Excel calculates them on open)" if formulas else ""
    return f"Updated {len(mapping)} cell(s) in {ws.title!r} of {p}{note}"


def format_excel_range(
    path: str,
    cell_range: str,
    sheet_name: str = "",
    bold: bool = False,
    number_format: str = "",
    fill_color: str = "",
    column_width: float = 0,
) -> str:
    """Style a range: bold, number format (e.g. '#,##0.00' or '0%'), fill colour, width."""
    openpyxl = _xlsx()
    from openpyxl.utils import range_boundaries

    wb, p = _open_wb(path)
    ws = _sheet(wb, sheet_name)
    try:
        min_col, min_row, max_col, max_row = range_boundaries(cell_range.strip().upper())
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"cell_range must look like 'A1:C10', got {cell_range!r}") from e

    colour = fill_color.strip().lstrip("#").upper()
    if colour and not re.fullmatch(r"[0-9A-F]{6,8}", colour):
        raise ValueError(f"fill_color must be a hex colour like 'FFFF00', got {fill_color!r}")
    fill = (
        openpyxl.styles.PatternFill(start_color=colour, end_color=colour, fill_type="solid")
        if colour
        else None
    )

    touched = 0
    for row in ws.iter_rows(min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col):
        for cell in row:
            if bold:
                cell.font = openpyxl.styles.Font(bold=True)
            if number_format:
                cell.number_format = number_format
            if fill is not None:
                cell.fill = fill
            touched += 1

    if column_width and float(column_width) > 0:
        from openpyxl.utils import get_column_letter

        for col in range(min_col, max_col + 1):
            ws.column_dimensions[get_column_letter(col)].width = float(column_width)

    wb.save(str(p))
    return f"Formatted {touched} cell(s) in {ws.title}!{cell_range.upper()} of {p}"


# ---------------------------------------------------------------- chart ---
def add_excel_chart(
    path: str,
    data_range: str,
    categories_range: str = "",
    sheet_name: str = "",
    chart_type: str = "bar",
    title: str = "",
    anchor: str = "",
) -> str:
    """Add a native Excel chart. `data_range` should include the header row so
    series get their names (e.g. 'B1:C10'); `categories_range` is the labels
    column without its header (e.g. 'A2:A10')."""
    from openpyxl.chart import BarChart, LineChart, PieChart, Reference, ScatterChart
    from openpyxl.utils import range_boundaries

    kind = str(chart_type).strip().lower()
    if kind not in CHART_TYPES:
        raise ValueError(f"chart_type must be one of {list(CHART_TYPES)}, got {chart_type!r}")

    wb, p = _open_wb(path)
    ws = _sheet(wb, sheet_name)
    try:
        d_min_col, d_min_row, d_max_col, d_max_row = range_boundaries(data_range.strip().upper())
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"data_range must look like 'B1:C10', got {data_range!r}") from e

    chart = {
        "bar": BarChart,
        "column": BarChart,
        "line": LineChart,
        "pie": PieChart,
        "scatter": ScatterChart,
    }[kind]()
    if kind == "bar":
        chart.type = "bar"
    elif kind == "column":
        chart.type = "col"
    if title:
        chart.title = title

    data = Reference(ws, min_col=d_min_col, min_row=d_min_row, max_col=d_max_col, max_row=d_max_row)
    chart.add_data(data, titles_from_data=True)

    if categories_range.strip():
        try:
            c_min_col, c_min_row, c_max_col, c_max_row = range_boundaries(
                categories_range.strip().upper()
            )
        except Exception as e:  # noqa: BLE001
            raise ValueError(
                f"categories_range must look like 'A2:A10', got {categories_range!r}"
            ) from e
        chart.set_categories(
            Reference(ws, min_col=c_min_col, min_row=c_min_row, max_col=c_max_col, max_row=c_max_row)
        )

    chart.height, chart.width = 8, 16
    ws.add_chart(chart, (anchor.strip().upper() or "H2"))
    wb.save(str(p))
    return f"Added a {kind} chart to {ws.title!r} in {p} (anchored at {anchor.upper() or 'H2'})"


# ------------------------------------------------------------------ csv ---
def csv_to_excel(csv_path: str, path: str, sheet_name: str = "Sheet1", delimiter: str = ",") -> str:
    """Import a CSV file into a new .xlsx, converting numbers as it goes."""
    src = _p(csv_path)
    if not src.exists():
        raise FileNotFoundError(f"CSV not found: {src}")
    with open(src, newline="", encoding="utf-8-sig", errors="replace") as f:
        rows = list(csv.reader(f, delimiter=delimiter or ","))
    if not rows:
        raise ValueError(f"{src.name} is empty")

    def _coerce(v: str):
        s = v.strip()
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return float(s)
        except ValueError:
            return v

    typed = [[_coerce(c) for c in row] for row in rows]
    return create_excel(path, json.dumps(typed, default=str), sheet_name) + f" (from {src.name})"


def excel_to_csv(path: str, output_path: str = "", sheet_name: str = "") -> str:
    """Export one sheet to a .csv file."""
    wb, p = _open_wb(path, data_only=True)
    ws = _sheet(wb, sheet_name)
    out = _p(output_path) if output_path else p.with_suffix(".csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for row in ws.iter_rows(values_only=True):
            if any(v is not None and str(v).strip() for v in row):
                writer.writerow(["" if v is None else v for v in row])
                count += 1
    return f"Exported {count} rows from {ws.title!r} to {out}"


# ------------------------------------------------------------- analysis ---
def summarize_excel(path: str, sheet_name: str = "") -> str:
    """Profile each column: type, fill rate, and stats (sum/mean/min/max) or
    top values. Use this before answering questions about a spreadsheet."""
    wb, p = _open_wb(path, data_only=True)
    ws = _sheet(wb, sheet_name)
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return f"Sheet {ws.title!r} is empty."

    # Formulas openpyxl wrote have no cached value, so they read as blank here.
    # Count them up front and say so, rather than silently under-reporting.
    wb_f, _ = _open_wb(path, data_only=False)
    ws_f = _sheet(wb_f, sheet_name)
    pending = sum(1 for row in ws_f.iter_rows() for cell in row if _is_formula(cell.value))

    headers = [str(h) if h is not None else f"Column {i + 1}" for i, h in enumerate(rows[0])]
    body = rows[1:]
    if not body:
        return f"Sheet {ws.title!r} has a header ({', '.join(headers)}) but no data rows."

    out = [f"Sheet {ws.title!r} — {len(body)} data rows x {len(headers)} columns", ""]
    for i, name in enumerate(headers):
        values = [r[i] for r in body if i < len(r)]
        filled = [v for v in values if v is not None and str(v).strip() != ""]
        numbers = [v for v in filled if isinstance(v, (int, float)) and not isinstance(v, bool)]
        line = [f"{name}: {len(filled)}/{len(values)} filled"]
        if numbers and len(numbers) >= len(filled) / 2:
            total = sum(numbers)
            ordered = sorted(numbers)
            mid = len(ordered) // 2
            median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
            line.append(
                f"numeric — sum {total:,.2f}, mean {total / len(numbers):,.2f}, "
                f"median {median:,.2f}, min {min(numbers):,.2f}, max {max(numbers):,.2f}"
            )
        else:
            uniques = {}
            for v in filled:
                uniques[str(v)] = uniques.get(str(v), 0) + 1
            top = sorted(uniques.items(), key=lambda kv: -kv[1])[:3]
            line.append(
                f"text — {len(uniques)} unique"
                + (f", top: {', '.join(f'{k} ({n})' for k, n in top)}" if top else "")
            )
        out.append("  " + " | ".join(line))
    if pending:
        out.append(
            f"\n[{pending} formula cell(s) have no cached value yet, so they count as empty above. "
            "Excel/LibreOffice fills them in on open.]"
        )
    return "\n".join(out)


def get_excel_info(path: str) -> str:
    """Summarise a workbook: every sheet's size, formula count, charts and freeze panes."""
    wb, p = _open_wb(path)
    lines = [
        f"File:   {p}",
        f"Size:   {p.stat().st_size:,} bytes",
        f"Sheets: {len(wb.sheetnames)} — {', '.join(wb.sheetnames)}",
        "",
    ]
    for name in wb.sheetnames:
        ws = wb[name]
        formulas = sum(
            1 for row in ws.iter_rows() for cell in row if _is_formula(cell.value)
        )
        charts = len(getattr(ws, "_charts", []))
        detail = f"  {name}: {ws.max_row} rows x {ws.max_column} cols"
        extras = []
        if formulas:
            extras.append(f"{formulas} formulas")
        if charts:
            extras.append(f"{charts} chart(s)")
        if ws.freeze_panes:
            extras.append(f"frozen at {ws.freeze_panes}")
        if extras:
            detail += f"  [{', '.join(extras)}]"
        lines.append(detail)
    if wb.defined_names:
        lines.append(f"\nNamed ranges: {', '.join(list(wb.defined_names)[:20])}")
    return "\n".join(lines)


def excel_to_pdf(path: str, output_path: str = "") -> str:
    """Convert a workbook to PDF using Excel if available, else LibreOffice."""
    from core.office import export_pdf

    p = _p(path)
    if not p.exists():
        raise FileNotFoundError(f"workbook not found: {p}")
    pdf = export_pdf("excel", p, output_path or None)
    return f"Exported PDF: {pdf} ({Path(pdf).stat().st_size:,} bytes)"


_DECLARATIONS: list[dict] = [
    {
        "name": "create_excel",
        "description": "Create an Excel .xlsx from a JSON list of rows. The first row becomes a bold, frozen header and columns are auto-fitted.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "data": {
                    "type": "string",
                    "description": 'JSON list of rows, e.g. [["Name","Qty"],["Widget",3]]',
                },
                "sheet_name": {"type": "string"},
            },
            "required": ["path", "data"],
        },
    },
    {
        "name": "add_excel_sheet",
        "description": "Add a new sheet to an existing workbook, optionally filled with JSON rows.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "sheet_name": {"type": "string"},
                "data": {"type": "string", "description": "Optional JSON list of rows"},
            },
            "required": ["path", "sheet_name"],
        },
    },
    {
        "name": "append_excel_row",
        "description": "Append one row (JSON list) to a sheet in an existing .xlsx.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "sheet_name": {"type": "string"},
                "row_data": {"type": "string", "description": 'JSON list, e.g. ["Widget",3,9.99]'},
            },
            "required": ["path", "sheet_name", "row_data"],
        },
    },
    {
        "name": "read_excel",
        "description": "Read a sheet as a pipe-separated table. Formula cells that Excel has not recalculated yet are shown as their formula text, never as blanks.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "sheet_name": {"type": "string", "description": "Defaults to the active sheet"},
                "max_rows": {"type": "integer", "description": "Default 500"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_excel_range",
        "description": "Read one specific range, e.g. 'A1:C10' — cheaper than reading a whole large sheet.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "cell_range": {"type": "string", "description": "e.g. A1:C10"},
                "sheet_name": {"type": "string"},
            },
            "required": ["path", "cell_range"],
        },
    },
    {
        "name": "update_excel_cells",
        "description": 'Set individual cells from a JSON object of cell → value, e.g. {"B2": 42, "D10": "=SUM(D2:D9)"}. Values starting with = become live Excel formulas.',
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "updates": {"type": "string", "description": 'JSON object, e.g. {"B2": 5, "C2": "=B2*2"}'},
                "sheet_name": {"type": "string"},
            },
            "required": ["path", "updates"],
        },
    },
    {
        "name": "format_excel_range",
        "description": "Style a range: bold, number format (e.g. '#,##0.00', '0%', '£#,##0'), hex fill colour, column width.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "cell_range": {"type": "string", "description": "e.g. A1:D1"},
                "sheet_name": {"type": "string"},
                "bold": {"type": "boolean"},
                "number_format": {"type": "string"},
                "fill_color": {"type": "string", "description": "Hex, e.g. FFFF00"},
                "column_width": {"type": "number"},
            },
            "required": ["path", "cell_range"],
        },
    },
    {
        "name": "add_excel_chart",
        "description": "Add a native Excel chart (bar, column, line, pie, scatter). Include the header row in data_range so series are named.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "data_range": {"type": "string", "description": "e.g. B1:C10 (include the header row)"},
                "categories_range": {"type": "string", "description": "e.g. A2:A10 (labels, no header)"},
                "sheet_name": {"type": "string"},
                "chart_type": {"type": "string", "description": "bar (default), column, line, pie, scatter"},
                "title": {"type": "string"},
                "anchor": {"type": "string", "description": "Top-left cell for the chart, default H2"},
            },
            "required": ["path", "data_range"],
        },
    },
    {
        "name": "csv_to_excel",
        "description": "Import a CSV into a new .xlsx, converting numeric text into real numbers.",
        "parameters": {
            "type": "object",
            "properties": {
                "csv_path": {"type": "string"},
                "path": {"type": "string", "description": "Output .xlsx path"},
                "sheet_name": {"type": "string"},
                "delimiter": {"type": "string", "description": "Default ','"},
            },
            "required": ["csv_path", "path"],
        },
    },
    {
        "name": "excel_to_csv",
        "description": "Export one sheet of a workbook to a .csv file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "output_path": {"type": "string"},
                "sheet_name": {"type": "string"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "summarize_excel",
        "description": "Profile a sheet column by column: fill rate, and sum/mean/median/min/max for numeric columns or top values for text. Use this before answering questions about a spreadsheet instead of reading every row.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "sheet_name": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "get_excel_info",
        "description": "Summarise a workbook: each sheet's dimensions, formula count, charts, freeze panes and named ranges.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "excel_to_pdf",
        "description": "Convert a workbook to PDF using Microsoft Excel when available, otherwise LibreOffice.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "output_path": {"type": "string"},
            },
            "required": ["path"],
        },
    },
]


def register_tools(registry) -> None:
    for d in _DECLARATIONS:
        registry.register_tool(d["name"], globals()[d["name"]], d)
