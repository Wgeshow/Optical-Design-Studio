"""Launch the native PyQt6 Optical Studio desktop."""
import argparse
import copy
import os
from pathlib import Path
import sys

from desktop_runtime import initialize_desktop, resource_root, set_windows_app_id
# app.py creates its shared library during import; choose a writable location
# first, including an explicit --library supplied to the installed executable.
initialize_desktop()

from bootstrap import initialize
initialize(1)
import matplotlib
matplotlib.use('Agg')

from PyQt6.QtCore import Qt, QSettings, QTimer, QSignalBlocker, QSize
from PyQt6.QtGui import QIcon, QKeySequence, QPixmap, QPainter, QPen, QColor
from PyQt6.QtWidgets import (QApplication,QMainWindow,QWidget,QHBoxLayout,QVBoxLayout,
    QFrame,QLabel,QListWidget,QListWidgetItem,QStackedWidget,QComboBox,QFileDialog,QMessageBox,QProgressBar,QToolButton,QTabWidget,QPushButton,QTabBar,QScrollArea)

from qt_common import theme_manager,button,note,scroll,preferences,COLORS,LOOKS,completion_notice
from qt_icons import navigation_icon
from qt_surfaces import WorkspaceBackground
from qt_core import ProjectStore,BackendWorker
from data_library import DataLibrary
from qt_chrome import WindowChrome, WindowsCustomFrame
from qt_windows_glass import WindowsDesktopGlass, prepare_window_translucency
from app_version import APP_VERSION


class StructureNotice(QFrame):
    """One brief in-window notification; never changes the page layout or focus."""
    def __init__(self,parent):
        super().__init__(parent)
        self.setObjectName('structureNotice')
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout=QVBoxLayout(self)
        layout.setContentsMargins(14,10,12,12)
        layout.setSpacing(4)
        heading=QHBoxLayout()
        title=QLabel('Shared Structure updated')
        self.title_label=title
        title.setObjectName('noticeTitle')
        heading.addWidget(title,1)
        self.dismiss_button=QToolButton()
        self.dismiss_button.setText('×')
        self.dismiss_button.setAccessibleName('Dismiss structure notification')
        self.dismiss_button.setToolTip('Dismiss')
        self.dismiss_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.dismiss_button.clicked.connect(self.dismiss)
        heading.addWidget(self.dismiss_button)
        layout.addLayout(heading)
        self.summary=QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.summary)
        self.timer=QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(4000)
        self.timer.timeout.connect(self.hide)
        self.hide()

    def dismiss(self):
        self.timer.stop()
        self.hide()


class OpticalStudio(QMainWindow):
    def __init__(self,store=None):
        super().__init__()
        self.store=store or ProjectStore()
        self.preferences=preferences()
        self.project_path=None
        self._saved_project=None if self.store.session_path.exists() else copy.deepcopy(self.store.project())
        self._closing=False
        self._updates_closing=False
        self.setObjectName('opticalStudioWindow')
        self.setWindowTitle('Optical Design Studio')
        icon_path=resource_root()/'S4_Studio.ico'
        if icon_path.is_file():self.setWindowIcon(QIcon(str(icon_path)))
        native_frame = False
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowMinMaxButtonsHint | Qt.WindowType.WindowCloseButtonHint)
        # Alpha support must exist before the custom Windows frame creates the
        # HWND. Solid B looks still paint an opaque workspace over this surface.
        prepare_window_translucency(self)
        self.setMinimumSize(640,480)
        self.resize(1460,960)
        geometry=self.preferences.value('geometry')
        if geometry is not None:self.restoreGeometry(geometry)
        self._defer_saved_window_state()
        # Establish density before constructing the page tree. Restyling every
        # hidden page after construction was the dominant launch-time cost.
        theme_manager().set_window_width(self.width())
        central=WorkspaceBackground(desktop_root=True)
        root=QVBoxLayout(central)
        root.setContentsMargins(8,8,8,8)
        root.setSpacing(0)
        self.chrome=WindowChrome(self,self.open_project,self.save_project,
                                 lambda:self.navigation.setCurrentRow(6), native_frame=native_frame)
        root.addWidget(self.chrome)
        self.project_header=QFrame()
        self.project_header.setObjectName('titleProject')
        project_layout=QHBoxLayout(self.project_header)
        project_layout.setContentsMargins(14,5,14,5)
        project_layout.setSpacing(6)
        project_label=QLabel('│')
        project_label.setObjectName('workspaceLabel')
        project_layout.addWidget(project_label)
        self.project_select=QLabel('Untitled project')
        self.project_select.setObjectName('projectSelector')
        self.project_select.setAccessibleName('Current project')
        self.project_select.setMinimumWidth(100)
        self.project_select.setMaximumWidth(200)
        project_layout.addWidget(self.project_select)
        project_layout.addStretch(1)
        # One persistent menu replaces the former Open-through-Help toolbar.
        self.chrome.file_button.setText('&Menu')
        self.chrome.file_button.setAccessibleName('Project and application menu')
        self.chrome.file_button.setToolTip('Open, save, export, appearance, settings and help')
        self.chrome.view_button.hide()
        self.chrome.layout().insertWidget(6,self.project_header,1)
        menu=self.chrome.file_menu
        for action in list(menu.actions()):
            menu.removeAction(action)
        new_action=menu.addAction('New project', self._start_new_design)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        self.addAction(new_action)
        menu.addAction(self.chrome.open_action)
        menu.addAction(self.chrome.save_action)
        self.save_as_action=menu.addAction('Save project as…', self.save_project_as)
        self.save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.addAction(self.save_as_action)
        menu.addSeparator()
        menu.addAction('Export geometry…', self._open_export_menu)
        menu.addSeparator()
        appearance=menu.addMenu('Appearance')
        for action in self.chrome.theme_actions.values():
            appearance.addAction(action)
        menu.addAction('Settings', lambda:self._navigate_route(6))
        menu.addAction('Help', lambda:self._navigate_route(7))
        menu.addSeparator()
        menu.addAction('Exit', self.close)
        self.theme_buttons={}
        # Retain an empty hidden adapter for older saved-layout integrations;
        # the single optical workspace needs no simulation-suite banner.
        self.workspace_tabs=QFrame(central); self.workspace_tabs.setObjectName('workspaceTabs'); self.workspace_tabs.hide()
        self.workspace_tab_buttons={}
        self._workspace_routes=()
        self.optical_workflow=QTabBar();self.optical_workflow.setObjectName('opticalWorkflowTabs');self.optical_workflow.setExpanding(True)
        self.optical_workflow.setDrawBase(False)
        self.optical_workflow.setUsesScrollButtons(True)
        self.optical_routes=[0,1,2,3,8,6,7]
        for label in ['Structure','Materials','Simulation','Simulation Sweep','AI Search','Settings','Help']:
            self.optical_workflow.addTab(label)
        self.optical_workflow.currentChanged.connect(lambda i:self._navigate_route(self.optical_routes[i]))
        navigation_bar=QFrame();navigation_bar.setObjectName('projectHeader');navigation_bar.setFixedHeight(55)
        navigation_layout=QHBoxLayout(navigation_bar)
        navigation_layout.setContentsMargins(19,4,12,4);navigation_layout.setSpacing(8)
        self.optical_workflow.setMaximumWidth(1040)
        navigation_layout.addWidget(self.optical_workflow,1)
        navigation_layout.addStretch(0)
        self.project_button=QToolButton()
        self.project_button.setObjectName('projectPicker')
        self.project_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.project_button.setText('Untitled project  ⌄')
        self.project_button.setIcon(navigation_icon('Saved work',COLORS[theme_manager().mode]['text']))
        self.project_button.setMinimumSize(200,40)
        self.project_button.setMaximumWidth(240)
        self.project_button.clicked.connect(self.open_project)
        navigation_layout.addWidget(self.project_button)
        navigation_layout.addWidget(QLabel('│'))
        self.project_save_button=QToolButton()
        self.project_save_button.setObjectName('projectSave')
        self.project_save_button.setFixedSize(40,40)
        self.project_save_button.setAccessibleName('Save project')
        self.project_save_button.setToolTip('Save project (Ctrl+S)')
        self.refresh_project_icons(theme_manager().mode)
        self.project_save_button.clicked.connect(self.save_project)
        navigation_layout.addWidget(self.project_save_button)
        self.chrome.layout().removeWidget(self.chrome.file_button)
        self.chrome.file_button.setText('⋮')
        navigation_layout.addWidget(self.chrome.file_button)
        root.addWidget(navigation_bar)
        body=QHBoxLayout()
        body.setContentsMargins(0,0,0,0)
        body.setSpacing(0)
        root.addLayout(body,1)
        sidebar=QFrame(central)
        self.sidebar = sidebar
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(180)
        side=QVBoxLayout(sidebar)
        side.setContentsMargins(18,28,18,20)
        self.sidebar_collapsed = self.preferences.value('sidebar_collapsed', False, type=bool)
        self.sidebar_toggle = QToolButton()
        self.sidebar_toggle.setCheckable(True)
        self.sidebar_toggle.setChecked(self.sidebar_collapsed)
        self.sidebar_toggle.setMinimumSize(36, 32)
        self.sidebar_toggle.clicked.connect(self.toggle_sidebar)
        side.addWidget(self.sidebar_toggle, 0, Qt.AlignmentFlag.AlignRight)
        side.addSpacing(6)
        self.navigation=QListWidget()
        self.navigation.setObjectName('navigation')
        self.navigation.addItems(['Structure','Materials','Simulate','Optimize','Fields','Saved work','Settings','About','AI Search'])
        self.navigation.hide()
        self.tool_navigation=QListWidget()
        self.tool_navigation.setObjectName('navigation')
        self._tool_pages=(
            ('Structure',0,None),('Materials',1,None),
            ('S4 · RCWA',2,0),('MEEP · FDTD',2,1),
            ('Simulation Sweep',3,None),('AI Search',8,None),('Field maps',4,None),
            ('Saved results',5,None),
            ('Settings',6,None),('About',7,None))
        for label,page_index,engine_index in self._tool_pages:
            item=QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole,page_index)
            item.setData(Qt.ItemDataRole.UserRole+1,engine_index)
            self.tool_navigation.addItem(item)
        self.tool_navigation.currentItemChanged.connect(
            lambda current,previous: self._navigate_route(
                current.data(Qt.ItemDataRole.UserRole),
                current.data(Qt.ItemDataRole.UserRole+1)) if current else None)
        side.addWidget(self.tool_navigation,1)
        side.addWidget(note('Appearance'))
        self.theme_select=QComboBox()
        self.theme_select.setObjectName('themeSelector')
        for key,(label,style,mode) in LOOKS.items():self.theme_select.addItem(label,key)
        self.theme_select.setCurrentIndex(self.theme_select.findData(theme_manager().look))
        self.theme_select.currentIndexChanged.connect(lambda:theme_manager().apply_look(self.theme_select.currentData()))
        theme_manager().changed.connect(self.refresh_theme)
        side.addWidget(self.theme_select)
        side.addSpacing(12)
        location=note('Saved locally\nYour data stays with the project library.')
        location.setToolTip(str(self.store.library.root))
        side.addWidget(location)
        self.sidebar_details = [location, self.theme_select] + sidebar.findChildren(QLabel)
        # Hidden route/theme adapters preserve existing programmatic callers.
        # Every visible page, including Settings and Help, uses the top tabs.
        sidebar.hide()
        workspace=WorkspaceBackground()
        self.workspace=workspace
        content=QVBoxLayout(workspace)
        content.setContentsMargins(0,0,0,0)
        content.setSpacing(0)
        self.stack=QStackedWidget()
        from qt_device_builder import DeviceBuilderPage as StructurePage
        from qt_materials import MaterialsPage
        from qt_library import LibraryPage
        from qt_compute import SimulationPage,OptimizePage,FieldsPage,SettingsPage
        from qt_about import AboutPage
        from qt_fdtd import FDTDPage
        from qt_ai_search import AISearchPage
        classes=[StructurePage,MaterialsPage,SimulationPage,OptimizePage,FieldsPage,LibraryPage,SettingsPage,AboutPage,AISearchPage]
        self.pages={}
        for index,cls in enumerate(classes):
            page=cls(self.store)
            if cls is AboutPage:
                from qt_help import add_help_tabs
                add_help_tabs(page)
            page.setObjectName('page')
            for guidance in page.findChildren(QLabel,'muted'):
                guidance.setToolTip(guidance.text());guidance.hide()
            page.layout().setContentsMargins(8,10,8,10)
            self.pages[self.navigation.item(index).text()]=page
            if cls is SimulationPage:
                self.simulation_engines = QTabWidget()
                self.fdtd_page = FDTDPage(self.store)
                self.simulation_engines.addTab(page, 'S4 · RCWA')
                self.simulation_engines.addTab(scroll(self.fdtd_page), 'MEEP · FDTD')
                from qt_index_shift import IndexShiftPage
                self.index_shift_page = IndexShiftPage(self.store)
                self.simulation_engines.addTab(scroll(self.index_shift_page), 'Δn sweep')
                self.simulation_engines.currentChanged.connect(self._simulation_engine_changed)
                self.stack.addWidget(self.simulation_engines)
            elif cls in (FieldsPage,LibraryPage):
                self.simulation_engines.addTab(scroll(page), 'Fields' if cls is FieldsPage else 'Saved results')
                # Preserve route indices for older saved layouts and callers.
                self.stack.addWidget(QWidget())
            else:
                self.stack.addWidget(page if cls in (OptimizePage,AISearchPage) else scroll(page))
        self.pages['About'].idle.connect(self._close_after_updates)
        for nested_page in (self.fdtd_page,self.index_shift_page):
            for guidance in nested_page.findChildren(QLabel,'muted'):
                guidance.setToolTip(guidance.text());guidance.hide()
        self.simulation_local_bars=[]
        self.simulation_engines.tabBar().hide()
        simulation_pages=[self.pages['Simulate'],self.fdtd_page,self.index_shift_page,self.pages['Fields'],self.pages['Saved work']]
        for simulation_page in simulation_pages:
            bar=QTabBar();bar.setExpanding(True);bar.setUsesScrollButtons(True)
            bar.setObjectName('simulationWorkspaceTabs')
            for text in ('S4 · RCWA','MEEP · FDTD','Δn sweep','Fields','Saved results'):bar.addTab(text)
            if simulation_page is self.pages['Simulate']:
                left=simulation_page.workspace_splitter.widget(0).findChild(QScrollArea).widget()
                left.layout().insertWidget(1,bar)
            elif hasattr(simulation_page,'setup_layout'):
                simulation_page.setup_layout.insertWidget(1,bar)
            else:simulation_page.layout().insertWidget(0,bar)
            bar.currentChanged.connect(self.simulation_engines.setCurrentIndex)
            self.simulation_local_bars.append(bar)
        self.simulation_engines.currentChanged.connect(self._sync_simulation_local_bars)
        self._sync_simulation_local_bars(self.simulation_engines.currentIndex())
        self.pages['Structure'].continue_requested.connect(lambda:self._navigate_route(1))
        self.pages['Settings'].addons_panel.idle.connect(self._close_after_updates)
        self.pages['Settings'].addons_panel.restart_requested.connect(self._restart_for_addons)
        self.pages['Settings'].addons_panel.runtime_changed.connect(self.fdtd_page.refresh_runtime)
        content.addWidget(self.stack,1)
        footer=QFrame()
        footer.setObjectName('workspaceFooter')
        footer.setFixedHeight(56)
        footer_layout=QHBoxLayout(footer)
        footer_layout.setContentsMargins(24,8,24,8)
        self.status=note('Ready')
        self.status.setObjectName('globalStatus')
        self.status.setMaximumHeight(36)
        self.progress_bar=QProgressBar()
        self.progress_bar.setMaximumWidth(220)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        self.stop_button=button('Stop',self.store.cancel)
        self.stop_button.setFixedSize(96,36)
        self.run_button=button('▶  Run',self._run_active_workspace,True)
        self.run_button.setFixedSize(160,36)
        for run_page in (self.pages['Simulate'],self.fdtd_page,self.index_shift_page,self.pages['Fields'],self.pages['Optimize']):
            for action in getattr(run_page,'starts',[]):action.hide()
            for action in getattr(run_page,'stops',[]):action.hide()
        self.fdtd_page.start_button.hide();self.fdtd_page.stop_button.hide()
        for action in self.pages['AI Search'].campaign_actions.findChildren(QPushButton):action.hide()
        for action in self.pages['AI Search'].stops:action.hide()
        footer_layout.addWidget(self.status,1)
        self.footer_project=note('Untitled project  ·  Units: µm')
        self.footer_project.setFixedWidth(140)
        self.footer_project.setFixedHeight(36)
        footer_layout.addWidget(self.footer_project)
        footer_layout.addWidget(self.progress_bar)
        footer_layout.addWidget(self.run_button)
        footer_layout.addWidget(self.stop_button)
        content.addWidget(footer)
        body.addWidget(workspace,1)
        self.setCentralWidget(central)
        self._windows_frame = WindowsCustomFrame(self)
        self._desktop_glass = WindowsDesktopGlass(self)
        self._desktop_glass.changed.connect(central.update)
        self._desktop_glass.apply(enabled=theme_manager().style=='glass',mode=theme_manager().mode)
        self.structure_notice=StructureNotice(workspace)
        self._structure_snapshot=self.structure_signature()
        self.navigation.currentRowChanged.connect(self._display_route)
        self.navigation.currentRowChanged.connect(self._sync_workspace_tabs)
        self.navigation.currentRowChanged.connect(self._sync_tool_navigation)
        self.navigation.setCurrentRow(int(self.preferences.value('page',0))%len(classes))
        self.store.changed.connect(self.structure_changed)
        self.store.busy_changed.connect(self.busy_changed)
        self.store.progress.connect(self.show_progress)
        self.store.run_failed.connect(self.show_error)
        self.store.run_finished.connect(self.show_finished)
        self.store.message.connect(self.show_status_message)
        self.store.task_failed.connect(lambda name,error:self.show_error(error))
        self.store.task_finished.connect(lambda name,result:self.notify_action('Completed',name+' completed.'))
        if self.store.restore_error:
            self.status.setText(self.store.restore_error)
        self.appearance_timer = QTimer(self)
        self.appearance_timer.setSingleShot(True)
        self.appearance_timer.setInterval(120)
        self.appearance_timer.timeout.connect(self.adapt_interface)
        theme_manager().appearance_changed.connect(self.adapt_interface)
        self.adapt_interface()
        self.file_state_timer=QTimer(self)
        self.file_state_timer.setInterval(700)
        self.file_state_timer.timeout.connect(self._refresh_project_file)
        self.file_state_timer.start()
        self.store.changed.connect(self._project_store_changed)
        self._refresh_project_file()
        self._sync_run_actions()

    def _run_active_workspace(self):
        route=self.navigation.currentRow()
        if route==2:
            index=self.simulation_engines.currentIndex()
            page=(self.pages['Simulate'],self.fdtd_page,self.index_shift_page,self.pages['Fields'],None)[index]
            if page is not None:page.run()
        elif route==3:
            page=self.pages['Optimize']
            (page.run_target if page.tabs.currentIndex()==0 else page.run_peaks)()
        elif route==8:self.pages['AI Search'].run('search')

    def _sync_run_actions(self):
        if not hasattr(self,'run_button'):return
        route=self.navigation.currentRow()
        runnable=route in (3,8) or (route==2 and self.simulation_engines.currentIndex()!=4)
        self.run_button.setEnabled(runnable and not self.store.busy)
        self.stop_button.setEnabled(self.store.busy and callable(getattr(self.store._worker,'cancel',None)))
        self.run_button.setToolTip('Run the active workspace' if runnable else 'Select a simulation or search workspace')

    def toggle_sidebar(self, checked):
        self.sidebar_collapsed = not self._sidebar_compact
        self._sidebar_manual = True
        self.preferences.setValue('sidebar_collapsed', self.sidebar_collapsed)
        self.preferences.sync()
        self.adapt_interface()

    def _display_route(self,page_index):
        if page_index in (4,5):
            self._navigate_route(page_index)
        else:
            self.stack.setCurrentIndex(page_index)

    def _navigate_route(self,page_index,engine_index=None):
        """Open a real workspace, optionally selecting its simulation engine."""
        if int(page_index) in (4,5):
            engine_index=3 if int(page_index)==4 else 4
            page_index=2
        self.navigation.setCurrentRow(int(page_index))
        if page_index == 2 and engine_index is not None and hasattr(self,'simulation_engines'):
            self.simulation_engines.setCurrentIndex(int(engine_index))
        self._sync_workspace_tabs(int(page_index))
        self._sync_tool_navigation(int(page_index))

    def _start_new_design(self):
        if self.store.busy:
            self.show_error('Wait for the current calculation before starting a new project.')
            return
        if not self._confirm_project_replace():
            return
        try:
            fresh=ProjectStore(self.store.library,restore=False)
            self.store.load_project(fresh.project())
            self.project_path=None
            self._saved_project=copy.deepcopy(self.store.project())
            self._refresh_project_file()
        except Exception as exc:
            self.show_error('Could not create a new project: '+str(exc))
            return
        self._navigate_route(0)
        self.notify_action('New project','Project created.')
        self.status.setText('Ready')

    def _open_export_menu(self):
        """Route the global Export action to the existing structure exporters."""
        self._navigate_route(0)
        export_button=getattr(self.pages.get('Structure'),'export_button',None)
        if export_button is not None and export_button.menu() is not None:
            QTimer.singleShot(0, export_button.showMenu)

    def _simulation_engine_changed(self,engine_index):
        if self.navigation.currentRow() == 2:
            self._sync_tool_navigation(2)
            self._sync_workspace_tabs(2)

    def _sync_simulation_local_bars(self,index):
        for bar in self.simulation_local_bars:
            with QSignalBlocker(bar):bar.setCurrentIndex(index)
        self._sync_run_actions()

    def _sync_workspace_tabs(self, page_index):
        self._sync_run_actions()
        engine_index=self.simulation_engines.currentIndex() if page_index==2 and hasattr(self,'simulation_engines') else None
        for (index,route_engine), tab in self.workspace_tab_buttons.items():
            selected = index == 0
            tab.setChecked(selected)
            tab.setProperty('active', selected)
            tab.style().unpolish(tab)
            tab.style().polish(tab)
        self._sync_sidebar_visibility(page_index)
        self.optical_workflow.setVisible(True)
        visible_route = page_index
        if visible_route in self.optical_routes:
            with QSignalBlocker(self.optical_workflow):
                self.optical_workflow.setCurrentIndex(self.optical_routes.index(visible_route))

    def _sync_sidebar_visibility(self, page_index=None):
        """All pages own the full canvas; navigation lives in the top tab row."""
        self.sidebar.hide()
        self.sidebar.setProperty('simulationHidden',True)

    def _sync_tool_navigation(self, page_index):
        engine_index=self.simulation_engines.currentIndex() if page_index==2 and hasattr(self,'simulation_engines') else None
        for row,(label,index,route_engine) in enumerate(self._tool_pages):
            if index == page_index and (index != 2 or route_engine == engine_index):
                with QSignalBlocker(self.tool_navigation):
                    self.tool_navigation.setCurrentRow(row)
                break

    def adapt_interface(self):
        manager = theme_manager()
        self.progress_bar.setMaximumWidth(max(40,min(220,self.width()-800)))
        manager.set_window_width(self.width())
        compact_header = self.width() < max(1150, round(1150 * manager.effective_scale))
        self.project_header.setVisible(True)
        self.chrome.file_button.setVisible(True)
        self.chrome.view_button.setVisible(False)
        compact = self.sidebar_collapsed or (manager.adaptive and self.width() < 1000 and not getattr(self, '_sidebar_manual', False))
        self._sidebar_compact = compact
        self.sidebar_toggle.setChecked(compact)
        self.sidebar_toggle.setText('›' if compact else '‹')
        self.sidebar_toggle.setAccessibleName('Expand sidebar' if compact else 'Collapse sidebar')
        self.sidebar_toggle.setToolTip('Expand sidebar' if compact else 'Collapse sidebar')
        self.sidebar.setFixedWidth(60 if compact else max(156, round(180 * manager.effective_scale)))
        self._sync_sidebar_visibility()
        icon_size = max(18, round(22 * manager.effective_scale))
        self.tool_navigation.setIconSize(QSize(icon_size, icon_size))
        self.sidebar.layout().setContentsMargins(3 if compact else 10, 8, 3 if compact else 10, 8)
        for index, (label,page_index,engine_index) in enumerate(self._tool_pages):
            item = self.tool_navigation.item(index)
            item.setText('' if compact else label)
            icon_label=( 'Simulate' if ('RCWA' in label or 'FDTD' in label) else
                        'Optimize' if label=='Simulation Sweep' else
                        'Fields' if label=='Field maps' else
                        'Saved work' if label=='Saved results' else label)
            item.setIcon(navigation_icon(icon_label, COLORS[manager.mode]['accent']))
            item.setToolTip(label)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, label)
        for widget in self.sidebar_details:
            widget.setVisible(not compact)
        from PyQt6.QtWidgets import QFormLayout, QTableWidget
        for page in self.pages.values():
            for name in ('workspace_splitter','target_workspace_splitter'):
                splitter=getattr(page,name,None)
                if splitter is not None and splitter.count()==3 and self.width()>=1100:
                    splitter.setSizes([380,650,340])
            if hasattr(page,'builder_splitter'):
                orientation = Qt.Orientation.Vertical if manager.adaptive and self.width() < 1100 else Qt.Orientation.Horizontal
                page.layer_list.setMinimumHeight(180 if orientation == Qt.Orientation.Vertical else 0)
                if page.builder_splitter.orientation() != orientation:
                    page.builder_splitter.setOrientation(orientation)
                    page.builder_splitter.setSizes([420,420,540] if orientation == Qt.Orientation.Vertical else [350,720,370])
            page.layout().setContentsMargins(8,10,8,10)
            page.layout().setSpacing(max(7, round(12 * manager.effective_scale)))
            for form in page.findChildren(QFormLayout):
                form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
                form.setVerticalSpacing(max(5, round(8 * manager.effective_scale)))
                form.setHorizontalSpacing(max(8, round(12 * manager.effective_scale)))
            for table in page.findChildren(QTableWidget):
                table.verticalHeader().setDefaultSectionSize(max(table.fontMetrics().height()+8, round(30 * manager.effective_scale)))

    def refresh_project_icons(self,mode):
        color=COLORS[mode]['text']
        self.project_button.setIcon(navigation_icon('Saved work',color))
        disk=QPixmap(24,24);disk.fill(Qt.GlobalColor.transparent)
        painter=QPainter(disk);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(color),1.6))
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(4,3,16,18,1.5,1.5)
        painter.setPen(QPen(QColor(COLORS[mode]['panel']),1))
        painter.setBrush(QColor(COLORS[mode]['panel']))
        painter.drawRect(8,3,8,6);painter.drawRect(8,13,8,8)
        painter.setPen(QPen(QColor(color),1.6))
        painter.drawLine(13,4,13,7);painter.end()
        self.project_save_button.setIcon(QIcon(disk));self.project_save_button.setIconSize(QSize(24,24))

    def refresh_theme(self,mode):
        self.refresh_project_icons(mode)
        if hasattr(self,'_desktop_glass'):
            self._desktop_glass.apply(enabled=theme_manager().style=='glass',mode=mode)
        for key,control in self.theme_buttons.items():control.setChecked(key==mode)
        with QSignalBlocker(self.theme_select):
            self.theme_select.setCurrentIndex(self.theme_select.findData(theme_manager().look))
        for index, label in enumerate(('Structure','Materials','Simulate','Optimize','Fields','Saved work','Settings','About','AI Search')):
            self.navigation.item(index).setIcon(navigation_icon(label, COLORS[mode]['accent']))
        for index,(label,page_index,engine_index) in enumerate(self._tool_pages):
            icon_label=( 'Simulate' if ('RCWA' in label or 'FDTD' in label) else
                        'Optimize' if label=='Simulation Sweep' else
                        'Fields' if label=='Field maps' else
                        'Saved work' if label=='Saved results' else label)
            self.tool_navigation.item(index).setIcon(navigation_icon(icon_label, COLORS[mode]['accent']))
        if hasattr(self,'structure_notice') and self.structure_notice.isVisible():
            self.position_structure_notice()

    def structure_signature(self):
        return tuple(frame.to_json(orient='records') for frame in
                     (self.store.materials,self.store.layers,self.store.patterns)) + (
                     self.store.settings.get('ax_um'),self.store.settings.get('ay_um'))

    def structure_changed(self,*args):
        snapshot=self.structure_signature()
        if snapshot==self._structure_snapshot:
            return
        self._structure_snapshot=snapshot
        names=self.store.layers.Name.tolist()
        visible=' → '.join(names[:7])
        if len(names)>7:
            visible+=f' → +{len(names)-7} layers'
        self.structure_notice.title_label.setText('Shared Structure updated')
        self.structure_notice.summary.show()
        self.structure_notice.summary.setText(
            f'{max(0,len(names)-2)} finite layers · {len(self.store.patterns)} regions · '
            f'{self.store.settings["ax_um"]:g} × {self.store.settings["ay_um"]:g} µm\n'
            'Applied to every workflow.')
        self.structure_notice.setToolTip(visible)
        self.position_structure_notice()
        self.structure_notice.show()
        self.structure_notice.raise_()
        self.structure_notice.timer.start()

    def notify_action(self,title,message='',detail=None):
        notice=self.structure_notice
        notice.title_label.setText(str(title))
        notice.dismiss_button.setAccessibleName('Dismiss notification')
        message=str(message or '')
        notice.summary.setText(message)
        notice.summary.setVisible(bool(message) and message.rstrip('.!').casefold()!=str(title).casefold())
        notice.setToolTip(str(detail or message))
        self.position_structure_notice()
        notice.show();notice.raise_();notice.timer.start()

    def show_status_message(self,message):
        notice=completion_notice(message)
        if notice is not None:
            self.notify_action(*notice,detail=str(message))
            self.status.setText('Ready')
        else:self.status.setText(str(message))

    def position_structure_notice(self):
        notice=self.structure_notice
        notice.setFixedWidth(min(440,max(240,self.workspace.width()-32)))
        notice.adjustSize()
        notice.move(max(8,self.workspace.width()-notice.width()-20),10)

    def _defer_saved_window_state(self):
        # Creating the custom HWND with an already-maximized Qt state gives
        # Qt an 8-pixel native frame around its frameless alpha backing store.
        # That surface can be entirely invisible although QWidget.grab works.
        # Establish the normal window and its first native paint before asking
        # Qt to maximize/fullscreen, preserving the saved normal geometry.
        self._startup_window_state = self.windowState() & (
            Qt.WindowState.WindowMaximized | Qt.WindowState.WindowFullScreen)
        if self._startup_window_state:
            self.setWindowState(Qt.WindowState.WindowNoState)

    def paintEvent(self,event):
        super().paintEvent(event)
        state=getattr(self,'_startup_window_state',Qt.WindowState.WindowNoState)
        if state and self.isVisible():
            self._startup_window_state=Qt.WindowState.WindowNoState
            # The queued callback runs after this entire widget tree has been
            # painted and flushed, including the native layered backing store.
            def restore_state():
                if self.isVisible():
                    if state & Qt.WindowState.WindowFullScreen:self.showFullScreen()
                    else:self.showMaximized()
            QTimer.singleShot(0,restore_state)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self, 'appearance_timer'):
            self.appearance_timer.start()
        if hasattr(self,'structure_notice'):
            self.position_structure_notice()
        if hasattr(self,'navigation') and self.navigation.currentItem() is not None:
            item=self.navigation.currentItem()
            bounds=self.navigation.visualItemRect(item)
            if bounds.top()<0 or bounds.bottom()>self.navigation.viewport().height():
                self.navigation.scrollToItem(item)

    def _close_after_updates(self):
        if self._updates_closing:
            self._updates_closing=False
            QTimer.singleShot(0,self.close)

    def _restart_for_addons(self):
        from application_restart import prepare_restart, launch_restart
        try:
            plan = prepare_restart(self.store.library.root, store=self.store,
                busy_checks=(lambda: self.pages['About'].busy,
                             lambda: self.pages['Settings'].addons_panel.busy))
            launch_restart(plan)
            # prepare_restart has saved the session; helper waits for this PID.
            self.preferences.setValue('geometry', self.saveGeometry())
            self.preferences.setValue('page', self.navigation.currentRow())
            QApplication.instance().quit()
        except Exception:
            self.show_error('The add-on is staged, but automatic restart could not start. Close and reopen the application when your work is saved.')

    def open_project(self):
        if self.store.busy:
            self.show_error('Wait for the current calculation before opening a project.')
            return False
        path,_=QFileDialog.getOpenFileName(self,'Open project',self._project_directory(),'Optical Studio project (*.json)')
        if path:
            if not self._confirm_project_replace():
                return False
            try:
                self.store.load_project(path)
                self._project_file_saved(path)
                self._navigate_route(0)
                self.notify_action('Opened',self.project_path.name,detail=str(self.project_path))
                self.status.setText('Ready')
                return True
            except Exception as exc:
                self.show_error('Could not open '+path+': '+str(exc))
        return False

    def save_project(self):
        return self._save_project_to(self.project_path) if self.project_path else self.save_project_as()

    def save_project_as(self):
        initial=str(self.project_path) if self.project_path else str(Path(self._project_directory())/'s4_project.json')
        path,_=QFileDialog.getSaveFileName(self,'Save project as',initial,'Optical Studio project (*.json)')
        if not path:
            return False
        if not Path(path).suffix:
            path+='.json'
        return self._save_project_to(path)

    def _save_project_to(self,path):
        try:
            result=self.store.save_project(str(path))
            self._project_file_saved(result)
            self.notify_action('Saved',self.project_path.name,detail=str(self.project_path))
            self.status.setText('Ready')
            return True
        except Exception as exc:
            self.show_error('Could not save '+str(path)+': '+str(exc)+'. Use Save as to choose another writable location.')
            return False

    def _project_directory(self):
        return str(self.project_path.parent) if self.project_path else str(self.preferences.value('project_directory',str(Path.home()/'Documents')))

    def _project_file_saved(self,path):
        self.project_path=Path(path).resolve()
        self.preferences.setValue('project_directory',str(self.project_path.parent))
        self._saved_project=copy.deepcopy(self.store.project())
        self._refresh_project_file()

    def _project_store_changed(self,reason):
        # Presets and Saved Results can also replace the shared project. They
        # must never retain the previous file as an implicit overwrite target.
        if reason=='project':
            self.project_path=None
            self._saved_project=None
        self._refresh_project_file()

    def _refresh_project_file(self):
        dirty=self.store.project()!=self._saved_project
        name=self.project_path.name if self.project_path else 'Untitled project'
        label=name+(' *' if dirty else '')
        self.project_select.setText(self.project_select.fontMetrics().elidedText(label,Qt.TextElideMode.ElideMiddle,190))
        self.project_select.setAccessibleName('Current project: '+label)
        detail=(str(self.project_path) if self.project_path else 'No project file selected. Save to create a portable JSON project.')
        if dirty:
            detail+='\nChanges have not been saved to the project file.'
        detail+='\nWorking-session recovery is automatic; use Save to update your portable project.'
        self.project_select.setToolTip(detail)
        self.project_button.setText(self.project_button.fontMetrics().elidedText(label,Qt.TextElideMode.ElideMiddle,160)+'  ⌄')
        self.project_button.setToolTip(detail)
        if hasattr(self,'footer_project'):
            self.footer_project.setText(self.footer_project.fontMetrics().elidedText(label,Qt.TextElideMode.ElideMiddle,138)+'\nUnits: µm')
        self.chrome.title.setToolTip(detail)
        self.setWindowTitle('Optical Design Studio')

    def _confirm_project_replace(self):
        if self.store.project()==self._saved_project:
            return True
        answer=QMessageBox.question(self,'Save project changes?',
            'Save changes to the current project before replacing it? Automatic session recovery will be replaced by the new project.',
            QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        return self.save_project() if answer==QMessageBox.StandardButton.Save else answer==QMessageBox.StandardButton.Discard

    def busy_changed(self,busy):
        self.progress_bar.setVisible(busy)
        self._sync_run_actions()
        if busy:
            self.progress_bar.setRange(0,0)
            self.status.setText('Running…')
        elif self._closing:
            QTimer.singleShot(0,self.close)

    def show_progress(self,event):
        if event.get('total') and event.get('done') is not None:
            self.progress_bar.setRange(0,100)
            self.progress_bar.setValue(max(0, min(100, int(100 * event['done'] / event['total']))))
            self.status.setText(f"{event['done']:,} / {event['total']:,} spectrum points")
        elif event.get('text'):
            self.status.setText(str(event['text']))

    def show_error(self,error):
        self.status.setText('Check: '+str(error)[-800:])
        self.status.setToolTip(str(error))

    def show_finished(self,event):
        summary=event.get('summary',{})
        state=str(summary.get('status',event.get('status','complete')))
        warnings=summary.get('warnings',[])
        if state.lower() in ('error','failed','cancelled') or warnings:
            self.status.setText(f"{event.get('run_kind','Calculation').title()}: {state}" +
                                (' with warnings' if warnings else ''))
            if warnings:self.status.setToolTip('\n'.join(map(str,warnings)))
        else:
            self.notify_action(event.get('run_kind','Calculation').title()+' complete','Results saved to your library.')
            self.status.setText('Ready')

    def closeEvent(self,event):
        for page in (self.pages['About'], self.pages['Settings'].addons_panel):
            if not page.shutdown():
                self._updates_closing=True
                self.status.setText('Cancelling the package operation safely before closing…')
                event.ignore()
                return
        if self.store.busy:
            event.ignore()
            if not callable(getattr(self.store._worker, 'cancel', None)):
                self.status.setText('The library operation is finishing. Close the window when it completes.')
                return
            answer=QMessageBox.question(self,'Calculation running','Cancel the active calculation and close after its workers stop?',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
            if answer==QMessageBox.StandardButton.Yes:
                self._closing=True
                self.store.cancel()
            return
        if not self.pages['About'].shutdown():
            self._updates_closing=True
            self.status.setText('Stopping the update request safely. The window will close when it finishes.')
            event.ignore()
            return
        if not self.pages['Settings'].addons_panel.shutdown():
            self._updates_closing=True
            self.status.setText('Stopping the add-on request safely. The window will close when it finishes.')
            event.ignore()
            return
        try:
            self.store._autosave()
        except Exception as exc:
            self.show_error('Could not save the session: '+str(exc)+'. Save a portable project before closing.')
            event.ignore()
            return
        self.preferences.setValue('geometry',self.saveGeometry())
        self.preferences.setValue('page',self.navigation.currentRow())
        event.accept()


def main(argv=None):
    import multiprocessing
    multiprocessing.freeze_support()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--theme',choices=['dark','light'])
    parser.add_argument('--look',choices=list(LOOKS),help='Choose B or frosted glass in light or dark mode.')
    parser.add_argument('--project',type=Path)
    parser.add_argument('--library',type=Path)
    parser.add_argument('--no-restore',action='store_true')
    parser.add_argument('--update-ack', type=Path)
    parser.add_argument('--page', choices=['Structure','Materials','Simulate','Optimize','Fields','Saved work','Settings','About','AI Search'])
    args=parser.parse_args(argv)
    selected_library=initialize_desktop(argv)
    set_windows_app_id()
    application=QApplication(sys.argv[:1])
    application.setApplicationName('Optical Design Studio')
    application.setApplicationVersion(APP_VERSION)
    application.setOrganizationName('ZhouGroup')
    icon=resource_root()/'S4_Studio.ico'
    if icon.is_file():
        application.setWindowIcon(QIcon(str(icon)))
    if args.look:
        theme_manager().apply_look(args.look)
    elif args.theme:
        theme_manager().apply(args.theme)
    else:
        theme_manager().apply(theme_manager().mode,persist=False)
    store=ProjectStore(DataLibrary(selected_library),restore=not args.no_restore)
    if args.project:
        store.load_project(args.project)
    window=OpticalStudio(store)
    if args.project:
        window._project_file_saved(args.project)
    from crash_reporting import install_crash_reporting
    window._crash_reporting = install_crash_reporting(selected_library, window.show_error)
    if args.page:
        index=next(i for i in range(window.navigation.count()) if window.navigation.item(i).text()==args.page)
        window._navigate_route(index)
    window.show()
    def save_window_preferences():
        window.preferences.setValue('geometry', window.saveGeometry())
        window.preferences.setValue('page', window.navigation.currentRow())
        window.preferences.sync()
    application.aboutToQuit.connect(save_window_preferences)
    def startup_ready():
        from desktop_runtime import startup_addon_results
        if startup_addon_results:
            messages = [f"{result['id']}: " + ('installed and verified' if result['status']=='activated'
                else 'installation failed; previous version preserved') for result in startup_addon_results]
            window.status.setText(' · '.join(messages))
            window.status.setToolTip('\n'.join(str(result.get('error', '')) for result in startup_addon_results))
        from application_restart import acknowledge_restart
        acknowledge_restart()
        if args.update_ack:
            from update_install import acknowledge_startup
            acknowledge_startup(args.update_ack)
    QTimer.singleShot(0, startup_ready)
    return application.exec()


if __name__=='__main__':
    raise SystemExit(main())
