"""Frosted desktop Acrylic for the Windows Qt raster window and custom chrome.

Prepare the widget before ``winId()`` (and therefore WindowsCustomFrame), then
construct WindowsDesktopGlass after WindowsCustomFrame and call apply for each
appearance change. The alpha channel stays allocated for the window lifetime;
ordinary themes paint it opaque. No whole-window opacity is used.

Windows draws the blurred Acrylic backdrop beneath tinted Qt surfaces. Keep
WS_EX_LAYERED under Qt's ownership in every state: Qt reallocates its alpha
buffer during maximize/restore and native flag mutation can blank the client.
The caption/resize styles and FramelessWindowHint remain owned by custom chrome.

References:
https://doc.qt.io/qt-6/qwidget.html#creating-translucent-windows
https://learn.microsoft.com/windows/win32/api/dwmapi/ne-dwmapi-dwm_systembackdrop_type
https://learn.microsoft.com/windows/win32/api/dwmapi/nf-dwmapi-dwmextendframeintoclientarea
"""

import ctypes
import sys
from ctypes import wintypes

from PyQt6.QtCore import QObject, QEvent, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication


def prepare_window_translucency(window):
    """Allocate Qt's alpha backing store before native window creation.

    Keep this attribute for every look, including B, to support later look
    switches without destroying the HWND and the custom frame callback.
    Return false if the caller attempted late preparation.
    """
    if sys.platform != 'win32' or QApplication.platformName() != 'windows':
        return False
    if (window.testAttribute(Qt.WidgetAttribute.WA_WState_Created)
            and not window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)):
        return False
    window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    window.setAutoFillBackground(False)
    return True


class _Margins(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in ('left', 'right', 'top', 'bottom')]


class _AccentPolicy(ctypes.Structure):
    _fields_=[('state',ctypes.c_int),('flags',ctypes.c_int),('color',wintypes.DWORD),('animation',ctypes.c_int)]


class _CompositionAttribute(ctypes.Structure):
    _fields_=[('attribute',ctypes.c_int),('data',ctypes.c_void_p),('size',ctypes.c_size_t)]


class WindowsDesktopGlass(QObject):
    """Configure clear composition after Qt finishes showing.

    ``active`` records accepted normal-window compositor configuration;
    ``alpha_active`` also covers maximized/fullscreen Qt alpha painting.
    Neither flag alone is visual proof. Unsupported hosts paint an opaque
    fallback, and no system transparency preference is changed.
    """
    changed = pyqtSignal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.active = False
        self.alpha_active = False
        self._composition_available = False
        self.enabled = False
        self.mode = 'dark'
        self.supported = False
        self.reason = 'Desktop glass requires Windows 11 build 22621 or later.'
        self.last_hresult = {}
        self.hwnd = 0
        self._old_proc = None
        self._callback = None
        self._native_configuration = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._apply_native)
        window.installEventFilter(self)
        if sys.platform != 'win32' or QApplication.platformName() != 'windows':
            self.reason = 'The current Qt platform has no Windows desktop compositor.'
            return
        if sys.getwindowsversion().build < 22621:
            return
        if not window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
            self.reason = 'Qt translucency was not prepared before native window creation.'
            return
        try:
            self.user = ctypes.WinDLL('user32', use_last_error=True)
            self.dwm = ctypes.WinDLL('dwmapi', use_last_error=True)
            self.user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            self.user.GetWindowLongW.restype = wintypes.LONG
            self.user.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
            self.user.SetWindowLongW.restype = wintypes.LONG
            self.user.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            self.user.SetWindowLongPtrW.restype = ctypes.c_void_p
            self.user.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND,
                                                 wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            self.user.CallWindowProcW.restype = ctypes.c_ssize_t
            self.dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                                      ctypes.c_void_p, wintypes.DWORD]
            self.dwm.DwmSetWindowAttribute.restype = ctypes.c_long
            self.dwm.DwmExtendFrameIntoClientArea.argtypes = [wintypes.HWND, ctypes.POINTER(_Margins)]
            self.dwm.DwmExtendFrameIntoClientArea.restype = ctypes.c_long
            self.dwm.DwmIsCompositionEnabled.argtypes = [ctypes.POINTER(wintypes.BOOL)]
            self.dwm.DwmIsCompositionEnabled.restype = ctypes.c_long
            self._accent_api=getattr(self.user,'SetWindowCompositionAttribute',None)
            if self._accent_api is not None:
                self._accent_api.argtypes=[wintypes.HWND,ctypes.POINTER(_CompositionAttribute)]
                self._accent_api.restype=wintypes.BOOL
            self.supported = True
            self.reason = 'Frosted desktop Acrylic is available.'
        except (OSError, AttributeError):
            self.reason = 'Windows desktop compositor functions are unavailable.'

    def apply(self, enabled=False, mode='dark'):
        """Select the desired look; applying after Show avoids Qt resetting it."""
        requested_enabled = bool(enabled)
        requested_mode = 'light' if mode == 'light' else 'dark'
        unchanged = (self.enabled, self.mode) == (requested_enabled, requested_mode)
        self.enabled, self.mode = requested_enabled, requested_mode
        self._sync_suspension()
        if not self.supported:
            self._set_active(False)
            return False
        if self.window.isVisible() and not (unchanged and self.active == self._use_native_glass() and self.hwnd):
            self._timer.start(0)
        return self.supported and self.enabled

    def _use_native_glass(self):
        """Acrylic uses the same compositor configuration in every state."""
        return self.enabled

    def _sync_suspension(self):
        suspended = False
        self.window.setProperty('desktopGlassSuspended', suspended)
        if suspended:
            self._set_active(False)
        self._sync_alpha()
        return suspended

    def _sync_alpha(self):
        """Transparent painting and native Acrylic are separate capabilities.

        Qt's enlarged layered backing store retains per-pixel alpha.
        Never fade the whole window: labels and controls retain their pixels.
        """
        alpha = self.supported and self.enabled and self._composition_available and self.active
        if self.alpha_active != alpha:
            self.alpha_active = alpha
            self.window.setProperty('desktopGlassAlphaActive', alpha)
            self.changed.emit()
            self.window.update()
            central = getattr(self.window, 'centralWidget', lambda: None)()
            if central is not None:
                central.update()

    def _set_active(self, active):
        active = bool(active)
        if self.active != active:
            self.active = active
            self.window.setProperty('desktopGlassActive', active)
            self.changed.emit()
        self._sync_alpha()
        self.window.update()
        central = getattr(self.window, 'centralWidget', lambda: None)()
        if central is not None:
            central.update()

    def _install_native_notifications(self, hwnd):
        if self.hwnd == hwnd and self._old_proc:
            return
        self.hwnd = hwnd
        proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM)

        def callback(native_hwnd, message, wparam, lparam):
            old_proc = self._old_proc
            # A small outer subclass observes only compositor/theme changes;
            # WindowsCustomFrame continues owning all caption/Snap hit tests.
            if message == 0x0082:  # WM_NCDESTROY
                self.user.SetWindowLongPtrW(native_hwnd, -4, old_proc)
                self._old_proc = None
                self.hwnd = 0
                try:
                    self._timer.stop()
                except RuntimeError:
                    pass  # QObject parent may already be tearing down.
            elif message in (0x0320, 0x031A, 0x001A):
                # WM_DWMCOMPOSITIONCHANGED, WM_THEMECHANGED, WM_SETTINGCHANGE.
                try:
                    if message == 0x0320:self._native_configuration=None
                    self._timer.start(50)
                except RuntimeError:
                    pass
            return self.user.CallWindowProcW(old_proc, native_hwnd, message, wparam, lparam)

        self._callback = proc_type(callback)
        self._old_proc = self.user.SetWindowLongPtrW(hwnd, -4, ctypes.cast(self._callback, ctypes.c_void_p))

    def _apply_native(self):
        suspended = self._sync_suspension()
        if not self.supported or not self.window.isVisible():
            return
        try:
            hwnd = int(self.window.winId())
            self._install_native_notifications(hwnd)
            composition = wintypes.BOOL()
            composition_hr = self.dwm.DwmIsCompositionEnabled(ctypes.byref(composition))
            self._composition_available = composition_hr == 0 and bool(composition.value)
            self._sync_alpha()
            if composition_hr != 0 or not composition.value:
                self._native_configuration=None
                self.reason = 'Desktop composition is unavailable; opaque fallback is active.'
                self._set_active(False)
                return
            use_glass = self._use_native_glass()
            configuration=(hwnd,use_glass,self.mode)
            if self._native_configuration==configuration:
                return
            # Qt owns its layered backing store in every window state.
            accent_api=getattr(self,'_accent_api',None)
            margins = _Margins(*((-1,-1,-1,-1) if use_glass else (0,0,0,0)))
            dark = wintypes.BOOL(self.mode == 'dark')
            backdrop = ctypes.c_int(3 if use_glass and accent_api is None else 1)
            self.last_hresult = {
                'composition': int(composition_hr),
                'dark_mode': int(self.dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))),
                'extend_frame': int(self.dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))),
                'system_backdrop': int(self.dwm.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(backdrop), ctypes.sizeof(backdrop))),
            }
            if accent_api is not None:
                # Qt owns a layered raster HWND. Its Acrylic accent supplies
                # live blur; DWMWA_SYSTEMBACKDROP alone may paint an opaque
                # fallback on that HWND. Never change its layered style.
                tint=0x46191614 if self.mode=='dark' else 0x50F6F4F3
                accent=_AccentPolicy(4 if use_glass else 0,0,tint,0)
                attribute=_CompositionAttribute(19,ctypes.cast(ctypes.pointer(accent),ctypes.c_void_p),ctypes.sizeof(accent))
                self.last_hresult['acrylic_accent']=0 if accent_api(hwnd,ctypes.byref(attribute)) else -1
            # The frame adapter keeps WS_CAPTION/WS_THICKFRAME, so Windows can
            # retain its rounded outer HWND and native resize/Snap contract.
            corner = ctypes.c_int(2)  # DWMWCP_ROUND.
            self.last_hresult['rounded_corner'] = int(self.dwm.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner)))
            accepted = self.last_hresult['extend_frame'] == 0 and self.last_hresult['system_backdrop'] == 0 and self.last_hresult.get('acrylic_accent',0)==0
            self._native_configuration=configuration if accepted else None
            self.reason = ('Frosted desktop Acrylic is configured.'
                           if accepted and use_glass else
                           'Desktop glass is disabled.' if not self.enabled else
                           'Windows rejected Acrylic configuration; opaque fallback is active.')
            self._set_active(accepted and use_glass)
        except (OSError, RuntimeError, ValueError) as error:
            self._composition_available = False
            self._native_configuration=None
            self.reason = 'Frosted desktop Acrylic could not be applied: ' + str(error)
            self._set_active(False)

    def eventFilter(self, watched, event):
        if watched is self.window:
            if event.type() == QEvent.Type.WindowStateChange:
                # Resizing/maximizing does not change HWND backdrop attributes.
                # Avoid reentering DWM during Qt's backing-store transition.
                self._sync_suspension()
            elif not self.supported:
                return super().eventFilter(watched, event)
            elif event.type() == QEvent.Type.Show:
                self._timer.start(0)
            elif event.type() == QEvent.Type.WinIdChange:
                self._native_configuration=None
                self._timer.start(50)
        return super().eventFilter(watched, event)
