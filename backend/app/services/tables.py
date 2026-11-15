"""Turn rows of cells into Markdown tables.

Every extractor (PDF, Word, Excel, CSV, PowerPoint, HTML, ODF) funnels its
tables through here, so they all reach the chunker in the one shape it keeps
whole and splits only between rows, with the header repeated.
"""
from __future__ import annotations

import datetime as _dt
import re
from decimal import Decimal
from typing import Any, Iterable, List, Optional, Sequence

_WS = re.compile(r"\s+")


def cell_text(value: Any, number_format: Optional[str] = None) -> str:
    """One cell as display text: no newlines or pipes, tidy numbers and dates."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, _dt.datetime):
        return value.date().isoformat() if value.time() == _dt.time() else value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, (_dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, (int, float, Decimal)):
        if number_format and "%" in number_format:
            return f"{float(value) * 100:.6g}%"
        if isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
                return ""
            return str(int(value)) if value.is_integer() and abs(value) < 1e15 else f"{value:.10g}"
        return str(value)
    text = _WS.sub(" ", str(value)).strip()
    return text.replace("|", "\\|")


def _trim(rows: List[List[str]]) -> List[List[str]]:
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [i for i in range(width) if any(r[i] for r in rows)]
    return [[r[i] for i in keep] for r in rows]


def md_table(rows: Iterable[Sequence[Any]], header: bool = True) -> str:
    """Rows of raw values -> a Markdown table, or "" if there is nothing in it.

    Empty rows and columns are dropped. Without a usable header row the
    columns are named "Column 1", "Column 2", ...
    """
    grid = _trim([[cell_text(c) for c in r] for r in rows])
    if not grid:
        return ""
    width = len(grid[0])
    if header and len(grid) > 1:
        head, body = grid[0], grid[1:]
        head = [h or f"Column {i + 1}" for i, h in enumerate(head)]
    else:
        head, body = [f"Column {i + 1}" for i in range(width)], grid
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * width) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


def split_blocks(rows: Iterable[Sequence[Any]], gap: int = 2) -> List[List[List[Any]]]:
    """Split a sheet into separate tables wherever `gap` or more blank rows
    sit between them (a sheet often holds a summary and a detail table)."""
    blocks: List[List[List[Any]]] = []
    cur: List[List[Any]] = []
    blank = 0
    for r in rows:
        r = list(r)
        if not any(c not in (None, "") and str(c).strip() for c in r):
            blank += 1
            if blank >= gap and cur:
                blocks.append(cur)
                cur = []
            continue
        blank = 0
        cur.append(r)
    if cur:
        blocks.append(cur)
    return blocks
