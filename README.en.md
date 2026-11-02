# Any2PDF

[简体中文](README.md) · [Portable downloads](https://github.com/LiamxZhang/any2pdf/releases) · [Builds](https://github.com/LiamxZhang/any2pdf/actions)

A local desktop PDF converter for Windows, Linux and macOS. Choose files or drag them into the window, convert a queue, and revisit results and clear failure explanations in persistent history. Chinese is the default; switch to English at any time. Files stay on your device.

## Run

Download the application for your OS from Releases; you do not need GitHub's automatically generated **Source code** archives. Windows provides one `.exe`; Linux provides one executable (run `chmod +x Any2PDF-0.1.2-Linux-x86_64` first). On macOS, extract the archive and open the single `Any2PDF.app`. End users do not install Python or conversion engines.

Windows/Linux executables automatically expand their runtime into a versioned cache under the application data directory on first launch. Later launches and conversions reuse it instead of unpacking again. First launch needs additional time and several GB of disk space. A missing cache is rebuilt automatically; upgrades use a separate cache. macOS keeps the native app bundle and uses an archive to preserve signing and internal links. Separate SHA-256 files are no longer published. Releases appear only after all three native tests and frozen smoke checks pass.

First-release targets are Windows 10/11 x86-64, Linux x86-64 with glibc 2.35+ and a normal desktop environment (Ubuntu 22.04 baseline), and macOS 12+ Apple Silicon. Intel macOS is not included. Linux still requires desktop graphics/font/audio libraries; see [runtime notes](THIRD_PARTY.md). Unsigned downloads may require your operating system's first-launch approval.

1. Add local files using Upload or drag and drop.
2. Choose an output folder on Convert and start the queue.
3. Open outputs, inspect failure diagnostics, or retry from History. Delete a selected history record or clear finished history without deleting originals or generated PDFs.

## Formats

- PDF validation and copy; JPEG, PNG, BMP, TIFF, WebP and GIF (multiple frames become pages).
- Plain text, CSV, JSON, Markdown, logs and common source code. UTF-8, BOM-marked UTF-16 and GB18030 are supported. CSV/Markdown use plain text layout.
- DOC/DOCX, XLS/XLSX, PPT/PPTX, ODT/ODS/ODP and RTF via bundled LibreOffice. Complex Microsoft Office layout may differ.
- HTML/HTM via bundled Chromium, prioritizing the bundled font for consistent Chinese rendering; typography may differ from the original. Scripts and external network resources are disabled; only resources in the source folder are served.

Maximum input size is **10 GiB (10,737,418,240 bytes)** per file. PDF/text input is read in blocks; generated text/image pages are written to disk incrementally. Page indexes, fonts, individual images and third-party engines still require resources. This size limit does not guarantee every 10 GiB document can be converted. Ensure sufficient memory and disk space. Each task has a two-hour timeout.

Unsupported formats, corrupt/encrypted files, missing engines, permissions, disk space, timeouts and worker crashes have explicit localized error messages and raw diagnostics. Existing PDFs are never overwritten; names receive a numeric suffix. Arbitrary proprietary formats are not promised.

## Data and development

Settings/history/logs are saved under `%LOCALAPPDATA%/Any2PDF` on Windows, `$XDG_DATA_HOME/Any2PDF` (default `~/.local/share/Any2PDF`) on Linux, and `~/Library/Application Support/Any2PDF` on macOS. Diagnostics contain local paths and engine output. Conversion engines are not a security sandbox for malicious documents.

```bash
python -m venv .venv
# Activate .venv for your shell.
python -m pip install -e ".[dev]"
python main.py
python -m pytest tests -q
python -m scripts.build --archive
```

Build on each target OS. The build script downloads pinned LibreOffice, Chromium and a Chinese font, retains legal notices, and creates the portable archive. Source mode can use an existing `soffice` or `ANY2PDF_LIBREOFFICE` override; frozen releases use bundled engines by default. Tag `v*` to build and publish after all native conversion and GUI tests pass; branch builds upload artifacts only. See [verification](docs/verification.md).

Application source is [MIT licensed](LICENSE). Dependencies retain their own licenses; see [THIRD_PARTY.md](THIRD_PARTY.md).
