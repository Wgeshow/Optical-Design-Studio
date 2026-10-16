"""Carrier-density input dialog for the layer-selective index sweep."""
from PyQt6.QtCore import Qt,QTimer
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,
    QTableWidget,QTableWidgetItem,QHeaderView,QPushButton,QDialogButtonBox,QCheckBox,QFileDialog,QMessageBox,QComboBox,QTabWidget,QWidget)
from carrier_index import validate_configuration,read_states_csv,evaluate_state,LIMITATION
_PARAMETER_POOL=ThreadPoolExecutor(max_workers=2,thread_name_prefix='ioffe')

class CarrierIndexDialog(QDialog):
    def __init__(self,parent=None,configuration=None,options=None):
        super().__init__(parent)
        self.setWindowTitle('Carrier-induced index change and junction calculations')
        self.resize(1000,850)
        cfg=configuration or options or {}
        layout=QVBoxLayout(self)
        title=QLabel('Carrier concentrations → material Δn and Δk')
        title.setStyleSheet('font-size:18px;font-weight:600')
        layout.addWidget(title)
        note=QLabel('Approximate free-carrier Drude calculation. Choose conductivity masses and mobilities appropriate to the material. Imported depth profiles are resolved into S4 slices; voltage alone does not determine a carrier profile.');note.setWordWrap(True);layout.addWidget(note)
        tabs=QTabWidget();layout.addWidget(tabs)
        optical=QWidget();layout=QVBoxLayout(optical);tabs.addTab(optical,'Carrier modulation')
        self.semiconductor=QComboBox();self.semiconductor.addItems(['Si','GaAs','AlGaAs','Custom'])
        self.semiconductor.setCurrentText(cfg.get('parameter_material',cfg.get('semiconductor','Si')))
        layout.addWidget(self.semiconductor)
        lookup=QHBoxLayout();lookup.addWidget(QLabel('Al fraction x'))
        self.alloy_x=QLineEdit(str(cfg.get('alloy_x',.3)));lookup.addWidget(self.alloy_x)
        self.fetch_button=QPushButton('Refresh from Ioffe');self.fetch_button.clicked.connect(lambda:self.fetch_parameters(True));lookup.addWidget(self.fetch_button);layout.addLayout(lookup)
        self.parameter_status=QLabel('Material selection loads Ioffe parameters. Missing or incompatible values remain editable.');self.parameter_status.setWordWrap(True);layout.addWidget(self.parameter_status)
        self.parameter_record=cfg.get('parameter_record',{})
        self.parameter_future=None;self.parameter_timer=QTimer(self);self.parameter_timer.setInterval(100);self.parameter_timer.timeout.connect(self.finish_parameters)
        self.alloy_x.editingFinished.connect(lambda:self.fetch_parameters())
        self.profiles={s['label']:s.get('profiles',[]) for s in cfg.get('states',[]) if s.get('profiles')}
        form=QFormLayout();self.fields={}
        for key,label,default in [('reference_electron_cm3','Reference electrons (cm⁻³)',0),('reference_hole_cm3','Reference holes (cm⁻³)',0),('mass_e_m0','Electron conductivity mass / m₀',.26),('mass_h_m0','Hole conductivity mass / m₀',.39),('mobility_e_cm2_Vs','Electron mobility (cm²/V·s)',1350),('mobility_h_cm2_Vs','Hole mobility (cm²/V·s)',480),('profile_slices','Slices per profiled layer',20)]:
            edit=QLineEdit(f'{cfg.get(key,default):g}');self.fields[key]=edit;form.addRow(label,edit)
        layout.addLayout(form)
        self.hole_model=QComboBox();self.hole_model.addItems(['Conductivity mass / manual','Heavy-hole approximation','Light-hole approximation'])
        self.hole_model.setCurrentText(cfg.get('hole_mass_model','Conductivity mass / manual'))
        self.hole_model.currentTextChanged.connect(self.apply_hole_mass)
        layout.addWidget(self.hole_model)
        self.optical_reference=QComboBox();self.optical_reference.addItems(['Library already includes reference carriers','Library is undoped: add carriers to both states'])
        self.optical_reference.setCurrentIndex(1 if cfg.get('optical_reference')=='undoped' else 0)
        layout.addWidget(self.optical_reference)
        self.profile_sampling=cfg.get('profile_sampling','uniform')
        self.comsol_report=cfg.get('comsol_report',{})
        self.semiconductor.currentTextChanged.connect(self.change_material)
        hint=QLabel('Enter absolute concentrations, not ΔN. Mobilities are fixed for this run. For depth data select a state, then import its profile CSV. Profiles use depth measured from the top of each named layer.')
        hint.setWordWrap(True);layout.addWidget(hint)
        self.states=QTableWidget(0,4);self.states.setHorizontalHeaderLabels(['State','Electrons (cm⁻³)','Holes (cm⁻³)','Bias label (V)'])
        self.states.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.states,1)
        for state in cfg.get('states',[dict(label='Biased',electron_cm3=1e18,hole_cm3=1e18)]):self.add_state(state)
        buttons=QHBoxLayout()
        for label,slot in [('Add state',lambda:self.add_state()),('Remove selected',self.remove_state),('Import states',self.import_csv),('Import depth profile',self.import_profile),('Calculate Δn',self.preview)]:
            b=QPushButton(label);b.clicked.connect(slot);buttons.addWidget(b)
        layout.addLayout(buttons)
        comsol_button=QPushButton('Import four COMSOL files · GaAs 200 / AlGaAs 20 / GaAs 200 nm')
        comsol_button.clicked.connect(self.import_comsol);layout.addWidget(comsol_button)
        preview_form=QFormLayout();self.preview_wavelength=QLineEdit('1550');self.preview_n=QLineEdit('3.48')
        preview_form.addRow('Calculator wavelength (nm)',self.preview_wavelength);preview_form.addRow('Calculator reference n',self.preview_n);layout.addLayout(preview_form)
        self.preview_label=QLabel('Calculator uses the n entered above. S4 uses the selected library n(λ).')
        self.preview_label.setWordWrap(True);layout.addWidget(self.preview_label)
        self.confirm=QCheckBox('Material parameters are appropriate and library n,k describe the reference carrier state.')
        self.confirm.setChecked(cfg.get('material_confirmed',cfg.get('silicon_confirmed',False)));layout.addWidget(self.confirm)
        footer=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        footer.button(QDialogButtonBox.StandardButton.Ok).setText('Use carrier states')
        footer.accepted.connect(self.accept_validated);footer.rejected.connect(self.reject);layout.addWidget(footer)
        junction=QWidget();jl=QVBoxLayout(junction);tabs.addTab(junction,'Junction estimate')
        jnote=QLabel('Abrupt, nondegenerate, uniformly doped homojunction approximation. Positive voltage means reverse bias. This estimate does not solve a GaAs/AlGaAs heterojunction or generate the imported carrier profiles.');jnote.setWordWrap(True);jl.addWidget(jnote)
        jf=QFormLayout();self.junction_fields={}
        for key,label,default in [('acceptor_cm3','Acceptor density (cm⁻³)',''),('donor_cm3','Donor density (cm⁻³)',''),('intrinsic_cm3','Intrinsic density at this temperature (cm⁻³)',''),('relative_permittivity','Relative static permittivity',''),('temperature_k','Temperature (K)','300'),('reverse_bias_v','Reverse bias (V)','0')]:
            edit=QLineEdit(default);self.junction_fields[key]=edit;jf.addRow(label,edit)
        jl.addLayout(jf);jb=QPushButton('Calculate built-in voltage and depletion width');jb.clicked.connect(self.calculate_junction);jl.addWidget(jb)
        self.junction_result=QLabel('Enter the material and doping parameters above.');self.junction_result.setWordWrap(True);jl.addWidget(self.junction_result);jl.addStretch()
        self.material_data=QTableWidget(0,3);self.material_data.setHorizontalHeaderLabels(['Parameter / units','Value','Source'])
        self.material_data.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        data_page=QWidget();data_layout=QVBoxLayout(data_page)
        self.material_notes=QLabel('Select a material to load its parameters.');self.material_notes.setWordWrap(True);data_layout.addWidget(self.material_notes)
        data_layout.addWidget(self.material_data,1);tabs.addTab(data_page,'Retrieved material data')
        self.alloy_x.setEnabled(self.semiconductor.currentText()=='AlGaAs')
        if not cfg:QTimer.singleShot(0,self.fetch_parameters)

    def change_material(self,name):
        masses={'Si':(.26,.39),'GaAs':(.067,.45)}.get(name)
        for key,value in zip(('mass_e_m0','mass_h_m0'),masses or ('','')):self.fields[key].setText(str(value))
        for key in ('mobility_e_cm2_Vs','mobility_h_cm2_Vs'):self.fields[key].clear()
        for key in ('intrinsic_cm3','relative_permittivity'):self.junction_fields[key].clear()
        self.confirm.setChecked(False)
        self.alloy_x.setEnabled(name=='AlGaAs')
        self.fetch_parameters()

    def fetch_parameters(self,refresh=True):
        from ioffe_parameters import material_parameters
        name=self.semiconductor.currentText()
        self.parameter_future=None;self.parameter_timer.stop();self.parameter_record={}
        if name=='Custom':
            self.parameter_status.setText('Custom material: enter its parameters manually.');return
        try:x=float(self.alloy_x.text()) if name=='AlGaAs' else None
        except ValueError:self.parameter_status.setText('Enter a numeric Al fraction x.');return
        self.parameter_status.setText('Loading '+name+' parameters from Ioffe…')
        self.parameter_future=_PARAMETER_POOL.submit(material_parameters,name,x=x,refresh=bool(refresh))
        self.parameter_timer.start()

    def finish_parameters(self):
        future=self.parameter_future
        if future is None or not future.done():return
        self.parameter_timer.stop();self.parameter_future=None
        try:record=future.result()
        except Exception as exc:
            self.parameter_status.setText('Ioffe retrieval failed: '+str(exc));return
        self.parameter_record=record
        for key in ('mass_e_m0','mass_h_m0','mobility_e_cm2_Vs','mobility_h_cm2_Vs'):
            self.fields[key].clear()
        for key in ('intrinsic_cm3','relative_permittivity'):self.junction_fields[key].clear()
        for key,value in record['values'].items():
            widget=self.fields.get(key) or self.junction_fields.get(key)
            if widget is not None and value is not None:widget.setText(f'{value:g}')
        self.apply_hole_mass()
        self.junction_fields['temperature_k'].setText(str(record.get('temperature_k',300)))
        self.confirm.setChecked(False)
        status={'bundled-cache':'Reviewed Ioffe cache','mixed':'Live Ioffe data + reviewed cache','live':'Live Ioffe data'}.get(record.get('status'),str(record.get('status','Loaded')))
        self.parameter_status.setText(status+' · '+str(record.get('temperature_k',300))+' K. See Retrieved material data for sources and assumptions.\n'+('Choose a hole-mass approximation or enter a conductivity mass.' if 'mass_h_m0' in record.get('missing',[]) else 'Mobility values are starting estimates; all fields remain editable.'))
        self.material_notes.setText('\n'.join(record.get('notes',[])))
        self.parameter_status.setToolTip('\n'.join(record.get('sources',[])))
        self.material_data.setRowCount(0)
        for key,value in record['values'].items():
            row=self.material_data.rowCount();self.material_data.insertRow(row)
            for col,text in enumerate((key,str(value),str(record.get('field_sources',{}).get(key,'')))):
                item=QTableWidgetItem(text);item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable);self.material_data.setItem(row,col,item)

    def apply_hole_mass(self,*_):
        key={'Heavy-hole approximation':'heavy_hole_mass_m0','Light-hole approximation':'light_hole_mass_m0'}.get(self.hole_model.currentText(),'mass_h_m0')
        value=self.parameter_record.get('values',{}).get(key)
        if value is not None:self.fields['mass_h_m0'].setText(f'{value:g}')
        elif self.hole_model.currentIndex()!=0:self.fields['mass_h_m0'].clear()
        self.confirm.setChecked(False)

    def calculate_junction(self):
        from carrier_index import junction_estimate
        try:
            result=junction_estimate(**{k:w.text() for k,w in self.junction_fields.items()})
            self.junction_result.setText('\n'.join(f'{k}: {v:.7g}' if isinstance(v,(int,float)) else f'{k}: {v}' for k,v in result.items()))
        except (ValueError,TypeError) as exc:self.junction_result.setText(str(exc))

    def import_profile(self):
        from carrier_index import read_profile_csv
        row=self.states.currentRow()
        if row<0:QMessageBox.information(self,'Depth profile','Select a carrier state first.');return
        path,_=QFileDialog.getOpenFileName(self,'Import layer-local carrier profile','','CSV (*.csv)')
        if not path:return
        try:self.states.item(row,0).setData(Qt.ItemDataRole.UserRole,read_profile_csv(path))
        except (ValueError,OSError) as exc:QMessageBox.warning(self,'Depth profile',str(exc));return
        self.preview_label.setText('Depth profile attached to '+self.states.item(row,0).text()+'. Layer thickness coverage is checked when starting S4.')

    def import_comsol(self):
        from qt_comsol_import import ComsolCarrierImport
        parent=self.parent();names=[r['layer'] for r in parent.layer_records()] if parent is not None and hasattr(parent,'layer_records') else None
        dialog=ComsolCarrierImport(self,names if names and len(names)==2 else None)
        if not dialog.exec():return
        if self.semiconductor.currentText()!='GaAs':self.semiconductor.setCurrentText('GaAs')
        row=self.states.currentRow()
        if row<0:
            if not self.states.rowCount():self.add_state()
            row=0
        self.states.item(row,0).setData(Qt.ItemDataRole.UserRole,dialog.result['profiles'])
        self.profile_sampling='knots';self.comsol_report=dialog.result['report']
        self.preview_label.setText('COMSOL reference and biased profiles imported for both GaAs layers. AlGaAs stays unchanged. Original sample intervals will be used for S4 slices. Choose whether library optics already include reference carriers.')

    def add_state(self,state=None):
        state=state if isinstance(state,dict) else dict(label=f'State {self.states.rowCount()+1}',electron_cm3=0,hole_cm3=0)
        row=self.states.rowCount();self.states.insertRow(row)
        for col,key in enumerate(('label','electron_cm3','hole_cm3','bias_v')):
            value=state.get(key,'');self.states.setItem(row,col,QTableWidgetItem('' if value is None else str(value)))
        self.states.item(row,0).setData(Qt.ItemDataRole.UserRole,state.get('profiles',[]))

    def remove_state(self):
        for row in sorted({i.row() for i in self.states.selectedIndexes()},reverse=True):self.states.removeRow(row)

    def configuration(self):
        states=[]
        for row in range(self.states.rowCount()):
            states.append({key:(self.states.item(row,col).text() if self.states.item(row,col) else '') for col,key in enumerate(('label','electron_cm3','hole_cm3','bias_v'))})
            profiles=self.states.item(row,0).data(Qt.ItemDataRole.UserRole)
            if profiles:states[-1]['profiles']=profiles
        name=self.semiconductor.currentText()
        return validate_configuration(dict(semiconductor='Custom' if name=='AlGaAs' else name,parameter_material=name,
            alloy_x=float(self.alloy_x.text()) if name=='AlGaAs' else None,parameter_record=self.parameter_record,
            hole_mass_model=self.hole_model.currentText(),
            optical_reference='undoped' if self.optical_reference.currentIndex()==1 else 'reference',profile_sampling=self.profile_sampling,comsol_report=self.comsol_report,
            material_confirmed=self.confirm.isChecked(),silicon_confirmed=self.confirm.isChecked(),states=states,**{k:w.text() for k,w in self.fields.items()}))

    options=configuration

    def import_csv(self):
        path,_=QFileDialog.getOpenFileName(self,'Import carrier states','','CSV (*.csv)')
        if not path:return
        try:states=read_states_csv(path)
        except (ValueError,OSError) as exc:QMessageBox.warning(self,'Carrier data',str(exc));return
        self.states.setRowCount(0)
        for state in states:self.add_state(state)

    def preview(self):
        try:
            cfg=self.configuration();lines=[]
            for state in cfg['states'][:6]:
                if state.get('profiles'):
                    lines.append(f"{state['label']}: depth profile attached ({len(state['profiles'])} samples); S4 evaluates each slice.")
                    continue
                v=evaluate_state(float(self.preview_wavelength.text()),float(self.preview_n.text()),cfg['reference_electron_cm3'],cfg['reference_hole_cm3'],state['electron_cm3'],state['hole_cm3'],cfg['mobility_e_cm2_Vs'],cfg['mobility_h_cm2_Vs'],mass_e_m0=cfg['mass_e_m0'],mass_h_m0=cfg['mass_h_m0'],semiconductor=cfg['semiconductor'])
                lines.append(f"{state['label']}: Δn = {v['delta_n']:.5g}; Δk = {v['delta_k']:.5g}; Δα = {v['delta_alpha_cm1']:.5g} cm⁻¹")
            self.preview_label.setText('Uniform-state calculation; depth profiles are evaluated per slice in S4.\n'+'\n'.join(lines+cfg['warnings']))
        except ValueError as exc:QMessageBox.warning(self,'Carrier data',str(exc))

    def accept_validated(self):
        try:self.configuration()
        except ValueError as exc:QMessageBox.warning(self,'Carrier data',str(exc));return
        self.accept()
