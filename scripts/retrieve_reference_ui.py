"""Retrieve a user-supplied UI reference on a runner; inspect bytes, never execute them."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile
import shutil
import zipfile


def inspect(download: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with download.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    report = {"bytes": download.stat().st_size, "sha256": digest}
    text_suffixes = {'.py', '.html', '.css', '.js', '.mjs', '.jsx', '.ts', '.tsx', '.json', '.md', '.txt', '.toml', '.yaml', '.yml'}
    ignored = {'node_modules', '.git', '.venv', 'venv', '__pycache__', 'site-packages', 'dist', 'build'}
    selected = []
    budget = 8 * 1024 * 1024
    with zipfile.ZipFile(output / 'source-snapshot.zip', 'w', zipfile.ZIP_DEFLATED) as target:
        if zipfile.is_zipfile(download):
            with zipfile.ZipFile(download) as archive:
                entries = archive.infolist()
                report['format'] = 'zip'
                report['entry_count'] = len(entries)
                report['inventory'] = [{"name": item.filename, "bytes": item.file_size} for item in entries[:10000]]
                for item in entries[:10000]:
                    name = PurePosixPath(item.filename.replace('\\', '/'))
                    if item.is_dir() or name.is_absolute() or '..' in name.parts or set(name.parts) & ignored:
                        continue
                    if any(part.startswith('.env') for part in name.parts) or name.suffix.lower() not in text_suffixes:
                        continue
                    if item.file_size > 512 * 1024 or item.file_size > budget:
                        continue
                    raw = archive.read(item)
                    try:
                        raw.decode('utf-8-sig')
                    except UnicodeDecodeError:
                        continue
                    target.writestr(str(name), raw)
                    budget -= len(raw)
                    selected.append(str(name))
        elif tarfile.is_tarfile(download):
            report['format'] = 'tar archive'
            with tarfile.open(download, 'r:*') as archive:
                entries = archive.getmembers()
                report['entry_count'] = len(entries)
                report['inventory'] = [{"name": item.name, "bytes": item.size} for item in entries[:10000]]
                for item in entries[:10000]:
                    name = PurePosixPath(item.name.replace('\\', '/'))
                    if not item.isfile() or name.is_absolute() or '..' in name.parts or set(name.parts) & ignored:
                        continue
                    if any(part.startswith('.env') for part in name.parts) or name.suffix.lower() not in text_suffixes:
                        continue
                    if item.size > 512 * 1024 or item.size > budget:
                        continue
                    with archive.extractfile(item) as source:
                        raw = source.read()
                    try:
                        raw.decode('utf-8-sig')
                    except UnicodeDecodeError:
                        continue
                    target.writestr(str(name), raw)
                    budget -= len(raw)
                    selected.append(str(name))
        else:
            with download.open('rb') as source:
                raw = source.read(512 * 1024)
            report['format'] = 'unrecognized archive or plain text'
            report['header_hex'] = raw[:40].hex()
            try:
                raw.decode('utf-8-sig')
                target.writestr('reference-source.txt', raw)
                selected.append('reference-source.txt')
            except UnicodeDecodeError:
                pass
    if download.stat().st_size <= 2 * 1024 * 1024:
        shutil.copyfile(download, output / 'original-download.bin')
        report['original_returned'] = True
    report['selected_source_files'] = selected
    report['scope'] = 'Bounded UTF-8 source snapshot; original returned only below 2 MiB for transport; no downloaded code executed by retrieval.'
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    import gdown  # Runner-only retrieval dependency, never an application dependency.
    destination = Path(sys.argv[1])
    output = Path(sys.argv[2])
    output.mkdir(parents=True, exist_ok=True)
    try:
        result = gdown.download(id='1zmn-G781kvJ3yRjmm8ENaCW4H7Wpz945', output=str(destination), quiet=False)
        if not result:
            raise RuntimeError('Drive did not return a downloadable file')
        inspect(destination, output)
    except Exception as exc:
        (output / 'report.json').write_text(json.dumps({'error': str(exc), 'scope': 'Download/inspection failed; no downloaded code executed.'}, indent=2), encoding='utf-8')
        raise
