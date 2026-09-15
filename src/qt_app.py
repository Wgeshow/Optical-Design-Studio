"""Launch the native PyQt6 Optical Studio desktop."""
import argparse
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
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QApplication,QMainWindow,QWidget,QHBoxLayout,QVBoxLayout,
    QFrame,QLabel,QListWidget,QStackedWidget,QComboBox,QFileDialog,QMessageBox,QProgressBar,QToolButton,QTabWidget)

from qt_common import theme_manager,button,note,scroll,preferences,COLORS
from qt_icons import navigation_icon
from qt_core import ProjectStore,BackendWorker
from data_library import DataLibrary
from qt_chrome import WindowChrome, WindowsCustomFrame
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
        self._closing=False
        self._updates_closing=False
        self.setWindowTitle('Optical Design Studio')
        native_frame = False
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowMinMaxButtonsHint | Qt.WindowType.WindowCloseButtonHint)
        self.setMinimumSize(640,480)
        self.resize(1460,960)
        central=QWidget()
        root=QVBoxLayout(central)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(0)
        self.chrome=WindowChrome(self,self.open_project,self.save_project,
                                 lambda:self.navigation.setCurrentRow(6), native_frame=native_frame)
        root.addWidget(self.chrome)
        body=QHBoxLayout()
        body.setContentsMargins(0,0,0,0)
        body.setSpacing(0)
        root.addLayout(body,1)
        sidebar=QFrame()
        self.sidebar = sidebar
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(205)
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
        self.navigation.addItems(['Structure','Materials','Simulate','Optimize','Fields','Saved work','Settings','About'])
        side.addWidget(self.navigation,1)
        side.addWidget(note('Appearance'))
        self.theme_select=QComboBox()
        self.theme_select.setObjectName('themeSelector')
        self.theme_select.addItem('Dark mode','dark')
        self.theme_select.addItem('Light mode','light')
        self.theme_select.setCurrentIndex(self.theme_select.findData(theme_manager().mode))
        self.theme_select.currentIndexChanged.connect(lambda:theme_manager().apply(self.theme_select.currentData()))
        theme_manager().changed.connect(self.refresh_theme)
        side.addWidget(self.theme_select)
        side.addSpacing(12)
        location=note('Saved locally\nYour data stays with the project library.')
        location.setToolTip(str(self.store.library.root))
        side.addWidget(location)
        self.sidebar_details = [location, self.theme_select] + sidebar.findChildren(QLabel)
        body.addWidget(sidebar)
        workspace=QWidget()
        self.workspace=workspace
        content=QVBoxLayout(workspace)
        content.setContentsMargins(0,0,0,0)
        content.setSpacing(0)
        self.stack=QStackedWidget()
        from qt_structure import StructurePage
        from qt_materials import MaterialsPage
        from qt_library import LibraryPage
        from qt_compute import SimulationPage,OptimizePage,FieldsPage,SettingsPage
        from qt_about import AboutPage
        from qt_fdtd import FDTDPage
        classes=[StructurePage,MaterialsPage,SimulationPage,OptimizePage,FieldsPage,LibraryPage,SettingsPage,AboutPage]
        self.pages={}
        for index,cls in enumerate(classes):
            page=cls(self.store)
            page.setObjectName('page')
            page.layout().setContentsMargins(*( (34,28,34,28) if cls is AboutPage else (20,14,20,14) ))
            self.pages[self.navigation.item(index).text()]=page
            if cls is SimulationPage:
                self.simulation_engines = QTabWidget()
                self.fdtd_page = FDTDPage(self.store)
                self.simulation_engines.addTab(scroll(page), 'S4 · RCWA')
                self.simulation_engines.addTab(scroll(self.fdtd_page), 'MEEP · FDTD')
                self.stack.addWidget(self.simulation_engines)
            else:
                self.stack.addWidget(scroll(page))
        self.pages['About'].idle.connect(self._close_after_updates)
        self.pages['Settings'].addons_panel.idle.connect(self._close_after_updates)
        self.pages['Settings'].addons_panel.restart_requested.connect(self._restart_for_addons)
        self.pages['Settings'].addons_panel.runtime_changed.connect(self.fdtd_page.refresh_runtime)
        content.addWidget(self.stack,1)
        footer=QFrame()
        footer.setObjectName('workspaceFooter')
        footer_layout=QHBoxLayout(footer)
        footer_layout.setContentsMargins(24,10,24,12)
        self.status=note('Ready · Applied Structure edits are shared across every workflow.')
        self.status.setObjectName('globalStatus')
        self.progress_bar=QProgressBar()
        self.progress_bar.setMaximumWidth(220)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        self.stop_button=button('Stop',self.store.cancel)
        self.stop_button.hide()
        footer_layout.addWidget(self.status,1)
        footer_layout.addWidget(self.progress_bar)
        footer_layout.addWidget(self.stop_button)
        content.addWidget(footer)
        body.addWidget(workspace,1)
        self.setCentralWidget(central)
        self._windows_frame = WindowsCustomFrame(self)
        self.structure_notice=StructureNotice(workspace)
        self._structure_snapshot=self.structure_signature()
        self.navigation.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.navigation.setCurrentRow(int(self.preferences.value('page',0))%len(classes))
        self.store.changed.connect(self.structure_changed)
        self.store.busy_changed.connect(self.busy_changed)
        self.store.progress.connect(self.show_progress)
        self.store.run_failed.connect(self.show_error)
        self.store.run_finished.connect(self.show_finished)
        self.store.message.connect(self.status.setText)
        self.store.task_failed.connect(lambda name,error:self.show_error(error))
        self.store.task_finished.connect(lambda name,result:self.status.setText(name+' completed.'))
        if self.store.restore_error:
            self.status.setText(self.store.restore_error)
        geometry=self.preferences.value('geometry')
        if geometry is not None:
            self.restoreGeometry(geometry)
        theme_manager().apply(theme_manager().mode,persist=False)
        self.appearance_timer = QTimer(self)
        self.appearance_timer.setSingleShot(True)
        self.appearance_timer.setInterval(120)
        self.appearance_timer.timeout.connect(self.adapt_interface)
        theme_manager().appearance_changed.connect(self.adapt_interface)
        self.adapt_interface()

    def toggle_sidebar(self, checked):
        self.sidebar_collapsed = not self._sidebar_compact
        self._sidebar_manual = True
        self.preferences.setValue('sidebar_collapsed', self.sidebar_collapsed)
        self.preferences.sync()
        self.adapt_interface()

    def adapt_interface(self):
        manager = theme_manager()
        manager.set_window_width(self.width())
        compact = self.sidebar_collapsed or (manager.adaptive and self.width() < 1000 and not getattr(self, '_sidebar_manual', False))
        self._sidebar_compact = compact
        self.sidebar_toggle.setChecked(compact)
        self.sidebar_toggle.setText('›' if compact else '‹')
        self.sidebar_toggle.setAccessibleName('Expand sidebar' if compact else 'Collapse sidebar')
        self.sidebar_toggle.setToolTip('Expand sidebar' if compact else 'Collapse sidebar')
        self.sidebar.setFixedWidth(60 if compact else max(156, round(180 * manager.effective_scale)))
        icon_size = max(18, round(22 * manager.effective_scale))
        self.navigation.setIconSize(QSize(icon_size, icon_size))
        self.sidebar.layout().setContentsMargins(3 if compact else 10, 8, 3 if compact else 10, 8)
        labels = ['Structure','Materials','Simulate','Optimize','Fields','Saved work','Settings','About']
        for index, label in enumerate(labels):
            item = self.navigation.item(index)
            item.setText('' if compact else label)
            item.setIcon(navigation_icon(label, COLORS[manager.mode]['accent']))
            item.setToolTip(label)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, label)
        for widget in self.sidebar_details:
            widget.setVisible(not compact)
        from PyQt6.QtWidgets import QFormLayout, QTableWidget
        for page in self.pages.values():
            margin = max(8, round(16 * manager.effective_scale))
            page.layout().setContentsMargins(margin, margin, margin, margin)
            page.layout().setSpacing(max(5, round(8 * manager.effective_scale)))
            for form in page.findChildren(QFormLayout):
                form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
                form.setVerticalSpacing(max(5, round(8 * manager.effective_scale)))
                form.setHorizontalSpacing(max(8, round(12 * manager.effective_scale)))
            for table in page.findChildren(QTableWidget):
                table.verticalHeader().setDefaultSectionSize(max(table.fontMetrics().height()+8, round(30 * manager.effective_scale)))

    def refresh_theme(self,mode):
        with QSignalBlocker(self.theme_select):
            self.theme_select.setCurrentIndex(self.theme_select.findData(mode))
        for index, label in enumerate(('Structure','Materials','Simulate','Optimize','Fields','Saved work','Settings','About')):
            self.navigation.item(index).setIcon(navigation_icon(label, COLORS[mode]['accent']))
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
        self.structure_notice.summary.setText(
            f'{max(0,len(names)-2)} finite layers · {len(self.store.patterns)} regions · '
            f'{self.store.settings["ax_um"]:g} × {self.store.settings["ay_um"]:g} µm\n'
            'Applied to every workflow.')
        self.structure_notice.setToolTip(visible)
        self.position_structure_notice()
        self.structure_notice.show()
        self.structure_notice.raise_()
        self.structure_notice.timer.start()

    def position_structure_notice(self):
        notice=self.structure_notice
        notice.setFixedWidth(min(440,max(240,self.workspace.width()-32)))
        notice.adjustSize()
        notice.move(max(8,self.workspace.width()-notice.width()-20),10)

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
        path,_=QFileDialog.getOpenFileName(self,'Open portable project','','S4 project (*.json)')
        if path:
            try:
                self.store.load_project(path)
                self.status.setText('Project opened. All workflows use this Structure.')
            except Exception as exc:
                self.show_error(str(exc))

    def save_project(self):
        path,_=QFileDialog.getSaveFileName(self,'Save portable project','s4_project.json','S4 project (*.json)')
        if path:
            try:
                result=self.store.save_project(path)
                self.status.setText('Saved project and optical constants: '+result)
            except Exception as exc:
                self.show_error(str(exc))

    def busy_changed(self,busy):
        self.progress_bar.setVisible(busy)
        self.stop_button.setVisible(busy)
        self.stop_button.setEnabled(isinstance(self.store._worker,BackendWorker))
        if busy:
            self.progress_bar.setRange(0,0)
            self.status.setText('Working in the background. Results are saved to your library.')
        elif self._closing:
            QTimer.singleShot(0,self.close)

    def show_progress(self,event):
        if event.get('total') and event.get('done') is not None:
            self.progress_bar.setRange(0,int(event['total']))
            self.progress_bar.setValue(int(event['done']))
            self.status.setText(f"{event['done']:,} / {event['total']:,} spectrum points")
        elif event.get('text'):
            self.status.setText(str(event['text']))

    def show_error(self,error):
        self.status.setText('Check: '+str(error)[-800:])
        self.status.setToolTip(str(error))

    def show_finished(self,event):
        summary=event.get('summary',{})
        self.status.setText(f"{event.get('run_kind','Calculation').title()}: {summary.get('status','complete')} · Saved to your library.")

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
    parser.add_argument('--project',type=Path)
    parser.add_argument('--library',type=Path)
    parser.add_argument('--no-restore',action='store_true')
    parser.add_argument('--update-ack', type=Path)
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
    if args.theme:
        theme_manager().apply(args.theme)
    else:
        theme_manager().apply(theme_manager().mode,persist=False)
    store=ProjectStore(DataLibrary(selected_library),restore=not args.no_restore)
    if args.project:
        store.load_project(args.project)
    window=OpticalStudio(store)
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
