"""Appearance persistence, sidebar controls and themed update confirmation."""
import os
import tempfile
import unittest
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_library = tempfile.TemporaryDirectory(prefix='optical_appearance_test_')
os.environ.setdefault('S4_LIBRARY_ROOT', _library.name)
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_app import OpticalStudio
from qt_core import ProjectStore
from qt_common import theme_manager


class AppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_sidebar_theme_scale_and_dialog(self):
        manager = theme_manager()
        old = manager.mode, manager.scale, manager.adaptive
        window = OpticalStudio(ProjectStore(DataLibrary(_library.name), restore=False))
        try:
            window.show()
            window.resize(1460, 900)
            window.sidebar_collapsed = False
            window.adapt_interface()
            self.assertEqual(window.navigation.item(0).text(), 'Structure')
            self.assertFalse(window.navigation.item(0).icon().isNull())
            window.sidebar_toggle.click()
            self.assertEqual(window.navigation.item(0).text(), '')
            self.assertEqual(window.navigation.item(0).toolTip(), 'Structure')
            window.sidebar_toggle.click()
            self.assertEqual(window.navigation.item(0).text(), 'Structure')
            manager.set_appearance(scale=140)
            self.assertEqual(manager.settings.value('interface_scale', type=int), 140)
            window.pages['About']._release = SimpleNamespace(version='1.0.6')
            for mode in ('light', 'dark'):
                manager.apply(mode)
                dialog = window.pages['About'].install_confirmation()
                dialog.show()
                self.app.processEvents()
                self.assertEqual(dialog.palette().window().color(), self.app.palette().window().color())
                dialog.close()
        finally:
            manager.set_appearance(scale=old[1], adaptive=old[2])
            manager.apply(old[0])
            window.close()


if __name__ == '__main__':
    unittest.main()
