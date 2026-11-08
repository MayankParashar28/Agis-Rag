import pytest

from app.services.url_import import (
    UrlImportError, _assert_public_host, _check_scheme, _ext_for, html_to_text, safe_filename,
)


def test_html_to_text_skips_chrome():
    html = """<html><head><title>My Page</title><style>.x{}</style></head>
    <body><nav>Menu</nav><h1>Hello</h1><p>First para.</p><script>bad()</script><p>Second.</p></body></html>"""
    title, text = html_to_text(html)
    assert title == "My Page"
    assert "# Hello" in text and "First para." in text and "Second." in text
    assert "Menu" not in text and "bad()" not in text


def test_ext_detection():
    assert _ext_for("application/pdf", "https://x/y") == ".pdf"
    assert _ext_for("text/html; charset=utf-8", "https://x/") == ".html"
    assert _ext_for("text/plain", "https://x/a") == ".txt"
    assert _ext_for("image/png", "https://x/a.png") is None


def test_rejects_non_http():
    with pytest.raises(UrlImportError):
        _check_scheme("file:///etc/passwd")


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "10.0.0.5", "169.254.169.254"])
async def test_blocks_private_hosts(host):
    with pytest.raises(UrlImportError):
        await _assert_public_host(host)


def test_safe_filename():
    assert safe_filename("A/B: report?", "https://x", ".txt") == "A B report.txt"
