"""Glass widget alpha must reach the desktop compositor without fading controls."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
_library=tempfile.TemporaryDirectory(prefix='desktop_surfaces_')
os.environ.setdefault('S4_LIBRARY_ROOT',_library.name)

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication, QLineEdit
from qt_common import theme_manager, ThemeManager, clamp_alpha
from qt_surfaces import WorkspaceBackground, WorkspacePanel


class DesktopSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.manager=theme_manager();self.previous=self.manager.look
        self.previous_settings=self.manager.settings
        self.previous_opacity=self.manager.glass_opacity
        self.temp=tempfile.TemporaryDirectory()
        self.manager.settings=QSettings(self.temp.name+'/appearance.ini',QSettings.Format.IniFormat)
        self.manager.glass_opacity=76

    def tearDown(self):
        self.manager.settings=self.previous_settings
        self.manager.glass_opacity=self.previous_opacity
        self.manager.apply_look(self.previous,persist=False)
        self.temp.cleanup()

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

    def test_new_opacity_range_persists_and_clamps_at_both_endpoints(self):
        self.manager.apply_look('glass_dark',persist=False)
        for supplied,expected in ((-5,0),(0,0),(17,17),(50,50),(65,65),(95,95),(100,100),(105,100)):
            with self.subTest(opacity=supplied):
                self.manager.set_glass_opacity(supplied)
                # A fresh QSettings instance reads persisted bytes, as at launch.
                settings=QSettings(self.temp.name+'/appearance.ini',QSettings.Format.IniFormat)
                with patch('qt_common.preferences',return_value=settings):
                    restored=ThemeManager()
                self.assertEqual(restored.glass_opacity,expected)
        self.assertEqual(clamp_alpha(-30),0)
        self.assertEqual(clamp_alpha(300),255)

    def test_low_opacity_reduces_actual_root_and_panel_pixels_to_zero(self):
        for look in ('glass_dark','glass_light'):
            self.manager.apply_look(look,persist=False)
            roots=[];panels=[]
            for opacity in (0,10,35,64,65,95,100):
                self.manager.set_glass_opacity(opacity)
                root=WorkspaceBackground(desktop_root=True)
                root._desktop_glass=SimpleNamespace(active=True)
                roots.append(self.capture(root).pixelColor(50,40).alpha())
                panels.append(self.capture(WorkspacePanel()).pixelColor(50,40).alpha())
            self.assertEqual(roots[0],0)
            self.assertEqual(panels[0],0)
            # Neighboring percentages may round to the same 8-bit alpha.
            self.assertTrue(all(a<=b for a,b in zip(roots,roots[1:])))
            self.assertTrue(all(a<=b for a,b in zip(panels,panels[1:])))
            self.assertLess(roots[1],roots[2]);self.assertLess(roots[2],roots[3])
            self.assertLess(panels[1],panels[2]);self.assertLess(panels[2],panels[3])
            self.assertEqual(roots[4],20)  # Previous 65% appearance is unchanged.

    def test_zero_surface_opacity_keeps_controls_and_unsupported_fallback_opaque(self):
        self.manager.apply_look('glass_dark',persist=False)
        self.manager.set_glass_opacity(0)
        root=WorkspaceBackground(desktop_root=True)
        root._desktop_glass=SimpleNamespace(active=True)
        field=QLineEdit('Readable input',root)
        field.setGeometry(10,10,80,30)
        self.assertEqual(root.windowOpacity(),1)
        image=self.capture(root)
        self.assertEqual(image.pixelColor(50,60).alpha(),0)
        self.assertEqual(image.pixelColor(50,30).alpha(),255)
        fallback=WorkspaceBackground(desktop_root=True)
        fallback._desktop_glass=SimpleNamespace(active=False)
        self.assertEqual(self.capture(fallback).pixelColor(50,40).alpha(),255)


if __name__=='__main__':unittest.main()
