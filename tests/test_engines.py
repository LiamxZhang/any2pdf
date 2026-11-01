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


@pytest.mark.integration
def test_real_html_pdf(tmp_path):
    from any2pdf.engines import capabilities
    if not capabilities()['html']:
        pytest.skip('Chromium not downloaded')
    source = tmp_path / 'page.html'
    source.write_text('<!doctype html><meta charset="utf-8"><h1>Local HTML</h1><p>你好</p>', encoding='utf-8')
    result = convert(source, tmp_path / 'out')
    assert 'Local HTML' in PdfReader(result).pages[0].extract_text()


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
