from pathlib import Path
import json
import threading

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

from any2pdf.core import MAX_BYTES, convert, inspect_input
from any2pdf.errors import ConversionError, explain
from any2pdf.history import History


def test_exact_size_boundary():
    assert inspect_input(Path('large.txt'), size=10 * 1024**3) == 'text'
    with pytest.raises(ConversionError, match='too_large'):
        inspect_input(Path('large.txt'), size=MAX_BYTES + 1)


def test_unsupported_file_has_localized_reason(tmp_path):
    source = tmp_path / 'archive.zip'
    source.write_bytes(b'zip')
    with pytest.raises(ConversionError) as err:
        convert(source, tmp_path / 'out')
    assert err.value.code == 'unsupported'
    assert '格式' in explain(err.value.code, 'zh')
    assert 'format' in explain(err.value.code, 'en').lower()
    assert not (tmp_path / 'out').exists()


def test_chinese_text_conversion_and_name_collision(tmp_path):
    source = tmp_path / '报告.txt'
    source.write_text('你好，世界！\n' + 'hello world\n' * 180, encoding='utf-8')
    out = tmp_path / 'out'
    first = convert(source, out)
    second = convert(source, out)
    assert first != second
    assert len(PdfReader(first).pages) >= 3
    assert 'hello world' in PdfReader(first).pages[0].extract_text()
    assert not list(out.glob('.any2pdf-*'))


def test_multiframe_tiff(tmp_path):
    source = tmp_path / 'scans.tiff'
    a = Image.new('RGB', (30, 40), 'white')
    b = Image.new('RGB', (40, 30), 'blue')
    a.save(source, save_all=True, append_images=[b])
    result = convert(source, tmp_path / 'out')
    assert len(PdfReader(result).pages) == 2


def test_pdf_copy_preserves_original(tmp_path):
    source = tmp_path / 'input.pdf'
    w = PdfWriter()
    w.add_blank_page(width=100, height=100)
    w.write(source)
    before = source.read_bytes()
    result = convert(source, tmp_path)
    assert result != source
    assert result.read_bytes() == before == source.read_bytes()


@pytest.mark.parametrize('encrypted', [False, True])
def test_bad_pdf_reason_and_cleanup(tmp_path, encrypted):
    source = tmp_path / 'bad.pdf'
    if encrypted:
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.encrypt('secret')
        writer.write(source)
    else:
        source.write_bytes(b'not a PDF')
    with pytest.raises(ConversionError) as err:
        convert(source, tmp_path / 'out')
    assert err.value.code == ('encrypted' if encrypted else 'invalid_pdf')
    assert not list((tmp_path / 'out').glob('*.pdf'))
    assert not list((tmp_path / 'out').glob('.any2pdf-*'))


def test_cancellation_prevents_output(tmp_path):
    source = tmp_path / 'note.txt'
    source.write_text('test')
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ConversionError, match='cancelled'):
        convert(source, tmp_path / 'out', cancelled=cancel.is_set)
    assert not list((tmp_path / 'out').glob('*.pdf'))


def test_history_recovers_interrupted_jobs_and_keeps_diagnostics(tmp_path):
    h = History(tmp_path / 'history.db')
    task = h.add('/a/report.docx', '/out')
    h.update(task, status='running')
    h.close()
    h = History(tmp_path / 'history.db')
    row = h.list()[0]
    assert row['status'] == 'failed'
    assert row['error_code'] == 'interrupted'
    h.update(task, status='failed', error_code='engine_failed', detail='exit code 1')
    assert h.list()[0]['detail'] == 'exit code 1'
    h.clear_finished()
    assert h.list() == []
    h.close()


def test_missing_office_engine_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv('ANY2PDF_LIBREOFFICE', str(tmp_path / 'missing'))
    source = tmp_path / 'report.docx'
    source.write_bytes(b'invalid')
    with pytest.raises(ConversionError) as err:
        convert(source, tmp_path / 'out')
    assert err.value.code == 'missing_office'
