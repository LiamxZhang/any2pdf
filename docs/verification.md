# Verification record

Date: 2026-11-01. Development host: Windows x86-64, Python 3.12.4.

## Local evidence

`python -m pytest tests -q` with complete local engines: **51 passed, 1 skipped** (68.04 seconds). The skip is a symlink-copy test requiring Windows symlink privileges; Linux/macOS exercise it. Both real Office and HTML conversions passed, including Chinese text extraction. Later build/CI evidence should supersede this count.

Verified behavior includes exact 10 GiB admission and >10 GiB rejection using a sparse file; this is a size-boundary test, not an arbitrary 10 GiB Office conversion claim. Text and PDF input use bounded reads. Rendered text/image pages are serialized to disk independently. Metadata, page indexes and a single decoded image/font remain memory consumers.

Tests exercise real Chinese text, GB18030 after a long ASCII prefix, embedded TrueType fonts, decoded image resources, multi-frame TIFF, existing PDF copy, corrupt/encrypted PDF failure, collision-safe publication, atomic publication without hard links, cancellation, SQLite interrupted-session recovery, default Chinese/live English and persisted preference, localized failure reasons and real subprocess completion.

## Native release gate

`.github/workflows/release.yml` builds Windows x86-64, Linux x86-64 and macOS arm64 independently, with pinned LibreOffice, Playwright Chromium and Chinese font. Each target runs the test suite, builds its portable payload, reruns tests with engines present, then converts text, image, PDF, HTML, RTF and DOCX using the frozen executable. It verifies unsupported/corrupt/encrypted failures and launches the native Qt GUI to capture a screenshot. Linux uses Xvfb with the xcb plugin, rather than substituting an offscreen platform plugin.

The publish job requires all native builds and smoke checks to succeed. Source publication alone does not prove portable release readiness. Check the repository Actions and Releases for the actual result.

## Published native evidence

Verified on 2026-11-02 (Asia/Shanghai): [release v0.1.0](https://github.com/LiamxZhang/any2pdf/releases/tag/v0.1.0) is public, not a draft. [Native workflow 41274766910](https://github.com/LiamxZhang/any2pdf/actions/runs/41274766910) completed successfully on commit `8f42dcf08a5f95e8c1727095fe4290fdfa30f965`.

| Native host | Complete-engine tests | Frozen conversion / error checks | Native GUI |
| --- | --- | --- | --- |
| Windows x86-64 | 52 passed | Passed | Passed |
| Linux x86-64 / Ubuntu 22.04 | 52 passed | Passed | Passed (xcb under Xvfb) |
| macOS arm64 | 52 passed | Passed | Passed |

Each frozen executable converted DOCX, RTF, existing PDF, PNG, local HTML and Chinese TXT; rejected damaged PDF, unsupported input and encrypted PDF with the expected specific error codes. Real engine tests also verified Chinese HTML text extraction and embedded NotoSansSC font identity. All three archives and their SHA-256 files were uploaded at initial publication. Separate checksum assets were removed on 2026-11-02 at the user's request.

## Practical limits

- Initial supported architectures are Windows/Linux x86-64 and macOS Apple Silicon. Intel macOS and Linux ARM are not bundled.
- Linux needs a glibc 2.35+ desktop environment and system graphics/audio/font libraries, documented in THIRD_PARTY.md.
- Native signing/notarization certificates are not configured. Standard OS downloaded-app approval may be required.
- Office layout depends on LibreOffice. HTML excludes scripts and remote resources. CSV and Markdown use plain text layout.
- No claim is made that every private format, encrypted file, pathological document, or 10 GiB input can be converted on all machines. Engine failures remain explicit and diagnostic.


## v0.1.1 interface and single-file verification

Date: 2026-11-02 (Asia/Shanghai). Native [workflow 41375753426](https://github.com/LiamxZhang/any2pdf/actions/runs/41375753426), application commit `846e78382eac33c157bc70c1f509d363bc99bde2`.

- Windows, Linux and macOS complete-engine suites: **55 passed each**.
- All three packaged apps passed DOCX, RTF, PDF, PNG, HTML and Chinese TXT conversions, explicit damaged/unsupported/encrypted errors, and native GUI screenshot checks. Windows/Linux exercised the new onefile executable, not a neighboring engine folder.
- Local full suite: 54 passed, 1 skipped (Windows symlink privilege). Focused UI suite: 8 passed, including real Qt drag-enter/leave/drop events and single-record deletion preserving other records and source/output files.
- A dark application palette was applied before opening the language popup; a pixel sampled in the unselected popup row was `#ffffff`.
- Windows and Linux package untouched engines as DATA after PyInstaller analysis; Linux executable permissions are restored from a build-time manifest. macOS keeps its signed app bundle. All runtime licenses remain bundled; project source is not a required end-user download.
- Single-file startup includes automatic extraction. Windows CI cold starts took approximately 50–80 seconds per standalone invocation; GUI-launched workers reuse the running application's extraction. Linux cold starts were approximately 6–9 seconds. Allow several GB of temporary disk space.
- Separate SHA-256 release files are no longer generated. GitHub's automatic source archive links remain platform-generated, and the download instructions direct users to the application assets.

Published release confirmed: [v0.1.1](https://github.com/LiamxZhang/any2pdf/releases/tag/v0.1.1). All three application assets are uploaded; there are no standalone checksum assets.


## v0.1.2 startup and selection verification

Date: 2026-11-02 (Asia/Shanghai). Application commit `701917509e41f402cffce1bb751ce93631c4ff77`; [native workflow 41386520687](https://github.com/LiamxZhang/any2pdf/actions/runs/41386520687).

All three complete-engine suites passed **66 tests each**, followed by frozen DOCX, RTF, PDF, PNG, HTML and Chinese TXT conversions, expected corrupt/unsupported/encrypted failure codes, and native GUI screenshot capture. Windows/Linux checks also verified that multiple independent processes reuse the same completed runtime cache without changing its completion marker. Test cache cleanup passed using Windows extended paths.

Local suite: **65 passed, 1 skipped** (Windows symlink privilege). New tests cover selected-row colors after focus loss on both tables, selection retention after refresh, removal of the upload size caption, no-Playwright capability probing, cached-runtime reuse/recovery, concurrent launch serialization, and unsafe archive-path rejection.

Windows native cached sample totals were 1.17 s (PDF), 1.12 s (PNG), 1.20 s (TXT), and 3.91 s (HTML). Its first DOCX invocation, including cache creation, took 54.25 s; Office conversion within it took 14.27 s. These are samples, not general conversion guarantees. See [performance investigation](performance.md) for local before/after measurements and first-launch/storage tradeoffs.

The upload size caption is removed while the stat-based 10 GiB admission boundary remains unchanged. The application still downloads as one executable on Windows/Linux and a native .app archive on macOS. No independent checksum assets are generated.

Published release confirmed: [v0.1.2](https://github.com/LiamxZhang/any2pdf/releases/tag/v0.1.2), with all three application assets uploaded and no separate checksum assets.
