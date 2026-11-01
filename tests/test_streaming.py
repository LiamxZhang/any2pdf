import builtins
import io
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
import pytest

from any2pdf.core import convert, validate_pdf


def test_validation_never_reads_entire_pdf_at_once(tmp_path, monkeypatch):
    source = tmp_path / 'input.pdf'
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(source)
    original_open = builtins.open
    class Guard:
        def __init__(self, stream):
            self.stream = stream
        def __getattr__(self, key):
            return getattr(self.stream, key)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def read(self, size=-1):
            assert 0 <= size < 8 * 1024 * 1024, 'Unbounded PDF read'
            return self.stream.read(size)
    def guarded_open(file, mode='r', *args, **kwargs):
        stream = original_open(file, mode, *args, **kwargs)
        return Guard(stream) if str(file).endswith('.pdf') and mode == 'rb' else stream
    monkeypatch.setattr(builtins, 'open', guarded_open)
    validate_pdf(source)


def test_ascii_prefix_does_not_misdetect_gb18030(tmp_path):
    source = tmp_path / 'encoded.txt'
    source.write_bytes(b'a' * 65536 + '\n中文'.encode('gb18030'))
    result = convert(source, tmp_path / 'out')
    with result.open('rb') as stream:
        assert len(PdfReader(stream).pages) > 0


def test_streaming_writer_does_not_retain_rendered_page_payloads(tmp_path):
    from any2pdf.streaming import StreamingCanvas
    target = tmp_path / 'out.pdf'
    pdf = StreamingCanvas(target, pagesize=(200, 200))
    for index in range(120):
        pdf.setFont('Helvetica', 10)
        pdf.drawString(10, 100, f'Page {index}')
        pdf.showPage()
        # Payloads must have reached disk before finalization.
        assert target.stat().st_size > 0
        assert len(pdf._canvas._doc.Pages.pages) == 0
    pdf.save()
    with target.open('rb') as stream:
        reader = PdfReader(stream)
        assert len(reader.pages) == 120
        assert 'Page 119' in reader.pages[-1].extract_text()


def test_streamed_pages_preserve_fonts_chinese_and_image_resources(tmp_path):
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.utils import ImageReader
    from any2pdf.core import text_font
    from any2pdf.streaming import StreamingCanvas
    font_file = Path(reportlab.__file__).parent / 'fonts/Vera.ttf'
    pdfmetrics.registerFont(TTFont('StreamingTestEmbedded', str(font_file)))
    target = tmp_path / 'resources.pdf'
    with StreamingCanvas(target, pagesize=(200, 200)) as pdf:
        for index in range(3):
            pdf.setFont('StreamingTestEmbedded', 10)
            pdf.drawString(10, 150, f'Embedded {index}')
            pdf.setFont(text_font(), 10)
            pdf.drawString(10, 130, '中文文本')
            pdf.drawImage(ImageReader(Image.new('RGB', (15, 20), 'blue')), 10, 10)
            pdf.showPage()
        pdf.save()
    with target.open('rb') as stream:
        reader = PdfReader(stream)
        assert len(reader.pages) == 3
        for index, page in enumerate(reader.pages):
            text = page.extract_text()
            assert f'Embedded {index}' in text
            assert '中文文本' in text
            assert len(page.images) == 1
            assert page.images[0].image.size == (15, 20)
            fonts = page['/Resources']['/Font'].get_object()
            assert any('/FontFile2' in font.get_object().get('/FontDescriptor', {})
                       for font in fonts.values())


def test_atomic_publication_fallback_preserves_collision(tmp_path, monkeypatch):
    import errno
    import os
    from any2pdf.core import publish
    source = tmp_path / 'temporary.pdf'
    source.write_bytes(b'complete new PDF')
    existing = tmp_path / 'result.pdf'
    existing.write_bytes(b'original PDF')
    def unsupported(*args):
        raise OSError(errno.ENOTSUP, 'Hard links unavailable')
    monkeypatch.setattr(os, 'link', unsupported)
    published = publish(source, tmp_path, 'result', lambda: False)
    assert existing.read_bytes() == b'original PDF'
    assert published.name == 'result (1).pdf'
    assert published.read_bytes() == b'complete new PDF'
    assert not source.exists()


def test_failed_atomic_publication_leaves_no_partial_output(tmp_path, monkeypatch):
    import errno
    from any2pdf import core
    source = tmp_path / 'temporary.pdf'
    source.write_bytes(b'complete new PDF')
    def unsupported(*args):
        raise OSError(errno.ENOTSUP, 'Atomic publication unavailable')
    monkeypatch.setattr(core.os, 'link', unsupported)
    monkeypatch.setattr(core, 'exclusive_rename', unsupported)
    with pytest.raises(OSError):
        core.publish(source, tmp_path, 'result', lambda: False)
    assert not (tmp_path / 'result.pdf').exists()
    assert source.read_bytes() == b'complete new PDF'


def test_cross_reference_stream_serializes_offsets_beyond_ten_billion(tmp_path):
    from any2pdf.streaming import StreamingCanvas
    target = tmp_path / 'wide-offsets.pdf'
    with StreamingCanvas(target) as pdf:
        pdf.drawString(10, 100, '64-bit cross references')
        pdf.showPage()
        # An unused synthetic index entry checks wide-offset serialization
        # without allocating or writing a multi-GiB test document.
        synthetic = pdf._reserve()
        pdf._offsets[synthetic] = 10**10 + 123
        pdf.save()
    data = target.read_bytes()
    stream_start = data.index(b'\nstream\n', data.index(b'/Type /XRef')) + len(b'\nstream\n')
    row = data[stream_start + synthetic * 11:stream_start + (synthetic + 1) * 11]
    assert row[0] == 1
    assert int.from_bytes(row[1:9], 'big') == 10**10 + 123


@pytest.mark.parametrize('lines,pages', [(51, 1), (102, 2), (103, 3)])
def test_exact_text_page_boundary_has_no_trailing_blank_page(tmp_path, lines, pages):
    source = tmp_path / 'lines.txt'
    source.write_text('line\n' * lines, encoding='utf-8')
    output = convert(source, tmp_path / 'out')
    with output.open('rb') as stream:
        reader = PdfReader(stream)
        assert len(reader.pages) == pages
        assert sum(page.extract_text().count('line') for page in reader.pages) == lines


@pytest.mark.parametrize('kind', ['image', 'pdf'])
@pytest.mark.parametrize('error,expected', [
    (PermissionError(13, 'Permission denied'), 'permission'),
    (OSError(28, 'No space left on device'), 'disk_full'),
])
def test_pdf_and_image_io_failures_keep_correct_reason(tmp_path, monkeypatch, kind, error, expected):
    from any2pdf import core
    from any2pdf.errors import ConversionError
    source = tmp_path / ('input.png' if kind == 'image' else 'input.pdf')
    def fail(*args, **kwargs):
        raise error
    if kind == 'image':
        Image.new('RGB', (10, 10), 'red').save(source)
        monkeypatch.setattr(core.StreamingCanvas, 'save', fail)
    else:
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(source)
        monkeypatch.setattr(core, 'PdfReader', fail)
    outdir = tmp_path / 'out'
    with pytest.raises(ConversionError) as caught:
        convert(source, outdir)
    assert caught.value.code == expected
    assert not list(outdir.iterdir())
