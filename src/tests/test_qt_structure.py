"""Native construction regression: selection, units, patterns and shared state."""
import os
from types import SimpleNamespace
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pandas as pd
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton

from model import MAT_COLS, LAYER_COLS, PAT_COLS
from qt_common import theme_manager
from qt_structure import StructurePage
from structure_builder import validate_structure


class MemoryStore(QObject):
    changed = pyqtSignal(str)
    library_changed = pyqtSignal()
    busy_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.materials = pd.DataFrame([
            ['Air', 'constant_nk', 1., 0., '', 'nm'],
            ['GaAs', 'constant_nk', 3.4, 0., '', 'nm'],
            ['SiO2', 'constant_nk', 1.45, 0., '', 'nm'],
            ['Au', 'constant_eps', -115.13, 11.259, '', 'nm'],
        ], columns=MAT_COLS)
        self.layers = pd.DataFrame([
            ['AirAbove', 0., 'Air'], ['PCS1', .25, 'GaAs'], ['PCS2', .25, 'GaAs'],
            ['Substrate', .1, 'SiO2'], ['Gold', .1, 'Au'], ['AirBelow', 0., 'Air'],
        ], columns=LAYER_COLS)
        self.patterns = pd.DataFrame([
            ['circle', 'PCS1', 'Air', 0., 0., .1, 0., 0.],
            ['circle', 'PCS2', 'Air', 0., 0., .05, 0., 0.],
        ], columns=PAT_COLS)
        self.settings = {'ax_um': .77, 'ay_um': .77}
        self.performance = {}
        self.library = SimpleNamespace(presets=lambda: {})
        self.context = SimpleNamespace(LIBRARY=self.library, PRESETS={
            'Air / Vacuum': ['Air', 'constant_nk', 1., 0., '', 'nm'],
            'Polymer': ['PMMA', 'constant_nk', 1.5, 0., '', 'nm'],
        })
        self.busy = False
        self.history = []

    def set_structure(self, materials, layers, patterns, reason='structure'):
        validate_structure(materials, layers, patterns)
        self.history.append((self.materials.copy(), self.layers.copy(), self.patterns.copy()))
        self.materials, self.layers, self.patterns = materials.copy(), layers.copy(), patterns.copy()
        self.changed.emit(reason)

    def update_settings(self, mapping):
        self.settings.update(mapping)
        self.changed.emit('settings')

    def undo(self):
        if not self.history:
            raise ValueError('There is no structure edit to undo.')
        self.materials, self.layers, self.patterns = self.history.pop()
        self.changed.emit('structure')


class QtStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.store = MemoryStore()
        self.page = StructurePage(self.store)
        self.page.resize(1180, 850)

    def tearDown(self):
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()

    def click(self, name):
        widget = self.page.findChild(QPushButton, name)
        self.assertIsNotNone(widget, name)
        self.assertTrue(widget.isEnabled(), name)
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def test_rapid_layer_switch_then_apply_updates_only_selected_layer(self):
        for name in ('PCS1', 'PCS2', 'Gold', 'PCS1', 'PCS2'):
            self.assertTrue(self.page.select_layer(name))
        self.page.layer_thickness.setValue(325)
        self.click('applyLayer')
        self.assertEqual(self.page.selected_layer, 'PCS2')
        self.assertEqual(self.page.layer_name.text(), 'PCS2')
        self.assertAlmostEqual(self.store.layers.loc[self.store.layers.Name == 'PCS2', 'Thickness_um'].iloc[0], .325)
        self.assertAlmostEqual(self.store.layers.loc[self.store.layers.Name == 'PCS1', 'Thickness_um'].iloc[0], .25)
        for _ in range(3):
            self.store.changed.emit('performance')
            self.app.processEvents()
        self.assertEqual(self.page.selected_layer, 'PCS2')
        self.assertEqual(self.page.layer_list.currentItem().data(Qt.ItemDataRole.UserRole), 'PCS2')

    def test_units_convert_unsaved_values_and_keep_correct_physical_dimensions(self):
        self.page.select_layer('PCS1')
        self.page.layer_thickness.setValue(415)
        self.page.region_x.setValue(20)
        self.page.region_sx.setValue(105)
        self.page.units.setCurrentText('µm')
        self.assertAlmostEqual(self.page.layer_thickness.value(), .415)
        self.assertAlmostEqual(self.page.region_x.value(), .02)
        self.assertAlmostEqual(self.page.region_sx.value(), .105)
        self.click('applyLayer')
        self.assertAlmostEqual(self.store.layers.iloc[1].Thickness_um, .415)
        self.page.units.setCurrentText('nm')
        self.assertAlmostEqual(self.page.layer_thickness.value(), 415)

    def test_repeat_copies_all_regions_and_undo_restores_shared_stack(self):
        self.page.repeat_start.setCurrentIndex(self.page.repeat_start.findData('PCS1'))
        self.page.repeat_end.setCurrentIndex(self.page.repeat_end.findData('PCS2'))
        self.page.repeat_count.setValue(2)
        self.click('repeatBlock')
        self.assertEqual(len(self.store.layers), 10)
        self.assertEqual(len(self.store.patterns), 6)
        self.assertEqual(list(self.store.layers.Name)[1:7], ['PCS1', 'PCS2', 'PCS1_copy', 'PCS2_copy', 'PCS1_copy_2', 'PCS2_copy_2'])
        self.assertAlmostEqual(self.store.patterns.iloc[3].SizeX_um, .05)
        self.assertEqual(self.page.selected_layer, 'PCS1_copy')
        self.click('undoStructure')
        self.assertEqual(len(self.store.layers), 6)
        self.assertEqual(len(self.store.patterns), 2)

    def test_rotated_region_keeps_full_rectangle_width_and_position(self):
        self.page.select_layer('PCS2')
        self.page.shape.setCurrentIndex(self.page.shape.findData('rectangle'))
        self.page.region_sx.setValue(120)
        self.page.region_sy.setValue(80)
        self.page.region_x.setValue(25)
        self.page.region_y.setValue(-10)
        self.page.region_angle.setValue(37)
        self.click('region_add')
        region = self.store.patterns.iloc[-1]
        self.assertEqual(region.Layer, 'PCS2')
        self.assertEqual(region.Shape, 'rectangle')
        self.assertAlmostEqual(region.SizeX_um, .12)
        self.assertAlmostEqual(region.SizeY_um, .08)
        self.assertAlmostEqual(region.CenterX_um, .025)
        self.assertAlmostEqual(region.CenterY_um, -.01)
        self.assertAlmostEqual(region.Angle_deg, 37)
        self.assertEqual(self.page.region_choice.currentData(), '2')
        self.page.region_sx.setValue(130)
        self.click('region_apply')
        self.assertAlmostEqual(self.store.patterns.iloc[-1].SizeX_um, .13)
        self.assertAlmostEqual(self.store.patterns.iloc[0].SizeX_um, .1)

    def test_rename_remaps_regions_and_preserves_selection(self):
        self.page.select_layer('PCS1')
        self.page.layer_name.setText('Upper slab')
        self.click('applyLayer')
        self.assertEqual(self.page.selected_layer, 'Upper slab')
        self.assertEqual(self.store.patterns.iloc[0].Layer, 'Upper slab')
        self.assertEqual(self.page.repeat_start.currentData(), 'Upper slab')

    def test_material_dropdown_can_add_preset_without_overwriting_existing(self):
        self.page.select_layer('PCS1')
        self.page.layer_material.setCurrentIndex(self.page.layer_material.findData('builtin:Polymer'))
        self.click('applyLayer')
        self.assertEqual(self.store.layers.iloc[1].Material, 'PMMA')
        self.assertIn('PMMA', list(self.store.materials.Name))
        self.assertEqual(self.store.layers.iloc[2].Material, 'GaAs')
        self.assertEqual(self.page.layer_material.currentData(), 'current:PMMA')

    def test_outer_media_and_busy_state_block_mutations(self):
        self.page.select_layer('AirAbove')
        self.assertFalse(self.page.layer_thickness.isEnabled())
        self.assertFalse(self.page.findChild(QPushButton, 'layer_delete').isEnabled())
        self.assertFalse(self.page.region_editor.isEnabled())
        self.page.layer_name.setText('Incident')
        self.click('applyLayer')
        self.assertEqual(self.store.layers.iloc[0].Thickness_um, 0.)
        before = self.store.layers.copy()
        self.store.busy = True
        self.store.busy_changed.emit(True)
        self.assertFalse(self.page.findChild(QPushButton, 'applyLayer').isEnabled())
        self.page.layer_action('below')
        pd.testing.assert_frame_equal(before, self.store.layers)

    def test_invalid_name_reports_inline_and_does_not_change_stack(self):
        self.page.select_layer('PCS2')
        self.page.layer_name.setText('PCS1')
        before = self.store.layers.copy()
        self.click('applyLayer')
        self.assertIn('already used', self.page.status.text())
        self.assertTrue(self.page.status.property('error'))
        pd.testing.assert_frame_equal(before, self.store.layers)
        self.assertEqual(self.page.selected_layer, 'PCS2')

    def test_shared_external_changes_refresh_layer_and_repeat_choices(self):
        self.page.select_layer('Gold')
        updated = self.store.layers.copy()
        updated.loc[1, 'Thickness_um'] = .29
        self.store.set_structure(self.store.materials, updated, self.store.patterns)
        self.assertEqual(self.page.selected_layer, 'Gold')
        self.assertEqual(self.page.layer_name.text(), 'Gold')
        self.assertIn('740 nm', self.page.summary.text())
        self.page.select_layer('PCS1')
        self.assertEqual(self.page.layer_thickness.value(), 290)

    def test_preview_supports_section_selection_after_canvas_replacement(self):
        self.page.draw_preview()
        metadata = self.page.plot.figure._s4_geometry
        self.page._plot_click(SimpleNamespace(button=1, inaxes=metadata['section'], ydata=.36))
        self.assertEqual(self.page.selected_layer, 'PCS2')
        self.assertEqual(self.page.plot.figure._s4_geometry['selected'], 'PCS2')
        self.page.draw_preview()
        self.assertIn('button_press_event', self.page.plot.canvas.callbacks.callbacks)

    def test_six_layer_preview_is_scaled_correctly_and_renders_both_themes(self):
        self.page.show()
        for mode in ('light', 'dark'):
            theme_manager().apply(mode, persist=False)
            self.app.processEvents()
            image = self.page.grab().toImage()
            self.assertGreater(image.width(), 800)
            self.assertGreater(image.height(), 600)
            self.assertFalse(image.isNull())
        meta = self.page.plot.figure._s4_geometry
        self.assertAlmostEqual(meta['total_um'], .7)
        self.assertEqual(len(meta['stack']), 6)
        self.assertEqual(meta['stack'][1]['z0'], 0.)
        self.assertEqual(meta['stack'][2]['z0'], .25)
        self.assertEqual(meta['warnings'], [])

    def test_long_layer_names_use_bounded_rows_and_keep_full_details(self):
        name = 'PCS layer with a deliberately long descriptive device name'
        self.page.layer_name.setText(name)
        self.click('applyLayer')
        self.page.show()
        self.app.processEvents()
        item = self.page.layer_list.currentItem()
        self.assertIn(name, item.toolTip())
        self.assertIn('250 nm', item.toolTip())
        self.assertEqual(len(item.text().splitlines()), 3)
        normal = self.page.layer_list.visualItemRect(item).height()
        self.page.layer_list.setStyleSheet('font-size: 22px;')
        self.page.layer_list.doItemsLayout()
        self.app.processEvents()
        large = self.page.layer_list.visualItemRect(item).height()
        self.assertGreater(large, normal)
        self.assertGreaterEqual(large, self.page.layer_list.fontMetrics().height()*3)
        self.assertFalse(self.page.layer_list.wordWrap())

    def test_thin_layer_labels_do_not_overlap_and_reflow_when_resized(self):
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from qt_structure import geometry_figure
        layers = self.store.layers.copy()
        layers.loc[2, 'Thickness_um'] = .002
        layers.loc[3, 'Thickness_um'] = .003
        figure = geometry_figure(layers, self.store.patterns, 'PCS2', .77, .77)
        canvas = FigureCanvasAgg(figure)
        for width, height in ((8.4, 3.6), (5, 2.6), (10, 5)):
            figure.set_size_inches(width, height)
            canvas.draw()
            visible = [(layer, text) for layer, text in figure._s4_geometry['labels'] if text.get_visible()]
            self.assertIn('PCS2', [layer['name'] for layer, _ in visible])
            boxes = [text.get_window_extent(canvas.get_renderer()) for _, text in visible]
            for index, box in enumerate(boxes):
                self.assertFalse(any(box.overlaps(other) for other in boxes[index+1:]))
        self.assertAlmostEqual(figure._s4_geometry['total_um'], .355)
        self.assertAlmostEqual(figure._s4_geometry['stack'][2]['z1']-.25, .002)

    def test_preview_hover_retains_details_for_unlabelled_thin_layer(self):
        layers = self.store.layers.copy()
        layers.loc[2, 'Thickness_um'] = .002
        self.store.set_structure(self.store.materials, layers, self.store.patterns)
        metadata = self.page.plot.figure._s4_geometry
        self.page._plot_hover(SimpleNamespace(inaxes=metadata['section'], ydata=.251))
        self.assertEqual(self.page.plot.canvas.toolTip(), 'PCS2\nGaAs\n2 nm')
        self.page._plot_hover(SimpleNamespace(inaxes=None, ydata=None))
        self.assertEqual(self.page.plot.canvas.toolTip(), '')


if __name__ == '__main__':
    unittest.main()
