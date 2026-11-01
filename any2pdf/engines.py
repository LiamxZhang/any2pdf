"""External engines run locally, without shell interpolation."""
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import unquote, urlparse

import psutil

from .errors import ConversionError
from .paths import vendor_root

TIMEOUT = 2 * 60 * 60


def kill_tree(pid):
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in reversed(children):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        parent.kill()
        psutil.wait_procs(children + [parent], timeout=3)
    except psutil.NoSuchProcess:
        pass


def office_executable():
    override = os.environ.get('ANY2PDF_LIBREOFFICE')
    if override:
        return override if Path(override).is_file() else None
    roots = [vendor_root() / 'libreoffice']
    for root in roots:
        for pattern in ('**/soffice.exe', '**/program/soffice', '**/MacOS/soffice'):
            matches = sorted(root.glob(pattern))
            if matches:
                return str(matches[0])
    if getattr(sys, 'frozen', False):
        return None
    candidates = [shutil.which('soffice'),
                  '/Applications/LibreOffice.app/Contents/MacOS/soffice',
                  'C:/Program Files/LibreOffice/program/soffice.exe']
    return next((str(p) for p in candidates if p and Path(p).is_file()), None)


def office_pdf(source, target, cancelled):
    executable = office_executable()
    if not executable:
        raise ConversionError('missing_office')
    profile = target.parent / 'office-profile'
    dest = target.parent / 'office-output'
    dest.mkdir()
    command = [executable, f'-env:UserInstallation={profile.as_uri()}', '--headless',
               '--nologo', '--nodefault', '--norestore', '--convert-to', 'pdf',
               '--outdir', str(dest), str(source)]
    log = target.parent / 'office.log'
    with log.open('wb') as stream:
        proc = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        start = time.monotonic()
        try:
            while proc.poll() is None:
                if cancelled():
                    raise ConversionError('cancelled')
                if time.monotonic() - start > TIMEOUT:
                    raise ConversionError('timeout')
                time.sleep(0.15)
        finally:
            if proc.poll() is None:
                kill_tree(proc.pid)
    candidates = list(dest.glob('*.pdf'))
    if proc.returncode != 0 or len(candidates) != 1:
        raise ConversionError('engine_failed', log.read_text(encoding='utf-8', errors='replace')[-16000:])
    candidates[0].replace(target)


class LocalDocumentHandler(SimpleHTTPRequestHandler):
    """Serve only the source directory; disallow symlink escapes and listings."""
    def translate_path(self, path):
        relative = unquote(urlparse(path).path).lstrip('/')
        root = Path(self.directory).resolve()
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            return str(root / '.any2pdf-nonexistent')
        return str(candidate)

    def list_directory(self, path):
        self.send_error(403)
        return None

    def log_message(self, format, *args):
        pass


def html_pdf(source, target, cancelled):
    from urllib.parse import quote
    bundled = vendor_root() / 'chromium'
    if bundled.exists():
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(bundled)
    elif getattr(sys, 'frozen', False):
        raise ConversionError('missing_browser', bundled)
    from playwright.sync_api import sync_playwright, Error
    handler = functools.partial(LocalDocumentHandler, directory=str(source.parent))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as p:
            if not Path(p.chromium.executable_path).is_file():
                raise ConversionError('missing_browser', p.chromium.executable_path)
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(java_script_enabled=False)
                page.route('**/*', lambda route: route.continue_()
                           if route.request.url.startswith(origin + '/') else route.abort())
                if cancelled():
                    raise ConversionError('cancelled')
                page.goto(origin + '/' + quote(source.name), wait_until='networkidle', timeout=120000)
                page.pdf(path=str(target), format='A4', print_background=True,
                         margin={'top': '15mm', 'bottom': '15mm', 'left': '12mm', 'right': '12mm'})
            finally:
                browser.close()
    except Error as exc:
        raise ConversionError('timeout' if 'Timeout' in str(exc) else 'engine_failed', exc) from exc
    finally:
        server.shutdown()
        server.server_close()


def capabilities():
    bundled = vendor_root() / 'chromium'
    if bundled.exists():
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(bundled)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = Path(p.chromium.executable_path).is_file()
    except Exception:
        browser = False
    return {'office': bool(office_executable()), 'html': browser}
