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
    from PyQt6.QtWidgets import QApplication
    from qt_chrome import WindowChrome, WindowsCustomFrame

    if not window.windowFlags() & Qt.WindowType.FramelessWindowHint:
        raise AssertionError('The application must draw its integrated custom title bar.')
    chrome = window.chrome
    if not isinstance(chrome, WindowChrome) or chrome.height() != 50:
        raise AssertionError('The reference 50-pixel title bar is missing.')
    if chrome.width() != window.centralWidget().width()-16 or chrome.y() != 8:
        raise AssertionError('The title bar does not fit the reference window inset.')
    if chrome.title.text() != window.windowTitle():
        raise AssertionError('The integrated title differs from the application title.')
    redesigned = hasattr(window, 'project_header') and window.project_header.isVisible()
    middle = [window.project_header] if redesigned else [chrome.file_button, chrome.view_button]
    controls = [chrome.logo, chrome.title, *middle,
                chrome.minimize_button, chrome.maximize_button, chrome.close_button]
    if chrome.native_frame:
        raise AssertionError('Custom caption controls must remain enabled on every platform.')
    frame = window._windows_frame
    if not isinstance(frame, WindowsCustomFrame):
        raise AssertionError('The Windows resizing/Snap adapter is missing.')
    expected_native = sys.platform == 'win32' and QApplication.platformName() == 'windows'
    if frame.enabled != expected_native:
        raise AssertionError('The Windows resizing/Snap adapter has the wrong activation state.')
    maximize_center = chrome.mapTo(window, chrome.maximize_button.geometry().center())
    if frame.hit_test(maximize_center) != 9:
        raise AssertionError('The maximize caption must expose HTMAXBUTTON for Windows Snap.')
    for control in controls:
        label = control.accessibleName() or control.objectName() or type(control).__name__
        if not control.isVisible() or not chrome.rect().contains(control.geometry()):
            raise AssertionError('A title-bar control is hidden or clipped: ' + label)
        if control.width() < control.minimumSizeHint().width():
            raise AssertionError('A title-bar control is narrower than its contents: ' + label)
    controls = sorted(controls, key=lambda control: control.geometry().left())
    for left, right in zip(controls, controls[1:]):
        if left.geometry().right() >= right.geometry().left():
            raise AssertionError('Title-bar controls overlap.')
    if redesigned:
        navigation = window.project_button.parentWidget()
        navigation_controls = [window.optical_workflow, window.project_button,
                               window.project_save_button, chrome.file_button]
        for control in navigation_controls:
            if not control.isVisible() or not navigation.rect().contains(control.geometry()):
                raise AssertionError('A navigation-bar control is hidden or clipped: ' +
                                     (control.accessibleName() or control.objectName()))
        ordered = sorted(navigation_controls, key=lambda control: control.geometry().left())
        for left, right in zip(ordered, ordered[1:]):
            if left.geometry().right() >= right.geometry().left():
                raise AssertionError('Navigation-bar controls overlap.')
    if chrome.title.width() < chrome.title.fontMetrics().horizontalAdvance(chrome.title.text()):
        raise AssertionError('The application title is truncated.')
    if hasattr(chrome, 'open_button') or hasattr(chrome, 'save_button'):
        raise AssertionError('Project commands must be in File, without duplicate title-bar buttons.')
    if not all(action in chrome.file_menu.actions() and action in window.actions()
               for action in (chrome.open_action, chrome.save_action)):
        raise AssertionError('File must retain project commands and their window shortcuts.')
    return dict(frameless=True, native_snap_adapter_enabled=frame.enabled,
                maximize_hit_test=9, height=chrome.height(), width=chrome.width(),
                visible_controls=len(controls), title=chrome.title.text(),
                project_commands_in_file_menu=True)


def settle_window_layout(application, window):
    """Deliver the responsive-density debounce and its queued layout changes."""
    from PyQt6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(window.appearance_timer.interval() + 80, loop.quit)
    loop.exec()
    application.processEvents()


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


def inspect_native_controls(window, store, application):
    """Exercise the shipped named-layer and material appearance controls."""
    import copy
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QWidget
    from qt_device_builder import GeometryViewport
    from qt_native_field_volume import NativeVolumeCanvas
    from qt_native_figure import NativeFigureCanvas

    builder=window.pages['Structure']
    names=list(store.layers['Name'])
    assert [builder.layer_selector.itemData(i) for i in range(builder.layer_selector.count())]==names
    selected=next(row for row in store.layers.to_dict('records')[1:-1] if row['Thickness_um']>0)
    builder.layer_selector.setCurrentIndex(builder.layer_selector.findData(selected['Name']))
    assert builder.selected_layer==selected['Name']
    assert builder.layer_list.currentItem().data(Qt.ItemDataRole.UserRole)==selected['Name']
    assert isinstance(builder.viewport,GeometryViewport)
    before=copy.deepcopy(store.project());undo_count=len(store._undo)
    materials=window.pages['Materials']
    materials.selection.setCurrentIndex(materials.selection.findData('project:'+selected['Material']))
    assert [materials.tabs.tabText(i) for i in range(materials.tabs.count())]==[
        'Inspect','Find online','Import CSV','Enter values']
    builder.set_geometry_view('3D Stack')
    application.processEvents()
    initial=builder.viewport.grab().toImage()
    camera=(builder.viewport.angle,builder.viewport.elevation,builder.viewport.zoom)
    materials.set_material_color('#ac56df')
    colored=builder.viewport.grab().toImage()
    builder.set_material_opacity(40)
    translucent=builder.viewport.grab().toImage()
    note='Frozen release verification note: display metadata preserves the physical model. '
    materials.material_notes.setPlainText(note)
    assert materials.save_material_notes()
    assert store.appearance['material_notes'][selected['Material']]==note
    assert builder.viewport.material_colors[selected['Material']]=='#ac56df'
    assert builder.viewport.material_opacities[selected['Material']]==40
    preview=window.pages['Settings'].appearance_page.viewport
    assert preview.material_colors[selected['Material']]=='#ac56df'
    assert preview.material_opacities[selected['Material']]==40
    assert camera==(builder.viewport.angle,builder.viewport.elevation,builder.viewport.zoom)
    samples=[(x,y) for y in range(20,initial.height()-20,4) for x in range(20,initial.width()-20,4)]
    changes=dict(color=sum(initial.pixel(x,y)!=colored.pixel(x,y) for x,y in samples),
        opacity=sum(colored.pixel(x,y)!=translucent.pixel(x,y) for x,y in samples))
    assert changes['color']>20 and changes['opacity']>20,changes
    for key in ('materials','layers','patterns','settings','performance'):
        assert store.project()[key]==before[key],key
    assert len(store._undo)==undo_count
    for mode in ('Unit cell','Cross-section','3D Stack'):
        builder.set_geometry_view(mode)
        assert not builder.viewport.grab().isNull()
    guide=window.pages['About'].help_guide
    guide.open_topic('Materials')
    assert 'dataset' in guide.reader.toPlainText().lower()
    assert guide.actual_example_button is not None
    widgets=window.findChildren(QWidget)
    legacy=[type(widget).__name__ for widget in widgets
        if type(widget).__module__.startswith('matplotlib.backends.backend_qt')]
    assert not legacy,legacy
    assert isinstance(materials.plot.canvas,NativeFigureCanvas)
    assert not materials.plot.canvas.unsupported_artists
    assert any(isinstance(widget,NativeVolumeCanvas) for widget in widgets)
    result=dict(named_layers=names,selected_layer=selected['Name'],material=selected['Material'],
        inspector_tabs=4,display_color='#ac56df',material_opacity=40,notes_preserved=True,
        changed_preview_pixels=changes,physical_model_unchanged=True,camera_unchanged=True,
        shared_settings_preview=True,help_assets_available=True,live_matplotlib_qt_widgets=legacy,
        native_2d_canvases=sum(isinstance(widget,NativeFigureCanvas) for widget in widgets),
        native_3d_canvases=sum(isinstance(widget,NativeVolumeCanvas) for widget in widgets))
    store.load_project(before)
    return result


def inspect_maximize_painting(window, application, output):
    """Exercise actual maximize/restore state and the opaque workspace policy."""
    from qt_common import theme_manager

    manager = theme_manager()
    previous = manager.look
    original_size = window.size()
    snapshots = []
    adapter = window._desktop_glass
    try:
        for look in ('glass_dark', 'glass_light'):
            manager.apply_look(look, persist=False)
            window.showMaximized()
            settle_window_layout(application, window)
            assert window.isMaximized() and not adapter.active
            if adapter.supported:
                assert window.property('desktopGlassSuspended')
            root = window.centralWidget()
            image = root.grab().toImage()
            assert not image.isNull() and image.pixelColor(3, 3).alpha() == 255
            # Check real controls/content as well as the background: a white
            # raster image with a valid window state must not pass this check.
            colors = {image.pixel(x, y) for y in range(4, image.height(), 16)
                      for x in range(4, image.width(), 16)}
            assert len(colors) > 8, len(colors)
            assert window.chrome.maximize_button.isVisible() and window.stack.isVisible()
            filename = Path(output)/('installed_'+look+'_maximized.png')
            assert window.grab().save(str(filename))
            snapshots.append(str(filename))
            window.showNormal()
            settle_window_layout(application, window)
            assert not window.isMaximized()
            if adapter.supported:
                assert not window.property('desktopGlassSuspended')
            assert adapter._use_native_glass()
            assert not root.grab().isNull()
        return dict(maximized_opaque_workspace=True, restored_glass_policy=True,
                    looks=['glass_dark', 'glass_light'], snapshots=snapshots,
                    native_compositor_supported=adapter.supported,
                    validation='Qt state and rendered raster content; desktop compositor appearance requires a live Windows session')
    finally:
        window.showNormal()
        window.resize(original_size)
        manager.apply_look(previous, persist=False)
        settle_window_layout(application, window)


def inspect_simulation_speed(result):
    """Verify the installed backend uses shared solves and exact indexed data."""
    import numpy as np
    from scan_storage import FieldSampleIndex, ScanPoints, SpectrumResults, json_default, json_object
    from contour_sweep import regions, _regions_reference

    directory = Path(result['output']).parent
    spectrum = SpectrumResults(directory/'spectrum.sqlite')
    index = FieldSampleIndex(directory/'fields')
    try:
        with (directory/'results.csv').open(newline='', encoding='utf-8') as stream:
            exported = [[float(value) for value in row.values()] for row in csv.DictReader(stream)]
        np.testing.assert_array_equal(exported, [row[1:] + [row[3]+row[4]+row[5]] for row in spectrum])
        assert len(index) == len(spectrum) == 3
        diagnostics = []
        for ordinal in range(len(index)):
            sample = index.sample(ordinal)
            saved = json.loads((Path(sample['directory'])/'field_diagnostics.json').read_text(encoding='utf-8'))
            assert saved['reused_spectrum_solution'], saved
            assert saved['sampling']['method'] == 'validated_fourier_planes', saved
            assert saved['sampling']['plane_calls'] > 0, saved
            assert sample['wavelength_nm'] == spectrum[ordinal][1]
            diagnostics.append(saved['sampling'])
        shared = result['info']['electric_fields']
        assert shared['reused_spectrum_solution'] and shared['samples'] == len(index), shared
        points = ScanPoints(1500., .001, 100000, 0.)
        encoded = json.dumps(points, default=json_default)
        decoded = json.loads(encoded, object_hook=json_object)
        assert len(encoded) < 200 and len(decoded) == 100000 and decoded[-1] == points[-1]
        mask = np.random.default_rng(13).random((17, 23)) > .6
        for periodic_x, periodic_y in ((False, False), (True, False), (True, True)):
            actual, count = regions(mask, periodic_x, periodic_y)
            expected, reference_count = _regions_reference(mask, periodic_x, periodic_y)
            np.testing.assert_array_equal(actual, expected)
            assert count == reference_count
        return dict(shared_spectrum_solutions=True, validated_fourier_sampling=True,
                    exact_disk_backed_spectrum=True, compact_scan_roundtrip=True,
                    contour_label_parity=True, field_sample_count=len(index), sampling=diagnostics)
    finally:
        spectrum.close()
        index.close()


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
            expected = ['Structure', 'Materials', 'Simulate', 'Optimize', 'Fields', 'Saved work', 'Settings', 'About','AI Search']
            if list(window.pages) != expected:
                raise AssertionError('Some desktop pages are missing.')
            if window.windowTitle() != 'Optical Design Studio':
                raise AssertionError('Unexpected application title.')
            screenshots = []
            chrome_layouts = []
            looks=('dark','light','glass_dark','glass_light')
            for mode in looks:
                theme_manager().apply_look(mode, persist=False)
                for width, height in ((1000, 720), (1536, 1024)):
                    window.resize(width, height)
                    settle_window_layout(application, window)
                    chrome_layouts.append(dict(theme=mode, **inspect_window_chrome(window)))
                for index, name in enumerate(expected):
                    window._navigate_route(index)
                    application.processEvents()
                    if window.stack.currentIndex() != (2 if index in (4,5) else index) or window.sidebar.isVisible() or window.workspace_tabs.isVisible():
                        raise AssertionError('Top-tab navigation must reach every page without the old sidebar or simulation banner.')
                    filename = report_path.parent / ('installed_' + mode + '_' + name.lower().replace(' ', '_') + '.png')
                    if not window.grab().save(str(filename)):
                        raise RuntimeError('Could not save screenshot: ' + str(filename))
                    screenshots.append(str(filename))
            return dict(pages=expected, themes=list(looks), screenshots=screenshots,
                        integrated_title_bar=chrome_layouts,
                        close_guard=inspect_busy_close_guard(window, application),
                        title=window.windowTitle(), window_icon_present=not window.windowIcon().isNull())

        check('desktop_pages_and_themes', render_interface)
        check('maximize_restore_painting', lambda: inspect_maximize_painting(window, application, report_path.parent))
        check('native_reference_controls_and_graphs',lambda:inspect_native_controls(window,store,application))

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

        spectrum_result = {}

        def cpu_spectrum():
            result = backend_job('simulation', dict(electric_fields=dict(grid=3, depth_samples=3, contour_step=.1)))
            spectrum_result.update(result)
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
        check('simulation_speed_and_scan_storage', lambda: inspect_simulation_speed(spectrum_result))

        def electric_fields():
            finite_layer = next(row['Name'] for row in store.project()['layers'][1:-1]
                                if float(row['Thickness_um']) > 0)
            result = backend_job('fields', dict(wavelength_nm=1550, grid=3, depth_samples=5, layer=finite_layer))
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
            from qt_field_volume import FieldVolumeWidget
            from qt_native_field_volume import NativeFieldVolumePlot,NativeVolumeCanvas,NativeSurfaceMesh
            from qt_native_figure import NativeFigureCanvas
            from field_volume import vectors
            from field_tracking_ui import _safe_directory
            from PyQt6.QtCore import QEvent,QPoint,QPointF,Qt
            from PyQt6.QtGui import QMouseEvent,QWheelEvent
            import numpy as np
            viewer = FieldVolumeWidget(store)
            try:
                viewer.resize(1100,800)
                viewer.show()
                application.processEvents()
                expected_snapshot=directory.resolve().relative_to(Path(library.runs).resolve()).as_posix()
                snapshot_index=viewer.snapshot.findData(expected_snapshot)
                assert snapshot_index>=0,expected_snapshot
                viewer.snapshot.setCurrentIndex(snapshot_index)
                assert viewer.snapshot.currentData()==expected_snapshot
                selected_csv=_safe_directory(library,viewer.snapshot.currentData())/'electric_fields.csv'
                assert selected_csv.resolve()==(directory/'electric_fields.csv').resolve()
                viewer.load()
                assert viewer.data is not None, viewer.status.text()
                assert viewer.snapshot.currentData()==expected_snapshot
                expected_xyz=np.array([[float(row[key]) for key in ('x_um','y_um','z_um')]
                    for row in rows if row['plane']=='volume_samples'])
                np.testing.assert_allclose(viewer.data[2],expected_xyz,rtol=1e-12,atol=1e-14)
                assert isinstance(viewer.plot,NativeFieldVolumePlot)
                assert isinstance(viewer.plot.canvas,NativeVolumeCanvas)
                assert viewer.plot._publication_figure is None
                assert viewer.data[1].groupby('layer')['z_um'].nunique().eq(5).all()
                assert viewer.surface_faces > 0, viewer.status.text()
                assert all(isinstance(mesh,NativeSurfaceMesh) for pair in viewer.surfaces for mesh in pair)
                assert 'Use Sample points' not in viewer.status.text()
                original_xyz=viewer.data[2].copy()
                original_fields={key:value.copy() for key,value in viewer.data[3].items()}
                canvas=viewer.plot.canvas
                original_angle=canvas.azimuth
                point=QPointF(canvas.width()/2,canvas.height()/2)
                for kind,position in ((QEvent.Type.MouseButtonPress,point),
                        (QEvent.Type.MouseMove,point+QPointF(40,0))):
                    event=QMouseEvent(kind,position,canvas.mapToGlobal(position),Qt.MouseButton.LeftButton,
                        Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
                    application.sendEvent(canvas,event)
                assert viewer.dragging and canvas.azimuth!=original_angle
                assert all(not full.get_visible() and fast.get_visible() for full,fast in viewer.surfaces)
                release=QMouseEvent(QEvent.Type.MouseButtonRelease,point+QPointF(40,0),
                    canvas.mapToGlobal(point+QPointF(40,0)),Qt.MouseButton.LeftButton,
                    Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
                application.sendEvent(canvas,release)
                viewer.restore_timer.stop()
                viewer.finish_interaction()
                assert all(full.get_visible() and not fast.get_visible() for full,fast in viewer.surfaces)
                old_zoom=canvas.zoom
                wheel=QWheelEvent(point,canvas.mapToGlobal(point),QPoint(),QPoint(0,120),
                    Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
                application.sendEvent(canvas,wheel)
                assert canvas.zoom>old_zoom
                viewer.threshold.setValue(50)
                viewer.show_arrows.setChecked(True)
                viewer.phase.setValue(0)
                old_vectors=viewer.arrow.vectors.copy()
                viewer.phase.setValue(90)
                selected_fields={key:value[viewer.arrow_ids] for key,value in original_fields.items()}
                np.testing.assert_allclose(viewer.arrow.vectors,vectors(selected_fields,'E',90)*viewer.scale)
                assert not np.array_equal(old_vectors,viewer.arrow.vectors)
                viewer.mode.setCurrentText('H')
                assert viewer.arrow is not None
                viewer.mode.setCurrentText('Energy flow')
                assert not viewer.play.isEnabled()
                np.testing.assert_array_equal(viewer.data[2],original_xyz)
                for key in original_fields:np.testing.assert_array_equal(viewer.data[3][key],original_fields[key])
                assert viewer.plot._publication_figure is None
                quantity=canvas.quantity
                ranges=canvas.axis_ranges
                application.processEvents()
                viewer.plot.canvas.draw()
                viewer.grab().save(str(report_path.parent/'installed_3d_fields.png'))
                fields_page=window.pages['Fields']
                fields_page.directory=Path(result['directory']);fields_page.field_directory=directory
                fields_page.wavelength.setValue(1550);fields_page.grid.setValue(3);fields_page.depth.setValue(5)
                fields_page.layer.setCurrentIndex(fields_page.layer.findData(finite_layer))
                fields_page.render_fields();window._navigate_route(4);application.processEvents()
                assert isinstance(fields_page.plot.canvas,NativeFigureCanvas)
                assert not fields_page.plot.canvas.unsupported_artists
                assert fields_page.plot.canvas.data_records
                fields_page.plot.grab().save(str(report_path.parent/'installed_2d_fields.png'))
            finally:
                viewer.close()
                viewer.deleteLater()
            return dict(sample_count=len(rows), minimum_E2=min(magnitudes), maximum_E2=max(magnitudes),
                        volume_depths=5,selected_snapshot=expected_snapshot,selected_csv_verified=True,
                        continuous_surface_and_rotation_verified=True,
                        live_renderer='NativeVolumeCanvas',native_2d_field_maps=True,
                        physical_axis_ranges=ranges,quantity=quantity,native_orbit_and_zoom=True,
                        saved_xyz_and_complex_fields_preserved=True,actual_phase_vectors_verified=True,
                        live_publication_artists_created=False,
                        feature_keys=sorted(features), diagnostics=features.get('acceleration', {}),
                        directory=str(directory))

        check('native_electric_field_maps_and_features', electric_fields)

        def ai_multi_hole():
            import copy
            from qt_multi_hole import MultiHoleDialog
            from optical_objective import response_name
            from circle_geometry import solver_regions
            saved = store.portable_project()
            try:
                dialog = MultiHoleDialog(store)
                dialog.double_lattice()
                dialog.positions.setChecked(False)
                dialog.apply()
                if dialog.result() != 1:
                    raise AssertionError(dialog.status.text())
                _, probe = prepare_job('simulation',store.portable_project(),{},library)
                assert len(probe['model']['patterns']) >= 2
                merged = copy.deepcopy(probe['model'])
                a,b = merged['patterns'][-2:]
                b.update(cx=a['cx']+a['sx'],cy=a['cy'],sx=a['sx'])
                assert any(p['shape']=='polygon' for p in solver_regions(merged))
                # Exercise polygon support in the packaged native worker, not only Shapely.
                patterns=store.patterns.to_dict('records')
                patterns[-1].update(CenterX_um=patterns[-2]['CenterX_um']+patterns[-2]['SizeX_um'],
                    CenterY_um=patterns[-2]['CenterY_um'],SizeX_um=patterns[-2]['SizeX_um'])
                store.set_structure(store.materials,store.layers,patterns)
                union_result=backend_job('simulation')
                options=dict(use_structure_patterns=True,merge_circles=True,bounds=dialog.bounds,
                    response='Transmission',objective='Response at target',response_threshold=0.,
                    trials=5,initial=2,finalists=1,target_nm=1550.,half_window=10.,step=10.,
                    min_q=1.,field_grid=3,map_grid=3,use_fields=True,track_resonance=False,reuse=False,
                    response_agreement=.02)
                # Use a bounded six-design grid in the installed application.
                options['bounds']=[dict(Parameter='radius',Target=str(len(patterns)),Min=patterns[-1]['SizeX_um']*.9,
                    Max=patterns[-1]['SizeX_um']*1.1,Step=patterns[-1]['SizeX_um']*.04,Choices='')]
                result=backend_job('target',options)
                summary=result['summary']
                if summary['status'] != 'complete' or summary['response'] != 'Transmission':
                    raise AssertionError(summary)
                if summary.get('verified_response_at_target') is None:
                    raise AssertionError('No verified transmission design in packaged AI test: '+str(summary))
                return dict(summary=summary,native_union_output=union_result['output'])
            finally:
                store.load_project(saved)

        check('ai_multi_hole_target_and_circle_union', ai_multi_hole)

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
            import matplotlib
            import pyqtgraph,qt_native_figure,qt_native_field_volume,qt_native_plot
            import field_sampling, scan_storage, simulation_fields
            modules = [numpy, scipy, sklearn, PyQt6.QtCore, matplotlib,pyqtgraph,
                       qt_native_figure,qt_native_field_volume,qt_native_plot,
                       field_sampling,scan_storage,simulation_fields]
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


def run_native_startup(report_path):
    """Verify the real main/event loop and compositor using an owned backdrop."""
    import ctypes
    from ctypes import wintypes as W
    from PyQt6.QtCore import QPoint, QTimer, Qt
    from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget
    from app_version import APP_VERSION
    from qt_common import preferences

    report_path = Path(report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = dict(version=APP_VERSION, frozen=bool(getattr(sys, 'frozen', False)),
                  executable=str(Path(sys.executable).resolve()), platform='windows',
                  checks={}, passed=False)
    background = None
    window = None
    application = None
    if sys.platform != 'win32':
        report['error'] = 'This check requires the real Windows Qt platform.'
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        return 1
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.IsZoomed.argtypes = [W.HWND]
    user.IsWindowVisible.argtypes = [W.HWND]
    user.GetClientRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
    user.WindowFromPoint.argtypes = [W.POINT]
    user.WindowFromPoint.restype = W.HWND
    user.GetAncestor.argtypes = [W.HWND, W.UINT]
    user.GetAncestor.restype = W.HWND
    user.SetWindowPos.argtypes = [W.HWND, W.HWND, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, W.UINT]
    user.SendMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    user.SendMessageW.restype = ctypes.c_ssize_t

    def prepare_saved_geometry():
        # The normal main creates the only QApplication. Its window factory
        # seeds geometry for this display without ever showing the donor.
        donor = QMainWindow()
        donor.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        available = application.primaryScreen().availableGeometry()
        donor.resize(min(1460, available.width()-40), min(960, available.height()-40))
        donor.move(20, 20)
        donor.setWindowState(Qt.WindowState.WindowMaximized)
        preferences().setValue('geometry', donor.saveGeometry())
        preferences().setValue('glass_opacity', 76)
        preferences().sync()
        donor.deleteLater()

    def save():
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')

    def stop():
        nonlocal background
        if background is not None:
            background.close()
        if window is not None:
            user.SetWindowPos(int(window.winId()), W.HWND(-2), 0, 0, 0, 0, 0x13)
            window.close()
        application.quit()

    def capture(name, maximized):
        hwnd = int(window.winId())
        report.setdefault('state_snapshots', []).append(dict(name=name, qt_maximized=window.isMaximized(),
            native_maximized=bool(user.IsZoomed(hwnd)), qt_visible=window.isVisible(),
            pending_startup_state=int(getattr(window, '_startup_window_state', Qt.WindowState.WindowNoState).value),
            preferences_file=window.preferences.fileName()))
        save()
        assert window.isVisible() and user.IsWindowVisible(hwnd), 'Window never became visible.'
        # Qt maximizes a frameless window by changing its geometry; Windows
        # need not set WS_MAXIMIZE/IsZoomed. Verify the actual native surface.
        assert window.isMaximized() == maximized, 'The saved Qt window state was not restored.'
        margins = window.windowHandle().frameMargins()
        assert margins.isNull(), 'Unexpected native frame margins break the layered surface.'
        client = W.RECT()
        assert user.GetClientRect(hwnd, ctypes.byref(client)), 'No native client rectangle.'
        dpr = window.devicePixelRatioF()
        assert abs(client.right-round(window.width()*dpr)) <= 1
        assert abs(client.bottom-round(window.height()*dpr)) <= 1
        if maximized:
            available = window.windowHandle().screen().availableGeometry()
            assert abs(client.right-round(available.width()*dpr)) <= 1
            assert abs(client.bottom-round(available.height()*dpr)) <= 1
        center = window.mapToGlobal(window.rect().center())
        # Convert via the native client origin for per-monitor DPI coordinates.
        user.ClientToScreen.argtypes = [W.HWND, ctypes.POINTER(W.POINT)]
        origin = W.POINT(0, 0)
        user.ClientToScreen(hwnd, ctypes.byref(origin))
        hit = user.WindowFromPoint(W.POINT(origin.x+client.right//2, origin.y+client.bottom//2))
        assert hit and int(user.GetAncestor(hit, 2) or hit) == hwnd, 'The rendered window is entirely transparent to native hit testing.'
        raster = window.grab().toImage()
        raster.save(str(report_path.parent/(name+'-qt.png')))
        details = dict(qt_maximized=window.isMaximized(), native_maximized=bool(user.IsZoomed(hwnd)),
                       size=[window.width(), window.height()], native_client=[client.right, client.bottom],
                       frame_margins=[margins.left(), margins.top(), margins.right(), margins.bottom()],
                       native_hit_matches_window=True)
        if maximized:
            assert window.centralWidget().grab().toImage().pixelColor(3, 3).alpha() == 255
            top_left = window.mapToGlobal(QPoint(0, 0))
            screen = window.windowHandle().screen()
            native = screen.grabWindow(0, top_left.x(), top_left.y(), window.width(), window.height()).toImage()
            assert not native.isNull(), 'No native compositor image.'
            native = native.scaled(raster.size())
            native.save(str(report_path.parent/(name+'-native.png')))
            matches = 0
            total = 0
            for row in range(1, 13):
                for column in range(1, 17):
                    x = round(column*(raster.width()-1)/17)
                    y = round(row*(raster.height()-1)/13)
                    expected = raster.pixelColor(x, y)
                    actual = native.pixelColor(x, y)
                    if expected.alpha() == 255:
                        total += 1
                        matches += max(abs(a-b) for a,b in zip(expected.getRgb()[:3], actual.getRgb()[:3])) <= 12
            assert total >= 100 and matches/total >= .85, 'The compositor is not displaying the painted controls.'
            details['native_pixels_match_fraction'] = matches/total
        report['checks'][name] = dict(passed=True, detail=details)
        save()

    def step(index):
        nonlocal background
        names = ('initial_maximized_native_surface', 'restore_state', 'remaximize_native_surface',
                 'system_restore_state', 'system_maximize_native_surface')
        try:
            if index == 0:
                background = QWidget()
                background.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
                background.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
                background.setStyleSheet('background:#176f70;')
                background.setGeometry(window.windowHandle().screen().availableGeometry())
                background.show()
                assert user.SetWindowPos(int(window.winId()), W.HWND(-1), 0, 0, 0, 0, 0x13)
                QTimer.singleShot(250, lambda: step(1))
                return
            capture(names[index-1], index % 2 == 1)
            if index == 1:
                window.showNormal()
                QTimer.singleShot(400, lambda: step(2))
            elif index == 2:
                window.showMaximized()
                QTimer.singleShot(400, lambda: step(3))
            elif index == 3:
                user.SendMessageW(int(window.winId()), 0x0112, 0xF120, 0)
                QTimer.singleShot(500, lambda: step(4))
            elif index == 4:
                user.SendMessageW(int(window.winId()), 0x0112, 0xF030, 0)
                QTimer.singleShot(500, lambda: step(5))
            else:
                report['passed'] = True
                save()
                stop()
        except Exception:
            name = names[max(0, min(index-1, len(names)-1))]
            report['checks'][name] = dict(passed=False, traceback=traceback.format_exc())
            save()
            stop()

    import qt_app
    original = qt_app.OpticalStudio
    def instrumented(*args, **kwargs):
        nonlocal window, application
        application = QApplication.instance()
        assert application.platformName() == 'windows', 'This check requires the Windows Qt platform.'
        prepare_saved_geometry()
        window = original(*args, **kwargs)
        QTimer.singleShot(700, lambda: step(0))
        return window
    qt_app.OpticalStudio = instrumented
    try:
        qt_app.main(['--library', str(Path(os.environ['S4_LIBRARY_ROOT'])), '--no-restore', '--look', 'glass_dark'])
    except Exception:
        report['error'] = traceback.format_exc()
        save()
    finally:
        qt_app.OpticalStudio = original
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--library', type=Path, required=True)
    args = parser.parse_args()
    os.environ['S4_LIBRARY_ROOT'] = str(args.library.resolve())
    raise SystemExit(run(args.report))
