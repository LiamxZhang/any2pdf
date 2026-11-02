"""Exercise the frozen worker with real inputs; imports no application source."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def fixtures(root: Path) -> list[Path]:
    from PIL import Image
    from reportlab.pdfgen.canvas import Canvas

    (root / '中文 text.txt').write_text('Any2PDF smoke test\n中文转换测试\n', encoding='utf-8')
    (root / 'page.html').write_text('<!doctype html><meta charset="utf-8"><h1>Any2PDF HTML</h1><p>中文测试</p>', encoding='utf-8')
    Image.new('RGB', (320, 200), (40, 130, 200)).save(root / 'image.png')
    canvas = Canvas(str(root / 'existing.pdf'))
    canvas.drawString(72, 720, 'Any2PDF PDF smoke')
    canvas.save()
    (root / 'document.rtf').write_text(r'{\rtf1\ansi Any2PDF Office smoke\par Second paragraph}', encoding='ascii')
    # Minimal standards-based DOCX exercises OOXML import without python-docx.
    with zipfile.ZipFile(root / 'document.docx', 'w') as archive:
        archive.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Any2PDF DOCX smoke</w:t></w:r></w:p><w:sectPr/></w:body></w:document>')
    return sorted(p for p in root.iterdir() if p.is_file())


def main() -> None:
    if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    from pypdf import PdfReader, PdfWriter

    parser = argparse.ArgumentParser()
    parser.add_argument('executable', type=Path)
    parser.add_argument('--gui-smoke', action='store_true', help='Also launch the native Qt GUI and verify its screenshot')
    args = parser.parse_args()
    executable = args.executable.resolve()
    if not executable.is_file():
        raise SystemExit(f'Frozen executable missing: {executable}')
    bundle = executable.parents[2] if executable.parent.name == 'MacOS' else executable.parent
    office = list(bundle.rglob('soffice.exe')) + list(bundle.rglob('soffice'))
    single_file = executable.parent.name == 'dist'
    if not single_file and not office:
        raise RuntimeError('Frozen bundle is missing LibreOffice')
    if not single_file and not list(bundle.rglob('NotoSansSC-Regular.ttf')):
        raise RuntimeError('Frozen bundle is missing the Chinese font')
    with tempfile.TemporaryDirectory(prefix='any2pdf-smoke-') as folder:
        root = Path(folder)
        sources = fixtures(root)
        env = dict(os.environ)
        # A smoke test must prove the payload works without developer overrides
        # or the user's browser cache / installed LibreOffice.
        for key in ('ANY2PDF_VENDOR', 'ANY2PDF_LIBREOFFICE', 'PYTHONPATH', 'PLAYWRIGHT_BROWSERS_PATH'):
            env.pop(key, None)
        env.update(ANY2PDF_DATA=str(root / 'app-data'), LOCALAPPDATA=str(root / 'app-data'), XDG_DATA_HOME=str(root / 'app-data'))
        for index, source in enumerate(sources):
            result = root / f'result-{index}.json'
            request = root / f'request-{index}.json'
            request.write_text(json.dumps({'source': str(source), 'outdir': str(root / 'output'), 'result': str(result), 'cancel': str(root / 'cancel')}), encoding='utf-8')
            proc = subprocess.run([str(executable), '--worker', str(request)], cwd=root, env=env, timeout=240, capture_output=True)
            if not result.exists():
                raise RuntimeError(f'{source.name}: worker exited {proc.returncode} without result: {proc.stderr!r}')
            report = json.loads(result.read_text(encoding='utf-8'))
            if proc.returncode or report['status'] != 'success':
                raise RuntimeError(f'{source.name}: {report}')
            output = Path(report['output'])
            pdf = PdfReader(output)
            if not pdf.pages:
                raise RuntimeError(f'{source.name}: empty PDF')
            if source.suffix in ('.txt', '.html', '.docx', '.rtf', '.pdf') and 'Any2PDF' not in ''.join(page.extract_text() or '' for page in pdf.pages):
                raise RuntimeError(f'{source.name}: expected text missing from PDF')
            print(f'PASS {source.name}: {len(pdf.pages)} page(s)', flush=True)
        damaged = root / 'damaged.pdf'
        damaged.write_bytes(b'%PDF-1.7\nnot a PDF document')
        unsupported = root / 'unsupported.bin'
        unsupported.write_bytes(b'unsupported')
        encrypted = root / 'encrypted.pdf'
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.encrypt('smoke-secret')
        with encrypted.open('wb') as stream:
            writer.write(stream)
        for index, (source, expected) in enumerate(((damaged, 'invalid_pdf'), (unsupported, 'unsupported'), (encrypted, 'encrypted'))):
            result = root / f'error-result-{index}.json'
            request = root / f'error-request-{index}.json'
            request.write_text(json.dumps({'source': str(source), 'outdir': str(root / 'output'), 'result': str(result), 'cancel': str(root / 'cancel')}), encoding='utf-8')
            proc = subprocess.run([str(executable), '--worker', str(request)], cwd=root, env=env, timeout=240, capture_output=True)
            if not result.exists():
                raise RuntimeError(f'{source.name}: no error result; exit={proc.returncode}, stdout={proc.stdout!r}, stderr={proc.stderr!r}')
            report = json.loads(result.read_text(encoding='utf-8'))
            if proc.returncode == 0 or report.get('status') != 'failed' or report.get('error_code') != expected or report.get('output'):
                raise RuntimeError(f'{source.name}: expected {expected}; result={report}, stdout={proc.stdout!r}, stderr={proc.stderr!r}')
            print(f'PASS {source.name}: {expected}', flush=True)
        if args.gui_smoke:
            screenshot = root / 'gui-smoke.png'
            # Exercise the native platform plugin, including xcb under Xvfb.
            env.pop('QT_QPA_PLATFORM', None)
            try:
                proc = subprocess.run([str(executable), '--gui-smoke', str(screenshot)], cwd=root, env=env, timeout=240, capture_output=True)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f'GUI smoke timed out; stdout={exc.stdout!r}, stderr={exc.stderr!r}') from exc
            if proc.returncode or not screenshot.exists() or screenshot.stat().st_size < 100:
                raise RuntimeError(f'GUI smoke failed: exit={proc.returncode}, screenshot={screenshot.exists()}, stdout={proc.stdout!r}, stderr={proc.stderr!r}')
            from PIL import Image
            with Image.open(screenshot) as image:
                image.verify()
            print(f'PASS native GUI: {screenshot.stat().st_size} byte screenshot', flush=True)


if __name__ == '__main__':
    main()
