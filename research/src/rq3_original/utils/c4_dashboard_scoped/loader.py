"""Strict explicit CSV source loader. Never calls the legacy synthetic fallback.

Manifests, identity rosters, course permissions and coverage declarations are
trusted DI inputs. This module does not discover people or infer authorisation.
Binary stores require a separately verified conversion; no pickle execution here.
"""
from dataclasses import replace
from pathlib import Path
import csv
import hashlib

from .scope import Snapshot, SourceSpec, ScopeError


def load_csv_snapshot(*, version, paths, specs, roster, calendars=None,
                      source_root, origin="LIVE", allow_synthetic=False):
    root = Path(source_root).resolve()
    if origin == "SYNTHETIC" and not allow_synthetic:
        raise ScopeError("Synthetic input requires explicit test opt-in")
    tables, verified = {}, {}
    for name, spec in specs.items():
        supplied = paths.get(name)
        if not supplied:
            tables[name] = None
            verified[name] = replace(spec, status="SOURCE_UNAVAILABLE")
            continue
        path = Path(supplied).resolve()
        if not path.is_relative_to(root):
            raise ScopeError("Source is outside its authorised root")
        if not path.is_file():
            tables[name] = None
            verified[name] = replace(spec, status="SOURCE_UNAVAILABLE")
            continue
        if path.suffix.lower() != ".csv":
            tables[name] = None
            verified[name] = replace(spec, status="BINARY_SOURCE_NOT_SAFELY_READABLE")
            continue
        data = path.read_bytes()
        if not spec.source_sha256 or hashlib.sha256(data).hexdigest() != spec.source_sha256:
            raise ScopeError("Source hash does not match its trusted manifest")
        import io
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
        if tuple(reader.fieldnames or ()) != spec.columns:
            raise ScopeError("Source headers do not match the versioned contract")
        tables[name] = tuple(dict(r) for r in reader)
        verified[name] = spec
    return Snapshot(version, tables, verified, roster, calendars or {}, origin)
