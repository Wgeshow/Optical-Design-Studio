"""Persist uncaught Python errors and native fault diagnostics for the desktop."""
import faulthandler
from pathlib import Path
import sys
import traceback


def install_crash_reporting(directory, report):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    log = (directory / 'desktop-crash.log').open('a', encoding='utf-8', buffering=1)
    # Keep the descriptor alive for the lifetime of the application.
    try:
        faulthandler.enable(file=log, all_threads=True)
    except (RuntimeError, OSError):
        pass
    previous = sys.excepthook

    def handle(kind, value, tb):
        if issubclass(kind, (KeyboardInterrupt, SystemExit)):
            previous(kind, value, tb)
            return
        try:
            traceback.print_exception(kind, value, tb, file=log)
            log.flush()
        except Exception:
            pass
        try:
            report(f'Unexpected application error: {value}. Details: {log.name}')
        except Exception:
            pass
    sys.excepthook = handle
    return log, previous
