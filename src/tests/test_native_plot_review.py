"""Independent populated-plot checks across desktop looks and compact sizes."""
import copy
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QApplication, QScrollArea, QGraphicsScene
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_common import theme_manager
from qt_materials import MaterialsPage
from qt_field_volume import FieldVolumeWidget
from test_native_field_volume import Store
from test_field_tracking_ui import sample

APP = QApplication.instance() or QApplication([])


class NativePlotReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manager = theme_manager()
        self.old = (self.manager.settings, self.manager.look, copy.deepcopy(self.manager.custom_colors),
                    self.manager.scale, self.manager.adaptive, self.manager.glass_opacity)
        self.manager.settings = QSettings(str(self.root / 'appearance.ini'), QSettings.Format.IniFormat)
        self.manager.custom_colors = {}
        self.manager.scale = 100
        self.manager.adaptive = False
        self.widgets = []

    def process(self):
        for _ in range(5):
            APP.processEvents()

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        self.process()
        self.manager.settings, self.manager.custom_colors = self.old[0], self.old[2]
        self.manager.scale, self.manager.adaptive, self.manager.glass_opacity = self.old[3:]
        self.manager.apply_look(self.old[1], persist=False)
        self.temp.cleanup()

    def test_material_dual_axes_survive_all_looks_resize_modes_copy_and_fit(self):
        store = ProjectStore(DataLibrary(self.root / 'library'), restore=False)
        page = MaterialsPage(store)
        outer = QScrollArea()
        outer.setWidgetResizable(True)
        outer.setWidget(page)
        self.widgets.append(outer)
        path = self.root / 'measured.csv'
        path.write_text('wavelength,n,k\n1000,2.1,.001\n1500,2.3,.02\n2000,2.2,.005\n', encoding='utf-8')
        page.import_paths([str(path)])
        outer.resize(1536, 920)
        outer.show()
        self.process()
        before = copy.deepcopy(store.project())
        main, twin = page.plot.figure.axes
        original = [(line.get_xdata().copy(), line.get_ydata().copy()) for axis in (main, twin) for line in axis.lines]
        page.plot.toolbar.zoom()
        page.plot.canvas.axis_views[main].setRange(xRange=(1200, 1800), yRange=(2.15, 2.4), padding=0)
        page.plot.canvas.axis_views[twin].setRange(yRange=(-3, -1.5), padding=0)
        self.process()
        displayed_x = page.plot.canvas.axis_views[main].viewRange()[0]
        for look in ('light', 'dark', 'glass_light', 'glass_dark'):
            self.manager.apply_look(look, persist=False)
            for width in (1536, 960, 640):
                outer.resize(width, 920)
                self.process()
                self.assertEqual(outer.width(), width)
                self.assertLessEqual(page.width(),outer.viewport().width())
                self.assertEqual(page.inspect_splitter.orientation(),Qt.Orientation.Vertical if width<1000 else Qt.Orientation.Horizontal)
                canvas = page.plot.canvas
                self.assertEqual(canvas.view.scene().itemIndexMethod(), QGraphicsScene.ItemIndexMethod.NoIndex)
                self.assertEqual(canvas.unsupported_artists, [])
                self.assertIsNot(canvas.axis_views[main], canvas.axis_views[twin])
                self.assertTrue(page.plot.toolbar.buttons['Zoom'].isChecked())
                for view in canvas.axis_views.values():
                    self.assertEqual(view.state['mouseMode'], view.RectMode)
                np.testing.assert_allclose(canvas.axis_views[main].viewRange()[0], displayed_x, atol=1e-9)
                records = [r for r in canvas.data_records if r['kind'] == 'line']
                for record, (x, y) in zip(records, original):
                    np.testing.assert_array_equal(record['raw_x'], x)
                    np.testing.assert_array_equal(record['raw_y'], y)
                for action in page.plot.toolbar.buttons.values():
                    button = page.plot.toolbar.widgetForAction(action)
                    self.assertTrue(action.text())
                    self.assertTrue(action.toolTip())
                    self.assertFalse(action.icon().isNull())
                    self.assertFalse(button.isHidden())
                self.assertFalse(canvas.grab().isNull())
        page.plot.toolbar.copy_figure()
        self.assertFalse(APP.clipboard().pixmap().isNull())
        page.plot.toolbar.home()
        self.assertFalse(page.plot.toolbar.buttons['Zoom'].isChecked())
        self.assertEqual(page.plot.canvas.axis_views[main].state['mouseMode'], page.plot.canvas.axis_views[main].PanMode)
        np.testing.assert_allclose(page.plot.canvas.axis_views[main].viewRange()[0], sorted(main.get_xlim()), atol=1e-9)
        self.assertEqual(store.project(), before)

    def test_native_volume_theme_resize_and_hide_stop_playback_without_data_changes(self):
        directory = self.root / 'fields'
        sample(directory, maps=True)
        widget = FieldVolumeWidget(Store(), campaign=True)
        self.widgets.append(widget)
        widget.resize(1000, 800)
        widget.show()
        widget.load_directory(directory)
        self.process()
        self.assertIsNotNone(widget.data, widget.status.text())
        xyz = widget.data[2].copy()
        fields = {key: value.copy() for key, value in widget.data[3].items()}
        widget.show_arrows.setChecked(True)
        widget.phase.setValue(45)
        canvas = widget.plot.canvas
        camera = (canvas.azimuth, canvas.elevation, canvas.zoom, canvas.pan.x(), canvas.pan.y())
        for look in ('light', 'dark', 'glass_light', 'glass_dark'):
            self.manager.apply_look(look, persist=False)
            for width, height in ((1000, 800), (640, 760)):
                widget.resize(width, height)
                self.process()
                self.assertEqual(widget.width(), width)
                self.assertEqual(camera, (canvas.azimuth, canvas.elevation, canvas.zoom, canvas.pan.x(), canvas.pan.y()))
                self.assertEqual(canvas.axis_ranges, ((-.5, .5), (-.5, .5), (0., 1.)))
                self.assertFalse(canvas.grab().isNull())
                for button in widget.plot.buttons.values():
                    self.assertTrue(button.accessibleName())
                    self.assertTrue(button.toolTip())
                    self.assertFalse(button.icon().isNull())
        widget.play.click()
        self.assertTrue(widget.timer.isActive())
        widget.hide()
        self.process()
        self.assertFalse(widget.timer.isActive())
        self.assertFalse(widget.restore_timer.isActive())
        self.assertFalse(widget.play.isChecked())
        self.assertFalse(widget.dragging)
        np.testing.assert_array_equal(widget.data[2], xyz)
        for key, original in fields.items():
            np.testing.assert_array_equal(widget.data[3][key], original)


if __name__ == '__main__':
    unittest.main()
