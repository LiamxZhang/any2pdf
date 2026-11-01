# Third-party software in portable releases

Any2PDF's own source is MIT licensed. Bundled dependencies retain their own
licenses; the MIT license does not replace them. Release payloads retain engine
license files and copy Python distribution license/notice files to
`vendor/licenses`. PyInstaller puts vendor data under `_internal/vendor` on
Windows/Linux and the application resource directory on macOS.

| Component | License / source |
| --- | --- |
| LibreOffice 25.8.7.2 | MPL 2.0 / LGPL 3+ and component licenses, retained in the complete distribution; [source archive](https://downloadarchive.documentfoundation.org/libreoffice/old/25.8.7.2/src/) |
| Microsoft Visual C++ runtime DLLs supplied in the official LibreOffice Windows MSI | Original Microsoft terms retained with the LibreOffice payload; x64 DLLs are copied into LibreOffice's program directory for application-local loading |
| Qt 6 / PySide6 / shiboken6 6.8.3 | LGPL 3 / GPL / commercial, including Qt module notices; [Qt LGPL obligations](https://www.qt.io/licensing/open-source-lgpl-obligations), [PySide source](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.8.3-src/) |
| Playwright 1.56.0 | Apache 2.0; [source](https://github.com/microsoft/playwright/tree/v1.56.0) |
| Chromium (revision pinned by Playwright 1.56.0) | BSD and numerous component licenses; retain browser `LICENSE*` / `credits*` files; [source](https://chromium.googlesource.com/chromium/src/) |
| Noto Sans SC | SIL Open Font License 1.1; retained `vendor/fonts/OFL.txt`; [pinned source](https://github.com/google/fonts/tree/a85815a42757630ce188fdad368c2dfc444d4773/ofl/notosanssc) |
| Pillow | HPND and component notices |
| ReportLab | BSD |
| pypdf | BSD 3-Clause |
| psutil | BSD 3-Clause |
| pyee | MIT |
| greenlet | MIT / Python Software Foundation License |
| charset-normalizer | MIT |
| typing_extensions | Python Software Foundation License |
| CPython | Python Software Foundation License and component notices |
| PyInstaller bootloader | GPL 2+ with the bootloader distribution exception |

LibreOffice is unmodified and runs as a separate executable. Its original
distribution and notices are retained. Official archive mirror metadata
publishes SHA-256 (not SHA-512); native downloads are checked against pinned
SHA-256 values. Engine download metadata is retained in its bundle.

Qt libraries are dynamically linked in an unpacked directory. Users may
replace compatible LGPL libraries and reverse engineer the application to
debug such modifications, as permitted by LGPL 3. The Python source and build
scripts allow rebuilding Any2PDF with modified compatible Qt/PySide libraries.
No additional restriction on these LGPL rights is imposed by Any2PDF.

The Noto variable font is instantiated at weight 400 into a static TrueType font
for ReportLab; it remains OFL licensed. Its source commit is recorded in
`vendor/versions.json`. No proprietary Microsoft Office or Microsoft fonts are
distributed.

Linux releases target x86-64 desktop distributions with glibc 2.35 or newer
(Ubuntu 22.04 baseline). As with Qt and Chromium desktop applications, host
graphics, fontconfig, NSS, D-Bus and audio system libraries must be available;
the release smoke test checks Ubuntu 22.04. This is not a static Linux binary.
macOS releases target Apple Silicon. Unsigned Windows/macOS binaries may
require the operating system's normal downloaded-app approval.
