"""Relevance filter — drop papers that don't match any configured topic.

A :class:`Topic` is a named bundle of keywords (multi-word phrases
allowed) and arXiv-style categories. A paper passes the filter when at
least one topic matches via:

* a keyword appearing in the title or abstract under word-boundary,
  case-insensitive comparison, **or**
* a category overlapping the paper's ``categories`` list.

The filter does not annotate matched topics on the paper — that is a
scoring concern. Filters stay pure: drop or keep, nothing else.

Empty topic lists and topics with neither keywords nor categories are
rejected at construction so misconfigured recipes fail fast instead of
silently dropping every paper.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from paperwiki.core.models import Paper, RunContext


class Topic(BaseModel):
    """A named bundle of keywords and arXiv categories used for matching."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            msg = "name must not be blank"
            raise ValueError(msg)
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def keyword_set(self) -> set[str]:
        """Lowercased keywords for fast comparison."""
        return {k.lower() for k in self.keywords if k.strip()}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def category_set(self) -> set[str]:
        """Lowercased categories for fast comparison."""
        return {c.lower() for c in self.categories if c.strip()}


class RelevanceFilter:
    """Pass papers that match at least one configured :class:`Topic`."""

    name = "relevance"

    def __init__(self, topics: list[Topic]) -> None:
        if not topics:
            msg = "RelevanceFilter requires at least one topic"
            raise ValueError(msg)
        for topic in topics:
            if not topic.keyword_set and not topic.category_set:
                msg = (
                    f"topic {topic.name!r} must declare keywords or categories;"
                    " an empty topic matches nothing"
                )
                raise ValueError(msg)
        self.topics = list(topics)
        # Pre-compile keyword patterns once. A keyword matches when it
        # appears between word boundaries (so "ai" does not hit "rain").
        self._keyword_patterns: list[tuple[Topic, list[re.Pattern[str]]]] = []
        for topic in self.topics:
            patterns = [
                re.compile(rf"\b{re.escape(k)}\b", re.IGNORECASE) for k in topic.keyword_set
            ]
            self._keyword_patterns.append((topic, patterns))

    async def apply(
        self,
        papers: AsyncIterator[Paper],
        ctx: RunContext,
    ) -> AsyncIterator[Paper]:
        async for paper in papers:
            if self._matches_any_topic(paper):
                yield paper
            else:
                ctx.increment("filter.relevance.dropped")

    def _matches_any_topic(self, paper: Paper) -> bool:
        haystack = f"{paper.title}\n{paper.abstract}"
        paper_categories = {c.lower() for c in paper.categories}
        for topic, patterns in self._keyword_patterns:
            if topic.category_set & paper_categories:
                return True
            for pattern in patterns:
                if pattern.search(haystack):
                    return True
        return False


__all__ = ["RelevanceFilter", "Topic"]
