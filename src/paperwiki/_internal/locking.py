"""Vault-level advisory lock for mutating runners.

All runners that write to ``Wiki/sources/`` or ``Wiki/concepts/`` must acquire
the vault lock before touching the filesystem. This prevents concurrent ingest
and compile runs from writing partial state that confuses downstream tools.

Usage::

    from paperwiki._internal.locking import acquire_vault_lock

    async def my_runner(vault_path: Path) -> None:
        async with acquire_vault_lock(vault_path):
            ...  # safe to write

Implementation
--------------
The lock is a plain file at ``<vault>/.vault.lock``. We open it with ``O_CREAT``
and then apply an exclusive advisory lock via the platform mechanism:

- **POSIX** (Linux, macOS): ``fcntl.flock(fd, LOCK_EX | LOCK_NB)``.
- **Windows** (fallback): ``msvcrt.locking`` with ``LK_NBLCK``.

When the lock is held by another process, we raise :class:`VaultLockError`
immediately (non-blocking) rather than spinning — the caller should surface the
error to the user. The lock is released when the async context manager exits.

We deliberately use ``asyncio.to_thread`` for the blocking OS calls so the
event loop is not stalled while waiting for the underlying file-system.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from paperwiki.core.errors import UserError

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class VaultLockError(UserError):
    """Raised when the vault is already locked by another process."""

    exit_code = 1


def _lock_file_path(vault_path: Path) -> Path:
    return vault_path / ".vault.lock"


def _acquire_lock_sync(fd: int) -> None:
    """Acquire exclusive lock on *fd* (non-blocking)."""
    if sys.platform == "win32":
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            msg = "vault is locked by another process"
            raise VaultLockError(msg) from exc
    else:
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            msg = "vault is locked by another process"
            raise VaultLockError(msg) from exc


def _release_lock_sync(fd: int) -> None:
    """Release lock and close *fd*."""
    if sys.platform == "win32":
        import msvcrt

        with contextlib.suppress(OSError):
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


@asynccontextmanager
async def acquire_vault_lock(vault_path: Path) -> AsyncGenerator[None, None]:
    """Async context manager that holds the exclusive vault lock.

    Raises :class:`VaultLockError` immediately if another process holds the
    lock. The lock is released when the context exits, even on exception.
    """
    lock_path = _lock_file_path(vault_path)
    # Ensure vault root exists (runners may run before first ingest).
    await asyncio.to_thread(lock_path.parent.mkdir, parents=True, exist_ok=True)

    fd = await asyncio.to_thread(
        os.open,
        str(lock_path),
        os.O_CREAT | os.O_WRONLY,
        0o644,
    )
    try:
        await asyncio.to_thread(_acquire_lock_sync, fd)
    except VaultLockError:
        await asyncio.to_thread(os.close, fd)
        raise

    try:
        yield
    finally:
        await asyncio.to_thread(_release_lock_sync, fd)


__all__ = ["VaultLockError", "acquire_vault_lock"]
