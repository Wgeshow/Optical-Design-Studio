"""Opt-in guided navigation for editable research studies.

The original tabs remain the source of section identity, saved drafts and
diagnostic destinations. This presentation does not change a solver request.
"""
from PyQt6.QtCore import QEvent, QTimer, QSize, Qt
from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QTextBrowser,
    QToolButton, QVBoxLayout, QWidget)

from qt_common import COLORS, theme_manager


class StudyFlow(QWidget):
    def __init__(self, workspace, stages, subtitle='', details=''):
        super().__init__(workspace)
        self.workspace = workspace
        self.details = details
        self._updating = False
        self._last_theme = None
        self.stages = []
        for title, sections in stages:
            indices = []
            for section in sections:
                index = section if isinstance(section, int) else workspace.sections.get(section)
                if index is None:
                    index = next((i for i in range(workspace.tabs.count())
                                  if workspace.tabs.tabText(i) == section), None)
                if index is not None and 0 <= index < workspace.tabs.count() and index not in indices:
                    indices.append(index)
            if indices:
                self.stages.append((title, indices))
        self._last_sections = {i: values[1][0] for i, values in enumerate(self.stages)}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        self.navigation = QHBoxLayout()
        self.buttons = []
        for index, (title, _) in enumerate(self.stages):
            button = QPushButton(str(index + 1)+'  '+title.replace('&', '&&'))
            button.setCheckable(True)
            button.setMinimumHeight(34)
            button.setObjectName('studyStage')
            button.setAccessibleName('Step '+str(index+1)+': '+title)
            button.clicked.connect(lambda checked=False, value=index: self.show_stage(value))
            self.navigation.addWidget(button)
            self.buttons.append(button)
        self.navigation.addStretch()
        self.results_button = QPushButton('Results')
        self.results_button.setMinimumHeight(34)
        self.results_button.clicked.connect(self.show_results)
        self.navigation.addWidget(self.results_button)
        self.more = QToolButton()
        self.more.setText('More')
        self.more.setMinimumHeight(34)
        self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu = QMenu(self.more)
        self.more.setMenu(self.menu)
        self.navigation.addWidget(self.more)
        layout.addLayout(self.navigation)
        row = QHBoxLayout()
        self.section_label = QLabel('Section')
        row.addWidget(self.section_label)
        self.sections = QComboBox()
        self.sections.setAccessibleName('Current study section')
        self.sections.setMinimumContentsLength(12)
        self.sections.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.sections.setMaximumWidth(330)
        self.sections.currentIndexChanged.connect(self._section_selected)
        row.addWidget(self.sections, 1)
        self.section_hint = QLabel()
        self.section_hint.setWordWrap(True)
        self.section_hint.setObjectName('studyMuted')
        row.addWidget(self.section_hint, 2)
        layout.addLayout(row)
        workspace.tabs.tabBar().hide()
        workspace.setProperty('guidedStudyWorkspace', True)
        workspace.setObjectName('guidedStudyWorkspace')
        workspace.body_layout.insertWidget(workspace.body_layout.indexOf(workspace.tabs), self)
        if subtitle:
            workspace.description.setText(subtitle)
        workspace.description.setToolTip(details)
        workspace.tabs.currentChanged.connect(self.refresh)
        workspace.installEventFilter(self)
        if hasattr(workspace, 'results'):
            workspace.results.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            install_results_navigation(workspace.results)
        theme_manager().appearance_changed.connect(self.apply_theme)
        theme_manager().changed.connect(self.apply_theme)
        self.refresh()
        self.apply_theme()

    def show_stage(self, index):
        if 0 <= index < len(self.stages):
            self.workspace.tabs.setCurrentIndex(self._last_sections[index])
            self.refresh()

    def show_results(self):
        index = self.workspace.tabs.indexOf(getattr(self.workspace, 'results', None))
        if index >= 0:
            self.workspace.tabs.setCurrentIndex(index)

    def _section_selected(self, index):
        if not self._updating and index >= 0:
            self.workspace.tabs.setCurrentIndex(self.sections.itemData(index))

    def refresh(self, *args):
        current = self.workspace.tabs.currentIndex()
        selected = next((i for i, (_, sections) in enumerate(self.stages) if current in sections), None)
        self._updating = True
        try:
            self.sections.clear()
            for i, button in enumerate(self.buttons):
                button.setChecked(i == selected)
            if selected is not None:
                self._last_sections[selected] = current
                indices = self.stages[selected][1]
            else:
                indices = [current]
            for index in indices:
                self.sections.addItem(self.workspace.tabs.tabText(index), index)
            self.sections.setCurrentIndex(max(0, self.sections.findData(current)))
            self.section_label.setVisible(len(indices) > 1)
            self.sections.setVisible(len(indices) > 1)
            self.section_hint.setText(self.workspace.tabs.tabText(current))
            self.section_hint.setVisible(len(indices) == 1)
            self.menu.clear()
            for index in range(self.workspace.tabs.count()):
                action = self.menu.addAction(self.workspace.tabs.tabText(index))
                action.setCheckable(True)
                action.setChecked(index == current)
                action.triggered.connect(lambda checked=False, value=index: self.workspace.tabs.setCurrentIndex(value))
            if self.details:
                self.menu.addSeparator()
                self.menu.addAction('About this model', self.show_details)
            self.results_button.setVisible(hasattr(self.workspace, 'results'))
        finally:
            self._updating = False
        self.adapt_layout()

    def show_details(self):
        dialog = QDialog(self.workspace)
        dialog.setWindowTitle('About this model')
        dialog.resize(640, 420)
        layout = QVBoxLayout(dialog)
        text = QTextBrowser()
        text.setPlainText(self.details)
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def adapt_layout(self):
        compact = self.workspace.width() < 1000
        self.workspace.body_layout.setContentsMargins(12 if compact else 16, 8, 12 if compact else 16, 10)
        for form in self.workspace.findChildren(QFormLayout):
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows if compact or form.property('studyAlwaysStacked') else QFormLayout.RowWrapPolicy.WrapLongRows)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setVerticalSpacing(8)
            form.setHorizontalSpacing(14)
        self.navigation.setSpacing(5 if compact else 8)

    def eventFilter(self, watched, event):
        if watched is self.workspace and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self.adapt_layout)
        return super().eventFilter(watched, event)

    def apply_theme(self):
        colors = COLORS[theme_manager().mode]
        from qt_reference_style import reference_icon
        for index, action in enumerate(self.buttons):
            action.setIcon(reference_icon(('cube','settings','play')[min(index,2)], colors['accent']))
        self.results_button.setIcon(reference_icon('spectrum', colors['accent']))
        self.more.setIcon(reference_icon('more', colors['muted']))
        for action in self.workspace.findChildren(QPushButton):
            name=action.text().lower()
            icon=('plus' if name.startswith(('add ','create ')) else 'delete' if name.startswith(('remove ','delete '))
                  else 'check' if name.startswith(('check ','validate')) else 'play' if name.startswith('run ')
                  else 'layers' if name.startswith('edit geometry') else 'materials' if name.startswith('edit electrical')
                  else 'save' if name.startswith('save ') else 'export' if name.startswith('export ') else '')
            if icon:
                action.setIcon(reference_icon(icon, colors['accent']));action.setIconSize(QSize(18,18))
        signature = tuple(colors.items())
        if signature == self._last_theme:
            return
        self._last_theme = signature
        self.workspace.setStyleSheet('''
            QWidget#guidedStudyWorkspace { background: %(bg)s; color: %(text)s; }
            QWidget#guidedStudyWorkspace QTabWidget::pane { border: 0; }
            QWidget#guidedStudyWorkspace QScrollArea { border: 0; background: %(panel)s; }
            QWidget#guidedStudyWorkspace QWidget#studyFieldPanel,
            QWidget#guidedStudyWorkspace QWidget#studyInspector { background: %(panel)s; }
            QWidget#guidedStudyWorkspace QLabel#setupTitle,
            QWidget#guidedStudyWorkspace QLabel#studyPageTitle { font-size: 23px; font-weight: 600; }
            QWidget#guidedStudyWorkspace QLabel#setupMuted,
            QWidget#guidedStudyWorkspace QLabel#studyMuted { color: %(muted)s; }
            QWidget#guidedStudyWorkspace QPushButton#studyStage { border: 0; background: transparent; color: %(muted)s; padding: 6px 12px; }
            QWidget#guidedStudyWorkspace QPushButton#studyStage:checked { background: %(select)s; color: %(accent)s; border-radius: 5px; }
            QWidget#guidedStudyWorkspace QLineEdit,
            QWidget#guidedStudyWorkspace QComboBox { min-height: 27px; padding: 3px 7px; border: 1px solid %(border)s; border-radius: 5px; background: %(field)s; color: %(text)s; }
            QWidget#guidedStudyWorkspace QListWidget,
            QWidget#guidedStudyWorkspace QTreeWidget { border: 1px solid %(border)s; background: %(panel)s; }
        ''' % colors)


def install_study_flow(workspace, stages, subtitle='', details=''):
    flow = StudyFlow(workspace, stages, subtitle, details)
    workspace.study_flow = flow
    return flow


def install_results_navigation(panel):
    """A single view selector keeps every result surface reachable at small sizes."""
    if hasattr(panel, 'view_selector') or not hasattr(panel, 'tabs'):
        return
    selector = QComboBox()
    selector.setAccessibleName('Result view')
    selector.setMaximumWidth(360)
    for index in range(panel.tabs.count()):
        selector.addItem(panel.tabs.tabText(index), index)
    selector.setCurrentIndex(panel.tabs.currentIndex())
    selector.currentIndexChanged.connect(panel.tabs.setCurrentIndex)
    panel.tabs.currentChanged.connect(selector.setCurrentIndex)
    panel.tabs.tabBar().hide()
    panel.layout().insertWidget(panel.layout().indexOf(panel.tabs), selector)
    panel.view_selector = selector
