"""Bounded end-to-end checks for a freshly installed desktop application.

The executable entry point sets an isolated S4_LIBRARY_ROOT before importing
this module. Nothing here changes the user's normal project or preferences.
"""
from datetime import datetime, timezone
import csv
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback


def inspect_window_chrome(window):
    """Check the shipped title bar at its actual laid-out size."""
    from PyQt6.QtCore import Qt
    from qt_chrome import WindowChrome

    native_frame = sys.platform == 'win32'
    if bool(window.windowFlags() & Qt.WindowType.FramelessWindowHint) == native_frame:
        raise AssertionError('Windows must use native resizing/Snap chrome; other platforms use custom chrome.')
    chrome = window.chrome
    if not isinstance(chrome, WindowChrome) or chrome.height() != 44:
        raise AssertionError('The integrated 44-pixel title bar is missing.')
    if chrome.width() != window.width() or chrome.y() != 0:
        raise AssertionError('The title bar does not span the top of the application.')
    if chrome.title.text() != window.windowTitle():
        raise AssertionError('The integrated title differs from the application title.')
    controls = [chrome.logo, chrome.title, chrome.file_button, chrome.view_button]
    if not native_frame:
        controls += [chrome.minimize_button, chrome.maximize_button, chrome.close_button]
    for control in controls:
        label = control.accessibleName() or control.objectName() or type(control).__name__
        if not control.isVisible() or not chrome.rect().contains(control.geometry()):
            raise AssertionError('A title-bar control is hidden or clipped: ' + label)
        if control.width() < control.minimumSizeHint().width():
            raise AssertionError('A title-bar control is narrower than its contents: ' + label)
    for left, right in zip(controls, controls[1:]):
        if left.geometry().right() >= right.geometry().left():
            raise AssertionError('Title-bar controls overlap.')
    if chrome.title.width() < chrome.title.fontMetrics().horizontalAdvance(chrome.title.text()):
        raise AssertionError('The application title is truncated.')
    if hasattr(chrome, 'open_button') or hasattr(chrome, 'save_button'):
        raise AssertionError('Project commands must be in File, without duplicate title-bar buttons.')
    if not all(action in chrome.file_menu.actions() and action in window.actions()
               for action in (chrome.open_action, chrome.save_action)):
        raise AssertionError('File must retain project commands and their window shortcuts.')
    return dict(frameless=not native_frame, height=chrome.height(), width=chrome.width(),
                visible_controls=len(controls), title=chrome.title.text(),
                project_commands_in_file_menu=True)


def inspect_busy_close_guard(window, application):
    """A caption close must still pass through the real application's closeEvent."""
    store = window.store
    previous = (store.busy, store._worker, window.status.text())
    try:
        # Represent a library operation without starting a worker or touching data.
        store.busy, store._worker = True, object()
        window.chrome.close_button.click()
        application.processEvents()
        if not window.isVisible():
            raise AssertionError('The caption close button bypassed the active-operation safeguard.')
        if 'library operation is finishing' not in window.status.text():
            raise AssertionError('The caption close button did not reach the application close handler.')
        return dict(active_library_operation_prevents_close=True)
    finally:
        store.busy, store._worker, status = previous
        window.status.setText(status)


def run(report_path):
    """Write a machine-readable report and return a conventional exit code."""
    from app_version import APP_VERSION
    report_path = Path(report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = dict(
        version=APP_VERSION,
        started=datetime.now(timezone.utc).isoformat(),
        executable=sys.executable,
        frozen=bool(getattr(sys, 'frozen', False)),
        python=sys.version,
        resource_root=str(getattr(sys, '_MEIPASS', Path(__file__).parent)),
        library_root=os.environ.get('S4_LIBRARY_ROOT'),
        checks={},
    )

    def save():
        report['elapsed_seconds'] = round(time.monotonic()-started, 3)
        report_path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')

    def check(name, function):
        before = time.monotonic()
        try:
            detail = function()
            report['checks'][name] = dict(passed=True, detail=detail)
        except Exception:
            report['checks'][name] = dict(passed=False, traceback=traceback.format_exc())
        report['checks'][name]['elapsed_seconds'] = round(time.monotonic()-before, 3)
        save()
        return report['checks'][name]['passed']

    save()
    window = None
    application = None
    store = None
    try:
        if not os.environ.get('S4_LIBRARY_ROOT'):
            raise RuntimeError('Self-test requires an explicitly isolated S4_LIBRARY_ROOT.')
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from bootstrap import initialize
        initialize(1)
        from PyQt6.QtCore import QEventLoop, QTimer
        from PyQt6.QtWidgets import QApplication
        from data_library import DataLibrary
        from qt_app import OpticalStudio
        from qt_common import theme_manager
        from qt_core import BackendWorker, ProjectStore, prepare_job

        application = QApplication.instance() or QApplication([sys.executable])
        application.setQuitOnLastWindowClosed(False)
        application.setApplicationName('Optical Design Studio')
        application.setOrganizationName('ZhouGroup')
        library = DataLibrary(os.environ['S4_LIBRARY_ROOT'])
        store = ProjectStore(library, restore=False)

        def inspect_library():
            entries = library.entries()
            presets = library.presets()
            minimum = int(os.environ.get('S4_SELF_TEST_MIN_SAVED_ENTRIES', '0'))
            if len(entries) < minimum:
                raise AssertionError(f'Expected at least {minimum} bundled entries; found {len(entries)}.')
            assets = list(library.assets.glob('*.csv'))
            if os.environ.get('S4_SELF_TEST_EXPECT_EMPTY_LIBRARY') == '1' and (entries or presets or assets):
                raise AssertionError('A fresh public installation contains research runs, presets or material tables.')
            # Validate the saved preset's embedded and managed optical constants.
            for preset in presets.values():
                materialized = library.materialize(preset['project'])
                library.snapshot(materialized)
            return dict(saved_entries=len(entries), saved_presets=len(presets),
                        optical_constant_files=len(assets), root=str(library.root),
                        empty_library_verified=os.environ.get('S4_SELF_TEST_EXPECT_EMPTY_LIBRARY') == '1')

        check('bundled_library', inspect_library)

        def render_interface():
            nonlocal window
            window = OpticalStudio(store)
            window.resize(1460, 960)
            window.show()
            expected = ['Structure', 'Materials', 'Simulate', 'Optimize', 'Fields', 'Saved work', 'Settings', 'About']
            if list(window.pages) != expected:
                raise AssertionError('Some desktop pages are missing.')
            if window.windowTitle() != 'Optical Design Studio':
                raise AssertionError('Unexpected application title.')
            screenshots = []
            chrome_layouts = []
            for mode in ('dark', 'light'):
                theme_manager().apply(mode, persist=False)
                for width, height in ((1000, 720), (1460, 960)):
                    window.resize(width, height)
                    application.processEvents()
                    chrome_layouts.append(dict(theme=mode, **inspect_window_chrome(window)))
                for index, name in enumerate(expected):
                    window.navigation.setCurrentRow(index)
                    application.processEvents()
                    filename = report_path.parent / ('installed_' + mode + '_' + name.lower().replace(' ', '_') + '.png')
                    if not window.grab().save(str(filename)):
                        raise RuntimeError('Could not save screenshot: ' + str(filename))
                    screenshots.append(str(filename))
            return dict(pages=expected, themes=['dark', 'light'], screenshots=screenshots,
                        integrated_title_bar=chrome_layouts,
                        close_guard=inspect_busy_close_guard(window, application),
                        title=window.windowTitle(), window_icon_present=not window.windowIcon().isNull())

        check('desktop_pages_and_themes', render_interface)

        def export_formats():
            import pandas as pd
            from model import MAT_COLS, LAYER_COLS, PAT_COLS
            from export_geometry import ExportOptions
            from cad_export import export_cad_step, read_step_metrics
            from comsol_export import export_comsol_java
            materials = pd.DataFrame([['Air','constant_nk',1.,0.,'','nm'],
                                      ['Glass','constant_nk',1.5,0.,'','nm']], columns=MAT_COLS)
            layers = pd.DataFrame([['Top',0.,'Air'],['Slab',.25,'Glass'],['Bottom',0.,'Air']], columns=LAYER_COLS)
            patterns = pd.DataFrame(columns=PAT_COLS)
            settings = {'ax_um':.77, 'ay_um':.8, 'fixed_wl_nm':1550}
            options = ExportOptions(2,3,'mm',False)
            java = export_comsol_java(report_path.parent/'ExportCheck.java',materials,layers,patterns,settings,options)
            if 'lengthUnit("mm")' not in java.read_text():
                raise AssertionError('COMSOL export unit missing.')
            step = export_cad_step(report_path.parent/'ExportCheck.step',materials,layers,patterns,settings,options)
            metrics = read_step_metrics(step)
            for actual, expected in ((metrics['x_um'],1.54),(metrics['y_um'],2.4),(metrics['z_um'],.25)):
                if not math.isclose(actual,expected,abs_tol=1e-6):
                    raise AssertionError('STEP round-trip changed physical dimensions.')
            return dict(step_roundtrip=metrics,
                        comsol_script_generated=True, comsol_execution_verified=False)

        check('cad_and_comsol_export', export_formats)

        def machine_learning():
            import numpy as np
            from ml_optimizer import dependencies
            GaussianProcessRegressor, ConstantKernel, Matern, ndtr, qmc, threadpool_limits = dependencies()
            x = np.array([[0.0], [0.3], [0.7], [1.0]])
            y = np.array([0.1, 0.6, 0.9, 0.2])
            with threadpool_limits(limits=1):
                regressor = GaussianProcessRegressor(kernel=ConstantKernel(1.0)*Matern(length_scale=.3),
                                                    optimizer=None, alpha=1e-8, normalize_y=True)
                regressor.fit(x, y)
                mean, std = regressor.predict(np.array([[.4], [.6]]), return_std=True)
                samples = qmc.Sobol(2, scramble=True, seed=42).random_base2(3)
                reference = qmc.Sobol(2, scramble=False).random_base2(2)
            if not (np.isfinite(mean).all() and np.isfinite(std).all() and np.isfinite(samples).all()):
                raise AssertionError('Nonfinite machine-learning output.')
            if not ((samples >= 0).all() and (samples < 1).all()
                    and len(np.unique(samples, axis=0)) == len(samples)
                    and (np.ptp(samples, axis=0) > .5).all()):
                raise AssertionError('Sobol sampler returned degenerate or out-of-range points; check bundled direction numbers.')
            expected = np.array([[0., 0.], [.5, .5], [.75, .25], [.25, .75]])
            if not np.array_equal(reference, expected):
                raise AssertionError('Sobol direction-number reference sequence is incorrect.')
            if not math.isclose(float(ndtr(0)), .5):
                raise AssertionError('SciPy normal CDF failed.')
            return dict(training_rows=len(x), predictions=mean.tolist(), uncertainty=std.tolist(),
                        sobol_samples=samples.tolist(), sobol_reference=reference.tolist())

        check('machine_learning_fit_predict', machine_learning)

        store.settings.update(NumG=25, wl_start_nm=1530, wl_stop_nm=1550, wl_step_nm=10)
        store.performance.update(mode='CPU only', workers=1, threads=1, chunk_size=1,
                                 timeout_seconds=90, require_gpu=False)

        def backend_job(kind, options=None):
            project = store.portable_project()
            # Check validation and launch using the exact same desktop contracts.
            _, spec = prepare_job(kind, project, options or {}, library)
            worker = BackendWorker(kind, project, options or {}, library)
            events, errors, completed = [], [], []
            loop = QEventLoop()
            deadline = QTimer()
            deadline.setSingleShot(True)
            timed_out = []

            def timeout():
                timed_out.append(True)
                worker.cancel()

            worker.event.connect(events.append)
            worker.completed.connect(completed.append)
            worker.failed.connect(errors.append)
            worker.finished.connect(loop.quit)
            deadline.timeout.connect(timeout)
            deadline.start(110000)
            worker.start()
            loop.exec()
            deadline.stop()
            worker.wait(5000)
            if timed_out:
                raise TimeoutError('The installed backend self-test exceeded 110 seconds.')
            if errors or not completed:
                raise RuntimeError('\n'.join(errors) or 'No backend completion event.')
            terminal = completed[-1]
            terminal['self_test_event_count'] = len(events)
            terminal['self_test_points'] = len(spec['model']['points'])
            return terminal

        def cpu_spectrum():
            result = backend_job('simulation')
            with Path(result['output']).open(newline='', encoding='utf-8') as stream:
                rows = list(csv.DictReader(stream))
            if len(rows) != 3:
                raise AssertionError(f'Expected 3 wavelength samples, received {len(rows)}.')
            for row in rows:
                if not all(math.isfinite(float(value)) for value in row.values()):
                    raise AssertionError('Spectrum contains nonfinite values.')
                if abs(float(row['R_plus_T_plus_A'])-1) > 1e-9:
                    raise AssertionError('Spectrum power balance failed.')
            native = result['info'].get('workers', [])
            if not native or result['info'].get('cpu_gemm_calls', 0) <= 0:
                raise AssertionError('No native S4 CPU work was recorded.')
            return dict(rows=rows, diagnostics=result['info'], output=result['output'])

        check('native_cpu_spectrum', cpu_spectrum)

        def electric_fields():
            finite_layer = next(row['Name'] for row in store.project()['layers'][1:-1]
                                if float(row['Thickness_um']) > 0)
            result = backend_job('fields', dict(wavelength_nm=1550, grid=3, layer=finite_layer))
            directory = Path(result['directory']) / 'fields'
            with (directory/'electric_fields.csv').open(newline='', encoding='utf-8') as stream:
                rows = list(csv.DictReader(stream))
            if not rows or not {'xy', 'xz', 'volume_samples'} <= {row['plane'] for row in rows}:
                raise AssertionError('Electric-field planes were not generated.')
            magnitudes = [float(row['E2']) for row in rows]
            if not all(math.isfinite(value) and value >= 0 for value in magnitudes):
                raise AssertionError('Invalid electric-field intensity.')
            features = result['summary']['field_features']
            if not features or not (directory/'field_features.json').is_file():
                raise AssertionError('Field descriptors were not saved.')
            return dict(sample_count=len(rows), minimum_E2=min(magnitudes), maximum_E2=max(magnitudes),
                        feature_keys=sorted(features), diagnostics=features.get('acceleration', {}),
                        directory=str(directory))

        check('native_electric_field_maps_and_features', electric_fields)

        if os.environ.get('S4_SELF_TEST_GPU') == '1':
            def gpu_diagnostic():
                store.performance.update(mode='GPU-assisted (one worker)', gpu_min_n=1, require_gpu=True)
                result = backend_job('diagnostic')
                if result['info'].get('gpu_gemm_calls', 0) <= 0 or result['info'].get('gpu_failures', 0):
                    raise AssertionError('Requested GPU self-test did not perform successful GPU work: ' +
                                         json.dumps(result['info']))
                return dict(diagnostics=result['info'], message=result.get('message'))
            check('native_gpu_diagnostic', gpu_diagnostic)

        def runtime_origins():
            import numpy
            import scipy
            import sklearn
            import PyQt6.QtCore
            import gradio
            import matplotlib
            import plotly
            modules = [numpy, scipy, sklearn, PyQt6.QtCore, gradio, matplotlib, plotly]
            origins = {module.__name__: str(module.__file__) for module in modules}
            if report['frozen']:
                root = Path(sys.executable).resolve().parent
                external = {name: path for name, path in origins.items()
                            if not Path(path).resolve().is_relative_to(root)}
                if external:
                    raise AssertionError('Installed app loaded dependencies outside its folder: ' + json.dumps(external))
            return origins

        check('dependency_origins', runtime_origins)
    except Exception:
        report['checks']['initialization'] = dict(passed=False, traceback=traceback.format_exc())
    finally:
        if window is not None:
            window.close()
        if application is not None:
            application.processEvents()
        report['passed'] = bool(report['checks']) and all(item['passed'] for item in report['checks'].values())
        report['finished'] = datetime.now(timezone.utc).isoformat()
        save()
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--library', type=Path, required=True)
    args = parser.parse_args()
    os.environ['S4_LIBRARY_ROOT'] = str(args.library.resolve())
    raise SystemExit(run(args.report))
