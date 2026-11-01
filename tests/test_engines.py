from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
import threading
import urllib.error
import urllib.request

import pytest
from any2pdf.core import convert, inspect_input, MAX_BYTES
from any2pdf.engines import LocalDocumentHandler, office_executable
from any2pdf.errors import ConversionError
from pypdf import PdfReader


def test_sparse_file_boundary_without_allocation(tmp_path):
    source = tmp_path / 'large.txt'
    # Windows SetSparse avoids reserving 10 GiB; POSIX truncate is sparse by default.
    with source.open('wb') as stream:
        if __import__('sys').platform == 'win32':
            import ctypes, msvcrt
            returned = ctypes.c_ulong()
            handle = msvcrt.get_osfhandle(stream.fileno())
            ok = ctypes.windll.kernel32.DeviceIoControl(ctypes.c_void_p(handle), 0x900C4,
                None, 0, None, 0, ctypes.byref(returned), None)
            if not ok:
                pytest.skip('Filesystem does not support sparse test fixture')
        stream.truncate(MAX_BYTES)
    assert inspect_input(source) == 'text'
    with source.open('r+b') as stream:
        stream.truncate(MAX_BYTES + 1)
    with pytest.raises(ConversionError, match='too_large'):
        inspect_input(source)


def test_local_html_server_rejects_traversal_and_directory_listing(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'index.html').write_text('<p>hello</p>')
    (tmp_path / 'secret.txt').write_text('secret')
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(LocalDocumentHandler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urllib.request.urlopen(base + '/index.html') as response:
            assert b'hello' in response.read()
        for path in ('/', '/../secret.txt', '/%2e%2e/secret.txt'):
            with pytest.raises(urllib.error.HTTPError):
                urllib.request.urlopen(base + path)
    finally:
        server.shutdown()
        server.server_close()


def test_local_html_font_endpoint_only_serves_configured_font(tmp_path):
    root = tmp_path / 'documents'
    root.mkdir()
    font = tmp_path / 'vendor' / 'NotoSansSC-Regular.ttf'
    font.parent.mkdir()
    font.write_bytes(b'bundled font fixture')
    (root / '__any2pdf_font.ttf').write_bytes(b'shadowed document file')
    server = ThreadingHTTPServer(('127.0.0.1', 0),
        partial(LocalDocumentHandler, directory=str(root), font_path=font))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urllib.request.urlopen(base + '/__any2pdf_font.ttf') as response:
            assert response.read() == b'bundled font fixture'
            assert response.headers.get_content_type() == 'font/ttf'
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + '/../vendor/NotoSansSC-Regular.ttf')
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.integration
def test_real_html_pdf(tmp_path):
    from any2pdf.engines import capabilities
    if not capabilities()['html']:
        pytest.skip('Chromium not downloaded')
    source = tmp_path / 'page.html'
    source.write_text('<!doctype html><meta charset="utf-8"><h1>Local HTML</h1><p>你好</p>'
                      '<script>document.body.innerHTML="DOCUMENT SCRIPT RAN"</script>', encoding='utf-8')
    # A disabled-JavaScript promise regression must fail within a minute rather
    # than hanging the entire integration suite and leaking browser processes.
    import json
    import subprocess
    import sys
    from any2pdf.engines import kill_tree
    process = subprocess.Popen([sys.executable, '-c',
        'import json,sys; from any2pdf.core import convert; '
        'print(json.dumps(str(convert(sys.argv[1],sys.argv[2]))))',
        str(source), str(tmp_path / 'out')], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        stdout, stderr = process.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        kill_tree(process.pid)
        process.communicate(timeout=10)
        pytest.fail('HTML conversion exceeded 60 seconds with document scripts disabled')
    assert process.returncode == 0, stderr.decode('utf-8', errors='replace')
    result = Path(json.loads(stdout.decode('utf-8')))
    assert 'Local HTML' in PdfReader(result).pages[0].extract_text()
    assert '你好' in PdfReader(result).pages[0].extract_text()
    # System CJK fonts can hide a broken webfont fallback on developer PCs.
    # Both Latin and Chinese must actually use the bundled font in the PDF.
    fonts = PdfReader(result).pages[0]['/Resources']['/Font'].values()
    names = [str(font.get_object()['/BaseFont']).split('+')[-1] for font in fonts]
    assert names and all(name.startswith('NotoSansSC') for name in names), names


@pytest.mark.integration
def test_real_office_pdf(tmp_path):
    if not office_executable():
        pytest.skip('LibreOffice not downloaded')
    # Flat OpenDocument text supported by LibreOffice; zip a minimal ODT.
    import zipfile
    source = tmp_path / 'document.odt'
    with zipfile.ZipFile(source, 'w') as archive:
        archive.writestr('mimetype', 'application/vnd.oasis.opendocument.text')
        archive.writestr('META-INF/manifest.xml', '<?xml version="1.0"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>')
        archive.writestr('content.xml', '<?xml version="1.0" encoding="UTF-8"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2"><office:body><office:text><text:p>Office conversion test 你好</text:p></office:text></office:body></office:document-content>')
    result = convert(source, tmp_path / 'out')
    assert 'Office conversion test' in PdfReader(result).pages[0].extract_text()
    assert '你好' in PdfReader(result).pages[0].extract_text()
    assert not list((tmp_path / 'out').glob('.any2pdf-*'))
