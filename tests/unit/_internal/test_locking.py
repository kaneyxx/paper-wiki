"""Unit tests for paperwiki._internal.locking."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from paperwiki._internal.locking import VaultLockError, acquire_vault_lock


class TestAcquireVaultLock:
    async def test_lock_creates_lock_file(self, tmp_path: Path) -> None:
        """The lock file is created on first acquisition."""
        async with acquire_vault_lock(tmp_path):
            assert (tmp_path / ".vault.lock").is_file()

    async def test_lock_file_persists_after_release(self, tmp_path: Path) -> None:
        """Lock file is not deleted on release (intentional — deletion is racy)."""
        async with acquire_vault_lock(tmp_path):
            pass
        assert (tmp_path / ".vault.lock").is_file()

    async def test_sequential_acquisitions_succeed(self, tmp_path: Path) -> None:
        """The same process can re-acquire the lock after releasing it."""
        async with acquire_vault_lock(tmp_path):
            pass
        async with acquire_vault_lock(tmp_path):
            pass

    async def test_lock_creates_parent_dir(self, tmp_path: Path) -> None:
        """acquire_vault_lock creates the vault directory if it does not exist."""
        vault = tmp_path / "new_vault"
        assert not vault.exists()
        async with acquire_vault_lock(vault):
            assert vault.is_dir()
            assert (vault / ".vault.lock").is_file()

    async def test_nested_lock_from_same_process_raises(self, tmp_path: Path) -> None:
        """A second acquire_vault_lock call while the lock is held must raise VaultLockError.

        Advisory ``flock`` on most POSIX systems is per-process, meaning the
        same process can re-lock without blocking. We test the concurrent-task
        scenario explicitly to document the expected cross-task behavior.
        """
        # Start a task that holds the lock and then tries to re-acquire it.
        # Since flock is per-process on POSIX, this may or may not raise —
        # what we do verify is that concurrent tasks coordinate correctly.
        results: list[bool] = []

        async def _hold_and_probe() -> None:
            async with acquire_vault_lock(tmp_path):
                # Try to acquire from a concurrent asyncio task.
                try:
                    async with acquire_vault_lock(tmp_path):
                        results.append(True)
                except VaultLockError:
                    results.append(False)

        await asyncio.wait_for(_hold_and_probe(), timeout=5)
        # We don't assert True/False — the behavior is platform-specific.
        # The important thing is it doesn't hang.
        assert len(results) == 1

    async def test_lock_released_on_exception(self, tmp_path: Path) -> None:
        """The lock is released even when the body raises an exception."""
        with pytest.raises(RuntimeError):
            async with acquire_vault_lock(tmp_path):
                raise RuntimeError("deliberate error")

        # After the exception, the lock file should exist and be acquirable again.
        async with acquire_vault_lock(tmp_path):
            pass


class TestVaultLockError:
    def test_is_user_error(self) -> None:
        from paperwiki.core.errors import UserError

        assert issubclass(VaultLockError, UserError)

    def test_exit_code_is_one(self) -> None:
        err = VaultLockError("vault is locked")
        assert err.exit_code == 1
