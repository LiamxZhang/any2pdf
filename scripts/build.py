"""Create a portable native PyInstaller bundle and checksummed release archive."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ASSET_LIMIT = 1_900_000_000


def split_asset(path: Path, limit: int = ASSET_LIMIT) -> list[Path]:
    if limit <= 0:
        raise ValueError('Asset limit must be positive')
    if path.stat().st_size <= limit:
        return [path]
    parts = []
    with path.open('rb') as source:
        index = 1
        while source.tell() < path.stat().st_size:
            part = path.with_name(f'{path.name}.part{index:03d}')
            with part.open('wb') as output:
                remaining = limit
                while remaining and (chunk := source.read(min(1024 * 1024, remaining))):
                    output.write(chunk)
                    remaining -= len(chunk)
            parts.append(part)
            index += 1
    path.unlink()
    return parts


def collect_licenses(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for package in ('PySide6', 'PySide6_Essentials', 'PySide6_Addons', 'shiboken6', 'Pillow', 'reportlab', 'pypdf', 'playwright', 'psutil',
                    'pyee', 'greenlet', 'charset-normalizer', 'typing_extensions', 'pyinstaller'):
        dist = importlib.metadata.distribution(package)
        for item in dist.files or []:
            if any(word in str(item).lower() for word in ('license', 'copying', 'notice')) and dist.locate_file(item).is_file():
                target = destination / package / str(item).replace('..', '_').replace(':', '_')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dist.locate_file(item), target)
    for base in (Path(sys.base_prefix), Path(sys.base_prefix) / 'share/doc/python3.12'):
        for name in ('LICENSE', 'LICENSE.txt', 'copyright'):
            source = base / name
            if source.is_file():
                shutil.copy2(source, destination / f'CPython-{name}')


def pyinstaller_command(root: Path) -> list[str]:
    # Native engine bundles must never enter PyInstaller's binary cache: its
    # per-file Mach-O rewriting/signing loses the surrounding framework bundle.
    return [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed', '--name', 'Any2PDF',
            '--add-data', f'{root / "LICENSE"}:.', '--add-data', f'{root / "THIRD_PARTY.md"}:.',
            '--collect-all', 'playwright', '--collect-all', 'pypdf', '--collect-all', 'reportlab',
            '--exclude-module', 'PySide6.QtWebEngineCore', '--exclude-module', 'PySide6.QtWebEngineWidgets',
            '--exclude-module', 'PySide6.QtWebEngineQuick', '--exclude-module', 'tkinter', str(root / 'main.py')]


def bundle_vendor(source: Path, dist: Path, system: str) -> Path:
    """Copy intact engine trees only after PyInstaller finishes the runtime."""
    relative = 'Any2PDF.app/Contents/Resources/vendor' if system == 'Darwin' else 'Any2PDF/_internal/vendor'
    destination = dist / relative
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=True)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-fetch', action='store_true')
    parser.add_argument('--archive', action='store_true')
    args = parser.parse_args()
    if not args.skip_fetch:
        subprocess.run([sys.executable, '-m', 'scripts.fetch_engines'], cwd=ROOT, check=True)
    vendor = ROOT / 'vendor'
    if not (vendor / 'fonts/NotoSansSC-Regular.ttf').exists() or not (vendor / 'versions.json').exists():
        raise RuntimeError('Vendor payload missing; run python -m scripts.fetch_engines')
    collect_licenses(vendor / 'licenses')
    subprocess.run(pyinstaller_command(ROOT), cwd=ROOT, check=True)
    system = platform.system()
    bundle_vendor(vendor, ROOT / 'dist', system)
    if system == 'Darwin':
        app = ROOT / 'dist/Any2PDF.app'
        # Signing must see the complete Chromium/LibreOffice apps and framework
        # symlinks. Keep upstream entitlements while applying an ad-hoc signature
        # to the assembled app; verification failure blocks archive publication.
        subprocess.run(['codesign', '--force', '--deep', '--sign', '-',
                        '--preserve-metadata=entitlements', str(app)], check=True)
        subprocess.run(['codesign', '--verify', '--deep', '--strict', '--verbose=2', str(app)], check=True)
    if args.archive:
        machine = {'AMD64': 'x86_64', 'aarch64': 'arm64'}.get(platform.machine(), platform.machine())
        name = f'Any2PDF-0.1.0-{system}-{machine}'
        release = ROOT / 'dist/release'
        release.mkdir(exist_ok=True)
        bundle = 'Any2PDF.app' if system == 'Darwin' else 'Any2PDF'
        # tar preserves executable permissions and macOS application symlinks.
        fmt = 'zip' if system == 'Windows' else 'gztar'
        archive = Path(shutil.make_archive(str(release / name), fmt, root_dir=ROOT / 'dist', base_dir=bundle))
        parts = split_asset(archive)
        lines = []
        for part in parts:
            with part.open('rb') as stream:
                lines.append(f'{hashlib.file_digest(stream, "sha256").hexdigest()}  {part.name}\n')
        (release / f'{name}.sha256').write_text(''.join(lines), encoding='utf-8')
        if len(parts) > 1:
            (release / f'{name}-REASSEMBLE.txt').write_text('Concatenate .part files in numeric order to recreate the archive before extracting.\nWindows: cmd /c copy /b "' + archive.name + '.part*" "' + archive.name + '"\nmacOS/Linux: cat ' + archive.name + '.part* > ' + archive.name + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
