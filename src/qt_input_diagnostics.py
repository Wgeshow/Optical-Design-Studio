"""Accessible missing-input list and exact-widget reveal/highlight helpers."""
from __future__ import annotations

import weakref

from PyQt6.QtCore import Qt, QEvent, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget,
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
        self.group_filter = QComboBox(self)
        self.group_filter.setAccessibleName('Filter input issues by section or object')
        self.group_filter.addItem('All input issues', '')
        self.group_filter.currentIndexChanged.connect(self._filter_issues)
        layout.addWidget(self.group_filter)
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
        selected_group = self.group_filter.currentData()
        self.group_filter.blockSignals(True)
        self.group_filter.clear()
        self.group_filter.addItem('All input issues', '')
        groups = dict.fromkeys(self._group(self.list.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(self.list.count()))
        for group in groups:
            if group:self.group_filter.addItem(group,group)
        self.group_filter.setCurrentIndex(max(0,self.group_filter.findData(selected_group)))
        self.group_filter.blockSignals(False)
        self.group_filter.setVisible(len(groups)>1)
        self.heading.setText(f'Missing inputs · {self.list.count()} issue(s)')
        self.first_button.setEnabled(bool(self.list.count()))
        self.setVisible(bool(self.list.count()))
        self._filter_issues()

    @staticmethod
    def _group(row):
        return ' / '.join(str(row.get(k,'')) for k in ('section','object_id') if row.get(k)) or str(row.get('workspace',''))

    def _filter_issues(self, *_):
        if not hasattr(self,'list'):return
        selected = self.group_filter.currentData()
        for index in range(self.list.count()):
            item=self.list.item(index)
            item.setHidden(bool(selected and self._group(item.data(Qt.ItemDataRole.UserRole))!=selected))
        first=next((self.list.item(i) for i in range(self.list.count()) if not self.list.item(i).isHidden()),None)
        self.first_button.setEnabled(first is not None)
        if self.list.currentItem() is not None and self.list.currentItem().isHidden():
            self.list.setCurrentItem(first)

    def _activate(self, item):
        if item is not None:
            self.list.setCurrentItem(item)
            self.activated.emit(dict(item.data(Qt.ItemDataRole.UserRole)))

    def go_to_first(self):
        self._activate(next((self.list.item(i) for i in range(self.list.count()) if not self.list.item(i).isHidden()),None))

    def eventFilter(self, watched, event):
        if watched is self.list and event.type() == QEvent.Type.KeyPress and event.key() in (
                Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if self.list.currentItem() is not None and not self.list.currentItem().isHidden():
                self._activate(self.list.currentItem())
            else:self.go_to_first()
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
