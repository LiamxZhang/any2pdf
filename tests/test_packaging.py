import hashlib
import io
import tarfile
from pathlib import Path

import pytest

from scripts.fetch_engines import verify_digest, extract_tar, libreoffice_asset
import scripts.fetch_engines as engines
from scripts.build import split_asset
import scripts.build as build


def test_checksum_rejects_corrupt_cache(tmp_path):
    path = tmp_path / 'download'
    path.write_bytes(b'original')
    verify_digest(path, hashlib.sha256(b'original').hexdigest())
    with pytest.raises(ValueError, match='checksum'):
        verify_digest(path, '0' * 64)


def test_archive_rejects_path_escape(tmp_path):
    path = tmp_path / 'bad.tar.gz'
    with tarfile.open(path, 'w:gz') as archive:
        info = tarfile.TarInfo('../escape')
        info.size = 3
        archive.addfile(info, io.BytesIO(b'bad'))
    with pytest.raises((ValueError, tarfile.FilterError)):
        extract_tar(path, tmp_path / 'extract')
    assert not (tmp_path / 'escape').exists()


def test_native_libreoffice_assets_are_pinned():
    for system, machine, suffix in [('Windows', 'AMD64', '.msi'), ('Linux', 'x86_64', '.tar.gz'), ('Darwin', 'arm64', '.dmg')]:
        url, digest = libreoffice_asset(system, machine)
        assert '25.8.7.2' in url
        assert url.endswith(suffix)
        assert len(digest) == 64
    with pytest.raises(ValueError):
        libreoffice_asset('Linux', 'aarch64')


def test_large_release_assets_split_without_data_loss(tmp_path):
    path = tmp_path / 'portable.zip'
    payload = bytes(range(101))
    path.write_bytes(payload)
    parts = split_asset(path, limit=32)
    assert all(p.stat().st_size <= 32 for p in parts)
    assert b''.join(p.read_bytes() for p in parts) == payload
    assert not path.exists()


def test_small_asset_keeps_original(tmp_path):
    path = tmp_path / 'portable.zip'
    path.write_bytes(b'hello')
    assert split_asset(path, limit=32) == [path]


def test_font_source_is_checked_against_pinned_git_blob(tmp_path):
    path = tmp_path / 'font.ttf'
    path.write_bytes(b'font data')
    expected = hashlib.sha1(b'blob 9\0font data').hexdigest()
    engines.verify_git_blob(path, expected)
    with pytest.raises(ValueError, match='checksum'):
        engines.verify_git_blob(path, '0' * 40)


@pytest.mark.parametrize('system,relative', [('Windows', 'Any2PDF/_internal/vendor'), ('Linux', 'Any2PDF/_internal/vendor'), ('Darwin', 'Any2PDF.app/Contents/Resources/vendor')])
def test_vendor_copied_after_analysis_into_native_runtime(tmp_path, system, relative):
    source = tmp_path / 'vendor'
    (source / 'chromium/Chromium.app/Contents/MacOS').mkdir(parents=True)
    executable = source / 'chromium/Chromium.app/Contents/MacOS/Chromium'
    executable.write_bytes(b'native binary must not be transformed')
    destination = build.bundle_vendor(source, tmp_path / 'dist', system)
    assert destination == tmp_path / 'dist' / relative
    assert (destination / executable.relative_to(source)).read_bytes() == executable.read_bytes()


def test_vendor_copy_preserves_framework_symlinks(tmp_path):
    source = tmp_path / 'vendor'
    (source / 'Framework.framework/Versions/A').mkdir(parents=True)
    (source / 'Framework.framework/Versions/A/binary').write_bytes(b'framework')
    link = source / 'Framework.framework/Versions/Current'
    try:
        link.symlink_to('A', target_is_directory=True)
    except OSError:
        pytest.skip('Windows symlink privilege unavailable')
    destination = build.bundle_vendor(source, tmp_path / 'dist', 'Darwin')
    copied = destination / link.relative_to(source)
    assert copied.is_symlink()
    assert (copied / 'binary').read_bytes() == b'framework'


def test_pyinstaller_analysis_excludes_vendor_binaries(tmp_path):
    command = build.pyinstaller_command(tmp_path)
    payloads = [command[index + 1] for index, arg in enumerate(command) if arg == '--add-data']
    assert payloads == [f'{tmp_path / "LICENSE"}:.', f'{tmp_path / "THIRD_PARTY.md"}:.']
    assert not any('vendor' in item for item in command)
