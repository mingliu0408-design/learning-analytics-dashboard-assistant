#!/usr/bin/env python3
"""Scan publication candidates and archives without emitting credential values.

Repo mode scans tracked and non-ignored candidate files, excluding Git internals.
Explicit paths are scanned in full, including nested ZIP/Office archives.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict, dataclass
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import zipfile

FORBIDDEN_PARTS = {'.git', '.venv', 'venv', 'env', '__pycache__', 'node_modules',
                   '.pytest_cache', '.mypy_cache', '.ruff_cache', '.conda', 'site-packages',
                   '.DS_Store', '__MACOSX'}
FORBIDDEN_SUFFIXES = {'.ttf', '.otf', '.woff', '.woff2', '.ttc', '.p12', '.pfx',
                      '.key', '.pem', '.pyc', '.pyo'}
IDENTITY_NAMES = re.compile(r'(?:^|[_ .-])(passport|identity[_ -]?card|id[_ -]?card|signed|signature|身份证|护照|签名)(?:$|[_ .-])', re.I)
TOKEN_PATTERNS = (
    ('PRIVATE_KEY', re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----')),
    ('GITHUB_TOKEN', re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b')),
    ('PROVIDER_KEY', re.compile(rb'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b')),
    ('AWS_ACCESS_KEY', re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b')),
    ('AUTH_HEADER', re.compile(rb'(?i)(?:authorization[\"\x27]?\s*[:=]\s*[\"\x27]?bearer\s+)[A-Za-z0-9._-]{20,}')),
)
CREDENTIAL_VALUE = re.compile(rb'''(?ix)(?:["']?)(api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|hmac[_-]?(?:secret|key)|password|private[_-]?key)(?:["']?)\s*[:=]\s*["']([^"'\r\n]{16,})["']''')
PLACEHOLDER = re.compile(rb'(?i)(?:example|placeholder|your[_ -]|replace[_ -]|synthetic|dummy|offline[_ -]|mock[_ -]|fixture[_ -]|test[_ -]|redacted|removed|changeme|not[_ -]|must[_ -]|none|os\.|getenv|<|\$\{|TODO)')
MAX_MEMBER = 2 * 1024**3
MAX_TOTAL = 8 * 1024**3
MAX_DEPTH = 4

@dataclass(frozen=True)
class Finding:
    path: str
    code: str

def unsafe_member(name: str) -> bool:
    value = name.replace('\\', '/')
    path = PurePosixPath(value)
    return (not value or value.startswith('/') or bool(re.match(r'^[A-Za-z]:', value))
            or '..' in path.parts or '\x00' in value)

def path_findings(name: str) -> list[Finding]:
    parts = PurePosixPath(name.replace('\\', '/')).parts
    leaf = parts[-1] if parts else ''
    found = []
    if any(part in FORBIDDEN_PARTS for part in parts):
        found.append(Finding(name, 'FORBIDDEN_DIRECTORY_OR_CACHE'))
    if Path(leaf).suffix.lower() in FORBIDDEN_SUFFIXES:
        found.append(Finding(name, 'FONT_OR_AUTHENTICATION_OR_CACHE_FILE'))
    if leaf == 'secrets.toml' or (leaf == '.env' or leaf.startswith('.env.') and not leaf.endswith(('example', 'sample', 'template'))):
        found.append(Finding(name, 'REAL_SECRET_CONFIGURATION'))
    if IDENTITY_NAMES.search(Path(leaf).stem):
        found.append(Finding(name, 'SIGNATURE_OR_IDENTITY_ATTACHMENT'))
    return found

def content_findings(name: str, payload: bytes) -> list[Finding]:
    found = []
    for code, pattern in TOKEN_PATTERNS:
        if pattern.search(payload):
            found.append(Finding(name, code))
    for match in CREDENTIAL_VALUE.finditer(payload):
        value = match.group(2)
        if not PLACEHOLDER.search(value) and re.search(rb'[A-Za-z]', value) and re.search(rb'[0-9+/=_-]', value):
            found.append(Finding(name, 'LITERAL_CREDENTIAL_FIELD'))
            break
    return found

def scan_bytes(name: str, payload: bytes, depth: int = 0) -> list[Finding]:
    found = path_findings(name) + content_findings(name, payload)
    if zipfile.is_zipfile(io.BytesIO(payload)):
        if depth >= MAX_DEPTH:
            return found + [Finding(name, 'ARCHIVE_DEPTH_LIMIT')]
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                seen = set()
                total = 0
                for member in archive.infolist():
                    child = name + '!/' + member.filename
                    if unsafe_member(member.filename):
                        found.append(Finding(child, 'UNSAFE_ARCHIVE_PATH'))
                        continue
                    normalized = str(PurePosixPath(member.filename.replace('\\', '/')))
                    if normalized in seen:
                        found.append(Finding(child, 'DUPLICATE_ARCHIVE_PATH'))
                        continue
                    seen.add(normalized)
                    if stat.S_ISLNK(member.external_attr >> 16):
                        found.append(Finding(child, 'ARCHIVE_SYMLINK'))
                        continue
                    if member.flag_bits & 1:
                        found.append(Finding(child, 'ENCRYPTED_UNINSPECTABLE_ARCHIVE'))
                        continue
                    total += member.file_size
                    if member.file_size > MAX_MEMBER or total > MAX_TOTAL:
                        found.append(Finding(child, 'ARCHIVE_SIZE_LIMIT'))
                        continue
                    if member.is_dir():
                        found.extend(path_findings(child))
                        continue
                    data = archive.read(member)
                    found.extend(scan_bytes(child, data, depth + 1))
        except (OSError, zipfile.BadZipFile, RuntimeError):
            found.append(Finding(name, 'ARCHIVE_READ_OR_CRC_FAILURE'))
    return found

def scan_path(path: Path, *, label: str | None = None) -> tuple[int, list[Finding]]:
    name = label or str(path)
    if path.is_symlink():
        return 1, [Finding(name, 'CANDIDATE_SYMLINK')]
    if path.is_dir():
        count, found = 0, []
        for child in sorted(path.rglob('*')):
            if child.is_file() or child.is_symlink():
                n, result = scan_path(child, label=name + '/' + child.relative_to(path).as_posix())
                count += n
                found.extend(result)
        return count, found
    try:
        return 1, scan_bytes(name, path.read_bytes())
    except OSError:
        return 1, [Finding(name, 'UNREADABLE_CANDIDATE')]

def repo_candidates(root: Path) -> list[Path]:
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], check=True, capture_output=True)
    return [root / p.decode('utf-8', errors='strict') for p in result.stdout.split(b'\x00') if p]

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='*', type=Path)
    parser.add_argument('--repo', type=Path)
    parser.add_argument('--output', type=Path, help='Optional JSON report, containing paths and codes only')
    args = parser.parse_args(argv)
    candidates = args.paths + (repo_candidates(args.repo) if args.repo else [])
    if not candidates:
        parser.error('provide --repo or explicit candidate paths')
    count, findings = 0, []
    for path in dict.fromkeys(candidates):
        label = str(path.relative_to(args.repo)) if args.repo and path.is_relative_to(args.repo) else path.name
        n, found = scan_path(path, label=label)
        count += n
        findings.extend(found)
    findings = sorted(set(findings), key=lambda item: (item.path, item.code))
    report = {'status': 'PASS' if not findings else 'FAIL', 'candidate_files': count,
              'finding_count': len(findings), 'findings': [asdict(f) for f in findings],
              'limitation': 'Pattern and archive policy scan; manual candidate review remains necessary.'}
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(serialized + '\n', encoding='utf-8')
    print(serialized)
    return 0 if not findings else 1

if __name__ == '__main__':
    sys.exit(main())
