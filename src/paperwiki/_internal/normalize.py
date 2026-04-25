"""Identifier and title normalization helpers.

The dedup filter and any cross-source identity check rely on a shared
normalization pass to compare arxiv ids and paper titles consistently.
The two functions here are the single source of truth.

Design choices:

* ``normalize_arxiv_id`` accepts the variants paper authors actually
  produce (``"arXiv:..."``, ``"arxiv:..."``, plain ids, ``vN`` suffixes)
  and rejects anything that doesn't fit the modern ``\\d+\\.\\d+`` form.
  Old-style ids (``cs.LG/0001001``) are out of scope for v0.x.
* ``normalize_title_key`` lowercases and strips everything outside
  ``[a-z0-9]``. This is intentionally aggressive — punctuation and CJK
  characters add noise without identity value across translation/edits.
"""

from __future__ import annotations

import re

_MODERN_ARXIV_ID_PATTERN = re.compile(r"^\d+\.\d+$")
_TITLE_KEY_STRIP_PATTERN = re.compile(r"[^a-z0-9]")


def normalize_arxiv_id(raw: str | None) -> str | None:
    """Return the canonical numeric form of an arxiv id, or ``None``.

    Examples::

        "arXiv:2506.13063"   -> "2506.13063"
        "arxiv:2506.13063v2" -> "2506.13063"
        "2506.13063"         -> "2506.13063"
        "not-an-id"          -> None
        ""                   -> None
    """
    if not isinstance(raw, str):
        return None
    s = raw.strip().lower()
    s = re.sub(r"^arxiv:\s*", "", s)
    s = re.sub(r"v\d+$", "", s)
    if _MODERN_ARXIV_ID_PATTERN.match(s):
        return s
    return None


def normalize_title_key(title: str | None) -> str | None:
    """Return a comparison-safe key for a paper title, or ``None`` if empty.

    Lowercases the input and strips everything except ``[a-z0-9]``.
    Returns ``None`` when the result is empty (e.g. punctuation-only input
    or ``None``).
    """
    if not isinstance(title, str):
        return None
    key = _TITLE_KEY_STRIP_PATTERN.sub("", title.lower())
    return key or None


__all__ = [
    "normalize_arxiv_id",
    "normalize_title_key",
]
