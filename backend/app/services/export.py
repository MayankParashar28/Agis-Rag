"""Conversation export (Markdown with citations as footnotes)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional


def conversation_to_markdown(conv, messages: List, kb_name: Optional[str]) -> str:
    """Export a conversation as Markdown with citations as footnotes."""
    lines = [f"# {conv.title}", ""]
    meta = []
    if kb_name:
        meta.append(f"Knowledge base: {kb_name}")
    meta.append(f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines += [" · ".join(meta), ""]
    notes: List[str] = []
    for m in messages:
        if m.sender == "user":
            lines += [f"**You:** {m.content}", ""]
            continue
        body = m.content or ""
        cits = m.citations or []
        for c in cits:
            idx = c.get("index") or (cits.index(c) + 1)
            page = c.get("page")
            ref = f"{c.get('source_doc', 'source')}" + (f", page {page}" if page else "")
            if c.get("url"):
                ref += f" <{c['url']}>"
            notes.append(f"[^{len(notes) + 1}]: {ref}")
            n = len(notes)
            body = re.sub(rf"\[Source\s+{idx}\]", f"[^{n}]", body)
        lines += ["**Assistant:**", "", body, ""]
    if notes:
        lines += ["---", "", "## Sources", ""] + notes + [""]
    return "\n".join(lines)


