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


def test_drop_hover_leave_and_actual_drop_feedback(app, tmp_path):
    from PySide6.QtCore import Qt, QPoint, QPointF
    from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
    source = tmp_path / 'test.txt'
    source.write_text('hello')
    w = MainWindow(data_dir=tmp_path / 'data', probe_engines=False)
    w.show()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source))])
    enter = QDragEnterEvent(QPoint(30, 30), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(w.drop_area, enter)
    assert enter.isAccepted()
    assert w.drop_area.property('dragActive') is True
    assert w.drop_title.text() == '松开以添加文件'
    QApplication.sendEvent(w.drop_area, QDragLeaveEvent())
    assert w.drop_area.property('dragActive') is False
    QApplication.sendEvent(w.drop_area, QDragEnterEvent(QPoint(30, 30), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    drop = QDropEvent(QPointF(30, 30), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(w.drop_area, drop)
    assert drop.isAccepted()
    assert w.drop_area.property('dragActive') is False
    assert len(w.history.list()) == 1
    assert '1' in w.added_label.text()
    w.close()


def test_delete_one_history_record_preserves_other_records_and_files(app, tmp_path):
    w = MainWindow(data_dir=tmp_path / 'data', probe_engines=False)
    source = tmp_path / 'original.txt'
    output = tmp_path / 'result.pdf'
    source.write_text('original')
    output.write_bytes(b'keep this file')
    first = w.history.add(source, tmp_path)
    w.history.update(first, status='success', output=str(output))
    second = w.history.add(source, tmp_path)
    w.history.update(second, status='failed', error_code='unsupported')
    w.session_ids.update((first, second))
    w.refresh()
    w.history_table.selectRow(0)
    assert w.delete_button.isEnabled()
    w.delete_button.click()
    assert [r['id'] for r in w.history.list()] == [first]
    assert source.read_text() == 'original'
    assert output.read_bytes() == b'keep this file'
    assert second not in w.session_ids
    queued = w.history.add(source, tmp_path)
    w.refresh()
    w.history_table.selectRow(0)
    assert not w.delete_button.isEnabled()
    assert not w.history.delete_finished(queued)
    assert len(w.history.list()) == 2
    w.close()


@pytest.mark.parametrize('page', [1, 2])
def test_selected_row_has_visible_feedback_after_losing_focus(app, tmp_path, page):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    w = MainWindow(data_dir=tmp_path / 'data', probe_engines=False)
    source = tmp_path / 'small.txt'
    source.write_text('hello')
    w.add_files([str(source)])
    w.tabs.setCurrentIndex(page)
    w.show()
    table = w.queue_table if page == 1 else w.history_table
    app.processEvents()
    table.selectRow(0)
    w.language.setFocus()
    app.processEvents()
    rect = table.visualItemRect(table.item(0, 0))
    color = table.viewport().grab().toImage().pixelColor(rect.right()-8, rect.center().y()).name()
    assert color == '#635beb', color
    w.refresh()
    app.processEvents()
    assert table.selectionModel().selectedRows()[0].row() == 0
    assert not any('10 GiB' in label.text() for label in w.upload_page.findChildren(__import__('PySide6.QtWidgets', fromlist=['QLabel']).QLabel))
    w.close()
