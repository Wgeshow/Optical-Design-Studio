"""Console protocol executable used only by the desktop application's workers."""
import multiprocessing

if __name__ == '__main__':
    multiprocessing.freeze_support()
    from backend import main
    raise SystemExit(main())
