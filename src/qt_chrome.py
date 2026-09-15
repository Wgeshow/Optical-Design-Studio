"""Theme-aware window chrome, with movement and resizing owned by the OS."""
import sys
from PyQt6.QtCore import Qt, QEvent, QPoint, QRect, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QIcon, QKeySequence, QAction, QActionGroup, QShortcut
from PyQt6.QtWidgets import QWidget, QFrame, QHBoxLayout, QLabel, QToolButton, QMenu

from qt_common import COLORS, theme_manager
from desktop_runtime import resource_root


class WindowsCustomFrame:
    """Keep the Win32 resize/maximize contract while drawing one Qt title bar.

    Microsoft requires HTMAXBUTTON for the Windows 11 Snap flyout. Coordinates
    in native messages are physical pixels, unlike Qt widget geometry.
    """
    def __init__(self, window):
        self.window = window
        self.enabled = False
        if sys.platform != 'win32':
            return
        from PyQt6.QtWidgets import QApplication
        if QApplication.platformName() != 'windows':
            return
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.types = ctypes, wintypes
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.GetWindowLongW.restype = wintypes.LONG
        self.user.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
        self.user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.user.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        self.user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user.IsZoomed.argtypes = [wintypes.HWND]
        self.user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        self.user.MonitorFromWindow.restype = wintypes.HANDLE
        self.hwnd = int(window.winId())
        self.enabled = True
        window._windows_frame = self
        # Subclass the HWND directly: the PyQt build shipped in the application
        # has a pointer-result nativeEvent binding that crashes on HWND creation.
        # Keep the callback alive for this HWND's lifetime.
        proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        self.user.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        self.user.SetWindowLongPtrW.restype = ctypes.c_void_p
        self.user.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.user.CallWindowProcW.restype = ctypes.c_ssize_t
        def window_proc(hwnd, message, wparam, lparam):
            msg = wintypes.MSG()
            msg.hWnd, msg.message, msg.wParam, msg.lParam = hwnd, message, wparam, lparam
            if message == 0x0082:  # WM_NCDESTROY: detach before Qt frees HWND.
                self.user.SetWindowLongPtrW(hwnd, -4, self._old_proc)
                self.enabled = False
            try:
                result = self.event(ctypes.addressof(msg))
            except Exception:
                result = None  # Never unwind a Python exception into Win32.
            if result is not None:
                return result[1]
            return self.user.CallWindowProcW(self._old_proc, hwnd, message, wparam, lparam)
        self._callback = proc_type(window_proc)
        self._old_proc = self.user.SetWindowLongPtrW(self.hwnd, -4, ctypes.cast(self._callback, ctypes.c_void_p))
        # WS_CAPTION preserves shell snap eligibility; WM_NCCALCSIZE removes
        # its visual non-client area. Keep minimize/maximize/system menu styles.
        style = self.user.GetWindowLongW(self.hwnd, -16)
        self.user.SetWindowLongW(self.hwnd, -16, style | 0x00CF0000)
        self.user.SetWindowPos(self.hwnd, None, 0, 0, 0, 0, 0x0027)

    def hit_test(self, point):
        """Return a Win32 hit code for a Qt logical client point."""
        w = self.window
        x, y = point.x(), point.y()
        if not (w.isMaximized() or w.isFullScreen()):
            left, right = x < 6, x >= w.width()-6
            top, bottom = y < 6, y >= w.height()-6
            if top and left: return 13
            if top and right: return 14
            if bottom and left: return 16
            if bottom and right: return 17
            if left: return 10
            if right: return 11
            if top: return 12
            if bottom: return 15
        chrome = w.chrome
        local = chrome.mapFrom(w, point)
        if chrome.maximize_button.geometry().contains(local):
            return 9  # HTMAXBUTTON: Windows owns hover and Snap Layout menu.
        return 1  # Interactive Qt controls and startSystemMove handle client.

    def event(self, message):
        if not self.enabled:
            return None
        c, t = self.ctypes, self.types
        msg = t.MSG.from_address(int(message))
        if msg.message == 0x0083:  # WM_NCCALCSIZE
            if msg.wParam and self.user.IsZoomed(msg.hWnd):
                class MonitorInfo(c.Structure):
                    _fields_ = [('size', t.DWORD), ('monitor', t.RECT), ('work', t.RECT), ('flags', t.DWORD)]
                info = MonitorInfo()
                info.size = c.sizeof(info)
                self.user.GetMonitorInfoW.argtypes = [t.HANDLE, c.POINTER(MonitorInfo)]
                monitor = self.user.MonitorFromWindow(msg.hWnd, 2)
                if self.user.GetMonitorInfoW(monitor, c.byref(info)):
                    rect = t.RECT.from_address(msg.lParam)
                    rect.left, rect.top = info.work.left, info.work.top
                    rect.right, rect.bottom = info.work.right, info.work.bottom
            return True, 0
        if msg.message == 0x0084:  # WM_NCHITTEST
            point = t.POINT(c.c_short(msg.lParam & 0xffff).value, c.c_short((msg.lParam >> 16) & 0xffff).value)
            self.user.ScreenToClient(msg.hWnd, c.byref(point))
            ratio = self.window.devicePixelRatioF()
            return True, self.hit_test(QPoint(round(point.x/ratio), round(point.y/ratio)))
        if msg.message in (0x00A1, 0x00A2) and msg.wParam == 9:
            # Non-client hits bypass QPushButton mouse events. Consume both
            # halves and toggle once on release, avoiding a second OS toggle.
            if msg.message == 0x00A2:
                self.window.chrome.toggle_maximize()
            return True, 0
        return None


class CaptionButton(QToolButton):
    """Small, high-DPI vector controls; no font-dependent symbol alignment."""
    def __init__(self, symbol, callback, parent=None):
        super().__init__(parent)
        self.symbol = symbol
        self.setFixedSize(46, 44)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoRaise(True)
        self.clicked.connect(callback)
        self.set_description(symbol)

    def set_description(self, symbol):
        self.symbol = symbol
        label = {'minimize': 'Minimize', 'maximize': 'Maximize', 'restore': 'Restore window', 'close': 'Close'}[symbol]
        self.setAccessibleName(label)
        self.setToolTip(label)
        self.update()

    def paintEvent(self, event):
        colors = COLORS[theme_manager().mode]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hover = self.underMouse() or self.hasFocus()
        if hover:
            painter.fillRect(self.rect(), QColor('#c42b35' if self.symbol == 'close' else colors['hover']))
        color = '#ffffff' if hover and self.symbol == 'close' else colors['text']
        painter.setPen(QPen(QColor(color), 1.2))
        x, y = self.width() / 2, self.height() / 2
        if self.symbol == 'minimize':
            painter.drawLine(QPoint(int(x - 5), int(y)), QPoint(int(x + 5), int(y)))
        elif self.symbol == 'maximize':
            painter.drawRect(QRectF(x - 5, y - 5, 10, 10))
        elif self.symbol == 'restore':
            painter.drawLine(QPoint(int(x - 2), int(y - 6)), QPoint(int(x + 6), int(y - 6)))
            painter.drawLine(QPoint(int(x + 6), int(y - 6)), QPoint(int(x + 6), int(y + 2)))
            painter.drawRect(QRectF(x - 5, y - 3, 8, 8))
        else:
            painter.drawLine(QPoint(int(x - 5), int(y - 5)), QPoint(int(x + 5), int(y + 5)))
            painter.drawLine(QPoint(int(x + 5), int(y - 5)), QPoint(int(x - 5), int(y + 5)))
        painter.end()


class ResizeHandle(QWidget):
    """Transparent perimeter grip, using logical pixels on every display."""
    def __init__(self, window, edges):
        super().__init__(window)
        self.edges = edges
        self.setObjectName('windowResizeHandle')
        self.setMouseTracking(True)
        horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
        vertical = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
        if horizontal and vertical:
            forward = edges in (Qt.Edge.TopEdge | Qt.Edge.LeftEdge, Qt.Edge.BottomEdge | Qt.Edge.RightEdge)
            cursor = Qt.CursorShape.SizeFDiagCursor if forward else Qt.CursorShape.SizeBDiagCursor
        else:
            cursor = Qt.CursorShape.SizeHorCursor if horizontal else Qt.CursorShape.SizeVerCursor
        self.setCursor(cursor)

    def mousePressEvent(self, event):
        window = self.window()
        if event.button() == Qt.MouseButton.LeftButton and not (window.isMaximized() or window.isFullScreen()):
            handle = window.windowHandle()
            if handle and handle.startSystemResize(self.edges):
                event.accept()
                return
        super().mousePressEvent(event)


class WindowChrome(QFrame):
    """A single compact title/action bar spanning the whole application."""
    def __init__(self, window, open_project, save_project, show_settings, native_frame=False):
        super().__init__(window)
        self.host = window
        self.native_frame = native_frame
        self.setObjectName('windowChrome')
        self.setFixedHeight(44)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        layout.setSpacing(2)
        self.logo = QLabel()
        self.logo.setPixmap(QIcon(str(resource_root() / 'S4_Studio.ico')).pixmap(24, 24))
        self.logo.setFixedSize(26, 28)
        self.logo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.logo)
        layout.addSpacing(7)
        self.title = QLabel(window.windowTitle())
        self.title.setObjectName('windowTitle')
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.title)
        layout.addSpacing(19)
        self.file_menu = QMenu(self)
        self.open_action = self.file_menu.addAction('Open project…', open_project)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.save_action = self.file_menu.addAction('Save project…', save_project)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        # Keep standard shortcuts active when the popup menu is closed.
        window.addActions([self.open_action, self.save_action])
        self.file_menu.addSeparator()
        self.file_menu.addAction('Exit', window.close)
        self.file_button = self.menu_button('&File', self.file_menu)
        layout.addWidget(self.file_button)
        self.view_menu = QMenu(self)
        group = QActionGroup(self)
        group.setExclusive(True)
        self.theme_actions = {}
        for key, label in (('dark', 'Dark mode'), ('light', 'Light mode')):
            action = QAction(label, self, checkable=True)
            action.triggered.connect(lambda checked, mode=key: theme_manager().apply(mode))
            group.addAction(action)
            self.view_menu.addAction(action)
            self.theme_actions[key] = action
        self.view_menu.addSeparator()
        self.view_menu.addAction('Settings', show_settings)
        self.view_button = self.menu_button('&View', self.view_menu)
        layout.addWidget(self.view_button)
        layout.addStretch(1)
        divider = QFrame()
        divider.setObjectName('captionDivider')
        divider.setFixedSize(1, 18)
        layout.addWidget(divider)
        layout.addSpacing(4)
        self.minimize_button = CaptionButton('minimize', window.showMinimized, self)
        self.maximize_button = CaptionButton('maximize', self.toggle_maximize, self)
        self.close_button = CaptionButton('close', window.close, self)
        for control in (self.minimize_button, self.maximize_button, self.close_button):
            layout.addWidget(control)
            control.setVisible(not native_frame)
        divider.setVisible(not native_frame)
        self.handles = []
        self.resize_edges = [Qt.Edge.TopEdge, Qt.Edge.BottomEdge, Qt.Edge.LeftEdge, Qt.Edge.RightEdge,
                             Qt.Edge.TopEdge | Qt.Edge.LeftEdge, Qt.Edge.TopEdge | Qt.Edge.RightEdge,
                             Qt.Edge.BottomEdge | Qt.Edge.LeftEdge, Qt.Edge.BottomEdge | Qt.Edge.RightEdge]
        for edge in ([] if native_frame else self.resize_edges):
            self.handles.append(ResizeHandle(window, edge))
        window.installEventFilter(self)
        window.windowTitleChanged.connect(self.title.setText)
        theme_manager().changed.connect(self.retheme)
        self.system_menu = QMenu(self)
        self.restore_action = self.system_menu.addAction('Restore', window.showNormal)
        self.system_menu.addAction('Minimize', window.showMinimized)
        self.maximize_action = self.system_menu.addAction('Maximize', window.showMaximized)
        self.system_menu.addSeparator()
        self.system_menu.addAction('Close', window.close).setShortcut(QKeySequence('Alt+F4'))
        self.system_shortcut = QShortcut(QKeySequence('Alt+Space'), window)
        self.system_shortcut.activated.connect(lambda: self.show_system_menu(self.mapToGlobal(QPoint(0, self.height()))))
        self.system_shortcut.setEnabled(not native_frame)
        self.retheme(theme_manager().mode)

    def action_button(self, text, callback):
        button = QToolButton(self)
        button.setText(text)
        button.setObjectName('chromeAction')
        button.setFixedHeight(30)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.clicked.connect(callback)
        return button

    def menu_button(self, text, menu):
        button = self.action_button(text, lambda: None)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setMenu(menu)
        return button

    def retheme(self, mode):
        for key, action in self.theme_actions.items():
            action.setChecked(key == mode)
        # Density changes alter stylesheet padding. Refresh the layout's cached
        # menu-button hints as well as repainting the caption controls.
        for button in (self.file_button, self.view_button):
            button.updateGeometry()
        self.layout().invalidate()
        self.update()
        for button in (self.minimize_button, self.maximize_button, self.close_button):
            button.update()

    def toggle_maximize(self):
        if self.host.isMaximized():
            self.host.showNormal()
        else:
            self.host.showMaximized()

    def update_window_state(self):
        self.maximize_button.set_description('restore' if self.host.isMaximized() else 'maximize')
        self.place_resize_handles()

    def place_resize_handles(self):
        width, height, grip = self.host.width(), self.host.height(), 5
        rectangles = [QRect(grip, 0, width - 2 * grip, grip),
                      QRect(grip, height - grip, width - 2 * grip, grip),
                      QRect(0, grip, grip, height - 2 * grip),
                      QRect(width - grip, grip, grip, height - 2 * grip),
                      QRect(0, 0, grip, grip), QRect(width - grip, 0, grip, grip),
                      QRect(0, height - grip, grip, grip), QRect(width - grip, height - grip, grip, grip)]
        visible = self.host.isVisible() and not (self.host.isMaximized() or self.host.isFullScreen())
        for handle, rectangle in zip(self.handles, rectangles):
            handle.setGeometry(rectangle)
            handle.setVisible(visible)
            if visible:
                handle.raise_()

    def eventFilter(self, watched, event):
        if watched is self.host:
            if event.type() == QEvent.Type.WindowStateChange:
                self.update_window_state()
            elif event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                self.place_resize_handles()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.host.windowHandle()
            if handle and handle.startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximize()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def show_system_menu(self, position):
        self.restore_action.setEnabled(self.host.isMaximized() or self.host.isMinimized())
        self.maximize_action.setEnabled(not self.host.isMaximized())
        self.system_menu.popup(position)

    def contextMenuEvent(self, event):
        self.show_system_menu(event.globalPos())
        event.accept()
