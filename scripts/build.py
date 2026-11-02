"""Create single-file executables or a native macOS application."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile
from any2pdf import __version__

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


def onefile_spec(root: Path, vendor: Path) -> Path:
    """Add engines as DATA after analysis to preserve their binaries intact."""
    scratch = root / '.local'
    scratch.mkdir(exist_ok=True)
    executable_paths = [p.relative_to(vendor).as_posix() for p in vendor.rglob('*')
                        if p.is_file() and p.stat().st_mode & 0o111]
    hook = scratch / 'vendor_permissions.py'
    # DATA entries lose executable permissions during POSIX extraction.
    hook.write_text('import os, sys\nfrom pathlib import Path\n'
                    + 'if os.name == "posix":\n'
                    + '    base = Path(sys._MEIPASS) / "vendor"\n'
                    + f'    for relative in {executable_paths!r}:\n'
                    + '        path = base / relative\n'
                    + '        path.chmod(path.stat().st_mode | 0o700)\n', encoding='utf-8')
    spec = scratch / 'Any2PDF-onefile.spec'
    source = f'''from PyInstaller.utils.hooks import collect_all
from PyInstaller.building.datastruct import Tree
datas = [({str(root / 'LICENSE')!r}, '.'), ({str(root / 'THIRD_PARTY.md')!r}, '.')]
binaries = []
hiddenimports = []
for package in ('playwright', 'pypdf', 'reportlab'):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
a = Analysis([{str(root / 'main.py')!r}], pathex=[{str(root)!r}],
    binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    hookspath=[], runtime_hooks=[{str(hook)!r}],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtWebEngineQuick', 'tkinter'], noarchive=False)
a.datas += Tree({str(vendor)!r}, prefix='vendor', typecode='DATA')
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='Any2PDF',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False)
'''
    spec.write_text(source, encoding='utf-8')
    return spec


def cached_portable(root: Path, system: str) -> Path:
    """Keep the download self-contained, but extract the full runtime only once."""
    from PyInstaller.archive.readers import CArchiveReader
    scratch = root / '.local'
    scratch.mkdir(exist_ok=True)
    payload = scratch / 'runtime.zip'
    runtime = root / 'dist/Any2PDF'
    identity = hashlib.sha256()
    with zipfile.ZipFile(payload, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for file in sorted(runtime.rglob('*')):
            if file.is_file():
                relative = file.relative_to(runtime).as_posix()
                with file.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                identity.update((relative + '\0' + digest + '\n').encode())
                archive.write(file, relative)
        archive.writestr('__any2pdf_runtime__.json', json.dumps({
            'key': identity.hexdigest(),
            'executable': 'Any2PDF.exe' if system == 'Windows' else 'Any2PDF',
        }))
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                    '--onefile', '--windowed', '--name', 'Any2PDF-bootstrap',
                    str(root / 'scripts/portable_launcher.py')], cwd=root, check=True)
    suffix = '.exe' if system == 'Windows' else ''
    bootstrap = root / 'dist' / ('Any2PDF-bootstrap' + suffix)
    reader = CArchiveReader(str(bootstrap))
    with bootstrap.open('rb') as source:
        source.seek(reader._end_offset - reader._COOKIE_LENGTH)
        cookie = list(__import__('struct').unpack(reader._COOKIE_FORMAT, source.read(reader._COOKIE_LENGTH)))
    output = root / 'dist' / ('Any2PDF-portable' + suffix)
    shutil.copy2(bootstrap, output)
    with output.open('ab') as target, payload.open('rb') as source:
        shutil.copyfileobj(source, target, length=1024 * 1024)
        # A new cookie keeps the bootloader's lookup at EOF, so startup does
        # not scan hundreds of MB backwards. Original TOC offsets stay valid.
        cookie[1] = target.tell() + reader._COOKIE_LENGTH - reader._start_offset
        target.write(__import__('struct').pack(reader._COOKIE_FORMAT, *cookie))
    output.chmod(0o755)
    # Validate both independently readable archives before shipping.
    assert CArchiveReader(str(output)).toc == reader.toc
    with zipfile.ZipFile(output) as archive:
        assert json.loads(archive.read('__any2pdf_runtime__.json'))['key'] == identity.hexdigest()
    return output


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
    system = platform.system()
    subprocess.run(pyinstaller_command(ROOT), cwd=ROOT, check=True)
    bundle_vendor(vendor, ROOT / 'dist', system)
    if system != 'Darwin':
        cached_portable(ROOT, system)
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
        name = f'Any2PDF-{__version__}-{system}-{machine}'
        release = ROOT / 'dist/release'
        release.mkdir(exist_ok=True)
        if system == 'Windows':
            archive = release / f'{name}.exe'
            shutil.copy2(ROOT / 'dist/Any2PDF-portable.exe', archive)
        elif system == 'Linux':
            archive = release / name
            shutil.copy2(ROOT / 'dist/Any2PDF-portable', archive)
        else:
            # macOS presents the signed bundle as one app; tar preserves symlinks.
            archive = Path(shutil.make_archive(str(release / name), 'gztar',
                root_dir=ROOT / 'dist', base_dir='Any2PDF.app'))
        parts = split_asset(archive)
        if len(parts) > 1:
            (release / f'{name}-REASSEMBLE.txt').write_text('Concatenate .part files in numeric order to recreate the archive before extracting.\nWindows: cmd /c copy /b "' + archive.name + '.part*" "' + archive.name + '"\nmacOS/Linux: cat ' + archive.name + '.part* > ' + archive.name + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
