"""Saved scientific results pass through real pages into native Qt plots."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).parent))
import numpy as np
import pandas as pd
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_common import PlotWidget
from qt_compute import FieldsPage, spectrum_figure
from qt_fdtd import FDTDPage
from qt_field_compare import FieldComparisonWidget
from qt_ai_search import AISearchPage
from qt_index_shift import IndexShiftPage
from test_field_tracking_ui import sample
import test_fixed_readout

APP = QApplication.instance() or QApplication([])


class NativeScientificCallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ProjectStore(DataLibrary(self.root / 'library'), restore=False)
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def page(self, kind):
        widget = kind(self.store)
        self.widgets.append(widget)
        widget.resize(1460, 950)
        widget.show()
        APP.processEvents()
        return widget

    def record(self, plot, artist):
        self.assertEqual(type(plot.canvas).__name__, 'NativeFigureCanvas')
        self.assertEqual(plot.canvas.unsupported_artists, [])
        found = [r for r in plot.canvas.data_records if r['source_artist'] is artist]
        self.assertEqual(len(found), 1)
        return found[0]

    def saved_fields(self, name, scale=1., thickness=1.):
        directory = self.store.library.runs / name / 'fields'
        model = sample(directory, scale=scale, thickness=thickness, maps=True)
        path = directory / 'electric_fields.csv'
        frame = pd.read_csv(path)
        for index, component in enumerate(('Ex', 'Ey', 'Ez')):
            frame[component + '_real'] = scale * (index + 1) * (1 + frame.x_um ** 2 + .1 * frame.z_um)
            frame[component + '_imag'] = scale * (index + 1) * .05
        frame['E2'] = sum(frame[c + '_real'] ** 2 + frame[c + '_imag'] ** 2 for c in ('Ex', 'Ey', 'Ez'))
        for component in ('Hx', 'Hy', 'Hz'):
            frame[component + '_real'] = 1. if component == 'Hy' else 0.
            frame[component + '_imag'] = 0.
        frame.to_csv(path, index=False)
        return directory, model, frame

    def test_large_native_spectrum_retains_peak_omitted_by_former_sampling_cap(self):
        count = 24001
        former = np.unique(np.linspace(0, count - 1, 20000, dtype=int))
        peak = int(np.setdiff1d(np.arange(count), former)[len(np.setdiff1d(np.arange(count), former)) // 2])
        values = np.full(count, .1)
        values[peak] = .999
        frame = pd.DataFrame(dict(wavelength_nm=np.linspace(1400., 1600., count),
                                  R=np.full(count, .0005), T=1-values-.0005, A=values))
        plot = PlotWidget()
        self.widgets.append(plot)
        plot.resize(1000, 650)
        plot.show()
        plot.draw_figure(spectrum_figure(frame))
        APP.processEvents()
        axis = plot.figure.axes[0]
        absorption = next(line for line in axis.lines if line.get_label() == 'Absorption')
        record = self.record(plot, absorption)
        self.assertEqual(len(record['raw_x']), count)
        np.testing.assert_array_equal(record['raw_x'], frame.wavelength_nm)
        np.testing.assert_array_equal(record['raw_y'], frame.A)
        self.assertEqual(record['raw_y'][peak], .999)
        self.assertEqual(self.record(plot, axis.collections[0])['raw_x'][0], frame.wavelength_nm.iloc[peak])

    def test_fields_page_controls_keep_saved_complex_components_log_scale_and_full_csv(self):
        directory, _, frame = self.saved_fields('field-page')
        original = (directory / 'electric_fields.csv').read_bytes()
        before = copy.deepcopy(self.store.project())
        page = self.page(FieldsPage)
        page.field_directory = directory
        page.arrows.setChecked(True)
        page.component_buttons.button(1).click()
        page.render_fields()
        for logarithmic in (False, True):
            page.logarithmic.setChecked(logarithmic)
            APP.processEvents()
            axes = page.plot.figure.axes[:2]
            meshes = [self.record(page.plot, axis.collections[0]) for axis in axes]
            self.assertIs(meshes[0]['norm'], meshes[1]['norm'])
            for plane, vertical, mesh in zip(('xy', 'xz'), ('y_um', 'z_um'), meshes):
                subset = frame[frame.plane == plane].copy()
                subset['amplitude'] = np.abs(subset.Ex_real + 1j * subset.Ex_imag)
                expected = subset.pivot(index=vertical, columns='x_um', values='amplitude').sort_index().to_numpy()
                if logarithmic:
                    expected = np.log10(np.maximum(expected, 1e-16))
                np.testing.assert_allclose(mesh['values'], expected, rtol=0, atol=5e-16)
                np.testing.assert_array_equal(mesh['coordinates'], mesh['source_artist'].get_coordinates())
            self.assertTrue(axes[1].yaxis_inverted())
            self.assertEqual(page.plot.canvas.plots[axes[0]].getAxis('bottom').labelText, 'x (µm)')
            self.assertEqual(page.plot.canvas.plots[axes[1]].getAxis('left').labelText, 'z (µm)')
            arrows = [r for r in page.plot.canvas.data_records if r['kind'] == 'quiver']
            self.assertEqual(len(arrows), 2)
            for arrow in arrows:
                np.testing.assert_array_equal(arrow['u'], arrow['source_artist'].U)
                self.assertEqual(len(arrow['native_items']), len(arrow['u']))
        page.contour.setValue(-1)
        page.contour_enabled.setChecked(True)
        APP.processEvents()
        self.assertEqual(page.plot.canvas.unsupported_artists, [])
        self.assertTrue(any(r['kind'] == 'contour' for r in page.plot.canvas.data_records))
        exported = self.root / 'raw-fields.csv'
        with patch('qt_compute.QFileDialog.getSaveFileName', return_value=(str(exported), 'CSV')):
            page.export_data()
        self.assertEqual(exported.read_bytes(), original)
        self.assertEqual((directory / 'electric_fields.csv').read_bytes(), original)
        self.assertEqual(self.store.project(), before)

    def test_fdtd_cached_spectrum_peak_and_complex_field_keep_values_coordinates_units(self):
        directory = self.store.library.runs / 'fdtd-native'
        directory.mkdir()
        data = pd.DataFrame(dict(wavelength_nm=[1500., 1501., 1502.], R=[.8, .1, .2],
                                 T=[.1, .7, .2], A=[.1, .2, .6]))
        data.to_csv(directory / 'results.csv', index=False)
        x = np.array([-.45, -.1, .4])
        depth = np.array([-.8, -.2, .1, .75])
        field = np.arange(12).reshape(3, 4) / 10 + 1j * np.linspace(.1, .9, 12).reshape(3, 4)
        np.savez(directory / 'fdtd_fields.npz', x_um=x, depth_um=depth, field=field, wavelength_nm=1501.)
        original = {p.name: p.read_bytes() for p in directory.iterdir()}
        page = self.page(FDTDPage)
        with patch.object(self.store, 'start_run') as solver:
            page._finished(dict(run_kind='fdtd', directory=str(directory)))
            for key, row in (('R', 0), ('T', 1), ('A', 2)):
                page.peak_quantity.setCurrentIndex(page.peak_quantity.findData(key))
                APP.processEvents()
                axis = page.plot.figure.axes[0]
                self.assertEqual(len(axis.lines), 3)
                for line in axis.lines:
                    column = {'Reflection': 'R', 'Transmission': 'T', 'Absorption': 'A'}[line.get_label()]
                    record = self.record(page.plot, line)
                    np.testing.assert_array_equal(record['raw_x'], data.wavelength_nm)
                    np.testing.assert_array_equal(record['raw_y'], data[column])
                peak = self.record(page.plot, axis.collections[0])
                self.assertEqual(peak['raw_x'][0], data.wavelength_nm.iloc[row])
                self.assertEqual(peak['raw_y'][0], data[key].iloc[row])
                self.assertEqual(page.samples.currentRow(), row)
                self.assertIn('%', page.plot.canvas.plots[axis].getAxis('left').tickStrings([.2], 1, .1)[0])
            solver.assert_not_called()
        axis = page.field_plot.figure.axes[0]
        mesh = self.record(page.field_plot, axis.collections[0])
        np.testing.assert_array_equal(mesh['values'], np.abs(field).T ** 2)
        np.testing.assert_array_equal(mesh['coordinates'], axis.collections[0].get_coordinates())
        self.assertTrue(axis.yaxis_inverted())
        self.assertEqual(page.field_plot.canvas.plots[axis].getAxis('bottom').labelText, 'x (µm)')
        self.assertEqual(page.field_plot.canvas.plots[axis].getAxis('left').labelText, 'Depth from stack centre (µm)')
        self.assertEqual(original, {name: (directory / name).read_bytes() for name in original})

    def test_comparison_actual_task_keeps_shared_scale_physical_and_relative_coordinates(self):
        reference, _, _ = self.saved_fields('reference', scale=1., thickness=1.)
        current, _, _ = self.saved_fields('current', scale=2., thickness=2.)
        original = [p.read_bytes() for p in (reference / 'electric_fields.csv', current / 'electric_fields.csv')]
        before = copy.deepcopy(self.store.project())
        page = self.page(FieldComparisonWidget)
        for combo, path in ((page.reference, reference), (page.current, current)):
            combo.setCurrentIndex(combo.findData(str(path.relative_to(self.store.library.runs)).replace('\\', '/')))
        page.arrows.setChecked(True)
        with patch.object(self.store, 'start_run') as solver:
            for alignment, maximum in (('Physical coordinates', 2.), ('Layer-relative coordinates', 1.)):
                previous_payload=page._payload
                page.alignment.setCurrentText(alignment)
                page.compare_now()
                self.assertEqual(page._pending,'field-comparison-preview')
                deadline = time.monotonic() + 15
                while (page._pending is not None or self.store.busy) and time.monotonic() < deadline:
                    APP.processEvents()
                    QTest.qWait(10)
                self.assertIsNone(page._pending, page.status.text())
                self.assertFalse(self.store.busy)
                self.assertIsNotNone(page._payload, page.status.text())
                self.assertIsNot(page._payload,previous_payload)
                axes = page.plot.figure.axes[:4]
                records = [self.record(page.plot, axis.collections[0]) for axis in axes]
                self.assertTrue(all(r['norm'] is records[0]['norm'] for r in records))
                for axis, record in zip(axes, records):
                    np.testing.assert_array_equal(record['values'], axis.collections[0].get_array())
                    np.testing.assert_array_equal(record['coordinates'], axis.collections[0].get_coordinates())
                self.assertEqual(axes[1].get_ylim(), (0., maximum))
                self.assertEqual(axes[3].get_ylim(), (0., maximum))
                flow = [r for r in page.plot.canvas.data_records if r['kind'] == 'quiver']
                self.assertTrue(flow)
                for record in flow:
                    np.testing.assert_array_equal(record['u'], record['source_artist'].U)
                    np.testing.assert_array_equal(record['v'], record['source_artist'].V)
                    self.assertTrue(record['native_items'])
            solver.assert_not_called()
        self.assertEqual(self.store.project(), before)
        self.assertEqual(original, [p.read_bytes() for p in (reference / 'electric_fields.csv', current / 'electric_fields.csv')])

    def test_ai_saved_campaign_switches_raw_components_depth_rta_and_validation(self):
        records = []
        for name, scale in (('design01', 1.), ('design02', 2.)):
            directory, model, frame = self.saved_fields(name, scale)
            profile = []
            for z, subset in frame[frame.plane == 'volume_samples'].groupby('z_um'):
                amplitudes = [float(np.abs(subset[c + '_real'] + 1j * subset[c + '_imag']).mean()) for c in ('Ex', 'Ey', 'Ez')]
                profile.append(dict(z_um=float(z), layer='PCS', abs_E=amplitudes, total_abs=float(np.linalg.norm(amplitudes))))
            records.append(dict(model=model, phase='train', field_directory=str(directory),
                fields=dict(feasible=False, depth_profile=profile, constraints=dict(volume_rms_contrast=2., xz_rms_contrast=2., volume_coverage=.5, xz_coverage=.5)),
                rta=[dict(wavelength_nm=w, R=r, T=1-r-.1, A=.1) for w, r in ((1540., .2), (1550., .6), (1560., .3))]))
        measurement = dict(name='contrast', measured=[1., 2.], predictions=[1.1, 1.8], std=[.1, .2], mae=.15, rmse=.16, interval_95_coverage=1.)
        summary = dict(completed=2, training=2, tests=0, new_simulations=0, reused=2, failures=0,
                       validation=dict(measurements=[measurement] * 3))
        page = self.page(AISearchPage)
        before = copy.deepcopy(self.store.project())
        with patch.object(self.store, 'start_run') as solver:
            page.load_campaign(dict(records=records, summary=summary))
            for index in (0, 1):
                page.designs.setCurrentIndex(index)
                page.component.setCurrentIndex(page.component.findData('Ex'))
                APP.processEvents()
                record = records[index]
                axes = page.field_plot.figure.axes[:2]
                image = self.record(page.field_plot, axes[0].images[0])
                mesh = self.record(page.field_plot, axes[1].collections[0])
                np.testing.assert_array_equal(image['values'], axes[0].images[0].get_array())
                self.assertEqual(image['extent'], (-500., 500., -500., 500.))
                np.testing.assert_array_equal(mesh['values'], axes[1].collections[0].get_array())
                self.assertEqual(page.field_plot.canvas.plots[axes[1]].getAxis('left').labelText, 'Depth z (nm)')
                self.assertTrue(axes[1].yaxis_inverted())
                axis = page.line_plot.figure.axes[0]
                line = self.record(page.line_plot, axis.lines[0])
                np.testing.assert_array_equal(line['raw_x'], [p['z_um'] * 1000 for p in record['fields']['depth_profile']])
                np.testing.assert_array_equal(line['raw_y'], [p['abs_E'][0] for p in record['fields']['depth_profile']])
                axis = page.rta_plot.figure.axes[0]
                np.testing.assert_array_equal(self.record(page.rta_plot, axis.lines[0])['raw_y'], [.2, .6, .3])
                self.assertIn('60', page.rta_plot.canvas.plots[axis].getAxis('left').tickStrings([.6], 1, .1)[0])
            page.threshold.setValue(2.2)
            self.assertTrue(any(r['kind'] == 'contour' for r in page.field_plot.canvas.data_records))
            page.moving.setChecked(True)
            APP.processEvents()
            axis = page.field_plot.figure.axes[0]
            image = self.record(page.field_plot, axis.images[0])
            np.testing.assert_array_equal(np.ma.getmaskarray(image['values']), np.ma.getmaskarray(axis.images[0].get_array()))
            self.assertTrue(np.ma.getmaskarray(image['values']).any())
            self.assertEqual(page.validation_plot.canvas.unsupported_artists, [])
            for axis in page.validation_plot.figure.axes[:2]:
                errorbar = axis.containers[0]
                points = self.record(page.validation_plot, errorbar.lines[0])
                np.testing.assert_array_equal(points['raw_x'], measurement['measured'])
                np.testing.assert_array_equal(points['raw_y'], measurement['predictions'])
                interval = self.record(page.validation_plot, errorbar.lines[2][0])
                np.testing.assert_array_equal(interval['segments'], errorbar.lines[2][0].get_segments())
            solver.assert_not_called()
        self.assertEqual(self.store.project(), before)

    def test_index_shift_actual_saved_run_keeps_signed_fraction_and_spectrum_units(self):
        directory = self.root / 'index-run'
        test_fixed_readout.FixedReadoutTests().simulate(directory)
        original = {p.name: p.read_bytes() for p in directory.glob('*.csv')}
        page = self.page(IndexShiftPage)
        page.directory = directory
        with patch.object(self.store, 'start_run') as solver:
            page.show_result({})
            for view, expected in (('Fixed-wavelength response', [.9, .25]), ('Change from baseline', [0., -.65])):
                page.readout_view.setCurrentText(view)
                APP.processEvents()
                axis = page.plot.figure.axes[0]
                record = self.record(page.plot, axis.lines[0])
                np.testing.assert_allclose(record['raw_y'], expected, rtol=0, atol=1e-15)
                self.assertIn('RIU', page.plot.canvas.plots[axis].getAxis('bottom').labelText)
                if view == 'Change from baseline':
                    self.assertIn('percentage points', axis.get_ylabel())
                    self.assertIn('65%', page.plot.canvas.plots[axis].getAxis('left').tickStrings([-.65], 1, .1)[0])
                    self.assertLess(axis.get_ylim()[0], -.65)
            page.readout_view.setCurrentText('Overlaid spectra')
            axis = page.plot.figure.axes[0]
            self.assertEqual(page.plot.canvas.plots[axis].getAxis('bottom').labelText, 'Wavelength (nm)')
            frame = pd.read_csv(directory / 'index_shift_spectra.csv')
            for line, (_, subset) in zip(axis.lines[:2], frame.groupby('case')):
                record = self.record(page.plot, line)
                np.testing.assert_array_equal(record['raw_x'], subset.wavelength_nm)
                np.testing.assert_array_equal(record['raw_y'], subset.R)
            solver.assert_not_called()
        self.assertEqual(original, {p.name: p.read_bytes() for p in directory.glob('*.csv')})


if __name__ == '__main__':
    unittest.main()
