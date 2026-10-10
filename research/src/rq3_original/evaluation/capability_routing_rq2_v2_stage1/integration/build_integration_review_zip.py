"""Build the allowlisted RQ2-V2 Stage 1 integration review archive."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


PACKAGE_ROOT = Path(__file__).resolve().parent
STAGE1_ROOT = PACKAGE_ROOT.parent
PROJECT_ROOT = PACKAGE_ROOT.parents[2]
STAGE0_ROOT = PROJECT_ROOT / "evaluation" / "capability_routing_rq2_v2_stage0"
DEFAULT_OUTPUT = Path(
    "/Users/liuming/Downloads/RQ2_V2_STAGE_1_INTEGRATION_REVIEW_2026-08-30.zip"
)
ARCHIVE_ROOT = "RQ2_V2_STAGE_1_INTEGRATION_REVIEW_2026-08-30"
EXPECTED_BRANCH = "research/rq2-v2-stage1-integration"
STARTING_HEAD = "ad43bd4addcb9a257690ca81e1185a6a0d1b5bb7"
EXPECTED_INTEGRATION_SUBJECT = (
    "RQ2-V2 Stage 1: integrate dataset and router implementations"
)
SAFE_SUFFIXES = frozenset({".py", ".md", ".json", ".jsonl", ".csv", ".txt"})
MAX_FILE_BYTES = 2 * 1024 * 1024
TEST_REPORT_PATH = PACKAGE_ROOT / "INTEGRATION_TEST_REPORT.json"
STAGE0_REVIEW_FILES = (
    STAGE0_ROOT / "__init__.py",
    STAGE0_ROOT / "contracts.py",
    STAGE0_ROOT / "interfaces.py",
    STAGE0_ROOT / "config" / "rq2_v2_contract_v1.json",
    STAGE0_ROOT / "schemas" / "case_v1.schema.json",
    STAGE0_ROOT / "schemas" / "prediction_v1.schema.json",
)
AUTHORIZED_COMMITS = (
    (
        "493777f0392928cfd5c2376a089dd16424578ef6",
        "RQ2-V2 Stage 1A: add controlled scenario and writer packets",
    ),
    (
        "46de7e0a80d56d2a4ff8cb5de39ff8079518678a",
        "RQ2-V2 Stage 1A-R1: repair scenario leakage and writer packets",
    ),
    (
        "0fecccdff70362134ead5c0786313a844471f664",
        "RQ2-V2 Stage 1B: implement rule and legacy intent baselines",
    ),
    (
        "1cdd4ed552860c6b1c1a67bc9716904681a6555f",
        "RQ2-V2 Stage 1B-R1: remove privileged state features from B0",
    ),
    (
        "df997b2083ccac4d951570dfdeb8cf908a49c1ab",
        "RQ2-V2 Stage 1C: implement prototype and OvR routers",
    ),
    (
        "2ac4a0d6dcb331e9d066b55d2f06e3e7db961525",
        "RQ2-V2 Stage 1C-R1: remove privileged features and repair learning curves",
    ),
    (
        "a079d910e27c4f348cbe58141a3b260bf85497ea",
        "RQ2-V2 Stage 1D: add offline LLM and hybrid harnesses",
    ),
    (
        "fbf8f923193bb78a48f33a0c32d85fabd4c232c2",
        "RQ2-V2 Stage 1D-R1: remove privileged state fields from LLM routing",
    ),
)
SECRET_PATTERNS = (
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
EMAIL_PATTERN = re.compile(
    rb"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE
)


class IntegrationReviewZipError(RuntimeError):
    """Raised when the final review archive cannot be built safely."""


def _git(*args: str, text: bool = True) -> str | bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=text,
    )
    return result.stdout


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_source_file(path: Path) -> bool:
    return (
        path.is_file()
        and not path.is_symlink()
        and path.suffix in SAFE_SUFFIXES
        and "__pycache__" not in path.parts
        and not path.name.startswith(".")
    )


def collect_review_files() -> list[Path]:
    files = [path for path in STAGE1_ROOT.rglob("*") if _safe_source_file(path)]
    files.extend(path for path in STAGE0_REVIEW_FILES if _safe_source_file(path))
    unique = sorted(set(files), key=lambda path: path.relative_to(PROJECT_ROOT).as_posix())
    if not unique:
        raise IntegrationReviewZipError("review allowlist is empty")
    for path in unique:
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise IntegrationReviewZipError(f"cannot inspect review file: {path}") from exc
        if size > MAX_FILE_BYTES:
            raise IntegrationReviewZipError(f"review file exceeds size limit: {path}")
    return unique


def _verify_writer_packets_empty() -> dict[str, int]:
    counts: dict[str, int] = {}
    for writer in ("A", "B"):
        path = STAGE1_ROOT / "track_a_dataset" / f"writer_packet_{writer}.csv"
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if len(rows) != 54:
            raise IntegrationReviewZipError(
                f"writer packet {writer} must contain exactly 54 rows"
            )
        if any(row.get("natural_student_query") != "" for row in rows):
            raise IntegrationReviewZipError(
                f"writer packet {writer} contains a non-empty query"
            )
        counts[writer] = len(rows)
    return counts


def _verify_safe_content(files: Iterable[Path]) -> None:
    for path in files:
        payload = path.read_bytes()
        if any(pattern.search(payload) for pattern in SECRET_PATTERNS):
            raise IntegrationReviewZipError(f"possible secret detected: {path}")
        if EMAIL_PATTERN.search(payload):
            raise IntegrationReviewZipError(f"possible email/PII detected: {path}")


def _commit_patch(commit: str) -> bytes:
    return _git("diff", "--binary", f"{commit}^", commit, text=False)  # type: ignore[return-value]


def _integrated_commit_map() -> list[dict[str, str]]:
    history_text = _git(
        "log", "--format=%H%x09%s", "--reverse", f"{STARTING_HEAD}..HEAD"
    )
    assert isinstance(history_text, str)
    history = [line.split("\t", 1) for line in history_text.splitlines() if line]
    by_subject: dict[str, list[str]] = {}
    for commit, subject in history:
        by_subject.setdefault(subject, []).append(commit)

    mappings: list[dict[str, str]] = []
    for source, subject in AUTHORIZED_COMMITS:
        integrated = by_subject.get(subject, [])
        if len(integrated) != 1:
            raise IntegrationReviewZipError(
                f"expected one integrated commit for {subject!r}, observed {integrated}"
            )
        integrated_commit = integrated[0]
        if _commit_patch(source) != _commit_patch(integrated_commit):
            raise IntegrationReviewZipError(
                f"integrated patch differs from authorized source commit: {source}"
            )
        mappings.append(
            {
                "authorized_source_commit": source,
                "integrated_commit": integrated_commit,
                "subject": subject,
                "patch_sha256": _sha256_bytes(_commit_patch(source)),
            }
        )
    return mappings


def _git_state(*, require_clean: bool) -> dict[str, Any]:
    branch = str(_git("branch", "--show-current")).strip()
    head = str(_git("rev-parse", "HEAD")).strip()
    status = str(_git("status", "--short"))
    subject = str(_git("show", "-s", "--format=%s", "HEAD")).strip()
    if branch != EXPECTED_BRANCH:
        raise IntegrationReviewZipError(
            f"integration branch mismatch: expected {EXPECTED_BRANCH}, observed {branch}"
        )
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", STARTING_HEAD, head],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
    )
    if require_clean and status:
        raise IntegrationReviewZipError("final review ZIP requires a clean working tree")
    if require_clean and subject != EXPECTED_INTEGRATION_SUBJECT:
        raise IntegrationReviewZipError(
            f"final integration commit subject mismatch: {subject!r}"
        )
    return {
        "working_directory": str(PROJECT_ROOT),
        "branch": branch,
        "starting_head": STARTING_HEAD,
        "final_integration_head": head,
        "final_integration_subject": subject,
        "working_tree_clean": not bool(status),
        "status_short": status.splitlines(),
        "authorized_commits": _integrated_commit_map(),
        "cherry_pick_conflicts": [],
    }


def _git_report_text(state: dict[str, Any]) -> str:
    lines = [
        "RQ2-V2 Stage 1 integration Git report",
        "",
        "Status: PASS",
        f"Working directory: {state['working_directory']}",
        f"Branch: {state['branch']}",
        f"Starting HEAD: {state['starting_head']}",
        f"Final integration HEAD: {state['final_integration_head']}",
        f"Integration commit: {state['final_integration_subject']}",
        f"Working tree clean: {str(state['working_tree_clean']).lower()}",
        "Cherry-pick conflicts: none",
        "",
        "Authorized source commits and integrated commits:",
    ]
    for item in state["authorized_commits"]:
        lines.append(
            f"- {item['authorized_source_commit']} -> {item['integrated_commit']}  "
            f"{item['subject']}"
        )
    return "\n".join(lines) + "\n"


def _zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, date_time=(2026, 8, 30, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def build_review_zip(
    output: str | Path = DEFAULT_OUTPUT,
    *,
    require_clean: bool = True,
) -> dict[str, Any]:
    target = Path(output).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing review ZIP: {target}")
    if not target.parent.is_dir():
        raise IntegrationReviewZipError(f"ZIP parent directory is unavailable: {target.parent}")
    if not TEST_REPORT_PATH.is_file():
        raise IntegrationReviewZipError(
            "INTEGRATION_TEST_REPORT.json must exist before the final review ZIP"
        )

    test_report = _load_json_report(TEST_REPORT_PATH)
    if test_report.get("status") != "PASS":
        raise IntegrationReviewZipError("integration test report is not PASS")
    files = collect_review_files()
    _verify_safe_content(files)
    writer_counts = _verify_writer_packets_empty()
    git_state = _git_state(require_clean=require_clean)
    git_report = _git_report_text(git_state).encode("utf-8")

    entries = []
    for path in files:
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        entries.append(
            {
                "path": relative,
                "sha256": _sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    manifest = {
        "schema_version": "rq2-v2-stage1-integration-review-manifest-v1",
        "scope": "RQ2_V2_STAGE_1_INTEGRATION_REVIEW_ONLY",
        "status": "PASS",
        "git": git_state,
        "source_files": entries,
        "source_file_count": len(entries),
        "writer_packet_rows": writer_counts,
        "writer_query_cells_filled": 0,
        "primary_feature_profile": "R2V2_PRIMARY_SEMANTIC_INPUT_V1",
        "b1_mapping_frozen": False,
        "b4_final_few_shots_selected": False,
        "b2_b3_p1_final_thresholds_selected": False,
        "network_calls": 0,
        "real_provider_calls": 0,
        "contains_raw_restricted_student_data": False,
        "contains_pii": False,
        "contains_secrets_or_api_keys": False,
        "contains_external_provider_outputs": False,
        "contains_large_model_weights": False,
        "contains_git_ignored_c0_or_mpnet_assets": False,
        "contains_unrelated_repository_files": False,
        "integration_test_report_sha256": _sha256_file(TEST_REPORT_PATH),
    }
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")

    with ZipFile(target, "x", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(PROJECT_ROOT).as_posix()
            archive.writestr(
                _zip_info(f"{ARCHIVE_ROOT}/{relative}"), path.read_bytes()
            )
        archive.writestr(
            _zip_info(f"{ARCHIVE_ROOT}/GIT_COMMIT_REPORT.txt"), git_report
        )
        archive.writestr(
            _zip_info(f"{ARCHIVE_ROOT}/REVIEW_MANIFEST.json"), manifest_bytes
        )

    with ZipFile(target) as archive:
        bad_member = archive.testzip()
        names = archive.namelist()
        if bad_member is not None:
            raise IntegrationReviewZipError(f"ZIP CRC failure: {bad_member}")
        if any(name.startswith("/") or ".." in Path(name).parts for name in names):
            raise IntegrationReviewZipError("ZIP contains an unsafe member path")
        if len(names) != len(files) + 2 or len(names) != len(set(names)):
            raise IntegrationReviewZipError("ZIP member count or uniqueness check failed")

    return {
        "status": "PASS",
        "output": str(target),
        "sha256": _sha256_file(target),
        "member_count": len(files) + 2,
        "source_file_count": len(files),
        "final_integration_head": git_state["final_integration_head"],
        "authorized_commit_count": len(git_state["authorized_commits"]),
        "writer_packet_rows": writer_counts,
        "network_calls": 0,
        "real_provider_calls": 0,
    }


def _load_json_report(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrationReviewZipError(f"cannot load integration test report: {path}") from exc
    if not isinstance(value, dict):
        raise IntegrationReviewZipError("integration test report must be a JSON object")
    return value


def main() -> int:
    try:
        report = build_review_zip()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error": f"{type(exc).__name__}: {exc}",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
