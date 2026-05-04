"""CLI tests for ``paperwiki extract-images`` vault optionality (Task 9.193).

Phase D 9.193 makes the ``vault`` positional optional so ``extract-images
<id>`` runs through the D-V resolver chain instead of forcing the user
to type the vault path every time. These tests pin both forms work:

* ``extract-images <vault> <id>`` — back-compat (existing behavior).
* ``extract-images <id>`` — new form, vault resolved from
  ``$PAPERWIKI_DEFAULT_VAULT`` or ``$PAPERWIKI_HOME/config.toml``.

The tests stub out the async ``extract_paper_images`` runner so they
exercise CLI argument parsing + resolver wiring without doing real
arxiv network I/O.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner


@dataclass
class _StubExtractResult:
    """Minimal stand-in for ``ExtractResult`` so the CLI's JSON dump works."""

    canonical_id: str = "arxiv:2506.13063"
    image_count: int = 1
    images: list[str] | None = None
    sources: dict[str, int] | None = None
    skipped: bool = False
    skip_reason: str | None = None

    def __post_init__(self) -> None:
        if self.images is None:
            self.images = []
        if self.sources is None:
            self.sources = {}


@pytest.fixture
def capture_runner_call(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace the async runner with a recorder so CLI tests stay hermetic.

    The recorder captures the resolved ``vault`` and ``canonical_id`` so
    individual tests can assert which path the resolver picked.
    """
    captured: dict[str, Any] = {}

    async def _fake_runner(
        vault: Path,
        canonical_id: str,
        *,
        force: bool = False,
        http_client: Any = None,
    ) -> _StubExtractResult:
        captured["vault"] = vault
        captured["canonical_id"] = canonical_id
        captured["force"] = force
        return _StubExtractResult(canonical_id=canonical_id)

    from paperwiki.runners import extract_paper_images as runner

    monkeypatch.setattr(runner, "extract_paper_images", _fake_runner)
    return captured


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear paper-wiki env vars so each test's resolver state is clean."""
    for var in (
        "PAPERWIKI_DEFAULT_VAULT",
        "PAPERWIKI_HOME",
        "PAPERWIKI_CONFIG_DIR",
    ):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Back-compat: two positional args still work
# ---------------------------------------------------------------------------


def test_extract_images_two_args_back_compat(
    tmp_path: Path,
    capture_runner_call: dict[str, Any],
) -> None:
    """``extract-images <vault> <id>`` is the historical form — still works."""
    from paperwiki.runners import extract_paper_images as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, [str(tmp_path), "arxiv:2506.13063"])

    assert result.exit_code == 0, result.output
    assert capture_runner_call["vault"] == tmp_path
    assert capture_runner_call["canonical_id"] == "arxiv:2506.13063"


# ---------------------------------------------------------------------------
# New form: vault resolved from env / config.toml
# ---------------------------------------------------------------------------


def test_extract_images_one_arg_resolves_vault_from_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_runner_call: dict[str, Any],
) -> None:
    """With only canonical_id, vault comes from $PAPERWIKI_DEFAULT_VAULT."""
    monkeypatch.setenv("PAPERWIKI_DEFAULT_VAULT", str(tmp_path))

    from paperwiki.runners import extract_paper_images as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, ["arxiv:2506.13063"])

    assert result.exit_code == 0, result.output
    assert capture_runner_call["vault"] == tmp_path
    assert capture_runner_call["canonical_id"] == "arxiv:2506.13063"


def test_extract_images_one_arg_resolves_vault_from_config_toml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_runner_call: dict[str, Any],
) -> None:
    """With only canonical_id, vault comes from config.toml when env unset."""
    fake_home = tmp_path / "paperwiki-home"
    fake_home.mkdir()
    fake_vault = tmp_path / "vault"
    (fake_home / "config.toml").write_text(
        f'default_vault = "{fake_vault}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PAPERWIKI_HOME", str(fake_home))

    from paperwiki.runners import extract_paper_images as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, ["arxiv:2506.13063"])

    assert result.exit_code == 0, result.output
    assert capture_runner_call["vault"] == fake_vault


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_extract_images_no_args_errors(
    capture_runner_call: dict[str, Any],
) -> None:
    """Zero positional args → exit non-zero with a usage-shaped error."""
    from paperwiki.runners import extract_paper_images as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, [])

    assert result.exit_code != 0
    # Either Typer's "missing argument" or our resolver's actionable
    # error is acceptable — both surface the gap to the user.
    combined = (result.output + (result.stderr if hasattr(result, "stderr") else "")).lower()
    assert "missing" in combined or "canonical" in combined or "argument" in combined


def test_extract_images_one_arg_no_vault_anywhere_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_runner_call: dict[str, Any],
) -> None:
    """``extract-images <id>`` with no resolver source set → actionable error."""
    monkeypatch.setenv("PAPERWIKI_HOME", str(tmp_path))  # empty home, no config.toml

    from paperwiki.runners import extract_paper_images as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, ["arxiv:2506.13063"])

    assert result.exit_code != 0
    combined = result.output + (result.stderr if hasattr(result, "stderr") else "")
    assert "--vault" in combined or "PAPERWIKI_DEFAULT_VAULT" in combined


# ---------------------------------------------------------------------------
# Disambiguation: a single arg that looks like a vault path
# ---------------------------------------------------------------------------


def test_extract_images_one_arg_without_colon_is_treated_as_vault_legacy_call(
    tmp_path: Path,
    capture_runner_call: dict[str, Any],
) -> None:
    """Defensive UX: a single arg WITHOUT ':' is unusable (not a canonical_id
    nor enough info to extract). The CLI must reject it with a useful hint
    rather than silently treating it as a vault path and crashing later when
    canonical_id is missing.
    """
    from paperwiki.runners import extract_paper_images as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, [str(tmp_path)])  # no canonical_id

    assert result.exit_code != 0
    combined = (result.output + (result.stderr if hasattr(result, "stderr") else "")).lower()
    # Must surface that canonical_id is missing or that the arg shape is wrong.
    assert "canonical" in combined or "missing" in combined or "arxiv:" in combined


def test_extract_images_emits_valid_json_in_new_form(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_runner_call: dict[str, Any],
) -> None:
    """The new single-arg form still emits the same JSON shape on stdout."""
    monkeypatch.setenv("PAPERWIKI_DEFAULT_VAULT", str(tmp_path))

    from paperwiki.runners import extract_paper_images as runner

    cli = CliRunner()
    result = cli.invoke(runner.app, ["arxiv:2506.13063"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["canonical_id"] == "arxiv:2506.13063"
    assert "image_count" in payload
