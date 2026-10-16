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

from PyQt6.QtCore import Qt, QSettings, QTimer, QSignalBlocker, QSize, QObject, pyqtSignal, QEvent, QCoreApplication
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
from qt_reference_style import reference_icon,REFERENCE_SIZE,BUILDER_PROPORTIONS


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
    startupPainted=pyqtSignal()

    def __init__(self,store=None,workspace_profile='device',*,defer_setup=False):
        super().__init__()
        self._construction_complete=False
        self._startup_painted=False
        self.setUpdatesEnabled(False)
        self._initialization=self._initialize(store,workspace_profile)
        if not defer_setup:
            for _ in self._initialization:pass
            self._initialization=None

    def advance_startup(self):
        """Build one complete GUI section; the caller yields to Qt between steps."""
        if self._initialization is None:return None
        try:return next(self._initialization)
        except StopIteration:
            self._initialization=None
            return None

    def _initialize(self,store,workspace_profile):
        self.workspace_profile='device'
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
        self.resize(*REFERENCE_SIZE)
        geometry=self.preferences.value('geometry')
        if geometry is not None:self.restoreGeometry(geometry)
        self._defer_saved_window_state()
        # Establish density before constructing the page tree. Restyling every
        # hidden page after construction was the dominant launch-time cost.
        theme_manager().set_window_width(self.width())
        central=WorkspaceBackground(self,desktop_root=True)
        self.setCentralWidget(central)
        root=QVBoxLayout(central)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(0)
        yield 'Preparing navigation and project controls…'
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
        self.project_select.hide()
        project_layout.addWidget(self.project_select)
        self.workspace_context=QLabel('Shared builder + Canvas tools')
        self.workspace_context.setObjectName('referenceWorkspaceContext')
        project_layout.addWidget(self.workspace_context)
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
        menu.addAction('Saved work library…',lambda:self._navigate_route(5))
        self.switch_workspace_action=menu.addAction('Switch workspace…',self.choose_workspace)
        menu.addAction('Choose simulation…',self.choose_workspace)
        optical_tools=menu.addMenu('Additional optical tools')
        optical_tools.addAction('Simulation Sweep',lambda:self._navigate_route(3))
        optical_tools.addAction('AI Search',lambda:self._navigate_route(8))
        optical_tools.addSeparator()
        optical_tools.addAction('S4 optical setup',lambda:self._open_optical_engine('s4'))
        optical_tools.addAction('MEEP · FDTD setup',lambda:self._open_optical_engine('meep'))
        optical_tools.addAction('Refractive-index sweep',lambda:self._navigate_route(2,2))
        optical_tools.addAction('Optical field maps',lambda:self._navigate_route(2,3))
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
        self.optical_workflow=QTabBar();self.optical_workflow.setObjectName('opticalWorkflowTabs');self.optical_workflow.setExpanding(False)
        self.optical_workflow.setDrawBase(False)
        self.optical_workflow.setUsesScrollButtons(True)
        self.optical_routes=[0,1,2,3,8,6,7]
        for label in ['Structure','Materials','Simulation','Simulation Sweep','AI Search','Settings','Help']:
            self.optical_workflow.addTab(label)
        self.optical_workflow.currentChanged.connect(lambda i:self._navigate_route(self.optical_routes[i]) if 0<=i<len(self.optical_routes) else None)
        navigation_bar=QFrame();self.navigation_bar=navigation_bar;navigation_bar.setObjectName('projectHeader');navigation_bar.setFixedHeight(42)
        navigation_layout=QHBoxLayout(navigation_bar)
        self.navigation_layout=navigation_layout
        navigation_layout.setContentsMargins(14,0,10,0);navigation_layout.setSpacing(8)
        self.optical_workflow.setMaximumWidth(1040)
        navigation_layout.addWidget(self.optical_workflow,1)
        navigation_layout.addStretch(0)
        self.diagnostic_back_button=QPushButton('Back to missing inputs')
        self.diagnostic_back_button.clicked.connect(self._return_from_diagnostic)
        self.diagnostic_back_button.hide()
        navigation_layout.addWidget(self.diagnostic_back_button)
        self._diagnostic_origin=None
        self.project_button=QToolButton()
        self.project_button.setObjectName('projectPicker')
        self.project_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.project_button.setText('Untitled project  ⌄')
        self.project_button.setIcon(navigation_icon('Saved work',COLORS[theme_manager().mode]['text']))
        self.project_button.setMinimumSize(140,32)
        self.project_button.setMaximumWidth(240)
        self.project_button.clicked.connect(self.open_project)
        navigation_layout.addWidget(self.project_button)
        self.project_button.hide()
        self.project_save_button=QToolButton()
        self.project_save_button.setObjectName('projectSave')
        self.project_save_button.setFixedSize(40,40)
        self.project_save_button.setAccessibleName('Save project')
        self.project_save_button.setToolTip('Save project (Ctrl+S)')
        self.refresh_project_icons(theme_manager().mode)
        self.project_save_button.clicked.connect(self.save_project)
        navigation_layout.addWidget(self.project_save_button)
        self.project_save_button.hide()
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
            ('S4 · RCWA',2,0),('MEEP · FDTD',2,1),('Electrical',2,5),('Coupled',2,6),
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
        workspace=WorkspaceBackground(central)
        self.workspace=workspace
        body.addWidget(workspace,1)
        content=QVBoxLayout(workspace)
        content.setContentsMargins(0,0,0,0)
        content.setSpacing(0)
        self.stack=QStackedWidget(workspace)
        content.addWidget(self.stack,1)
        yield 'Preparing the structure editor…'
        from qt_custom_device import CustomDevicePage as StructurePage
        from qt_materials import MaterialsPage
        from qt_library import LibraryPage
        from qt_compute import SimulationPage,OptimizePage,FieldsPage,SettingsPage
        from qt_about import AboutPage
        from qt_fdtd import FDTDPage
        from qt_ai_search import AISearchPage
        classes=[StructurePage,MaterialsPage,SimulationPage,OptimizePage,FieldsPage,LibraryPage,SettingsPage,AboutPage,AISearchPage]
        self.pages={}
        for index,cls in enumerate(classes):
            page=cls(self.store) if cls is AboutPage else cls(self.store,self.stack)
            if cls is AboutPage:page.setParent(self.stack)
            if cls is AboutPage:
                from qt_help import add_help_tabs
                add_help_tabs(page)
            if not page.objectName():page.setObjectName('page')
            if hasattr(page,'routeRequested'):page.routeRequested.connect(self._route_setup_action)
            if cls is StructurePage:page.setProperty('referenceWorkspace',True)
            for guidance in page.findChildren(QLabel,'muted'):
                guidance.setToolTip(guidance.text());guidance.hide()
            page.layout().setContentsMargins(8,6,8,6)
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
            yield 'Prepared '+self.navigation.item(index).text()+' editor'
        from simulation_setup_state import SimulationSetupState
        from qt_simulation_setup import SimulationSetupWorkspace
        self.setup_state=SimulationSetupState(self.store,self)
        self.electrical_page=SimulationSetupWorkspace(self.store,self.simulation_engines,mode='electrical',state=self.setup_state)
        self.simulation_engines.addTab(self.electrical_page,'Electrical')
        yield 'Prepared electrical simulation setup'
        self.coupled_page=SimulationSetupWorkspace(self.store,self.simulation_engines,mode='coupled',state=self.setup_state)
        self.simulation_engines.addTab(self.coupled_page,'Coupled')
        yield 'Prepared coupled simulation setup'
        self.optical_setup=SimulationSetupWorkspace(self.store,self.simulation_engines,mode='optical',state=self.setup_state)
        self.simulation_engines.removeTab(0)
        self.pages['Simulate'].setParent(self);self.pages['Simulate'].hide()
        self.simulation_engines.insertTab(0,self.optical_setup,'Optical')
        self.simulation_engines.addTab(self.pages['Simulate'],'Original optical')
        self.simulation_engines.setCurrentIndex(0)
        for setup_page in (self.optical_setup,self.electrical_page,self.coupled_page):
            setup_page.setProperty('referenceWorkspace',True)
            setup_page.selectWorkflow.connect(self._select_simulation_workflow)
            setup_page.routeRequested.connect(self._route_setup_action)
            setup_page.runRequested.connect(self._run_setup_mode)
            setup_page.editDeviceRequested.connect(lambda:self._navigate_route(0))
            setup_page.resultsRequested.connect(lambda record:self._open_simulation_result(record.get('directory'),record.get('summary',{})))
            setup_page.diagnosticRequested.connect(lambda target,p=setup_page:self._open_input_diagnostic(target,p))
        yield 'Prepared optical simulation setup'
        self._pending_setup_fields=None
        self._queued_setup_fields=None
        self.store.run_finished.connect(self._setup_run_finished)
        self.store.run_failed.connect(self._setup_run_failed)
        self.store.busy_changed.connect(self._setup_busy_changed)
        from qt_results_workspace import ResultsWorkspace
        self.results_page=ResultsWorkspace(self.store)
        self.results_page.setProperty('referenceWorkspace',True)
        self.navigation.addItem('Results');self.stack.addWidget(self.results_page)
        self.pages['Results']=self.results_page
        from qt_photonic_bands import PhotonicBandsWorkspace
        from qt_research_studies import ResearchStudiesWorkspace
        self.photonic_bands_page=PhotonicBandsWorkspace(self.store,self.stack)
        self.research_studies_page=ResearchStudiesWorkspace(self.store,self.stack)
        self.research_studies_page.projectReplacementRequested.connect(self._open_research_reference)
        self.research_studies_page.independentBenchmarkRequested.connect(self._open_band_reference)
        self.research_studies_page.selectionChanged.connect(self._sync_run_actions)
        self.research_studies_page.simulationRequested.connect(self._open_simulation_choice)
        for label,page in (('Photonic Bands',self.photonic_bands_page),('More studies',self.research_studies_page)):
            page.set_embedded(True)
            self.navigation.addItem(label)
            self.stack.addWidget(page)
            self.pages[label]=page
            page.diagnosticRequested.connect(lambda target,p=page:self._open_input_diagnostic(target,p))
            if hasattr(page,'routeRequested'):page.routeRequested.connect(self._route_setup_action)
        menu.addAction('Photonic Bands',lambda:self._navigate_route(10))
        menu.addAction('More studies and paper benchmarks',lambda:self._navigate_route(11))
        menu.addAction('PCSEL simulations',lambda:self._route_setup_action('pcsel'))
        yield 'Prepared photonic bands and additional studies'
        self.results_page.openRunRequested.connect(self._choose_simulation_result)
        self.results_page.rerunRequested.connect(self._rerun_simulation_result)
        self.pages['About'].idle.connect(self._close_after_updates)
        yield 'Prepared saved results and exports'
        for nested_page in (self.fdtd_page,self.index_shift_page):
            if hasattr(nested_page,'routeRequested'):nested_page.routeRequested.connect(self._route_setup_action)
            for guidance in nested_page.findChildren(QLabel,'muted'):
                guidance.setToolTip(guidance.text());guidance.hide()
        self.simulation_local_bars=[]
        self.simulation_engines.tabBar().hide()
        simulation_pages=[self.pages['Simulate'],self.fdtd_page,self.index_shift_page,self.pages['Fields'],self.pages['Saved work']]
        for simulation_page in simulation_pages:
            bar=QTabBar();bar.setExpanding(True);bar.setUsesScrollButtons(True)
            bar.setObjectName('simulationWorkspaceTabs')
            for engine,text in enumerate(('Optical · S4','Optical · FDTD','Optical · Δn','Optical fields','Saved results','Electrical','Coupled')):
                i=bar.addTab(text);bar.setTabData(i,engine)
            if simulation_page is self.pages['Simulate']:
                left=simulation_page.workspace_splitter.widget(0).findChild(QScrollArea).widget()
                self.original_geometry_label=QLabel('Geometry: optical layer and pattern tables')
                self.original_geometry_label.setWordWrap(True)
                self.original_geometry_label.setObjectName('originalGeometryScope')
                self.original_geometry_label.setToolTip('Original optics uses optical table materials and layers. A finite PC array contributes one air-hole period; electrical contacts and canonical polygon additions are not injected.')
                left.layout().insertWidget(1,self.original_geometry_label)
                left.layout().insertWidget(1,bar)
            elif hasattr(simulation_page,'setup_layout'):
                simulation_page.setup_layout.insertWidget(1,bar)
            else:simulation_page.layout().insertWidget(0,bar)
            bar.currentChanged.connect(lambda index,bar=bar:self._navigate_route(2,bar.tabData(index)) if index>=0 else None)
            self.simulation_local_bars.append(bar)
            if simulation_page in (self.pages['Simulate'],self.electrical_page,self.coupled_page):bar.hide()
        self.simulation_engines.currentChanged.connect(self._sync_simulation_local_bars)
        self._sync_simulation_local_bars(self.simulation_engines.currentIndex())
        self.pages['Structure'].continue_requested.connect(lambda:self._navigate_route(1))
        self.pages['Settings'].addons_panel.idle.connect(self._close_after_updates)
        self.pages['Settings'].addons_panel.restart_requested.connect(self._restart_for_addons)
        self.pages['Settings'].addons_panel.runtime_changed.connect(self.fdtd_page.refresh_runtime)
        footer=QFrame();self.workspace_footer=footer
        footer.setObjectName('workspaceFooter')
        footer.setFixedHeight(62)
        footer_layout=QHBoxLayout(footer)
        footer_layout.setContentsMargins(18,8,18,8);footer_layout.setSpacing(12)
        status_icon=QLabel();status_icon.setPixmap(reference_icon('info',COLORS[theme_manager().mode]['accent']).pixmap(22,22))
        footer_layout.addWidget(status_icon)
        self.status=note('Preview only · no simulation run')
        self.status.setObjectName('globalStatus')
        self.status.setMaximumHeight(36)
        self.progress_bar=QProgressBar()
        self.progress_bar.setMaximumWidth(220)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        self.stop_button=button('Stop',self.store.cancel)
        self.stop_button.setFixedSize(96,36)
        self.run_button=button('▶  Run',self._run_active_workspace,True)
        self.run_button.setObjectName('referenceRun');self.run_button.setFixedSize(202,42)
        self.run_button.setIcon(reference_icon('play'));self.run_button.setIconSize(QSize(19,19))
        self.footer_save=button('Save project',self._save_active_workspace)
        self.footer_save.setObjectName('referenceFooterAction');self.footer_save.setFixedHeight(42)
        self.footer_save.setIcon(reference_icon('save'));self.footer_save.setMinimumWidth(148)
        self.footer_validate=button('Validate device',self._validate_active_workspace)
        self.footer_validate.setObjectName('referenceFooterAction');self.footer_validate.setFixedHeight(42)
        self.footer_validate.setIcon(reference_icon('check'));self.footer_validate.setMinimumWidth(158)
        for run_page in (self.pages['Simulate'],self.fdtd_page,self.index_shift_page,self.pages['Fields'],self.pages['Optimize'],self.electrical_page,self.coupled_page):
            for action in getattr(run_page,'starts',[]):action.hide()
            for action in getattr(run_page,'stops',[]):action.hide()
        self.fdtd_page.start_button.hide();self.fdtd_page.stop_button.hide()
        for action in self.pages['AI Search'].campaign_actions.findChildren(QPushButton):action.hide()
        for action in self.pages['AI Search'].stops:action.hide()
        footer_layout.addWidget(self.status,1)
        self.footer_project=note('Untitled project  ·  Units: µm')
        self.footer_project.setFixedWidth(140)
        self.footer_project.setFixedHeight(36)
        self.footer_project.hide()
        footer_layout.addWidget(self.progress_bar)
        footer_layout.addWidget(self.footer_save)
        footer_layout.addWidget(self.footer_validate)
        footer_layout.addWidget(self.run_button)
        footer_layout.addWidget(self.stop_button)
        content.addWidget(footer)
        self.results_page.layout().removeWidget(self.results_page.footer_widget)
        content.addWidget(self.results_page.footer_widget)
        self.results_page.footer_widget.hide()
        yield 'Finalizing workspace layout…'
        self._windows_frame = WindowsCustomFrame(self)
        self._desktop_glass = WindowsDesktopGlass(self)
        self._desktop_glass.changed.connect(central.update)
        self._desktop_glass.apply(enabled=theme_manager().style=='glass',mode=theme_manager().mode)
        self.structure_notice=StructureNotice(workspace)
        self._structure_snapshot=self.structure_signature()
        self.navigation.currentRowChanged.connect(self._display_route)
        self.navigation.currentRowChanged.connect(self._sync_workspace_tabs)
        self.navigation.currentRowChanged.connect(self._sync_tool_navigation)
        saved_page=int(self.preferences.value('page',0))
        self.navigation.setCurrentRow(saved_page if 0<=saved_page<self.navigation.count() else 0)
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
        if hasattr(self.pages['Structure'],'status_changed'):self.pages['Structure'].status_changed.connect(self.status.setText)
        theme_manager().appearance_changed.connect(self.adapt_interface)
        self.adapt_interface()
        # Project mutations and explicit open/save actions update file status.
        # Polling a full snapshot every 700 ms freezes large PC-array projects.
        self.file_state_timer=QTimer(self)  # Inactive compatibility adapter.
        self.store.changed.connect(self._project_store_changed)
        self.store.search_changed.connect(self._refresh_project_file)
        self._refresh_project_file()
        self._sync_run_actions()
        self.set_workspace_profile(workspace_profile)
        self.store.changed.connect(self._refresh_original_geometry_label)
        self._refresh_original_geometry_label()
        self._construction_complete=True
        self.setUpdatesEnabled(True)

    def _refresh_original_geometry_label(self,*_):
        from optical_unit_cell import pc_unit_cell
        try:
            cell=pc_unit_cell(self.store.device)
            if cell is not None:
                text=f"Geometry: optical tables · one air hole · {cell['width_um']:g} × {cell['depth_um']:g} µm periodic cell"
            else:
                text=f"Geometry: optical layer and pattern tables · {self.store.settings['ax_um']:g} × {self.store.settings['ay_um']:g} µm periodic cell"
        except ValueError as exc:text='Optical cell: '+str(exc)
        self.original_geometry_label.setText(text)

    def choose_workspace(self):
        if self.store.busy:
            self.status.setText('Wait for the active calculation before switching workspaces.')
            return
        from qt_workspace_start import choose_startup_workspace
        profile=choose_startup_workspace('ask',self.preferences,self,self.workspace_profile)
        if profile is not None:self.set_workspace_profile(profile)

    def set_workspace_profile(self,profile):
        """Select an interface without rewriting applied geometry or settings."""
        from qt_workspace_start import normalize_workspace_profile
        simulation_target=getattr(profile,'simulation_target','')
        selected=normalize_workspace_profile(profile)
        if selected not in ('device','original'):raise ValueError('Unknown workspace: '+str(profile))
        profile=selected
        self.workspace_profile=profile
        self.store.optical_geometry_source='original_tables' if profile=='original' else 'device'
        self.setWindowTitle('Optical Design Studio · '+('Original Optical Studio' if profile=='original' else 'Device Studio'))
        structure=self.pages['Structure']
        structure.tabs.setTabEnabled(0,profile!='original')
        structure.tabs.setCurrentIndex(1 if profile=='original' else 0)
        structure.advanced_return.setVisible(False)
        self.pages['Materials'].workspace_tabs.tabBar().setVisible(profile!='original')
        self.pages['Materials'].workspace_tabs.setTabEnabled(1,profile!='original')
        if profile=='original':self.pages['Materials'].workspace_tabs.setCurrentIndex(0)
        choices=((7,'Original · S4'),(1,'Optical · FDTD'),(2,'Optical · Δn'),(3,'Optical fields'),(4,'Saved results')) if profile=='original' else tuple(enumerate(('Optical · S4','Optical · FDTD','Optical · Δn','Optical fields','Saved results','Electrical','Coupled')))
        for bar in self.simulation_local_bars:
            with QSignalBlocker(bar):
                while bar.count():bar.removeTab(0)
                for engine,text in choices:
                    index=bar.addTab(text);bar.setTabData(index,engine)
            bar.setVisible(profile=='original' or bar is not self.simulation_local_bars[0])
        index=self.simulation_engines.currentIndex()
        for engine in (0,5,6):self.simulation_engines.setTabEnabled(engine,profile!='original')
        self.simulation_engines.setTabEnabled(7,profile=='original')
        if profile=='original' and index in (0,5,6):self.simulation_engines.setCurrentIndex(7)
        elif profile=='device' and index==7:self.simulation_engines.setCurrentIndex(0)
        self._sync_simulation_local_bars(self.simulation_engines.currentIndex())
        self._reference_navigation_mode=None
        if profile=='original' and self.navigation.currentRow()==9:
            self._navigate_route(2,7)
        else:self._sync_workspace_tabs(self.navigation.currentRow())
        self.status.setText(self._idle_workspace_description())

        if simulation_target:self._open_simulation_choice(simulation_target)

    def _open_simulation_choice(self,target):
        """Open the selected editable model without starting or replacing a project."""
        if target.startswith('photonic_bands'):
            self._navigate_route(10)
            page=self.photonic_bands_page
            dimension=3 if target=='photonic_bands' else 2
            solver='legume' if target.endswith('.legume') else 'mpb'
            page.dimension.setCurrentIndex(page.dimension.findData(dimension))
            page.solver.setCurrentIndex(page.solver.findData(solver))
            page.show_stage('unit');page.flush_draft()
        elif target.startswith('sesame_transport'):
            self._navigate_route(11);self.research_studies_page.select_engine('sesame_transport')
            page=self.research_studies_page._pages['sesame_transport']
            page.dimension.setCurrentIndex(page.dimension.findData(2 if target.endswith('.2d') else 1))
            page.study_flow.show_stage(0);page.flush_draft()
        elif target in ('electrical','electrical.iv','electrical.cv'):
            self._select_simulation_workflow('electrical')
            choice={'electrical':'bias','electrical.iv':'iv','electrical.cv':'cv'}[target]
            try:self.setup_state.set('ui.electrical.study',choice)
            except ValueError:pass
            self.electrical_page.select_section('electrical.study')
            if self.setup_state.get('ui.electrical.study')!=choice:
                self.status.setText('Select the editable-device model to use this study. Your existing settings are preserved.')
        elif target=='papers':
            self._navigate_route(11);self.research_studies_page.show_paper_library()
        elif target.startswith('pcsel.'):
            self._navigate_route(11)
            self.research_studies_page.select_engine('pcsel')
            self.research_studies_page._pages['pcsel'].select_model(target.split('.',1)[1])
        elif target=='lumped_laser':
            self._navigate_route(11);self.research_studies_page.select_engine(target)
        elif target=='fdtd':self._navigate_route(2,1)
        else:self._route_setup_action(target)

    def _run_active_workspace(self):
        route=self.navigation.currentRow()
        if route==2:
            index=self.simulation_engines.currentIndex()
            page=(self.pages['Simulate'],self.fdtd_page,self.index_shift_page,self.pages['Fields'],None,self.electrical_page,self.coupled_page,self.pages['Simulate'])[index]
            if index in (0,5,6):
                (self.optical_setup,self.electrical_page,self.coupled_page)[(0,5,6).index(index)].run()
            elif page is not None:page.run()
        elif route==0:
            if self.workspace_profile=='original':
                self._navigate_route(2,7)
                self.pages['Simulate'].run()
                return
            # The shared builder runs the selected simulation workflow. An
            # optical cell must not require a resolved full electrical mesh.
            if not self.pages['Structure'].apply_inspector():return
            engine=self.simulation_engines.currentIndex()
            if engine in (3,4):engine=0
            self._navigate_route(2,engine)
            self._run_active_workspace()
        elif route==3:
            page=self.pages['Optimize']
            (page.run_target if page.tabs.currentIndex()==0 else page.run_peaks)()
        elif route==8:self.pages['AI Search'].run('search')
        elif route==9:self._rerun_simulation_result()
        elif route==10:self.photonic_bands_page.run()
        elif route==11:self.research_studies_page.run()

    def _select_simulation_workflow(self,workflow):
        if self.workspace_profile!='device':self.set_workspace_profile('device')
        {'optical':self.optical_setup,'electrical':self.electrical_page,'coupled':self.coupled_page}[workflow].set_mode(workflow)
        self._navigate_route(2,{'optical':0,'electrical':5,'coupled':6}[workflow])

    def _open_optical_engine(self,engine):
        if self.workspace_profile=='original':
            self._navigate_route(2,7 if engine=='s4' else 1)
            return
        self.setup_state.set('ui.optical.engine',engine)
        self._select_simulation_workflow('optical')
        self.optical_setup.select_section('optical.domain')

    def _route_setup_action(self,target):
        """Use named destinations so new section tabs cannot shift old routes."""
        target=str(target)
        head=target.split('.')[0].lower()
        if head=='global':head=target.split('.')[1].lower()
        from research_simulation import ADAPTERS
        research_engines={engine for engine,_ in ADAPTERS}
        if head in research_engines or head in ('bands','research','studies','research_studies'):
            route=10 if head in ('photonic_bands','bands') else 11
            self._navigate_route(route)
            page=self.photonic_bands_page if route==10 else self.research_studies_page
            if route==11 and head in research_engines:page.select_engine(head)
            if hasattr(page,'select_section'):page.select_section(target)
            return
        if head in ('optical','electrical','coupled'):
            self._select_simulation_workflow(head)
            page={'optical':self.optical_setup,'electrical':self.electrical_page,'coupled':self.coupled_page}[head]
            page.select_section(head+'.overview' if target==head else target)
            return
        if head in ('structure','device'):
            if target=='structure.original':
                self.set_workspace_profile('original')
                self._navigate_route(0)
                self.status.setText('Edit the optical layer and pattern structure used by this simulation.')
                return
            self._navigate_route(0)
            origin={0:self.optical_setup,5:self.electrical_page,6:self.coupled_page}.get(self.simulation_engines.currentIndex())
            selected=getattr(origin,'selected_object','') if origin is not None else ''
            if 'contact' in target:selected=self.setup_state.get('ui.electrical.selected_contact_id',selected)
            if selected:self.pages['Structure'].select_object(selected)
            if target.endswith('.optical'):self.pages['Structure'].inspector_tabs.setCurrentIndex(2)
            if 'pc' in target:
                QTimer.singleShot(0,self.pages['Structure'].pc_area)
            return
        if head in ('materials','material'):
            self._navigate_route(1)
            page=self.pages['Materials']
            if hasattr(page,'workspace_tabs'):
                electrical='electrical' in target or target=='global.materials' and self.simulation_engines.currentIndex() in (5,6)
                page.workspace_tabs.setCurrentIndex(1 if electrical else 0)
            return
        global_routes={'settings':6,'help':7,'about':7,'results':9}
        if head in global_routes:
            self._navigate_route(global_routes[head])
            if head=='results':
                category={'optical':'Optical response','profiles':'Carriers & charge','iv':'I–V / C–V',
                    'cv':'I–V / C–V','fields':'Potential & fields','exports':'Raw data & exports',
                    'optical-fields':'Optical E/H','phase':'Specular phase'}.get(target.split('.')[-1])
                if category:self.results_page.select_category(category)
            elif head=='settings':
                page=self.pages['Settings']
                if hasattr(page,'select_section'):page.select_section(target)
            return
        tools={'sweep':(3,None),'ai':(8,None),'index_shift':(2,2),'fields':(2,3),'library':(2,4)}
        parts=target.split('.')
        if len(parts)>=2 and parts[0]=='tools' and parts[1] in tools:
            self._navigate_route(*tools[parts[1]])
            page=({'sweep':self.pages['Optimize'],'ai':self.pages['AI Search'],
                'index_shift':self.index_shift_page,'fields':self.pages['Fields'],
                'library':self.pages['Saved work']}.get(target.split('.')[1]))
            leaf='.'.join(parts[2:])
            leaf={'playback':'volume','details':'notes'}.get(leaf,leaf)
            if page is not None and hasattr(page,'select_tool_tab'):page.select_tool_tab(leaf)
            return
        self.status.setText('Select the owning editor for '+target.replace('.',' › '))

    def _open_input_diagnostic(self,target,origin=None):
        """Navigate by explicit object/field identity, retaining the return route."""
        from input_diagnostics import normalize_diagnostic
        from research_simulation import ADAPTERS
        research_engines={engine for engine,_ in ADAPTERS}
        target=normalize_diagnostic(target)
        if self._diagnostic_origin is None:
            self._diagnostic_origin=dict(page=origin,route=self.navigation.currentRow(),
                engine=self.simulation_engines.currentIndex())
        self.diagnostic_back_button.show()
        workspace=target.get('workspace','')
        section=target.get('section','')
        field=target.get('field','')
        section_owner=section.split('.')[0].lower()
        explicit_owner='.' in section or not workspace
        if explicit_owner and (section_owner in research_engines or section_owner in ('settings','structure','device','materials','material','bands','research','studies','research_studies')):
            workspace=section_owner
            target['workspace']=workspace
        if workspace in ('optical','electrical','coupled'):
            self._select_simulation_workflow(workspace)
            page={'optical':self.optical_setup,'electrical':self.electrical_page,'coupled':self.coupled_page}[workspace]
            return page.open_diagnostic(target)
        if workspace in research_engines or workspace in ('bands','research','studies','research_studies'):
            route=10 if workspace in ('photonic_bands','bands') else 11
            self._navigate_route(route)
            return (self.photonic_bands_page if route==10 else self.research_studies_page).open_diagnostic(target)
        if workspace in ('structure','device'):
            page=self.pages['Structure']
            ident=target.get('object_id')
            if ident and not any(row.get('id')==ident for group in ('layers','shapes','contacts','doping_regions') for row in (self.store.device or {}).get(group,[])):
                self.status.setText('The referenced object was removed. Recheck inputs to select a current issue.')
                return False
            self._navigate_route(0)
            if hasattr(page,'open_diagnostic'):
                return page.open_diagnostic(target)
        elif workspace=='settings':
            self._navigate_route(6)
            page=self.pages['Settings']
            page.select_section(section or 'settings.runtime')
            if hasattr(page,'open_diagnostic'):return page.open_diagnostic(target)
        elif workspace in ('materials','material'):
            self._route_setup_action(section or 'materials')
        else:
            self._route_setup_action(section or workspace)
        self.status.setText(target['message'])
        return False

    def _return_from_diagnostic(self):
        token=self._diagnostic_origin
        self._diagnostic_origin=None
        self.diagnostic_back_button.hide()
        if not token:return
        if hasattr(self.pages['Structure'],'return_from_diagnostic'):
            self.pages['Structure'].return_from_diagnostic()
        self._navigate_route(token['route'],token['engine'] if token['route']==2 else None)
        page=token['page']
        if page is not None and hasattr(page,'return_to_issues'):page.return_to_issues()

    def _save_active_workspace(self):
        if self.navigation.currentRow()==2 and self.simulation_engines.currentIndex() in (0,5,6):
            page={0:self.optical_setup,5:self.electrical_page,6:self.coupled_page}[self.simulation_engines.currentIndex()]
            page.save_setup()
        else:self.save_project()

    def _run_setup_mode(self,mode):
        if self.store.busy:return
        page={'optical':self.optical_setup,'electrical':self.electrical_page,'coupled':self.coupled_page}[mode]
        try:
            issues=self.setup_state.validate(mode)
            if issues:
                page.validate_setup()
                return
            options=self.setup_state.job_options(mode)
            if mode=='optical':
                if self.setup_state.get('ui.optical.engine','s4')=='meep':
                    self.fdtd_page._restore()
                    self.fdtd_page.run()
                    return
                policy=self.setup_state.get('ui.optical.outputs.execution_plan','spectrum_only')
                if policy=='fields_only':
                    self.store.start_run('simulation_fields',options)
                else:
                    if policy=='spectrum_then_fields':
                        self._pending_setup_fields=dict(options=copy.deepcopy(options),project=self.store.portable_project())
                    self.store.start_run('simulation',options)
            else:self.store.start_run(mode,options)
        except Exception as exc:
            self._pending_setup_fields=None
            self.show_error('Cannot start '+mode+' simulation: '+str(exc))

    def _setup_run_finished(self,event):
        directory=event.get('directory')
        if self.workspace_profile=='original' and event.get('run_kind') in ('simulation','simulation_fields','fields','fdtd'):
            return
        if self._pending_setup_fields and event.get('run_kind')=='simulation':
            pending=self._pending_setup_fields
            self._pending_setup_fields=None
            if event.get('summary',{}).get('status','complete')=='complete':
                pending['options']['spectrum_id']=Path(directory).name if directory else ''
                self._queued_setup_fields=pending
                self.status.setText('Spectrum saved · optical field stage queued')
                return
        if event.get('run_kind') in ('simulation','simulation_fields','electrical','coupled','fdtd') and directory:
            QTimer.singleShot(0,lambda:self._open_simulation_result(directory,event.get('summary',{})))

    def _setup_busy_changed(self,busy):
        if busy or not self._queued_setup_fields:return
        pending=self._queued_setup_fields;self._queued_setup_fields=None
        def start_fields():
            try:self.store.start_run('simulation_fields',pending['options'],project_snapshot=pending['project'])
            except Exception as exc:self.show_error('Spectrum saved; optical field stage could not start: '+str(exc))
        QTimer.singleShot(0,start_fields)

    def _setup_run_failed(self,error):
        self._pending_setup_fields=None;self._queued_setup_fields=None

    def _open_simulation_result(self,directory,summary=None):
        if directory:
            try:
                self.results_page.load_run(directory)
                self._navigate_route(9)
            except Exception as exc:self.show_error('Could not open results: '+str(exc))

    def _choose_simulation_result(self):
        path=QFileDialog.getExistingDirectory(self,'Open simulation results',str(self.store.library.runs))
        if path:self._open_simulation_result(path)

    def _rerun_simulation_result(self):
        if self.store.busy:
            self.status.setText('Wait for the active calculation before restoring saved inputs.')
            return
        directory=getattr(self.results_page,'directory',None)
        if directory is None:return
        directory=Path(directory)
        try:
            project_path=directory/'project.json'
            if project_path.is_file():
                if not self._confirm_project_replace():return
                self.store.load_project(project_path)
            request_path=directory/'desktop_request.json'
            if request_path.is_file():
                from data_library import read_json
                request=read_json(request_path)
                if request.get('options',{}).get('optical_geometry_source')=='original_tables':
                    self.set_workspace_profile('original')
                    kind=request.get('kind')
                    if kind in ('target','peaks','ai_search'):
                        self._navigate_route(8 if kind=='ai_search' else 3)
                    else:self._navigate_route(2,{'fields':3,'index_shift':2}.get(kind,7))
                    return
            summary=getattr(self.results_page,'summary',{})
            coupled=bool(summary.get('optical',{}).get('optical_enabled',False))
            electrical=bool(summary.get('results'))
            self._select_simulation_workflow('coupled' if coupled else 'electrical' if electrical else 'optical')
        except Exception as exc:self.show_error('Could not restore saved inputs: '+str(exc))

    def _validate_active_workspace(self):
        route=self.navigation.currentRow()
        if route==0:self.pages['Structure'].validate_current()
        elif route==2 and self.simulation_engines.currentIndex() in (0,5,6):
            (self.optical_setup,self.electrical_page,self.coupled_page)[(0,5,6).index(self.simulation_engines.currentIndex())].validate_setup()
        elif route in (10,11):
            (self.photonic_bands_page if route==10 else self.research_studies_page).validate_setup()

    def _idle_workspace_description(self):
        if self.navigation.currentRow()==10:
            return 'Photonic Bands · independent periodic crystal'
        if self.navigation.currentRow()==11:
            return 'Simulation studies · editable setup and paper comparisons'
        return ('Original optical tables · periodic S4 geometry' if self.workspace_profile=='original'
            else 'Device Studio · shared optical and electrical structure')

    def _sync_run_actions(self):
        if not hasattr(self,'run_button'):return
        route=self.navigation.currentRow()
        self.workspace_footer.setVisible(route!=9)
        self.results_page.footer_widget.setVisible(route==9)
        runnable=route in (0,3,8,10,11) or (route==9 and getattr(self.results_page,'directory',None) is not None) or (route==2 and self.simulation_engines.currentIndex()!=4)
        if route==11:
            current=self.research_studies_page.stack.currentWidget()
            runnable=callable(getattr(current,'run',None)) or callable(getattr(current,'run_simulation',None))
        self.run_button.setEnabled(runnable and not self.store.busy)
        labels={0:'Run optical simulation',5:'Run electrical simulation',6:'Run coupled simulation',7:'Run optical simulation'}
        self.run_button.setText(labels.get(self.simulation_engines.currentIndex(),'Run simulation') if route==2 else
            'Rerun / refine mesh' if route==9 else 'Calculate bands' if route==10 else 'Run simulation')
        self.footer_save.setText('Save setup' if route==2 and self.simulation_engines.currentIndex() in (0,5,6) else 'Save project')
        self.footer_save.setVisible(route!=9)
        self.footer_validate.setVisible(route in (10,11) or self.workspace_profile=='device' and (route==0 or (route==2 and self.simulation_engines.currentIndex() in (0,5,6))))
        self.switch_workspace_action.setEnabled(not self.store.busy)
        self.footer_validate.setText('Check inputs' if route in (10,11) else 'Validate' if route==2 else 'Validate device')
        self.footer_validate.setEnabled(not self.store.busy)
        self.stop_button.setEnabled(self.store.busy and callable(getattr(self.store._worker,'cancel',None)))
        self.stop_button.setVisible(self.store.busy)
        self.run_button.setToolTip('Calculate frequency bands for this periodic crystal' if route==10 else
            'Run the active workspace' if runnable else 'Select a simulation or search workspace')
        if not self.store.busy and self.status.text() in (
                'Original optical tables · periodic S4 geometry',
                'Device Studio · shared optical and electrical structure',
                'Simulation studies · editable setup and paper comparisons',
                'Photonic Bands · independent periodic crystal'):
            self.status.setText(self._idle_workspace_description())

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
            if self.workspace_profile=='original' and page_index==0 and hasattr(self,'pages') and 'Structure' in self.pages:
                self.pages['Structure'].tabs.setCurrentIndex(1)
                self.pages['Structure'].advanced_return.hide()
            if self.workspace_profile=='original' and page_index==2 and self.simulation_engines.currentIndex() in (0,5,6):
                self.simulation_engines.setCurrentIndex(7)
            self.stack.setCurrentIndex(page_index)
            if hasattr(self,'appearance_timer'):self.appearance_timer.start(0)

    def _navigate_route(self,page_index,engine_index=None):
        """Open a real workspace, optionally selecting its simulation engine."""
        if int(page_index) in (4,5):
            engine_index=3 if int(page_index)==4 else 4
            page_index=2
        if self.workspace_profile=='original' and page_index==2:
            if engine_index in (5,6):self.set_workspace_profile('device')
            elif engine_index==0 or engine_index is None and self.simulation_engines.currentIndex() in (0,5,6):engine_index=7
        self.navigation.setCurrentRow(int(page_index))
        if page_index == 2 and engine_index is not None and hasattr(self,'simulation_engines'):
            self.simulation_engines.setCurrentIndex(int(engine_index))
        if page_index==2 and hasattr(self,'optical_setup'):
            entry={0:('optical',self.optical_setup),5:('electrical',self.electrical_page),6:('coupled',self.coupled_page)}.get(self.simulation_engines.currentIndex())
            if entry:entry[1].set_mode(entry[0])
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
            from qt_compute import SettingsPage
            defaults=SettingsPage.saved_execution_defaults()
            if defaults:
                fresh.update_settings(defaults.get('settings',{}))
                fresh.update_performance(defaults.get('performance',{}))
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
        page=self.pages.get('Structure')
        if self.workspace_profile=='original':page=page._legacy
        export_button=getattr(page,'export_button',None)
        if export_button is not None and export_button.menu() is not None:
            QTimer.singleShot(0, export_button.showMenu)

    def _simulation_engine_changed(self,engine_index):
        if self.navigation.currentRow() == 2:
            self._sync_tool_navigation(2)
            self._sync_workspace_tabs(2)
            if hasattr(self,'appearance_timer'):self.appearance_timer.start(0)

    def _sync_simulation_local_bars(self,index):
        for bar in self.simulation_local_bars:
            selected=next((i for i in range(bar.count()) if bar.tabData(i)==index),-1)
            with QSignalBlocker(bar):bar.setCurrentIndex(selected)
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
        self._reference_navigation(page_index)
        self.optical_workflow.setVisible(True)
        visible_route = 2 if self.workspace_profile=='device' and page_index in (3,8) else page_index
        if visible_route in self.optical_routes:
            with QSignalBlocker(self.optical_workflow):
                self.optical_workflow.setCurrentIndex(self.optical_routes.index(visible_route))

    def _reference_navigation(self,page_index):
        workflow=page_index==2 and self.simulation_engines.currentIndex() in (0,5,6)
        results=page_index==9
        mode='workflow' if workflow else 'results' if results else 'builder'
        mode=self.workspace_profile+':'+mode
        labels=['Structure','Materials','Simulation','Results','Settings','Help']
        routes=[0,1,2,9,6,7]
        if self.workspace_profile=='original':
            labels=['Structure','Materials','Simulation','Simulation Sweep','AI Search','Settings','Help']
            routes=[0,1,2,3,8,6,7]
        labels.append('Photonic Bands')
        routes.append(10)
        compact=self.width()<1150
        if getattr(self,'_reference_navigation_mode',None)!=mode or getattr(self,'_reference_header_compact',None)!=compact:
            with QSignalBlocker(self.optical_workflow):
                while self.optical_workflow.count():self.optical_workflow.removeTab(0)
                for label in labels:self.optical_workflow.addTab(label)
            self.optical_routes=routes
            self.navigation_layout.removeWidget(self.optical_workflow)
            self.chrome.layout().removeWidget(self.optical_workflow)
            self.navigation_layout.removeWidget(self.chrome.file_button)
            self.chrome.layout().removeWidget(self.chrome.file_button)
            if compact:self.navigation_layout.insertWidget(0,self.optical_workflow,1)
            else:self.chrome.layout().insertWidget(4,self.optical_workflow)
            self.chrome.layout().insertWidget(4 if compact else 5,self.chrome.file_button)
            self._reference_navigation_mode=mode
            self._reference_header_compact=compact
        self.navigation_bar.setVisible(compact or self._diagnostic_origin is not None)
        self.project_header.setVisible(False)
        self.chrome.title.setText('Original Optical Studio' if self.workspace_profile=='original' else 'Optical Design Studio')
        self.workspace_context.setText('Simulation results · Electrical + Optical' if results else 'Shared builder + Canvas tools' if page_index==0 else '')
        icon_names={'Structure':'structure','Materials':'materials','Simulation':'simulation','Results':'results',
            'Simulation Sweep':'sweep','AI Search':'search','Settings':'settings','Help':'help','Photonic Bands':'simulation'}
        for index,label in enumerate(labels):self.optical_workflow.setTabIcon(index,reference_icon(icon_names[label],COLORS[theme_manager().mode]['text']))
        self.optical_workflow.setIconSize(QSize(18,18))
        # Resize can rebuild the compact header without a route-change signal.
        # Keep its selection aligned with the page that is already displayed.
        visible_route=2 if page_index==11 or self.workspace_profile=='device' and page_index in (3,8) else page_index
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
        self._reference_navigation(self.navigation.currentRow())
        self.workspace_context.setVisible(not compact_header)
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
            if not page.isVisible():continue
            if page is getattr(self, 'photonic_bands_page', None):
                # The scene, object inspector and setup steps manage their own
                # proportions. Generic form wrapping truncates their inputs.
                if hasattr(page, 'adapt_layout'):
                    page.adapt_layout()
                continue
            if page is getattr(self, 'research_studies_page', None):
                page.adapt_layout()
                continue
            if page.property('referenceWorkspace'):
                page.layout().setContentsMargins(8,6,8,6)
                if hasattr(page,'adapt_layout'):page.adapt_layout()
                continue
            density=(manager.effective_scale,self.width()<1100,manager.adaptive)
            if getattr(page,'_applied_layout_density',None)==density:continue
            page._applied_layout_density=density
            # Splitters manage their own responsive sizes. Do not reassign
            # hidden result panels or erase user-adjusted proportions.
            if hasattr(page,'builder_splitter'):
                orientation = Qt.Orientation.Vertical if manager.adaptive and self.width() < 1100 else Qt.Orientation.Horizontal
                page.layer_list.setMinimumHeight(180 if orientation == Qt.Orientation.Vertical else 0)
                if page.builder_splitter.orientation() != orientation:
                    page.builder_splitter.setOrientation(orientation)
                    page.builder_splitter.setSizes([420,420,540] if orientation == Qt.Orientation.Vertical else list(BUILDER_PROPORTIONS))
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
        if hasattr(self,'simulation_engines'):self._reference_navigation(self.navigation.currentRow())
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
        elif self.isVisible() and getattr(self,'_construction_complete',False) and not getattr(self,'_startup_painted',False):
            self._startup_painted=True
            # Wait for all child painters and the backing store to finish.
            QTimer.singleShot(0,self.startupPainted.emit)

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
            self._flush_research_drafts()
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
            self._diagnostic_origin=None
            self.diagnostic_back_button.hide()
            for page in (self.photonic_bands_page,self.research_studies_page):page.refresh()
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
        self.setWindowTitle('Optical Design Studio · '+('Original Optical Studio' if self.workspace_profile=='original' else 'Device Studio'))

    def _confirm_project_replace(self):
        self._flush_research_drafts()
        if self.store.project()==self._saved_project:
            return True
        answer=QMessageBox.question(self,'Save project changes?',
            'Save changes to the current project before replacing it? Automatic session recovery will be replaced by the new project.',
            QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        return self.save_project() if answer==QMessageBox.StandardButton.Save else answer==QMessageBox.StandardButton.Discard

    def _flush_research_drafts(self):
        for page in (self.photonic_bands_page,self.research_studies_page):
            page.flush_draft()

    def _open_band_reference(self,identity,run=False):
        """Paper library opens the independent editor without replacing a device."""
        self._navigate_route(10)
        page=self.photonic_bands_page
        index=page.benchmark_picker.findData(identity)
        if index<0:return
        page.benchmark_picker.setCurrentIndex(index)
        if run:
            page.run_benchmark()
        else:
            page.duplicate_benchmark()
            page.show_stage('unit')

    def _open_research_reference(self,case):
        """Opening a full reference device uses the normal project save flow."""
        if self.store.busy:
            self.status.setText('Wait for the active calculation before opening another device.')
            return False
        if not self._confirm_project_replace():return False
        try:
            project=copy.deepcopy(case['project']);kind=case['kind'];options=copy.deepcopy(case['options'])
            project.setdefault('desktop_search',{})[kind]=options
            self.store.load_project(project)
            if kind in ('electrical','coupled'):
                self.set_workspace_profile('device')
                self._navigate_route(2,5 if kind=='electrical' else 6)
            elif kind in ('simulation','fields','simulation_fields','index_shift'):
                self.set_workspace_profile('original' if options.get('optical_geometry_source')=='original_tables' else 'device')
                route={'fields':3,'simulation_fields':7 if self.workspace_profile=='original' else 0,'index_shift':2}.get(kind,7 if self.workspace_profile=='original' else 0)
                self._navigate_route(2,route)
            else:
                self._navigate_route({'peaks':3,'target':3,'ai_search':8}.get(kind,2))
            self.status.setText('Editable paper reference: '+case.get('label',kind))
            return True
        except Exception as exc:
            self.show_error('Could not open the editable reference: '+str(exc))
            return False

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
        if self.navigation.currentRow()==9:
            self.results_page.footer_label.setText('Check: '+str(error)[-500:])
            self.results_page.footer_label.setToolTip(str(error))

    def show_finished(self,event):
        summary=event.get('summary',{})
        state=str(summary.get('status',event.get('status','complete')))
        warnings=summary.get('warnings',[])
        title={'simulation':'Optical spectrum','simulation_fields':'Optical E/H fields',
            'electrical':'Electrical simulation','coupled':'Coupled simulation'}.get(
                event.get('run_kind'),str(event.get('run_kind','Calculation')).replace('_',' ').title())
        if state.lower() in ('error','failed','cancelled') or warnings:
            self.status.setText(f"{title}: {state}" +
                                (' with warnings' if warnings else ''))
            if warnings:self.status.setToolTip('\n'.join(map(str,warnings)))
        else:
            self.notify_action(title+' complete','Results saved to your library.')
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
            self._flush_research_drafts()
            self.store._autosave()
        except Exception as exc:
            self.show_error('Could not save the session: '+str(exc)+'. Save a portable project before closing.')
            event.ignore()
            return
        self.preferences.setValue('geometry',self.saveGeometry())
        self.preferences.setValue('page',self.navigation.currentRow())
        event.accept()


class DesktopStartup(QObject):
    """Keep a painted loading surface while complete GUI sections are built."""
    def __init__(self,application,store,profile,args,library):
        super().__init__(application)
        from qt_workspace_start import WorkspaceLoadingWindow
        self.application=application;self.args=args;self.library=library
        self.cancelled=False;self.finished=False;self._started=False
        self.loading=WorkspaceLoadingWindow(profile)
        self.window=OpticalStudio(store,workspace_profile=profile,defer_setup=True)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(10)
        self.timer.timeout.connect(self._advance)
        self.loading.cancelled.connect(self.cancel)
        self.loading.installEventFilter(self)
        self.window.startupPainted.connect(self._painted)
        self.application.aboutToQuit.connect(self._save_preferences)
        self.loading.show();self.loading.raise_();self.loading.activateWindow()

    def eventFilter(self,watched,event):
        if watched is self.loading and event.type()==QEvent.Type.Paint and not self._started:
            self._started=True
            # Start after the loading widget and all of its children paint.
            self.timer.start()
        return super().eventFilter(watched,event)

    def _advance(self):
        if self.cancelled or self.finished:return
        try:
            stage=self.window.advance_startup()
            if stage is not None:
                self.loading.set_stage(stage)
                self.timer.start()
                return
            if self.args.project:self.window._project_file_saved(self.args.project)
            from crash_reporting import install_crash_reporting
            self.window._crash_reporting=install_crash_reporting(self.library,self.window.show_error)
            if self.args.page:
                index=next(i for i in range(self.window.navigation.count()) if self.window.navigation.item(i).text()==self.args.page)
                self.window._navigate_route(index)
            self.loading.set_stage('Rendering your workspace…')
            self.window.show()
            self.application.setQuitOnLastWindowClosed(True)
        except Exception as exc:
            self.timer.stop()
            QMessageBox.critical(self.loading,'Cannot open workspace',str(exc))
            self.cancel()

    def _painted(self):
        if self.cancelled or self.finished:return
        self.finished=True
        self.loading.shutdown_without_cancel()
        self.window.raise_();self.window.activateWindow()
        from desktop_runtime import startup_addon_results
        if startup_addon_results:
            messages=[f"{result['id']}: "+('installed and verified' if result['status']=='activated'
                else 'installation failed; previous version preserved') for result in startup_addon_results]
            self.window.status.setText(' · '.join(messages))
            self.window.status.setToolTip('\n'.join(str(result.get('error','')) for result in startup_addon_results))

    def _save_preferences(self):
        if not self.finished or self.cancelled:return
        self.window.preferences.setValue('geometry',self.window.saveGeometry())
        self.window.preferences.setValue('page',self.window.navigation.currentRow())
        self.window.preferences.sync()

    def cancel(self):
        if self.cancelled or self.finished:return
        self.cancelled=True;self.timer.stop()
        if self.window._initialization is not None:
            self.window._initialization.close();self.window._initialization=None
        self.window.hide();self.window.deleteLater()
        self.loading.shutdown_without_cancel()
        self.application.quit()

    def dispose(self):
        """Release the native widgets before QApplication/interpreter teardown."""
        from PyQt6 import sip
        self.timer.stop()
        application=self.application
        application.aboutToQuit.disconnect(self._save_preferences)
        window,loading=self.window,self.loading
        self.window=self.loading=None
        if window is not None and not sip.isdeleted(window):
            if window._initialization is not None:
                window._initialization.close();window._initialization=None
            window.hide();window.deleteLater()
        if loading is not None and not sip.isdeleted(loading):
            loading.shutdown_without_cancel()
        self.deleteLater()
        # The event loop has ended, so queued QWidget destruction needs an
        # explicit flush while its QApplication and native services are alive.
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.application=None


def main(argv=None):
    import multiprocessing
    multiprocessing.freeze_support()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--theme',choices=['dark','light'])
    parser.add_argument('--look',choices=list(LOOKS),help='Choose B or frosted glass in light or dark mode.')
    parser.add_argument('--project',type=Path)
    parser.add_argument('--library',type=Path)
    parser.add_argument('--no-restore',action='store_true')
    parser.add_argument('--workspace',choices=['ask','device','original'],help='Choose Device Studio, Original Optical Studio, or show the startup chooser.')
    parser.add_argument('--update-ack', type=Path)
    parser.add_argument('--page', choices=['Structure','Materials','Simulate','Optimize','Fields','Saved work','Settings','About','AI Search','Results'])
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
    from qt_workspace_start import choose_startup_workspace
    def acknowledge_opened_ui():
        # The chooser is a usable startup window. Update/restart helpers must
        # not time out while the user is deciding which workspace to open.
        from application_restart import acknowledge_restart
        acknowledge_restart()
        if args.update_ack:
            from update_install import acknowledge_startup
            acknowledge_startup(args.update_ack)
    QTimer.singleShot(0,acknowledge_opened_ui)
    # Closing the chooser must not enqueue application exit before the chosen
    # main window is constructed (the chooser is initially the only window).
    application.setQuitOnLastWindowClosed(False)
    profile=choose_startup_workspace(args.workspace,preferences())
    if profile is None:return 0
    # Retain the coordinator for the application lifetime. No partial main
    # window is shown, and each section is built on the GUI thread.
    startup=DesktopStartup(application,store,profile,args,selected_library)
    application._desktop_startup=startup
    try:
        return application.exec()
    finally:
        startup.dispose()
        application._desktop_startup=None


if __name__=='__main__':
    raise SystemExit(main())
