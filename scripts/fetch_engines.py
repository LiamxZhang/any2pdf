"""Fetch pinned redistributable engines; never install LibreOffice on the host."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = '25.8.7.2'
FONT_COMMIT = 'a85815a42757630ce188fdad368c2dfc444d4773'
FONT_BLOB = 'fb0637bafbcd804fe32152370a1225990745b4bc'
ASSETS = {
    ('Windows', 'x86_64'): ('win/x86_64', f'LibreOffice_{VERSION}_Win_x86-64.msi', '4773ad68edc890c7d02ae0733710af118e7e95398a4d05077429182941604ec6'),
    ('Linux', 'x86_64'): ('deb/x86_64', f'LibreOffice_{VERSION}_Linux_x86-64_deb.tar.gz', '3f180b16f5ecc97e95e8b7ca27dd9d17b12da1958afa9df2cc33e1276c588091'),
    ('Darwin', 'arm64'): ('mac/aarch64', f'LibreOffice_{VERSION}_MacOS_aarch64.dmg', 'fd9e94e59f09dbeb484ded61e504a84cfe5b99eb0ef029339bfa1748a47653fe'),
}


def libreoffice_asset(system: str, machine: str) -> tuple[str, str]:
    machine = {'amd64': 'x86_64', 'aarch64': 'arm64'}.get(machine.lower(), machine.lower())
    try:
        folder, name, digest = ASSETS[system, machine]
    except KeyError as exc:
        raise ValueError(f'Unsupported native target: {system}/{machine}') from exc
    return f'https://downloadarchive.documentfoundation.org/libreoffice/old/{VERSION}/{folder}/{name}', digest


def verify_digest(path: Path, expected: str, algorithm: str = 'sha256') -> None:
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, algorithm).hexdigest()
    if actual.lower() != expected.lower():
        raise ValueError(f'{algorithm} checksum mismatch for {path.name}: {actual}')


def verify_git_blob(path: Path, expected: str) -> None:
    digest = hashlib.sha1(f'blob {path.stat().st_size}\0'.encode())
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError(f'Git blob checksum mismatch for {path.name}')


def download(url: str, path: Path, digest: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if digest:
            try:
                verify_digest(path, digest)
                return path
            except ValueError:
                path.unlink()
        else:
            return path
    partial = path.with_suffix(path.suffix + '.partial')
    for attempt in range(4):
        try:
            print(f'Downloading {url}', flush=True)
            with urllib.request.urlopen(url, timeout=120) as response, partial.open('wb') as out:
                shutil.copyfileobj(response, out, 1024 * 1024)
            if digest:
                verify_digest(partial, digest)
            partial.replace(path)
            return path
        except (OSError, ValueError):
            partial.unlink(missing_ok=True)
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError('Download failed')


def extract_tar(path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path) as archive:
        archive.extractall(destination, filter='data')


def fetch_libreoffice(vendor: Path, cache: Path) -> None:
    system, machine = platform.system(), platform.machine()
    url, digest = libreoffice_asset(system, machine)
    dest = vendor / 'libreoffice'
    marker = dest / '.any2pdf-version'
    if marker.exists() and marker.read_text() == VERSION:
        return
    archive = download(url, cache / url.rsplit('/', 1)[1], digest)
    # Retain official metadata as provenance. The archive publishes SHA-256,
    # not SHA-512; the SHA-256 values above were read from its mirrorlist.
    download(url + '.mirrorlist', cache / (archive.name + '.mirrorlist'))
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    if system == 'Windows':
        result = subprocess.run(['msiexec.exe', '/a', str(archive), '/qn', f'TARGETDIR={dest.resolve()}'], check=False)
        if result.returncode not in (0, 3010):
            raise RuntimeError(f'LibreOffice administrative extraction failed: {result.returncode}')
        if not list(dest.rglob('soffice.exe')):
            raise RuntimeError('MSI extraction did not produce soffice.exe')
    elif system == 'Linux':
        with tempfile.TemporaryDirectory() as work:
            extract_tar(archive, Path(work))
            packages = sorted(Path(work).rglob('*.deb'))
            if not packages:
                raise RuntimeError('No LibreOffice DEBs found')
            for package in packages:
                subprocess.run(['dpkg-deb', '-x', str(package), str(dest)], check=True)
    else:
        with tempfile.TemporaryDirectory() as work:
            mount = Path(work) / 'mount'
            subprocess.run(['hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', str(mount), str(archive)], check=True)
            try:
                app = next(mount.glob('LibreOffice.app'))
                subprocess.run(['ditto', str(app), str(dest / app.name)], check=True)
            finally:
                subprocess.run(['hdiutil', 'detach', str(mount)], check=True)
    shutil.copy2(cache / (archive.name + '.mirrorlist'), dest / 'DOWNLOAD-PROVENANCE.html')
    marker.write_text(VERSION)


def fetch_font(vendor: Path, cache: Path) -> None:
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont

    fonts = vendor / 'fonts'
    fonts.mkdir(parents=True, exist_ok=True)
    base = f'https://raw.githubusercontent.com/google/fonts/{FONT_COMMIT}/ofl/notosanssc/'
    variable = download(base + 'NotoSansSC%5Bwght%5D.ttf', cache / f'NotoSansSC-{FONT_COMMIT}.ttf')
    try:
        verify_git_blob(variable, FONT_BLOB)
    except ValueError:
        variable.unlink(missing_ok=True)
        raise
    license_path = download(base + 'OFL.txt', cache / f'NotoSansSC-{FONT_COMMIT}-OFL.txt')
    with TTFont(variable) as font:
        static = instantiateVariableFont(font, {'wght': 400}, inplace=False)
        static.save(fonts / 'NotoSansSC-Regular.ttf')
    shutil.copy2(license_path, fonts / 'OFL.txt')


def main() -> None:
    vendor, cache = ROOT / 'vendor', ROOT / '.local/downloads'
    vendor.mkdir(exist_ok=True)
    fetch_libreoffice(vendor, cache)
    fetch_font(vendor, cache)
    env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(vendor / 'chromium'))
    subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'], env=env, check=True)
    (vendor / 'versions.json').write_text(json.dumps({'libreoffice': VERSION, 'playwright': '1.56.0', 'font_commit': FONT_COMMIT}, indent=2))


if __name__ == '__main__':
    main()
