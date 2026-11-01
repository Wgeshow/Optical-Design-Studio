"""Stage-specific native layouts; existing widgets remain the model authority."""
from PyQt6.QtCore import Qt, QSignalBlocker
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QScrollArea,QSplitter,QGroupBox,QFormLayout,QSizePolicy,QComboBox,QLineEdit,QAbstractSpinBox,QCheckBox,QTableWidget,QStackedWidget
from qt_journey import StageHost
from qt_input_diagnostics import DiagnosticPanel

def _body(*widgets):
    body=QWidget(); layout=QVBoxLayout(body)
    for widget in widgets: widget.setParent(body); layout.addWidget(widget); widget.show()
    return body

def _pair(left,right,*,result_surface=False):
    from qt_compute import _ResponsiveSplitter
    class ResultSplitter(_ResponsiveSplitter):
        def resizeEvent(self,event):
            orientation=Qt.Orientation.Horizontal if self.width()>=self.responsive_breakpoint else Qt.Orientation.Vertical
            if orientation!=self.orientation():
                # Returning to the same desktop width must reapply the result
                # ratio, even though the cached horizontal width is unchanged.
                self._last_layout_width=0
            super().resizeEvent(event)
    split=(ResultSplitter if result_surface else _ResponsiveSplitter)(Qt.Orientation.Horizontal)
    if result_surface:
        split.reference_ratios=(.72,.28)
        split.responsive_breakpoint=1120
        split.vertical_minimum_sizes=(620,240)
    for widget in (left,right): widget.setMinimumWidth(0); split.addWidget(widget); widget.show()
    split.setSizes([650,380]); split.setChildrenCollapsible(False)
    return split

def _scroll(widget):
    area=QScrollArea(); area.setWidgetResizable(True); area.setFrameShape(QScrollArea.Shape.NoFrame); area.setWidget(widget)
    return area

def _compact(widget):
    body=QWidget(); body.setMaximumWidth(520); layout=QVBoxLayout(body)
    widget.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Maximum)
    layout.addWidget(widget,0,Qt.AlignmentFlag.AlignTop); layout.addStretch()
    return body

def _sampling(page,route):
    from qt_optical_domain_canvas import OpticalSamplingCanvas
    if route=='fdtd':
        def values():
            c=page.controls
            return dict(first=c['wavelength_min_nm'].value(),last=c['wavelength_max_nm'].value(),
                        detail=f"{c['frequency_points'].value()} frequency samples",source='Broadband pulse · normal incidence · '+c['polarization'].currentText())
        title='Broadband pulse and frequency sampling'; controls=page.controls.values()
    elif route=='tools.index_shift':
        def values():
            c=page.controls; center=c['reference_nm'].value(); radius=c['tracking_window_nm'].value()
            return dict(first=center-radius,last=center+radius,center=center,
                        detail='Nearest sampled '+c['feature'].currentText().lower()+' in this search window',source=c['response'].currentText()+' · zero-shift baseline retained')
        title='Sampled resonance search window'; controls=page.controls.values()
    else:
        def values():
            center=page.field_wavelength.value()
            return dict(first=center,last=center,center=center,
                        detail=f"{page.field_controls['grid'].value()} XY samples/axis · {page.field_controls['depth_samples'].value()} depths/layer",
                        source=page.field_source.currentText())
        title='Requested field sampling'; controls=[page.field_wavelength,page.field_source,*page.field_controls.values()]
    return OpticalSamplingCanvas(values,title,controls)

def _group(widget):
    while widget is not None and not isinstance(widget,QGroupBox): widget=widget.parentWidget()
    return widget

def _lift_tab(tabs,index):
    current=tabs.currentIndex()
    with QSignalBlocker(tabs):
        name=tabs.tabText(index); body=tabs.widget(index); tabs.removeTab(index); body.setParent(None)
        tabs.insertTab(index,QWidget(),name); tabs.setCurrentIndex(current)
    return body

def _fields(title,rows):
    group=QGroupBox(title); form=QFormLayout(group)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    for label,widget in rows:
        parent = widget.parentWidget()
        old = parent.layout() if parent is not None else None
        if isinstance(old,QFormLayout):
            taken=old.takeRow(widget)
            if taken.labelItem and taken.labelItem.widget(): taken.labelItem.widget().deleteLater()
        form.addRow(label,widget)
    return group

def _geometry(page,store,route):
    if route=='fdtd':
        from qt_optical_domain_canvas import OpticalDomainCanvas
        canvas=OpticalDomainCanvas(store,page.controls)
    else:
        from qt_device_builder import GeometryViewport
        from qt_custom_device import DeviceCanvas
        canvas=QStackedWidget(); original=GeometryViewport(); finite=DeviceCanvas('3d')
        canvas.addWidget(original); canvas.addWidget(finite)
        def refresh(*_):
            source=getattr(store,'optical_geometry_source','device')
            canvas.setCurrentIndex(0 if source=='original_tables' else 1)
            try:
                if source=='original_tables': original.set_model(store,'',3)
                else: finite.set_device(store.device or {})
            except (ValueError,KeyError,TypeError): pass
        store.changed.connect(refresh); refresh()
        page._refresh_journey_geometry=refresh
    label=QLabel('This study’s applied geometry · preview only, not a field solution'); label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Fixed)
    canvas.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
    page.journey_full_edit_button=QPushButton('Open full device editor here')
    page.journey_full_edit_button.setAccessibleName('Open full structure editor for this study')
    from qt_reference_style import reference_icon
    page.journey_full_edit_button.setIcon(reference_icon('structure', '#3974df'))
    edit=QPushButton('Open separate periodic structure editor')
    def navigate():
        target='structure.original' if route != 'fdtd' and getattr(store,'optical_geometry_source','device')=='original_tables' else 'structure.device'
        if hasattr(page,'routeRequested'): page.routeRequested.emit(target)
        elif hasattr(page.window(),'_route_setup_action'): page.window()._route_setup_action(target)
    edit.clicked.connect(navigate)
    def update_editor_link(*_):
        edit.setVisible(route != 'fdtd' and getattr(store,'optical_geometry_source','device') == 'original_tables')
    store.changed.connect(update_editor_link)
    previous_refresh = getattr(page, '_refresh_journey_geometry', lambda: None)
    def refresh_geometry():
        previous_refresh(); update_editor_link()
    page._refresh_journey_geometry = refresh_geometry
    result = _body(label,canvas,page.journey_full_edit_button,edit)
    update_editor_link()
    return result

def _structure_stage(page, store, route, host, body):
    # The full editor occupies the complete stage; it is never squeezed inside
    # the adjacent solver settings/preview splitter. Existing inputs keep their
    # original owners and bindings in the first page of this stack.
    stack = QStackedWidget()
    stack.addWidget(_scroll(body))
    page.journey_structure_stack = stack
    page.journey_device_editor = None

    def open_editor():
        if store.busy:
            return False
        if page.journey_device_editor is None:
            from qt_study_device_editor import StudyDeviceEditor
            editor = StudyDeviceEditor(page, include_advanced=route != 'fdtd', optical_materials=True, back_label='Back to domain & setup' if route == 'fdtd' else 'Back to structure overview')
            editor.return_requested.connect(lambda: stack.setCurrentIndex(0))
            editor.continue_requested.connect(lambda: host.select_stage('parameters'))
            page.journey_device_editor = editor
            stack.addWidget(editor)
        editor = page.journey_device_editor
        source = 'device' if route == 'fdtd' else getattr(store, 'optical_geometry_source', 'device')
        if not editor.open_editor(source=source):
            return False
        host.select_stage('structure')
        stack.setCurrentWidget(editor)
        return True

    page.open_journey_device_editor = open_editor
    page.journey_full_edit_button.clicked.connect(open_editor)
    return stack

def _request(page,store,route):
    project=store.portable_project()
    if route=='optical':
        from qt_compute import _value
        project['settings'].update({key:_value(w) for key,w in page.controls.items()})
        return 'simulation',project,dict(measure_phase=page.measure_phase.isChecked())
    if route=='tools.sweep': return 'peaks',project,page.peak_options()
    if route=='tools.ai':
        operation=getattr(page,'journey_check_operation',None)
        operation=operation.currentData() if operation is not None else 'search'
        if operation in ('fit','verify') and not page.resume.text().strip():
            from qt_research_common import FieldError
            raise FieldError('resume','Open a campaign checkpoint before fitting or verifying saved data.')
        return 'ai_search',project,page.options(operation)
    return {'fdtd':'fdtd','tools.index_shift':'index_shift','tools.fields':'fields'}[route],project,page.options()

def _checks(page,store,route,host):
    body=QWidget(); layout=QVBoxLayout(body)
    state=QLabel('Current inputs have not been checked. Runtime availability is separate.'); state.setWordWrap(True); layout.addWidget(state)
    page.journey_check_state=state
    if route=='fdtd':
        source_summary=QLabel(); source_summary.setWordWrap(True)
        page.journey_source_summary=source_summary
        layout.addWidget(source_summary)
        def update_source_summary(*_):
            integrated=page.controls['source_is_integrated'].isChecked()
            source_summary.setText('Gaussian source: '+('integrated polarization (on).' if integrated else 'current (integration off).')+
                ' Both reference and device use this setting. Decay and spectral convergence require separate checks.')
        page.controls['source_is_integrated'].toggled.connect(update_source_summary)
        update_source_summary()
    if route=='tools.ai':
        operation=QComboBox(); operation.setAccessibleName('AI operation to validate')
        for title,key in [('Collect and train','collect'),('Fit saved data','fit'),('Search','search'),('Verify leaders','verify')]: operation.addItem(title,key)
        operation.setCurrentIndex(2); page.journey_check_operation=operation
        layout.addWidget(QLabel('Validate the selected existing campaign operation')); layout.addWidget(operation)
    issues=DiagnosticPanel(body); layout.addWidget(issues); page.journey_diagnostics=issues
    controls=dict(getattr(page,'controls',{})); controls.update(getattr(page,'search_controls',{}))
    controls.update({k:getattr(page,k) for k in ('wavelength','grid','depth','layer','material','layers','bounds','resume') if hasattr(page,k)})
    def reveal(target):
        widget=controls.get(target.get('field'))
        if widget is not None: host.reveal(widget)
        else: host.select_stage(target.get('section','parameters'))
    issues.activated.connect(reveal)
    def check():
        try:
            kind,project,options=_request(page,store,route)
            if kind=='fdtd':
                from fdtd_model import build_job
                build_job(project,store.library.files_for(project),options)
            else:
                from qt_core import prepare_job
                if getattr(store,'optical_geometry_source','device')=='original_tables': options=dict(options,optical_geometry_source='original_tables')
                prepare_job(kind,project,options,store.library)
            issues.set_diagnostics([])
            operation_note=(page.journey_check_operation.currentText()+': ') if route=='tools.ai' else ''
            state.setText(operation_note+'Input preparation passed for this draft. Runtime availability and convergence are not established.')
        except Exception as exc:
            field=str(getattr(exc,'field','') or getattr(exc,'key','')); message=str(exc)
            if field not in controls: field=next((k for k in controls if k.lower() in message.lower()),'')
            if not field and route=='fdtd' and 'wavelength' in message.lower(): field='wavelength_max_nm'
            section='structure' if not field and any(word in message.lower() for word in ('material','layer','geometry','lattice','period')) else 'parameters'
            issues.set_diagnostics([dict(message=message,workspace=route,section=section,field=field)])
            state.setText('Resolve the input below. Your draft is preserved.')
    check_button=QPushButton('Check current inputs'); check_button.clicked.connect(check); layout.addWidget(check_button)
    issues.recheckRequested.connect(check); issues.returnRequested.connect(lambda:issues.list.setFocus())
    runtime=QLabel('Runtime not checked here. Checking inputs never installs or launches a solver.'); runtime.setWordWrap(True); layout.addWidget(runtime)
    button=QPushButton('Open solver runtime settings')
    def settings():
        window=page.window()
        if hasattr(window,'_navigate_route'):
            window._navigate_route(6)
            settings_page=getattr(window,'pages',{}).get('Settings')
            if settings_page is not None and hasattr(settings_page,'select_section'):
                settings_page.select_section('meep runtimes' if route=='fdtd' else 'runtimes')
    button.clicked.connect(settings); layout.addWidget(button); layout.addStretch()
    page.check_journey_inputs=check
    def invalidate(*_):
        issues.set_diagnostics([])
        state.setText('Inputs changed since the last check. Recheck the current draft before interpreting readiness.')
    for widget in page.findChildren(QWidget):
        if not isinstance(widget,(QLineEdit,QAbstractSpinBox,QComboBox,QCheckBox,QTableWidget)): continue
        for name in ('valueChanged','textChanged','currentIndexChanged','toggled','itemChanged'):
            signal=getattr(widget,name,None)
            if signal is not None: signal.connect(invalidate); break
    store.changed.connect(invalidate)
    return body

def _operation(page,store,route,host):
    body=QWidget(); layout=QVBoxLayout(body); state=QLabel(page.status.text()); state.setWordWrap(True); layout.addWidget(state)
    page.journey_run_state=state
    if route=='fdtd':
        # Keep timing and its action in the visible journey, not the hidden legacy panel.
        for widget in (page.estimate_button, page.timing_status, page.progress):
            widget.setParent(body); layout.addWidget(widget)
        page.estimate_button.show(); page.timing_status.show()
    kinds={'fdtd'} if route=='fdtd' else set(getattr(page,'kinds',()))
    owner={'running':bool(getattr(page,'_active',False)) and getattr(store,'active_study',route)==route}
    def owns(): return owner['running'] and getattr(store,'active_study',route)==route
    row=QHBoxLayout(); sources=list(getattr(page,'starts',[]))
    if not sources and hasattr(page,'start_button'): sources=[page.start_button]
    if route=='tools.sweep': sources=[s for s in sources if 'sweep' in s.text().lower()]
    buttons=[]
    for source in sources:
        button=QPushButton(source.text()); row.addWidget(button); buttons.append((button,source))
        def start(checked=False,source=source):
            if store.busy or getattr(store,'active_study',route)!=route: return
            owner['running']=True; source.click()
            if not store.busy: owner['running']=False
            state.setText(page.status.text()); sync(store.busy)
        button.clicked.connect(start)
    cancel=QPushButton('Pause and save' if route=='tools.ai' else 'Cancel')
    page.journey_cancel_button=cancel
    def cancel_owned():
        if store.busy and owns():
            store.cancel(); state.setText('Pause requested; waiting for checkpoint.' if route=='tools.ai' else 'Cancellation requested; waiting for this study’s worker.')
    cancel.clicked.connect(cancel_owned); row.addWidget(cancel); layout.addLayout(row)
    original_stops=list(getattr(page,'stops',[]))
    if hasattr(page,'stop_button'): original_stops.append(page.stop_button)
    for stop in original_stops:
        try: stop.clicked.disconnect()
        except TypeError: pass
        stop.clicked.connect(cancel_owned)
    def sync(busy):
        if busy and getattr(store,'active_study',route)==route and getattr(page,'_active',False): owner['running']=True
        for button,source in buttons: button.setEnabled(not busy and source.isEnabled() and getattr(store,'active_study',route)==route)
        cancel.setEnabled(bool(busy and owns()))
        for stop in original_stops: stop.setEnabled(bool(busy and owns()))
    def progress(event):
        if event.get('run_kind') in kinds and getattr(store,'active_study',route)==route:
            owner['running']=True; state.setText(str(event.get('message') or event.get('text') or page.status.text())); sync(store.busy)
    def finished(event):
        if event.get('run_kind') not in kinds or not owns(): return
        owner['running']=False; state.setText(page.status.text())
        if event.get('status')!='cancelled': host.show_results()
        sync(False)
    def failed(message):
        if owns(): owner['running']=False; state.setText(str(message)); sync(False)
    store.busy_changed.connect(sync); store.changed.connect(lambda *_:sync(store.busy))
    store.progress.connect(progress); store.run_finished.connect(finished); store.run_failed.connect(failed)
    if hasattr(page,'run_log'): layout.addWidget(page.run_log.parentWidget())
    layout.addStretch(); sync(store.busy)
    return body

def install_optical_journey(page,store,route):
    if hasattr(page,'optical_journey'):
        if hasattr(page,'_refresh_journey_geometry'): page._refresh_journey_geometry()
        return page.optical_journey
    if route.startswith('photonic_bands'): return getattr(page,'journey_bar',None)
    if page.__class__.__name__ not in {'SimulationPage','FDTDPage','IndexShiftPage','FieldsPage','OptimizePage','AISearchPage'}: return None
    root=getattr(page,'layout_',None) or page.layout(); host=StageHost(page); page.optical_journey=host
    geometry=_geometry(page,store,route); extra=None; workbench=getattr(page,'workbench',None)
    if workbench:
        setup=workbench.input_scroll.takeWidget(); results=workbench.views.widget(1); results.setParent(None)
        if workbench.input_tabs.count()>1:
            area=workbench.input_tabs.widget(1); extra=area.takeWidget() if isinstance(area,QScrollArea) else area
        old=workbench
    elif route=='optical':
        old=page.workspace_scroll; split=page.workspace_splitter; setup,results,extra=split.widget(0),split.widget(1),split.widget(2)
    elif route=='tools.sweep':
        old=page.tabs; split=page.general_page; setup,results=split.widget(0),split.widget(1)
    else:
        old=page.workspace_splitter; setup,results,extra=old.widget(0),old.widget(1),old.widget(2)
    old.hide(); root.removeWidget(old); setup.setParent(None); results.setParent(None)
    proxies={}
    if route=='fdtd':
        domain = _fields('Meep domain and mesh', [(label, page.controls[key]) for label, key in [
            ('Dimensionality', 'dimensions'), ('Resolution (cells/µm)', 'resolution'), ('Section Y (µm)', 'section_y_um'), ('Cell budget', 'max_cells')] if key in page.controls])
        boundaries = _fields('Boundaries and absorbing layers', [(label, page.controls[key]) for label, key in [
            ('PML thickness (µm)', 'pml_um'), ('Air/medium padding (µm)', 'padding_um')]])
        pulse = _fields('Broadband pulse', [(label, page.controls[key]) for label, key in [
            ('Polarization', 'polarization'), ('Minimum wavelength (nm)', 'wavelength_min_nm'),
            ('Maximum wavelength (nm)', 'wavelength_max_nm'), ('Frequency samples', 'frequency_points'),
            ('Pulse source', 'source_is_integrated')]])
        stopping = _fields('Time stepping and stopping', [(label, page.controls[key]) for label, key in [
            ('Maximum time after pulse (µm/c)', 'run_after_sources'), ('Courant factor', 'courant'), ('Monitor field decay target', 'decay_by'), ('Dispersion fit tolerance', 'fit_tolerance')] if key in page.controls])
        presets = QWidget(); preset_row = QHBoxLayout(presets); preset_row.setContentsMargins(0, 0, 0, 0)
        page.journey_load_preset = QPushButton('Load Meep setup…')
        page.journey_save_preset = QPushButton('Save Meep setup…')
        page.journey_load_preset.clicked.connect(lambda: page.load_setup_preset())
        page.journey_save_preset.clicked.connect(lambda: page.save_setup_preset())
        preset_row.addWidget(page.journey_load_preset); preset_row.addWidget(page.journey_save_preset)
        stages=[('Domain & mesh',_pair(geometry,_scroll(_body(presets,domain,page.exterior_group,boundaries))),'structure'),
                ('Broadband pulse',_pair(_sampling(page,route),_compact(pulse)),'parameters'),
                ('Stopping & saved fields',_pair(_sampling(page,route),_compact(_body(stopping,page.controls['fit_materials'],page.controls['save_fields']))),'stopping')]
    elif route=='tools.index_shift':
        stages=[('Material occurrences',_pair(geometry,_scroll(page.layers.parentWidget())),'structure'),
                ('Index & carrier states',_body(_group(page.material),page.shared),'parameters'),
                ('Optical sampling & tracking',_pair(_sampling(page,route),_compact(_body(_group(page.controls['reference_nm']),setup))),'sampling')]
    elif route=='tools.fields':
        display=_group(page.wavelength)
        sampling=_fields('Field sampling',[(label,getattr(page,name)) for label,name in [('Wavelength','wavelength'),('Layer','layer'),('Grid samples per axis','grid'),('Depth samples','depth')]])
        stages=[('Structure & excitation',geometry,'structure'),('Field sampling',_body(sampling,setup),'parameters')]
        # Keep one compact display/export sidebar; nested splitters otherwise
        # consume most of the result width and squeeze the actual field maps.
        display.setTitle('Field display')
        display.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Maximum)
        extra=_body(display,extra) if extra is not None else display
    elif route=='optical':
        illumination=_body(page.controls['mode'].parentWidget(),page.wavelength_box,page.angle_box,page.controls['polarization'].parentWidget())
        stages=[('Periodic structure',geometry,'structure'),('Illumination & scan',illumination,'parameters'),
                ('Phase & field outputs',_pair(_sampling(page,route),_compact(_body(_group(page.field_single),setup))),'outputs')]
        page._mode()
    elif route=='tools.sweep':
        campaign_note=QLabel('This study evaluates the selected parameter combinations. For adaptive learning, open AI optical search as an independent study.')
        campaign_note.setWordWrap(True)
        open_ai=QPushButton('Open AI optical search')
        open_ai.clicked.connect(lambda:page.routeRequested.emit('tools.ai'))
        stages=[('Base design & scan',geometry,'structure'),('Parameter recipe',_body(page.shared_hole,page.bounds),'parameters'),
                ('Sweep budget & execution',_body(campaign_note,open_ai,page.general_detail_tabs,setup),'sampling')]
    else:
        tabs=page.setup_tabs; bodies=[_lift_tab(tabs,i) for i in range(3)]
        stages=[('Design & field objective',_pair(geometry,bodies[0]),'structure'),
                ('Collection & verification',bodies[1],'parameters'),('Fit & model search',_body(bodies[2],setup),'search')]
        proxies[tabs]={0:'structure',1:'parameters',2:'search'}
    descriptions={
        'structure':'Edit this study’s full structure and material assignments. The full editor retains the original drawing, arrays, layers and inspector controls.',
        'parameters':{'fdtd':'Choose the broadband wavelength interval and frequency sample count.',
                      'tools.index_shift':'Choose manual shifts or supplied carrier states; review baseline and layer coupling.',
                      'tools.fields':'Choose the wavelength, finite layer and saved XY/depth sampling.',
                      'tools.sweep':'Enter each parameter range and review the exact combination recipe.',
                      'tools.ai':'Set independent training/test counts, sampling and higher-accuracy verification.',
                      'optical':'Choose wavelength or angle sampling and the incident polarization and direction.'}.get(route,''),
        'stopping':'Set post-pulse stopping, material fitting and saved field output; runtime setup is under Checks.',
        'sampling':'Review this study’s optical samples and the selected tracking or sweep budget.',
        'outputs':'Choose phase measurement and independent field wavelength/source and sampling.',
        'search':'Open or resume a campaign, fit saved data or search using the current field objective.'}
    for title,body,key in stages:
        content = _structure_stage(page,store,route,host,body) if key == 'structure' else _scroll(body)
        host.add_stage(title,content,description=descriptions.get(key,''),key=key)
    host.add_stage('Check inputs & runtime',_checks(page,store,route,host),key='checks')
    operation=_operation(page,store,route,host)
    if route=='fdtd':
        # Domain/pulse/stopping controls were moved into their real stages.
        # Keep the unused legacy setup container parented and hidden instead
        # of showing its now-empty groups again beneath the run actions.
        setup.setParent(page); setup.hide()
    host.add_stage('Run & progress',operation,key='run')
    if extra is not None:
        results=_pair(results,_scroll(extra),result_surface=True)
        if route=='optical':
            results.responsive_breakpoint=1120
            results.vertical_minimum_sizes=(700,240)
    page.journey_results_layout=results
    host.add_stage('Saved results',_scroll(results),description='Actual saved data, provenance and exports.',key='results')
    root.insertWidget(0,host,1); host.select_stage('structure')
    if workbench:
        workbench.show_results=host.show_results
        workbench.select_step=lambda index:host.select_stage(min(index,len(stages)-1))
    original=getattr(page,'select_tool_tab',None)
    if original:
        def select_tool_tab(target):
            value=original(target); key=(target or '').split('/')[-1]
            if route=='tools.sweep' and key in ('explore.learning','explore.constraints','explore.detection'):
                # Compatibility paths lead to sweep budget. Adaptive settings
                # remain preserved but hidden; AI is an independent study.
                page.general_detail_tabs.setTabVisible(0,False)
                page.general_detail_tabs.setTabVisible(2,False)
                page.general_detail_tabs.setCurrentIndex(1)
                host.select_stage('sampling')
                return True
            if route=='tools.ai' and key in ('setup','training','search'): host.select_stage({'setup':'structure','training':'parameters','search':'search'}[key])
            elif key in ('','setup','target','explore'): host.select_stage('parameters')
            else: host.show_results()
            return value
        page.select_tool_tab=select_tool_tab
    for tabs,mapping in proxies.items(): tabs.currentChanged.connect(lambda index,mapping=mapping:host.select_stage(mapping.get(index,'parameters')))
    if route=='tools.index_shift': page.update_coupling()
    return host
