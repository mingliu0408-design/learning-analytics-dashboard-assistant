"""CLI for the one and only authorized Stage 5E real scoring invocation."""

from __future__ import annotations

import json

from .scoring import run_one_time_final_scoring


def main() -> int:
    result = run_one_time_final_scoring()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
