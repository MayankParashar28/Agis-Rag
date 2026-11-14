from app.services.chunking import split_markdown, split_text_recursive

DOC = """# Returns policy

Customers may return items within 30 days.

## Exceptions

Sale items cannot be returned. Gift cards are final.

| Item | Window | Refund |
|------|--------|--------|
| Shoes | 30 days | Full |
| Hats | 14 days | Store credit |
| Socks | 7 days | None |

## Contact

Email support for help.
"""


def test_sections_carry_heading_path():
    chunks = split_markdown(DOC, 1000, 0)
    sections = {c.section for c in chunks}
    assert "Returns policy" in sections
    assert "Returns policy > Exceptions" in sections
    assert "Returns policy > Contact" in sections


def test_table_is_one_chunk_and_whole():
    chunks = split_markdown(DOC, 1000, 0)
    tables = [c for c in chunks if c.kind == "table"]
    assert len(tables) == 1
    assert "| Shoes |" in tables[0].text and "| Socks |" in tables[0].text
    assert tables[0].section == "Returns policy > Exceptions"
    # The table is not merged into surrounding prose.
    assert "Sale items" not in tables[0].text


def test_embed_text_prefixes_section():
    chunk = next(c for c in split_markdown(DOC, 1000, 0) if c.section == "Returns policy > Contact")
    assert chunk.embed_text.startswith("Returns policy > Contact\n")
    assert chunk.text == "Email support for help."


def test_long_table_split_by_rows_repeats_header():
    rows = "\n".join(f"| r{i} | {'x' * 40} |" for i in range(200))
    table = "| a | b |\n|---|---|\n" + rows
    chunks = split_markdown(table, 500, 0)
    assert len(chunks) > 1
    assert all(c.text.startswith("| a | b |\n|---|---|") for c in chunks)
    assert sum(c.text.count("| r") for c in chunks) == 200


def test_plain_text_falls_back_to_recursive_splitter():
    text = ("word " * 3000).strip()
    chunks = split_markdown(text, 1000, 100)
    assert all(c.section is None for c in chunks)
    assert "".join(c.text for c in chunks).count("word") >= 3000
    assert all(len(c.text) <= 1100 for c in chunks)


def test_recursive_split_keeps_all_text():
    text = "Para one. Sentence two.\n\nPara two is here.\n\n" * 200
    parts = split_text_recursive(text, 300, 0)
    assert "".join(parts) == text
