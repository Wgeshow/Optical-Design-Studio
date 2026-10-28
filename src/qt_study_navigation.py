"""One shell workflow, mirrored from each simulation's existing journey.

The controller owns navigation presentation only. Page-owned JourneyBars remain
sources of truth, so no controls, drafts, validation or solver wiring are copied.
"""
from PyQt6.QtCore import QObject, QSize, QSignalBlocker, Qt, QEvent, QTimer
from PyQt6.QtWidgets import QComboBox, QLabel, QPushButton, QSizePolicy

from qt_common import COLORS, theme_manager
from qt_journey import stage_icon
from qt_reference_style import reference_icon


class StudyNavigation(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.source = None
        self.page = None
        self.owner = None
        self._bound = set()
        self._syncing = False
        self._requesting = False
        self._mouse_navigation = False
        self._signature = None
        self._utility = False
        self._last_route = None
        self._return_route = None
        self._last_engine = None
        self._return_engine = None
        self.parameter_editor = None
        self.parameter_return = QPushButton('Return to simulation stage')
        self.parameter_return.setObjectName('returnFromOpticalParameters')
        self.parameter_return.clicked.connect(self.return_from_parameters)
        self.parameter_return.hide()
        window.navigation_layout.insertWidget(2,self.parameter_return)
        self.current = -1
        self.tabs = window.optical_workflow
        self.tabs.setMaximumWidth(16777215)
        self.tabs.setMinimumWidth(0)
        self.tabs.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.tabs.setUsesScrollButtons(False)
        self.tabs.setElideMode(Qt.TextElideMode.ElideNone)
        window.navigation_layout.removeWidget(self.tabs)
        window.chrome.layout().removeWidget(self.tabs)
        row = window.workflow_navigation_layout
        row.setSpacing(8)
        self.previous = QPushButton('Previous')
        self.previous.setAccessibleName('Previous simulation stage')
        self.previous.clicked.connect(lambda: self.request(self.current - 1))
        row.addWidget(self.previous)
        row.addWidget(self.tabs, 1)
        self.selector = QComboBox()
        self.selector.setObjectName('simulationStageSelector')
        self.selector.setAccessibleName('Simulation stage')
        self.selector.setMinimumWidth(0)
        self.selector.setMinimumContentsLength(12)
        self.selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.selector.activated.connect(self.request)
        row.addWidget(self.selector, 1)
        self.utility_label = QLabel()
        row.addWidget(self.utility_label, 1)
        self.return_button = QPushButton()
        self.return_button.setObjectName('returnToSimulation')
        self.return_button.clicked.connect(self.return_to_study)
        row.addWidget(self.return_button)
        self.next = QPushButton('Continue')
        self.next.setAccessibleName('Next simulation stage')
        self.next.clicked.connect(lambda: self.request(self.current + 1))
        row.addWidget(self.next)
        # A click on the selected stage must also leave its full editor subview.
        self.tabs.installEventFilter(self)
        self.tabs.tabBarClicked.connect(self._clicked)
        window.navigation_layout.removeWidget(window.chrome.file_button)
        window.chrome.layout().removeWidget(window.chrome.file_button)
        window.chrome.layout().insertWidget(4, window.chrome.file_button)
        window.chrome.file_button.setText('&Menu')
        window.workflow_navigation.setFixedHeight(48)

    @staticmethod
    def source_for(page):
        """Explicit adapters for every implemented simulation journey."""
        for owner_name, bar_name in (('setup_flow', 'journey_bar'),
                                     ('optical_journey', 'bar'),
                                     ('study_flow', 'bar'),
                                     ('journey_host', 'bar')):
            owner = getattr(page, owner_name, None)
            bar = getattr(owner, bar_name, None)
            if bar is not None:
                return bar
        for name in ('journey_bar', 'laser_journey', 'paper_journey'):
            bar = getattr(page, name, None)
            if bar is not None:
                return bar
        return None

    def _is_papers(self):
        w = self.window
        return (w.navigation.currentRow() == 11 and
                w.research_studies_page.stack.currentWidget() is w.research_studies_page.library_page)

    def eventFilter(self, watched, event):
        if watched is self.tabs and event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            # QTabBar emits both currentChanged and tabBarClicked for a new
            # pointer selection. Dispatch the click once; keyboard selection
            # continues to use currentChanged. The selected tab also reopens
            # its canonical stage from any local editor/overview subview.
            self._mouse_navigation = True
            QTimer.singleShot(0, self._end_pointer_navigation)
        return super().eventFilter(watched, event)

    def _end_pointer_navigation(self):
        self._mouse_navigation = False

    def _clicked(self, index):
        self.request(index)

    def _source_changed(self, source):
        if source is self.source and not self._requesting:
            self.sync(self.window.navigation.currentRow())

    def _bind(self, source):
        source.set_external_navigation(True)
        if source not in self._bound:
            self._bound.add(source)
            source.navigationChanged.connect(lambda s=source: self._source_changed(s))

    def editor_stage(self, route):
        stages = self.source.stages if self.source is not None else []
        words = ('material',) if route == 1 else ('device', 'structure', 'crystal', 'cell', 'domain', 'design', 'stack')
        return next((i for i, stage in enumerate(stages)
                     if any(word in stage['title'].lower() for word in words)), 0 if stages else -1)

    def sync(self, route):
        w = self.window
        if self._syncing or not getattr(w, '_construction_complete', False):
            return
        self._syncing = True
        try:
            utility = route in (5, 6, 7) or (route == 2 and w.simulation_engines.currentIndex() == 4)
            if self._is_papers():
                owner, page = 'papers', w.research_studies_page.library_page
            elif utility and self.owner == 'papers':
                owner, page = self.owner, self.page
            elif (utility or route in (0, 1, 9)) and self.owner == w.store.active_study:
                owner, page = self.owner, self.page
            else:
                owner, page = w.store.active_study, w._active_setup_page()
            source = self.source_for(page)
            self.owner, self.page, self.source = owner, page, source
            if utility and not self._utility:
                self._return_route = self._last_route
                self._return_engine = self._last_engine
            if not utility:
                self._last_route = route
                self._last_engine = w.simulation_engines.currentIndex() if route==2 else None
            self._utility = utility
            stages = source.stages if source is not None else []
            if source is not None:
                self._bind(source)
            signature = tuple((stage['title'], stage.get('icon'), stage.get('description', '')) for stage in stages)
            if signature != self._signature:
                with QSignalBlocker(self.tabs), QSignalBlocker(self.selector):
                    while self.tabs.count():
                        self.tabs.removeTab(0)
                    self.selector.clear()
                    for i, stage in enumerate(stages):
                        title = stage['title']
                        self.tabs.addTab(title.replace('&', '&&'))
                        self.tabs.setTabToolTip(i, stage.get('description') or title)
                        self.selector.addItem(f'{i + 1}. {title}', i)
                self._signature = signature
            w.optical_routes = list(range(len(stages)))
            current = source._current if source is not None else -1
            if route in (0, 1):
                current = self.editor_stage(route)
            elif route == 9:
                current = next((i for i, s in enumerate(stages) if 'result' in s['title'].lower()), current)
            editor=getattr(w,'_optical_parameter_pages',{}).get(owner)
            self.parameter_editor=editor if route==2 and editor is not None and w.simulation_engines.currentWidget() is editor else None
            if self.parameter_editor is not None:
                section=editor.current_section.split('.')[-1]
                key=('sampling' if section not in ('overview','domain','materials') else 'structure') if owner=='tools.index_shift' else ('parameters' if section in ('sweep','outputs') else 'structure') if owner=='tools.fields' else 'structure'
                current=page.optical_journey.keys[key]
            self.current = -1 if utility else current
            self.parameter_return.setVisible(self.parameter_editor is not None)
            with QSignalBlocker(self.tabs), QSignalBlocker(self.selector):
                self.tabs.setCurrentIndex(self.current)
                self.selector.setCurrentIndex(self.current)
            c = COLORS[theme_manager().mode]
            for i, stage in enumerate(stages):
                icon = reference_icon(stage.get('icon') or stage_icon(stage['title']), c['accent'])
                self.tabs.setTabIcon(i, icon)
                self.selector.setItemIcon(i, icon)
            self.tabs.setIconSize(QSize(18, 18))
            self.previous.setIcon(reference_icon('back', c['muted']))
            self.next.setIcon(reference_icon('next', c['accent']))
            self.return_button.setIcon(reference_icon('back', c['accent']))
            title = 'Paper comparisons' if owner == 'papers' else w._study_title()
            self.return_button.setText('Return to ' + title)
            self.utility_label.setText({5: 'Saved work', 6: 'Application settings', 7: 'Help'}.get(route, 'Saved work'))
            self.previous.setEnabled(self.current > 0)
            self.next.setEnabled(0 <= self.current < len(stages) - 1)
            # Account for actual stage labels and scale, not only a fixed breakpoint.
            available = w.width() - self.previous.sizeHint().width() - self.next.sizeHint().width() - 70
            compact = w.width() < 1100 or self.tabs.sizeHint().width() > available
            self.tabs.setVisible(not utility and bool(stages) and not compact)
            self.selector.setVisible(not utility and bool(stages) and compact)
            self.previous.setVisible(not utility and bool(stages))
            self.next.setVisible(not utility and bool(stages))
            self.return_button.setVisible(utility)
            self.utility_label.setVisible(utility)
            w.workflow_navigation.setVisible(bool(stages) or utility)
            w.navigation_bar.show()
            w.project_header.hide()
            w.chrome.title.setText('Optical Design Studio')
            w.workspace_context.setText('')
            w._sync_study_context()
            if owner == 'papers':
                w.active_simulation_label.setText(title)
                w.active_simulation_label.setToolTip('Open a reference as an editable simulation.')
                w.transfer_inputs_button.setEnabled(False)
                w.setWindowTitle('Optical Design Studio · ' + title)
        finally:
            self._syncing = False

    def _open_owner(self):
        if self.owner == 'papers':
            self.window._open_simulation_choice('papers')
        else:
            self.window._open_active_setup()

    def return_to_study(self):
        source = self.source
        selected = source._current if source is not None else -1
        if self.owner != 'papers' and self._return_route in (0, 1, 9):
            self.window._navigate_route(self._return_route)
        elif self._return_route==2 and self._return_engine is not None and self._return_engine>=8:
            self.window._navigate_route(2,self._return_engine)
        else:
            self._open_owner()
        # Opening the owner can restore its last section. Retain the exact
        # journey stage from before Settings/Help, including Check/Run/Results.
        if source is self.source and selected >= 0 and source._current != selected:
            source.stageRequested.emit(selected)
        self.sync(self.window.navigation.currentRow())

    def return_from_parameters(self):
        self.request(self.current)

    def request(self, index):
        if self._syncing or self._requesting or self.source is None:
            return
        if not 0 <= index < len(self.source.stages):
            return
        self._requesting = True
        try:
            source = self.source
            w = self.window
            owner_route,owner_engine = (11,None) if self.owner == 'papers' else w._study_location()
            engine_mismatch=owner_route==2 and w.simulation_engines.currentIndex()!=owner_engine
            if w.navigation.currentRow() != owner_route or engine_mismatch or self._utility:
                self._open_owner()
            source.stageRequested.emit(index)
        finally:
            self._requesting = False
        self.sync(self.window.navigation.currentRow())

    def show_results(self):
        if self.source is None:
            return False
        index = next((i for i, stage in enumerate(self.source.stages)
                      if 'result' in stage['title'].lower()), None)
        if index is None:
            return False
        self.request(index)
        return True
