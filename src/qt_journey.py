"""Accessible journey navigation over real application widgets.

Navigation has no model or solver side effects. Existing editors keep their
identity, signals and draft values when a different stage is shown.
"""
from PyQt6.QtCore import Qt, QSize, QSignalBlocker, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from qt_common import COLORS, theme_manager
from qt_reference_style import reference_icon


def stage_icon(title):
    name = title.lower()
    if 'result' in name: return 'spectrum'
    if name.startswith(('run', 'calculate')): return 'play'
    if 'check' in name or 'review' in name: return 'check'
    if any(word in name for word in ('crystal', 'structure', 'device', 'cell', 'domain')): return 'cube'
    if any(word in name for word in ('wavevector', 'pulse', 'sampling', 'spectrum')): return 'spectrum'
    return 'settings'


class JourneyBar(QWidget):
    stageRequested = pyqtSignal(int)
    navigationChanged = pyqtSignal()

    def __init__(self, stages=(), parent=None):
        super().__init__(parent)
        self.setObjectName('journeyNavigation')
        self._current = -1
        self._external_navigation = False
        self.stages = []
        self.buttons = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(7)
        self.strip = QScrollArea(self)
        self.strip.setFrameShape(QFrame.Shape.NoFrame)
        self.strip.setWidgetResizable(True)
        self.strip.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.strip.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.strip.setFixedHeight(52)
        body = QWidget(self.strip)
        self.navigation = QHBoxLayout(body)
        self.navigation.setContentsMargins(0, 0, 0, 0)
        self.navigation.setSpacing(5)
        self.strip.setWidget(body)
        root.addWidget(self.strip)
        row = QHBoxLayout()
        self.back_button = QPushButton('Back', self)
        self.back_button.setMaximumWidth(128)
        self.back_button.setAccessibleName('Previous setup step')
        self.back_button.clicked.connect(lambda: self._request(self._current - 1))
        row.addWidget(self.back_button)
        self.selector = QComboBox(self)
        self.selector.setAccessibleName('Simulation journey step')
        self.selector.setMinimumWidth(0)
        self.selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.selector.setMinimumContentsLength(14)
        self.selector.activated.connect(self._request)
        row.addWidget(self.selector, 1)
        self.position = QLabel(self)
        self.position.setObjectName('journeyPosition')
        self.position.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.position, 1)
        self.next_button = QPushButton('Continue', self)
        self.next_button.setMaximumWidth(128)
        self.next_button.setAccessibleName('Next setup step')
        self.next_button.clicked.connect(lambda: self._request(self._current + 1))
        row.addWidget(self.next_button)
        root.addLayout(row)
        self.description = QLabel(self)
        self.description.setObjectName('journeyDescription')
        self.description.setWordWrap(True)
        root.addWidget(self.description)
        theme_manager().changed.connect(self.apply_theme)
        self.set_stages(stages)

    def _request(self, index):
        if 0 <= index < len(self.stages):
            self.stageRequested.emit(index)

    def set_stages(self, stages):
        normalized = [dict(s) if isinstance(s, dict) else {'title': str(s)} for s in stages]
        if normalized == self.stages:
            return
        self.stages = normalized
        while self.navigation.count():
            item = self.navigation.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.buttons = []
        with QSignalBlocker(self.selector):
            self.selector.clear()
            for index, stage in enumerate(self.stages):
                title = stage['title']
                button = QPushButton(f'{index + 1}  {title}'.replace('&', '&&'), self.strip.widget())
                button.setObjectName('journeyStep')
                button.setCheckable(True)
                button.setMinimumHeight(34)
                button.setAccessibleName(f'Step {index + 1}: {title}')
                button.clicked.connect(lambda checked=False, i=index: self._request(i))
                self.navigation.addWidget(button)
                self.buttons.append(button)
                self.selector.addItem(title, index)
        self.navigation.addStretch()
        # Publish a single coherent update, including a clamped selection.
        with QSignalBlocker(self):
            self.set_current(min(max(self._current, 0), len(self.stages) - 1))
        self.apply_theme()
        self.navigationChanged.emit()

    def set_current(self, index):
        previous = self._current
        self._current = index if 0 <= index < len(self.stages) else -1
        for i, button in enumerate(self.buttons):
            button.setChecked(i == self._current)
        with QSignalBlocker(self.selector):
            self.selector.setCurrentIndex(self._current)
        self.back_button.setEnabled(self._current > 0)
        self.next_button.setEnabled(0 <= self._current < len(self.stages) - 1)
        self.position.setText(f'Step {self._current + 1} of {len(self.stages)}' if self._current >= 0 else '')
        description = self.stages[self._current].get('description', '') if self._current >= 0 else ''
        self.description.setText(description)
        self.description.setVisible(bool(description) and not self._external_navigation)
        if self._current >= 0:
            self.strip.ensureWidgetVisible(self.buttons[self._current], 16, 0)
        if previous != self._current:
            self.navigationChanged.emit()

    def set_external_navigation(self, enabled):
        """Let the application shell present this bar's state and requests."""
        self._external_navigation = bool(enabled)
        self._update_navigation_visibility()
        self.setVisible(not self._external_navigation)

    def _update_navigation_visibility(self):
        standalone = not self._external_navigation
        compact = self.width() < 1050
        self.strip.setVisible(standalone and not compact)
        self.selector.setVisible(standalone and compact)
        self.position.setVisible(standalone and not compact)
        self.back_button.setVisible(standalone)
        self.next_button.setVisible(standalone)
        self.description.setVisible(standalone and bool(self.description.text()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_navigation_visibility()

    def apply_theme(self, *_):
        c = COLORS[theme_manager().mode]
        for button, stage in zip(self.buttons, self.stages):
            button.setIcon(reference_icon(stage.get('icon') or stage_icon(stage['title']), c['accent']))
            button.setIconSize(QSize(18, 18))
        self.back_button.setIcon(reference_icon('back', c['muted']))
        self.next_button.setIcon(reference_icon('next', c['accent']))
        self.setStyleSheet('''
            QWidget#journeyNavigation { background: transparent; }
            QWidget#journeyNavigation QScrollArea { border: 0; background: transparent; }
            QPushButton#journeyStep { border: 0; border-bottom: 2px solid %(border)s;
                border-radius: 0; padding: 6px 10px; color: %(muted)s; background: transparent; }
            QPushButton#journeyStep:checked { color: %(accent)s; border-color: %(accent)s;
                background: %(select)s; font-weight: 600; }
            QLabel#journeyDescription, QLabel#journeyPosition { color: %(muted)s; }
        ''' % c)


class _StageStack(QStackedWidget):
    def minimumSizeHint(self):
        return QSize(0, 0)


class StageHost(QWidget):
    stageChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('simulationJourney')
        self.stages = []
        self.keys = {}
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)
        self.bar = JourneyBar(parent=self)
        root.addWidget(self.bar)
        self.stack = _StageStack(self)
        self.stack.setMinimumWidth(0)
        root.addWidget(self.stack, 1)
        self.bar.stageRequested.connect(self.select_stage)
        self.stack.currentChanged.connect(self._changed)

    def add_stage(self, title, widget, description='', icon=None, key=None):
        index = len(self.stages)
        self.stages.append(dict(title=title, description=description, icon=icon))
        self.keys[key or title] = index
        widget.setMinimumWidth(0)
        widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.stack.addWidget(widget)
        self.bar.set_stages(self.stages)
        self.bar.set_current(self.stack.currentIndex())
        return index

    def select_stage(self, index):
        if isinstance(index, str):
            index = self.keys.get(index, -1)
        if 0 <= index < self.stack.count():
            self.stack.setCurrentIndex(index)
            self.bar.set_current(index)

    def _changed(self, index):
        self.bar.set_current(index)
        self.stageChanged.emit(index)

    def reveal(self, widget):
        from qt_input_diagnostics import reveal_and_focus
        return reveal_and_focus(widget)

    def show_results(self):
        index = next((i for i, s in enumerate(self.stages) if 'result' in s['title'].lower()), self.stack.count() - 1)
        self.select_stage(index)
