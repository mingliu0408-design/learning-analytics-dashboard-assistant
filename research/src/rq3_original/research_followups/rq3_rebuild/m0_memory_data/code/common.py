"""Owned utilities. No provider, routing, generation, or network dependency."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
from datetime import datetime, timezone

OWNED = Path(__file__).resolve().parents[1]
BASE_HEAD = "595b949185ad1b97cdbb9b0fdaeb9804aff7c45c"
SUBTREE = "research_followups/rq3_rebuild/m0_memory_data"
FLAGS = ["SYNTHETIC_DEVELOPMENT_FIXTURE", "MODEL_AUTHORED", "NOT_FOR_INDEPENDENT_TEST"]
_offline = False

def utc():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")

def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def object_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()

def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")

def disable_network():
    """Process-wide guard, installed before importing inherited code or ML libraries."""
    global _offline
    if _offline:
        return
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE",
                "HF_HUB_DISABLE_TELEMETRY", "PYTHONDONTWRITEBYTECODE"):
        os.environ[key] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"
    sys.dont_write_bytecode = True
    def guard(event, args):
        if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo",
                     "socket.gethostbyname", "socket.gethostbyaddr", "socket.bind",
                     "socket.sendto", "socket.sendmsg"}:
            raise RuntimeError("M0_NETWORK_DISABLED")
        if event == "socket.__new__" and args[1] in (socket.AF_INET, socket.AF_INET6):
            raise RuntimeError("M0_NETWORK_DISABLED")
    sys.addaudithook(guard)
    _offline = True

def inherited_root():
    root = OWNED.parents[2]
    if not (root / "utils/c4_memory/c4_memory_store.py").is_file():
        raise RuntimeError("INHERITED_REPOSITORY_REQUIRED: see MEMORY_STATE_HARNESS.md")
    sys.path.insert(0, str(root))
    return root
