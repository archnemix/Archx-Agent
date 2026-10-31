"""User reference archive inspection is bounded and never extracts executable paths."""
import io
import json
import tarfile
import zipfile

from scripts.retrieve_reference_ui import inspect as inspect_reference


def test_zip_snapshot_keeps_source_but_not_paths_secrets_or_dependencies(tmp_path):
    source = tmp_path / 'input.zip'
    with zipfile.ZipFile(source, 'w') as archive:
        for name in ['app/public/ui.mjs', '../escape.js', '/absolute.js', 'app/.env', 'app/node_modules/vendor.js']:
            archive.writestr(name, 'export const reference = true;')
    out = tmp_path / 'result'
    inspect_reference(source, out)
    with zipfile.ZipFile(out / 'source-snapshot.zip') as archive:
        assert archive.namelist() == ['app/public/ui.mjs']
    report = json.loads((out / 'report.json').read_text())
    assert report['entry_count'] == 5
    assert report['original_returned']
    assert (out / 'original-download.bin').read_bytes() == source.read_bytes()


def test_gzip_tar_handles_modules_without_following_archive_links(tmp_path):
    source = tmp_path / 'input.tar.gz'
    with tarfile.open(source, 'w:gz') as archive:
        raw = b'export const reference = true;'
        info = tarfile.TarInfo('app/public/theme.mjs')
        info.size = len(raw)
        archive.addfile(info, io.BytesIO(raw))
        link = tarfile.TarInfo('app/public/link.js')
        link.type = tarfile.SYMTYPE
        link.linkname = '/etc/passwd'
        archive.addfile(link)
    out = tmp_path / 'result'
    inspect_reference(source, out)
    with zipfile.ZipFile(out / 'source-snapshot.zip') as archive:
        assert archive.namelist() == ['app/public/theme.mjs']


def test_large_binary_original_is_not_returned(tmp_path):
    source = tmp_path / 'input.bin'
    source.write_bytes(b'\xff' * (2 * 1024 * 1024 + 1))
    out = tmp_path / 'result'
    inspect_reference(source, out)
    assert not (out / 'original-download.bin').exists()
    assert json.loads((out / 'report.json').read_text())['selected_source_files'] == []
