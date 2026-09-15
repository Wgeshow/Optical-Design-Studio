"""Small frozen entry point: divert worker processes before importing Qt."""
import multiprocessing
import os
from pathlib import Path
import sys
import traceback

if __name__ == '__main__':
    multiprocessing.freeze_support()
    from desktop_runtime import dispatch_startup_helper
    helper_result = dispatch_startup_helper()
    if helper_result is not None:
        raise SystemExit(helper_result)
    if '--apply-update' in sys.argv:
        from update_install import helper_main
        raise SystemExit(helper_main(sys.argv[sys.argv.index('--apply-update') + 1]))
    if '--self-test' in sys.argv:
        report = Path(sys.argv[sys.argv.index('--self-test') + 1]).resolve()
        report.parent.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        os.environ.setdefault('S4_LIBRARY_ROOT', str(report.parent/'User Data'))
        try:
            from installer_smoke import run
            raise SystemExit(run(report))
        except Exception:
            report.with_suffix('.failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
            raise
    try:
        from qt_app import main
        raise SystemExit(main())
    except Exception:
        root = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Optical Design Studio'
        root.mkdir(parents=True, exist_ok=True)
        log = root/'startup-error.txt'
        log.write_text(traceback.format_exc(), encoding='utf-8')
        if os.name == 'nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f'Optical Design Studio could not start.\n\nDetails were saved to:\n{log}',
                                            'Optical Design Studio', 0x10)
        raise
