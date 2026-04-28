"""Centralized logger configuration for paperwiki runners."""

from __future__ import annotations

import os
import sys

from loguru import logger


def configure_runner_logging(
    *,
    verbose: bool = False,
    default_level: str = "INFO",
) -> None:
    """Reset loguru's sinks and re-configure for runner output.

    Removes the default DEBUG sink. Adds a stderr sink at
    ``default_level`` (INFO) or DEBUG when ``verbose`` is True.
    Honors PAPERWIKI_LOG_LEVEL env var as the highest-priority
    override (so CI / hooks can silence runners with one env var).
    """
    logger.remove()  # Drop loguru's default DEBUG sink.

    env_override = os.environ.get("PAPERWIKI_LOG_LEVEL")
    if env_override:
        level = env_override.upper()
    elif verbose:
        level = "DEBUG"
    else:
        level = default_level

    logger.add(
        sys.stderr,
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function} - {message}",
    )

    # Pin chatty modules to WARNING by default (overridable via
    # PAPERWIKI_LOG_LEVEL=DEBUG which still wins).
    if not verbose and not env_override:
        logger.disable("paperwiki.plugins.filters.dedup")
        logger.disable("paperwiki._internal.arxiv_source")


__all__ = ["configure_runner_logging"]
