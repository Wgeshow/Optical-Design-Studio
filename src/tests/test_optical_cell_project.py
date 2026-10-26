"""Selected optical cell persists independently of finite-device geometry."""
import copy
import tempfile
import unittest
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore,desktop_settings,prepare_job


class OpticalCellProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_cell_selection_roundtrip_does_not_resize_device(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ProjectStore(DataLibrary(folder),restore=False)
            before=copy.deepcopy(store.device)
            extent=(store.settings['ax_um'],store.settings['ay_um'])
            cell=dict(enabled=True,width_um=.1,depth_um=.12,cx_um=0.,cy_um=0.)
            store.update_settings({'optical_unit_cell':cell})
            self.assertEqual(store.device,before)
            self.assertEqual((store.settings['ax_um'],store.settings['ay_um']),extent)
            self.assertEqual(store.project()['settings']['optical_unit_cell'],cell)
            path=Path(folder)/'cell.json';store.save_project(path)
            other=ProjectStore(DataLibrary(Path(folder)/'reopened'),restore=False)
            other.load_project(path)
            self.assertEqual(other.settings['optical_unit_cell'],cell)
            self.assertEqual(other.device,before)

    def test_bad_selection_rejected_before_store_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ProjectStore(DataLibrary(folder),restore=False)
            before=store.project()
            for config in ({'enabled':'yes'},{'width_um':0},{'depth_um':float('nan')},
                           {'cx_um':float('inf')},{'unknown':1}):
                with self.subTest(config=config),self.assertRaises(ValueError):
                    store.update_settings({'optical_unit_cell':config})
                self.assertEqual(store.project(),before)

    def test_disabled_choice_is_preserved(self):
        cell=dict(enabled=False,width_um=.45,depth_um=.45,cx_um=.1,cy_um=-.1)
        self.assertEqual(desktop_settings({'optical_unit_cell':cell})['optical_unit_cell'],cell)


if __name__=='__main__':unittest.main()
