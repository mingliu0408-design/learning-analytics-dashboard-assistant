#!/usr/bin/env python3
"""Recompute saved numerical results with network access disabled in this process."""
from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
NETWORK_ATTEMPTS = []


def offline_guard(event, args):
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.bind"}:
        NETWORK_ATTEMPTS.append(event)
        raise RuntimeError("OFFLINE_NETWORK_DISABLED")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", required=True)
    parser.add_argument("--output", type=Path, default=Path("outputs/reproduction"))
    args = parser.parse_args()
    if not __debug__:
        parser.error("Do not use -O: frozen input-contract assertions must remain enabled.")
    sys.addaudithook(offline_guard)
    for name in list(os.environ):
        if any(token in name.upper() for token in ("API_KEY", "ACCESS_TOKEN", "AUTH_TOKEN")):
            os.environ.pop(name)
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    results = {}
    for name in ("rq1", "rq2", "r7", "s7"):
        module = importlib.import_module("reproduce." + name)
        target = out / name
        target.mkdir(exist_ok=True)
        results[name] = module.run(target)
        print(name + ": recomputation completed", flush=True)
    model_modules = sorted(set(sys.modules) & {"torch", "transformers", "sentence_transformers", "openai"})
    assert not model_modules, model_modules
    assert not NETWORK_ATTEMPTS, NETWORK_ATTEMPTS
    receipt = {
        "scope": "L1_SAVED_MATERIAL_RECOMPUTATION",
        "python": platform.python_version(),
        "numpy": importlib.import_module("numpy").__version__,
        "network_guard": "Python audit hook denies socket connect/DNS/bind",
        "network_attempt_events": NETWORK_ATTEMPTS,
        "model_provider_modules_loaded": model_modules,
        "models_or_providers_executed": False,
        "results": results,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    (out / "RUN_RECEIPT.json").write_text(json.dumps(receipt, indent=2, default=str) + "\n")
    print(json.dumps(receipt, indent=2, default=str))


if __name__ == "__main__":
    main()
