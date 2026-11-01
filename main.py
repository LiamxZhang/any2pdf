import sys


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        from any2pdf.worker import run_worker
        return run_worker(sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == '--gui-smoke':
        from any2pdf.ui import gui_smoke
        return gui_smoke(sys.argv[2])
    from any2pdf.ui import run
    return run()


if __name__ == '__main__':
    from multiprocessing import freeze_support
    freeze_support()
    raise SystemExit(main())
