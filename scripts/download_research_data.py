#!/usr/bin/env python3
"""Download the published LAD research archive with hash and safe extraction checks."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import urllib.request
from urllib.parse import urlparse
import zipfile

MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_TOTAL_BYTES = 4 * 1024**3
MAX_MEMBER_BYTES = 512 * 1024**2
MAX_MEMBERS = 50000
MAX_COMPRESSION_RATIO = 2000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def members_checked(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS:
        raise ValueError('Archive contains too many members')
    seen: set[str] = set()
    total = 0
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        mode = info.external_attr >> 16
        if (not name or path.is_absolute() or '..' in path.parts or '\\' in name
                or '\x00' in name or ':' in path.parts[0]):
            raise ValueError('Unsafe archive path')
        canonical = '/'.join(path.parts).casefold()
        if canonical in seen:
            raise ValueError('Duplicate or case-colliding archive path')
        seen.add(canonical)
        if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ValueError('Archive contains a link or special file')
        if info.flag_bits & 1:
            raise ValueError('Encrypted archive is unsupported')
        if info.file_size > MAX_MEMBER_BYTES:
            raise ValueError('Archive member is unexpectedly large')
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise ValueError('Archive expands beyond allowed total size')
        if info.file_size / max(1, info.compress_size) > MAX_COMPRESSION_RATIO:
            raise ValueError('Archive has an abnormal compression ratio')
    return infos


def safe_extract(archive_path: Path, destination: Path) -> dict[str, int]:
    """Preflight the entire ZIP and existing paths, then publish without overwrite."""
    destination = destination.absolute()
    if destination.is_symlink():
        raise ValueError('Destination must not be a symlink')
    for parent in [destination.parent, *destination.parents]:
        if parent.is_symlink():
            raise ValueError('Destination parent must not be a symlink')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        infos = members_checked(archive)
        if archive.testzip() is not None:
            raise ValueError('Archive CRC check failed')
        with tempfile.TemporaryDirectory(prefix='lad-data-', dir=destination.parent) as work:
            staged = Path(work) / 'contents'
            staged.mkdir()
            for info in infos:
                target = staged / PurePosixPath(info.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                if info.is_dir():
                    target.mkdir(exist_ok=True)
                    continue
                with archive.open(info) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                if target.stat().st_size != info.file_size:
                    raise ValueError('Extracted member length mismatch')
            manifest = staged / 'PUBLIC_FILE_MANIFEST.json'
            if manifest.exists():
                entries = json.loads(manifest.read_text(encoding='utf-8'))['files']
                for entry in entries:
                    rel = PurePosixPath(entry['destination'])
                    if rel.is_absolute() or '..' in rel.parts:
                        raise ValueError('Unsafe manifest member')
                    path = staged / rel
                    if not path.is_file() or sha256(path) != entry['published_sha256']:
                        raise ValueError('Published per-file hash mismatch')
            if not destination.exists():
                staged.rename(destination)
                return {'written': sum(not info.is_dir() for info in infos), 'identical': 0}
            if not destination.is_dir():
                raise ValueError('Destination is not a directory')
            # Preflight every existing path before writing any new destination file.
            files = [path for path in staged.rglob('*') if path.is_file()]
            same = 0
            for source in files:
                target = destination / source.relative_to(staged)
                for parent in [target.parent, *target.parents]:
                    if parent == destination.parent:
                        break
                    if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                        raise ValueError('Unsafe existing destination parent')
                if target.is_symlink():
                    raise ValueError('Existing destination is a symlink')
                if target.exists():
                    if not target.is_file() or sha256(target) != sha256(source):
                        raise FileExistsError('Refusing to overwrite existing different data')
                    same += 1
            written = 0
            for source in files:
                target = destination / source.relative_to(staged)
                if target.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open('rb') as source_handle, target.open('xb') as target_handle:
                    shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
                written += 1
            return {'written': written, 'identical': same}


def download(url: str, expected_sha256: str, destination: Path) -> dict[str, int]:
    if urlparse(url).scheme != 'https':
        raise ValueError('A public HTTPS URL is required')
    if len(expected_sha256) != 64 or any(c not in '0123456789abcdef' for c in expected_sha256.lower()):
        raise ValueError('A full SHA-256 is required')
    with tempfile.TemporaryDirectory(prefix='lad-download-') as work:
        archive_path = Path(work) / 'research.zip'
        request = urllib.request.Request(url, headers={'User-Agent': 'LAD-research-data-downloader/1'})
        with urllib.request.urlopen(request, timeout=60) as response, archive_path.open('xb') as output:
            if urlparse(response.geturl()).scheme != 'https':
                raise ValueError('Insecure redirect refused')
            announced = response.headers.get('Content-Length')
            if announced and int(announced) > MAX_ARCHIVE_BYTES:
                raise ValueError('Download exceeds allowed archive size')
            size = 0
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > MAX_ARCHIVE_BYTES:
                    raise ValueError('Download exceeds allowed archive size')
                output.write(block)
        if sha256(archive_path) != expected_sha256.lower():
            raise ValueError('Archive SHA-256 mismatch')
        return safe_extract(archive_path, destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', help='Public GitHub Release download URL')
    parser.add_argument('--sha256', help='Expected archive SHA-256')
    parser.add_argument('--destination', type=Path, default=Path('research/released_data'))
    args = parser.parse_args()
    url, digest = args.url, args.sha256
    if not url or not digest:
        manifest_path = Path(__file__).resolve().parents[1] / 'data/manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        assets = manifest.get('release_assets', [])
        if not assets or not assets[0].get('url'):
            parser.error('Published asset URL is not recorded; provide both --url and --sha256')
        url, digest = assets[0]['url'], assets[0]['sha256']
    if bool(args.url) != bool(args.sha256):
        parser.error('--url and --sha256 must be provided together')
    print(json.dumps(download(url, digest, args.destination)))

if __name__ == '__main__':
    main()
