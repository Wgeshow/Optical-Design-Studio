"""Glass widget alpha must reach the desktop compositor without fading controls."""
import os
import tempfile
import unittest
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
_library=tempfile.TemporaryDirectory(prefix='desktop_surfaces_')
os.environ.setdefault('S4_LIBRARY_ROOT',_library.name)

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication
from qt_common import theme_manager
from qt_surfaces import WorkspaceBackground, WorkspacePanel


class DesktopSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.manager=theme_manager();self.previous=self.manager.look

    def tearDown(self):
        self.manager.apply_look(self.previous,persist=False)

    def capture(self,widget):
        widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        widget.resize(100,80)
        image=QImage(widget.size(),QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        widget.render(image)
        widget.deleteLater()
        return image

    def test_desktop_root_is_translucent_but_solid_looks_are_opaque(self):
        for look in ('glass_dark','glass_light','dark','light'):
            self.manager.apply_look(look,persist=False)
            root=WorkspaceBackground(desktop_root=True)
            root._desktop_glass=SimpleNamespace(active=True)
            image=self.capture(root)
            alpha=image.pixelColor(50,40).alpha()
            if look.startswith('glass_'):
                self.assertGreater(alpha,0)
                self.assertLess(alpha,100)
                self.assertEqual(image.pixelColor(0,0).alpha(),0)
            else:self.assertEqual(alpha,255)

    def test_nested_glass_background_does_not_hide_desktop(self):
        for look in ('glass_dark','glass_light'):
            self.manager.apply_look(look,persist=False)
            image=self.capture(WorkspaceBackground())
            self.assertEqual(image.pixelColor(50,40).alpha(),0)

    def test_unsupported_preview_has_one_readable_opaque_fallback(self):
        self.manager.apply_look('glass_dark',persist=False)
        root=WorkspaceBackground(desktop_root=True)
        root._desktop_glass=SimpleNamespace(active=False)
        self.assertEqual(self.capture(root).pixelColor(50,40).alpha(),255)

    def test_panel_itself_preserves_translucency(self):
        for look in ('glass_dark','glass_light'):
            self.manager.apply_look(look,persist=False)
            alpha=self.capture(WorkspacePanel()).pixelColor(50,40).alpha()
            self.assertGreater(alpha,90)
            self.assertLess(alpha,220)


if __name__=='__main__':unittest.main()
