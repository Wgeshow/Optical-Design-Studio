"""Acrylic persists through state transitions without repeated DWM writes."""
import ctypes
from ctypes import wintypes
import os,tempfile,unittest
from types import SimpleNamespace
from unittest.mock import Mock
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
_library=tempfile.TemporaryDirectory(prefix='s4_glass_import_')
os.environ.setdefault('S4_LIBRARY_ROOT',_library.name)
from PyQt6.QtCore import QCoreApplication,QEvent,Qt
from PyQt6.QtWidgets import QApplication,QMainWindow,QVBoxLayout,QLabel
from qt_common import COLORS,theme_manager
from qt_surfaces import WorkspaceBackground
from qt_windows_glass import WindowsDesktopGlass,_Margins


class DesktopGlassTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.manager=theme_manager();self.previous=self.manager.look
        self.manager.apply_look('glass_dark',persist=False)
        self.window=QMainWindow();self.window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.window.resize(480,320)
        self.root=WorkspaceBackground(desktop_root=True);layout=QVBoxLayout(self.root)
        layout.addWidget(QLabel('Visible optical workspace'));layout.addStretch()
        self.window.setCentralWidget(self.root)
        self.adapter=WindowsDesktopGlass(self.window);self.window._desktop_glass=self.adapter
        self.adapter.supported=True;self.adapter.enabled=True
        self.adapter._install_native_notifications=Mock()
        self.adapter.user=SimpleNamespace(SetWindowLongW=Mock())
        self.requests=[];self.margins=[]
        def composition(pointer):
            ctypes.cast(pointer,ctypes.POINTER(wintypes.BOOL)).contents.value=True
            return 0
        def attribute(hwnd,key,pointer,size):
            self.requests.append((key,ctypes.cast(pointer,ctypes.POINTER(ctypes.c_int)).contents.value));return 0
        def extend(hwnd,pointer):
            m=ctypes.cast(pointer,ctypes.POINTER(_Margins)).contents
            self.margins.append((m.left,m.right,m.top,m.bottom));return 0
        self.adapter.dwm=SimpleNamespace(DwmIsCompositionEnabled=composition,DwmSetWindowAttribute=attribute,DwmExtendFrameIntoClientArea=extend)
        self.window.show();self.settle()
    def settle(self):
        for _ in range(3):self.app.processEvents()
    def tearDown(self):
        self.adapter._timer.stop();self.window.close();self.window.deleteLater();self.settle()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.manager.apply_look(self.previous,persist=False)
    def assert_frosted(self):
        color=self.root.grab().toImage().pixelColor(self.root.width()//2,self.root.height()-30)
        self.assertGreaterEqual(color.alpha(),96);self.assertLess(color.alpha(),255)
        self.assertTrue(self.adapter.active);self.assertTrue(self.adapter.alpha_active)
        self.assertEqual(self.window.windowOpacity(),1)
    def test_acrylic_is_enabled_with_full_frame_and_nonclear_tint(self):
        self.assertEqual([v for k,v in self.requests if k==38][-1],3)
        self.assertEqual(self.margins[-1],(-1,-1,-1,-1));self.assert_frosted()
    def test_repeated_maximize_restore_never_reconfigures_dwm_or_layered_style(self):
        before=len(self.requests)
        for _ in range(4):
            self.window.showMaximized();self.settle();self.assert_frosted()
            self.assertFalse(self.window.property('desktopGlassSuspended'))
            self.window.showNormal();self.settle();self.assert_frosted()
        self.assertEqual(len(self.requests),before);self.adapter.user.SetWindowLongW.assert_not_called()
    def test_fullscreen_and_resize_keep_same_backdrop(self):
        before=len(self.requests);self.window.showFullScreen();self.settle()
        self.adapter.eventFilter(self.window,QEvent(QEvent.Type.Resize));self.settle()
        self.assertEqual(len(self.requests),before);self.assert_frosted()
    def test_composition_loss_is_opaque_and_recovery_reapplies_acrylic(self):
        original=self.adapter.dwm.DwmIsCompositionEnabled
        self.adapter.dwm.DwmIsCompositionEnabled=Mock(return_value=-1);self.adapter._apply_native()
        self.assertFalse(self.adapter.alpha_active)
        color=self.root.grab().toImage().pixelColor(100,280)
        self.assertEqual(color.alpha(),255);self.assertEqual(color.name(),COLORS[self.manager.mode]['bg'])
        self.adapter.dwm.DwmIsCompositionEnabled=original;self.adapter._apply_native();self.settle();self.assert_frosted()
    def test_rejected_acrylic_never_exposes_clear_pixels(self):
        self.adapter._native_configuration=None
        self.adapter.dwm.DwmSetWindowAttribute=Mock(return_value=-1);self.adapter._apply_native()
        self.assertFalse(self.adapter.active);self.assertFalse(self.adapter.alpha_active)
        self.assertEqual(self.root.grab().toImage().pixelColor(100,280).alpha(),255)
    def test_theme_changes_reapply_once_and_disable_removes_backdrop(self):
        self.adapter.apply(True,'light');self.settle()
        self.assertEqual([v for k,v in self.requests if k==20][-1],False)
        before=len(self.requests);self.adapter.apply(True,'light');self.settle();self.assertEqual(len(self.requests),before)
        self.adapter.apply(False,'light');self.settle()
        self.assertEqual([v for k,v in self.requests if k==38][-1],1)
        self.assertEqual(self.margins[-1],(0,0,0,0));self.assertFalse(self.adapter.alpha_active)


if __name__=='__main__':unittest.main()
