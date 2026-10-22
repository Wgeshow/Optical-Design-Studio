"""Native AI Search tab: range collection, training, validation, search and review."""
import copy
from pathlib import Path
from matplotlib.figure import Figure
import pandas as pd
from PyQt6.QtCore import QSignalBlocker, pyqtSignal
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QTabWidget,QFileDialog,QLineEdit,QCheckBox,QComboBox,QLabel,QPushButton
from qt_compute import _RunPage,_group,_combo,_check,_button,_value,_set_value,_on_edit,_scroll,_ResponsiveSplitter
from qt_common import number,integer,table,fill_table,PlotWidget
from qt_surfaces import WorkspacePanel
from qt_ranges import BoundsEditor
from qt_core import prepare_job
from data_library import read_json
from qt_field_volume import FieldVolumeWidget
from ai_campaign import DEFAULTS
from ai_campaign_plots import field_figure,line_figure,rta_figure,validation_figure

class AISearchPage(_RunPage):
    routeRequested=pyqtSignal(str)
    def __init__(self,store,parent=None):
        super().__init__(store,'AI Search','Scan parameter ranges, train from S4 fields, and search with an optional simulation limit.',{'ai_search'},parent)
        self.records=[];self._loading=True;self.campaign=None;self.fields_cache={};self.contour_cache={}
        self.controls={
            'basis':integer(32,1,4096),'polarization':_combo([('p · TM','p'),('s · TE','s'),('45° · s + p','45° s+p')]),
            'theta_deg':number(0,-89.999999,89.999999,3),'phi_deg':number(0,-360,360,3),
            'wavelength_nm':number(1550,1,1e6,2),'mode':_combo([('Adaptive range sampling','Budgeted adaptive'),'Full range scan']),
            'initial':QLineEdit('20'),'test_count':QLineEdit('5'),'adaptive':QLineEdit('15'),'new_budget':QLineEdit('0'),
            'grid':integer(9,3,40),'depth_samples':integer(3,3,40),'contour_step':number(.1,.001,100,3),
            'contrast_target':number(3,1,1000,2),'coverage_target':number(.8,0,1,2),'shell_um':number(.02,.000001,1,5),
            'finalists':QLineEdit('2'),'verification_factor':number(1.5,1.01,4,2),'verification_grid':integer(17,3,80),'agreement':number(.1,.001,1,3),
            'half_window':number(10,.1,1000,2),'rta_step':number(.5,.001,100,3),'reuse':_check('Reuse compatible completed simulations'),
            'seed':integer(42,0,2147483647),'link_holes':_check('Link aligned hole radius / position through PCS layers'),
            'approach':_combo([('Discover from strength and coverage','discover'),('Match a saved field shape','reference')]),
            'reference_weight':number(1,.01,100,2)}
        self.resume=QLineEdit();self.reference=QLineEdit();self.reference.setPlaceholderText('Fields folders separated by semicolons')
        left=WorkspacePanel();controls=QVBoxLayout(left);self.setup_tabs=QTabWidget()
        setup=QWidget();layout=QVBoxLayout(setup)
        box,_=_group('Simulation conditions',[(label,self.controls[key]) for label,key in [('Wavelength (nm)','wavelength_nm'),('Polarization','polarization')]])
        layout.addWidget(box)
        box,_=_group('Field objective',[(label,self.controls[key]) for label,key in [('Amplitude contrast','contrast_target'),('Shell coverage (0–1)','coverage_target')]])
        layout.addWidget(box)
        note=QLabel('AI ranges, incident light, sampling, and run counts are saved separately from Simulation. Geometry comes from Structure; computing resources come from Settings.');note.setWordWrap(True);layout.addWidget(note)
        self.bounds=BoundsEditor(store,allowed={'thickness','lattice_square','lattice_x','lattice_y','radius','r_over_a','center_x','center_y','layer_material','pattern_material'});layout.addWidget(self.bounds)
        bound_layout=self.bounds.layout();form_layout=bound_layout.takeAt(0).layout()
        self.bounds_editor=QWidget();self.bounds_editor.setLayout(form_layout);self.bounds_editor.hide()
        self.bounds.hint.hide();self.bounds.setToolTip(self.bounds.hint.text())
        bound_layout.removeWidget(self.bounds.overview);bound_layout.insertWidget(0,self.bounds.overview)
        self.bounds.overview.setMinimumHeight(140);self.bounds.overview.setMaximumHeight(180)
        self.edit_bounds=QPushButton('Edit parameter bounds');self.edit_bounds.setCheckable(True)
        self.edit_bounds.toggled.connect(self.bounds_editor.setVisible)
        bound_layout.insertWidget(1,self.edit_bounds);bound_layout.insertWidget(2,self.bounds_editor)
        self.bounds.add.hide();self.edit_bounds.toggled.connect(self.bounds.add.setVisible)
        layout.addWidget(self.controls['link_holes']);layout.addWidget(_button('Create ranges around current design',self.default_ranges));layout.addWidget(_button('Copy ranges from Optimize',self.copy_ranges));layout.addStretch()
        layout.removeWidget(self.bounds);layout.insertWidget(1,self.bounds)
        self.setup_tabs.addTab(_scroll(setup),'Set up')
        training=QWidget();layout=QVBoxLayout(training)
        box,_=_group('Advanced incident light and field goal',[(label,self.controls[key]) for label,key in [('Incidence θ (degrees)','theta_deg'),('Azimuth φ (degrees)','phi_deg'),('Fourier basis','basis'),('Shell width (µm)','shell_um'),('Shape goal','approach')]])
        layout.addWidget(box)
        box,_=_group('Training collection',[(label,self.controls[key]) for label,key in [('Scan method','mode'),('Initial training designs','initial'),('Independent test designs','test_count'),('Adaptive designs','adaptive'),('Optional new-design limit (0 = none)','new_budget')]])
        layout.addWidget(box);layout.addWidget(self.controls['reuse']);self.plan_label=QLabel('Preview the plan before running. Test designs never enter fitting or candidate rankings.');self.plan_label.setWordWrap(True);layout.addWidget(self.plan_label);layout.addWidget(_button('Preview count and estimated time',self.preview))
        box,_=_group('Sampling and contour detail',[(label,self.controls[key]) for label,key in [('Field grid per axis','grid'),('Volume depths per layer','depth_samples'),('Contour amplitude step','contour_step'),('RTA half-window (nm)','half_window'),('RTA step (nm)','rta_step'),('Random seed','seed')]])
        layout.addWidget(box)
        box,form=_group('Reference field', [('Saved fields directory',self.reference),('Shape weight',self.controls['reference_weight'])]);form.addRow(_button('Choose reference fields…',self.choose_reference));layout.addWidget(box)
        box,form=_group('Resume / reuse campaign',[('Checkpoint file',self.resume)]);form.addRow(_button('Open campaign…',self.open_campaign));layout.addWidget(box)
        box,_=_group('Higher-accuracy verification',[(label,self.controls[key]) for label,key in [('Finalists','finalists'),('Fourier basis multiplier','verification_factor'),('Verification field grid','verification_grid'),('Relative agreement tolerance','agreement')]])
        layout.addWidget(box)
        layout.addWidget(self.actions('Collect and train',lambda:self.run('collect')));layout.addWidget(self.actions('Fit / check saved data only',lambda:self.run('fit')))
        self.setup_tabs.addTab(_scroll(training),'Training')
        search=QWidget();sl=QVBoxLayout(search);hint=QLabel('AI Search alternates S4 measurements and contour-informed Bayesian proposals. It reserves independent test designs and keeps screening and verification results separate.');hint.setWordWrap(True);sl.addWidget(hint);sl.addWidget(self.actions('Run AI search',lambda:self.run('search')));sl.addWidget(self.actions('Verify current leaders',lambda:self.run('verify')));sl.addWidget(_button('Open saved files',self.open_results));sl.addStretch();self.setup_tabs.addTab(search,'Search')
        controls.addWidget(self.setup_tabs)
        right=WorkspacePanel();output=QVBoxLayout(right);self.summary=QLabel('No campaign loaded. Start with your applied Structure or open saved work.');self.summary.setWordWrap(True)
        self.designs=QComboBox();self.designs.setMinimumContentsLength(15);self.component=_combo([('|E|','total'),('|Ex|','Ex'),('|Ey|','Ey'),('|Ez|','Ez')]);self.layer=QComboBox();self.layer.setMinimumContentsLength(12)
        bar=QHBoxLayout();bar.addWidget(QLabel('Design'));bar.addWidget(self.designs,1);bar.addWidget(self.component);bar.addWidget(self.layer);output.addLayout(bar)
        self.result_tabs=QTabWidget();self.field_plot=PlotWidget();self.line_plot=PlotWidget();self.rta_plot=PlotWidget();self.validation_plot=PlotWidget();self.results=table([]);self.validation_table=table([])
        for widget,label in [(self.field_plot,'XY / full-stack XZ'),(self.line_plot,'Depth line'),(self.rta_plot,'RTA'),(self.validation_plot,'Prediction vs S4'),(self.results,'Training designs'),(self.validation_table,'Validation errors')]:self.result_tabs.addTab(widget,label)
        self.volume_view=FieldVolumeWidget(store,campaign=True);self.result_tabs.addTab(self.volume_view,'3D electric field')
        self.result_tabs.currentChanged.connect(self.draw_volume)
        self.contour_page=QWidget();cl=QVBoxLayout(self.contour_page);self.contour_view=QComboBox();cl.addWidget(self.contour_view);self.contour_status=QLabel();self.contour_status.setWordWrap(True);cl.addWidget(self.contour_status);self.contour_table=table(['Amplitude','Regions','Area fraction']);cl.addWidget(self.contour_table);self.result_tabs.addTab(self.contour_page,'Contour scan')
        self.contour_view.currentIndexChanged.connect(self.draw_contours);self.result_tabs.currentChanged.connect(self.draw_contours)
        self.field_plot.setMinimumHeight(320)
        self.result_tabs.setMinimumHeight(320);output.addWidget(self.result_tabs,1)
        self.moving=_check('Moving ceiling',False);self.threshold=number(0,0,10000,3);self.threshold.setSingleStep(.1);bar=QHBoxLayout();bar.addWidget(self.moving);bar.addWidget(QLabel('Contour amplitude'));bar.addWidget(self.threshold);output.addLayout(bar)
        self.apply=_button('Use selected design in Structure',self.apply_selected);self.apply.setEnabled(False);self.inspect_note=QLabel('All field components use incident amplitude. Test designs are for validation; predictions are not measured results.');self.inspect_note.setWordWrap(True);output.addWidget(self.inspect_note)
        from qt_result_export import export_run
        inspector=WorkspacePanel();inspector_layout=QVBoxLayout(inspector)
        title=QLabel('Search progress & candidates');title.setObjectName('sectionTitle');inspector_layout.addWidget(title)
        inspector_layout.addWidget(self.summary)
        from qt_custom_device import DeviceCanvas
        self.device_preview=DeviceCanvas('3d');self.device_preview.compact_preview=True
        self.device_preview.setMinimumHeight(220);self.device_preview.setMaximumHeight(300)
        inspector_layout.addWidget(self.device_preview)
        preview_label=QLabel('Shared input device · measured fields are shown in the result tabs');preview_label.setWordWrap(True);inspector_layout.addWidget(preview_label)
        inspector_layout.addWidget(_button('Edit shared optical setup',lambda:self.routeRequested.emit('optical.overview')))
        inspector_layout.addStretch()
        inspector_layout.addWidget(self.apply)
        inspector_layout.addWidget(_button('Export campaign…',lambda:export_run(self,self.directory,self.status)))
        self.campaign_actions=self.actions('Start search',lambda:self.run('search'));controls.addWidget(self.campaign_actions)
        controls.addWidget(_button('Preview plan',self.preview))
        self.progress_bar.setParent(inspector);inspector_layout.insertWidget(2,self.progress_bar)
        split=_ResponsiveSplitter();split.addWidget(left);split.addWidget(right);split.addWidget(inspector);split.setSizes([330,760,350]);self.workspace_splitter=split;self.layout_.addWidget(split,1);self.layout_.addWidget(self.status)
        self.designs.currentIndexChanged.connect(self.inspect);self.component.currentIndexChanged.connect(self.draw_fields);self.layer.currentIndexChanged.connect(self.draw_fields);self.threshold.valueChanged.connect(self.draw_fields);self.moving.toggled.connect(self.draw_fields)
        self.results.itemSelectionChanged.connect(self.select_table);self.bounds.changed.connect(self.save)
        for w in self.controls.values():_on_edit(w,self.save)
        self.controls['mode'].currentIndexChanged.connect(self.enabling);self.controls['approach'].currentIndexChanged.connect(self.enabling)
        self.reference.editingFinished.connect(self.save);self.resume.editingFinished.connect(self.save);store.changed.connect(self.restore)
        self.restore('project');self._loading=False
        for b in self.stops:b.setText('Pause and save')
        self.enabling()
        self.tool_tabs={'setup':[(self.setup_tabs,0)],'training':[(self.setup_tabs,1)],'search':[(self.setup_tabs,2)],
            'fields':[(self.result_tabs,0)],'depth':[(self.result_tabs,1)],'rta':[(self.result_tabs,2)],
            'prediction':[(self.result_tabs,3)],'designs':[(self.result_tabs,4)],'validation':[(self.result_tabs,5)],
            'volume':[(self.result_tabs,6)],'contours':[(self.result_tabs,7)]}
        self.store.changed.connect(self._refresh_device_preview)
        self._refresh_device_preview()
        from qt_tool_workspace import polish_tool_workspace
        polish_tool_workspace(self)
        for explanation in (note,hint,self.inspect_note):
            explanation.hide();explanation.parentWidget().setToolTip(explanation.text())
        self.plan_label.setText('')
        self.summary.setText('No campaign loaded')
        self.setup_tabs.setCurrentIndex(0)
        if self.resume.text() and Path(self.resume.text()).is_file():
            try:
                path=Path(self.resume.text());self.directory=path.parent;self.load_campaign(read_json(path))
            except Exception as exc:self.status.setText('Could not reopen saved campaign: '+str(exc))

    def _refresh_device_preview(self,*_):
        self.device_preview.set_device(self.store.device or {})
        self.device_preview.optical_unit_cell=self.store.settings.get('optical_unit_cell',{})

    def select_tool_tab(self,route):
        from qt_tool_workspace import select_tool_tab
        return select_tool_tab(self,route)

    def enabling(self,*_):
        full=self.controls['mode'].currentData()=='Full range scan'
        self.controls['initial'].setEnabled(not full);self.controls['adaptive'].setEnabled(not full)
        reference=self.controls['approach'].currentData()=='reference'
        self.reference.setEnabled(reference);self.controls['reference_weight'].setEnabled(reference)

    def _busy(self,busy):
        super()._busy(busy)
        if hasattr(self,'apply'):self.apply.setEnabled(not busy and self.selected() is not None)

    def options(self,operation='collect'):
        out={k:_value(v) for k,v in self.controls.items()};out.update(bounds=self.bounds.records(),resume_file=self.resume.text().strip(),reference_directory=self.reference.text().strip(),operation=operation);return out

    def save(self,*_):
        if self._loading:return
        if getattr(self.store,'study_navigation_enabled',False) and self.store.active_study!='tools.ai':return
        try:self.store.save_search('ai_search',self.options())
        except Exception as exc:self.status.setText(str(exc))

    def restore(self,reason):
        if reason not in ('project','study','structure','undo'):return
        saved=self.store.search_state.get('ai_search',{});self._loading=True
        try:
            for k,w in self.controls.items():
                value=saved.get(k,DEFAULTS[k])
                if isinstance(w,QLineEdit):w.setText(str(value))
                else:_set_value(w,value)
            self.resume.setText(str(saved.get('resume_file','')));self.reference.setText(str(saved.get('reference_directory','')))
            self.bounds.set_records(saved.get('bounds',[]))
        except Exception as exc:self.status.setText('Saved AI setup needs review: '+str(exc))
        finally:self._loading=False

    def default_ranges(self):
        try:
            rows=[]
            for _,r in self.store.layers.iloc[1:-1].iterrows():
                if r.Thickness_um>0 and r.Name in set(self.store.patterns.Layer):
                    rows.append(dict(Parameter='thickness',Target=r.Name,Min=float(r.Thickness_um)*.9,Max=float(r.Thickness_um)*1.1,Step=float(r.Thickness_um)*.05,Choices=''))
            a=float(self.store.settings['ax_um']);rows.append(dict(Parameter='lattice_square',Target='',Min=a*.95,Max=a*1.05,Step=a*.025,Choices=''))
            if len(self.store.patterns):
                r=self.store.patterns.iloc[0];v=float(r.SizeX_um);rows.append(dict(Parameter='radius',Target='1',Min=v*.9,Max=v*1.1,Step=v*.05,Choices=''))
            self.bounds.set_records(rows);self.save();self.status.setText('Ranges created. Review limits and steps before starting.')
        except Exception as exc:self.status.setText(str(exc))

    def copy_ranges(self):
        try:
            opts=self.store.search_state.get('peaks') or self.store.search_state.get('target') or {}
            rows=list(opts.get('bounds',[]))
            for hole in opts.get('holes',[]):
                if hole.get('Shape')!='circle':continue
                indices=[i+1 for i,p in self.store.patterns.iterrows() if p.Layer==hole['Layer'] and p.Shape=='circle']
                if not indices:continue
                index=indices[0];lo=float(hole['MinX_um']);hi=float(hole['MaxX_um'])
                if not any(r['Parameter'] in ('radius','r_over_a') and str(r['Target'])==str(index) for r in rows):
                    rows.append(dict(Parameter='radius',Target=str(index),Min=lo,Max=hi,Step=max((hi-lo)/max(1,int(opts.get('grid_steps',21))-1),1e-9),Choices=''))
            self.bounds.set_records(rows);self.save()
        except Exception as exc:self.status.setText(str(exc))

    def preview(self):
        try:
            _,job=prepare_job('ai_search',self.store.portable_project(),self.options('search'),self.store.library);cfg=job['search']
            plan=cfg['design_count'] if cfg['mode']=='Full range scan' else min(cfg['design_count'],cfg['initial']+cfg['test_count']+cfg['adaptive'])
            estimate='Time estimate available after completed designs.'
            if self.campaign:
                summary=self.campaign.get('summary',{});n=summary.get('new_simulations',0)
                if n:estimate=f"Estimated maximum time: {summary['elapsed_seconds']/n*(min(cfg['new_budget'],plan+cfg['finalists']) if cfg['new_budget'] else plan+cfg['finalists'])/60:.1f} min, based on this campaign; accuracy and hardware affect it."
            limit=f"New S4 designs capped at {cfg['new_budget']:,}." if cfg['new_budget'] else 'No simulation limit; all planned designs can run.'
            self.plan_label.setText(f"Range grid: {cfg['design_count']:,} combinations. Planned unique screening designs: ≤{plan:,}; verification: ≤{cfg['finalists']}. {limit} Reuse can reduce work. {estimate}")
        except Exception as exc:self.plan_label.setText(str(exc))

    def run(self,operation):
        if operation in ('fit','verify') and not self.resume.text():self.status.setText('Open a campaign first, or collect initial training designs.');return
        self.save();self.records=[];self._start('ai_search',self.options(operation))

    def choose_reference(self):
        path=QFileDialog.getExistingDirectory(self,'Choose saved fields directory')
        if path:
            old=self.reference.text().strip();paths=[p.strip() for p in old.split(';') if p.strip()]
            if path not in paths:paths.append(path)
            self.reference.setText(';'.join(paths));self.save()

    def open_campaign(self):
        path,_=QFileDialog.getOpenFileName(self,'Open AI campaign checkpoint',str(self.store.library.runs),'Campaign (campaign.json)')
        if path:
            try:
                saved=read_json(path);settings=dict(saved['settings']);base=saved.get('base',{})
                for key,value in dict(basis=base.get('basis',32),polarization=base.get('polarization','p'),phi_deg=base.get('phi',0.),theta_deg=base.get('points',[[0,1550,0.]])[0][2]).items():settings.setdefault(key,value)
                self._loading=True
                for k,w in self.controls.items():
                    value=settings.get(k,DEFAULTS[k])
                    if isinstance(w,QLineEdit):w.setText(str(value))
                    else:_set_value(w,value)
                self.bounds.set_records([{k:r.get(k,'') for k in ('Parameter','Target','Min','Max','Step','Choices')} for r in settings.get('input_bounds',settings.get('bounds',[]))])
                self.reference.setText(settings.get('reference_directory',''));self.resume.setText(path);self._loading=False;self.save();self.directory=Path(path).parent;self.load_campaign(saved)
            except Exception as exc:self._loading=False;self.status.setText(str(exc))

    def _progress(self,event):
        super()._progress(event)
        if event.get('run_kind')=='ai_search' and event.get('kind')=='campaign_observation':
            self.records.append(event['record']);self.refresh_designs();self.summary.setText(f"{len(self.records)} observations displayed · new work {event.get('completed')} / {event.get('total')}")

    def show_result(self,event):
        path=self.directory/'campaign.json';self.resume.setText(str(path));self.load_campaign(read_json(path));self.save();self.status.setText(f"{event['summary']['status']}. Saved to {self.directory}")

    def load_campaign(self,saved):
        self.campaign=saved;self.records=saved['records'];s=saved['summary'];self.summary.setText(f"{s['completed']} completed · {s['training']} training · {s['tests']} tests · {s['new_simulations']} new S4 designs · {s['reused']} reused · {s['failures']} failed")
        self.refresh_designs();report=s.get('validation',{});self.validation_plot.draw_figure(validation_figure(report));fill_table(self.validation_table,[{k:v for k,v in r.items() if k in ('name','mae','rmse','interval_95_coverage')} for r in report.get('measurements',[])])
        if self.directory and (self.directory/'design_results.csv').exists():fill_table(self.results,pd.read_csv(self.directory/'design_results.csv'))

    def refresh_designs(self):
        selected=self.designs.currentData()
        with QSignalBlocker(self.designs):
            self.designs.clear()
            for i,r in enumerate(self.records):
                state='verified' if r.get('verified') else 'targets met' if r['fields']['feasible'] else 'targets unmet'
                self.designs.addItem(f"{i+1} · {r['phase']} · {state}",i)
            index=self.designs.findData(selected);self.designs.setCurrentIndex(index if index>=0 else self.designs.count()-1)
        self.inspect()

    def selected(self):
        index=self.designs.currentData();return self.records[index] if isinstance(index,int) and 0<=index<len(self.records) else None

    def draw_contours(self,*_):
        if self.result_tabs.currentWidget() is not self.contour_page:return
        record=self.selected()
        if not record:return
        path=Path(record['field_directory'])/'field_contours.json'
        if not path.is_file():self.contour_status.setText('This saved design has no contour hierarchy.');return
        key=str(path)
        if key not in self.contour_cache:
            self.contour_cache.clear();self.contour_cache[key]=read_json(path)
        result=self.contour_cache[key];views=result['views']
        if set(self.contour_view.itemText(i) for i in range(self.contour_view.count()))!=set(views):
            with QSignalBlocker(self.contour_view):
                current=self.contour_view.currentText();self.contour_view.clear();self.contour_view.addItems(list(views));self.contour_view.setCurrentIndex(max(0,self.contour_view.findText(current)))
        scan=views[self.contour_view.currentText()][self.component.currentData()]
        self.contour_status.setText(f"Step {result['step']:g} × incident amplitude · {scan['summary']['level_count']} levels · {scan['summary']['births']} births · {scan['summary']['merges']} merges. Exact sampled shapes and parent tracks are saved in field_contours.json.")
        fill_table(self.contour_table,[dict(Amplitude=f"{r['level']:.5g}",Regions=r['region_count'],Area_fraction=f"{r['area_fraction']:.3%}") for r in scan['levels']])

    def inspect(self,*_):
        r=self.selected();self.apply.setEnabled(r is not None and not self.store.busy)
        self.volume_view.invalidate()
        self.draw_volume()
        if not r:return
        names=[l['name'] for l in r['model']['layers'][1:-1] if l['thickness']>0]
        with QSignalBlocker(self.layer):
            current=self.layer.currentText();self.layer.clear();self.layer.addItems(names);self.layer.setCurrentIndex(max(0,self.layer.findText(current)))
        self.draw_fields();self.line_plot.draw_figure(line_figure(r));self.rta_plot.draw_figure(rta_figure(r));c=r['fields']['constraints']
        self.inspect_note.setText(f"Volume contrast: {(c['volume_rms_contrast'] or 0):.3f}× · XZ contrast: {(c['xz_rms_contrast'] or 0):.3f}× · volume coverage: {c['volume_coverage']:.1%} · XZ coverage: {c['xz_coverage']:.1%}. Screening basis {r['model']['basis']}; phase: {r['phase']}.")

    def draw_volume(self,*_):
        if self.result_tabs.currentWidget() is not self.volume_view:return
        record=self.selected()
        path=record.get('field_directory') if record else None
        self.volume_view.load_directory(path)

    def draw_fields(self,*_):
        self.draw_contours()
        r=self.selected()
        if r:
            try:self.field_plot.draw_figure(field_figure(r,self.component.currentData(),self.layer.currentText(),self.threshold.value(),self.moving.isChecked(),self.controls['contour_step'].value()))
            except Exception as exc:self.status.setText('Could not preview saved fields: '+str(exc))

    def select_table(self):
        row=self.results.currentRow()
        if row>=0 and self.results.item(row,0):
            try:self.designs.setCurrentIndex(self.designs.findData(int(self.results.item(row,0).text())-1))
            except ValueError:pass

    def apply_selected(self):
        r=self.selected()
        if not r or self.store.busy:return
        try:
            project=self.store.library.from_model(r['model'],self.store.portable_project());self.store.replace_active_study(project);self.status.setText('Selected simulated design applied to this simulation’s structure.')
        except Exception as exc:self.status.setText(str(exc))

