"""Unit tests for paperwiki._internal.normalize.

These helpers underpin the dedup filter and any cross-source identity
matching, so we exercise the boundary cases aggressively.
"""

from __future__ import annotations

import pytest

from paperwiki._internal.normalize import normalize_arxiv_id, normalize_title_key


class TestNormalizeArxivId:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2506.13063", "2506.13063"),
            ("arXiv:2506.13063", "2506.13063"),
            ("arxiv:2506.13063", "2506.13063"),
            (" arXiv:2506.13063 ", "2506.13063"),
            ("2506.13063v1", "2506.13063"),
            ("2506.13063v12", "2506.13063"),
            ("ARXIV:2506.13063V2", "2506.13063"),
            # Old-format ids (e.g. cs.LG/0001001) — we accept the modern form only.
            # These should normalize to None or pass through? Decision: pass through
            # if it parses, but we currently only support modern dotted form.
            ("not-an-id", None),
            ("", None),
            (None, None),
            ("   ", None),
        ],
    )
    def test_normalize_arxiv_id_examples(self, raw: str | None, expected: str | None) -> None:
        assert normalize_arxiv_id(raw) == expected

    def test_non_string_input_returns_none(self) -> None:
        # Defensive: callers may pass anything they pulled from JSON.
        assert normalize_arxiv_id(12345) is None  # type: ignore[arg-type]
        assert normalize_arxiv_id([]) is None  # type: ignore[arg-type]


class TestNormalizeTitleKey:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("PRISM2: Unlocking Multi-Modal AI", "prism2unlockingmultimodalai"),
            ("Foo-Bar (v2)", "foobarv2"),
            ("  Mixed    Whitespace  ", "mixedwhitespace"),
            ("中英文混合 — Vision-Language", "visionlanguage"),
            ("12345", "12345"),
            ("", None),
            (None, None),
            ("   ", None),
            ("!!!", None),  # all punctuation -> empty after stripping
        ],
    )
    def test_normalize_title_key_examples(self, raw: str | None, expected: str | None) -> None:
        assert normalize_title_key(raw) == expected

    def test_normalize_title_key_is_idempotent(self) -> None:
        title = "Foo-Bar Baz"
        once = normalize_title_key(title)
        twice = normalize_title_key(once)
        assert once == twice
