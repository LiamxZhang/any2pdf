import json
import sys

from any2pdf.worker import run_worker


def test_windowed_worker_reports_stages_without_console(tmp_path, monkeypatch):
    source = tmp_path / 'test.txt'
    source.write_text('hello world')
    request = {'source': str(source), 'outdir': str(tmp_path / 'out'),
               'result': str(tmp_path / 'result.json'), 'cancel': str(tmp_path / 'cancel'),
               'stage': str(tmp_path / 'stage.json')}
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(request))
    monkeypatch.setattr(sys, 'stdout', None)
    assert run_worker(path) == 0
    assert json.loads((tmp_path / 'stage.json').read_text())['stage'] == 'saving'
