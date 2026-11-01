import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtWidgets import QApplication

from any2pdf.ui import MainWindow


@pytest.fixture(scope='session')
def app():
    return QApplication.instance() or QApplication([])


def test_default_chinese_and_live_language_switch(app, tmp_path):
    w = MainWindow(data_dir=tmp_path, probe_engines=False)
    assert w.lang == 'zh'
    assert w.tabs.tabText(0) == '上传文件'
    w.language.setCurrentIndex(1)
    assert w.tabs.tabText(0) == 'Upload'
    assert w.start_button.text() == 'Start conversion'
    w.close()
    w = MainWindow(data_dir=tmp_path, probe_engines=False)
    assert w.lang == 'en'
    w.close()


def test_add_file_and_show_localized_failure_in_history(app, tmp_path):
    source = tmp_path / 'bad.zip'
    source.write_bytes(b'invalid')
    w = MainWindow(data_dir=tmp_path / 'data', probe_engines=False)
    w.add_files([str(source)])
    row = w.history.list()[0]
    assert row['status'] == 'failed'
    assert row['error_code'] == 'unsupported'
    assert '格式' in w.history_table.item(0, 3).text()
    w.language.setCurrentIndex(1)
    assert 'format' in w.history_table.item(0, 3).text().lower()
    w.close()


def test_local_file_mime_is_accepted_and_adds_queue(app, tmp_path):
    source = tmp_path / 'test.txt'
    source.write_text('hello')
    w = MainWindow(data_dir=tmp_path / 'data', probe_engines=False)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source))])
    w.add_mime(mime)
    assert w.queue_table.rowCount() == 1
    assert w.history.list()[0]['source'] == str(source.resolve())
    w.close()


def test_worker_completes_and_history_persists(app, tmp_path):
    import time
    source = tmp_path / 'test.txt'
    source.write_text('hello world')
    w = MainWindow(data_dir=tmp_path / 'data', probe_engines=False)
    w.outdir.setText(str(tmp_path / 'out'))
    w.add_files([str(source)])
    w.start_queue()
    deadline = time.monotonic() + 30
    while (w.process is not None or w.pending) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.02)
    row = w.history.list()[0]
    assert row['status'] == 'success', row
    assert os.path.isfile(row['output'])
    w.close()


def test_worker_stages_are_localized(app, tmp_path):
    w = MainWindow(data_dir=tmp_path, probe_engines=False)
    w.current_stage = 'saving'
    assert '保存' in w.stage_text()
    w.language.setCurrentIndex(1)
    assert 'Saving' in w.stage_text()
    w.close()


def test_cancelling_text_worker_cleans_temporary_output(app, tmp_path):
    import time
    source = tmp_path / 'long.txt'
    source.write_bytes(b'Hello world\n' * 500000)
    w = MainWindow(data_dir=tmp_path / 'data', probe_engines=False)
    w.outdir.setText(str(tmp_path / 'output'))
    w.add_files([str(source)])
    w.start_queue()
    # Let QProcess start before requesting cancellation.
    deadline = time.monotonic() + 5
    while w.process and not w.process.processId() and time.monotonic() < deadline:
        app.processEvents()
    w.cancel_active()
    deadline = time.monotonic() + 15
    while w.process is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.02)
    assert w.history.list()[0]['status'] == 'cancelled'
    assert not list((tmp_path / 'output').glob('*.pdf'))
    assert not list((tmp_path / 'output').glob('.any2pdf-*'))
    w.close()
