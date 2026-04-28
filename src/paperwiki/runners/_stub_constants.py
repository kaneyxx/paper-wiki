"""Constants shared between the auto-bootstrap runner and wiki-lint detection.

Single source of truth for the auto-created stub sentinel string and
frontmatter shape, so wiki-ingest (creates) and wiki-lint (detects) can
never drift.
"""

from __future__ import annotations

AUTO_CREATED_SENTINEL_BODY = (
    "_Auto-created during digest auto-ingest. "
    "This stub is intentionally empty until you run /paper-wiki:wiki-ingest on the source paper "
    "to synthesize a proper concept article._\n\n"
    "_Lint with /paper-wiki:wiki-lint to surface all stubs that still need review._"
)

# Individually-typed constants (preferred — used by runner)
AUTO_CREATED_FLAG: bool = True
AUTO_CREATED_TAGS: tuple[str, ...] = ("auto-created",)
AUTO_CREATED_STATUS: str = "draft"
AUTO_CREATED_CONFIDENCE: float = 0.3

# Bundle for code that wants the full frontmatter shape at once
# (e.g. tests asserting parity with the runner's writes).
AUTO_CREATED_FRONTMATTER_FIELDS: dict[str, object] = {
    "auto_created": AUTO_CREATED_FLAG,
    "tags": list(AUTO_CREATED_TAGS),
    "status": AUTO_CREATED_STATUS,
    "confidence": AUTO_CREATED_CONFIDENCE,
}
