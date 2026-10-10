"""Deny escrow reads until Track-B Capability Gold is frozen."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class EscrowAccessDenied(PermissionError):
    pass


def assert_escrow_access_authorised() -> None:
    if os.environ.get("TRACK_B_CAPABILITY_GOLD_FROZEN") != "true":
        raise EscrowAccessDenied("Track-B legacy escrow remains sealed before Gold freeze")


def read_escrow_after_gold(path: Path) -> list[dict[str, Any]]:
    assert_escrow_access_authorised()
    if not path.is_file() or path.is_symlink():
        raise EscrowAccessDenied("legacy escrow payload is unavailable or unsafe")
    return [json.loads(line) for line in path.read_text().splitlines() if line]
