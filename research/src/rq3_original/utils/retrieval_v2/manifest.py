"""Manifest loading and coverage auditing for Retrieval v2."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
import tempfile
from typing import Any, Iterable

from .config import DEFAULT_CONFIG, PROJECT_ROOT, RETRIEVAL_VERSION, is_privacy_excluded
from .models import ManifestRecordV2


KNOWN_EXCLUDED_SOURCES = (
    ("chat_history.csv", "private conversation history"),
    ("input/student_info.xlsx", "private student record"),
    (".streamlit/secrets.toml", "secret configuration"),
    ("System Data/Configuration/", "system configuration"),
    ("evaluation/outputs/", "frozen/generated evaluation output"),
)


def load_manifest(path: Path = DEFAULT_CONFIG.manifest_path) -> list[ManifestRecordV2]:
    """Load and validate the explicit corpus allowlist."""

    records: list[ManifestRecordV2] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid manifest JSON at line {line_no}: {exc}") from exc
            record = ManifestRecordV2.from_dict(raw)
            if record.document_id in seen:
                raise ValueError(f"Duplicate manifest document_id: {record.document_id}")
            excluded, reason = is_privacy_excluded(record.source_path)
            if excluded and record.enabled:
                raise ValueError(
                    f"Privacy-excluded path cannot be enabled: {record.source_path} ({reason})"
                )
            seen.add(record.document_id)
            records.append(record)
    return records


def manifest_hash(path: Path = DEFAULT_CONFIG.manifest_path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_path_for(record: ManifestRecordV2, project_root: Path = PROJECT_ROOT) -> Path:
    candidate = (project_root / record.source_path).resolve()
    root = project_root.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Manifest source escapes project root: {record.source_path}")
    return candidate


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_corpus_audit(
    records: Iterable[ManifestRecordV2] | None = None,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    """Build a deterministic coverage report without crawling the repository."""

    rows: list[dict[str, Any]] = []
    hashes: defaultdict[str, list[str]] = defaultdict(list)
    detected_week_counts: Counter[str] = Counter()
    supplied = list(records) if records is not None else load_manifest()
    for record in supplied:
        excluded, excluded_pattern = is_privacy_excluded(record.source_path)
        path = source_path_for(record, project_root)
        exists = path.is_file()
        source_hash = sha256_file(path) if exists else ""
        if source_hash:
            hashes[source_hash].append(record.document_id)
        actual_status = record.extraction_status if exists else "missing"
        extraction_method = "none"
        extraction_warnings: list[str] = []
        detected_weeks: list[str] = []
        if exists and record.enabled:
            from .ingestion import ingest_record

            extracted = ingest_record(record, project_root)
            actual_status = extracted.extraction_status
            extraction_method = extracted.extraction_method
            extraction_warnings = list(extracted.warnings)
            detected_weeks = sorted({section.week for section in extracted.sections if section.week})
            detected_week_counts.update(detected_weeks or ["unspecified"])
        rows.append(
            {
                **record.__dict__,
                "exists": exists,
                "source_hash": source_hash,
                "privacy_or_security_excluded": excluded or not record.enabled,
                "exclusion_reason": record.excluded_reason or excluded_pattern,
                "reported_extraction_status": actual_status,
                "extraction_method": extraction_method,
                "extraction_warnings": extraction_warnings,
                "detected_weeks": detected_weeks,
                "legacy_doc_unreadable": bool(
                    record.source_type == "legacy_doc" and actual_status == "unreadable"
                ),
            }
        )

    enabled_rows = [row for row in rows if row["enabled"]]
    material_counts = Counter(str(row["material_type"]) for row in enabled_rows)
    content_counts = Counter(str(row["content_level"]) for row in enabled_rows)
    extraction_counts = Counter(str(row["reported_extraction_status"]) for row in enabled_rows)
    duplicate_hashes = {
        digest: ids for digest, ids in sorted(hashes.items()) if len(ids) > 1
    }
    return {
        "retrieval_version": RETRIEVAL_VERSION,
        "manifest_hash": manifest_hash(),
        "total_manifest_documents": len(rows),
        "enabled_documents": len(enabled_rows),
        "existing_source_files": sum(bool(row["exists"]) for row in enabled_rows),
        "missing_source_files": sum(not row["exists"] for row in enabled_rows),
        "extraction_status_counts": dict(sorted(extraction_counts.items())),
        "content_level_counts": dict(sorted(content_counts.items())),
        "coverage_by_week": dict(sorted(detected_week_counts.items())),
        "coverage_by_material_type": dict(sorted(material_counts.items())),
        "title_or_citation_only_sources": [
            row["document_id"]
            for row in enabled_rows
            if row["content_level"] in {"title_and_metadata", "citation_only"}
        ],
        "unreadable_legacy_doc_files": [
            row["source_path"] for row in enabled_rows if row["legacy_doc_unreadable"]
        ],
        "duplicate_source_hashes": duplicate_hashes,
        "sources_excluded_for_privacy_or_security": [
            {
                "source_path": row["source_path"],
                "reason": row["exclusion_reason"] or "manifest-disabled",
                "exists": row["exists"],
            }
            for row in rows
            if row["privacy_or_security_excluded"]
        ] + [
            {
                "source_path": source,
                "reason": reason,
                "exists": (project_root / source.rstrip("/")).exists(),
            }
            for source, reason in KNOWN_EXCLUDED_SOURCES
        ],
        "privacy_exclusion_policy": [
            "chat_history.csv",
            "API keys and .env files",
            "secrets.toml",
            "System Data/Configuration",
            "evaluation outputs and human annotations",
            "private student records",
            "__MACOSX, .DS_Store, and cache files",
        ],
        "documents": rows,
    }


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_corpus_audit(
    audit: dict[str, Any], output_dir: Path = DEFAULT_CONFIG.output_dir
) -> tuple[Path, Path, Path]:
    """Write JSON, CSV, and Markdown audit artifacts atomically."""

    json_path = output_dir / "corpus_coverage_audit_v2.json"
    csv_path = output_dir / "corpus_coverage_audit_v2.csv"
    md_path = output_dir / "corpus_coverage_audit_v2.md"
    _atomic_text(json_path, json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    fieldnames = list(audit["documents"][0]) if audit["documents"] else []
    lines: list[str] = []
    if fieldnames:
        import io

        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for row in audit["documents"]:
            writer.writerow(row)
        lines.append(buffer.getvalue())
    _atomic_text(csv_path, "".join(lines))

    markdown = [
        "# Corpus coverage audit v2",
        "",
        "Post-freeze experimental retrieval extension.",
        "",
        f"- Retrieval version: `{audit['retrieval_version']}`",
        f"- Total manifest documents: {audit['total_manifest_documents']}",
        f"- Enabled documents: {audit['enabled_documents']}",
        f"- Existing source files: {audit['existing_source_files']}",
        f"- Missing source files: {audit['missing_source_files']}",
        f"- Content levels: `{json.dumps(audit['content_level_counts'], sort_keys=True)}`",
        f"- Extraction statuses: `{json.dumps(audit['extraction_status_counts'], sort_keys=True)}`",
        f"- Coverage by material type: `{json.dumps(audit['coverage_by_material_type'], sort_keys=True)}`",
        f"- Duplicate source hashes: {len(audit['duplicate_source_hashes'])}",
        f"- Unreadable legacy DOC files: {len(audit['unreadable_legacy_doc_files'])}",
        "",
        "## Allowlisted documents",
        "",
        "| Document | Source | Exists | Material | Content level | Extraction status |",
        "|---|---|---:|---|---|---|",
    ]
    for row in audit["documents"]:
        markdown.append(
            f"| {row['document_id']} | `{row['source_path']}` | {str(row['exists']).lower()} "
            f"| {row['material_type']} | {row['content_level']} | {row['reported_extraction_status']} |"
        )
    markdown.extend(
        [
            "",
            "## Privacy boundary",
            "",
            "The index is built from the manifest allowlist only. Chat history, secrets, configuration, "
            "evaluation outputs, annotations, private student data, and cache/system files are not indexed.",
        ]
    )
    _atomic_text(md_path, "\n".join(markdown) + "\n")
    return json_path, csv_path, md_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Retrieval v2 corpus manifest tools")
    parser.add_argument("command", choices=["audit"])
    args = parser.parse_args(argv)
    if args.command == "audit":
        audit = build_corpus_audit()
        paths = write_corpus_audit(audit)
        print(json.dumps({"summary": {k: audit[k] for k in (
            "total_manifest_documents", "enabled_documents", "existing_source_files",
            "missing_source_files", "extraction_status_counts", "content_level_counts"
        )}, "outputs": [str(path.relative_to(PROJECT_ROOT)) for path in paths]}, indent=2))


if __name__ == "__main__":
    main()
