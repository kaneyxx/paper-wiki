"""Task 9.197 (was 9.153) — snapshot the ``paperwiki update --check``
output ordering.

Pre-v0.3.43, ``_consume_rc_just_added_stamp()`` was called at the
TOP of ``update()``, which printed the rc-edit acknowledgement
**before** the dry-run plan — misleading users into thinking
the upgrade had already happened. v0.3.43 D-9.43.4 moved the
consume-stamp call to the END of each branch (``--check`` exit and
apply-mode end) so the plan is always read first.

Existing tests in ``test_update_self_heal.py`` pin this at the
``app.invoke`` boundary; this commit adds a direct unit-level pin
on the ``_print_update_check_plan`` helper so a future refactor
that splits format from order can't quietly regress.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from paperwiki import cli

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


# ---------------------------------------------------------------------------
# Direct unit pins on _print_update_check_plan — snapshots the text
# ---------------------------------------------------------------------------


def test_check_plan_already_at_latest_emits_no_action_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When versions match, the plan must say "already at" and nothing else."""
    cli._print_update_check_plan(
        marketplace_ver="0.4.7",
        cache_ver="0.4.7",
        cache_empty=False,
        mid_upgrade=False,
    )
    captured = capsys.readouterr()
    assert captured.out == "plan: paper-wiki is already at 0.4.7 — no action needed\n"


def test_check_plan_drift_lists_each_step_in_order(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Drift detected: plan + Note + nothing-applied trailer in that order."""
    cli._print_update_check_plan(
        marketplace_ver="0.4.7",
        cache_ver="0.4.6",
        cache_empty=False,
        mid_upgrade=False,
    )
    captured = capsys.readouterr()
    out = captured.out

    plan_pos = out.find("plan: would upgrade 0.4.6 → 0.4.7")
    note_pos = out.find("Note: .bak directories live at")
    trailer_pos = out.find("nothing applied — re-run without --check to apply.")

    # All three are present.
    assert plan_pos != -1, f"missing 'plan: would upgrade' line in:\n{out}"
    assert note_pos != -1, f"missing 'Note: .bak' line in:\n{out}"
    assert trailer_pos != -1, f"missing 'nothing applied' trailer in:\n{out}"

    # Order: plan → Note → trailer.
    assert plan_pos < note_pos < trailer_pos, (
        f"order broken — plan_pos={plan_pos} note_pos={note_pos} trailer_pos={trailer_pos}\n{out}"
    )


def test_check_plan_mid_upgrade_emits_hint_first(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Mid-upgrade state takes priority over normal drift summary."""
    cli._print_update_check_plan(
        marketplace_ver="0.4.7",
        cache_ver="0.4.6",
        cache_empty=False,
        mid_upgrade=True,
    )
    captured = capsys.readouterr()
    out = captured.out

    assert out.startswith("plan: paper-wiki appears to be mid-upgrade"), (
        f"mid-upgrade hint must lead the output:\n{out}"
    )
    assert "nothing applied" in out


def test_check_plan_cache_empty_emits_self_heal_preview(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Empty cache: preview self-heal."""
    cli._print_update_check_plan(
        marketplace_ver="0.4.7",
        cache_ver=None,
        cache_empty=True,
        mid_upgrade=False,
    )
    captured = capsys.readouterr()
    out = captured.out

    assert "self-heal from marketplace at v0.4.7" in out
    assert "nothing applied" in out


# ---------------------------------------------------------------------------
# _consume_rc_just_added_stamp — pins consume-once semantics
# (Task 9.197 sibling: the rc-edit hint must fire AFTER the plan,
# and only once per stamp.)
# ---------------------------------------------------------------------------


def test_consume_stamp_is_silent_when_no_stamp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No stamp file → no output. Pin the silent-no-op contract."""
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda _cls: tmp_path))

    cli._consume_rc_just_added_stamp()
    captured = capsys.readouterr()

    assert captured.out == ""


def test_consume_stamp_emits_message_and_deletes_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Stamp present → emit "Added auto-source line to <rc>" then delete it.

    Consume-once semantics: stamp deleted as a side effect so a follow-up
    call is silent (which the next test pins).
    """
    stamp_dir = tmp_path / ".local" / "lib" / "paperwiki"
    stamp_dir.mkdir(parents=True)
    stamp_path = stamp_dir / ".rc-just-added"
    stamp_path.write_text("/Users/test/.zshrc\n", encoding="utf-8")

    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda _cls: tmp_path))

    cli._consume_rc_just_added_stamp()
    captured = capsys.readouterr()

    assert "Added auto-source line to /Users/test/.zshrc" in captured.out
    assert not stamp_path.exists(), "stamp must be deleted after consumption"


def test_consume_stamp_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Second call (after consumption) emits nothing."""
    stamp_dir = tmp_path / ".local" / "lib" / "paperwiki"
    stamp_dir.mkdir(parents=True)
    stamp_path = stamp_dir / ".rc-just-added"
    stamp_path.write_text("/Users/test/.zshrc\n", encoding="utf-8")

    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda _cls: tmp_path))

    # First call consumes.
    cli._consume_rc_just_added_stamp()
    capsys.readouterr()

    # Second call: silent.
    cli._consume_rc_just_added_stamp()
    captured = capsys.readouterr()
    assert captured.out == ""
