"""Exact answers from tables.

Questions such as "total sales in March", "which region grew most" or
"average order value" need arithmetic over many rows. Retrieval hands the
model a few passages, and models add up long columns badly, so instead:

1. At indexing time every table in a document (a spreadsheet sheet, a CSV,
   a table in a PDF/Word/HTML file) is stored as rows (``DocumentTable``).
2. At question time, if the question asks for a calculation, the model is
   shown the relevant tables' columns and a few sample rows and writes one
   SQLite SELECT.
3. The SELECT runs on an in-memory copy of just those tables, under an
   authorizer that allows reading and nothing else, with a time limit.
4. The exact result goes to the answering model as the first source, and to
   the UI with the query, so the reader can check how the number was made.
"""
from __future__ import annotations

import asyncio
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.config import settings
from app.core.logging import logger

# ---------------------------------------------------------------------------
# 1. Pulling tables out of parsed pages
# ---------------------------------------------------------------------------
_SPLIT = re.compile(r"(?<!\\)\|")


def _cells(line: str) -> List[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.strip().replace("\\|", "|") for c in _SPLIT.split(line)]


@dataclass
class ExtractedTable:
    name: str
    page_number: Optional[int]
    columns: List[str]
    rows: List[List[str]] = field(default_factory=list)
    section: Optional[str] = None
    last_page: Optional[int] = None   # set when the table runs onto later pages


def _unique_columns(cols: Sequence[str]) -> List[str]:
    out, seen = [], {}
    for i, c in enumerate(cols):
        c = (c or "").strip() or f"Column {i + 1}"
        n = seen.get(c.lower(), 0)
        seen[c.lower()] = n + 1
        out.append(c if n == 0 else f"{c} ({n + 1})")
    return out


def extract_tables(pages: List[Dict[str, Any]], min_rows: int = 2) -> List[ExtractedTable]:
    """Every Markdown table in the parsed pages, as header + rows.

    A table that continues onto the next page with the same header and
    section (PDF tables split by a page break) is joined back into one.
    """
    from app.services.chunking import TABLE_SEP_RE, _blocks

    found: List[ExtractedTable] = []
    for page in pages:
        page_no = page.get("page_number")
        for block in _blocks(page.get("content") or ""):
            if block.kind != "table":
                continue
            lines = [ln for ln in block.text.splitlines() if ln.strip()]
            if len(lines) < 2:
                continue
            body_start = 2 if TABLE_SEP_RE.match(lines[1]) else 1
            columns = _unique_columns(_cells(lines[0]))
            rows = []
            for ln in lines[body_start:]:
                cells = _cells(ln)
                cells = (cells + [""] * len(columns))[:len(columns)]
                if any(cells):
                    rows.append(cells)
            if not rows:
                continue
            prev = found[-1] if found else None
            prev_end = (prev.last_page or prev.page_number) if prev else None
            if (prev and prev.columns == columns and prev.section == block.section
                    and page_no is not None and prev_end is not None and page_no == prev_end + 1):
                prev.rows.extend(rows)
                prev.last_page = page_no
                continue
            found.append(ExtractedTable(name="", page_number=page_no, columns=columns, rows=rows, section=block.section))

    out = [t for t in found if len(t.rows) >= min_rows and len(t.columns) >= 2]
    counts: Dict[str, int] = {}
    for i, t in enumerate(out, start=1):
        base = (t.section.split(" > ")[-1] if t.section else "") or f"Table {i}"
        if not t.section and t.page_number:
            base += f" (page {t.page_number})"
        counts[base] = counts.get(base, 0) + 1
        t.name = base if counts[base] == 1 else f"{base} ({counts[base]})"
        t.name = t.name[:250]
    return out


# ---------------------------------------------------------------------------
# 2. Typing columns: "1,200", "$5", "4.2%", "(30)" are numbers
# ---------------------------------------------------------------------------
_NUM = re.compile(r"^\(?[-+]?[$€£₹¥]?\s*[-+]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?\s*(%|[kKmMbB]n?)?\)?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}(:\d{2})?)?$")
_SCALE = {"k": 1e3, "m": 1e6, "b": 1e9, "bn": 1e9}


def to_number(v: str) -> Optional[float]:
    s = (v or "").strip()
    if not s or not _NUM.match(s):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "").replace(" ", "")
    s = re.sub(r"[$€£₹¥]", "", s)
    scale = 1.0
    m = re.search(r"(bn|[kKmMbB])$", s)
    if m:
        scale = _SCALE[m.group(1).lower()]
        s = s[: m.start()]
    s = s.rstrip("%")
    try:
        n = float(s) * scale
    except ValueError:
        return None
    return -n if neg else n


def column_types(columns: List[str], rows: List[List[str]]) -> List[str]:
    """'REAL', 'DATE' or 'TEXT' per column: a column is numeric when nearly
    every non-empty value parses as a number."""
    types = []
    for i in range(len(columns)):
        vals = [r[i] for r in rows if i < len(r) and (r[i] or "").strip()]
        if not vals:
            types.append("TEXT")
            continue
        nums = sum(1 for v in vals if to_number(v) is not None)
        dates = sum(1 for v in vals if _DATE.match(v.strip()))
        if nums / len(vals) >= 0.9:
            types.append("REAL")
        elif dates / len(vals) >= 0.9:
            types.append("DATE")
        else:
            types.append("TEXT")
    return types


# ---------------------------------------------------------------------------
# 3. A sandboxed SQLite run
# ---------------------------------------------------------------------------
_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
if hasattr(sqlite3, "SQLITE_RECURSIVE"):
    _ALLOWED_ACTIONS.add(sqlite3.SQLITE_RECURSIVE)
_BLOCKED_FUNCTIONS = {"load_extension", "readfile", "writefile", "fts3_tokenizer", "edit"}


class QueryError(Exception):
    pass


@dataclass
class LoadedTable:
    alias: str            # t1, t2, ... (what the SQL uses)
    table_id: str
    doc_id: str
    filename: str
    name: str
    page_number: Optional[int]
    columns: List[str]
    types: List[str]
    rows: List[List[str]]


def _qi(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _value(v: str, t: str):
    if t == "REAL":
        n = to_number(v)
        if n is None:
            return None
        return int(n) if n.is_integer() and abs(n) < 2 ** 53 else n
    return (v or "").strip() or None


def build_database(tables: List[LoadedTable]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    # SQLite's legacy quirk reads a double-quoted name that matches no column
    # as a string, so SUM("Revnue") quietly returns 0. Turn that off: a typo
    # must be an error the model can fix, never a wrong number.
    if hasattr(conn, "setconfig"):
        conn.setconfig(sqlite3.SQLITE_DBCONFIG_DQS_DML, False)
        conn.setconfig(sqlite3.SQLITE_DBCONFIG_DQS_DDL, False)
    for t in tables:
        cols = ", ".join(f"{_qi(c)} {('REAL' if ty == 'REAL' else 'TEXT')}" for c, ty in zip(t.columns, t.types))
        conn.execute(f"CREATE TABLE {t.alias} ({cols})")
        marks = ", ".join("?" for _ in t.columns)
        conn.executemany(f"INSERT INTO {t.alias} VALUES ({marks})",
                         ([_value(v, ty) for v, ty in zip(r, t.types)] for r in t.rows))
    conn.commit()
    return conn


def check_identifiers(conn: sqlite3.Connection, sql: str) -> None:
    """Every double-quoted name must be a real column or an AS alias."""
    known = {r[1].lower() for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
             for r in conn.execute(f"PRAGMA table_info({t[0]})")}
    aliases = {a.lower() for a in re.findall(r'(?i)\bAS\s+"([^"]+)"', sql)}
    for name in re.findall(r'"((?:[^"]|"")+)"', re.sub(r"'(?:[^']|'')*'", "", sql)):
        if name.replace('""', '"').lower() not in known | aliases:
            raise QueryError(f"no such column: {name}")


def run_select(conn: sqlite3.Connection, sql: str, timeout_s: float = 3.0, max_rows: int = 200) -> Tuple[List[str], List[tuple], bool]:
    """Run one read-only SELECT. Anything else is refused by the authorizer;
    a query running past `timeout_s` is interrupted."""
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise QueryError("empty query")
    if ";" in re.sub(r"'(?:[^']|'')*'", "", sql):
        raise QueryError("only one statement is allowed")
    if not re.match(r"(?is)^\s*(select|with)\b", sql):
        raise QueryError("only SELECT queries are allowed")

    def authorizer(action, arg1, arg2, dbname, source):
        if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in _BLOCKED_FUNCTIONS:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_READ and (arg1 or "").lower().startswith("sqlite_"):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY

    if not hasattr(conn, "setconfig"):   # Python < 3.12 cannot switch the quirk off
        check_identifiers(conn, sql)

    deadline = time.monotonic() + timeout_s
    conn.set_authorizer(authorizer)
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        cur = conn.execute(sql)
        cols = [d[0] for d in (cur.description or [])]
        rows = cur.fetchmany(max_rows + 1)
    except sqlite3.DatabaseError as e:
        msg = str(e)
        if "interrupted" in msg:
            msg = "the query took too long"
        elif "not authorized" in msg:
            msg = "the query tried to do something other than read the tables"
        raise QueryError(msg)
    finally:
        conn.set_authorizer(None)
        conn.set_progress_handler(None, 0)
    return cols, rows[:max_rows], len(rows) > max_rows


# ---------------------------------------------------------------------------
# 4. Deciding when to calculate, and which tables to use
# ---------------------------------------------------------------------------
_ANALYTIC = re.compile(
    r"\b(total|sum|add up|average|avg|mean|median|count|how many|how much|number of|max(imum)?|min(imum)?|"
    r"highest|lowest|largest|smallest|biggest|top \d+|bottom \d+|top|most|least|rank|percent(age)?|share|ratio|"
    r"growth|grew|increase|decrease|difference|between|per\b|each|by (month|year|quarter|week|day|region|country|"
    r"category|product|customer|team|department)|group|breakdown|trend|compare|more than|less than|greater|"
    r"above|below|over|under|exceed|list (all|every)|which .* (has|have|had))\b", re.I)
_STOP = set("the a an and or of to in on for with by is are was were be what which who how many much does do did "
            "show me give list all from that this these those it its as at".split())


def is_analytic(question: str) -> bool:
    return bool(_ANALYTIC.search(question or ""))


def _terms(text: str) -> set:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    out = set()
    for w in words:
        if w in _STOP or len(w) < 3:
            continue
        out.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return out


def score_table(question: str, filename: str, name: str, columns: List[str], sample: List[List[str]]) -> float:
    q = _terms(question)
    if not q:
        return 0.0
    head = _terms(" ".join(columns) + " " + name + " " + filename)
    body = _terms(" ".join(" ".join(r) for r in sample))
    return len(q & head) * 2 + len(q & body) * 0.5


# ---------------------------------------------------------------------------
# 5. The question step
# ---------------------------------------------------------------------------
_PROMPT = """You turn questions into one SQLite SELECT over the tables below.

Rules:
- Use only the tables and columns listed. Quote every column name with double quotes, exactly as written.
- REAL columns are already numbers (currency signs, commas and % removed; "4.2%" is stored as 4.2).
- DATE columns are text 'YYYY-MM-DD'; use strftime('%Y-%m', col) and similar to group by month or year.
- Text matching should be forgiving: use LOWER(col) LIKE '%word%' unless an exact value is clearly meant.
- Give the result columns clear names with AS. Round averages and percentages with ROUND(x, 2).
- For lists, ORDER BY something meaningful and LIMIT 50.
- One statement, SELECT or WITH only.
- If the tables cannot answer the question, return {"sql": null, "reason": "..."}.

Reply with JSON only: {"sql": "<query>", "table": "<t1, t2 ...: the main table used>"}"""


def _schema_text(tables: List[LoadedTable]) -> str:
    parts = []
    for t in tables:
        cols = ", ".join(f'"{c}" {ty}' for c, ty in zip(t.columns, t.types))
        sample = "\n".join("  " + " | ".join(r) for r in t.rows[:3])
        where = f'"{t.name}" in {t.filename}' + (f" (page {t.page_number})" if t.page_number else "")
        parts.append(f"{t.alias}: {where}, {len(t.rows)} rows\n  columns: {cols}\n  first rows:\n{sample}")
    return "\n\n".join(parts)


@dataclass
class Calculation:
    sql: str
    columns: List[str]
    rows: List[List[Any]]
    truncated: bool
    table: LoadedTable
    tables: List[LoadedTable]
    usage: Any = None

    def result_markdown(self, limit: int = 50) -> str:
        from app.services.tables import md_table
        if len(self.rows) == 1 and len(self.columns) == 1:
            from app.services.tables import cell_text
            return f"{self.columns[0]} = {cell_text(self.rows[0][0])}"
        body = md_table([self.columns] + [list(r) for r in self.rows[:limit]])
        if len(self.rows) > limit or self.truncated:
            body += f"\n(first {limit} result rows shown)"
        return body or "(no rows matched)"

    def as_chunk(self) -> Dict[str, Any]:
        used = ", ".join(f'"{t.name}" ({len(t.rows)} rows)' for t in self.tables)
        content = (f"Exact calculation over the full table data of {self.table.filename}: {used}.\n"
                   f"Query: {self.sql}\nResult:\n{self.result_markdown()}")
        return {
            "content": content,
            "filename": self.table.filename,
            "source": self.table.filename,
            "page_number": self.table.page_number or 1,
            "doc_id": self.table.doc_id,
            "chunk_id": None,
            "similarity_score": 1.0,
            "kind": "calculation",
            "section": self.table.name,
            "sql": self.sql,
        }

    def as_event(self) -> Dict[str, Any]:
        from app.services.tables import cell_text
        return {
            "event": "calculation",
            "sql": self.sql,
            "columns": self.columns,
            "rows": [[cell_text(v) for v in r] for r in self.rows[:50]],
            "truncated": self.truncated or len(self.rows) > 50,
            "tables": [{"name": t.name, "filename": t.filename, "doc_id": t.doc_id, "page": t.page_number,
                        "rows": len(t.rows)} for t in self.tables],
        }


async def _load_candidates(db, kb_id, document_ids: Optional[List[str]], question: str, limit: int) -> List[LoadedTable]:
    from sqlalchemy import select
    from app.models.knowledge import Document, DocumentTable

    q = (select(DocumentTable.id, DocumentTable.doc_id, DocumentTable.name, DocumentTable.page_number,
                DocumentTable.columns, DocumentTable.n_rows, Document.filename)
         .join(Document, Document.id == DocumentTable.doc_id)
         .where(DocumentTable.kb_id == kb_id, Document.status == "indexed"))
    if document_ids:
        ids = []
        for d in document_ids:
            try:
                ids.append(uuid.UUID(str(d)))
            except ValueError:
                pass
        if ids:
            q = q.where(DocumentTable.doc_id.in_(ids))
    meta = (await db.execute(q)).all()
    if not meta:
        return []
    scored = sorted(meta, key=lambda m: (score_table(question, m.filename, m.name, m.columns, []), m.n_rows), reverse=True)
    if len(meta) > limit and score_table(question, scored[0].filename, scored[0].name, scored[0].columns, []) == 0:
        return []   # many tables and none looks related: do not guess
    chosen = scored[:limit]
    rows_by_id = dict((await db.execute(
        select(DocumentTable.id, DocumentTable.rows).where(DocumentTable.id.in_([m.id for m in chosen]))
    )).all())
    out = []
    for i, m in enumerate(chosen, start=1):
        rows = rows_by_id.get(m.id) or []
        out.append(LoadedTable(alias=f"t{i}", table_id=str(m.id), doc_id=str(m.doc_id), filename=m.filename,
                               name=m.name, page_number=m.page_number, columns=list(m.columns),
                               types=column_types(list(m.columns), rows), rows=rows))
    return out


async def calculate(kb_id, question: str, document_ids: Optional[List[str]] = None) -> Optional[Calculation]:
    """Answer `question` by calculation over the KB's tables, or return None
    when it is not a calculation question, there is no suitable table, or no
    model is available. Never raises."""
    from app.services import llm

    if not settings.TABLE_QA_ENABLED or not is_analytic(question) or not llm.llm_available():
        return None
    try:
        from app.core.database import SessionLocal
        async with SessionLocal() as db:
            tables = await _load_candidates(db, kb_id, document_ids, question, settings.TABLE_QA_MAX_TABLES)
        if not tables:
            return None
        conn = await asyncio.to_thread(build_database, tables)
        try:
            usage_total = llm.Usage()
            user = f"Tables:\n\n{_schema_text(tables)}\n\nQuestion: {question}"
            last_error = None
            for attempt in range(2):
                prompt = user if last_error is None else (
                    f"{user}\n\nYour previous query:\n{last_error[0]}\nfailed with: {last_error[1]}\nFix it.")
                data, usage = await llm.complete_json(_PROMPT, prompt, temperature=0.0, max_tokens=600)
                usage_total.add(usage)
                sql = (data or {}).get("sql")
                if not sql:
                    logger.info(f"Table QA: no query for this question ({(data or {}).get('reason')}).")
                    return None
                try:
                    cols, rows, truncated = await asyncio.to_thread(run_select, conn, sql)
                except QueryError as e:
                    last_error = (sql, str(e))
                    logger.info(f"Table QA query failed (attempt {attempt + 1}): {e}")
                    continue
                main_alias = re.findall(r"t\d+", str((data or {}).get("table") or "")) or re.findall(r"\bt\d+\b", sql)
                main = next((t for t in tables if t.alias == (main_alias[0] if main_alias else "")), tables[0])
                used = [t for t in tables if re.search(rf"\b{t.alias}\b", sql)] or [main]
                return Calculation(sql=sql, columns=cols, rows=[list(r) for r in rows], truncated=truncated,
                                   table=main, tables=used, usage=usage_total)
            return None
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Table QA skipped: {e}")
        return None


# ---------------------------------------------------------------------------
# 6. Backfill for documents indexed before tables were stored
# ---------------------------------------------------------------------------
def pages_from_table_chunks(chunks: List[Tuple[str, Optional[int], Optional[str]]]) -> List[Dict[str, Any]]:
    """Rebuild page text from stored table chunks (content, page, section).

    A long table was split into chunks that each repeat its header; joined
    back here so it comes out as one table again.
    """
    pages: Dict[Optional[int], List[str]] = {}
    last_header: Dict[Optional[int], Tuple[Optional[str], str]] = {}
    for content, page, section in chunks:
        lines = (content or "").strip().splitlines()
        if len(lines) < 2:
            continue
        header = "\n".join(lines[:2])
        parts = pages.setdefault(page, [])
        if last_header.get(page) == (section, header) and parts:
            parts[-1] += "\n" + "\n".join(lines[2:])
        else:
            prefix = f"## {section.split(' > ')[-1]}\n\n" if section else ""
            parts.append(prefix + "\n".join(lines))
        last_header[page] = (section, header)
    return [{"page_number": p, "content": "\n\n".join(parts)} for p, parts in sorted(pages.items(), key=lambda x: x[0] or 0)]


async def backfill_tables(limit_docs: int = 500) -> int:
    """Store tables for indexed documents that predate table storage, from
    their table chunks (no re-parsing). Returns how many documents were done."""
    from sqlalchemy import select
    from app.core.database import SessionLocal
    from app.models.knowledge import Document, DocumentChunk, DocumentTable
    from app.services.indexer import DocumentIndexer

    done = 0
    async with SessionLocal() as db:
        docs = (await db.execute(select(Document).where(Document.status == "indexed"))).scalars().all()
        todo = [d for d in docs if "data_tables" not in (d.meta_info or {})][:limit_docs]
        for doc in todo:
            chunks = (await db.execute(
                select(DocumentChunk.content, DocumentChunk.page_number, DocumentChunk.section)
                .where(DocumentChunk.doc_id == doc.id, DocumentChunk.kind == "table")
                .order_by(DocumentChunk.chunk_index)
            )).all()
            tables = DocumentIndexer._table_rows(doc.id, doc.kb_id, pages_from_table_chunks(chunks), doc.filename) if chunks else []
            existing = (await db.execute(select(DocumentTable.id).where(DocumentTable.doc_id == doc.id).limit(1))).first()
            if not existing:
                db.add_all(tables)
            doc.meta_info = {**(doc.meta_info or {}), "data_tables": len(tables)}
            await db.commit()
            done += 1
    if done:
        logger.info(f"Stored tables for {done} previously indexed document(s).")
    return done
