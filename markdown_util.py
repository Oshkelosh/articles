"""Plain-text helpers for article Markdown (no MD→HTML dependency)."""

from __future__ import annotations

import re

_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_MD_EMPHASIS = re.compile(r"[*_`#>\-]+")
_WHITESPACE = re.compile(r"\s+")


def plain_excerpt(markdown: str, max_len: int = 160) -> str:
    """Strip light Markdown markup and truncate for meta/list excerpts."""
    text = markdown or ""
    text = _MD_IMAGE.sub("", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_EMPHASIS.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."
