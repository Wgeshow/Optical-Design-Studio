"""Layer-selective Δn controls and saved spectral comparisons."""
import json
from pathlib import Path
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.ticker import PercentFormatter
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QGroupBox,QTabWidget,QTableWidget,QTableWidgetItem,QHeaderView,QFileDialog
from qt_compute import _ResponsiveSplitter,_scroll,_RunPage,_combo,_check,_label,_button,_group,_value,_set_value,_on_edit
from qt_common import number,integer,PlotWidget,table,fill_table
from qt_ranges import _choices
from qt_surfaces import WorkspacePanel

class _ResponsePlot(PlotWidget):
    def clear(self):
        figure=Figure(figsize=(8,5),layout='constrained')
        axis=figure.add_subplot(111)
        axis.set(xlabel='Wavelength (nm)',ylabel='Optical response (%)',ylim=(0,1))
        axis.yaxis.set_major_formatter(PercentFormatter(xmax=1))
        axis.grid(alpha=.2)
        self.draw_figure(figure)

    def draw_figure(self,figure=None):
        super().draw_figure(figure)
        if self.toolbar:self.toolbar.hide()

    def retheme(self):
        super().retheme()
        if self.toolbar:self.toolbar.hide()

class IndexShiftPage(_RunPage):
    def __init__(self,store,parent=None):
        super().__init__(store,'Refractive-index shift','Sweep a manual Δn or calculate material index and absorption changes from carrier concentrations.',{'index_shift'},parent)
        self.loading=False
        self.layout_.setContentsMargins(8,10,8,10)
        left=QWidget();right=WorkspacePanel();details=WorkspacePanel()
        controls,output,detail_layout=QVBoxLayout(left),QVBoxLayout(right),QVBoxLayout(details)
        controls.setContentsMargins(10,10,10,10)
        output.setContentsMargins(12,12,12,12)
        detail_layout.setContentsMargins(10,10,10,10)
        self.setup_layout=controls
        controls.addWidget(_label('Simulation Setup'))
        output.addWidget(_label('Simulation Results'))
        detail_layout.addWidget(_label('Shifted design details'))
        self.material=_combo([])
        self.sweep_mode=_combo(['Manual Δn','Carrier density'])
        self.carrier_configuration={}
        self.carrier_button=_button('Set electron / hole concentrations…',self.configure_carriers)
        self.carrier_note=_label('Enter reference and biased concentrations in cm⁻³. The selected layers share each carrier state.',True)
        self.equal=_check('Equal shift across selected layers',True)
        self.material.setToolTip('Shift only this material in checked layers, including patterned regions. Other material occurrences retain their original index.')
        self.equal.setToolTip('Apply the shared Δn range to every checked layer. Clear to edit independent ranges in Layers to shift.')
        self.controls=dict(start=number(0,-10,10,6),stop=number(.02,-10,10,6),samples=integer(3,1,101),
            response=_combo(['Reflection','Transmission','Absorption']),feature=_combo(['Peak','Dip']),
            reference_nm=number(1550,.000001),tracking_window_nm=number(30,.000001))
        box,form=_group('Material and coupling',[('Material',self.material)])
        form.addRow('Index model',self.sweep_mode)
        form.addRow(self.carrier_button)
        form.addRow(self.carrier_note)
        form.addRow(self.equal);controls.addWidget(box)
        self.shared,_=_group('Shared Δn sweep',[('Start Δn (RIU)',self.controls['start']),('Stop Δn (RIU)',self.controls['stop']),('Samples',self.controls['samples'])])
        controls.addWidget(self.shared)
        controls.addWidget(_label('Only occurrences of this material in checked layers are shifted, including patterned regions. Unchecked layers keep their original index.',True))
        tracking,_=_group('Sampled resonance tracking',[(label,self.controls[key]) for label,key in [('Response','response'),('Feature','feature'),('Reference λ (nm)','reference_nm'),('Search radius (nm)','tracking_window_nm')]])
        tracking.setToolTip('Track the nearest sampled peak or dip inside the search radius. Wavelength range, incident light, basis and performance are shared with S4 · RCWA. A zero-shift baseline is included.')
        controls.addWidget(tracking)
        self.window_label=_label('',True);controls.addWidget(self.window_label)
        controls.addWidget(_label('Set the wavelength range and incident light on the S4 · RCWA tab. A Δn=0 baseline is always included. Basis and performance settings are shared.',True))
        controls.addStretch()
        actions=self.actions('Run Δn sweep',self.run)
        layers=QGroupBox('Layers to shift')
        layout=QVBoxLayout(layers)
        self.layers=QTableWidget(0,5)
        self.layers.setHorizontalHeaderLabels(['Shift','Layer / material location','Start Δn','Stop Δn','Samples'])
        self.layers.verticalHeader().hide()
        self.layers.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        for col,width in [(0,55),(2,112),(3,112),(4,90)]: self.layers.setColumnWidth(col,width)
        self.layers.setMinimumHeight(110)
        self.layers.setMaximumHeight(240)
        layout.addWidget(self.layers)
        self.count_label=_label('');layout.addWidget(self.count_label)
        detail_layout.addWidget(layers)
        self.readout_view=_combo(['Fixed-wavelength response','Change from baseline','Overlaid spectra'])
        self.readout_layer=_combo([])
        readout_controls=QHBoxLayout()
        readout_controls.addWidget(_label('Plot'))
        readout_controls.addWidget(self.readout_view,1)
        readout_controls.addWidget(_label('Δn axis'))
        readout_controls.addWidget(self.readout_layer,1)
        output.addLayout(readout_controls)
        self.locked_label=_label('The Δn = 0 peak sets one fixed wavelength for every shifted case.',True)
        output.addWidget(self.locked_label)
        self.readout_view.currentIndexChanged.connect(self.redraw_result)
        self.readout_layer.currentIndexChanged.connect(self.redraw_result)
        self.saved_spectra=None;self.saved_summary=None;self.saved_readout=None
        metrics=QHBoxLayout()
        self.metrics={}
        for key,title in [('wavelength','Baseline λ'),('spectra','Spectra'),('shift','Peak shift')]:
            card=QGroupBox(title);card_layout=QVBoxLayout(card)
            value=_label('—');value.setObjectName('metricValue');card_layout.addWidget(value)
            self.metrics[key]=value;metrics.addWidget(card)
        output.insertLayout(1,metrics)
        self.plot=_ResponsePlot();self.plot.setMinimumHeight(320)
        self.feature_table=table([])
        self.readout_table=table([])
        tabs=QTabWidget();tabs.addTab(self.plot,'Response plot');tabs.addTab(self.readout_table,'Fixed-wavelength data');tabs.addTab(self.feature_table,'Resonance shifts')
        output.addWidget(tabs,1)
        self.result_note=_label('No sweep yet. Shared sweeps report Δλ/Δn in nm/RIU; independent sweeps report the shift for each combination.',True)
        detail_layout.addWidget(self.result_note)
        result_box=QGroupBox('Run summary');result_layout=QVBoxLayout(result_box)
        self.summary_label=_label('—');result_layout.addWidget(self.summary_label)
        detail_layout.addWidget(result_box)
        detail_layout.addStretch()
        buttons=QVBoxLayout();buttons.addWidget(_button('Load saved Δn result',self.load_saved));buttons.addWidget(_button('Open CSV result files',self.open_results));detail_layout.addLayout(buttons)
        from qt_result_export import export_frame
        buttons.insertWidget(2,_button('Export sweep CSV…',lambda:export_frame(self,self.saved_spectra,self.status,'index-shift-spectra.csv')))
        setup=WorkspacePanel();setup.setMinimumWidth(330)
        setup_outer=QVBoxLayout(setup);setup_outer.setContentsMargins(0,0,0,0)
        setup_outer.addWidget(_scroll(left),1);setup_outer.addWidget(actions)
        details.setMinimumWidth(290)
        self.workspace_splitter=_ResponsiveSplitter(Qt.Orientation.Horizontal)
        self.workspace_splitter.reference_ratios=(.30,.44,.26)
        for pane in (setup,right,details):self.workspace_splitter.addWidget(pane)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setSizes([390,580,340])
        self.workspace_splitter.setStretchFactor(1,1)
        self.layout_.addWidget(self.workspace_splitter,1);self.footer()
        self.material.currentIndexChanged.connect(self.rebuild_layers)
        self.equal.toggled.connect(self.changed)
        self.sweep_mode.currentIndexChanged.connect(self.changed)
        for widget in self.controls.values(): _on_edit(widget,self.changed)
        store.changed.connect(self.refresh)
        self.refresh()

    def layer_records(self):
        records=[]
        for row in range(self.layers.rowCount()):
            if self.layers.cellWidget(row,0).isChecked():
                records.append(dict(layer=self.layers.item(row,1).data(Qt.ItemDataRole.UserRole),
                    start=self.layers.cellWidget(row,2).value(),stop=self.layers.cellWidget(row,3).value(),samples=self.layers.cellWidget(row,4).value()))
        return records

    def options(self):
        carrier=self.sweep_mode.currentIndex()==1
        return dict(material=self.material.currentData() or '',equal=True if carrier else self.equal.isChecked(),
            sweep_mode='carrier' if carrier else 'manual',carrier=self.carrier_configuration,
            layers=self.layer_records(),**{k:_value(w) for k,w in self.controls.items()})

    def configure_carriers(self):
        from qt_carrier_index import CarrierIndexDialog
        dialog=CarrierIndexDialog(self,configuration=self.carrier_configuration)
        if dialog.exec():
            self.carrier_configuration=dialog.configuration()
            self.changed()

    def refresh(self,*_):
        if self.loading:return
        saved=self.store.search_state.get('index_shift',{})
        self.loading=True
        selected=saved.get('material',self.material.currentData())
        names=[str(n) for n in self.store.materials['Name'] if str(n).strip()]
        _choices(self.material,[(n,n) for n in names],selected)
        self.equal.setChecked(saved.get('equal',True))
        self.sweep_mode.setCurrentIndex(1 if saved.get('sweep_mode')=='carrier' else 0)
        self.carrier_configuration=saved.get('carrier',{})
        for k,w in self.controls.items():
            if k in saved:_set_value(w,saved[k])
        self.loading=False
        self.rebuild_layers(saved=saved)
        s=self.store.settings
        self.window_label.setText(f"Current wavelengths: {s.get('wl_start_nm',0):g}–{s.get('wl_stop_nm',0):g} nm · step {s.get('wl_step_nm',0):g} nm")

    def rebuild_layers(self,*_,saved=None):
        if self.loading:return
        self.loading=True
        previous={r['layer']:r for r in (saved or {}).get('layers',[])}
        material=self.material.currentData()
        self.layers.setRowCount(0)
        for layer in self.store.layers.to_dict('records'):
            name=layer['Name']
            patterns=[r for r in self.store.patterns.to_dict('records') if r['Layer']==name and r['Material']==material]
            background=layer['Material']==material
            if not background and not patterns:continue
            row=self.layers.rowCount();self.layers.insertRow(row)
            check=_check('',name in previous)
            self.layers.setCellWidget(row,0,check)
            text=name+' · '+('background' if background else '')+(' + ' if background and patterns else '')+(f'{len(patterns)} region(s)' if patterns else '')
            item=QTableWidgetItem(text);item.setData(Qt.ItemDataRole.UserRole,name);item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable);self.layers.setItem(row,1,item)
            data=previous.get(name,dict(start=0,stop=.02,samples=3))
            for col,key in [(2,'start'),(3,'stop'),(4,'samples')]:
                widget=integer(data[key],1,101) if key=='samples' else number(data[key],-10,10,6)
                self.layers.setCellWidget(row,col,widget);_on_edit(widget,self.changed)
            check.toggled.connect(self.changed)
        self.loading=False
        self.update_coupling()

    def update_coupling(self):
        carrier=self.sweep_mode.currentIndex()==1
        equal=carrier or self.equal.isChecked();self.shared.setEnabled(equal and not carrier)
        self.shared.setVisible(not carrier);self.equal.setVisible(not carrier)
        self.carrier_button.setVisible(carrier);self.carrier_note.hide()
        profiled=any(s.get('profiles') for s in self.carrier_configuration.get('states',[]))
        self.carrier_note.setText(f"{len(self.carrier_configuration.get('states',[]))} biased states configured · "+('layer-specific depth profiles; geometry is preserved through all slices.' if profiled else 'same concentrations in every selected layer. Both n and k change with wavelength.'))
        self.carrier_button.setToolTip(self.carrier_note.text())
        for col in (2,3,4):self.layers.setColumnHidden(col,equal)
        for row in range(self.layers.rowCount()):
            enabled=self.layers.cellWidget(row,0).isChecked() and not equal
            for col in (2,3,4):self.layers.cellWidget(row,col).setEnabled(enabled)
        from index_shift import sweep_values
        try:
            records=self.layer_records()
            if not records: text='Select one or more layers.'
            elif carrier:
                text=f"{len(records)} selected layers · {1+len(self.carrier_configuration.get('states',[]))} spectra including reference carrier state"
            elif equal:
                values=sweep_values(_value(self.controls['start']),_value(self.controls['stop']),_value(self.controls['samples']))
                total=len(values)+(0 if 0 in values else 1)
                text=f'{len(records)} selected layers · {total} spectra including baseline · identical Δn in every selected layer'
            else:
                import math
                grids=[sweep_values(r['start'],r['stop'],r['samples']) for r in records]
                total=math.prod(len(g) for g in grids)+(0 if all(0 in g for g in grids) else 1)
                text=f'{total} spectra including baseline · all combinations of the per-layer ranges (maximum 201 with baseline)'
            self.count_label.setText(text)
        except ValueError as exc:self.count_label.setText(str(exc))

    def changed(self,*_):
        if self.loading:return
        self.update_coupling()
        try:self.store.save_search('index_shift',self.options())
        except Exception as exc:self.status.setText(str(exc))

    def run(self):
        try:
            options=self.options();self.store.save_search('index_shift',options)
            self._start('index_shift',options)
        except Exception as exc:self.status.setText(str(exc))

    def load_saved(self):
        directory=QFileDialog.getExistingDirectory(self,'Open a saved index-shift run',str(self.store.library.runs))
        if directory:
            try:self.directory=Path(directory);self.show_result({})
            except Exception as exc:self.status.setText(str(exc))

    def show_result(self,event):
        summary=json.loads((self.directory/'search_summary.json').read_text())
        spectra=pd.read_csv(self.directory/'index_shift_spectra.csv')
        features=pd.read_csv(self.directory/'index_shift_features.csv')
        from index_shift import fixed_wavelength_readout
        self.saved_summary=summary;self.saved_spectra=spectra
        self.saved_readout=pd.DataFrame(fixed_wavelength_readout(spectra.to_dict('records'),summary))
        fill_table(self.readout_table,self.saved_readout)
        fill_table(self.feature_table,features)
        self.readout_layer.blockSignals(True)
        _choices(self.readout_layer,[(name,name) for name in summary['layers']],self.readout_layer.currentData())
        self.readout_layer.blockSignals(False)
        self.readout_layer.setEnabled(not summary['equal'] or summary.get('depth_profiles',False))
        wavelength=summary.get('baseline_nm')
        if wavelength is None:
            self.locked_label.setText('No baseline peak/dip was resolved. Refine the wavelength step or adjust the reference/search range.')
        else:
            value=self.saved_readout.iloc[0]['baseline_value']
            self.locked_label.setText(f"Locked wavelength: {wavelength:g} nm · Δn = 0 {summary['feature'].lower()} · baseline {summary['response'].lower()} = {value:.6g}. Every case is measured at this same wavelength.")
        self.metrics['wavelength'].setText('—' if wavelength is None else f'{wavelength:g} nm')
        self.metrics['spectra'].setText(str(summary['spectra']))
        shifts=pd.to_numeric(features.get('shift_nm',pd.Series(dtype=float)),errors='coerce').dropna()
        self.metrics['shift'].setText('—' if shifts.empty else f'{shifts.iloc[-1]:+.4g} nm')
        self.summary_label.setText(f"{summary['material']} · {summary['response']}\n{len(summary['layers'])} layers · {summary['spectra']} spectra\n"+('Carrier density' if summary.get('sweep_mode')=='carrier' else 'Manual Δn'))
        self.locked_label.setToolTip(self.locked_label.text())
        self.locked_label.setVisible(wavelength is None)
        self.redraw_result()
        self.status.setText(f"Completed {summary['spectra']} spectra. Original library materials are unchanged.")

    def redraw_result(self,*_):
        if self.saved_summary is None:return
        summary=self.saved_summary;spectra=self.saved_spectra
        figure=Figure(figsize=(8,4),layout='constrained');axis=figure.add_subplot(111)
        column={'Reflection':'R','Transmission':'T','Absorption':'A'}[summary['response']]
        groups=list(spectra.groupby('case'))
        view=self.readout_view.currentData()
        count=0
        if view=='Overlaid spectra':
            for case,frame in groups[:24]:
                label='Baseline Δn=0' if case==0 else ', '.join(n+' '+f"{frame.iloc[0]['dn:'+n]:+.4g}" for n in summary['layers'])
                axis.plot(frame.wavelength_nm,frame[column],label=label)
            if summary.get('baseline_nm') is not None:axis.axvline(summary['baseline_nm'],color='#888888',ls='--',label='Fixed readout wavelength')
            axis.set(xlabel='Wavelength (nm)',ylabel=summary['response']+' (%)',title='Carrier-induced index and absorption change' if summary.get('sweep_mode')=='carrier' else 'Real-index shift · k held fixed')
            count=len(groups)
        elif summary.get('baseline_nm') is None:
            axis.text(.5,.5,'No resolved baseline feature.\nAdjust the wavelength range or sampling.',ha='center',va='center',transform=axis.transAxes)
            axis.set_axis_off()
        else:
            frame=self.saved_readout
            layer=self.readout_layer.currentData() or summary['layers'][0]
            x='dn:'+layer
            other=[] if summary['equal'] or summary.get('depth_profiles') else ['dn:'+n for n in summary['layers'] if n!=layer]
            curves=list(frame.groupby(other[0] if len(other)==1 else other,dropna=False)) if other else [(None,frame)]
            for fixed,subset in curves[:24]:
                subset=subset.sort_values(x)
                label=layer if summary.get('depth_profiles') else 'All selected layers' if summary['equal'] else ', '.join(key[3:]+' '+f'{subset.iloc[0][key]:+.5g}' for key in other) or layer
                axis.plot(subset[x],subset['delta_value' if view=='Change from baseline' else 'value'],marker='o',label=label)
            wavelength=summary['baseline_nm']
            axis.set(xlabel=('Thickness-averaged Δn (RIU) · '+layer if summary.get('depth_profiles') else 'Refractive-index change, Δn (RIU)'+(' · '+layer if not summary['equal'] else '')),
                ylabel=('Change in ' if view=='Change from baseline' else '')+summary['response'].lower()+f' at {wavelength:g} nm '+('(percentage points)' if view=='Change from baseline' else '(%)'),
                title=f'Fixed-wavelength readout · λ₀ = {wavelength:g} nm')
            if view=='Change from baseline':axis.axhline(0,color='#888888',lw=.8,ls='--')
            count=len(curves)
        axis.yaxis.set_major_formatter(PercentFormatter(xmax=1))
        axis.set_ylim((-1,1) if view=='Change from baseline' else (0,1))
        axis.grid(alpha=.2)
        if axis.get_legend_handles_labels()[0]:axis.legend(fontsize=8,loc='best')
        self.plot.draw_figure(figure)
        coupling='depth profiles; Δn axis is a layer thickness average, not mode effective index' if summary.get('depth_profiles') else 'equal Δn' if summary['equal'] else 'independent per-layer Δn'
        self.result_note.setText(f"Displayed run: {coupling}, {summary['spectra']} spectra. Fixed-wavelength values use the Δn = 0 feature, even if shifted peaks move outside the tracking window."+(f' First 24 curves shown; all data available in the table.' if count>24 else ''))
        self.result_note.setToolTip(summary['note'])
