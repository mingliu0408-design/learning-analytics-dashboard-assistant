"""Build the exact-allowlist RQ2-V2 Stage 1 Track A review ZIP."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parents[2]
DEFAULT_OUTPUT = Path(
    "/Users/liuming/Downloads/RQ2_V2_STAGE_1_TRACK_A_R1_DATASET_PACKETS_REVIEW_2026-08-30.zip"
)
ARCHIVE_ROOT = "RQ2_V2_STAGE_1_TRACK_A_R1_DATASET_PACKETS_REVIEW_2026-08-30"
ALLOWED_FILES = (
    "README.md",
    "scenario_blueprints.jsonl",
    "writer_packet_A.csv",
    "writer_packet_B.csv",
    "HUMAN_WRITER_GUIDE.md",
    "SCENARIO_CONTENT_AUDIT.md",
    "build_writer_packets.py",
    "validate_track_a.py",
    "test_track_a.py",
    "build_review_zip.py",
    "STATUS.md",
)
SECRET_PATTERNS = (
    b"OPENAI_" + b"API_KEY",
    b"AWS_SECRET_" + b"ACCESS_KEY",
    b"PRIVATE " + b"KEY-----",
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, date_time=(2026, 8, 30, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def build_review_zip(output: Path = DEFAULT_OUTPUT) -> dict[str, object]:
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite review ZIP: {output}")
    members: list[str] = []
    with ZipFile(output, mode="x", compression=ZIP_DEFLATED) as archive:
        for filename in ALLOWED_FILES:
            path = PACKAGE_ROOT / filename
            if not path.is_file() or path.is_symlink():
                raise FileNotFoundError(f"missing review source file: {path}")
            value = path.read_bytes()
            if any(pattern in value for pattern in SECRET_PATTERNS):
                raise ValueError(f"possible secret marker in review source: {path}")
            relative = path.relative_to(PROJECT_ROOT).as_posix()
            member = f"{ARCHIVE_ROOT}/{relative}"
            archive.writestr(_zip_info(member), value)
            members.append(member)
    return {
        "status": "PASS",
        "output": str(output),
        "member_count": len(members),
        "members": members,
        "sha256": _sha256_bytes(output.read_bytes()),
    }


def main() -> int:
    print(json.dumps(build_review_zip(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
