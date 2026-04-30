"""Install-state health checks shared by ``paperwiki status`` and
``paperwiki doctor``.

v0.3.43 D-9.43.3 extracts what was previously
``paperwiki.cli._check_install_health`` so the doctor command can
reuse the same logic without an import-cycle. The function is
read-only — no env mutation, no filesystem writes — and returns
structured tuples so callers control the rendering.

The helper / shim / PATH check pattern was introduced in v0.3.40
D-9.40.1 (status command); v0.3.41 D-9.41.2 added strict-mode exit
for ``paperwiki status``; v0.3.43 promotes it to the canonical
shared probe.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "VERSION_TAG_RE",
    "InstallHealthRow",
    "check_install_health",
]


VERSION_TAG_RE = re.compile(r"v(\d+\.\d+\.\d+)")
"""Match a SemVer ``v<X>.<Y>.<Z>`` tag inside a header line."""


# ``InstallHealthRow`` is a positional tuple intentionally (matches the
# v0.3.40 shape). New consumers should prefer named access:
#
#   for label, ok, hint in check_install_health(...):
#       ...
InstallHealthRow = tuple[str, bool, str | None]


def check_install_health(
    *,
    home: Path,
    expected_version: str,
    path_env: str | None,
) -> list[InstallHealthRow]:
    """Return ``[(label, ok, action_hint)]`` for the four install-health checks.

    Args:
        home: User's HOME directory (helper + shim resolve under
            ``$HOME/.local/{lib,bin}/``).
        expected_version: The version tag expected in the helper and
            shim headers (typically ``paperwiki.__version__``).
        path_env: Value of ``$PATH`` to scan for ``$HOME/.local/bin``;
            pass ``None`` to render an "unset PATH" outcome.

    The four rows checked, in order:

    1. ``~/.local/lib/paperwiki/bash-helpers.sh`` exists.
    2. Helper's first-line tag matches ``expected_version``.
    3. ``~/.local/bin/paperwiki`` exists AND its tag line matches.
    4. ``~/.local/bin`` is on ``$PATH``.

    Read-only — no side effects, no env mutation. Each row is computed
    independently; missing helper does NOT short-circuit row 2 (the
    label "helper tag matches" reports False with the same restart hint).
    """
    helper_path = home / ".local" / "lib" / "paperwiki" / "bash-helpers.sh"
    shim_path = home / ".local" / "bin" / "paperwiki"
    expected_tag = f"v{expected_version}"
    restart_hint = "restart Claude Code"
    path_hint = 'add `export PATH="$HOME/.local/bin:$PATH"` to your shell rc'

    rows: list[InstallHealthRow] = []

    # Row 1: helper file present.
    helper_present = helper_path.is_file()
    rows.append(
        (
            "helper present",
            helper_present,
            None if helper_present else restart_hint,
        )
    )

    # Row 2: helper tag matches expected version.
    helper_tag_match = False
    if helper_present:
        try:
            content = helper_path.read_text(encoding="utf-8")
            first_line = content.splitlines()[0] if content else ""
            match = VERSION_TAG_RE.search(first_line)
            if match is not None and match.group(0) == expected_tag:
                helper_tag_match = True
        except (OSError, UnicodeDecodeError, IndexError):
            helper_tag_match = False
    rows.append(
        (
            "helper tag matches",
            helper_tag_match,
            None if helper_tag_match else restart_hint,
        )
    )

    # Row 3: shim present AND tag matches (combined per plan §17.3).
    shim_ok = False
    if shim_path.is_file():
        try:
            content = shim_path.read_text(encoding="utf-8")
            for line in content.splitlines()[:2]:
                match = VERSION_TAG_RE.search(line)
                if match and match.group(0) == expected_tag:
                    shim_ok = True
                    break
        except (OSError, UnicodeDecodeError):
            shim_ok = False
    rows.append(
        (
            "shim present + tag matches",
            shim_ok,
            None if shim_ok else restart_hint,
        )
    )

    # Row 4: ~/.local/bin on PATH.
    local_bin = str(home / ".local" / "bin")
    path_value = path_env if path_env is not None else ""
    path_ok = local_bin in path_value.split(":")
    rows.append(
        (
            "~/.local/bin on PATH",
            path_ok,
            None if path_ok else path_hint,
        )
    )

    return rows
