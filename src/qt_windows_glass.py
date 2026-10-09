"""Desktop Acrylic for the Windows Qt raster window, preserving custom chrome.

Prepare the widget before ``winId()`` (and therefore WindowsCustomFrame), then
construct WindowsDesktopGlass after WindowsCustomFrame and call apply for each
appearance change. The alpha channel stays allocated for the window lifetime;
ordinary themes paint it opaque. No whole-window opacity is used.

The documented Windows 11 backdrop API supplies real blur of other windows.
Qt's raster backing store initially uses WS_EX_LAYERED, which prevents this
backdrop from appearing. Clearing that flag before the DWM request lets DWM
compose the material; Qt may restore the flag on its next alpha-buffer flush.
Keep the caption/resize styles and FramelessWindowHint owned by custom chrome.
Maximized/fullscreen windows use the theme's opaque workspace fallback: Qt
reallocates its layered alpha buffer during these transitions, and removing
WS_EX_LAYERED at that point can leave DWM displaying a blank client surface.
Restoring the window enables Desktop Acrylic again.

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


class WindowsDesktopGlass(QObject):
    """Apply the supported compositor material after Qt finishes showing.

    ``active`` means the native Desktop Acrylic request was accepted. Windows
    itself can substitute an opaque material for accessibility, power, remote
    session or transparency preferences; this flag is not visual proof. The
    module never changes those preferences. Unsupported hosts retain Qt alpha
    transparency so the caller can paint an honest fallback.
    """
    changed = pyqtSignal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.active = False
        self.enabled = False
        self.mode = 'dark'
        self.supported = False
        self.reason = 'Desktop Acrylic requires Windows 11 build 22621 or later.'
        self.last_hresult = {}
        self.hwnd = 0
        self._old_proc = None
        self._callback = None
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
            self.supported = True
            self.reason = 'Desktop Acrylic is available.'
        except (OSError, AttributeError):
            self.reason = 'Windows DWM backdrop functions are unavailable.'

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
        """Avoid changing the layered alpha contract on a maximized surface."""
        return self.enabled and not (self.window.isMaximized() or self.window.isFullScreen())

    def _sync_suspension(self):
        suspended = self.enabled and not self._use_native_glass()
        self.window.setProperty('desktopGlassSuspended', suspended)
        if suspended:
            self._set_active(False)
        return suspended

    def _set_active(self, active):
        active = bool(active)
        if self.active != active:
            self.active = active
            self.window.setProperty('desktopGlassActive', active)
            self.changed.emit()
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
            if composition_hr != 0 or not composition.value:
                self.reason = 'Desktop composition is currently unavailable; Qt alpha fallback is active.'
                self._set_active(False)
                return
            use_glass = self._use_native_glass()
            if use_glass:
                exstyle = self.user.GetWindowLongW(hwnd, -20)
                if exstyle & 0x00080000:  # WS_EX_LAYERED, never WS_EX_TRANSPARENT.
                    self.user.SetWindowLongW(hwnd, -20, exstyle & ~0x00080000)
                margins = _Margins(-1, -1, -1, -1)
            else:
                margins = _Margins(0, 0, 0, 0)
            dark = wintypes.BOOL(self.mode == 'dark')
            backdrop = ctypes.c_int(3 if use_glass else 1)  # TRANSIENTWINDOW / NONE.
            self.last_hresult = {
                'composition': int(composition_hr),
                'dark_mode': int(self.dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))),
                'extend_frame': int(self.dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))),
                'system_backdrop': int(self.dwm.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(backdrop), ctypes.sizeof(backdrop))),
            }
            # The frame adapter keeps WS_CAPTION/WS_THICKFRAME, so Windows can
            # retain its rounded outer HWND and native resize/Snap contract.
            corner = ctypes.c_int(2)  # DWMWCP_ROUND.
            self.last_hresult['rounded_corner'] = int(self.dwm.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner)))
            accepted = self.last_hresult['extend_frame'] == 0 and self.last_hresult['system_backdrop'] == 0
            self.reason = ('Maximized/fullscreen window uses an opaque workspace to preserve Qt painting.'
                           if suspended else
                           'Desktop Acrylic requested successfully; Windows controls material fallback.'
                           if accepted and use_glass else
                           'Desktop Acrylic is disabled.' if not self.enabled else
                           'Windows rejected Desktop Acrylic; Qt alpha fallback is active.')
            self._set_active(accepted and use_glass)
        except (OSError, RuntimeError, ValueError) as error:
            self.reason = 'Desktop Acrylic could not be applied: ' + str(error)
            self._set_active(False)

    def eventFilter(self, watched, event):
        if watched is self.window:
            if event.type() == QEvent.Type.WindowStateChange:
                # Switch the root paint to opaque before the enlarged raster
                # buffer's first flush. Keep Qt's layered flag intact, and
                # retire/re-enable the DWM backdrop once state processing ends.
                self._sync_suspension()
                if self.supported:
                    self._timer.start(0)
            elif not self.supported:
                return super().eventFilter(watched, event)
            elif event.type() == QEvent.Type.Show:
                self._timer.start(0)
            elif event.type() == QEvent.Type.WinIdChange:
                self._timer.start(50)
            elif event.type() == QEvent.Type.Resize and self.enabled:
                # Reapply after Qt recreates/reallocates its raster backing store.
                if self._use_native_glass():
                    self._timer.start(75)
                else:
                    self._set_active(False)
                    self._timer.start(0)
        return super().eventFilter(watched, event)
