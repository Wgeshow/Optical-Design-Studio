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
        from qt_journey import JourneyBar
        from qt_research_journey import ensure_execution_panels
        ensure_execution_panels(workspace)
        self.stages = []
        self._last_sections = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        self.bar = JourneyBar(parent=self)
        self.bar.stageRequested.connect(self.show_stage)
        self.navigation = self.bar.navigation
        self.buttons = self.bar.buttons
        layout.addWidget(self.bar)
        self.results_button = QPushButton('Results', self)
        self.results_button.clicked.connect(self.show_results)
        self.results_button.hide()
        self.more = QToolButton(self)
        self.more.setText('All sections')
        self.more.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.more.setAccessibleName('All sections for this simulation')
        self.more.setMinimumHeight(32)
        self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu = QMenu(self.more)
        self.more.setMenu(self.menu)
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
        row.addWidget(self.more)
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
        self.set_stages(stages)
        self.refresh()
        self.apply_theme()

    def set_stages(self, stages):
        resolved = []
        used = set()
        for title, sections in stages:
            indices = []
            for section in sections:
                index = section if isinstance(section, int) else self.workspace.sections.get(section)
                if index is None:
                    index = next((i for i in range(self.workspace.tabs.count())
                        if self.workspace.tabs.tabText(i) == section), None)
                if index is not None and 0 <= index < self.workspace.tabs.count() and index not in used:
                    indices.append(index)
                    used.add(index)
            if indices:
                resolved.append((title, indices))
        reserved = {self.workspace.sections['__journey_check'], self.workspace.sections['__journey_run']}
        result = self.workspace.tabs.indexOf(getattr(self.workspace, 'results', None))
        reserved.add(result)
        allowed = getattr(self.workspace, 'journey_allowed_sections', lambda: None)()
        for index in range(self.workspace.tabs.count()):
            if index in used or index in reserved or not self.workspace.tabs.isTabVisible(index):
                continue
            if allowed is not None and index not in allowed:
                continue
            owner = self._section_owner(index, resolved)
            if owner is None:
                # Keep an otherwise unmatched section explicitly reachable rather
                # than leaving the shell without a selected destination.
                resolved.append((self.workspace.tabs.tabText(index), [index]))
            else:
                resolved[owner][1].append(index)
            used.add(index)
        for title, key in (('Check inputs', '__journey_check'), ('Run & progress', '__journey_run')):
            index = self.workspace.sections[key]
            if index not in used:
                resolved.append((title, [index]))
        result = self.workspace.tabs.indexOf(getattr(self.workspace, 'results', None))
        if result >= 0 and result not in used:
            resolved.append(('Results', [result]))
        self.stages = resolved
        self._last_sections = {i: self._last_sections.get(i, values[0]) if self._last_sections.get(i) in values else values[0]
            for i, (_, values) in enumerate(self.stages)}
        self.refresh()

    def _section_owner(self, index, stages):
        """Attach alternate views to the stage containing their real editor."""
        w = self.workspace
        keys = [key for key, value in w.sections.items() if value == index]
        advanced_root = next((key[len('advanced_'):] for key in keys if key.startswith('advanced_')), None)
        if advanced_root:
            # Friendly inspectors and the full typed editor share one model.
            # Their actual widget ancestry is authoritative after model-specific
            # controls have been moved into their appropriate stage.
            for collection in ('friendly_hosts', 'friendly_forms', 'fields'):
                widget = getattr(w, collection, {}).get(advanced_root)
                if widget is None:
                    continue
                for owner, (_, indices) in enumerate(stages):
                    if any(w.tabs.widget(section).isAncestorOf(widget) for section in indices):
                        return owner
        if any(key.lower() in ('geometry', 'overview') for key in keys):
            for key in ('design', 'device_editor', 'device_context'):
                target = w.sections.get(key)
                owner = next((i for i, (_, indices) in enumerate(stages) if target in indices), None)
                if owner is not None:
                    return owner
            return 0 if stages else None
        return None

    def show_stage(self, index):
        if 0 <= index < len(self.stages):
            self.workspace.tabs.setCurrentIndex(self._last_sections.get(index, self.stages[index][1][0]))
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
        icons = {'Check inputs':'check', 'Run & progress':'play', 'Results':'spectrum'}
        describe = getattr(self.workspace, 'journey_stage_description', lambda title, sections: '')
        self.bar.set_stages([dict(title=title, icon=icons.get(title, 'cube' if i==0 else 'settings'),
            description=('Review the current inputs and jump directly to anything that needs attention.' if title=='Check inputs'
                else 'Start or stop this workspace’s job and inspect its actual progress.' if title=='Run & progress'
                else 'Inspect saved outputs, model limits and provenance.' if title=='Results'
                else describe(title, sections) or 'Edit '+', '.join(self.workspace.tabs.tabText(j) for j in sections)+'.'))
            for i, (title, sections) in enumerate(self.stages)])
        self.buttons = self.bar.buttons
        self.bar.set_current(selected if selected is not None else -1)
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
            allowed = getattr(self.workspace, 'journey_allowed_sections', lambda: None)()
            for index in range(self.workspace.tabs.count()):
                if not self.workspace.tabs.isTabVisible(index) or (allowed is not None and index not in allowed):
                    continue
                action = self.menu.addAction(self.workspace.tabs.tabText(index))
                action.setCheckable(True)
                action.setChecked(index == current)
                action.triggered.connect(lambda checked=False, value=index: self.workspace.tabs.setCurrentIndex(value))
            if self.details:
                self.menu.addSeparator()
                self.menu.addAction('About this model', self.show_details)
            self.results_button.hide()
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
            title=self.stages[index][0].lower()
            icon='check' if 'check' in title else 'play' if 'run' in title else 'spectrum' if 'result' in title else 'cube' if index==0 else 'settings'
            action.setIcon(reference_icon(icon, colors['accent']))
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
