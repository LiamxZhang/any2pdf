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


@pytest.mark.parametrize('executable,fonts', [
    ('LibreOffice/program/soffice.exe', 'LibreOffice/share/fonts/truetype'),
    ('opt/libreoffice25.8/program/soffice', 'opt/libreoffice25.8/share/fonts/truetype'),
    ('LibreOffice.app/Contents/MacOS/soffice', 'LibreOffice.app/Contents/Resources/fonts/truetype'),
])
def test_chinese_font_copied_into_office_private_fonts(tmp_path, executable, fonts):
    vendor = tmp_path / 'vendor'
    (vendor / 'fonts').mkdir(parents=True)
    (vendor / 'fonts/NotoSansSC-Regular.ttf').write_bytes(b'static TTF')
    (vendor / 'fonts/OFL.txt').write_text('SIL Open Font License')
    soffice = vendor / 'libreoffice' / executable
    soffice.parent.mkdir(parents=True)
    soffice.write_bytes(b'office binary')
    engines.bundle_office_font(vendor)
    private_fonts = vendor / 'libreoffice' / fonts
    assert (private_fonts / 'NotoSansSC-Regular.ttf').read_bytes() == b'static TTF'
    assert (private_fonts / 'NotoSansSC-OFL.txt').read_text() == 'SIL Open Font License'
    # A cached extraction marker must not suppress repair of private fonts.
    (vendor / 'libreoffice/.any2pdf-version').write_text(engines.VERSION)
    (private_fonts / 'NotoSansSC-Regular.ttf').unlink()
    engines.bundle_office_font(vendor)
    assert (private_fonts / 'NotoSansSC-Regular.ttf').read_bytes() == b'static TTF'


def test_windows_office_runtime_dlls_are_app_local_and_x64_only(tmp_path):
    vendor = tmp_path / 'vendor'
    office = vendor / 'libreoffice'
    program = office / 'LibreOffice/program'
    program.mkdir(parents=True)
    (program / 'soffice.exe').write_bytes(b'office')
    (office / 'System64').mkdir()
    (office / 'System32').mkdir()
    (office / 'System64/vcruntime140.dll').write_bytes(b'x64 runtime')
    (office / 'System64/msvcp140_1.dll').write_bytes(b'x64 C++ runtime')
    (office / 'System32/vcruntime140.dll').write_bytes(b'wrong x86 runtime')
    (office / 'System32/x86-only.dll').write_bytes(b'wrong architecture')
    engines.bundle_office_windows_runtime(vendor)
    assert (program / 'vcruntime140.dll').read_bytes() == b'x64 runtime'
    assert (program / 'msvcp140_1.dll').read_bytes() == b'x64 C++ runtime'
    assert not (program / 'x86-only.dll').exists()
    assert (office / 'System64/vcruntime140.dll').read_bytes() == b'x64 runtime'
    # Repairs an existing cached administrative extraction without MSI rerun.
    (office / '.any2pdf-version').write_text(engines.VERSION)
    (program / 'vcruntime140.dll').unlink()
    engines.bundle_office_windows_runtime(vendor)
    assert (program / 'vcruntime140.dll').read_bytes() == b'x64 runtime'


def test_office_runtime_dll_copy_ignores_non_windows_tree(tmp_path):
    vendor = tmp_path / 'vendor'
    (vendor / 'libreoffice/opt/libreoffice25.8/program').mkdir(parents=True)
    engines.bundle_office_windows_runtime(vendor)
