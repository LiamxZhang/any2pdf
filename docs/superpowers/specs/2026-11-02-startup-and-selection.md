# Startup, conversion and selection improvements

Requested: remove the upload size caption, provide clear selection feedback on both tables, investigate startup/conversion speed. Reducing the input limit to 5 GB is optional if needed.

Measured root cause: the prior onefile runtime includes about 2 GB of engines and expands/cleans them on every standalone run. Local old-package small-text end-to-end invocation took 146.83 seconds, while its worker reported 0.078 seconds conversion. Lowering a stat-only size cap cannot address this overhead.

Keep the 10 GiB cap and remove its upload caption. Use purple/white selected rows in active and inactive window states. Test selection persistence across refresh and focus changes.

Windows/Linux keep one downloaded executable. A small standard-library bootstrap reads a ZIP overlay and extracts the native onedir runtime once to an application-owned content-keyed cache. Stream entries, reject unsafe paths/symlinks, restore POSIX executable modes, verify ZIP CRCs, serialize concurrent launches via OS locks, publish a completion marker atomically with the runtime directory. Later launches check the marker and executable and reuse the cache. Missing executables trigger recovery. Versions coexist. The PyInstaller EOF cookie is updated to retain its original TOC and avoid backwards scanning through the large overlay; validate both archive readers and native bootloader execution.

macOS retains its signed app. Startup capability checks use known executable paths without starting Playwright. Text layout caches at most 4096 character widths, retaining streaming, cancellation and encoding behavior.

Validation: compare identical text fixtures and packaged CLI/GUI runs; run full tests and all three native build/conversion/error/GUI checks; assert the cache completion marker does not change between conversions. Publish v0.1.2 only after those checks pass.
