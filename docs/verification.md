# Verification record

Date: 2026-11-01. Development host: Windows x86-64, Python 3.12.4.

## Local evidence

`python -m pytest tests -q` with complete local engines: **51 passed, 1 skipped** (68.04 seconds). The skip is a symlink-copy test requiring Windows symlink privileges; Linux/macOS exercise it. Both real Office and HTML conversions passed, including Chinese text extraction. Later build/CI evidence should supersede this count.

Verified behavior includes exact 10 GiB admission and >10 GiB rejection using a sparse file; this is a size-boundary test, not an arbitrary 10 GiB Office conversion claim. Text and PDF input use bounded reads. Rendered text/image pages are serialized to disk independently. Metadata, page indexes and a single decoded image/font remain memory consumers.

Tests exercise real Chinese text, GB18030 after a long ASCII prefix, embedded TrueType fonts, decoded image resources, multi-frame TIFF, existing PDF copy, corrupt/encrypted PDF failure, collision-safe publication, atomic publication without hard links, cancellation, SQLite interrupted-session recovery, default Chinese/live English and persisted preference, localized failure reasons and real subprocess completion.

## Native release gate

`.github/workflows/release.yml` builds Windows x86-64, Linux x86-64 and macOS arm64 independently, with pinned LibreOffice, Playwright Chromium and Chinese font. Each target runs the test suite, builds its portable payload, reruns tests with engines present, then converts text, image, PDF, HTML, RTF and DOCX using the frozen executable. It verifies unsupported/corrupt/encrypted failures and launches the native Qt GUI to capture a screenshot. Linux uses Xvfb with the xcb plugin, rather than substituting an offscreen platform plugin.

The publish job requires all native builds and smoke checks to succeed. Source publication alone does not prove portable release readiness. Check the repository Actions and Releases for the actual result.

## Practical limits

- Initial supported architectures are Windows/Linux x86-64 and macOS Apple Silicon. Intel macOS and Linux ARM are not bundled.
- Linux needs a glibc 2.35+ desktop environment and system graphics/audio/font libraries, documented in THIRD_PARTY.md.
- Native signing/notarization certificates are not configured. Standard OS downloaded-app approval may be required.
- Office layout depends on LibreOffice. HTML excludes scripts and remote resources. CSV and Markdown use plain text layout.
- No claim is made that every private format, encrypted file, pathological document, or 10 GiB input can be converted on all machines. Engine failures remain explicit and diagnostic.
