"""Native ML code isolation. Only JSON texts from the synthetic diagnostic parent.

This is local process IPC, with network disabled; no model extraction, routing,
generation, tuning, or alternative backend is implemented here.
"""
import contextlib
import json
from pathlib import Path
import sys
from common import disable_network, inherited_root
disable_network()
inherited_root()
from utils.c4_memory.c4_memory_retriever import FrozenLocalMPNetBackend

def main():
    model = Path(sys.argv[1]).resolve()
    opens = []
    def observe(event, args):
        if event == "open" and isinstance(args[0], str):
            p = Path(args[0]).resolve()
            if p.is_relative_to(model) and str(p) not in opens: opens.append(str(p))
    sys.addaudithook(observe)
    try:
        backend = FrozenLocalMPNetBackend(model, verify_hashes=True)
        with contextlib.redirect_stdout(sys.stderr):
            import torch
            torch.set_num_threads(1)
            torch.use_deterministic_algorithms(True)
            backend._load()
        print(json.dumps({"identity": dict(backend.identity), "model_open_events": opens,
            "actual_parameter_device": str(next(backend._encoder.parameters()).device)}), flush=True)
        for line in sys.stdin:
            message = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                vectors = backend.encode(message["texts"])
            print(json.dumps({"vectors": vectors}), flush=True)
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__ + ": " + str(exc)[:500]}), flush=True)
        return 1
    return 0

if __name__ == "__main__": sys.exit(main())
