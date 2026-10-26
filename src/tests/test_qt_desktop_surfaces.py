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
from PyQt6.QtWidgets import QApplication, QLineEdit, QGroupBox, QLabel
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
        self.manager.glass_opacity=35

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
            root._desktop_glass=SimpleNamespace(active=True, alpha_active=True)
            image=self.capture(root)
            alpha=image.pixelColor(50,40).alpha()
            if look.startswith('glass_'):
                self.assertGreaterEqual(alpha,96)
                self.assertLess(alpha,255)
                self.assertGreaterEqual(image.pixelColor(0,0).alpha(),96)
            else:self.assertEqual(alpha,255)

    def test_nested_glass_background_does_not_hide_desktop(self):
        for look in ('glass_dark','glass_light'):
            self.manager.apply_look(look,persist=False)
            image=self.capture(WorkspaceBackground())
            self.assertEqual(image.pixelColor(50,40).alpha(),0)

    def test_unsupported_preview_has_one_readable_opaque_fallback(self):
        self.manager.apply_look('glass_dark',persist=False)
        root=WorkspaceBackground(desktop_root=True)
        root._desktop_glass=SimpleNamespace(active=False, alpha_active=False)
        self.assertEqual(self.capture(root).pixelColor(50,40).alpha(),255)

    def test_panel_itself_has_honest_opacity_below_edge_sheen(self):
        for look in ('glass_dark','glass_light'):
            self.manager.apply_look(look,persist=False)
            image=self.capture(WorkspacePanel())
            expected=clamp_alpha(self.manager.glass_opacity*2.55)
            # The subtle upper edge sheen is decorative. Sample below it so
            # the actual panel fill must match the selected percentage exactly.
            for x,y in ((30,50),(50,55),(70,60)):
                self.assertEqual(image.pixelColor(x,y).alpha(),expected)

    def test_fresh_settings_default_to_thirty_five_percent(self):
        settings=QSettings(self.temp.name+'/fresh.ini',QSettings.Format.IniFormat)
        with patch('qt_common.preferences',return_value=settings):
            restored=ThemeManager()
        self.assertEqual(restored.glass_opacity,35)

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
                root._desktop_glass=SimpleNamespace(active=True, alpha_active=True)
                roots.append(self.capture(root).pixelColor(50,40).alpha())
                panels.append(self.capture(WorkspacePanel()).pixelColor(50,40).alpha())
            self.assertGreaterEqual(roots[0],96)
            self.assertEqual(panels[0],0)
            self.assertEqual(roots,[roots[0]]*len(roots))
            self.assertEqual(panels,[clamp_alpha(p*2.55) for p in (0,10,35,64,65,95,100)])

    def test_nested_groups_do_not_add_another_glass_fill(self):
        self.manager.apply_look('glass_dark',persist=False)
        group=QGroupBox()
        group.setObjectName('nestedGlassTest')
        image=self.capture(group)
        self.assertEqual(image.pixelColor(50,40).alpha(),0)

    def test_blank_label_area_keeps_the_single_panel_alpha_without_a_plate(self):
        for look in ('glass_dark','glass_light'):
            self.manager.apply_look(look,persist=False)
            self.manager.glass_opacity=35
            panel=WorkspacePanel()
            label=QLabel('Optical label',panel)
            label.setGeometry(10,45,80,25)
            # Leave the lower-right label area blank while retaining real text
            # in the widget. Its pixels must show only the parent panel fill.
            label.setAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignTop)
            image=self.capture(panel)
            expected=clamp_alpha(35*2.55)
            self.assertEqual(image.pixelColor(85,66).alpha(),expected)
            self.assertEqual(image.pixelColor(50,73).alpha(),expected)

    def test_zero_surface_opacity_keeps_controls_and_unsupported_fallback_opaque(self):
        self.manager.apply_look('glass_dark',persist=False)
        self.manager.set_glass_opacity(0)
        root=WorkspaceBackground(desktop_root=True)
        root._desktop_glass=SimpleNamespace(active=True, alpha_active=True)
        field=QLineEdit('Readable input',root)
        field.setGeometry(10,10,80,30)
        self.assertEqual(root.windowOpacity(),1)
        image=self.capture(root)
        self.assertGreaterEqual(image.pixelColor(50,60).alpha(),96)
        self.assertLess(image.pixelColor(50,60).alpha(),255)
        self.assertEqual(image.pixelColor(50,30).alpha(),255)
        fallback=WorkspaceBackground(desktop_root=True)
        fallback._desktop_glass=SimpleNamespace(active=False, alpha_active=False)
        self.assertEqual(self.capture(fallback).pixelColor(50,40).alpha(),255)

    def test_maximized_alpha_without_native_acrylic_preserves_controls_at_zero_opacity(self):
        for look in ('glass_dark', 'glass_light'):
            self.manager.apply_look(look, persist=False)
            self.manager.glass_opacity = 0
            root = WorkspaceBackground(desktop_root=True)
            root.setWindowState(Qt.WindowState.WindowMaximized)
            root._desktop_glass = SimpleNamespace(active=False, alpha_active=True)
            field = QLineEdit('Readable input', root)
            field.setGeometry(10, 10, 80, 30)
            image = self.capture(root)
            self.assertGreaterEqual(image.pixelColor(50, 60).alpha(),96)
            self.assertLess(image.pixelColor(50, 60).alpha(),255)
            self.assertEqual(image.pixelColor(50, 30).alpha(), 255)
            self.assertEqual(root.windowOpacity(), 1)

    def test_maximized_unsupported_alpha_fallback_and_solid_looks_remain_opaque(self):
        for look, alpha_active in (('glass_dark', False), ('glass_light', False),
                                   ('dark', True), ('light', True)):
            self.manager.apply_look(look, persist=False)
            self.manager.glass_opacity = 0
            root = WorkspaceBackground(desktop_root=True)
            root.setWindowState(Qt.WindowState.WindowMaximized)
            root._desktop_glass = SimpleNamespace(active=False, alpha_active=alpha_active)
            self.assertEqual(self.capture(root).pixelColor(50, 40).alpha(), 255)


if __name__=='__main__':unittest.main()
