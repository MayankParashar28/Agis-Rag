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
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside", "iframe"}
    BLOCK = {"p", "div", "section", "article", "br", "li", "tr", "h1", "h2", "h3",
             "h4", "h5", "h6", "pre", "blockquote", "table", "ul", "ol"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.parts.append("\n")
        if tag in ("h1", "h2", "h3") and not self._skip_depth:
            self.parts.append("## " if tag != "h1" else "# ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r"\n\s*\n\s*\n+", "\n\n", raw)
        return "\n".join(line.strip() for line in raw.splitlines()).strip()


def html_to_text(html: str) -> Tuple[str, str]:
    """Return (title, readable text) for an HTML document."""
    parser = _TextExtractor()
    parser.feed(html)
    return parser.title.strip(), parser.text()


def _ext_for(content_type: str, url: str) -> Optional[str]:
    ct = content_type.split(";")[0].strip().lower()
    if ct == "application/pdf" or url.lower().endswith(".pdf"):
        return ".pdf"
    if ct in ("text/csv", "application/csv") or url.lower().endswith(".csv"):
        return ".csv"
    if ct == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return ".docx"
    if ct in ("text/html", "application/xhtml+xml"):
        return ".html"
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
                        "Links to web pages, PDF, DOCX, CSV or text files can be imported.")
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
    title = re.sub(r"\.(pdf|csv|txt|docx)$", "", title, flags=re.I)
    return FetchedDocument(bytes(body), ext, title, url)
