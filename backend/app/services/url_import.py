"""Fetch a web page or file by URL so it can be indexed like an upload.

Guards against SSRF: only http(s), only public addresses (every redirect hop
is re-checked), a capped download size and a short timeout. HTML is reduced
to readable text with the standard library, so no extra dependency is needed.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx

MAX_REDIRECTS = 5
TIMEOUT_SECONDS = 20
# Many sites answer 403 to unknown bots, so look like a regular browser.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 AegisRAG-Importer/1.0"
)


class UrlImportError(ValueError):
    """A user-facing reason the URL could not be imported."""


@dataclass
class FetchedDocument:
    content: bytes
    ext: str             # ".pdf", ".txt", ".csv" or ".docx"
    title: str
    final_url: str


async def _assert_public_host(host: str) -> None:
    if not host:
        raise UrlImportError("The URL has no host name.")
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    except socket.gaierror:
        raise UrlImportError(f"Could not resolve '{host}'.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise UrlImportError("That address points to a private network and cannot be imported.")


def _check_scheme(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UrlImportError("Only http:// and https:// links can be imported.")
    return parsed.hostname or ""


class _TextExtractor(HTMLParser):
    """Readable text from HTML. Headings become Markdown headings and
    <table>s become Markdown tables, so the chunker keeps them whole."""
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside", "iframe", "template"}
    BLOCK = {"p", "div", "section", "article", "br", "li", "tr", "h1", "h2", "h3",
             "h4", "h5", "h6", "pre", "blockquote", "table", "ul", "ol", "dd", "dt", "hr"}
    HEADINGS = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### ", "h5": "##### ", "h6": "###### "}

    def __init__(self, skip_chrome: bool = True):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip_depth = 0
        self._in_title = False
        self._skip = self.SKIP if skip_chrome else {"script", "style", "noscript", "svg", "template"}
        # One entry per open <table>: {"rows": [...], "row": [...] | None, "cell": [...] | None}
        self._tables: list[dict] = []

    def _sink(self) -> list:
        """Where text goes right now: the open table cell, or the page."""
        if self._tables:
            t = self._tables[-1]
            if t["cell"] is not None:
                return t["cell"]
            return []  # text between cells (whitespace) is dropped
        return self.parts

    def handle_starttag(self, tag, attrs):
        if tag in self._skip:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
        elif tag == "table":
            self._tables.append({"rows": [], "row": None, "cell": None})
        elif self._tables and tag == "tr":
            t = self._tables[-1]
            self._close_row(t)
            t["row"] = []
        elif self._tables and tag in ("td", "th"):
            t = self._tables[-1]
            if t["row"] is None:
                t["row"] = []
            self._close_cell(t)
            t["cell"] = []
            span = dict(attrs).get("colspan")
            t["span"] = int(span) if span and str(span).isdigit() and 1 < int(span) <= 50 else 1
        elif self._tables:
            if tag in ("br", "p", "li", "div"):
                self._sink().append(" ")
        elif tag in self.BLOCK:
            self.parts.append("\n")
            if tag in self.HEADINGS:
                self.parts.append(self.HEADINGS[tag])

    def _close_cell(self, t):
        if t["cell"] is not None and t["row"] is not None:
            text = re.sub(r"\s+", " ", "".join(t["cell"])).strip()
            t["row"].extend([text] * t.get("span", 1))
        t["cell"] = None

    def _close_row(self, t):
        self._close_cell(t)
        if t["row"]:
            t["rows"].append(t["row"])
        t["row"] = None

    def handle_endtag(self, tag):
        if tag in self._skip:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
        elif tag == "table" and self._tables:
            from app.services.tables import md_table
            t = self._tables.pop()
            self._close_row(t)
            rendered = md_table(t["rows"])
            if self._tables:          # nested table: flatten into the outer cell
                self._sink().append(" ; ".join(" ".join(r) for r in t["rows"]))
            elif rendered:
                self.parts.append("\n\n" + rendered + "\n\n")
        elif self._tables and tag in ("td", "th"):
            self._close_cell(self._tables[-1])
        elif self._tables and tag == "tr":
            self._close_row(self._tables[-1])
        elif not self._tables and tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip_depth:
            self._sink().append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r"\n\s*\n\s*\n+", "\n\n", raw)
        return "\n".join(line.strip() for line in raw.splitlines()).strip()


def html_to_text(html: str, skip_chrome: bool = True) -> Tuple[str, str]:
    """Return (title, readable text) for an HTML document. `skip_chrome`
    drops nav/header/footer, which suits web pages but not saved documents."""
    parser = _TextExtractor(skip_chrome)
    parser.feed(html)
    parser.close()
    while parser._tables:  # unclosed <table> in sloppy HTML
        parser.handle_endtag("table")
    return parser.title.strip(), parser.text()


_CT_EXT = {
    "application/pdf": ".pdf",
    "text/csv": ".csv", "application/csv": ".csv",
    "text/tab-separated-values": ".tsv",
    "application/json": ".json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "application/vnd.oasis.opendocument.presentation": ".odp",
    "application/epub+zip": ".epub",
    "application/rtf": ".rtf", "text/rtf": ".rtf",
    "text/markdown": ".md",
}


def _ext_for(content_type: str, url: str) -> Optional[str]:
    from app.services.extractors import IMAGE_EXTS, SUPPORTED_EXTS
    ct = content_type.split(";")[0].strip().lower()
    path_ext = "." + urlparse(url).path.rsplit(".", 1)[-1].lower() if "." in urlparse(url).path.rsplit("/", 1)[-1] else ""
    if ct in _CT_EXT:
        return _CT_EXT[ct]
    if ct in ("text/html", "application/xhtml+xml"):
        return ".html"
    # Servers often send files as octet-stream: trust the link's extension.
    if path_ext in SUPPORTED_EXTS and path_ext not in IMAGE_EXTS and path_ext not in (".html", ".htm"):
        return path_ext
    if ct.startswith("text/"):
        return ".txt"
    return None


def safe_filename(title: str, url: str, ext: str) -> str:
    base = title or (urlparse(url).netloc + urlparse(url).path)
    base = re.sub(r"[^\w\-. ]+", " ", base).strip()
    base = re.sub(r"\s+", " ", base)[:120] or "imported-page"
    return f"{base}{ext}"


def normalize_url(url: str) -> str:
    """Accept "example.com/page" as well as full links."""
    url = url.strip()
    if url and "://" not in url:
        url = "https://" + url
    return url


async def fetch_url(url: str, max_bytes: int) -> FetchedDocument:
    url = normalize_url(url)
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False,
                                 headers={"User-Agent": USER_AGENT,
                                          "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9,*/*;q=0.8"}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            await _assert_public_host(_check_scheme(url))
            async with client.stream("GET", url) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise UrlImportError("The site redirected without a destination.")
                    url = urljoin(url, location)
                    continue
                if resp.status_code in (401, 403):
                    raise UrlImportError(f"The site refused the download (HTTP {resp.status_code}). It may need a login or block automated access.")
                if resp.status_code >= 400:
                    raise UrlImportError(f"The site answered with HTTP {resp.status_code}.")
                ext = _ext_for(resp.headers.get("content-type", ""), url)
                if ext is None:
                    raise UrlImportError(
                        f"Unsupported content type '{resp.headers.get('content-type', 'unknown')}'. "
                        "Links to web pages and documents (PDF, Word, Excel, PowerPoint, CSV, text) can be imported.")
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise UrlImportError(f"The file is larger than {max_bytes // (1024 * 1024)} MB.")
                break
        else:
            raise UrlImportError("Too many redirects.")

    if ext == ".html":
        title, text = html_to_text(body.decode(resp.encoding or "utf-8", errors="replace"))
        if len(text) < 50:
            raise UrlImportError("The page has almost no readable text (it may need JavaScript to render).")
        header = f"# {title}\nSource: {url}\n\n" if title else f"Source: {url}\n\n"
        return FetchedDocument((header + text).encode("utf-8"), ".txt", title, url)

    title = urlparse(url).path.rsplit("/", 1)[-1] or urlparse(url).netloc
    title = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", title)
    return FetchedDocument(bytes(body), ext, title, url)
