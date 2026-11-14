"""Structure- and table-aware chunking.

Documents parsed to Markdown (LlamaParse output, imported web pages, .md
files) carry headings and tables. Splitting them by a fixed character count
cuts tables mid-row and detaches text from the heading that gives it meaning.
Here:

- text is grouped by section, and every chunk remembers its heading path
  ("Returns > Exceptions"); the path is prepended when the chunk is embedded,
  so a question phrased like the heading finds the right section;
- a Markdown table is one chunk, never split mid-row (a very long table is
  split by rows with the header row repeated);
- plain text without any structure falls back to the recursive splitter.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


@dataclass
class Chunk:
    text: str                      # what is stored and shown
    section: Optional[str] = None  # heading path, e.g. "Returns > Exceptions"
    kind: str = "text"             # "text" | "table"

    @property
    def embed_text(self) -> str:
        return f"{self.section}\n{self.text}" if self.section else self.text


@dataclass
class _Block:
    kind: str
    text: str
    section: Optional[str]


def split_text_recursive(text: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> List[str]:
    """Character-budget splitter on paragraph / line / sentence / word boundaries."""
    if len(text) <= chunk_size:
        return [text]
    delimiters = ["\n\n", "\n", ". ", " ", ""]

    def recursive_split(block: str, idx: int) -> List[str]:
        if len(block) <= chunk_size:
            return [block]
        if idx >= len(delimiters):
            return [block[i:i + chunk_size] for i in range(0, len(block), chunk_size)]
        sep = delimiters[idx]
        parts = block.split(sep) if sep else list(block)
        out: List[str] = []
        current = ""
        for j, part in enumerate(parts):
            piece = part + (sep if sep and j < len(parts) - 1 else "")
            if len(current) + len(piece) <= chunk_size:
                current += piece
            else:
                if current:
                    out.append(current)
                if len(piece) > chunk_size:
                    out.extend(recursive_split(piece, idx + 1))
                    current = ""
                else:
                    current = piece
        if current:
            out.append(current)
        return out

    raw = recursive_split(text, 0)
    if chunk_overlap <= 0:
        return raw
    out = [raw[0]]
    for prev, cur in zip(raw, raw[1:]):
        out.append(prev[-chunk_overlap:] + cur)
    return out


def _blocks(text: str) -> List[_Block]:
    """Walk the lines once, tracking the heading stack and table runs."""
    stack: List[tuple] = []  # (level, title)
    blocks: List[_Block] = []
    para: List[str] = []
    table: List[str] = []

    def section() -> Optional[str]:
        return " > ".join(t for _, t in stack) if stack else None

    def flush_para():
        nonlocal para
        body = "\n".join(para).strip()
        if body:
            blocks.append(_Block("text", body, section()))
        para = []

    def flush_table():
        nonlocal table
        if len(table) >= 2:
            blocks.append(_Block("table", "\n".join(table).strip(), section()))
        elif table:
            para.extend(table)
        table = []

    for line in text.splitlines():
        if TABLE_ROW_RE.match(line) or (table and TABLE_SEP_RE.match(line)):
            if not table:
                flush_para()
            table.append(line.rstrip())
            continue
        if table:
            flush_table()
        m = HEADING_RE.match(line)
        if m:
            flush_para()
            level, title = len(m.group(1)), m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            continue
        if not line.strip():
            flush_para()
        else:
            para.append(line.rstrip())
    flush_table()
    flush_para()
    return blocks


def _split_table(table: str, chunk_size: int) -> List[str]:
    rows = table.splitlines()
    header = rows[:2] if len(rows) > 1 and TABLE_SEP_RE.match(rows[1]) else rows[:1]
    body = rows[len(header):]
    out, cur = [], list(header)
    for row in body:
        if sum(len(r) + 1 for r in cur) + len(row) > chunk_size and len(cur) > len(header):
            out.append("\n".join(cur))
            cur = list(header)
        cur.append(row)
    if len(cur) > len(header) or not out:
        out.append("\n".join(cur))
    return out


def split_markdown(text: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> List[Chunk]:
    """Chunk a document, keeping tables whole and sections together."""
    blocks = _blocks(text)
    if not blocks:
        return []

    has_structure = any(b.kind == "table" or b.section for b in blocks)
    if not has_structure:
        return [Chunk(t) for t in split_text_recursive(text, chunk_size, chunk_overlap) if t.strip()]

    chunks: List[Chunk] = []
    buf: List[str] = []
    buf_section: Optional[str] = None

    def flush():
        nonlocal buf
        body = "\n\n".join(buf).strip()
        if body:
            pieces = split_text_recursive(body, chunk_size, chunk_overlap)
            chunks.extend(Chunk(p, buf_section) for p in pieces if p.strip())
        buf = []

    for b in blocks:
        if b.kind == "table":
            flush()
            # Tables get up to 3x the budget before being split by rows: a
            # table is only useful whole.
            for piece in _split_table(b.text, chunk_size * 3):
                chunks.append(Chunk(piece, b.section, "table"))
            buf_section = b.section
            continue
        if b.section != buf_section:
            flush()
            buf_section = b.section
        if sum(len(x) for x in buf) + len(b.text) > chunk_size and buf:
            flush()
            buf_section = b.section
        buf.append(b.text)
    flush()
    return chunks
