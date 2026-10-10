"""Atomic, durable, reread-verified persistence primitives for future D1."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from typing import Callable


class DurablePersistenceError(RuntimeError):
    pass


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_durable(
    path: Path,
    payload: bytes,
    *,
    mode: int = 0o600,
    replace: bool = False,
    verifier: Callable[[bytes], None] | None = None,
) -> dict[str, int | str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and not replace):
        raise DurablePersistenceError("durable target already exists")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() and not replace:
            raise DurablePersistenceError("durable target appeared during write")
        os.replace(temporary, path)
        os.chmod(path, mode)
        _fsync_directory(path.parent)
        reread = path.read_bytes()
        if reread != payload:
            raise DurablePersistenceError("durable reread mismatch")
        if verifier is not None:
            verifier(reread)
        return {
            "sha256": hashlib.sha256(reread).hexdigest(),
            "size_bytes": len(reread),
        }
    finally:
        if temporary.exists():
            temporary.unlink()


def verify_durable_payload(path: Path, receipt: dict[str, object]) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise DurablePersistenceError("durable payload is missing or unsafe")
    payload = path.read_bytes()
    if (
        hashlib.sha256(payload).hexdigest() != receipt.get("sha256")
        or len(payload) != receipt.get("size_bytes")
    ):
        raise DurablePersistenceError("durable receipt mismatch")
    return payload
