import json
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import zipfile

import pytest
from scripts.portable_launcher import ensure_runtime


def archive_at(path, bad_path=None):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('__any2pdf_runtime__.json', json.dumps({'key': 'a' * 64, 'executable': 'Any2PDF'}))
        entry = zipfile.ZipInfo('Any2PDF')
        entry.external_attr = (stat.S_IFREG | 0o755) << 16
        archive.writestr(entry, b'native executable')
        archive.writestr('vendor/engine', b'engine')
        if bad_path:
            archive.writestr(bad_path, b'escape')
    return path


def test_runtime_is_expanded_once_and_reused_without_rewriting(tmp_path):
    archive = archive_at(tmp_path / 'app.zip')
    executable, created = ensure_runtime(archive, tmp_path / 'cache')
    assert created and executable.read_bytes() == b'native executable'
    old_time = executable.stat().st_mtime_ns
    executable2, created = ensure_runtime(archive, tmp_path / 'cache')
    assert not created and executable2 == executable
    assert executable.stat().st_mtime_ns == old_time
    # Interrupted or manually removed runtimes recover on the next run.
    executable.unlink()
    executable2, created = ensure_runtime(archive, tmp_path / 'cache')
    assert created and executable2.is_file()


def test_parallel_launchers_share_one_complete_runtime(tmp_path):
    archive = archive_at(tmp_path / 'app.zip')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: ensure_runtime(archive, tmp_path / 'cache'), range(2)))
    assert sum(created for _, created in results) == 1
    assert results[0][0] == results[1][0]
    assert not list((tmp_path / 'cache').glob('*partial*'))


@pytest.mark.parametrize('bad_path', ['../escape', '/absolute', 'C:/escape', '..\\escape'])
def test_runtime_archive_path_escape_is_rejected(tmp_path, bad_path):
    archive = archive_at(tmp_path / 'app.zip', bad_path)
    with pytest.raises(ValueError, match='Unsafe'):
        ensure_runtime(archive, tmp_path / 'cache')
    assert not (tmp_path / 'escape').exists()
    assert not list((tmp_path / 'cache').glob('*/.complete'))
