import sys
import types

import pytest

sys.modules.setdefault("app.services.models", types.SimpleNamespace(get_embedding_model=lambda: None, get_reranker=lambda: None))

from app.services import table_qa as T  # noqa: E402

SALES = """## Sheet: Sales

| Month | Region | Revenue | Margin |
|---|---|---|---|
| 2026-01-01 | North | $1,200 | 12.5% |
| 2026-01-01 | South | $800 | 9% |
| 2026-02-01 | North | $1,500 | 14% |
| 2026-02-01 | South | (100) | -2% |
"""


def _loaded(pages):
    out = []
    for i, t in enumerate(T.extract_tables(pages), start=1):
        out.append(T.LoadedTable(f"t{i}", f"id{i}", "doc1", "sales.xlsx", t.name, t.page_number,
                                 t.columns, T.column_types(t.columns, t.rows), t.rows))
    return out


def test_extract_and_type_tables():
    tables = T.extract_tables([{"page_number": 1, "content": SALES}])
    assert len(tables) == 1
    t = tables[0]
    assert t.name == "Sheet: Sales" and t.columns == ["Month", "Region", "Revenue", "Margin"] and len(t.rows) == 4
    assert T.column_types(t.columns, t.rows) == ["DATE", "TEXT", "REAL", "REAL"]


def test_numbers_parse_like_a_spreadsheet_shows_them():
    assert [T.to_number(x) for x in ["1,200", "$5", "4.2%", "(30)", "2.5k", "€3 m", "abc", "12-3", ""]] == \
        [1200, 5, 4.2, -30, 2500, 3_000_000, None, None, None]


def test_table_split_across_pages_is_joined():
    head = "| Item | Qty |\n|---|---|\n"
    pages = [{"page_number": 1, "content": "Intro text.\n\n" + head + "| a | 1 |\n| b | 2 |"},
             {"page_number": 2, "content": head + "| c | 3 |\n| d | 4 |"},
             {"page_number": 4, "content": head + "| e | 5 |\n| f | 6 |"}]   # not adjacent: a new table
    tables = T.extract_tables(pages)
    assert [len(t.rows) for t in tables] == [4, 2]


def test_duplicate_and_blank_headers_get_unique_names():
    pages = [{"page_number": 1, "content": "| A | A |  |\n|---|---|---|\n| 1 | 2 | 3 |\n| 4 | 5 | 6 |"}]
    assert T.extract_tables(pages)[0].columns == ["A", "A (2)", "Column 3"]


def test_sql_runs_exactly_over_all_rows():
    conn = T.build_database(_loaded([{"page_number": 1, "content": SALES}]))
    cols, rows, _ = T.run_select(conn, 'SELECT "Region", SUM("Revenue") AS total FROM t1 GROUP BY "Region" ORDER BY total DESC')
    assert cols == ["Region", "total"] and rows == [("North", 2700), ("South", 700)]
    _, rows, _ = T.run_select(conn, """SELECT strftime('%Y-%m', "Month") m, ROUND(AVG("Margin"), 2) FROM t1 GROUP BY m""")
    assert rows == [("2026-01", 10.75), ("2026-02", 6.0)]


@pytest.mark.parametrize("sql", [
    "DELETE FROM t1",
    "SELECT 1; DROP TABLE t1",
    "ATTACH DATABASE '/tmp/x.db' AS x",
    "PRAGMA table_info(t1)",
    "SELECT load_extension('evil')",
    "SELECT * FROM sqlite_master",
    "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT count(*) FROM c",
])
def test_sandbox_refuses_anything_but_reading(sql):
    conn = T.build_database(_loaded([{"page_number": 1, "content": SALES}]))
    with pytest.raises(T.QueryError):
        T.run_select(conn, sql, timeout_s=0.5)


def test_only_calculation_questions_trigger():
    assert T.is_analytic("What was the total revenue in February?")
    assert T.is_analytic("Which region has the highest margin?")
    assert T.is_analytic("How many orders were placed by each customer?")
    assert not T.is_analytic("What is our refund policy?")


def test_backfill_rebuilds_split_tables_from_chunks():
    chunks = [("| Item | Qty |\n|---|---|\n| a | 1 |\n| b | 2 |", 1, "Sheet: Stock"),
              ("| Item | Qty |\n|---|---|\n| c | 3 |", 1, "Sheet: Stock"),
              ("| Name | Age |\n|---|---|\n| x | 30 |\n| y | 40 |", 2, "Sheet: People")]
    tables = T.extract_tables(T.pages_from_table_chunks(chunks))
    assert [(t.name, len(t.rows)) for t in tables] == [("Sheet: Stock", 3), ("Sheet: People", 2)]


async def test_calculate_end_to_end_with_retry(monkeypatch):
    from app.services import llm

    tables = _loaded([{"page_number": 1, "content": SALES}])

    async def fake_candidates(db, kb_id, doc_ids, question, limit):
        return tables

    class FakeSession:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return False

    replies = iter([
        {"sql": 'SELECT SUM("Revnue") FROM t1'},                       # typo: fails, model gets the error
        {"sql": 'SELECT SUM("Revenue") AS total_revenue FROM t1 WHERE "Month" LIKE \'2026-02%\'', "table": "t1"},
    ])
    prompts = []

    async def fake_json(system, user, **kw):
        prompts.append(user)
        return next(replies), llm.Usage("Gemini", "gemini-flash", 100, 20)

    monkeypatch.setattr(T, "_load_candidates", fake_candidates)
    monkeypatch.setattr(llm, "complete_json", fake_json)
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    import app.core.database as database
    monkeypatch.setattr(database, "SessionLocal", FakeSession)

    calc = await T.calculate("kb", "What was the total revenue in February?")
    assert calc is not None and calc.rows == [[1400]]
    assert "no such column" in prompts[1]                                # the error was fed back
    chunk = calc.as_chunk()
    assert chunk["kind"] == "calculation" and "total_revenue = 1400" in chunk["content"]
    assert calc.as_event()["tables"][0]["rows"] == 4
    assert calc.usage.prompt_tokens == 200


async def test_calculate_skips_non_calculation_questions(monkeypatch):
    called = []
    monkeypatch.setattr(T, "_load_candidates", lambda *a: called.append(1))
    assert await T.calculate("kb", "Summarise the leave policy") is None
    assert not called


def test_misspelled_column_is_an_error_not_a_zero():
    conn = T.build_database(_loaded([{"page_number": 1, "content": SALES}]))
    with pytest.raises(T.QueryError, match="no such column"):
        T.run_select(conn, 'SELECT SUM("Revnue") FROM t1')
    with pytest.raises(T.QueryError, match="no such column"):     # the Python < 3.12 path
        T.check_identifiers(conn, 'SELECT SUM("Revnue") FROM t1')
    T.check_identifiers(conn, 'SELECT SUM("Revenue") AS "Total" FROM t1 ORDER BY "Total"')
