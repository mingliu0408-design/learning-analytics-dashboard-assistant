"""Metadata-only schema survey through the sealed F1 identity access guard."""
import json
import sys
from collections import Counter

from f1_common import ROOT
from f1_controlled_unblinding_guard import controlled_csv, controlled_json, controlled_jsonl


def schema(value, depth=0):
    if depth >= 4:
        return type(value).__name__
    if isinstance(value, dict):
        return {k: schema(v, depth+1) for k,v in value.items()}
    if isinstance(value, list):
        return {"list_count": len(value), "element_schema": schema(value[0], depth+1) if value else None}
    return type(value).__name__


for name in sys.argv[1:]:
    path = ROOT / name
    loader = {".csv": controlled_csv, ".jsonl": controlled_jsonl, ".json": controlled_json}[path.suffix]
    value = loader(path, "SCHEMA_INSPECTION", "f1_inspect_sources.py")
    report = {"source": name, "schema": schema(value)}
    if isinstance(value, list) and value and isinstance(value[0], dict):
        if "result" in value[0]:
            report["active_result_schema"] = schema(next((x["result"] for x in value if x.get("result") is not None), None))
            for nested in ["sources", "items"]:
                candidate = next((x["result"][nested][0] for x in value
                                  if isinstance(x.get("result"),dict) and x["result"].get(nested)), None)
                if candidate is not None:
                    report[nested + "_element_schema"] = schema(candidate)
        for key in ["status", "mode", "mode_id", "persistent_replay_eligible", "memory_class"]:
            if key in value[0]:
                report[key + "_counts"] = dict(Counter(x[key] for x in value))
    print(json.dumps(report, sort_keys=True))
