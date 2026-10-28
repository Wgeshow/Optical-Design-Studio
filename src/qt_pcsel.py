"""Laser and PCSEL simulation workspace."""
from pathlib import Path
from dataclasses import asdict
from copy import deepcopy
from datetime import datetime, timezone
import csv
import io
import json
import uuid
import numpy as np
from PyQt6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QDoubleSpinBox,
 QSpinBox,QPushButton,QGroupBox,QTabWidget,QComboBox,QPlainTextEdit,QScrollArea,QFileDialog,
 QTableWidget,QTableWidgetItem,QHeaderView,QFrame,QGridLayout,QSizePolicy,QToolButton,QMenu)
from PyQt6.QtCore import Qt, QSignalBlocker
from PyQt6.QtGui import QColor, QPainter, QPen, QFont
from qt_common import theme_manager, PlotWidget
from pcsel_design import PCSELDesign
from laser_model import LaserParameters,solve_laser
from comsol_results import load_comsol_power_results,merge_comsol_power


class LaserModelDiagram(QWidget):
    """Input-model context; no unsolved spatial or transient data are displayed."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(120, 240)
        self.setAccessibleName('Steady-state laser estimate: drive, carriers, photons, output light and temperature feedback')
        theme_manager().changed.connect(self.update)

    def paintEvent(self, event):
        from qt_common import COLORS
        from PyQt6.QtCore import QRectF, QPointF
        c = COLORS[theme_manager().mode]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(c['panel']))
        compact=self.width()<480
        canvas_width,canvas_height=(300,360) if compact else (590,390)
        scale = min(self.width()/canvas_width, self.height()/canvas_height)
        painter.translate((self.width()-canvas_width*scale)/2, (self.height()-canvas_height*scale)/2)
        painter.scale(scale, scale)
        painter.setFont(QFont('Segoe UI', 12))
        def arrow(x1, y1, x2, y2):
            painter.setPen(QPen(QColor(c['muted']), 1.6))
            painter.drawLine(QPointF(x1,y1),QPointF(x2,y2))
            import math
            angle=math.atan2(y2-y1,x2-x1)
            for offset in (-.45,.45):
                painter.drawLine(QPointF(x2,y2),QPointF(x2-8*math.cos(angle+offset),y2-8*math.sin(angle+offset)))
        def box(x,y,w,h,text,color):
            painter.setPen(QPen(QColor(color),1.8))
            fill=QColor(color);fill.setAlpha(24);painter.setBrush(fill)
            rect=QRectF(x,y,w,h);painter.drawRoundedRect(rect,9,9)
            painter.setPen(QColor(c['text']));painter.drawText(rect,Qt.AlignmentFlag.AlignCenter,text)
        if compact:
            painter.setFont(QFont('Segoe UI',10))
            arrow(72,80,72,130);arrow(125,160,175,160);arrow(228,190,228,245)
            arrow(72,190,72,245);arrow(125,275,228,190)
            box(20,20,105,60,'Drive current\nI (mA)','#3b82f6')
            box(20,130,105,60,'Carriers\nN (cm⁻³)','#10a78a')
            box(175,130,105,60,'Photons\nS','#6478db')
            box(175,245,105,60,'Output light\nP (mW)','#9861c9')
            box(20,245,105,60,'Temperature\nT (K)','#d59a32')
            painter.setPen(QColor(c['muted']));painter.setFont(QFont('Segoe UI',9))
            painter.drawText(QRectF(123,135,54,22),Qt.AlignmentFlag.AlignCenter,'Gain')
            painter.drawText(QRectF(40,320,220,25),Qt.AlignmentFlag.AlignCenter,'Lumped thermal feedback')
        else:
            arrow(115,95,115,153);arrow(180,190,245,190);arrow(365,190,425,190)
            arrow(115,226,115,290);arrow(175,325,305,325);arrow(305,325,305,226)
            box(50,25,130,70,'Drive current\nI (mA)','#3b82f6')
            box(45,153,135,74,'Carriers\nN (cm⁻³)','#10a78a')
            box(245,153,120,74,'Photons\nS','#6478db')
            box(425,153,125,74,'Output light\nP (mW)','#9861c9')
            box(50,290,125,70,'Temperature\nT (K)','#d59a32')
            painter.setPen(QColor(c['muted']));painter.setFont(QFont('Segoe UI',10))
            painter.drawText(QRectF(175,160,75,25),Qt.AlignmentFlag.AlignCenter,'Gain')
            painter.drawText(QRectF(181,335,170,25),Qt.AlignmentFlag.AlignCenter,'Thermal feedback')
        painter.end()


class _PCSELPlot(PlotWidget):
    """Retain the laser page's source-figure API on the shared native viewer."""
    def draw_idle(self):
        self.draw_figure(self.figure)


class WorkflowTabs(QTabWidget):
    def __init__(self):
        super().__init__()
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.TextElideMode.ElideNone)
        self.tabBar().setMinimumHeight(44)
        self.setStyleSheet('QTabBar::tab { min-height:24px; padding:8px 16px; }')

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.tabBar().setFixedWidth(max(100,self.width()-2))
        self.tabBar().setExpanding(True)


class PCSELPage(QWidget):
    def __init__(self,store):
        super().__init__(); self.store=store; self.last_result=None; self._results_stale=False
        self.setObjectName('laserWorkspace')
        root=QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        # The application chrome already identifies this as the Laser / PCSEL
        # workspace.  Starting with the workflow strip keeps the complete
        # instrument visible in one desktop viewport, like the approved design.
        self.run_state=QLabel('●  READY'); self.run_state.setObjectName('runState'); self.run_state.hide()
        self.tabs=WorkflowTabs(); self.tabs.setObjectName('laserWorkflowTabs'); self.tabs.setDocumentMode(True); root.addWidget(self.tabs,1)
        # Controls are created by the detail pages before the dashboard begins its
        # first calculation.  The first page mirrors the integrated instrument view,
        # while the remaining pages provide room for detailed inspection/editing.
        dashboard=self.setup_tab()
        optical=self.optical_tab();electrical=self.electrical_tab();li=self.li_tab()
        modulation=self.modulation_tab();thermal=self.thermal_tab();comsol=self.mode_tab();report=self.report_tab()
        self.device_store=self.create_device_store(store)
        from qt_device_builder import DeviceBuilderPage
        self.device_builder=DeviceBuilderPage(self.device_store,laser=True)
        self.device_builder.select_layer('Photonic crystal')
        self.device_builder.cells.setCurrentIndex(2)
        device=QWidget();device_layout=QVBoxLayout(device);form=QFormLayout();device_layout.addLayout(form)
        self.pc_layer=QComboBox();self.active_layer=QComboBox()
        names=self.device_store.layers.Name.tolist()[1:-1]
        for combo in (self.pc_layer,self.active_layer):combo.addItems(names)
        self.pc_layer.setCurrentText('Photonic crystal');self.active_layer.setCurrentText('Quantum well')
        self.device_width=self.spin(100,.01,1e5,1,' µm',2);self.device_height=self.spin(100,.01,1e5,1,' µm',2)
        for label,w in [('PC layer',self.pc_layer),('Active layer',self.active_layer),('Active width',self.device_width),('Active height',self.device_height)]:form.addRow(label,w)
        assign=QPushButton('Apply device geometry');assign.setProperty('primary',True);assign.clicked.connect(self.apply_device_geometry);device_layout.addWidget(assign)
        help=QLabel('Active volume = width × height × selected active-layer thickness. Optical Q and confinement must be supplied independently. This editable stack is an illustrative design, not a validated paper reproduction.');help.setWordWrap(True);help.setObjectName('muted');device_layout.addWidget(help);device_layout.addStretch()
        self.device_builder.tabs.addTab(self.device_builder._scroll(device),'Device')
        self.device_builder.continue_requested.connect(lambda:self.tabs.setCurrentIndex(1))
        self.device_store.changed.connect(self.sync_device_geometry)
        for page,name in [(self.device_builder,'Device Setup'),(optical,'Optical Modes'),(electrical,'Electrical && Gain'),
                          (comsol,'COMSOL'),(thermal,'Thermal'),(modulation,'Modulation · optional'),
                          (self.wrap_page(dashboard),'Results'),(report,'Report')]:self.tabs.addTab(page,name)
        self.results_index=6
        # Keep the detailed L-I figure accessible within Results without adding
        # a second top-level performance stage.
        self.detail_results=li;li.hide();li.setParent(dashboard)
        self.workflow_footer=QWidget();bar=QHBoxLayout(self.workflow_footer);root.addWidget(self.workflow_footer)
        back=QPushButton('← Back');back.clicked.connect(lambda:self.tabs.setCurrentIndex(max(0,self.tabs.currentIndex()-1)))
        self.continue_button=QPushButton('Continue →');self.continue_button.setProperty('primary',True)
        self.continue_button.clicked.connect(lambda:self.tabs.setCurrentIndex(min(self.tabs.count()-1,self.tabs.currentIndex()+1)))
        bar.addWidget(back);bar.addStretch();bar.addWidget(self.continue_button)
        self.tabs.currentChanged.connect(lambda i:self.continue_button.setText('Continue to '+self.tabs.tabText(min(i+1,self.tabs.count()-1))+' →'))
        self.tabs.currentChanged.connect(lambda i:self.workflow_footer.setVisible(i!=0))
        self.workflow_footer.hide()
        theme_manager().changed.connect(self.retheme)
        self.sync_device_geometry()
        self.solver_status.setText('Optical parameters: supplied by user\n\nS4 / Meep: not run\n\nCOMSOL: no results imported\n\nSteady-state estimate: ready')
        self.status.setText('Configure inputs, then run the analytical laser model in Results.')
        self.report.setPlainText('No laser simulation has been run. Results and provenance will appear here.')
        self.retheme()
        self._install_clean_workbench(root, optical, electrical, modulation, thermal, device)
        self._install_laser_journey()
        self._draft_loading=False
        self._draft_controls={name:value for name,value in vars(self).items()
            if isinstance(value,(QDoubleSpinBox,QSpinBox,QComboBox)) and name not in ('result_selector','parameter_selector')}
        self._default_draft=self.draft()
        self._restore_project_draft()
        if store is not None: store.changed.connect(self._project_draft_changed)
        self.device_store.changed.connect(self.flush_draft)
        for control in self._draft_controls.values():
            (control.currentIndexChanged if isinstance(control,QComboBox) else control.valueChanged).connect(self.flush_draft)

    def draft(self):
        return dict(device=self.device_store._project_payload(),controls={name:
            control.currentText() if isinstance(control,QComboBox) else control.value()
            for name,control in self._draft_controls.items()})

    def flush_draft(self,*_):
        if not self._draft_loading and self.last_result is not None and hasattr(self,'laser_run_note'):
            self.laser_run_note.setText('Inputs changed · previous analytical results are stale. Run again to update them.')
            self.laser_result_note.setText('Inputs changed · displayed analytical results belong to the previous inputs. Run again to update them.')
            if not self._results_stale:
                self.report.setPlainText('INPUTS CHANGED: this report retains the previous calculation inputs. Run again to update it.\n\n'+self.report.toPlainText())
            self._results_stale=True
        if self._draft_loading or self.store is None:return
        if getattr(self.store,'study_navigation_enabled',False) and self.store.active_study!='lumped_laser':return
        from copy import deepcopy
        namespace=deepcopy(self.store.search_state.get('research_workspaces',{}))
        namespace.setdefault('schema_version',1)
        namespace['lumped_laser']=self.draft()
        self.store.save_search('research_workspaces',namespace)

    def _restore_project_draft(self):
        from copy import deepcopy
        if self.store is None:return
        value=deepcopy(self.store.search_state.get('research_workspaces',{}).get('lumped_laser',self._default_draft))
        self._draft_loading=True
        try:
            self.device_store.load_project(value['device'],autosave=False)
            for name,value in value.get('controls',{}).items():
                control=self._draft_controls.get(name)
                if isinstance(control,QComboBox):control.setCurrentText(str(value))
                elif control is not None:control.setValue(value)
        finally:self._draft_loading=False

    def _project_draft_changed(self,reason):
        if reason not in ('project','study'):return
        if reason=='project':self._clear_results()
        if (getattr(self.store,'study_navigation_enabled',False)
                and self.store.active_study!='lumped_laser'):return
        self._restore_project_draft()

    def _clear_results(self):
        # Project replacement must not retain another project's calculation or
        # external overlay. A normal study switch keeps this document's results.
        self.last_result=None;self._comsol_imported=None;self._results_stale=False
        self.result_export_button.setEnabled(False)
        self.report.setPlainText('No laser simulation has been run for this project.')
        self.status.setProperty('error',False);self.status.setText('Configure inputs, then run the analytical laser model.')
        self.run_state.setText('●  READY');self.run_state.setStyleSheet('')
        self.laser_run_note.setText('Not run · no analytical result is available for this project.')
        self.laser_result_note.setText('No analytical calculation has been run for this project. External power imports have been cleared.')
        self.laser_check_note.setText('Inputs have not been checked.')
        self._laser_diagnostic=None;self.laser_issue_button.hide()
        self.quick.clear();self.modulation_summary.clear();self.thermal_summary.clear()
        self.mode_table.setRowCount(0)
        for card in self.dashboard_kpis:
            card.setText(card.text().split('\n',1)[0]+'\n—')
        self.overview_status.setText('RESULT\nAwaiting simulation')
        self.solver_status.setText('Optical parameters: supplied by user\n\nS4 / Meep: not run\n\nCOMSOL: no results imported\n\nSteady-state estimate: ready')
        for plot in self.findChildren(_PCSELPlot):plot.clear()

    def _install_clean_workbench(self, root, optical, electrical, modulation, thermal, device):
        from qt_legacy_study_workbench import StudyWorkbench
        from qt_reference_style import reference_icon
        from qt_common import COLORS
        rail = self.findChild(QFrame, 'setupRail')
        old_area = rail.parentWidget().parentWidget()
        if isinstance(old_area, QScrollArea):
            old_area.takeWidget();old_area.hide()
        root.removeWidget(self.tabs)
        result_host=QWidget();result_layout=QVBoxLayout(result_host)
        result_layout.setContentsMargins(0,0,0,0)
        self.result_selector=QComboBox()
        self.result_selector.setAccessibleName('Laser result view')
        for name,index in [('Overview',6),('Optical mode',1),('Mode comparison',3),('Temperature',4),('Modulation',5),('Report and import',7)]:
            self.result_selector.addItem(name,index)
        self.result_selector.currentIndexChanged.connect(lambda _:self.tabs.setCurrentIndex(self.result_selector.currentData()))
        export_row=QHBoxLayout();export_row.addWidget(self.result_selector,1)
        self.result_export_button=QToolButton();self.result_export_button.setText('Export data')
        self.result_export_button.setObjectName('exportLaserNumericalData')
        self.result_export_button.setAccessibleName('Export numerical laser results')
        self.result_export_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.result_export_button.setIcon(reference_icon('export',COLORS[theme_manager().mode]['accent']))
        self.result_export_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu=QMenu(self.result_export_button)
        menu.addAction('Raw numerical result JSON…',self.export_result_json)
        menu.addAction('Current sweep CSV + result JSON…',self.export_sweep_csv)
        menu.addAction('Modulation CSV + result JSON…',self.export_modulation_csv)
        self.result_export_button.setMenu(menu);self.result_export_button.setEnabled(False)
        self.result_export_button.setToolTip('Export the completed numerical arrays and captured inputs. CSV exports include a full result JSON beside the table.')
        export_row.addWidget(self.result_export_button);result_layout.addLayout(export_row)
        result_layout.addWidget(self.tabs,1)
        self.tabs.tabBar().hide();self.tabs.setCurrentIndex(self.results_index)
        self.workflow_footer.hide()
        self.tabs.currentChanged.connect(lambda _:self.workflow_footer.hide())
        self.workbench=StudyWorkbench(self.device_store,'Steady-state laser estimate',
            ['Device & mode','Gain & injection','Drive & calculate'],rail,result_host,
            edit_geometry=self._edit_laser_structure,
            preview_note='Independent editable laser geometry. Optical mode inputs are supplied; the calculation is a lumped steady-state estimate.')
        root.insertWidget(0,self.workbench,1)
        self.workbench.input_tabs.setTabText(0,'Drive && geometry')
        parameter_tabs={}
        for name,page in [('Mode',optical),('Gain',electrical),('Thermal',thermal),('Modulation',modulation)]:
            host=QWidget();layout=QVBoxLayout(host);layout.setContentsMargins(10,10,10,10)
            for group in list(page.findChildren(QGroupBox)):
                if isinstance(group.layout(),QFormLayout):layout.addWidget(group)
            layout.addStretch()
            parameter_tabs[name]=self.workbench.add_parameter_tab(host,name)
        self.workbench.add_parameter_tab(device,'Device assignments')
        self.parameter_selector=QComboBox()
        self.parameter_selector.setAccessibleName('Laser parameter group')
        for index in range(self.workbench.input_tabs.count()):
            self.parameter_selector.addItem(self.workbench.input_tabs.tabText(index).replace('&&','&'),index)
        self.parameter_selector.currentIndexChanged.connect(self.workbench.input_tabs.setCurrentIndex)
        self.workbench.input_tabs.currentChanged.connect(self.parameter_selector.setCurrentIndex)
        self.workbench.input_tabs.tabBar().hide()
        self.workbench.properties.layout().insertWidget(0,self.parameter_selector)
        self.workbench.set_step_targets([
            lambda:self.workbench.input_tabs.setCurrentIndex(parameter_tabs['Mode']),
            lambda:self.workbench.input_tabs.setCurrentIndex(parameter_tabs['Gain']),
            lambda:self.workbench.input_tabs.setCurrentIndex(0)])
        structure=self.workbench.views.widget(0)
        self.workbench.views.removeTab(0)
        self.model_views=QTabWidget();self.model_views.setDocumentMode(True)
        self.model_views.addTab(LaserModelDiagram(),'Model flow')
        self.model_views.addTab(structure,'3D structure')
        self.workbench.views.insertTab(0,self.model_views,'Model')
        self.workbench.views.setCurrentIndex(0)
        self.workbench.objects.currentItemChanged.connect(lambda *_:self.model_views.setCurrentIndex(1))
        self.workbench.apply_theme()
        self.workbench.select_step(0)
        for index in range(self.tabs.count()):
            self.tabs.setTabIcon(index,reference_icon('results',COLORS[theme_manager().mode]['muted']))

    def _install_laser_journey(self):
        """Scalar setup screens reuse the original numerical control objects."""
        from qt_journey import JourneyBar
        self.laser_stage = 0
        for action in self.workbench.step_buttons:
            action.hide()
        self.laser_journey = JourneyBar([
            dict(title='Supplied mode', description='Enter optical parameters from an identified source. Selecting a source label does not import an optical solution.'),
            dict(title='Gain & heat', description='Explicit carrier, recombination, efficiency and lumped thermal laws. Geometry remains optional volume context.'),
            dict(title='Drive & modulation', description='Set the drive sweep and optional small-signal bias. Values retain the backend units shown.'),
            dict(title='Check inputs', description='Check the scalar inputs before running. This does not run S4, Meep or a spatial thermal solver.'),
            dict(title='Run', description='Run the steady-state estimate with carrier clamping above threshold. The calculation is synchronous and has no worker cancellation.'),
            dict(title='Results', description='Inspect the actual analytical result, external power import and report provenance.')], self)
        self.workbench.layout().insertWidget(1, self.laser_journey)
        self.laser_journey.stageRequested.connect(self._show_laser_stage)
        self.laser_result_note=QLabel('No steady-state estimate has been run. Optical source labels alone do not import results.')
        self.laser_result_note.setWordWrap(True)
        self.result_selector.parentWidget().layout().insertWidget(1,self.laser_result_note)
        self.workbench.show_results=self.show_results
        context=QPushButton('Geometry and advanced inputs…')
        context.clicked.connect(self._show_laser_context)
        self.workbench.properties.layout().insertWidget(0,context)
        self._laser_parameter_pages = {}
        specifications = [
            ('Mode inputs', [('Wavelength (nm)', 'wavelength'), ('Optical parameter source', 'optical_source'), ('Quality factor Q', 'quality_factor'), ('Group index', 'group_index'), ('Confinement Γ', 'confinement'), ('Internal loss (cm⁻¹)', 'internal_loss'), ('Mode volume (reference)', 'mode_volume')]),
            ('Gain and injection', [('Gain model', 'gain_model'), ('Transparency density', 'transparency_density'), ('Differential gain', 'differential_gain'), ('Active volume (µm³)', 'active_volume'), ('SRH A', 'recombination_a'), ('Radiative B', 'recombination_b'), ('Auger C', 'recombination_c'), ('Injection efficiency', 'injection_efficiency'), ('Differential efficiency', 'differential_efficiency'), ('Spontaneous factor β', 'spontaneous_beta')]),
            ('Lumped thermal inputs', [('Ambient temperature', 'ambient_temperature'), ('Thermal resistance', 'thermal_resistance'), ('Operating voltage', 'series_voltage'), ('Wavelength coefficient', 'thermal_shift'), ('Transparency temperature coefficient', 'transparency_temperature'), ('Differential-gain temperature coefficient', 'gain_temperature')]),
            ('Drive sweep', [('Starting current', 'current_start'), ('Stopping current', 'current_max'), ('Current samples', 'current_points')]),
            ('Small-signal modulation', [('Bias current', 'bias_current'), ('Frequency span', 'modulation_max'), ('Gain compression', 'gain_compression')]),
        ]
        self._laser_control_sections={key:name for name,fields in specifications for _,key in fields}
        self._laser_field_titles={key:title for _,fields in specifications for title,key in fields}
        for name, fields in specifications:
            host=QWidget(); layout=QVBoxLayout(host); form=QFormLayout(); layout.addLayout(form)
            for title, key in fields:
                control=getattr(self,key)
                for old in self.findChildren(QFormLayout):
                    if old.indexOf(control)>=0:
                        row=old.takeRow(control)
                        if row.labelItem and row.labelItem.widget():row.labelItem.widget().deleteLater()
                        break
                if key=='gain_model':
                    self.supported_gain_model=QLabel('Linear differential gain')
                    self.supported_gain_model.setToolTip('This solver uses linear differential gain. Logarithmic and spectral gain inputs are not supported.')
                    form.addRow(title,self.supported_gain_model)
                    control.hide()
                else:form.addRow(title,control)
            if name in ('Mode inputs', 'Small-signal modulation'):
                note=QLabel('Steady-state estimate with carrier clamping above threshold; no transient rate-equation solve.' if name=='Mode inputs' else 'Estimated modulation: carrier lifetime uses 1 / max(A, 1 s⁻¹); damping is max(0.1, 0.7 × resonance frequency) GHz. This is a heuristic response, not a linearized coupled rate-equation solve.')
                note.setWordWrap(True);layout.addWidget(note)
            layout.addStretch()
            self._laser_parameter_pages[name]=self.workbench.add_parameter_tab(host,name)
        self.gain_model.setEnabled(False)
        self.gain_model.setToolTip('This solver uses linear differential gain. Logarithmic and spectral gain inputs are not supported.')
        self.mode_volume.setToolTip('Retained optical context; this value is not passed into the current LaserParameters calculation.')
        self.optical_source.setToolTip('Source label only. Enter and verify the numerical Q, group index and confinement independently.')
        checks=QWidget(); check_layout=QVBoxLayout(checks)
        self.laser_check_note=QLabel('Inputs have not been checked.'); self.laser_check_note.setWordWrap(True)
        check_layout.addWidget(self.laser_check_note)
        check=QPushButton('Check analytical inputs');check.clicked.connect(self._check_laser_inputs);check_layout.addWidget(check)
        self._laser_diagnostic=None
        self.laser_issue_button=QPushButton('Go to input')
        self.laser_issue_button.setObjectName('laserGoToInvalidInput')
        self.laser_issue_button.clicked.connect(lambda:self.open_diagnostic())
        self.laser_issue_button.hide();check_layout.addWidget(self.laser_issue_button);check_layout.addStretch()
        self._laser_check_page=self.workbench.add_parameter_tab(checks,'Check analytical inputs')
        run=QWidget(); run_layout=QVBoxLayout(run)
        self.laser_run_note=QLabel('Not run · no analytical result is available.');self.laser_run_note.setWordWrap(True)
        run_layout.addWidget(self.laser_run_note)
        scope=QLabel('Lumped steady-state estimate: carrier density is clamped above threshold. Modulation uses an estimated carrier lifetime and heuristic damping; no time-dependent rate equations are solved. Synchronous calculation; no worker Stop is available.')
        scope.setWordWrap(True);run_layout.addWidget(scope)
        action=QPushButton('Run analytical laser model');action.setProperty('primary',True);action.clicked.connect(self.run_simulation);run_layout.addWidget(action);run_layout.addStretch()
        self._laser_run_page=self.workbench.add_parameter_tab(run,'Run analytical model')
        self.parameter_selector.blockSignals(True);self.parameter_selector.clear()
        for index in range(self.workbench.input_tabs.count()):self.parameter_selector.addItem(self.workbench.input_tabs.tabText(index).replace('&&','&'),index)
        self.parameter_selector.blockSignals(False)
        self._show_laser_stage(0)

    def _show_laser_stage(self, index):
        self.laser_stage=index;self.laser_journey.set_current(index)
        if index!=5:self._laser_setup_stage=index
        names=[['Mode inputs'],['Gain and injection','Lumped thermal inputs'],['Drive sweep','Small-signal modulation']]
        if index<3:
            pages=[self._laser_parameter_pages[name] for name in names[index]]
        elif index==3:pages=[self._laser_check_page]
        elif index==4:pages=[self._laser_run_page]
        else:pages=[]
        # Stage changes only presentation. Every original editor remains alive
        # and reachable through the parameter selector's optional-context menu.
        allowed=set(pages)
        if index==0:
            allowed.update(i for i in range(self.workbench.input_tabs.count())
                           if self.workbench.input_tabs.tabText(i).replace('&&','&')=='Device assignments')
        for i in range(self.parameter_selector.count()):
            self.parameter_selector.model().item(i).setEnabled(i in allowed)
        self.workbench.objects_panel.setVisible(False)
        self.workbench.properties.setVisible(index!=5)
        self.parameter_selector.setVisible(len(allowed)>1)
        self.result_selector.setVisible(index==5)
        if pages:self.workbench.input_tabs.setCurrentIndex(pages[0])
        self.model_views.setCurrentIndex(0)
        self.workbench.views.setCurrentIndex(1 if index==5 else 0)

    def show_results(self):
        self.tabs.setCurrentIndex(self.results_index)
        self._show_laser_stage(5)

    def show_setup(self):
        self._show_laser_stage(getattr(self,'_laser_setup_stage',0))

    def validate_setup(self):
        """Public check contract used by the global simulation footer."""
        valid=self._check_laser_inputs()
        self._show_laser_stage(3)
        return valid

    def _check_laser_inputs(self):
        field=''
        try:
            for key,title in self._laser_field_titles.items():
                control=getattr(self,key)
                if key!='mode_volume' and isinstance(control,(QDoubleSpinBox,QSpinBox)) and not control.hasAcceptableInput():
                    field=key
                    raise ValueError('Enter a valid value for '+title+'.')
            if self.current_start.value()>=self.current_max.value():
                field='current_max'
                raise ValueError('Stopping current must exceed starting current.')
            parameters=self.laser_parameters()
            try:parameters.validate()
            except (ValueError,OverflowError):
                # Use the existing parameter validator to identify the control;
                # do not infer destinations by parsing human-readable errors.
                controls=dict(wavelength_nm='wavelength',group_index='group_index',
                    confinement='confinement',quality_factor='quality_factor',
                    transparency_density_cm3='transparency_density',differential_gain_cm2='differential_gain',
                    active_volume_um3='active_volume',recombination_a_s='recombination_a',
                    recombination_b_cm3_s='recombination_b',recombination_c_cm6_s='recombination_c',
                    injection_efficiency='injection_efficiency',differential_efficiency='differential_efficiency',
                    internal_loss_cm='internal_loss',spontaneous_emission_factor='spontaneous_beta',
                    gain_compression_cm3='gain_compression',ambient_temperature_k='ambient_temperature',
                    thermal_resistance_k_w='thermal_resistance',drive_voltage_v='series_voltage',
                    wavelength_shift_nm_k='thermal_shift',transparency_temperature_coefficient_k='transparency_temperature',
                    differential_gain_temperature_coefficient_k='gain_temperature')
                for parameter,control in controls.items():
                    try:LaserParameters(**{parameter:getattr(parameters,parameter)}).validate()
                    except (ValueError,OverflowError):
                        field=control
                        break
                raise
        except (ValueError,OverflowError) as exc:
            from input_diagnostics import diagnostic
            self._laser_diagnostic=diagnostic(str(exc),workspace='lumped_laser',
                section=self._laser_control_sections.get(field,''),field=field)
            self.laser_check_note.setText('Inputs need attention: '+str(exc))
            self.laser_issue_button.setText('Go to '+self._laser_field_titles.get(field,'input').lower())
            self.laser_issue_button.setVisible(bool(field))
            return False
        self._laser_diagnostic=None;self.laser_issue_button.hide()
        self.laser_check_note.setText('Analytical inputs are valid. Optical Q and confinement are supplied parameters; S4 and Meep have not run.')
        return True

    def open_diagnostic(self,target=None):
        """Select the owning laser stage, then reveal its unchanged input."""
        from qt_input_diagnostics import reveal_and_focus
        target=target or self._laser_diagnostic
        if not isinstance(target,dict):return False
        field=target.get('field','');section=self._laser_control_sections.get(field)
        if section is None:return False
        stage={'Mode inputs':0,'Gain and injection':1,'Lumped thermal inputs':1,
               'Drive sweep':2,'Small-signal modulation':2}[section]
        self._show_laser_stage(stage)
        self.workbench.input_tabs.setCurrentIndex(self._laser_parameter_pages[section])
        return reveal_and_focus(getattr(self,field),message=target.get('message',''))

    def return_to_issues(self):
        self._show_laser_stage(3)
        if self._laser_diagnostic:self.laser_issue_button.setFocus()

    def _show_laser_context(self):
        """Optional authored geometry is context, not a spatial laser solve."""
        for i in range(self.parameter_selector.count()):self.parameter_selector.model().item(i).setEnabled(True)
        self.parameter_selector.setVisible(True)
        self.workbench.properties.setVisible(True)
        self.workbench.objects_panel.setVisible(True)
        self.workbench.input_tabs.setCurrentIndex(0)
        self.workbench.views.setCurrentIndex(0)
        self.model_views.setCurrentIndex(1)

    def _edit_laser_structure(self):
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox
        from qt_device_builder import DeviceBuilderPage
        dialog=QDialog(self);dialog.setWindowTitle('Edit laser structure and materials');dialog.resize(1180,800)
        layout=QVBoxLayout(dialog);editor=DeviceBuilderPage(self.device_store,laser=True)
        layout.addWidget(editor,1)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        dialog.exec()
        self.sync_device_geometry()

    @staticmethod
    def wrap_page(page):
        area=QScrollArea();area.setWidgetResizable(True);area.setFrameShape(QFrame.Shape.NoFrame);area.setWidget(page)
        return area

    @staticmethod
    def create_device_store(parent_store):
        """Independent laser geometry; never overwrite the general optical model."""
        from qt_core import ProjectStore
        import pandas as pd
        from model import MAT_COLS,LAYER_COLS,PAT_COLS
        from data_library import read_json
        result=ProjectStore(parent_store.library if parent_store else None,restore=False)
        result.session_path=result.library.data/'laser_device_session.json'
        result.materials=pd.DataFrame([
            ['Air','constant_nk',1.,0.,'','nm'],['InP','constant_nk',3.17,0.,'','nm'],
            ['InGaAsP','constant_nk',3.45,0.,'','nm']],columns=MAT_COLS)
        result.layers=pd.DataFrame([
            ['Air',0.,'Air'],['Top cladding',1.,'InP'],['Photonic crystal',.43,'InGaAsP'],
            ['Barrier',.01,'InGaAsP'],['Quantum well',.007,'InGaAsP'],
            ['Bottom cladding',1.,'InP'],['Substrate',0.,'InP']],columns=LAYER_COLS)
        result.patterns=pd.DataFrame([['circle','Photonic crystal','Air',0.,0.,.045,0.,0.]],columns=PAT_COLS)
        result.settings.update(ax_um=.474,ay_um=.474)
        return result

    def sync_device_geometry(self,*args):
        from structure_builder import rows
        from model import LAYER_COLS,PAT_COLS
        layers=rows(self.device_store.layers,LAYER_COLS);patterns=rows(self.device_store.patterns,PAT_COLS)
        self.period.setValue(float(self.device_store.settings['ax_um']))
        circles=[p for p in patterns if p['Shape']=='circle']
        if circles:
            first=circles[0];self.radius.setValue(float(first['SizeX_um']))
            layer=next((l for l in layers if l['Name']==first['Layer']),None)
            if layer:self.etch.setValue(float(layer['Thickness_um']))
        if hasattr(self,'pc_layer'):
            names=[l['Name'] for l in layers[1:-1]]
            for combo in (self.pc_layer,self.active_layer):
                current=combo.currentText()
                with QSignalBlocker(combo):combo.clear();combo.addItems(names);combo.setCurrentText(current if current in names else names[0])
        active=[l for l in layers[1:-1] if l['Name']==self.active_layer.currentText()] if hasattr(self,'active_layer') else []
        if active:self.gain_thickness.setValue(sum(float(l['Thickness_um']) for l in active))
        self.structure_canvas.set_model(self.device_store,self.pc_layer.currentText(),5)
        if self.last_result is not None:
            self.run_state.setText('●  INPUTS CHANGED');self.status.setText('Device changed. Run again to update results.')

    def apply_device_geometry(self):
        self.sync_device_geometry()
        layers=self.device_store.layers
        row=layers[layers.Name==self.pc_layer.currentText()]
        if len(row):self.etch.setValue(float(row.iloc[0].Thickness_um))
        self.active_volume.setValue(self.device_width.value()*self.device_height.value()*self.gain_thickness.value())
        self.device_builder.status.setText('Device geometry applied to the analytical laser model.')

    def retheme(self,*args):
        for plot in self.findChildren(_PCSELPlot):plot.retheme()

    @staticmethod
    def workspace_stylesheet():
        return """
        QWidget#laserWorkspace { background:#06172a; color:#dce7f3; font-size:11px; }
        QLabel#pageTitle { color:#63ccff; font-size:20px; font-weight:750; letter-spacing:1px; }
        QLabel#eyebrow { color:#6f8ca6; font-size:10px; letter-spacing:1px; }
        QLabel#runState { color:#47d7bd; background:#0d2130; border:1px solid #1e5360; border-radius:12px; padding:6px 12px; font-weight:700; }
        QFrame#setupRail,QFrame#instrumentPanel { background:#08233c; border:1px solid #245f86; border-radius:4px; }
        QLabel#railTitle { color:#edf6ff; font-weight:700; font-size:12px; letter-spacing:1px; }
        QLabel#sectionLabel { color:#6f8ca6; font-size:9px; font-weight:700; letter-spacing:1px; padding-top:5px; }
        QGroupBox { background:#0b1b2a; border:1px solid #1b3448; border-radius:8px; margin-top:11px; padding:12px 10px 9px; font-weight:650; color:#dce8f5; }
        QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 5px; color:#86a9c4; }
        QDoubleSpinBox,QSpinBox,QComboBox,QPlainTextEdit { background:#071b2d; border:1px solid #315875; border-radius:4px; padding:2px 5px; color:#e8f1fa; selection-background-color:#167f89; min-height:18px; }
        QDoubleSpinBox:focus,QSpinBox:focus,QComboBox:focus { border-color:#31c7ba; }
        QTabWidget::pane { border:0; background:#071b2d; top:-1px; }
        QTabBar { qproperty-expanding:true; }
        QTabBar::tab { background:#091d31; color:#a8c7e5; padding:8px 14px; border:1px solid #214765; border-bottom:2px solid transparent; }
        QTabBar::tab:selected { color:#e9f7ff; background:#0b3655; border-bottom:2px solid #21cfff; }
        QPushButton { background:#12283a; border:1px solid #29475e; border-radius:6px; padding:7px 12px; color:#dce9f4; font-weight:600; }
        QPushButton:hover { border-color:#44cabd; background:#173348; }
        QPushButton[primary="true"] { color:white; font-size:14px; background:#079be0; border:1px solid #25ddff; }
        QLabel#kpi { background:#09223a; border:1px solid #245f86; border-radius:5px; padding:4px; color:#d9f8f2; font-size:10px; }
        QLabel#solverStatus { color:#cfe7fa; padding:2px; }
        QLabel#muted { color:#7690a6; }
        QHeaderView::section { background:#102638; color:#8eabc2; border:0; border-bottom:1px solid #29465a; padding:7px; }
        QTableWidget { background:#081622; alternate-background-color:#0b1c2a; border:1px solid #203b50; gridline-color:#183247; color:#d7e4ee; }
        QScrollArea { border:0; background:transparent; }
        """

    def build_setup_rail(self):
        rail=QFrame(); rail.setObjectName('setupRail'); rail.setFixedWidth(270)
        layout=QVBoxLayout(rail); layout.setContentsMargins(10,7,10,7); layout.setSpacing(2)
        label=QLabel('PCSEL Device Parameters'); label.setObjectName('railTitle'); layout.addWidget(label)
        section=QLabel('GEOMETRY'); section.setObjectName('sectionLabel'); layout.addWidget(section)
        self.device_type=QComboBox(); self.device_type.addItems(['PCSEL','VCSEL','Edge-emitting laser','Photonic-crystal cavity']); self.device_type.hide()
        self.lattice=QComboBox(); self.lattice.addItems(['Square','Hexagonal','Triangular'])
        self.hole_shape=QComboBox(); self.hole_shape.addItems(['Circular','Elliptical','Square'])
        self.periods=QSpinBox(); self.periods.setRange(3,99); self.periods.setValue(12)
        self.period=self.spin(.42,.05,100,.01,' µm'); self.radius=self.spin(.14,.001,49,.01,' µm'); self.etch=self.spin(.18,.001,100,.01,' µm')
        self.gain_thickness=self.spin(.25,.001,100,.01,' µm'); self.wavelength=self.spin(1550,100,3000,1,' nm',1)
        form=QFormLayout(); form.setVerticalSpacing(2); form.setHorizontalSpacing(5); form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        for text,w in [('Lattice constant (a)',self.period),('Hole radius (r)',self.radius),('Hole shape',self.hole_shape),('Lattice type',self.lattice),('Number of periods',self.periods)]: form.addRow(text,w)
        layout.addLayout(form)
        section=QLabel('LASER STRUCTURE'); section.setObjectName('sectionLabel'); layout.addWidget(section)
        structure=QFormLayout(); structure.setVerticalSpacing(2); structure.setHorizontalSpacing(5)
        self.top_index=self.spin(3.17,1,10,.01,'  InP',2)
        self.substrate=QComboBox(); self.substrate.addItems(['InP','GaAs','GaN'])
        for text,w in [('Top cladding (n)',self.top_index),('Etch depth',self.etch),('Active thickness',self.gain_thickness),('Substrate',self.substrate)]: structure.addRow(text,w)
        layout.addLayout(structure)
        section=QLabel('DESIGN TARGETS'); section.setObjectName('sectionLabel'); layout.addWidget(section)
        targets=QFormLayout(); targets.setVerticalSpacing(2); targets.setHorizontalSpacing(5)
        self.target_q=self.spin(1e4,10,1e8,100,'',0); self.material_gain=self.spin(1500,0,1e6,50,' cm⁻¹',0)
        for text,w in [('Target wavelength',self.wavelength),('Target Q factor',self.target_q),('Material gain',self.material_gain)]: targets.addRow(text,w)
        layout.addLayout(targets)
        section=QLabel('CURRENT SWEEP'); section.setObjectName('sectionLabel'); layout.addWidget(section)
        self.fidelity=QComboBox(); self.fidelity.addItems(['Analytical estimate','Imported optical solution','Coupled multiphysics']); self.fidelity.hide()
        self.current_max=self.spin(150,.001,1e6,10,' mA',1); self.current_points=QSpinBox(); self.current_points.setRange(2,10001); self.current_points.setValue(301)
        self.current_start=self.spin(0,0,1e6,1,' mA',1)
        runform=QFormLayout(); runform.setVerticalSpacing(2); runform.setHorizontalSpacing(5)
        for text,w in [('Start current',self.current_start),('Stop current',self.current_max),('Points',self.current_points)]: runform.addRow(text,w)
        layout.addLayout(runform)
        self.status=QLabel(); self.status.setObjectName('muted'); self.status.setWordWrap(True); layout.addWidget(self.status)
        run=QPushButton('▶  RUN SIMULATION'); run.setObjectName('runPCSELSimulation'); run.setProperty('primary',True); run.clicked.connect(self.run_simulation); run.hide(); layout.addWidget(run)
        return rail

    def spin(self,v,lo,hi,step,suffix='',decimals=4):
        w=QDoubleSpinBox(); w.setDecimals(decimals); w.setRange(lo,hi); w.setSingleStep(step); w.setValue(v); w.setSuffix(suffix); return w

    def scroll(self,layout):
        content=QWidget(); content.setLayout(layout); page=QScrollArea(); page.setWidgetResizable(True); page.setWidget(content); return page

    def setup_tab(self):
        page=QWidget(); page.setObjectName('pcselDashboard'); layout=QVBoxLayout(page); layout.setContentsMargins(7,7,7,7); layout.setSpacing(7)
        self._dashboard_panels=[]
        upper=QHBoxLayout(); upper.setSpacing(7); layout.addLayout(upper,57)
        rail_area=self.wrap_page(self.build_setup_rail());rail_area.setFixedWidth(285)
        rail_area.setMinimumHeight(0);upper.addWidget(rail_area)

        center=QGridLayout(); center.setSpacing(7); upper.addLayout(center,5)
        self.structure_canvas=self.compact_geometry('3D PCSEL Structure (Multilayer View)')
        self.field_canvas=self.compact_canvas('Optical field · no solver data',0)
        center.addWidget(self.structure_canvas.parentWidget(),0,0)
        center.addWidget(self.field_canvas.parentWidget(),0,1)

        side=QVBoxLayout(); side.setSpacing(7); upper.addLayout(side,3)
        status_panel=self.panel('Solver & Simulation Status'); status_layout=status_panel.layout()
        self.solver_status=QLabel('Optical parameters: supplied by user\n\nS4 / Meep: not run\n\nCOMSOL: no results imported\n\nSteady-state estimate: ready')
        self.solver_status.setObjectName('solverStatus'); status_layout.addWidget(self.solver_status); side.addWidget(status_panel)
        flow=self.panel('Laser input sources'); flow_label=QLabel('Supplied optical mode → Steady-state laser estimate\n'
                                                        'Gain, recombination and thermal inputs · Optional external power data')
        flow_label.setAlignment(Qt.AlignmentFlag.AlignCenter); flow_label.setWordWrap(True); flow.layout().addWidget(flow_label); side.addWidget(flow)
        dashboard_run=QPushButton('▶   Run Laser Simulation'); dashboard_run.setObjectName('runLaserSimulationDashboard'); dashboard_run.setProperty('primary',True); dashboard_run.clicked.connect(self.run_simulation); side.addWidget(dashboard_run)

        results=self.panel('Simulation Results'); result_layout=results.layout(); plots=QHBoxLayout(); plots.setSpacing(5); result_layout.addLayout(plots,1)
        self.dashboard_li=self.compact_canvas('L-I Curve',145); plots.addWidget(self.dashboard_li.parentWidget())
        self.dashboard_mod=self.compact_canvas('Modulation Response',145); plots.addWidget(self.dashboard_mod.parentWidget())
        self.dashboard_rolloff=self.compact_canvas('Junction temperature',145); plots.addWidget(self.dashboard_rolloff.parentWidget())
        self.dashboard_shift=self.compact_canvas('Wavelength Shift',145); plots.addWidget(self.dashboard_shift.parentWidget())
        cards=QHBoxLayout(); result_layout.addLayout(cards)
        self.dashboard_kpis=[]
        for caption in ('Threshold Current','Output Power (I max)','Slope Efficiency','3-dB Bandwidth','SMSR','Lasing Wavelength','Thermal Roll-off (T₀)','Power Conversion Efficiency'):
            card=QLabel(caption+'\n—'); card.setWordWrap(True); card.setMinimumHeight(64); card.setObjectName('kpi'); card.setAlignment(Qt.AlignmentFlag.AlignCenter); cards.addWidget(card); self.dashboard_kpis.append(card)
        layout.addWidget(results,43)

        # Compatibility/live overview labels remain discoverable by integrations.
        self.overview_geometry=QLabel('GEOMETRY\nSquare lattice PCSEL'); self.overview_geometry.setObjectName('kpi'); self.overview_geometry.hide()
        self.overview_sweep=QLabel('CURRENT SWEEP\n0 — 150 mA'); self.overview_sweep.setObjectName('kpi'); self.overview_sweep.hide()
        self.overview_solver=QLabel('MODEL\nAnalytical estimate'); self.overview_solver.setObjectName('kpi'); self.overview_solver.hide()
        self.overview_status=QLabel('RESULT\nAwaiting simulation'); self.overview_status.setObjectName('kpi'); self.overview_status.hide()
        for widget in (self.overview_geometry,self.overview_sweep,self.overview_solver,self.overview_status): layout.addWidget(widget)
        return page

    @staticmethod
    def panel(title):
        frame=QFrame(); frame.setObjectName('instrumentPanel'); box=QVBoxLayout(frame); box.setContentsMargins(8,6,8,8); box.setSpacing(4)
        heading=QLabel(title); heading.setObjectName('railTitle'); box.addWidget(heading); return frame

    def compact_canvas(self,title,height):
        frame=PCSELPage.panel(title); self._dashboard_panels.append(frame)
        widget=_PCSELPlot(); widget._instrument_panel=frame
        widget.setMinimumSize(0,height); widget.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Ignored); frame.setMinimumSize(0,0); frame.layout().addWidget(widget,1); return widget

    def compact_geometry(self,title):
        from qt_device_builder import GeometryViewport
        frame=PCSELPage.panel(title);self._dashboard_panels.append(frame)
        widget=GeometryViewport();widget._instrument_panel=frame
        widget.setToolTip('Applied Device Setup layers and patterns. Preview controls do not change optical n/k values.')
        widget.setMinimumSize(0,0);widget.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Ignored)
        frame.setMinimumSize(0,0);frame.layout().addWidget(widget,1)
        return widget

    def optical_tab(self):
        layout=QVBoxLayout(); box=QGroupBox('Optical solution'); form=QFormLayout(box); layout.addWidget(box)
        self.optical_source=QComboBox(); self.optical_source.addItems(['Enter mode parameters','Meep / FDTD result','S4 unit-cell result','FEM result'])
        self.quality_factor=self.spin(4.2e4,10,1e8,100,'',0); self.group_index=self.spin(3.6,1,20,.1); self.confinement=self.spin(.22,.001,1,.01); self.mode_volume=self.spin(2.8,.001,1e6,.1,' (λ/n)³'); self.internal_loss=self.spin(0,0,1e5,.1,' cm⁻¹')
        for label,w in [('Source',self.optical_source),('Quality factor Q',self.quality_factor),('Group index',self.group_index),('Confinement Γ',self.confinement),('Mode volume',self.mode_volume),('Internal loss',self.internal_loss)]: form.addRow(label,w)
        self.mode_canvas=self.canvas(layout,'Γ-point band and mode estimate'); return self.scroll(layout)

    def electrical_tab(self):
        layout=QVBoxLayout(); row=QHBoxLayout(); layout.addLayout(row)
        box=QGroupBox('Material gain'); form=QFormLayout(box); row.addWidget(box)
        self.gain_model=QComboBox(); self.gain_model.addItems(['Linear differential gain','Logarithmic gain','Imported spectral gain'])
        self.transparency_density=self.spin(1,.001,1000,.1,' ×10¹⁸ cm⁻³'); self.differential_gain=self.spin(2.5,.001,1000,.1,' ×10⁻¹⁶ cm²'); self.active_volume=self.spin(120,.001,1e7,1,' µm³')
        for label,w in [('Gain model',self.gain_model),('Transparency density',self.transparency_density),('Differential gain',self.differential_gain),('Active volume',self.active_volume)]: form.addRow(label,w)
        box=QGroupBox('Injection and recombination'); form=QFormLayout(box); row.addWidget(box)
        self.recombination_a=self.spin(1,.001,1e6,.1,' ×10⁸ s⁻¹'); self.recombination_b=self.spin(1,0,1e6,.1,' ×10⁻¹⁰ cm³/s'); self.recombination_c=self.spin(3,0,1e6,.1,' ×10⁻²⁹ cm⁶/s')
        self.injection_efficiency=self.spin(.85,.001,1,.01); self.differential_efficiency=self.spin(.7,.001,1,.01); self.spontaneous_beta=self.spin(1,0,10000,.1,' ×10⁻⁴')
        for label,w in [('A · SRH',self.recombination_a),('B · radiative',self.recombination_b),('C · Auger',self.recombination_c),('Injection efficiency',self.injection_efficiency),('Differential efficiency',self.differential_efficiency),('Spontaneous emission β',self.spontaneous_beta)]: form.addRow(label,w)
        note=QLabel('Use extracted COMSOL carrier/current results to set active volume, injection efficiency, and recombination inputs.'); note.setObjectName('muted'); note.setWordWrap(True); layout.addWidget(note); layout.addStretch(1); return self.scroll(layout)

    def li_tab(self):
        layout=QVBoxLayout(); self.quick=QLabel(); self.quick.setObjectName('pcselQuickResults'); self.quick.setWordWrap(True); layout.addWidget(self.quick); self.laser_canvas=self.canvas(layout,'Light–current characteristic'); return self.scroll(layout)

    def modulation_tab(self):
        layout=QVBoxLayout(); box=QGroupBox('Small-signal estimate'); form=QFormLayout(box); layout.addWidget(box)
        self.bias_current=self.spin(80,.001,1e6,5,' mA',1); self.modulation_max=self.spin(40,.1,1000,5,' GHz',1); self.gain_compression=self.spin(.02,0,100,.01,' ×10⁻¹⁷ cm³')
        form.addRow('Bias current',self.bias_current); form.addRow('Frequency span',self.modulation_max); form.addRow('Gain compression',self.gain_compression)
        self.modulation_summary=QLabel(); self.modulation_summary.setObjectName('muted'); layout.addWidget(self.modulation_summary); self.modulation_canvas=self.canvas(layout,'Normalized frequency response'); return self.scroll(layout)

    def thermal_tab(self):
        layout=QVBoxLayout(); box=QGroupBox('Thermal feedback'); form=QFormLayout(box); layout.addWidget(box)
        self.ambient_temperature=self.spin(300,4,1000,5,' K',1); self.thermal_resistance=self.spin(18,0,1e5,1,' K/W',2); self.series_voltage=self.spin(1.8,.001,100,.1,' V',2); self.thermal_shift=self.spin(.07,0,100,.01,' nm/K',3)
        defaults=LaserParameters()
        self.transparency_temperature=self.spin(defaults.transparency_temperature_coefficient_k,0,1,.0001,' K⁻¹',5)
        self.gain_temperature=self.spin(defaults.differential_gain_temperature_coefficient_k,0,1,.0001,' K⁻¹',5)
        for label,w in [('Ambient temperature',self.ambient_temperature),('Thermal resistance',self.thermal_resistance),('Operating voltage',self.series_voltage),('Wavelength coefficient',self.thermal_shift),('Transparency temperature coefficient',self.transparency_temperature),('Differential gain temperature coefficient',self.gain_temperature)]: form.addRow(label,w)
        self.thermal_summary=QLabel(); self.thermal_summary.setObjectName('muted'); layout.addWidget(self.thermal_summary); self.thermal_canvas=self.canvas(layout,'Temperature and wavelength drift'); return self.scroll(layout)

    def mode_tab(self):
        layout=QVBoxLayout(); self.mode_table=QTableWidget(0,6); self.mode_table.setObjectName('pcselModeComparison'); self.mode_table.setHorizontalHeaderLabels(['Mode','λ (nm)','Q','Γ','Threshold gain','Relative margin']); self.mode_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); layout.addWidget(self.mode_table)
        self.optimization_canvas=self.canvas(layout,'Mode competition and radius sensitivity'); return self.scroll(layout)

    def report_tab(self):
        page=QWidget(); layout=QVBoxLayout(page); bar=QHBoxLayout(); imported=QPushButton('Import COMSOL power…'); imported.setObjectName('importComsolLaserPower'); imported.clicked.connect(self.import_comsol); bar.addWidget(imported); export=QPushButton('Export report…'); export.setObjectName('exportLaserReport'); export.clicked.connect(self.export_report); bar.addWidget(export); bar.addStretch(1); layout.addLayout(bar)
        self.report=QPlainTextEdit(); self.report.setReadOnly(True); self.report.setObjectName('pcselSimulationReport'); layout.addWidget(self.report); return page

    @staticmethod
    def canvas(layout,title):
        box=QGroupBox(title); inner=QVBoxLayout(box); widget=_PCSELPlot(); widget.setMinimumHeight(300); widget.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding); inner.addWidget(widget); layout.addWidget(box,1); return widget

    def design(self):
        layer = self.device_store.layers
        selected = layer[layer.Name == self.pc_layer.currentText()]
        if selected.empty:
            raise ValueError('Select a patterned device layer.')
        return PCSELDesign(self.period.value(),self.radius.value(),self.etch.value(),
                           self.gain_thickness.value(),self.wavelength.value(),
                           patterned_layer_thickness_um=float(selected.iloc[0].Thickness_um)).validate()
    def _optional_design_context(self):
        """Geometry is report context, never a prerequisite for supplied modes."""
        try:
            return self.design()
        except (ValueError, OverflowError):
            return None

    def laser_parameters(self):
        return LaserParameters(wavelength_nm=self.wavelength.value(),group_index=self.group_index.value(),confinement=self.confinement.value(),quality_factor=self.quality_factor.value(),transparency_density_cm3=self.transparency_density.value()*1e18,differential_gain_cm2=self.differential_gain.value()*1e-16,active_volume_um3=self.active_volume.value(),recombination_a_s=self.recombination_a.value()*1e8,recombination_b_cm3_s=self.recombination_b.value()*1e-10,recombination_c_cm6_s=self.recombination_c.value()*1e-29,injection_efficiency=self.injection_efficiency.value(),differential_efficiency=self.differential_efficiency.value(),internal_loss_cm=self.internal_loss.value(),spontaneous_emission_factor=self.spontaneous_beta.value()*1e-4,gain_compression_cm3=self.gain_compression.value()*1e-17,ambient_temperature_k=self.ambient_temperature.value(),thermal_resistance_k_w=self.thermal_resistance.value(),drive_voltage_v=self.series_voltage.value(),wavelength_shift_nm_k=self.thermal_shift.value(),transparency_temperature_coefficient_k=self.transparency_temperature.value(),differential_gain_temperature_coefficient_k=self.gain_temperature.value())

    def run_simulation(self):
        # Reject unfinished numeric drafts before value() can reuse an old value.
        if not self._check_laser_inputs():
            self.laser_run_note.setText('Input error: '+self._laser_diagnostic['message'])
            self._show_laser_stage(3)
            return None
        try:
            if self.current_start.value()>=self.current_max.value():raise ValueError('Stop current must be greater than start current.')
            parameters=self.laser_parameters().validate(); currents=np.linspace(self.current_start.value(),self.current_max.value(),self.current_points.value()); frequencies=np.linspace(0,self.modulation_max.value(),501); r=solve_laser(parameters,currents); r['modulation']=solve_laser(parameters,[self.bias_current.value()],frequencies)['modulation']
        except (ValueError,OverflowError) as exc:
            if hasattr(self,'laser_run_note'):
                self.laser_run_note.setText('Input error: '+str(exc))
                self.laser_result_note.setText('Calculation not completed. Previous displays, if present, are stale: '+str(exc))
            self.last_result=None; self.result_export_button.setEnabled(False); self.status.setText(str(exc)); self.status.setProperty('error',True); self.run_state.setText('●  INPUT ERROR'); self.run_state.setStyleSheet('color:#ff8297;'); self.overview_status.setText(f'RESULT\n{exc}'); return None
        d=self._optional_design_context()
        # A later input edit or external overlay must not rewrite the provenance
        # of an already calculated result with values from live controls.
        r.setdefault('inputs',asdict(parameters))
        r['report_context']=dict(geometry=self._report_geometry(d),fidelity=self.fidelity.currentText(),
            mode_volume=self.mode_volume.value(),optical_source=self.optical_source.currentText())
        from app_version import APP_VERSION
        r['calculation_context']=dict(result_id=uuid.uuid4().hex,completed_at_utc=datetime.now(timezone.utc).isoformat(),
            app_version=APP_VERSION,study_id='lumped_laser',
            current_sweep=dict(start_mA=float(currents[0]),stop_mA=float(currents[-1]),samples=len(currents)),
            modulation=dict(bias_current_mA=self.bias_current.value(),frequency_stop_GHz=float(frequencies[-1]),samples=len(frequencies)),
            method='Lumped steady-state ABC threshold/output estimate with supplied optical mode, carrier clamping above threshold, lumped thermal feedback and heuristic modulation.',
            limitations=['Optical Q and confinement are supplied; S4 and Meep were not run.',
                         'Optional geometry is context only unless explicitly applied to scalar volume inputs.',
                         'No time-dependent coupled rate equations are solved; carrier density is clamped above threshold.',
                         'Modulation uses carrier lifetime 1 / max(A, 1 s^-1) and damping max(0.1, 0.7 * resonance frequency) GHz.',
                         'External COMSOL power remains a separately identified overlay.'])
        self._results_stale=False
        self.result_export_button.setEnabled(True)
        self.last_result=r; self.status.setProperty('error',False); self.status.setText(f'Complete · {len(currents)} samples · supplied optical mode')
        if hasattr(self,'laser_run_note'):
            self.laser_run_note.setText(f'Steady-state estimate complete · {len(currents)} current samples. Carrier clamping above threshold; heuristic modulation. Supplied optical parameters; no spatial optical solve.')
            self.laser_result_note.setText(f'Steady-state estimate · {len(currents)} current samples. Carrier density is clamped above threshold; modulation uses estimated lifetime and heuristic damping. No transient rate-equation solve. Optical Q and confinement supplied by user; S4 / Meep not run. External power imports retain their own report provenance.')
        self.run_state.setText('●  SOLVED'); self.run_state.setStyleSheet('')
        self.overview_geometry.setText(f'OPTIONAL GEOMETRY\n{self.lattice.currentText()} · r/a {d.hole_radius_um/d.period_um:.3f}' if d is not None else 'OPTIONAL GEOMETRY\nNo valid geometry context; supplied-mode calculation')
        self.overview_sweep.setText(f'CURRENT SWEEP\n{self.current_start.value():g} — {self.current_max.value():g} mA · {len(currents)} pts')
        self.overview_solver.setText(f'MODEL\n{self.fidelity.currentText()}')
        self.overview_status.setText(f"RESULT\nIth {r['threshold_current_ma']:.2f} mA · {r['output_power_mw'][-1]:.2f} mW")
        self.quick.setText(f"Resonance  {parameters.wavelength_nm:.1f} nm     Q  {self.quality_factor.value():.3g}     Photon lifetime  {r['photon_lifetime_ps']:.3g} ps\nThreshold gain  {r['threshold_gain_cm-1']:.3g} cm⁻¹     Threshold current  {r['threshold_current_ma']:.3g} mA     Slope  {r['slope_efficiency_w_per_a']:.3g} W/A")
        self.plot_dashboard(d,r); self.plot_mode(d); self.plot_laser(r); self.plot_modulation(r); self.plot_thermal(r); self.populate_modes(d,r); self.plot_sensitivity(d); self.write_report(d,r)
        comsol_state='external power imported' if getattr(self,'_comsol_imported',None) is not None else 'not imported'
        self.solver_status.setText('Optical parameters: supplied by user\n\nS4 / Meep: not run\n\nCOMSOL: '+comsol_state+'\n\nSteady-state estimate: calculation complete')
        if getattr(self,'_comsol_imported',None) is not None:
            self.last_result=merge_comsol_power(r,self._comsol_imported);self._render_comsol()
        self.retheme()
        if hasattr(self,'workbench'):
            self.workbench.show_results();self.tabs.setCurrentIndex(self.results_index)
            if hasattr(self,'laser_journey'):self._show_laser_stage(5)
        return self.last_result

    @staticmethod
    def style(fig,ax):
        fig.patch.set_facecolor('#0b2537'); ax.set_facecolor('#0b2537'); ax.grid(True,color='#254257'); ax.tick_params(colors='#9eb1c4'); ax.xaxis.label.set_color('#c6d1df'); ax.yaxis.label.set_color('#c6d1df'); ax.title.set_color('white')
    def finish(self,fig,canvas):
        if fig.axes: fig.axes[0].legend(facecolor='#0b2537',edgecolor='#365268',labelcolor='#dbe5ef')
        fig.tight_layout(); canvas.draw_idle()
    def plot_dashboard(self,d,r):
        self.structure_canvas.set_model(self.device_store,self.pc_layer.currentText(),5)

        fig=self.field_canvas.figure;fig.clear();ax=fig.add_subplot(111);ax.set_axis_off();ax.text(.5,.5,'Field data unavailable\nRun an electromagnetic solver for this device.',ha='center',va='center');self.field_canvas.draw_idle()

        current=np.asarray(r['currents_ma']); power=np.asarray(r['output_power_mw']); temp=np.asarray([row['temperature_k'] for row in r['sweep']]); wl=np.asarray([row['wavelength_nm'] for row in r['sweep']])
        self.dashboard_plot(self.dashboard_li,current,power,'Current (mA)','Power (mW)')
        m=r['modulation']; self.dashboard_plot(self.dashboard_mod,np.asarray(m['frequencies_ghz']),np.asarray(m['magnitude_db']),'Frequency (GHz)','Response (dB)',logx=True)
        self.dashboard_plot(self.dashboard_shift,temp-273.15,wl-wl[0],'Temperature (°C)','Δλ (nm)')
        self.dashboard_plot(self.dashboard_rolloff,current,temp-273.15,'Current (mA)','Junction temperature (°C)')
        bw=m['bandwidth_3db_ghz']; peak=float(power[-1]); values=(f"{r['threshold_current_ma']:.1f} mA",f'{peak:.1f} mW',f"{r['slope_efficiency_w_per_a']:.2f} W/A",f'{bw:.1f} GHz' if bw is not None else '> span','Not calculated',f'{wl[-1]:.1f} nm','Not calculated',f'{100*peak/max(.001,current[-1]*self.series_voltage.value()):.1f} %')
        for card,caption,value in zip(self.dashboard_kpis,('Threshold Current','Output Power (I max)','Slope Efficiency','3-dB Bandwidth','SMSR','Lasing Wavelength','Thermal Roll-off (T₀)','Power Conversion Efficiency'),values): card.setText(f'{caption}\n{value}')

    def dashboard_plot(self,canvas,x,y,xlabel,ylabel,logx=False):
        fig=canvas.figure; fig.clear(); ax=fig.add_subplot(111); self.style(fig,ax); ax.plot(x,y,color='#35aaff',lw=1.6); ax.fill_between(x,y,0,color='#168bd0',alpha=.12)
        if logx: ax.set_xscale('log')
        ax.set_xlabel(xlabel,fontsize=7); ax.set_ylabel(ylabel,fontsize=7); ax.tick_params(labelsize=6); fig.set_layout_engine('constrained'); canvas.draw_idle()
    def plot_mode(self,d):
        fig=self.mode_canvas.figure;fig.clear();ax=fig.add_subplot(111);ax.set_axis_off();ax.text(.5,.5,'Enter independently calculated mode parameters above.\nA finite-device PCSEL eigenmode solve is not performed by this steady-state laser estimate.',ha='center',va='center',wrap=True);self.mode_canvas.draw_idle()
    def plot_laser(self,r):
        fig=self.laser_canvas.figure; fig.clear(); ax=fig.add_subplot(111); self.style(fig,ax); ax.plot(r['currents_ma'],r['output_power_mw'],color='#00cbb8',label='Analytical model');
        if r.get('comsol'): ax.plot(r['comsol']['current_ma'],r['comsol']['output_power_mw'],color='#4aa3ff',marker='o',ms=3,label='COMSOL imported')
        ax.axvline(r['threshold_current_ma'],color='#e36d91',ls='--',label='Threshold'); ax.set(title='Steady-state L–I curve',xlabel='Current (mA)',ylabel='Power (mW)'); self.finish(fig,self.laser_canvas)
    def plot_modulation(self,r):
        fig=self.modulation_canvas.figure; fig.clear(); ax=fig.add_subplot(111); self.style(fig,ax); m=r['modulation']; f=np.asarray(m['frequencies_ghz']); db=np.asarray(m['magnitude_db']); bw=m['bandwidth_3db_ghz']; fr=m['relaxation_frequency_ghz']; self.modulation_summary.setText(f"Estimated resonance {fr:.2f} GHz · estimated 3 dB bandwidth {bw:.2f} GHz · heuristic damping" if bw is not None else f"Estimated resonance {fr:.2f} GHz · bandwidth exceeds selected span · heuristic damping"); ax.plot(f,db,label='Heuristic response estimate'); ax.axhline(-3,color='#e36d91',ls='--',label='−3 dB'); ax.set(title='Estimated modulation response',xlabel='Frequency (GHz)',ylabel='Response (dB)',ylim=(-30,5)); self.finish(fig,self.modulation_canvas)
    def plot_thermal(self,r):
        fig=self.thermal_canvas.figure; fig.clear(); ax=fig.add_subplot(111); self.style(fig,ax); current=np.asarray(r['currents_ma']); temp=np.asarray([x['temperature_k'] for x in r['sweep']]); wl=np.asarray([x['wavelength_nm'] for x in r['sweep']]); ax.plot(current,temp,color='#e36d91',label='Junction temperature'); ax.set(title='Self-consistent lumped thermal model',xlabel='Current (mA)',ylabel='Temperature (K)'); self.thermal_summary.setText(f'At {current[-1]:.1f} mA: {temp[-1]:.1f} K · {wl[-1]:.2f} nm'); self.finish(fig,self.thermal_canvas)
    def populate_modes(self,d,r):
        self.mode_table.setRowCount(1)
        values=['User-supplied mode',f'{self.wavelength.value():.2f}',f'{self.quality_factor.value():.4g}',f'{self.confinement.value():.3f}',f"{r['threshold_gain_cm-1']:.3g}",'Not calculated']
        for col,value in enumerate(values):self.mode_table.setItem(0,col,QTableWidgetItem(value))
    def plot_sensitivity(self,d):
        fig=self.optimization_canvas.figure;fig.clear();ax=fig.add_subplot(111);ax.set_axis_off();ax.text(.5,.5,'No mode competition or geometry sensitivity solve has been run.',ha='center',va='center',wrap=True);self.optimization_canvas.draw_idle()
    def _report_geometry(self,d):
        return (f'Optional geometry context (not used by this scalar calculation):\n'
                    f'Device: {self.device_type.currentText()}\nLattice: {self.lattice.currentText()}\n'
                    f'Period: {d.period_um:.4g} µm\nHole radius: {d.hole_radius_um:.4g} µm\n'
                    f'Fill factor: {d.fill_factor:.4%}\n') if d is not None else (
                    'Optional geometry context: unavailable or incomplete; not used by this scalar calculation.\n')
    def write_report(self,d,r):
        inputs=r.get('inputs',{})
        context=r.get('report_context',{})
        geometry=context.get('geometry',self._report_geometry(d))
        wavelength=inputs.get('wavelength_nm',self.wavelength.value())
        quality_factor=inputs.get('quality_factor',self.quality_factor.value())
        confinement=inputs.get('confinement',self.confinement.value())
        mode_volume=context.get('mode_volume',self.mode_volume.value())
        fidelity=context.get('fidelity',self.fidelity.currentText())
        warning='INPUTS CHANGED: this report retains the previous calculation inputs. Run again to update it.\n\n' if self._results_stale else ''
        self.report.setPlainText(warning+f"PCSEL LASER SIMULATION / PERFORMANCE REPORT\n\n{geometry}Target wavelength: {wavelength:.4g} nm\n\nOPTICAL\nQ: {quality_factor:.6g}\nConfinement: {confinement:.6g}\nMode volume: {mode_volume:.6g} (lambda/n)^3\nPhoton lifetime: {r['photon_lifetime_ps']:.6g} ps\n\nTHRESHOLD AND OUTPUT\nThreshold gain: {r['threshold_gain_cm-1']:.6g} cm^-1\nThreshold carrier density: {r['threshold_density_cm-3']:.6g} cm^-3\nThreshold current: {r['threshold_current_ma']:.6g} mA\nSlope efficiency: {r['slope_efficiency_w_per_a']:.6g} W/A\nOutput at {r['currents_ma'][-1]:.6g} mA: {r['output_power_mw'][-1]:.6g} mW\n\nMETHOD\nSteady-state ABC recombination, linear material gain, Q-derived photon lifetime from user-supplied mode parameters, carrier clamping above threshold, heuristic modulation, and lumped thermal estimate. No time-dependent rate equations are solved. Modulation carrier lifetime is 1 / max(A, 1 s^-1); damping is max(0.1, 0.7 * resonance frequency) GHz.\nFidelity: {fidelity}.")
    def export_report(self,path=None):
        if path is False or path is None: path,_=QFileDialog.getSaveFileName(self,'Export laser report','laser_pcsel_report.txt','Text report (*.txt)')
        if not path: return None
        target=Path(path); target.write_text(self.report.toPlainText(),encoding='utf-8'); return target

    def numerical_result_snapshot(self):
        """Copy the completed result; exporting never reads current physical inputs."""
        if self.last_result is None:
            raise ValueError('Run the analytical laser model before exporting numerical results.')
        result=deepcopy(self.last_result)
        result['export_metadata']=dict(schema='optical-design-studio/laser-export/v1',
            exported_at_utc=datetime.now(timezone.utc).isoformat(),
            inputs_changed_since_calculation=bool(self._results_stale),
            result_status='completed_for_previous_inputs' if self._results_stale else 'completed',
            input_provenance='Captured inputs and calculation_context belong to this completed calculation; live edited controls are not substituted.',
            table_units=dict(current_ma='mA',carrier_density_cm_3='cm^-3',photon_density_cm_3='cm^-3',
                output_power_mw='mW',temperature_k='K',wavelength_nm='nm',wall_plug_efficiency='1',
                relaxation_frequency_ghz='GHz',frequencies_ghz='GHz',magnitude_linear='1',magnitude_db='dB'))
        return result

    @staticmethod
    def _numerical_json(result):
        def encode(value):
            if isinstance(value,np.ndarray):return value.tolist()
            if isinstance(value,np.generic):return value.item()
            if isinstance(value,Path):return str(value)
            raise TypeError('Unsupported numerical result value: '+type(value).__name__)
        return json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False,default=encode)+'\n'

    def export_result_json(self,path=None):
        return self._export_numerical_result('json',path)

    def export_sweep_csv(self,path=None):
        return self._export_numerical_result('sweep',path)

    def export_modulation_csv(self,path=None):
        return self._export_numerical_result('modulation',path)

    def _export_numerical_result(self,kind,path=None):
        try:
            result=self.numerical_result_snapshot()
            raw_json=self._numerical_json(result)
            if path is False or path is None:
                default='laser_pcsel_result.json' if kind=='json' else 'laser_pcsel_'+kind+'.csv'
                title='Export raw numerical laser result' if kind=='json' else 'Export laser '+kind+' CSV and result JSON'
                path,_=QFileDialog.getSaveFileName(self,title,default,'JSON (*.json)' if kind=='json' else 'CSV (*.csv)')
            if not path:return None
            target=Path(path)
            if kind=='json':
                target.write_text(raw_json,encoding='utf-8')
                paths=[target]
            else:
                source=target.with_suffix('.result.json')
                if kind=='sweep':
                    mapping=[('current_ma','current_mA'),('carrier_density_cm_3','carrier_density_cm^-3'),
                        ('photon_density_cm_3','photon_density_cm^-3'),('output_power_mw','output_power_mW'),
                        ('temperature_k','temperature_K'),('wavelength_nm','wavelength_nm'),
                        ('wall_plug_efficiency','wall_plug_efficiency_1'),('relaxation_frequency_ghz','relaxation_frequency_GHz')]
                    points=result.get('sweep',[])
                    if not points:raise ValueError('The completed result has no current-sweep samples to export.')
                else:
                    modulation=result.get('modulation',{})
                    keys=('frequencies_ghz','magnitude_linear','magnitude_db')
                    values=[modulation.get(key,[]) for key in keys]
                    if not len(values[0]) or any(len(value)!=len(values[0]) for value in values):
                        raise ValueError('The completed result has no complete modulation arrays to export.')
                    points=[dict(zip(keys,row),bias_current_ma=modulation['bias_current_ma']) for row in zip(*values)]
                    mapping=[('frequencies_ghz','frequency_GHz'),('magnitude_linear','magnitude_linear_1'),
                        ('magnitude_db','magnitude_dB'),('bias_current_ma','bias_current_mA')]
                buffer=io.StringIO(newline='')
                writer=csv.writer(buffer)
                writer.writerow([title for _,title in mapping]+['result_id','inputs_changed_since_calculation','source_result_json'])
                for point in points:
                    writer.writerow([point[key] for key,_ in mapping]+[result.get('calculation_context',{}).get('result_id',''),
                        str(result['export_metadata']['inputs_changed_since_calculation']).lower(),source.name])
                # Build both serializations before touching either destination.
                source.write_text(raw_json,encoding='utf-8')
                target.write_text(buffer.getvalue(),encoding='utf-8',newline='')
                paths=[target,source]
            self.status.setProperty('error',False)
            self.status.setText('Exported '+', '.join(item.name for item in paths)+
                (' · inputs changed; saved data retain the completed calculation inputs.' if self._results_stale else ' · full numerical precision.'))
            return target
        except (ValueError,TypeError,KeyError,OSError) as exc:
            self.status.setProperty('error',True);self.status.setText('Numerical export failed: '+str(exc))
            return None

    def import_comsol(self,path=None):
        if path is False or path is None: path,_=QFileDialog.getOpenFileName(self,'Import COMSOL laser results','','COMSOL manifest (*.json)')
        if not path: return None
        if self.last_result is None and self.run_simulation() is None:return None
        try:
            imported=load_comsol_power_results(path); self.last_result=merge_comsol_power(self.last_result,imported)
        except (ValueError,OSError) as exc:
            self.status.setProperty('error',True); self.status.setText(f'COMSOL import failed: {exc}'); return None
        self._comsol_imported=imported
        self.status.setProperty('error',False); self.status.setText(f"COMSOL results imported · {imported.provenance.get('model_name','model')}")
        self._render_comsol();self.retheme()
        return imported

    def _render_comsol(self):
        self.plot_laser(self.last_result); d=self._optional_design_context(); self.write_report(d,self.last_result)
        self.solver_status.setText('Optical parameters: supplied by user\n\nS4 / Meep: not run\n\nCOMSOL: external power imported\n\nSteady-state estimate: calculation complete')
        details=self.last_result['comsol']; self.report.appendPlainText(f"\n\nCOMSOL IMPORT\nModel: {details['provenance'].get('model_name','')}\nStudy: {details['provenance'].get('study','')}\nSamples: {len(details['current_ma'])}\nManifest: {details['manifest_path']}")
