"""Presentation-only three-column flow for the canonical simulation editors.

The existing setup state, field objects and section identities remain the source
of truth. Moving a panel never commits a draft or substitutes a device.
"""
from PyQt6.QtCore import Qt, QSignalBlocker, QSize, QTimer, QObject
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QComboBox,
    QTreeWidget, QTreeWidgetItem, QHBoxLayout, QVBoxLayout, QStackedWidget, QScrollArea,
    QSizePolicy, QFileDialog)
from qt_common import COLORS, theme_manager
from qt_reference_style import reference_icon
from qt_journey import JourneyBar


STAGES = {
    'optical': [('Device', ['overview', 'domain']),
                ('Light & materials', ['incident', 'sweep', 'materials']),
                ('Accuracy & outputs', ['accuracy', 'outputs']), ('Check inputs', []), ('Run', []), ('Results', [])],
    'electrical': [('Device', ['overview', 'contacts', 'materials']),
                   ('Bias & physics', ['study', 'temperature']),
                   ('Mesh & outputs', ['mesh', 'outputs']), ('Check inputs', []), ('Run', []), ('Results', [])],
    'coupled': [('Device', ['overview']),
                ('Link physics', ['electrical-setup', 'optical-setup', 'transfer']),
                ('Response & outputs', ['response', 'outputs']), ('Check transfer', []), ('Run', []), ('Results', [])],
}


class SimulationSetupFlow(QObject):
    def __init__(self, workspace):
        super().__init__(workspace)
        self.page = w = workspace
        self.compact = None
        self.compact_view = 'settings'
        self._object_signature = None
        self._device_snapshot = None
        self._syncing = False
        self.extra_stage = None
        self._pending_run = False
        self._owns_run = False
        self.completed_event = None
        self.device_editor = None
        self._device_settings = False
        w.setProperty('simulationFlowOwned', True)
        self.header = QWidget(w)
        header = QVBoxLayout(self.header); header.setContentsMargins(4, 2, 4, 0); header.setSpacing(6)
        w.center.layout().removeWidget(w.title)
        header.addWidget(w.title)
        self.journey_bar = JourneyBar(parent=self.header)
        self.journey_bar.stageRequested.connect(self.show_stage)
        header.addWidget(self.journey_bar)
        self.step_buttons = self.journey_bar.buttons
        w.layout_.insertWidget(1, self.header)

        # Compact navigation uses the same panels, not duplicate editors.
        self.compact_bar = QWidget(w)
        compact_row = QHBoxLayout(self.compact_bar); compact_row.setContentsMargins(0, 0, 0, 0)
        self.compact_buttons = {}
        for key, title, icon in [('settings', 'Settings', 'settings'), ('device', 'Device', 'cube'), ('objects', 'Objects', 'layers')]:
            button = QPushButton(title); button.setObjectName('setupView'); button.setCheckable(True)
            button.setProperty('flowIcon', icon)
            button.clicked.connect(lambda checked=False, value=key: self.show_compact(value))
            compact_row.addWidget(button); self.compact_buttons[key] = button
        self.section_picker = QComboBox(); self.section_picker.setMinimumWidth(0)
        self.section_picker.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.section_picker.setMinimumContentsLength(10)
        self.section_picker.setAccessibleName('Simulation setup section')
        self.section_picker.currentIndexChanged.connect(self._pick_section)
        compact_row.addWidget(self.section_picker, 1)
        w.layout_.insertWidget(2, self.compact_bar)

        nav = w.nav_panel.layout()
        w.navigation.setMinimumHeight(105); w.navigation.setMaximumHeight(245)
        self.object_heading = QLabel('DEVICE OBJECTS'); self.object_heading.setObjectName('setupNavTitle')
        nav.insertWidget(2, self.object_heading)
        self.object_tree = QTreeWidget(); self.object_tree.setObjectName('setupObjectTree')
        self.object_tree.setHeaderHidden(True); self.object_tree.setMinimumWidth(0)
        self.object_tree.setAccessibleName('This simulation’s device objects')
        self.object_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.object_tree.currentItemChanged.connect(self._object_selected)
        nav.insertWidget(3, self.object_tree, 1)
        self.edit_object = QPushButton('Edit selected object'); self.edit_object.setProperty('flowIcon', 'cube')
        self.edit_object.clicked.connect(self.edit_selected)
        nav.insertWidget(4, self.edit_object)
        self.edit_structure = QPushButton('Open Structure editor'); self.edit_structure.setProperty('flowIcon', 'structure')
        self.edit_structure.setText('Edit structure')
        self.edit_structure.clicked.connect(lambda: self.open_device_editor('device'))
        nav.insertWidget(5, self.edit_structure)

        self.scene = QFrame(); self.scene.setObjectName('setupScene')
        scene = QVBoxLayout(self.scene); scene.setContentsMargins(12, 10, 12, 10); scene.setSpacing(8)
        tools = QHBoxLayout()
        caption = QLabel('This simulation’s device'); caption.setObjectName('setupCardTitle'); tools.addWidget(caption, 1)
        self.view_choice = QComboBox(); self.view_choice.setAccessibleName('Device preview view')
        self.view_choice.addItems(['3D view', 'Top · XY', 'Section · XZ'])
        self.view_choice.setMinimumWidth(118); self.view_choice.setMaximumWidth(160)
        tools.addWidget(self.view_choice)
        self.fit_button = QPushButton('Fit'); self.fit_button.setMinimumWidth(52)
        self.fit_button.clicked.connect(w.fit_preview); tools.addWidget(self.fit_button)
        scene.addLayout(tools)
        self.views = QStackedWidget(); self.views.setMinimumWidth(180)
        for view in (w.shared_preview, w.top_preview, w.section_preview):
            view.setMaximumHeight(16777215); view.setMinimumSize(180, 190)
            view.compact_preview = False
            self.views.addWidget(view)
        self.view_choice.currentIndexChanged.connect(self.views.setCurrentIndex)
        scene.addWidget(self.views, 1)
        self.scene_caption = caption
        self.scene_tools = tools
        self.curve_preview = None
        self.coupled_preview = None
        self.selection = QLabel('Select an object in the scene or object list.'); self.selection.setWordWrap(True)
        self.selection.setObjectName('setupMuted'); scene.addWidget(self.selection)
        self.legend = QLabel('Geometry preview · drag to rotate · scroll to zoom')
        self.legend.setWordWrap(True); self.legend.setObjectName('setupPreviewLegend'); scene.addWidget(self.legend)
        self.domain = QLabel(); self.domain.setWordWrap(True); self.domain.setObjectName('setupPreviewLegend')
        scene.addWidget(self.domain)
        w.rail_scroll.hide()
        # The detailed domain summary remains available in a disclosure below
        # the inspector; no output or domain information is discarded.
        self.summary_toggle = QPushButton('Domain details'); self.summary_toggle.setCheckable(True)
        self.summary_toggle.setObjectName('setupDisclosure')
        self.details_area = QScrollArea(); self.details_area.setWidgetResizable(True)
        self.details_area.setObjectName('setupScroll'); self.details_area.setFrameShape(QFrame.Shape.NoFrame)
        self.details_area.setMaximumHeight(180)
        details = QWidget(); details_layout = QVBoxLayout(details); details_layout.setContentsMargins(8, 8, 8, 8)
        details_layout.addWidget(w.summary); details_layout.addWidget(w.sequence)
        self.details_area.setWidget(details); self.details_area.hide()
        self.summary_toggle.toggled.connect(self.details_area.setVisible)
        self.summary_toggle.toggled.connect(lambda checked: w.sequence.setVisible(checked and w.current_mode == 'coupled'))
        w.center.layout().insertWidget(w.center.layout().count()-1, self.summary_toggle)
        w.center.layout().insertWidget(w.center.layout().count()-1, self.details_area)
        w.summary.show()
        w.sequence.hide()  # readable run sequence is also in coupled Overview
        w.purpose.setObjectName('setupInspectorTitle')
        w.purpose.setMaximumHeight(75)
        w.center.setMinimumWidth(0)
        w.stack.setMinimumWidth(0)
        self._build_outcomes()
        w.runRequested.connect(self._run_requested)
        w.store.busy_changed.connect(self._busy_changed)
        w.store.changed.connect(self._sync_run_controls)
        self._sync_run_controls()
        w.store.progress.connect(self._progress)
        w.store.run_finished.connect(self._finished)
        w.store.run_failed.connect(self._failed)
        self.apply_style()
        self.sync_section()
        self.adapt_layout()
        if self.journey_bar._current == 0 and w._is_active_document():
            self.open_device_editor()

    def _pick_section(self, index):
        if not self._syncing and index >= 0:
            self.page.select_section(self.section_picker.itemData(index))
            self.show_compact('settings')

    def show_stage(self, index):
        if not 0 <= index < len(STAGES[self.page.current_mode]):
            return
        if index >= 3:
            self.extra_stage = index
            self.journey_bar.set_current(index)
            self.page.stack.setCurrentWidget(self.outcome_pages[index])
            self.page.purpose.setText(STAGES[self.page.current_mode][index][0])
            if index == 3:
                self.check_summary.setText(self.page.summary.text())
            self.adapt_layout(force=True)
            return
        self.extra_stage = None
        if index == 0:
            self._device_settings = False
        self._leave_device_editor()
        mode = self.page.current_mode
        suffix = STAGES[mode][index][1][0]
        self.page.select_section(mode + '.' + suffix)
        self.show_compact('settings')
        if index == 0:
            self.open_device_editor()

    def sync_section(self):
        w = self.page
        mode = w.current_mode
        section = getattr(w, 'current_section', mode + '.overview')
        source_mode = section.split('.')[0]
        stage = (1 if mode == 'coupled' and source_mode in ('electrical', 'optical') else
            next((i for i, (_, sections) in enumerate(STAGES[mode]) if section.split('.')[-1] in sections), 1))
        self.extra_stage = None
        self._leave_device_editor()
        self.compact_view = 'settings'
        self._syncing = True
        try:
            descriptions = {
                'optical': ['Edit the periodic structure and material assignments. Continue to illumination and scan samples.',
                    'Set wavelength or angle samples, polarization and optical material data. Continue to Fourier accuracy and outputs.',
                    'Choose Fourier accuracy, phase and field outputs. Continue to input and runtime checks.'],
                'electrical': ['Edit finite layers, contacts, doping and mesh. Continue to electrode potentials and the charge model.',
                    'Assign the swept electrode, held potentials and bias samples. Review the selected electrostatic or transport model.',
                    'Review the actual finite mesh and terminal outputs. Continue to input and runtime checks.'],
                'coupled': ['Edit the finite electrical device and identify the periodic optical cell. Continue to layer mapping.',
                    'Map electrical layers to optical materials and choose the reference state and averaging cell. Continue to spectral response.',
                    'Choose spectral samples, material corrections and feature tracking. Continue to transfer checks.']
            }[mode] + [
                'Check the current draft; select an issue to focus its exact input. Continue to the validated calculation.',
                'Start the calculation and inspect worker progress. Stop cancels only this study’s job. Continue to saved results.',
                'Inspect the saved run and its numerical and model checks. Return to inputs to prepare another calculation.']
            if w._simulation_context == 'electrical.iv':
                descriptions[1] = 'Choose the current model, applied terminal-voltage samples and optional measured I–V data. Continue to mesh and current checks.'
            elif w._simulation_context == 'electrical.cv':
                descriptions[1] = 'Choose the swept electrode and held potentials. Sample raw electrode charge for signed dQ/dV; measured C–V data are optional.'
            self.journey_bar.set_stages([dict(title=label, description=descriptions[i], icon=('cube','settings','mesh','check','play','spectrum')[i]) for i,(label,_) in enumerate(STAGES[mode])])
            self.step_buttons = self.journey_bar.buttons
            self.journey_bar.set_current(stage)
            for i in range(w.navigation.count()):
                item = w.navigation.item(i)
                suffix = item.data(Qt.ItemDataRole.UserRole).split('.')[-1]
                item.setHidden(suffix not in STAGES[mode][stage][1])
            w.navigation.setMaximumHeight(54 * len(STAGES[mode][stage][1]) + 12)
            with QSignalBlocker(self.section_picker):
                self.section_picker.clear()
                source_mode = section.split('.')[0]
                for tab in w._modes[source_mode]['tabs']:
                    self.section_picker.addItem(tab['title'], tab['id'])
                self.section_picker.setCurrentIndex(self.section_picker.findData(section))
            w.purpose.setText(w.section_meta.get(section, {}).get('title', 'Setup'))
            w.purpose.setToolTip(w.section_meta.get(section, {}).get('purpose', ''))
            if self.compact:
                self.show_compact('settings')
        finally:
            self._syncing = False
        self._sync_scene()
        self.adapt_layout(force=True)
        if stage == 0 and section == mode + '.overview' and not self._device_settings:
            self.open_device_editor()

    def refresh(self):
        w = self.page; device = w.store.device or {}
        if self.extra_stage == 3:
            self.check_summary.setText(w.summary.text())
        w.sequence.setVisible(w.current_mode == 'coupled' and self.summary_toggle.isChecked())
        if self._device_snapshot is device:
            signature = self._object_signature
        else:
            signature = tuple((group, len(device.get(group, [])), tuple((r.get('id'), r.get('name'), r.get('enabled', True)) for r in device.get(group, [])[:500]))
                              for group in ('layers', 'shapes', 'contacts', 'doping_regions'))
            self._device_snapshot = device
        if signature != self._object_signature:
            self._object_signature = signature
            with QSignalBlocker(self.object_tree):
                self.object_tree.clear()
                for group, title, icon in [('layers', 'Layers', 'layers'), ('shapes', 'Geometry', 'cube'), ('contacts', 'Contacts', 'simulation'), ('doping_regions', 'Doping regions', 'materials')]:
                    rows = device.get(group, [])
                    if not rows: continue
                    parent = QTreeWidgetItem([f'{title} ({len(rows)})']); self.object_tree.addTopLevelItem(parent)
                    parent.setIcon(0, reference_icon(icon, COLORS[theme_manager().mode]['muted']))
                    # Large arrays remain usable without building 100k Qt rows.
                    for row in rows[:500]:
                        item = QTreeWidgetItem([row.get('name') or row.get('id', 'Object')])
                        item.setData(0, Qt.ItemDataRole.UserRole, row.get('id'))
                        item.setToolTip(0, row.get('id', ''))
                        parent.addChild(item)
                    if len(rows) > 500:
                        parent.addChild(QTreeWidgetItem([f'{len(rows)-500:,} more · open Structure']))
                    parent.setExpanded(group == 'layers')
        self.select_object(getattr(w, 'selected_object', ''))
        width, depth = device.get('width_um', 0), device.get('depth_um', 0)
        domain = 'Finite electrical domain' if w.current_mode == 'electrical' else 'Finite device · optical simulation repeats the chosen cell'
        self.domain.setText(f'{width:g} × {depth:g} µm  ·  {domain}')
        if self.coupled_preview is not None:
            self.coupled_preview.set_device(device, getattr(w, 'selected_object', ''))
            self.coupled_preview.optical_unit_cell = w.state.get('settings.optical_unit_cell')
        self._sync_scene()

    def _object_selected(self, current, previous):
        if current and current.data(0, Qt.ItemDataRole.UserRole):
            self.page.select_object(current.data(0, Qt.ItemDataRole.UserRole))

    def _build_outcomes(self):
        from PyQt6.QtWidgets import QPlainTextEdit
        self.outcome_pages = {}
        for index in (3, 4, 5):
            panel = QWidget()
            panel.setMinimumWidth(0)
            layout = QVBoxLayout(panel)
            self.page.stack.addWidget(panel)
            self.outcome_pages[index] = panel
        check = self.outcome_pages[3].layout()
        self.check_summary = QLabel('Review the current inputs before validating.'); self.check_summary.setWordWrap(True)
        check.addWidget(self.check_summary)
        self.review_button = QPushButton('Review current inputs')
        self.review_button.clicked.connect(lambda: self.page._review_setup())
        check.addWidget(self.review_button)
        self.check_button = QPushButton('Check current inputs')
        self.check_button.clicked.connect(self.page.validate_current)
        check.addWidget(self.check_button)
        runtime = QPushButton('Check selected runtime')
        runtime.clicked.connect(self.page._runtime_check)
        check.addWidget(runtime)
        note = QLabel('Validation checks the current draft and model compatibility. Numerical convergence is established from saved solver evidence, not from a ready badge. Select any reported issue to open its exact field.')
        note.setWordWrap(True); check.addWidget(note); check.addStretch()
        run = self.outcome_pages[4].layout()
        self.run_state = QLabel('No calculation is running for this study.'); self.run_state.setWordWrap(True)
        run.addWidget(self.run_state)
        self.run_log = QPlainTextEdit(); self.run_log.setReadOnly(True)
        self.run_log.document().setMaximumBlockCount(2000)
        self.run_log.setAccessibleName('Actual calculation progress and log')
        run.addWidget(self.run_log, 1)
        actions = QHBoxLayout()
        self.run_button = QPushButton('Validate and run this study')
        self.run_button.clicked.connect(self.page.run)
        self.stop_button = QPushButton('Stop this calculation'); self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._cancel)
        actions.addWidget(self.run_button); actions.addWidget(self.stop_button); run.addLayout(actions)
        results = self.outcome_pages[5].layout()
        self.result_note = QLabel('Results appear here after a real saved solve. No calculated fields or curves are available yet.')
        self.result_note.setWordWrap(True); results.addWidget(self.result_note)
        self.result_dashboard = None
        self.open_result_button = QPushButton('View this completed run')
        self.open_result_button.setEnabled(False)
        self.open_result_button.clicked.connect(self._open_result)
        results.addWidget(self.open_result_button)
        self.browse_result_button = QPushButton('Open a saved run…')
        self.browse_result_button.setToolTip('Choose a saved run folder to inspect its plots and fields without rerunning or replacing this study’s inputs.')
        self.browse_result_button.clicked.connect(self._browse_result)
        results.addWidget(self.browse_result_button)
        back = QPushButton('Return to editable inputs'); back.clicked.connect(lambda: self.show_stage(0))
        results.addWidget(back)

    def open_device_editor(self, identity=None):
        if not self.page._is_active_document() or self.page.store.busy:
            return False
        self.extra_stage = None
        self._device_settings = False
        if self.device_editor is None:
            from qt_study_device_editor import StudyDeviceEditor
            self.device_editor = StudyDeviceEditor(self.page, include_advanced=self.page.current_mode == 'optical')
            self.device_editor.continue_requested.connect(lambda: self.show_stage(1))
            self.device_editor.return_requested.connect(self.show_device_settings)
            self.views.addWidget(self.device_editor)
        if not self.device_editor.open_editor(identity):
            return False
        self.journey_bar.set_current(0)
        self.views.setCurrentWidget(self.device_editor)
        self.scene_caption.setText('Edit this study’s geometry, contacts and mesh')
        self.view_choice.hide()
        self.fit_button.hide()
        self.selection.hide(); self.legend.hide(); self.domain.hide()
        self.adapt_layout(force=True)
        return True

    def show_device_settings(self):
        self._device_settings = True
        self._leave_device_editor()
        self.page.select_section(self.page.current_mode + '.overview')
        self.show_compact('settings')

    def _leave_device_editor(self):
        if self.device_editor is not None and self.views.currentWidget() is self.device_editor:
            self.views.setCurrentIndex(self.view_choice.currentIndex())
        self.view_choice.show()
        self.fit_button.show()
        self.selection.show(); self.legend.show(); self.domain.show()

    def _sync_scene(self):
        if self.device_editor is not None and self.views.currentWidget() is self.device_editor:
            return
        w = self.page
        study = w._simulation_context or ''
        variant = 'iv' if study == 'electrical.iv' else 'cv' if study == 'electrical.cv' else ''
        stage = self.journey_bar._current
        if variant and stage > 0:
            self.scene_caption.setText('Current–voltage experiment' if variant == 'iv' else 'Electrode charge → electrostatic capacitance')
            if self.curve_preview is not None and getattr(self, '_curve_variant', '') == variant:
                self.views.setCurrentWidget(self.curve_preview)
                self.view_choice.hide()
                return
            if self.curve_preview is None:
                from qt_common import PlotWidget
                self.curve_preview = PlotWidget()
                self.views.addWidget(self.curve_preview)
            from matplotlib.figure import Figure
            figure = Figure(figsize=(7, 5), layout='constrained')
            axes = figure.subplots(1 if variant == 'iv' else 2, 1, squeeze=False).ravel()
            frame = None
            if getattr(self, '_result_loaded', False) and self.result_dashboard is not None:
                frame = self.result_dashboard.iv_data if variant == 'iv' else self.result_dashboard.cv_data
            columns = [('current_A', 'Current (A)')] if variant == 'iv' else [('terminal_charge_C', 'Electrode charge (C)'), ('capacitance_F', 'Signed dQ/dV (F)')]
            for ax, (column, ylabel) in zip(axes, columns):
                ax.set_xlabel('Actual swept-terminal voltage (V)'); ax.set_ylabel(ylabel)
                if frame is not None and not frame.empty and column in frame:
                    import numpy as np
                    import pandas as pd
                    xkey = 'terminal_voltage_V' if 'terminal_voltage_V' in frame else 'bias_V'
                    if xkey in frame:
                        x = pd.to_numeric(frame[xkey], errors='coerce').to_numpy(float)
                        y = pd.to_numeric(frame[column], errors='coerce').to_numpy(float)
                        keep = np.isfinite(x); order = np.argsort(x[keep])
                        if np.any(keep & np.isfinite(y)):
                            # Retain NaN gaps instead of drawing through unavailable physical regimes.
                            ax.plot(x[keep][order], y[keep][order], '-o', markersize=4)
                            ax.set_title('Saved run · inputs frozen at calculation', fontsize=10)
                if not ax.lines:
                    ax.text(.5, .5, 'Saved samples appear after a real solve.\nOpen Results to inspect calculated curves.', transform=ax.transAxes, ha='center', va='center', fontsize=10)
                ax.grid(alpha=.15)
            self.curve_preview.draw_figure(figure)
            self._curve_variant = variant
            self.views.setCurrentWidget(self.curve_preview)
            self.view_choice.hide()
        elif w.current_mode == 'coupled':
            if self.coupled_preview is None:
                from qt_custom_device import DeviceCanvas
                paired = QWidget(); pair_layout = QHBoxLayout(paired)
                finite = DeviceCanvas('3d'); self.coupled_finite = finite
                self.coupled_preview = DeviceCanvas('top')
                for title, view in [('Finite electrical device', finite), ('Periodic optical cell · cyan outline', self.coupled_preview)]:
                    body = QWidget(); column = QVBoxLayout(body); column.addWidget(QLabel(title)); column.addWidget(view, 1)
                    view.setMinimumWidth(0); view.object_selected.connect(w.select_object)
                    pair_layout.addWidget(body, 1)
                self.coupled_pair = paired; self.views.addWidget(paired)
            device = w.store.device or {}
            self.coupled_finite.set_device(device, getattr(w, 'selected_object', ''))
            self.coupled_preview.set_device(device, getattr(w, 'selected_object', ''))
            self.coupled_preview.optical_unit_cell = w.state.get('settings.optical_unit_cell')
            self.views.setCurrentWidget(self.coupled_pair)
            self.scene_caption.setText('Finite electrical domain → periodic optical cell')
            self.view_choice.hide()
        else:
            self.scene_caption.setText('This simulation’s device · editable geometry preview')
            self.view_choice.show()
            self.views.setCurrentIndex(self.view_choice.currentIndex())

    def _run_requested(self, mode):
        if mode == self.page.current_mode and self.page._is_active_document() and not self.page.store.busy:
            self._pending_run = True
            self._submission_worker = getattr(self.page.store, '_worker', None)
            self._submission_mode = mode
            QTimer.singleShot(0, self._end_submission)
            self.run_log.clear()
            self.run_state.setText('Submitting the validated request. No result is claimed until the worker reports it.')
            self.show_stage(4)

    def _busy_changed(self, busy):
        if busy and self._pending_run:
            worker = getattr(self.page.store, '_worker', None)
            allowed = {'simulation', 'simulation_fields', 'fields', 'fdtd'} if self._submission_mode == 'optical' else {self._submission_mode}
            if worker is not None and worker is not self._submission_worker and getattr(worker, 'kind', '') in allowed:
                self._owns_run = True
                self.run_state.setText('Calculation running. Progress below is reported by the real worker.')
            self._pending_run = False
        if not busy:
            self._owns_run = False
        self._sync_run_controls()

    def _sync_run_controls(self, *_):
        # Active study changes do not necessarily emit a busy transition.
        busy = self.page.store.busy
        self.run_button.setEnabled(not busy and self.page._is_active_document())
        self.stop_button.setEnabled(bool(busy and self._owns_run))

    def _end_submission(self):
        if self._pending_run:
            self._pending_run = False
            self.run_state.setText('No calculation was started. Review the reported input or runtime issue before trying again.')

    def _cancel(self):
        if self._owns_run and self.page.store.busy:
            self.page.store.cancel()

    def _progress(self, event):
        if self._owns_run:
            text = event.get('text') or event.get('message') or str(event)
            self.run_log.appendPlainText(str(text))

    def _finished(self, event):
        if not self._owns_run:
            return
        self.completed_event = event
        self._owns_run = False; self.stop_button.setEnabled(False)
        summary = event.get('summary', {})
        self.run_state.setText('Saved run status: '+str(summary.get('status', 'finished'))+'. Inspect numerical and model checks in Results.')
        self.result_note.setText('Saved run: '+str(event.get('directory', ''))+'\nStatus: '+str(summary.get('status', 'finished'))+'. These results belong to the saved request.')
        self.open_result_button.setEnabled(bool(event.get('directory')))
        self._result_loaded = False
        self._curve_variant = ''
        if self.result_dashboard is not None:
            self.result_dashboard.hide()
        if self.page.current_mode != 'optical' and event.get('directory'):
            import json
            from pathlib import Path
            from qt_electrical_results import ElectricalResultsPanel, saved_result_path
            try:
                # Worker events contain search_summary metadata, not the saved volume/result rows.
                saved_summary = summary
                if not isinstance(saved_summary.get('results'), list):
                    path = saved_result_path(Path(event['directory']), 'electrical_summary.json')
                    if path is None:
                        raise ValueError('No saved electrical summary is available.')
                    saved_summary = json.loads(path.read_text(encoding='utf-8'))
                if self.result_dashboard is None:
                    self.result_dashboard = ElectricalResultsPanel()
                    self.outcome_pages[5].layout().insertWidget(1, self.result_dashboard, 1)
                self.result_dashboard.set_result(event['directory'], saved_summary)
                self._result_loaded = True
                self.result_dashboard.show()
                study = self.page._simulation_context
                if study in ('electrical.iv', 'electrical.cv'):
                    self.result_dashboard.tabs.setCurrentIndex(1 if study.endswith('.iv') else 2)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                if self.result_dashboard is not None:
                    self.result_dashboard.hide()
                self.result_note.setText(self.result_note.text()+'\nSaved electrical preview could not be loaded: '+str(exc))
        if self.page._is_active_document():
            self.show_stage(5)

    def _failed(self, message):
        if self._owns_run or self._pending_run:
            self._owns_run = self._pending_run = False
            self.stop_button.setEnabled(False)
            self.run_state.setText('Calculation failed: '+str(message))
            self.run_log.appendPlainText(str(message))

    def _open_result(self):
        if self.completed_event:
            self.page.resultsRequested.emit(self.completed_event)

    def _browse_result(self):
        if not self.page._is_active_document():
            return
        path = QFileDialog.getExistingDirectory(self.page, 'Open simulation results', str(self.page.store.library.runs))
        if path:
            # Viewing is separate from restoring inputs or claiming completion.
            self.page.resultsRequested.emit(dict(directory=path))

    def select_object(self, ident):
        device = self.page.store.device or {}
        found = next(((group, row) for group in ('layers', 'shapes', 'contacts', 'doping_regions') for row in device.get(group, []) if row.get('id') == ident), None)
        self.edit_object.setEnabled(found is not None)
        if found:
            group, row = found
            detail = [row.get('name') or ident]
            for key, caption, unit in [('thickness_um', 'Thickness', 'µm'), ('cx_um', 'X', 'µm'), ('cy_um', 'Y', 'µm'), ('size_x_um', 'Width', 'µm'), ('material_id', 'Material', '')]:
                if key in row: detail.append(f'{caption}: {row[key]} {unit}'.rstrip())
            self.selection.setText('  ·  '.join(detail))
        else:
            self.selection.setText('Select an object in the scene or object list.')
        with QSignalBlocker(self.object_tree):
            for i in range(self.object_tree.topLevelItemCount()):
                parent = self.object_tree.topLevelItem(i)
                for j in range(parent.childCount()):
                    item = parent.child(j)
                    if item.data(0, Qt.ItemDataRole.UserRole) == ident and ident:
                        self.object_tree.setCurrentItem(item)
                        return

    def edit_selected(self):
        ident = getattr(self.page, 'selected_object', '')
        self.open_device_editor(ident or 'device')

    def show_compact(self, view):
        self.compact_view = view
        if self.compact or self.page.width() < 1120:
            # Hide the previous panel before showing another; showing both even
            # momentarily can grow a native window beyond its requested size.
            panels = {'objects': self.page.nav_panel, 'device': self.scene, 'settings': self.page.center}
            for panel in panels.values():
                panel.hide()
                panel.setMinimumWidth(0); panel.setMaximumWidth(16777215)
            panels[view].show()
        for key, button in self.compact_buttons.items(): button.setChecked(key == view)

    def adapt_layout(self, force=False):
        w = self.page; compact = w.width() < 1120
        full = self.extra_stage is not None or self.device_editor is not None and self.views.currentWidget() is self.device_editor
        if compact != self.compact or force:
            self.compact = compact
            while w.body.count(): w.body.takeAt(0)
            if full:
                target = w.center if self.extra_stage is not None else self.scene
                for panel in (w.nav_panel, self.scene, w.center):
                    panel.setVisible(panel is target)
                target.setMinimumWidth(0); target.setMaximumWidth(16777215)
                w.body.addWidget(target, 1)
            elif compact:
                for panel in (w.nav_panel, self.scene, w.center):
                    panel.setVisible(panel is {'objects': w.nav_panel, 'device': self.scene, 'settings': w.center}[self.compact_view])
                    panel.setMinimumWidth(0); panel.setMaximumWidth(16777215)
                    w.body.addWidget(panel, 1)
            else:
                w.nav_panel.setMinimumWidth(175); w.nav_panel.setMaximumWidth(215)
                self.scene.setMinimumWidth(280); self.scene.setMaximumWidth(16777215)
                w.center.setMinimumWidth(330); w.center.setMaximumWidth(440)
                w.body.addWidget(w.nav_panel, 0); w.body.addWidget(self.scene, 1); w.body.addWidget(w.center, 0)
                for panel in (w.nav_panel, self.scene, w.center): panel.show()
        self.compact_bar.setVisible(compact and not full)
        note = w.findChild(QLabel, 'setupModeNote')
        if note is not None: note.setVisible(not compact)
        if compact and not full: self.show_compact(self.compact_view)
        for field in w.fields: field.set_horizontal(False)
        for grid, cards in w.page_grids: w._reflow_grid(grid, cards)

    def apply_style(self):
        c = COLORS[theme_manager().mode]
        for mode, button in self.page.mode_buttons.items():
            button.setIcon(reference_icon({'optical':'simulation','electrical':'mesh','coupled':'settings'}[mode], c['accent']))
            button.setIconSize(QSize(17, 17))
        for button, icon in zip(self.step_buttons, ('cube', 'materials', 'play')):
            button.setIcon(reference_icon(icon, c['accent']))
            button.setIconSize(QSize(17, 17))
        for button in list(self.compact_buttons.values()) + [self.edit_object, self.edit_structure]:
            button.setIcon(reference_icon(button.property('flowIcon'), c['accent']))
            button.setIconSize(QSize(17, 17))
        self.page.setStyleSheet(self.page.styleSheet() + f'''
            QFrame#setupScene {{ background:{c['panel']}; border:1px solid {c['border']}; border-radius:9px; }}
            QLabel#setupTitle {{font-size:23px;font-weight:600;}}
            QLabel#setupInspectorTitle {{font-size:16px;font-weight:600;padding:4px 2px;}}
            QPushButton#setupStep {{background:transparent;border:0;border-bottom:2px solid {c['border']};border-radius:0;color:{c['muted']};padding:7px;}}
            QPushButton#setupStep:checked {{color:{c['accent']};border-bottom:2px solid {c['accent']};font-weight:600;}}
            QPushButton#setupView:checked {{background:{c['select']};color:{c['accent']};}}
            QTreeWidget#setupObjectTree {{background:transparent;border:0;outline:0;}}
            QTreeWidget#setupObjectTree::item {{padding:6px 2px;}}
            QTreeWidget#setupObjectTree::item:selected {{background:{c['select']};color:{c['accent']};}}
            QFrame#setupCard,QFrame#setupNavigation {{border-radius:8px;}}
        ''')
