# Interface and portable release refinement

User requested removal of branding, slogans, privacy/offline badges and verbose upload instructions; drag hover/release feedback; individual history deletion; a white language popup independent of OS appearance; removal of separate release checksum assets; and compact application downloads without source.

Implement a drop area with a highlighted border and localized release prompt, preserving batch selection and persistent conversion errors. Keep only selection, drop prompt, file count and size cap on Upload. Delete finished records individually with a database guard against deleting active/queued tasks, and preserve input/output files. Explicit popup styles and palette use white in both OS modes.

Windows/Linux will package the complete runtime and untouched engine trees in a PyInstaller onefile executable. Append engine DATA entries after analysis to avoid native binary rewriting; a runtime hook restores executable permissions from a build-time manifest on Linux. Workers reuse the parent's extracted runtime. macOS retains its signed app bundle. Release assets contain executables or the macOS app archive, without separate checksum files. GitHub-generated source links are automatic; users are directed to application assets.

Verification: UI drag-enter/leave/drop tests, history deletion/file retention tests, complete suite, real onefile conversions and errors, native GUI smoke on all targets, and release asset inspection. Single-file startup needs temporary extraction and sufficient disk space; disclose this on the download page.
