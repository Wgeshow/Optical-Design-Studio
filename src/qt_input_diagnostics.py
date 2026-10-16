"""Accessible missing-input list and exact-widget reveal/highlight helpers."""
from __future__ import annotations

import weakref

from PyQt6.QtCore import Qt, QEvent, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QScrollArea, QStackedWidget, QTabWidget,
    QToolBox, QVBoxLayout, QWidget)

from input_diagnostics import normalize_diagnostic


class DiagnosticPanel(QFrame):
    activated = pyqtSignal(dict)
    recheckRequested = pyqtSignal()
    returnRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('missingInputsPanel')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        self.heading = QLabel('Missing inputs')
        self.heading.setAccessibleName('Missing inputs and invalid settings')
        layout.addWidget(self.heading)
        self.list = QListWidget()
        self.list.setObjectName('setupValidation')
        self.list.setAccessibleName('Missing inputs; choose an issue to go to its field')
        self.list.setMaximumHeight(140)
        self.list.setWordWrap(True)
        self.list.itemClicked.connect(self._activate)
        self.list.installEventFilter(self)
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        self.first_button = QPushButton('Go to first missing input')
        self.first_button.clicked.connect(self.go_to_first)
        self.recheck_button = QPushButton('Recheck inputs')
        self.recheck_button.clicked.connect(self.recheckRequested)
        self.return_button = QPushButton('Back to issues')
        self.return_button.clicked.connect(self.returnRequested)
        for button in (self.first_button, self.recheck_button, self.return_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.hide()

    def set_diagnostics(self, diagnostics, *, workspace='', revision=''):
        current = self.list.currentItem()
        selected = current.data(Qt.ItemDataRole.UserRole).get('id') if current else None
        scroll = self.list.verticalScrollBar().value()
        self.list.clear()
        for value in diagnostics:
            row = normalize_diagnostic(value, workspace=workspace, revision=revision)
            route = ' › '.join(str(row[key]) for key in ('workspace', 'section', 'object_id', 'field') if row.get(key))
            units = ' [' + row['units'] + ']' if row.get('units') else ''
            item = QListWidgetItem(row['message'] + units + ('\n' + route if route else ''))
            item.setData(Qt.ItemDataRole.UserRole, row)
            item.setToolTip('Go to field: ' + route if row.get('field') else 'Open the owning section to resolve this issue.')
            self.list.addItem(item)
            if row['id'] == selected:
                self.list.setCurrentItem(item)
        self.list.verticalScrollBar().setValue(scroll)
        self.heading.setText(f'Missing inputs · {self.list.count()} issue(s)')
        self.first_button.setEnabled(bool(self.list.count()))
        self.setVisible(bool(self.list.count()))

    def _activate(self, item):
        if item is not None:
            self.list.setCurrentItem(item)
            self.activated.emit(dict(item.data(Qt.ItemDataRole.UserRole)))

    def go_to_first(self):
        self._activate(self.list.item(0))

    def eventFilter(self, watched, event):
        if watched is self.list and event.type() == QEvent.Type.KeyPress and event.key() in (
                Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._activate(self.list.currentItem() or self.list.item(0))
            return True
        return super().eventFilter(watched, event)


def reveal_and_focus(widget, *, message=''):
    """Reveal containing pages without changing model switches or draft values."""
    if widget is None:
        return False
    child, parent = widget, widget.parentWidget()
    scrolls = []
    while parent is not None:
        if isinstance(parent, (QStackedWidget, QTabWidget, QToolBox)):
            index = next((i for i in range(parent.count())
                          if parent.widget(i) is widget or parent.widget(i).isAncestorOf(widget)), -1)
            if index >= 0:
                parent.setCurrentIndex(index)
        if isinstance(parent, QScrollArea):
            scrolls.append(parent)
        child, parent = parent, parent.parentWidget()
    # A disabled model's conditional fields must not be enabled by navigation.
    if not widget.isEnabled() or not widget.isVisible():
        return False
    for scroll in reversed(scrolls):
        scroll.ensureWidgetVisible(widget, 24, 32)
    widget.setFocus(Qt.FocusReason.OtherFocusReason)
    if message:
        widget.setAccessibleDescription(message)
    old = widget.findChild(QFrame, 'diagnosticFieldHighlight', Qt.FindChildOption.FindDirectChildrenOnly)
    if old is not None:
        old.deleteLater()
    border = QFrame(widget)
    border.setObjectName('diagnosticFieldHighlight')
    border.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    border.setStyleSheet('QFrame#diagnosticFieldHighlight { background: transparent; border: 2px solid #efb44c; border-radius: 3px; }')
    border.setGeometry(widget.rect())
    border.show()
    border.raise_()
    border_ref = weakref.ref(border)
    def clear():
        try:
            existing = border_ref()
            if existing is not None:
                existing.deleteLater()
        except RuntimeError:
            pass  # The editor may have closed while the highlight was visible.
    QTimer.singleShot(4500, clear)
    return True
