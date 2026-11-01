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
        descendants = {}
        drain_started = None
        def child_running(child):
            try:
                return child.is_running() and child.status() != psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess:
                return False
        try:
            while True:
                try:
                    for child in psutil.Process(proc.pid).children(recursive=True):
                        descendants[child.pid] = child
                except psutil.NoSuchProcess:
                    pass
                # The launcher may return before a conversion/helper child has
                # finished writing its isolated profile. Keep that directory
                # until all observed descendants have exited as well.
                if proc.poll() is not None:
                    if not any(child_running(child) for child in descendants.values()):
                        break
                    if drain_started is None:
                        drain_started = time.monotonic()
                    if time.monotonic() - drain_started >= 10:
                        break  # finally kills and reaps known lingering children
                if cancelled():
                    raise ConversionError('cancelled')
                if time.monotonic() - start > TIMEOUT:
                    raise ConversionError('timeout')
                time.sleep(0.15)
        finally:
            if proc.poll() is None:
                kill_tree(proc.pid)
            for child in descendants.values():
                if child_running(child):
                    try:
                        child.kill()  # Process handles protect against PID reuse.
                    except psutil.NoSuchProcess:
                        pass
            psutil.wait_procs(list(descendants.values()), timeout=3)
            # LO's extension registry creates paths over MAX_PATH even for an
            # ordinary output folder. Without an extended Windows path Python
            # can skip those files as "missing", then fail removing the parent.
            if profile.exists():
                cleanup_path = str(profile.resolve())
                if sys.platform == 'win32':
                    cleanup_path = ('\\\\?\\UNC\\' + cleanup_path[2:] if cleanup_path.startswith('\\\\')
                                    else '\\\\?\\' + cleanup_path)
                shutil.rmtree(cleanup_path)
    candidates = list(dest.glob('*.pdf'))
    if proc.returncode != 0 or len(candidates) != 1:
        detail = f'LibreOffice exit code: {proc.returncode}; generated PDF files: {len(candidates)}\n'
        detail += log.read_text(encoding='utf-8', errors='replace')[-15000:]
        raise ConversionError('engine_failed', detail)
    candidates[0].replace(target)


class LocalDocumentHandler(SimpleHTTPRequestHandler):
    """Serve only the source directory; disallow symlink escapes and listings."""
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.ttf': 'font/ttf'}

    def __init__(self, *args, font_path=None, **kwargs):
        self.font_path = Path(font_path).resolve() if font_path is not None else None
        super().__init__(*args, **kwargs)

    def translate_path(self, path):
        relative = unquote(urlparse(path).path).lstrip('/')
        # This reserved URL exposes exactly one trusted bundled file, never
        # an arbitrary path outside the document directory.
        if relative == '__any2pdf_font.ttf' and self.font_path is not None:
            return str(self.font_path)
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


def add_html_font_fallback(page, font_url):
    """Trusted converter code runs while document-authored scripts stay disabled."""
    page.evaluate('''fontURL => {
        // Print with the bundled font first. Generic system font fallback can
        // select missing CJK glyphs on Linux before reaching an appended face.
        // Snapshot before mutation to avoid repeatedly inheriting the prefix.
        const styles = Array.from(document.querySelectorAll('*'), element =>
            [element, getComputedStyle(element).fontFamily]);
        const sheet = document.createElement('style');
        sheet.textContent = '@font-face {font-family: "Any2PDF CJK"; src: url("' +
            fontURL + '") format("truetype"); font-weight: 100 900; font-style: normal;}';
        document.head.appendChild(sheet);
        for (const [element, family] of styles) {
            element.style.setProperty('font-family', '"Any2PDF CJK", ' + family, 'important');
        }
        const probe = document.createElement('span');
        probe.id = '__any2pdf_font_probe';
        probe.textContent = '你好';
        probe.style.cssText = 'font-family: "Any2PDF CJK" !important; font-size:16px; ' +
            'position:absolute; left:-10000px; visibility:hidden; display:block !important';
        document.body.appendChild(probe);
        return probe.offsetHeight; // Force layout and the font request.
    }''', font_url)
    # Awaiting a JS Promise can hang indefinitely with document scripts disabled.
    # Synchronous evaluation plus a bounded Python loop leaves font loading to
    # Chromium without permitting document-authored JavaScript to run.
    deadline = time.monotonic() + 30
    while not page.evaluate('''() => {
        const bundled = Array.from(document.fonts).filter(face => face.family.includes('Any2PDF CJK'));
        return bundled.length > 0 && bundled.every(face => face.status === 'loaded') &&
            document.fonts.check('16px "Any2PDF CJK"', '你好');
    }'''):
        if time.monotonic() >= deadline:
            raise ConversionError('engine_failed', 'Bundled Chinese font did not load within 30 seconds')
        time.sleep(0.05)
    page.evaluate('''() => document.getElementById('__any2pdf_font_probe')?.remove()''')


def html_pdf(source, target, cancelled):
    from urllib.parse import quote
    bundled = vendor_root() / 'chromium'
    if bundled.exists():
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(bundled)
    elif getattr(sys, 'frozen', False):
        raise ConversionError('missing_browser', bundled)
    from playwright.sync_api import sync_playwright, Error
    font = vendor_root() / 'fonts/NotoSansSC-Regular.ttf'
    handler = functools.partial(LocalDocumentHandler, directory=str(source.parent),
                                font_path=font if font.is_file() else None)
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as p:
            if not Path(p.chromium.executable_path).is_file():
                raise ConversionError('missing_browser', p.chromium.executable_path)
            browser = p.chromium.launch(headless=True, executable_path=p.chromium.executable_path)
            try:
                # Source CSP must not prevent trusted font/style injection.
                # Scripts remain disabled and the route still blocks networks.
                page = browser.new_page(java_script_enabled=False, bypass_csp=True)
                page.route('**/*', lambda route: route.continue_()
                           if route.request.url.startswith(origin + '/') else route.abort())
                if cancelled():
                    raise ConversionError('cancelled')
                page.goto(origin + '/' + quote(source.name), wait_until='networkidle', timeout=120000)
                page.emulate_media(media='print')
                if font.is_file():
                    add_html_font_fallback(page, origin + '/__any2pdf_font.ttf')
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
