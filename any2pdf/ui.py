"""Native desktop interface. Workers never run on the GUI thread."""
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid
import psutil
import tempfile

from PySide6.QtCore import Qt, QProcess, QTimer, QUrl, QLockFile, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QDialog, QVBoxLayout, QWidget)

from . import __version__
from .core import inspect_input
from .engines import capabilities, kill_tree, TIMEOUT
from .errors import ConversionError, explain
from .history import History
from .i18n import tr
from .paths import data_root, resource_root, vendor_root

STYLE = '''
QMainWindow, QDialog { background: #F6F7FB; }
QWidget { color: #1E293B; font-size: 13px; }
QLabel#subtitle, QLabel#hint { color: #64748B; }
QLabel#eyebrow { color: #635BEB; font-weight: 700; font-size: 12px; }
QLabel#dropTitle { font-size: 24px; font-weight: 600; }
QLabel#dropIcon { font-size: 42px; color: #635BEB; }
QFrame#drop { background: #FCFCFF; border: 2px dashed #B5B3ED; border-radius: 16px; }
QFrame#drop[dragActive="true"] { background: #EDEBFF; border: 2px solid #635BEB; }
QFrame#card { background: white; border: 1px solid #E4E8F1; border-radius: 12px; }
QTabWidget::pane { background: white; border: 1px solid #E4E8F1; border-radius: 12px; }
QTabBar::tab { padding: 13px 25px; color: #64748B; border-bottom: 3px solid transparent; }
QTabBar::tab:selected { color: #635BEB; border-bottom: 3px solid #635BEB; font-weight: bold; }
QPushButton { background: white; border: 1px solid #D9DFEA; border-radius: 7px; padding: 9px 15px; }
QPushButton:hover { background: #F0EFFF; border-color: #A8A1EE; }
QPushButton:disabled { color: #A5ADBC; background: #F1F3F8; border-color: #E4E8F1; }
QPushButton#primary { background: #635BEB; border-color: #635BEB; color: white; font-weight: 600; padding: 11px 24px; }
QPushButton#primary:hover { background: #5146D4; }
QPushButton#primary:disabled { background: #B9B5EC; border-color: #B9B5EC; }
QLineEdit, QComboBox { background: white; border: 1px solid #D9DFEA; border-radius: 6px; padding: 8px; }
QComboBox QAbstractItemView { background-color: #FFFFFF; color: #1E293B; selection-background-color: #EDEBFF; selection-color: #1E293B; border: 1px solid #D9DFEA; outline: 0; }
QComboBox QAbstractItemView::item { background-color: #FFFFFF; color: #1E293B; min-height: 30px; }
QComboBox QAbstractItemView::item:selected { background-color: #EDEBFF; }
QTableWidget { border: 0; gridline-color: #EEF1F6; background: white; selection-background-color: #DAD6FF; selection-color: #172554; }
QTableWidget::item:selected, QTableWidget::item:selected:!active { background: #635BEB; color: #FFFFFF; border: 1px solid #5146D4; }
QHeaderView::section { background: #F8F9FC; border: 0; border-bottom: 1px solid #E4E8F1; padding: 10px; text-align: left; color: #64748B; }
QProgressBar { border: 0; background: #EAE8FC; border-radius: 3px; max-height: 6px; }
QProgressBar::chunk { background: #635BEB; border-radius: 3px; }
QTextEdit { background: white; border: 1px solid #D9DFEA; border-radius: 8px; padding: 12px; }
'''


def human_size(size):
    if size is None:
        return '—'
    for unit in ('B', 'KiB', 'MiB', 'GiB'):
        if size < 1024 or unit == 'GiB':
            return f'{size:.1f} {unit}'
        size /= 1024


class DropArea(QFrame):
    filesDropped = Signal(object)
    activeChanged = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setObjectName('drop')
        self.setAcceptDrops(True)
        self.set_active(False)

    def set_active(self, active):
        self.setProperty('dragActive', active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
        self.activeChanged.emit(active)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            self.set_active(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dragLeaveEvent(self, event):
        self.set_active(False)
        event.accept()

    def dropEvent(self, event):
        self.set_active(False)
        if any(u.isLocalFile() for u in event.mimeData().urls()):
            self.filesDropped.emit(event.mimeData())
            event.acceptProposedAction()
        else:
            event.ignore()


class MainWindow(QMainWindow):
    def __init__(self, data_dir=None, probe_engines=True):
        super().__init__()
        self.root = Path(data_dir) if data_dir else data_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings_file = self.root / 'settings.json'
        try:
            self.settings = json.loads(self.settings_file.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.settings = {}
        self.lang = self.settings.get('lang', 'zh')
        self.history = History(self.root / 'history.sqlite3')
        self.recover_workspaces()
        self.pending = []
        self.session_ids = set()
        self.process = None
        self.active = None
        self.job_dir = None
        self.user_cancelled = False
        self.timed_out = False
        self.closing = False
        self.current_stage = 'starting'
        self.engines = capabilities() if probe_engines else {'office': False, 'html': False}
        self.setWindowTitle(f'Any2PDF · {__version__}')
        self.resize(1040, 700)
        self.setMinimumSize(900, 620)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLE)
        self.labels = []
        self.build_ui()
        self.translate()
        self.refresh()

    def text(self, key):
        return tr(key, self.lang)

    def recover_workspaces(self):
        for request in (self.root / 'jobs').glob('*/request.json'):
            job = request.parent
            # Only remove our UUID-labelled scratch space, never source paths.
            if len(job.name) != 32 or any(c not in '0123456789abcdef' for c in job.name):
                continue
            try:
                data = json.loads(request.read_text(encoding='utf-8'))
                prefix = f'.any2pdf-{job.name}-'
                if data.get('workspace_prefix') != prefix:
                    continue
                output = Path(data['outdir'])
                if output.is_absolute() and output.is_dir():
                    for folder in output.glob(prefix + '*'):
                        if folder.is_dir() and not folder.is_symlink():
                            shutil.rmtree(folder, ignore_errors=True)
                shutil.rmtree(job, ignore_errors=True)
            except (OSError, KeyError, ValueError):
                continue

    def stage_text(self):
        return self.text('stage_' + self.current_stage)

    def label(self, key, name=None):
        widget = QLabel()
        if name:
            widget.setObjectName(name)
        widget.setWordWrap(True)
        self.labels.append((widget, key))
        return widget

    def button(self, key, callback, primary=False):
        widget = QPushButton()
        if primary:
            widget.setObjectName('primary')
        widget.clicked.connect(callback)
        self.labels.append((widget, key))
        return widget

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(34, 24, 34, 20)
        layout.setSpacing(16)
        header = QHBoxLayout()
        header.addStretch()
        self.language = QComboBox()
        self.language.addItems(['简体中文', 'English'])
        # A non-native popup and explicit palette avoid OS dark popup colors.
        self.language.setStyleSheet('QComboBox { combobox-popup: 0; background: #FFFFFF; color: #1E293B; }')
        palette = self.language.view().palette()
        for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
            palette.setColor(group, QPalette.Base, QColor('#FFFFFF'))
            palette.setColor(group, QPalette.Window, QColor('#FFFFFF'))
            palette.setColor(group, QPalette.Text, QColor('#1E293B'))
            palette.setColor(group, QPalette.Highlight, QColor('#EDEBFF'))
            palette.setColor(group, QPalette.HighlightedText, QColor('#1E293B'))
        self.language.view().setPalette(palette)
        self.language.setCurrentIndex(1 if self.lang == 'en' else 0)
        self.language.currentIndexChanged.connect(self.change_language)
        header.addWidget(self.language)
        layout.addLayout(header)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.upload_page = QWidget()
        self.tabs.addTab(self.upload_page, '')
        upload = QVBoxLayout(self.upload_page)
        upload.setContentsMargins(26, 26, 26, 22)
        upload.setSpacing(16)
        self.drop_area = drop = DropArea()
        drop.filesDropped.connect(self.add_mime)
        drop.activeChanged.connect(self.update_drop_title)
        drop.setMinimumHeight(225)
        content = QVBoxLayout(drop)
        content.setContentsMargins(25, 20, 25, 20)
        content.setSpacing(9)
        content.addStretch()
        self.drop_title = self.label('drop_title', 'dropTitle')
        self.drop_title.setAlignment(Qt.AlignCenter)
        content.addWidget(self.drop_title)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.button('choose', self.choose_files, True))
        row.addStretch()
        content.addLayout(row)
        content.addStretch()
        upload.addWidget(drop, 1)
        self.added_label = QLabel()
        self.added_label.setStyleSheet('color: #635BEB;')
        upload.addWidget(self.added_label)
        self.queue_page = QWidget()
        self.tabs.addTab(self.queue_page, '')
        queue_layout = QVBoxLayout(self.queue_page)
        queue_layout.setContentsMargins(18, 18, 18, 18)
        output_row = QHBoxLayout()
        output_row.addWidget(self.label('output_dir'))
        default_output = Path.home() / 'Documents/Any2PDF'
        self.outdir = QLineEdit(self.settings.get('outdir', str(default_output)))
        self.outdir.editingFinished.connect(self.save_settings)
        output_row.addWidget(self.outdir, 1)
        self.browse_button = self.button('browse', self.choose_output)
        output_row.addWidget(self.browse_button)
        queue_layout.addLayout(output_row)
        self.queue_table = self.make_table()
        self.queue_table.itemDoubleClicked.connect(lambda _: self.show_details(self.queue_table))
        queue_layout.addWidget(self.queue_table, 1)
        controls = QHBoxLayout()
        self.start_button = self.button('start', self.start_queue, True)
        controls.addWidget(self.start_button)
        self.cancel_button = self.button('cancel', self.cancel_active)
        controls.addWidget(self.cancel_button)
        controls.addStretch()
        controls.addWidget(self.button('details', lambda: self.show_details(self.queue_table)))
        controls.addWidget(self.button('remove', self.remove_selected))
        queue_layout.addLayout(controls)
        self.history_page = QWidget()
        self.tabs.addTab(self.history_page, '')
        history_layout = QVBoxLayout(self.history_page)
        history_layout.setContentsMargins(18, 18, 18, 18)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.textChanged.connect(self.refresh)
        filters.addWidget(self.search, 1)
        self.status_filter = QComboBox()
        self.status_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.status_filter)
        history_layout.addLayout(filters)
        self.history_table = self.make_table()
        self.history_table.itemDoubleClicked.connect(lambda _: self.show_details(self.history_table))
        history_layout.addWidget(self.history_table, 1)
        actions = QHBoxLayout()
        actions.addWidget(self.button('open', lambda: self.open_selected(False)))
        actions.addWidget(self.button('open_folder', lambda: self.open_selected(True)))
        actions.addWidget(self.button('retry', self.retry_selected))
        actions.addWidget(self.button('details', lambda: self.show_details(self.history_table)))
        actions.addStretch()
        self.delete_button = self.button('delete_record', self.delete_history_record)
        actions.addWidget(self.delete_button)
        self.history_table.itemSelectionChanged.connect(self.update_delete_button)
        actions.addWidget(self.button('clear', self.clear_history))
        history_layout.addLayout(actions)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)
        footer = QHBoxLayout()
        self.status_label = QLabel()
        footer.addWidget(self.status_label, 1)
        layout.addLayout(footer)

    def make_table(self):
        table = QTableWidget(0, 6)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.verticalHeader().hide()
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        table.setColumnWidth(0, 180)
        table.setColumnWidth(1, 90)
        table.setColumnWidth(2, 105)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        table.setColumnWidth(4, 140)
        table.setColumnWidth(5, 70)
        return table

    def change_language(self, index):
        self.lang = 'en' if index else 'zh'
        self.translate()
        self.refresh()
        self.save_settings()

    def translate(self):
        for widget, key in self.labels:
            widget.setText(self.text(key))
        for i, key in enumerate(('upload', 'convert', 'history')):
            self.tabs.setTabText(i, self.text(key))
        for table in (self.queue_table, self.history_table):
            table.setHorizontalHeaderLabels([self.text(k) for k in ('file', 'size', 'status', 'reason', 'created', 'elapsed')])
        self.search.setPlaceholderText(self.text('search'))
        index = self.status_filter.currentIndex()
        self.status_filter.blockSignals(True)
        self.status_filter.clear()
        for key in ('all', 'queued', 'running', 'success', 'failed', 'cancelled'):
            self.status_filter.addItem(self.text(key), key)
        self.status_filter.setCurrentIndex(max(0, index))
        self.status_filter.blockSignals(False)
        self.update_drop_title(bool(self.drop_area.property('dragActive')))

    def save_settings(self):
        self.settings.update(lang=self.lang, outdir=self.outdir.text())
        temp = self.settings_file.with_suffix('.tmp')
        temp.write_text(json.dumps(self.settings, ensure_ascii=False), encoding='utf-8')
        temp.replace(self.settings_file)

    def choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, self.text('choose'))
        self.add_files(files)

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, self.text('output_dir'), self.outdir.text())
        if folder:
            self.outdir.setText(folder)
            self.save_settings()

    def update_drop_title(self, active):
        self.drop_title.setText(self.text('drop_release' if active else 'drop_title'))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            self.drop_area.set_active(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.drop_area.set_active(False)
        event.accept()

    def dropEvent(self, event):
        self.drop_area.set_active(False)
        self.add_mime(event.mimeData())
        event.acceptProposedAction()

    def add_mime(self, mime):
        self.add_files([url.toLocalFile() for url in mime.urls() if url.isLocalFile()])

    def add_files(self, files):
        live = {row['source'] for row in self.history.list() if row['status'] in ('queued', 'running')}
        for filename in files:
            source = str(Path(filename).resolve())
            if source in live:
                continue
            task = self.history.add(source, self.outdir.text())
            self.session_ids.add(task)
            try:
                inspect_input(Path(source))
                self.pending.append(task)
                live.add(source)
            except ConversionError as exc:
                self.history.update(task, status='failed', error_code=exc.code, detail=exc.detail)
            except OSError as exc:
                self.history.update(task, status='failed', error_code='permission', detail=str(exc))
        self.refresh()

    def refresh(self, *_):
        rows = self.history.list()
        self.fill_table(self.queue_table, [r for r in rows if r['id'] in self.session_ids])
        query = self.search.text().casefold()
        status = self.status_filter.currentData()
        self.fill_table(self.history_table, [r for r in rows if query in r['source'].casefold()
                                            and (not status or status == 'all' or r['status'] == status)])
        busy = self.process is not None
        self.start_button.setEnabled(bool(self.pending) and not busy)
        self.cancel_button.setEnabled(busy and not self.user_cancelled and not self.timed_out)
        self.browse_button.setEnabled(not busy)
        self.outdir.setReadOnly(busy)
        self.progress.setVisible(busy)
        self.added_label.setText(self.text('selected_count') + str(len(self.session_ids)) if self.session_ids else '')
        self.update_delete_button()
        if busy:
            row = next((r for r in rows if r['id'] == self.active), {})
            self.status_label.setText(self.text('working') + Path(row.get('source', '')).name + '  ·  ' + self.stage_text())
        else:
            self.status_label.setText(self.text('ready') + '  ·  ' + self.text('queue_count') + str(len(self.pending)))

    def fill_table(self, table, rows):
        selected = self.selected_id(table)
        table.setRowCount(len(rows))
        colors = {'success': '#26835C', 'failed': '#C44343', 'running': '#635BEB', 'cancelled': '#8A6A26'}
        for index, row in enumerate(rows):
            path = Path(row['source'])
            try:
                size = path.stat().st_size
            except OSError:
                size = None
            reason = explain(row['error_code'], self.lang) if row['error_code'] else row['output']
            try:
                created = datetime.fromisoformat(row['created']).astimezone().strftime('%m-%d %H:%M')
            except ValueError:
                created = row['created']
            values = [path.name, human_size(size), self.text(row['status']), reason, created,
                      f"{row['elapsed']:.1f}s" if row['elapsed'] else '—']
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, row['id'])
                item.setToolTip(row['source'] if column == 0 else value)
                if column == 2:
                    item.setForeground(QColor(colors.get(row['status'], '#64748B')))
                table.setItem(index, column, item)
            table.setRowHeight(index, 44)
            if row['id'] == selected:
                table.selectRow(index)

    def selected_id(self, table):
        item = table.item(table.currentRow(), 0)
        return item.data(Qt.UserRole) if item else None

    def selected_row(self, table):
        task = self.selected_id(table)
        return next((r for r in self.history.list() if r['id'] == task), None)

    def start_queue(self):
        if self.process is not None or not self.pending:
            return
        self.save_settings()
        self.tabs.setCurrentIndex(1)
        self.active = self.pending.pop(0)
        row = next(r for r in self.history.list() if r['id'] == self.active)
        job_id = uuid.uuid4().hex
        self.job_dir = self.root / 'jobs' / job_id
        self.job_dir.mkdir(parents=True)
        self.workspace_prefix = f'.any2pdf-{job_id}-'
        self.job_outdir = Path(self.outdir.text()).expanduser().resolve()
        self.request = {'source': row['source'], 'outdir': str(self.job_outdir),
                        'result': str(self.job_dir / 'result.json'), 'cancel': str(self.job_dir / 'cancel'),
                        'stage': str(self.job_dir / 'stage.json'),
                        'workspace_prefix': self.workspace_prefix}
        request_file = self.job_dir / 'request.json'
        request_file.write_text(json.dumps(self.request, ensure_ascii=False), encoding='utf-8')
        self.history.update(self.active, status='running', outdir=str(self.job_outdir), error_code='', detail='')
        self.user_cancelled = self.timed_out = False
        self.current_stage = 'starting'
        self.started_at = time.monotonic()
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_worker_output)
        self.process.finished.connect(self.worker_finished)
        self.process.errorOccurred.connect(self.worker_error)
        self.worker_log = bytearray()
        self.stage_buffer = bytearray()
        if getattr(sys, 'frozen', False):
            executable, args = sys.executable, ['--worker', str(request_file)]
        else:
            executable, args = sys.executable, [str(resource_root() / 'main.py'), '--worker', str(request_file)]
        self.watchdog = QTimer(self)
        self.watchdog.setSingleShot(True)
        self.watchdog.timeout.connect(self.on_timeout)
        self.watchdog.start(TIMEOUT * 1000)
        self.stage_timer = QTimer(self)
        self.stage_timer.timeout.connect(self.read_stage_file)
        self.stage_timer.start(250)
        self.process.start(executable, args)
        self.refresh()

    def read_stage_file(self):
        if not self.process:
            return
        try:
            stage = json.loads(Path(self.request['stage']).read_text(encoding='utf-8')).get('stage')
            if stage in ('text', 'image', 'pdf', 'office', 'html', 'saving') and stage != self.current_stage:
                self.current_stage = stage
                self.refresh()
        except (OSError, ValueError, AttributeError):
            pass

    def read_worker_output(self):
        if self.process:
            data = bytes(self.process.readAllStandardOutput())
            self.worker_log.extend(data)
            del self.worker_log[:-16000]
            self.stage_buffer.extend(data)
            while b'\n' in self.stage_buffer:
                line, _, tail = self.stage_buffer.partition(b'\n')
                self.stage_buffer = bytearray(tail)
                try:
                    stage = json.loads(line).get('stage')
                    if stage in ('text', 'image', 'pdf', 'office', 'html', 'saving'):
                        self.current_stage = stage
                        self.refresh()
                except (ValueError, AttributeError):
                    pass
            del self.stage_buffer[:-16000]

    def worker_error(self, error):
        if error == QProcess.FailedToStart:
            self.worker_finished(-1, QProcess.CrashExit)

    def on_timeout(self):
        if self.process:
            self.timed_out = True
            self.cancel_active()

    def cancel_active(self):
        if not self.process:
            return
        self.user_cancelled = not self.timed_out
        Path(self.request['cancel']).touch()
        proc = self.process
        QTimer.singleShot(1200, lambda: self.force_stop(proc))
        self.refresh()

    def force_stop(self, process):
        if self.process is process and process.state() != QProcess.NotRunning:
            try:
                kill_tree(process.processId())
            except (OSError, psutil.Error):
                process.kill()

    def worker_finished(self, exit_code=0, exit_status=None):
        if self.process is None:
            return
        self.watchdog.stop()
        self.watchdog.deleteLater()
        self.stage_timer.stop()
        self.stage_timer.deleteLater()
        self.read_worker_output()
        try:
            result = json.loads(Path(self.request['result']).read_text(encoding='utf-8'))
            required = {'status', 'output', 'error_code', 'detail', 'elapsed'}
            if set(result) != required or result['status'] not in ('success', 'failed', 'cancelled'):
                raise ValueError('Invalid worker response')
        except (OSError, ValueError):
            code = 'timeout' if self.timed_out else 'cancelled' if self.user_cancelled else 'worker_crashed'
            result = {'status': 'cancelled' if code == 'cancelled' else 'failed', 'error_code': code,
                      'output': '', 'detail': f'Process exit: {exit_code}\n' + self.worker_log.decode('utf-8', errors='replace'),
                      'elapsed': time.monotonic() - self.started_at}
        if self.timed_out and result['status'] != 'success':
            result.update(status='failed', error_code='timeout')
        self.history.update(self.active, **result)
        logs = self.root / 'logs'
        logs.mkdir(exist_ok=True)
        (logs / f'{self.active}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        # Remove only the directory prefix belonging to this exact worker.
        if self.job_outdir.is_dir():
            for folder in self.job_outdir.glob(self.workspace_prefix + '*'):
                if folder.is_dir() and not folder.is_symlink():
                    shutil.rmtree(folder, ignore_errors=True)
        shutil.rmtree(self.job_dir, ignore_errors=True)
        self.process.deleteLater()
        self.process = None
        self.active = None
        self.refresh()
        if self.pending and not self.closing:
            QTimer.singleShot(0, self.start_queue)

    def remove_selected(self):
        task = self.selected_id(self.queue_table)
        if task in self.pending:
            self.pending.remove(task)
            self.history.update(task, status='cancelled', error_code='cancelled')
        if task != self.active:
            self.session_ids.discard(task)
        self.refresh()

    def retry_selected(self):
        row = self.selected_row(self.history_table)
        if row and row['status'] not in ('queued', 'running'):
            self.add_files([row['source']])
            self.tabs.setCurrentIndex(1)

    def update_delete_button(self):
        row = self.selected_row(self.history_table)
        self.delete_button.setEnabled(bool(row and row['status'] not in ('queued', 'running')))

    def delete_history_record(self):
        task = self.selected_id(self.history_table)
        if task is not None and self.history.delete_finished(task):
            self.session_ids.discard(task)
            try:
                (self.root / 'logs' / f'{task}.json').unlink(missing_ok=True)
            except OSError as exc:
                QMessageBox.warning(self, self.text('error_title'), str(exc))
            self.refresh()

    def clear_history(self):
        if QMessageBox.question(self, 'Any2PDF', self.text('clear_question')) == QMessageBox.Yes:
            for task in self.history.clear_finished():
                try:
                    (self.root / 'logs' / f'{task}.json').unlink(missing_ok=True)
                except OSError as exc:
                    QMessageBox.warning(self, self.text('error_title'), str(exc))
            self.refresh()

    def open_selected(self, folder):
        row = self.selected_row(self.history_table)
        if not row:
            QMessageBox.information(self, 'Any2PDF', self.text('empty_selection'))
            return
        path = Path(row['output']) if row['output'] else None
        if path and path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent if folder else path)))
        else:
            QMessageBox.information(self, 'Any2PDF', self.text('missing_output'))

    def show_details(self, table):
        row = self.selected_row(table)
        if not row:
            QMessageBox.information(self, 'Any2PDF', self.text('empty_selection'))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self.text('diagnostics'))
        dialog.resize(720, 450)
        layout = QVBoxLayout(dialog)
        text = QTextEdit()
        text.setReadOnly(True)
        reason = explain(row['error_code'], self.lang) if row['error_code'] else self.text('no_error')
        text.setPlainText(f"{row['source']}\n\n{reason}\n\nCode: {row['error_code'] or '—'}\n\n{row['detail']}")
        layout.addWidget(text)
        dialog.exec()

    def closeEvent(self, event):
        if self.process:
            if QMessageBox.question(self, 'Any2PDF', self.text('close_question')) != QMessageBox.Yes:
                event.ignore()
                return
            self.closing = True
            self.cancel_active()
            self.force_stop(self.process)
            if self.process:
                self.process.waitForFinished(5000)
            if self.process:
                self.worker_finished(-1)
        for task in self.pending:
            self.history.update(task, status='cancelled', error_code='cancelled')
        self.pending.clear()
        self.save_settings()
        self.history.close()
        event.accept()


def setup_font(app):
    font = vendor_root() / 'fonts/NotoSansSC-Regular.ttf'
    if font.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 10))
            return
    app.setFont(QFont('Microsoft YaHei' if sys.platform == 'win32' else 'Sans Serif', 10))


def run():
    app = QApplication(sys.argv)
    app.setApplicationName('Any2PDF')
    app.setOrganizationName('Any2PDF')
    setup_font(app)
    root = data_root()
    lock = QLockFile(str(root / 'application.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        try:
            lang = json.loads((root / 'settings.json').read_text(encoding='utf-8')).get('lang', 'zh')
        except (OSError, ValueError):
            lang = 'zh'
        QMessageBox.information(None, 'Any2PDF', tr('already_running', lang))
        return 0
    window = MainWindow(data_dir=root)
    window.show()
    return app.exec()


def gui_smoke(screenshot):
    """Exercise native Qt plugins with an isolated profile on each CI desktop."""
    app = QApplication(sys.argv)
    setup_font(app)
    with tempfile.TemporaryDirectory(prefix='any2pdf-gui-') as folder:
        window = MainWindow(data_dir=Path(folder))
        window.show()
        status = [1]
        def capture():
            if all(window.engines.values()) and window.grab().save(str(screenshot)):
                status[0] = 0
            window.close()
            app.quit()
        QTimer.singleShot(750, capture)
        app.exec()
        return status[0]
