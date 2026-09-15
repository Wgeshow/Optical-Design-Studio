"""Square defaults, rectangular restore, and draft isolation for lattice editing."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PyQt6.QtWidgets import QApplication
from qt_structure import StructurePage
from tests.test_qt_structure import MemoryStore


class SquareLatticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.store = MemoryStore()
        self.page = StructurePage(self.store)

    def tearDown(self):
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()

    def test_square_default_and_apply(self):
        self.assertTrue(self.page.square_lattice.isChecked())
        self.assertTrue(self.page.lattice_y.isHidden())
        self.assertEqual(self.page.lattice_x_label.text(), 'Period')
        self.page.lattice_x.setValue(900)
        self.assertEqual(self.store.settings['ax_um'], .77)
        self.page.apply_lattice()
        self.assertEqual(self.store.settings['ax_um'], .9)
        self.assertEqual(self.store.settings['ay_um'], .9)

    def test_rectangular_draft_survives_unrelated_refresh(self):
        self.page.square_lattice.setChecked(False)
        self.page.lattice_y.setValue(1200)
        self.store.changed.emit('performance')
        self.assertFalse(self.page.square_lattice.isChecked())
        self.assertEqual(self.page.lattice_y.value(), 1200)
        self.page.apply_lattice()
        self.assertEqual(self.store.settings['ay_um'], 1.2)

    def test_rectangular_project_restores_without_mutation(self):
        self.store.settings.update(ax_um=.8, ay_um=1.1)
        self.store.changed.emit('project')
        self.assertFalse(self.page.square_lattice.isChecked())
        self.assertFalse(self.page.lattice_y.isHidden())
        self.assertEqual(self.page.lattice_y.value(), 1100)
        self.page.square_lattice.setChecked(True)
        self.assertEqual(self.store.settings['ay_um'], 1.1)
        self.page.apply_lattice()
        self.assertEqual(self.store.settings['ay_um'], .8)

    def test_editor_units_convert_every_length_without_mutating_project(self):
        self.assertEqual(self.page.lattice_x.suffix(), ' nm')
        self.page.lattice_x.setValue(830)
        self.page.cut_y.setValue(30)
        self.page.layer_thickness.setValue(333)
        self.page.units.setCurrentText('µm')
        self.assertEqual(self.page.lattice_x.suffix(), ' µm')
        self.assertEqual(self.page.lattice_y.suffix(), ' µm')
        self.assertEqual(self.page.lattice_x.value(), .83)
        self.assertEqual(self.page.lattice_y.value(), .83)
        self.assertEqual(self.page.cut_y.value(), .03)
        self.assertEqual(self.page.layer_thickness.value(), .333)
        self.assertEqual(self.store.settings['ax_um'], .77)
        self.assertEqual(self.page.plot.figure.axes[0].get_xlabel(), 'x (µm)')
        self.page.units.setCurrentText('nm')
        self.assertEqual(self.page.lattice_x.value(), 830)
        self.assertEqual(self.page.layer_thickness.value(), 333)
        self.assertEqual(self.page.plot.figure.axes[0].get_xlabel(), 'x (nm)')
        self.assertAlmostEqual(self.page.plot.figure._s4_geometry['cut_y_um'], .03)
        self.page.view_mode.setCurrentIndex(1)
        self.assertEqual(self.page.plot.figure.axes[0].get_zlabel(), 'Depth z (nm)')

    def test_rectangular_unit_conversion_preserves_both_draft_lengths(self):
        self.page.square_lattice.setChecked(False)
        self.page.lattice_x.setValue(850)
        self.page.lattice_y.setValue(1230)
        self.page.units.setCurrentText('µm')
        self.assertEqual(self.page.lattice_x.value(), .85)
        self.assertEqual(self.page.lattice_y.value(), 1.23)
        self.page.apply_lattice()
        self.assertEqual(self.store.settings['ax_um'], .85)
        self.assertEqual(self.store.settings['ay_um'], 1.23)


if __name__ == '__main__':
    unittest.main()
