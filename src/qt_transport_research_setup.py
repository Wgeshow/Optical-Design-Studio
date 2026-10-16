"""Guided editable finite-device transport and high-field optical studies."""
from copy import deepcopy
import uuid

from PyQt6.QtCore import Qt, QPointF, QRectF, QSize
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLayout, QLineEdit,
    QScrollArea, QSizePolicy, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from qt_research_common import button, label
from qt_research_studies import StructuredStudyWorkspace
from qt_study_fields import NamedPropertyForm, SequenceField, replace_structured_form
from qt_study_flow import install_study_flow
from qt_common import COLORS, theme_manager
from qt_reference_style import reference_icon


class TransportDevicePanel(QWidget):
    """Select the actual shared device; all edits route to its owning inspector."""
    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace
        self.current_id = 'device'
        self.objects = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.compact_choice = QComboBox()
        self.compact_choice.addItems(['Setup controls', 'Device preview'])
        self.compact_choice.setAccessibleName('Compact device panel')
        self.compact_choice.currentIndexChanged.connect(self.adapt_layout)
        layout.addWidget(self.compact_choice)
        self.splitter = QSplitter()
        layout.addWidget(self.splitter, 1)
        self.left = QWidget()
        left = QVBoxLayout(self.left); left.setContentsMargins(8, 8, 8, 8)
        left.addWidget(label('Objects', 'setupHeading'))
        self.add_button = button('Add / edit objects', lambda: self.edit_object('device'))
        left.addWidget(self.add_button)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAccessibleName('Shared device objects')
        self.tree.currentItemChanged.connect(self._selected)
        self.tree.setMinimumWidth(120)
        left.addWidget(self.tree, 1)
        self.splitter.addWidget(self.left)
        self.middle = QWidget()
        middle = QVBoxLayout(self.middle); middle.setContentsMargins(8, 8, 8, 8)
        middle.addWidget(label('Device structure', 'setupHeading'))
        toolbar = QHBoxLayout()
        self.view_choice = QComboBox()
        for caption, mode in [('3D structure', '3d'), ('Top view', 'top'), ('Section', 'section')]:
            self.view_choice.addItem(caption, mode)
        self.view_choice.setAccessibleName('Device preview view')
        self.view_choice.currentIndexChanged.connect(self._view_changed)
        toolbar.addWidget(self.view_choice)
        self.reset_button = button('Reset view', self.reset_view)
        toolbar.addWidget(self.reset_button)
        toolbar.addStretch()
        middle.addLayout(toolbar)
        from qt_custom_device import DeviceCanvas
        self.canvas = DeviceCanvas('3d')
        self.canvas.setMinimumSize(180, 240)
        self.canvas.compact_preview = True
        self.canvas.depth_display_mode = 'physical'
        self.canvas.set_render_quality('studio', reflections=False)
        self.canvas.object_selected.connect(self.select_object)
        middle.addWidget(self.canvas, 1)
        self.preview_note = label('')
        middle.addWidget(self.preview_note)
        self.splitter.addWidget(self.middle)
        self.right = QScrollArea()
        self.right.setWidgetResizable(True)
        self.right.setFrameShape(QScrollArea.Shape.NoFrame)
        self.right.setMinimumWidth(220)
        panel = QWidget(); right = QVBoxLayout(panel)
        right.setContentsMargins(10, 8, 10, 8)
        self.selected_title = label('Device', 'setupHeading')
        right.addWidget(self.selected_title)
        self.object_summary = label('')
        right.addWidget(self.object_summary)
        self.edit_button = button('Edit selected object', self.edit_selected)
        right.addWidget(self.edit_button)
        right.addWidget(label('Bias & assignments', 'setupHeading'))
        right.addWidget(label('Contact to sweep'))
        self.contact_picker = QComboBox()
        self.contact_picker.setAccessibleName('Device contact to bias')
        right.addWidget(self.contact_picker)
        self.contact_picker.currentIndexChanged.connect(workspace._contact_selected)
        right.addWidget(label('Bias sequence (V)'))
        self.bias = SequenceField(workspace.structured['biases_V'], 'Enter explicit voltages, separated by commas')
        right.addWidget(self.bias)
        right.addWidget(label('Other contact voltages and doping come from the shared device.'))
        self.material_button = button('Edit material properties', lambda: workspace.diagnosticRequested.emit(
            dict(workspace='materials', section='electrical', field='electrical_materials',
                 message='Edit the material properties used by this transport study.')))
        right.addWidget(self.material_button)
        self.physics_button = button('Contact and interface laws', lambda: workspace.study_flow.show_stage(1))
        right.addWidget(self.physics_button)
        right.addStretch()
        self.right.setWidget(panel)
        self.splitter.addWidget(self.right)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([200, 610, 290])
        self.setMinimumHeight(350)
        theme_manager().changed.connect(self._icons)
        theme_manager().appearance_changed.connect(self._icons)
        self._icons()
        self._view_changed()

    def _icons(self):
        color = COLORS[theme_manager().mode]['accent']
        for control, name in ((self.add_button, 'plus'), (self.edit_button, 'structure'),
                (self.reset_button, 'reset'), (self.material_button, 'materials'), (self.physics_button, 'settings')):
            control.setIcon(reference_icon(name, color)); control.setIconSize(QSize(17, 17))
        for index, name in enumerate(('cube', 'mesh', 'layers')):
            self.view_choice.setItemIcon(index, reference_icon(name, color))
        for identity, (item, group, obj) in self.objects.items():
            item.setIcon(0, reference_icon('layers' if group == 'layers' else 'mesh' if identity == 'mesh' else 'cube', color))

    def refresh(self, device):
        self.device = device
        self.tree.blockSignals(True); self.tree.clear(); self.objects = {}
        def append(parent, title, identity, group, obj):
            item = QTreeWidgetItem(parent, [title])
            item.setData(0, Qt.ItemDataRole.UserRole, identity)
            self.objects[identity] = (item, group, obj)
        append(self.tree, 'Device boundary', 'device', 'device', device)
        for group, title in [('layers', 'Layers'), ('shapes', 'Patterns'), ('contacts', 'Contacts'), ('doping_regions', 'Doping regions')]:
            rows = device.get(group, [])
            if not rows: continue
            parent = QTreeWidgetItem(self.tree, [title])
            parent.setFlags(parent.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            for obj in rows:
                title = obj.get('name') or obj['id']
                if not obj.get('enabled', True): title += ' · disabled'
                append(parent, title, obj['id'], group, obj)
        append(self.tree, 'Mesh control', 'mesh', 'mesh', device.get('mesh', {}))
        self.tree.expandAll(); self.tree.blockSignals(False)
        self._icons()
        self.select_object(self.current_id if self.current_id in self.objects else 'device')
        self.bias.refresh()

    def select_object(self, identity):
        record = self.objects.get(identity)
        if record is None: return False
        self.tree.setCurrentItem(record[0])
        self._selected(record[0])
        return True

    def _selected(self, item, previous=None):
        identity = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if identity not in self.objects: return
        self.current_id = identity
        _, group, obj = self.objects[identity]
        self.selected_title.setText(item.text(0))
        props = [('material_id', 'Material', ''), ('thickness_um', 'Thickness', ' µm'),
                 ('shape', 'Shape', ''), ('radius_um', 'Radius', ' µm'), ('voltage', 'Voltage', ' V'),
                 ('donor_cm3', 'Donors', ' cm⁻³'), ('acceptor_cm3', 'Acceptors', ' cm⁻³')]
        lines = [f'{title}: {obj[key]}{unit}' for key, title, unit in props if key in obj]
        if identity == 'device':
            lines = ['Geometry, layers and contacts are shared with Structure.']
        elif identity == 'mesh':
            lines = ['Edit the shared spatial grid and refinement settings in Structure.']
        self.object_summary.setText('\n'.join(lines) or 'Select Edit selected object for all geometry and assignment fields.')
        layer = identity if group == 'layers' else obj.get('layer_id', '')
        self.canvas.set_device(self.device, selected=identity, selected_layer=layer)

    def edit_selected(self):
        self.edit_object(self.current_id)

    def edit_object(self, identity):
        self.workspace.diagnosticRequested.emit(dict(workspace='structure', section='device', field='device',
            object_id=identity, message='Edit this shared device object; return to the study to continue.'))

    def _view_changed(self):
        self.canvas.mode = self.view_choice.currentData()
        scope = 'Representative cell · insulating side faces.' if self.workspace.engine == 'pcsel_unitcell_transport' else 'Authored finite device · setup preview.'
        self.preview_note.setText(scope + (' Section at y = 0; depth scaled to fit.' if self.canvas.mode == 'section'
            else ' Drag to rotate; scroll to zoom.' if self.canvas.mode == '3d' else 'Top view of the selected layer.'))
        self.canvas.update()

    def reset_view(self):
        self.canvas.zoom = 1.; self.canvas.pan = QPointF(); self.canvas.yaw = -.6; self.canvas.elevation = .48
        self.canvas.update()

    def adapt_layout(self, *args):
        compact = self.workspace.width() < 1100
        preview = self.compact_choice.currentIndex() == 1
        self.compact_choice.setVisible(compact)
        self.left.setVisible(not compact or not preview)
        self.right.setVisible(not compact or not preview)
        self.middle.setVisible(not compact or preview)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.adapt_layout()


class IllustrativeBands(QWidget):
    """A schematic explanation of material inputs, never numerical output."""
    def __init__(self, form, parent=None):
        super().__init__(parent)
        self.form = form
        self.setMinimumSize(200, 260)
        self.setAccessibleName('Illustrative conduction and valence bands, not calculated results')
        form.editor.changed.connect(self.update)
        form.navigator.currentItemChanged.connect(lambda *args: self.update())
        theme_manager().changed.connect(self._theme_changed)
        theme_manager().appearance_changed.connect(self._theme_changed)

    def _theme_changed(self, *args):
        self.update()

    def paintEvent(self, event):
        colors = COLORS[theme_manager().mode]
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ink, muted = QColor(colors['text']), QColor(colors['muted'])
        painter.setPen(ink)
        painter.drawText(QRectF(12, 12, self.width()-24, 42), Qt.AlignmentFlag.AlignLeft, 'Material band model')
        w, h = self.width(), self.height()
        cx = w*.47; top = max(72., h*.20); bottom = h*.68
        gap = min(50., (bottom-top)*.32); cy = (top+bottom)/2
        for sign, color in [(-1, '#2874e7'), (1, '#e66671')]:
            path = QPainterPath()
            for step in range(61):
                x = (step/60.-.5)*w*.62
                y = cy + sign*(gap/2 + (x/(w*.31))**2*(bottom-top-gap)*.45)
                point = QPointF(cx+x, y)
                path.moveTo(point) if step == 0 else path.lineTo(point)
            painter.setPen(QPen(QColor(color), 2.1)); painter.drawPath(path)
        painter.setPen(QPen(muted, 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(w*.13, cy-gap/2), QPointF(w*.82, cy-gap/2))
        painter.drawLine(QPointF(w*.13, cy+gap/2), QPointF(w*.82, cy+gap/2))
        painter.setPen(ink)
        painter.drawLine(QPointF(cx, cy-gap/2+3), QPointF(cx, cy+gap/2-3))
        painter.drawText(QRectF(cx+8, cy-12, w*.5-14, 25), 'Eg')
        painter.setPen(QColor('#2874e7')); painter.drawText(QRectF(12, top-23, w-24, 25), Qt.AlignmentFlag.AlignRight, 'Conduction band')
        painter.setPen(QColor('#e66671')); painter.drawText(QRectF(12, bottom+8, w-24, 25), Qt.AlignmentFlag.AlignRight, 'Valence band')
        source = self.form._array_source()
        values = {source.child(i).text(0): source.child(i).text(1) for i in range(source.childCount())} if source else {}
        supplied = values.get('bandgap_eV', values.get('reference_gap_eV', ''))
        caption = 'Supplied gap: '+supplied+' eV' if supplied else 'Enter the gap in the selected material or state.'
        painter.setPen(muted)
        painter.drawText(QRectF(12, h-78, w-24, 33), Qt.TextFlag.TextWordWrap, caption)
        painter.drawText(QRectF(12, h-55, w-24, 50), Qt.TextFlag.TextWordWrap,
            'Illustrative bands · not to scale\nCalculate to obtain optical response.')


class TransportResearchWorkspace(StructuredStudyWorkspace):
    """Presentation over the existing authoritative typed transport request."""
    def __init__(self, store, capability, parent=None):
        self.input_forms = {}
        super().__init__(store, capability, parent)
        self._setup_native_forms()
        self.device_note = label('')
        _, domain = self.add_section('Device & assignments', 'device_context')
        domain.addWidget(self.device_note)
        self.device_panel = TransportDevicePanel(self)
        self.device_preview = self.device_panel.canvas
        self.contact_picker = self.device_panel.contact_picker
        domain.addWidget(self.device_panel, 1)
        _, review = self.add_section('Review calculation', 'calculation_review')
        self.review_note = label('')
        review.addWidget(self.review_note)
        review.addWidget(button('Check inputs', self.validate_inputs))
        review.addWidget(label('Results retain convergence, current balance, thermal validity and model limitations. '
            'A completed job and agreement with a paper are reported separately.'))
        review.addStretch()
        self.study_flow = install_study_flow(self, [
            ('Device', ['device_context', 'Bias', 'Device assignments']),
            ('Physics', ['Materials', 'Contacts', 'Interfaces', 'Recombination', 'Heat', 'Tunnelling', 'Optical response']),
            ('Calculate', ['Solver', 'Model', 'calculation_review', 'Review & files'])],
            subtitle='Set the device and bias, choose the physical models, then check and calculate.',
            details='\n\n'.join(capability.get('limitations', [])))
        self.tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.heading.setText('PCSEL representative cell' if self.engine == 'pcsel_unitcell_transport' else 'Finite-contact transport')
        self.store.changed.connect(self.refresh_context)
        self.refresh_context()
        # A brand-new draft opens the device step. Restored section identity is
        # kept for existing work and diagnostic navigation.
        saved = store.search_state.get('research_workspaces', {}).get(self.state_key)
        if not saved:
            self.select_section('device_context')
            self.study_flow.show_stage(0)

    def _setup_native_forms(self):
        _, advanced = self.add_section('Advanced properties', 'advanced_properties')
        advanced.addWidget(label('Exact property editors retain every supported value. Normal setup uses the labeled forms in the study steps.'))
        for key, editor in self.structured.items():
            replacement = SequenceField(editor, 'For example: 0, 0.1, 0.2') if key in ('biases_V', 'wavelengths_nm') else NamedPropertyForm(editor)
            if replace_structured_form(self, key, replacement):
                self.input_forms[key] = replacement
                advanced.addWidget(label(next((row.get('label', key) for row in self.schema if row['path'] == key), key), 'setupHeading'))
                advanced.addWidget(editor)
                editor.show()
        advanced.addStretch()

    def _refresh_forms(self):
        for form in self.input_forms.values():
            form.refresh()
        if hasattr(self, 'device_panel'): self.device_panel.bias.refresh()

    def restore_draft(self, state):
        super().restore_draft(state)
        self._refresh_forms()

    def load_settings(self, settings):
        super().load_settings(settings)
        self._refresh_forms()
        if hasattr(self, 'device_note'):
            self.refresh_context()

    def create_model_fields(self, key):
        super().create_model_fields(key)
        self._refresh_forms()

    def refresh_context(self, *args):
        if not hasattr(self, 'contact_picker'):
            return
        device = getattr(self.store, 'device', None) or {}
        layers = [row for row in device.get('layers', []) if row.get('enabled', True)]
        contacts = [row for row in device.get('contacts', []) if row.get('enabled', True)]
        self.device_panel.refresh(device)
        self.device_note.setText(str(len(layers))+' enabled layers · '+str(len(contacts))+' enabled contacts · shared device')
        self.contact_picker.blockSignals(True)
        self.contact_picker.clear()
        self.contact_picker.addItem('Choose a contact…', '')
        for row in contacts:
            self.contact_picker.addItem(row.get('name', row['id']), row['id'])
        self.contact_picker.setCurrentIndex(max(0, self.contact_picker.findData(self.fields['swept_contact_id'].text())))
        self.contact_picker.blockSignals(False)
        scope = ('Representative cell with insulating side faces.' if self.engine == 'pcsel_unitcell_transport'
                 else 'Finite-device transport with explicit contact and interface laws.')
        self.review_note.setText(scope+'\n'+str(len(layers))+' layers and '+str(len(contacts))+' contacts from the current device.\n'
            'Bias sequence and model coefficients remain editable in the previous steps. Only assigned optional physics is used.')

    def _contact_selected(self, index):
        self.fields['swept_contact_id'].setText(self.contact_picker.itemData(index) or '')

    def open_diagnostic(self, target):
        field = target.get('field', '').removeprefix('settings.')
        root = field.split('.')[0]
        form = self.input_forms.get(root)
        if form is not None:
            if hasattr(form, 'preview_choice'):
                form.preview_choice.setCurrentIndex(0)
                self.adapt_layout()
            result = form.open_field(field, target.get('object_id', ''))
            if not result and hasattr(form, 'preview_choice'):
                current = form.editor.tree.currentItem()
                control = form._fields.get(current.text(0)) if current is not None else None
                if control is not None and current.text(0) == field.split('.')[-1]:
                    # A just-rebuilt field in the formerly hidden compact panel
                    # has not received Qt's deferred show event yet.
                    control.show()
                    from qt_input_diagnostics import reveal_and_focus
                    result = reveal_and_focus(control)
            if result:
                self.study_flow.refresh()
            return result
        return super().open_diagnostic(target)

    def adapt_layout(self):
        if hasattr(self, 'study_flow'): self.study_flow.adapt_layout()
        if hasattr(self, 'device_panel'): self.device_panel.adapt_layout()
        for form in self.input_forms.values():
            if hasattr(form, 'band_preview'):
                compact = self.width() < 1100
                preview = form.preview_choice.currentIndex() == 1
                form.preview_choice.setVisible(compact)
                form.band_preview.setVisible(not compact or preview)
                form.panel_scroll.setVisible(not compact or not preview)
                form.panel.show()
                form.navigator.setVisible(not compact or not preview)
                form.setMinimumHeight(420 if compact else 520)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.adapt_layout()


class HighFieldOpticsWorkspace(TransportResearchWorkspace):
    """Explicit material and carrier-state forms for local FK sensitivity."""
    def __init__(self, store, capability, parent=None):
        self.input_forms = {}
        StructuredStudyWorkspace.__init__(self, store, capability, parent)
        from qt_high_field_results import HighFieldResultsPanel
        old_results = self.results
        result_index = self.tabs.indexOf(old_results)
        self.tabs.removeTab(result_index)
        self.results = HighFieldResultsPanel(store, self)
        self.tabs.insertTab(result_index, self.results, 'Results')
        old_results.deleteLater()
        self._setup_native_forms()
        self.heading.setText('High-field optical response')
        self.tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        for key in ('material', 'samples'):
            form = self.input_forms[key]
            form.band_preview = IllustrativeBands(form)
            form.splitter.insertWidget(1, form.band_preview)
            form.panel_scroll = QScrollArea()
            form.panel_scroll.setWidgetResizable(True)
            form.panel_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            form.panel_scroll.setMinimumWidth(230)
            form.panel_scroll.setWidget(form.panel)
            form.splitter.insertWidget(2, form.panel_scroll)
            form.splitter.setStretchFactor(1, 1)
            form.splitter.setStretchFactor(2, 1)
            form.splitter.setSizes([185, 460, 350])
            form.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
            form.form.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
            form.panel.setMinimumWidth(230)
            form.panel_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
            form.preview_choice = QComboBox()
            form.preview_choice.addItems(['Edit input values', 'Illustrative bands'])
            form.preview_choice.setAccessibleName('Compact high-field panel')
            form.preview_choice.currentIndexChanged.connect(self.adapt_layout)
            form.layout().insertWidget(0, form.preview_choice)
            form.preview_choice.hide()
            form.setMinimumHeight(390)
            form.editor.changed.connect(self._refresh_high_field_presentation)
        material_layout = self.tabs.widget(self.sections['Material']).widget().layout()
        self.create_material_button = button('Add required material inputs', self.create_material_fields)
        self.input_forms['material'].panel_layout.insertWidget(1, self.create_material_button)
        states_layout = self.tabs.widget(self.sections['States']).widget().layout()
        controls = QHBoxLayout()
        self.add_state_button = button('Add field / carrier state', self.add_sample)
        self.remove_state_button = button('Remove selected state', self.remove_sample)
        controls.addWidget(self.add_state_button)
        controls.addWidget(self.remove_state_button)
        controls.addStretch()
        states_layout.addLayout(controls)
        states_layout.addWidget(label('Each state has its own electric field, band gap, temperature and reduced Fermi levels. '
            'These are material-response samples; no finite device or contact geometry is implied.'))
        _, review = self.add_section('Review calculation', 'calculation_review')
        review.addWidget(label('Calculate absorption and changes in refractive index for each wavelength and state.', 'setupHeading'))
        review.addWidget(label('Δn and Δk are relative to the supplied zero-field, unoccupied reference gap. '
            'Converge the energy cutoff and integration grid before interpreting quantitative differences.'))
        review.addWidget(button('Check inputs', self.validate_inputs))
        review.addStretch()
        self.study_flow = install_study_flow(self, [
            ('Material', ['Material']), ('States', ['States']),
            ('Calculate', ['Spectrum', 'Accuracy', 'calculation_review', 'Review & files'])],
            subtitle='Define the material, add field and carrier states, then calculate the optical response.',
            details='\n\n'.join(capability.get('limitations', [])))
        for form_layout in self.findChildren(QFormLayout):
            form_layout.setProperty('studyAlwaysStacked', True)
        theme_manager().changed.connect(self._refresh_high_field_presentation)
        theme_manager().appearance_changed.connect(self._refresh_high_field_presentation)
        self._refresh_high_field_presentation()
        saved = store.search_state.get('research_workspaces', {}).get(self.state_key)
        if not saved:
            self.study_flow.show_stage(0)

    def _refresh_high_field_presentation(self, *args):
        color = COLORS[theme_manager().mode]['accent']
        for name, icon in [('create_material_button', 'materials'), ('add_state_button', 'plus'), ('remove_state_button', 'delete')]:
            control = getattr(self, name, None)
            if control is not None: control.setIcon(reference_icon(icon, color))
        if hasattr(self, 'create_material_button'):
            self.create_material_button.setVisible(not self.structured['material'].tree.topLevelItem(0).childCount())
        for key in ('material', 'samples'):
            form = self.input_forms.get(key)
            if form is None: continue
            for node, source in form._nodes.values():
                node.setIcon(0, reference_icon('materials' if key == 'material' else 'field', color))
            if key == 'samples':
                current = form.navigator.currentItem()
                root = form.navigator.topLevelItem(0)
                if current is root and root is not None and root.childCount():
                    form.navigator.setCurrentItem(root.child(0))
        self.adapt_layout()

    def _refresh_forms(self):
        super()._refresh_forms()
        if hasattr(self, 'study_flow'): self._refresh_high_field_presentation()

    def create_material_fields(self):
        editor = self.structured['material']
        try:
            existing = editor.value()
        except ValueError:
            self.status.setText('Existing material fields are already editable. Finish their missing values.'); return
        if existing:
            self.status.setText('The current material was preserved. Edit its fields above.'); return
        editor.set_template(dict(electron_mass_ratio=None, hole_mass_ratios=[None],
            absorption_prefactor_cm1_sqrt_eV=None, reference_gap_eV=None, source=''))
        self._refresh_forms()
        self._edited()

    def add_sample(self):
        editor = self.structured['samples']
        editor.append_template(dict(id='state-'+uuid.uuid4().hex[:8], field_V_m=0., bandgap_eV=0.,
            temperature_K=0., electron_reduced_fermi=0., hole_reduced_fermi=0.),
            missing_numbers=('field_V_m', 'bandgap_eV', 'temperature_K', 'electron_reduced_fermi', 'hole_reduced_fermi'))
        self._refresh_forms()
        form = self.input_forms['samples']
        root = form.navigator.topLevelItem(0)
        if root.childCount():
            form.navigator.setCurrentItem(root.child(root.childCount()-1))

    def remove_sample(self):
        form = self.input_forms['samples']
        chosen = form.navigator.currentItem()
        if chosen is None:
            return
        path = chosen.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        source = form._nodes[path][1]
        root = self.structured['samples'].tree.topLevelItem(0)
        while source.parent() is not root:
            source = source.parent()
            if source is None:
                return
        root.removeChild(source)
        for index in range(root.childCount()):
            root.child(index).setText(0, str(index))
        self.structured['samples'].changed.emit()
        self._refresh_forms()
