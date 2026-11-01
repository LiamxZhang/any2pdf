"""Write completed PDF pages to disk, retaining only object offsets and page IDs.

ReportLab renders one page at a time. Each independent page's resource graph is
copied immediately, preserving encoded image/font streams without recompression.
"""
from io import BytesIO

from pypdf import PdfReader
from pypdf.generic import (ArrayObject, DictionaryObject, IndirectObject,
                          NameObject, NumberObject, StreamObject)
from reportlab.pdfgen.canvas import Canvas


class StreamingCanvas:
    def __init__(self, target, pagesize=None):
        self._stream = open(target, 'wb')
        self._stream.write(b'%PDF-1.7\n%\xe2\xe3\xcf\xd3\n')
        self._offsets = [0, 0, 0]  # catalog and pages tree are written last
        self._pages = []
        self._pagesize = pagesize
        self._reset()

    def _reset(self):
        self._buffer = BytesIO()
        self._canvas = Canvas(self._buffer, pagesize=self._pagesize, pageCompression=1)
        self._has_content = False

    def drawString(self, *args, **kwargs):
        self._has_content = True
        return self._canvas.drawString(*args, **kwargs)

    def drawImage(self, *args, **kwargs):
        self._has_content = True
        return self._canvas.drawImage(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._canvas, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._stream.close()

    def _reserve(self):
        self._offsets.append(0)
        return len(self._offsets) - 1

    def _write(self, number, obj):
        self._offsets[number] = self._stream.tell()
        self._stream.write(f'{number} 0 obj\n'.encode('ascii'))
        obj.write_to_stream(self._stream)
        self._stream.write(b'\nendobj\n')

    def showPage(self):
        self._pagesize = self._canvas._pagesize
        self._canvas.showPage()
        self._canvas.save()
        self._buffer.seek(0)
        reader = PdfReader(self._buffer)
        page = reader.pages[0]
        number = self._reserve()
        mapping = {(page.indirect_reference.idnum, page.indirect_reference.generation): number}
        pending = []

        def clone(obj):
            if isinstance(obj, IndirectObject):
                key = (obj.idnum, obj.generation)
                if key not in mapping:
                    mapping[key] = self._reserve()
                    pending.append((mapping[key], obj))
                return IndirectObject(mapping[key], 0, None)
            if isinstance(obj, DictionaryObject):
                copied = StreamObject() if isinstance(obj, StreamObject) else DictionaryObject()
                if isinstance(obj, StreamObject):
                    copied._data = obj._data
                for key, value in obj.items():
                    copied[key] = clone(value)
                return copied
            if isinstance(obj, ArrayObject):
                return ArrayObject(clone(value) for value in obj)
            return obj

        # Do not copy the input's page tree (which points back to this page).
        page.pop('/Parent', None)
        copied = clone(page)
        copied[NameObject('/Parent')] = IndirectObject(2, 0, None)
        self._write(number, copied)
        while pending:
            object_number, reference = pending.pop()
            self._write(object_number, clone(reference.get_object()))
        self._pages.append(number)
        self._stream.flush()
        self._reset()

    def save(self):
        if self._has_content or not self._pages:
            self.showPage()
        pages = DictionaryObject({NameObject('/Type'): NameObject('/Pages'),
            NameObject('/Count'): NumberObject(len(self._pages)),
            NameObject('/Kids'): ArrayObject(IndirectObject(n, 0, None) for n in self._pages)})
        self._write(2, pages)
        self._write(1, DictionaryObject({NameObject('/Type'): NameObject('/Catalog'),
                                       NameObject('/Pages'): IndirectObject(2, 0, None)}))
        # PDF 1.5+ cross-reference streams allow 64-bit offsets. Emit each row
        # directly instead of buffering a second copy of the complete index.
        xref_number = self._reserve()
        xref = self._stream.tell()
        self._offsets[xref_number] = xref
        size = len(self._offsets)
        self._stream.write((f'{xref_number} 0 obj\n<< /Type /XRef /Size {size} '
                            f'/Root 1 0 R /W [1 8 2] /Length {size * 11} >>\nstream\n').encode('ascii'))
        self._stream.write(b'\x00' + bytes(8) + b'\xff\xff')
        for offset in self._offsets[1:]:
            self._stream.write(b'\x01' + offset.to_bytes(8, 'big') + b'\x00\x00')
        self._stream.write(f'\nendstream\nendobj\nstartxref\n{xref}\n%%EOF\n'.encode('ascii'))
        self._stream.close()
