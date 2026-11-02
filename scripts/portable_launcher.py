"""Small portable bootstrap: expand an embedded runtime once, reuse it later.

Only the Python standard library is imported, keeping bootstrap startup small.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile


def cache_root():
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local'))
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
    return base / 'Any2PDF' / 'runtime'


@contextmanager
def cache_lock(path, timeout=600):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0)
        stream.write(b'0')
        stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise TimeoutError('Timed out waiting for runtime extraction')
                time.sleep(.1)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)


def ensure_runtime(archive_path, root=None):
    root = (Path(root) if root else cache_root()).resolve()
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read('__any2pdf_runtime__.json'))
        key = manifest['key']
        if len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
            raise ValueError('Invalid runtime identity')
        relative_exe = PurePosixPath(manifest['executable'])
        if relative_exe.is_absolute() or '..' in relative_exe.parts:
            raise ValueError('Invalid executable path')
        destination = root / key
        executable = destination.joinpath(*relative_exe.parts)
        marker = destination / '.complete'
        with cache_lock(root / (key + '.lock')):
            if marker.is_file() and marker.read_text() == key and executable.is_file():
                return executable, False
            root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=key + '-partial-', dir=root) as temporary:
                scratch = Path(temporary)
                for info in archive.infolist():
                    if info.filename == '__any2pdf_runtime__.json':
                        continue
                    relative = PurePosixPath(info.filename)
                    if relative.is_absolute() or '..' in relative.parts or chr(92) in info.filename or ':' in info.filename:
                        raise ValueError('Unsafe runtime archive path')
                    mode = info.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        raise ValueError('Runtime archive must not contain symlinks')
                    output = scratch.joinpath(*relative.parts)
                    if info.is_dir():
                        output.mkdir(parents=True, exist_ok=True)
                        continue
                    output.parent.mkdir(parents=True, exist_ok=True)
                    # ZipFile verifies each file's CRC while streaming it.
                    with archive.open(info) as source, output.open('wb') as target:
                        shutil.copyfileobj(source, target, length=1024 * 1024)
                    if os.name != 'nt':
                        output.chmod((mode & 0o777) or 0o644)
                if not scratch.joinpath(*relative_exe.parts).is_file():
                    raise ValueError('Runtime executable missing from archive')
                (scratch / '.complete').write_text(key)
                # A missing/incomplete cache can be rebuilt; versioned paths
                # keep upgrades from replacing another running app's runtime.
                if destination.exists():
                    if not destination.resolve().is_relative_to(root) or destination.is_symlink():
                        raise ValueError('Unsafe runtime cache destination')
                    shutil.rmtree(destination)
                scratch.rename(destination)
        return executable, True


def main():
    try:
        executable, _ = ensure_runtime(sys.executable)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith('_PYI_') and k != '_MEIPASS2'}
        return subprocess.call([str(executable), *sys.argv[1:]], env=env)
    except Exception as exc:
        message = 'Any2PDF 启动失败 / Could not start Any2PDF:\n' + str(exc)
        if os.name == 'nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, 'Any2PDF', 0x10)
        elif sys.stderr:
            print(message, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
