# v0.1.2 performance investigation

Date: 2026-11-02. Local host: Windows x86-64, Python 3.12.4. These are sample measurements, not latency guarantees.

## Root causes

The v0.1.1 onefile download contains about 2 GB of expanded runtime and engines. A standalone process repeatedly decompresses thousands of files and removes them on exit. A small text fixture spent only about 0.078 seconds inside conversion but took 146.83 seconds from process launch to exit locally. The input-size admission check uses file metadata; reducing its 10 GiB cap would not address this overhead.

Startup also called Playwright to probe engine availability and recursively searched for Office. v0.1.2 checks native executable paths without launching the Playwright driver. Repeated text characters previously performed repeated font-width calculations.

## Changes

Windows/Linux remain one downloaded executable. A small bootstrap expands a versioned native runtime once to the user's application-data cache, then directly launches that runtime. The cache is reused between launches and worker invocations, supports concurrent launch locking and interrupted/missing-cache recovery, and retains native executable permissions and licenses. macOS retains the signed app bundle.

Text layout caches at most 4096 character widths, preserving bounded input reads and incremental PDF output. Office processes and browser rendering still incur their native startup and processing costs; complex files can remain slow.

## Local measurements

| Measurement | v0.1.1 | v0.1.2 |
| --- | --- | --- |
| Small ASCII text, standalone process launch to exit | 146.83 s | First expansion: 45.60 s; cached: 1.15 s |
| Same fixture, worker-reported conversion | 0.078 s | 0.078 s |
| Repeated Chinese/Latin text layout, fonts already registered, median of 3 alternating runs | 0.668 s | 0.561 s |

A cached native GUI smoke invocation took 6.73 s, including its deliberately scheduled 0.75 s screenshot delay. This is not directly comparable to the text-process benchmark.

A complete frozen smoke rerun passed DOCX, RTF, PDF, PNG, HTML, Chinese TXT, unsupported/corrupt/encrypted error cases, native GUI capture, and cache-marker reuse checks. After the initial expansion, local PDF/image/text samples took approximately 1.1 s each end-to-end; HTML took 6.34 s. Office samples on this machine still took 32–40 s inside the engine. Profiling attributed most Office time to waiting for LibreOffice; it is not a Python text-layout or admission-limit bottleneck.

## Native CI evidence

[Workflow 41386520687](https://github.com/LiamxZhang/any2pdf/actions/runs/41386520687) runs complete-engine tests and real frozen conversions on each OS. The smoke test asserts that the cache completion marker and identity stay unchanged between multiple independent conversions. All three complete-engine suites passed 66 tests each. Windows native cached totals were 1.17 s (PDF), 1.12 s (PNG), 1.20 s (TXT), and 3.91 s (HTML); the first DOCX invocation including extraction took 54.25 s. Linux native measurements after first extraction were 0.51 s for PDF, 0.53 s for PNG, 0.58 s for Chinese TXT, and 2.02 s for HTML. macOS measurements were 0.29 s, 0.30 s, 0.30 s, and 3.50 s respectively. Different hosts and workloads should not be compared as a controlled cross-platform benchmark.

## Storage and first launch

First launch still takes time and needs several GB of disk space. The cache persists under `%LOCALAPPDATA%/Any2PDF/runtime` on Windows or `$XDG_DATA_HOME/Any2PDF/runtime` (normally `~/.local/share/Any2PDF/runtime`) on Linux. Upgrades can have separate caches. Removing a cache causes automatic reconstruction on next launch; originals, outputs and history are separate from this runtime cache.
