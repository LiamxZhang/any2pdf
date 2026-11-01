"""Bounded input processing and no-overwrite output publication."""
import codecs
import errno
import os
from pathlib import Path
import shutil
import tempfile
import warnings
import sys

from PIL import Image, ImageSequence
from pypdf import PdfReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont

from .errors import ConversionError
from .paths import vendor_root
from .streaming import StreamingCanvas

MAX_BYTES = 10 * 1024**3
TEXT = set('txt csv json md markdown log py js ts tsx jsx c h cpp hpp java rs go sh yaml yml toml xml ini cfg sql css tex r srt'.split())
IMAGES = {'jpg', 'jpeg', 'png', 'bmp', 'tif', 'tiff', 'webp', 'gif'}
OFFICE = set('doc docx xls xlsx ppt pptx odt ods odp rtf'.split())


def inspect_input(source, size=None):
    source = Path(source)
    if size is None:
        if not source.is_file():
            raise ConversionError('missing_file', source)
        size = source.stat().st_size
    if size > MAX_BYTES:
        raise ConversionError('too_large', f'{size:,} bytes > {MAX_BYTES:,} bytes')
    ext = source.suffix.lower().lstrip('.')
    for extensions, kind in ((TEXT, 'text'), (IMAGES, 'image'), (OFFICE, 'office'),
                             ({'pdf'}, 'pdf'), ({'html', 'htm'}, 'html')):
        if ext in extensions:
            return kind
    raise ConversionError('unsupported', source.suffix or '(no extension)')


def check_cancel(cancelled):
    if cancelled():
        raise ConversionError('cancelled')


def validate_pdf(path):
    try:
        with open(path, 'rb') as stream:
            reader = PdfReader(stream)
            if reader.is_encrypted:
                raise ConversionError('encrypted')
            if not len(reader.pages):
                raise ConversionError('invalid_pdf', 'PDF has no pages')
    except ConversionError:
        raise
    except OSError:
        raise
    except Exception as exc:
        raise ConversionError('invalid_pdf', exc) from exc


def copy_stream(source, target, cancelled):
    with open(source, 'rb') as inp, open(target, 'wb') as out:
        while chunk := inp.read(1024 * 1024):
            check_cancel(cancelled)
            out.write(chunk)


def text_font():
    font = vendor_root() / 'fonts/NotoSansSC-Regular.ttf'
    name = 'Any2PDF-CJK' if font.exists() else 'STSong-Light'
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, str(font)) if font.exists() else UnicodeCIDFont(name))
    return name


def text_encoding(source, cancelled=lambda: False):
    with open(source, 'rb') as stream:
        sample = stream.read(65536)
    utf16 = sample.startswith(codecs.BOM_UTF16_LE) or sample.startswith(codecs.BOM_UTF16_BE)
    if not utf16 and b'\x00' in sample:
        raise ConversionError('text_encoding', 'NUL byte in text input')
    for encoding in (('utf-16',) if utf16 else ('utf-8-sig', 'gb18030')):
        try:
            decoder = codecs.getincrementaldecoder(encoding)()
            with open(source, 'rb') as stream:
                while block := stream.read(65536):
                    check_cancel(cancelled)
                    if not utf16 and b'\x00' in block:
                        raise ConversionError('text_encoding', 'NUL byte in text input')
                    decoder.decode(block, final=False)
                decoder.decode(b'', final=True)
            return encoding
        except UnicodeError:
            pass
    raise ConversionError('text_encoding')


def text_pdf(source, target, cancelled):
    font = text_font()
    encoding = text_encoding(source, cancelled)
    pdf = StreamingCanvas(target, pagesize=(595.28, 841.89))
    pdf.setTitle(source.name)
    pdf.setFont(font, 10)
    y, width_used, line = 795, 0, []
    def flush_line():
        nonlocal y, width_used
        pdf.drawString(42, y, ''.join(line))
        line.clear()
        width_used = 0
        y -= 15
        if y < 42:
            pdf.showPage()
            pdf.setFont(font, 10)
            y = 795
    # Read fixed-size blocks, including documents with a single enormous line.
    try:
        with open(source, 'r', encoding=encoding, newline=None) as stream:
            while block := stream.read(8192):
                check_cancel(cancelled)
                # At most one fixed block in memory; wrap without building a full input line.
                for char in block:
                    if char == '\r':
                        continue
                    if char == '\t':
                        char = '    '
                    width = pdfmetrics.stringWidth(char, font, 10)
                    if char == '\n' or width_used + width > 511:
                        flush_line()
                        if char == '\n':
                            continue
                    line.append(char)
                    width_used += width
        if line:
            flush_line()
        pdf.save()
    except UnicodeError as exc:
        raise ConversionError('text_encoding', exc) from exc
    finally:
        pdf.close()


def image_pdf(source, target, cancelled):
    from reportlab.lib.utils import ImageReader
    pdf = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(source) as img:
                pdf = StreamingCanvas(target)
                for frame in ImageSequence.Iterator(img):
                    check_cancel(cancelled)
                    rgb = frame.convert('RGB')
                    w, h = rgb.size
                    scale = min(1, 14000 / max(w, h))
                    pw, ph = max(1, w * scale), max(1, h * scale)
                    pdf.setPageSize((pw, ph))
                    pdf.drawImage(ImageReader(rgb), 0, 0, width=pw, height=ph)
                    pdf.showPage()
                    rgb.close()
                pdf.save()
    except ConversionError:
        raise
    except OSError as exc:
        if isinstance(exc, PermissionError) or exc.errno == errno.ENOSPC:
            raise
        raise ConversionError('invalid_image', exc) from exc
    except Exception as exc:
        raise ConversionError('invalid_image', exc) from exc
    finally:
        if pdf is not None:
            pdf.close()


def exclusive_rename(source, target):
    """Atomic publication on volumes without hard links; never overwrite."""
    if sys.platform == 'win32':
        os.rename(source, target)  # Windows rename fails if target exists.
        return
    import ctypes
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith('linux') and hasattr(library, 'renameat2'):
        rename = library.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = rename(-100, os.fsencode(source), -100, os.fsencode(target), 1)
    elif sys.platform == 'darwin' and hasattr(library, 'renamex_np'):
        rename = library.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = rename(os.fsencode(source), os.fsencode(target), 4)
    else:
        raise OSError(errno.ENOTSUP, 'Atomic no-overwrite publication is unavailable')
    if result:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(target))


def publish(temp, outdir, stem, cancelled):
    counter = 0
    while True:
        check_cancel(cancelled)
        path = outdir / f"{stem}{f' ({counter})' if counter else ''}.pdf"
        try:
            # Temp lives on the output volume. A hardlink atomically reserves the name.
            os.link(temp, path)
            return path
        except FileExistsError:
            counter += 1
        except OSError as exc:
            if exc.errno not in (errno.EPERM, errno.ENOTSUP, errno.EACCES, errno.EXDEV):
                raise
            try:
                check_cancel(cancelled)
                exclusive_rename(temp, path)
                return path
            except FileExistsError:
                counter += 1


def convert(source, outdir, cancelled=lambda: False, progress=lambda stage: None,
            workspace_prefix='.any2pdf-'):
    source, outdir = Path(source).resolve(), Path(outdir).resolve()
    try:
        kind = inspect_input(source)
        check_cancel(cancelled)
        outdir.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(outdir).free < 16 * 1024**2:
            raise ConversionError('disk_full', 'Less than 16 MiB available')
        with tempfile.TemporaryDirectory(prefix=workspace_prefix, dir=outdir) as workspace:
            temp = Path(workspace) / 'result.pdf'
            progress(kind)
            if kind == 'pdf':
                validate_pdf(source)
                copy_stream(source, temp, cancelled)
            elif kind == 'text':
                text_pdf(source, temp, cancelled)
            elif kind == 'image':
                image_pdf(source, temp, cancelled)
            else:
                from .engines import office_pdf, html_pdf
                (office_pdf if kind == 'office' else html_pdf)(source, temp, cancelled)
            check_cancel(cancelled)
            validate_pdf(temp)
            progress('saving')
            return publish(temp, outdir, source.stem, cancelled)
    except ConversionError:
        raise
    except PermissionError as exc:
        raise ConversionError('permission', exc) from exc
    except FileNotFoundError as exc:
        raise ConversionError('missing_file', exc) from exc
    except OSError as exc:
        raise ConversionError('disk_full' if exc.errno == errno.ENOSPC else 'unknown', exc) from exc
    except Exception as exc:
        raise ConversionError('unknown', exc) from exc
