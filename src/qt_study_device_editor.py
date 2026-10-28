"""A study-owned host for the complete, authoritative finite device editor."""
from copy import deepcopy
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QToolButton, QMenu, QTabBar, QComboBox, QSizePolicy


class StudyDeviceEditor(QWidget):
    continue_requested = pyqtSignal()
    return_requested = pyqtSignal()

    def __init__(self, owner, *, include_advanced=False, back_label='Device settings', optical_materials=False):
        super().__init__(owner)
        self.owner = owner
        self.store = owner.store
        self.include_advanced = include_advanced
        self.optical_materials = optical_materials or include_advanced
        self.document_id = getattr(owner, '_bound_study_id', None) or getattr(owner, '_simulation_context', None) or getattr(self.store, 'active_study', None)
        self.editor = None
        self._compact_editor = False
        self._layout_initialized = False
        self._desktop_sizes = [286, 920, 346]
        self._back_label = back_label
        self.setMinimumWidth(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.note = QLabel('Full device editor · Layers, shapes, arrays, contacts, doping, materials and mesh. Apply commits the selected object; navigation preserves its draft.')
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.actions = QWidget(self)
        row = QHBoxLayout(self.actions); row.setContentsMargins(0, 0, 0, 0)
        self.back_button = QPushButton(back_label)
        self.back_button.clicked.connect(self.return_requested)
        row.addWidget(self.back_button)
        self.menu_buttons = {}
        for key, title in [('objects', 'Objects'), ('drawing', 'Drawing and arrays'), ('materials', 'Materials'), ('export', 'Export')]:
            button = QToolButton(); button.setText(title)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            button.setAccessibleName(title + ' editor actions')
            row.addWidget(button); self.menu_buttons[key] = button
        row.addStretch(1)
        self.continue_button = QPushButton('Continue to simulation setup')
        self.continue_button.clicked.connect(self._continue)
        row.addWidget(self.continue_button)
        self.actions.hide(); layout.addWidget(self.actions)
        self.optical_preview_note = QLabel('Layer and region preview colors show electrical materials. Optical assignments are shown in the inspector’s Optical tab.')
        self.optical_preview_note.setWordWrap(True)
        self.optical_preview_note.setAccessibleName('Device preview material context')
        self.optical_preview_note.hide(); layout.addWidget(self.optical_preview_note)
        self.compact_navigation = QWidget(self)
        panes = QHBoxLayout(self.compact_navigation); panes.setContentsMargins(0, 0, 0, 0)
        self.pane_tabs = QTabBar(); self.pane_tabs.setExpanding(False)
        for title in ('Objects', 'Geometry', 'Properties', 'Materials'):
            self.pane_tabs.addTab(title)
        self.pane_tabs.setCurrentIndex(1)
        self.pane_tabs.setAccessibleName('Full device editor pane')
        self.pane_tabs.currentChanged.connect(self._adapt_editor)
        panes.addWidget(self.pane_tabs, 1)
        self.canvas_choice = QComboBox()
        self.canvas_choice.addItems(['3D view', 'Draw in top view', 'Cross section'])
        self.canvas_choice.setAccessibleName('Full device editor geometry view')
        self.canvas_choice.currentIndexChanged.connect(self._adapt_editor)
        panes.addWidget(self.canvas_choice)
        self.compact_navigation.hide(); layout.addWidget(self.compact_navigation)
        self.open_button = QPushButton('Open full device editor')
        self.open_button.clicked.connect(lambda: self.open_editor())
        layout.addWidget(self.open_button)
        self.message = QLabel('')
        self.message.setWordWrap(True)
        self.message.setAccessibleName('Device editor status')
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.message.hide()
        layout.addWidget(self.message)
        self.store.changed.connect(self._context_changed)
        self.store.busy_changed.connect(self._context_changed)

    def _document_current(self):
        check = getattr(self.owner, '_is_active_document', None)
        return (not check or check()) and (not self.document_id or self.store.active_study == self.document_id)

    def _active(self):
        return self._document_current() and not self.store.busy

    def _context_changed(self, *_):
        self.setEnabled(self._active())
        self._update_optical_preview_note()

    def _update_optical_preview_note(self):
        finite = self.editor is not None and self.editor.tabs.currentIndex() == 0
        current = self._document_current()
        device = self.store.device if current else {}
        has_override = any(obj.get('optical_material_name') for kind in ('layers', 'shapes')
                           for obj in device.get(kind, []))
        self.optical_preview_note.setVisible(finite and current and has_override)

    def open_editor(self, identity=None, *, source=None):
        if not self._active():
            return False
        if source == 'original_tables' and not self.include_advanced:
            self._status('This solver uses the finite device editor. The periodic S4 editor belongs to a separate optical study.')
            return False
        if self.editor is None:
            from qt_custom_device import CustomDevicePage
            host = self

            class OwnedDevicePage(CustomDevicePage):
                def _apply_reference_style(self, *args):
                    super()._apply_reference_style(*args)
                    from qt_common import COLORS, theme_manager
                    if theme_manager().mode != 'light':
                        return
                    c = COLORS['light']
                    scope = 'QWidget[deviceBuilder="true"]'
                    self.setStyleSheet(self.styleSheet() + f'''
                        {scope} QTreeWidget::item:selected {{ background:{c['select']}; color:{c['text']}; }}
                        {scope} QTabBar::tab:selected {{ background:{c['select']}; color:{c['accent']}; }}
                        {scope} QToolButton#deviceToolCard:checked,
                        {scope} QToolButton#deviceMeshPreview:checked {{ background:{c['select']}; color:{c['accent']}; }}
                        {scope} QPushButton[primary="true"] {{ background:{c['accent']}; color:white; }}
                        {scope} QPushButton[primary="true"]:hover {{ background:{c['accent']}; color:white; }}
                        {scope} QFrame#deviceMaterialCard {{ background:{c['field']}; }}
                        {scope} QPushButton#materialCardEdit {{ color:{c['text']}; background:{c['panel']}; }}
                    ''')
                    from qt_custom_device import _device_icon
                    for name, button in self.tool_buttons.items():
                        button.setIcon(_device_icon(name, c['muted']))

                def refresh(self, *reason):
                    # The store selects a different study before emitting its
                    # change. Do not replace this document's pending inspector
                    # with that other study's geometry, or reload it on return.
                    if not host._document_current():
                        return
                    source = host._editor_source_snapshot()
                    if reason and reason[0] == 'study' and getattr(self, '_study_initialized', False):
                        if source == self._study_source:
                            return  # Returning to this unchanged document retains its draft.
                        # Explicit imports/transfers may keep object IDs but replace
                        # their values. Never allow stale inspector fields to undo them.
                        reason = ('project',)
                    super().refresh(*reason)
                    self._study_source = source
                    self._study_initialized = True

            self.editor = OwnedDevicePage(self.store, self, include_advanced=self.include_advanced)
            self.editor.continue_requested.connect(self._continue)
            self.editor.status_changed.connect(self._status)
            self.editor.setMinimumWidth(0)
            if self.editor._legacy is not None:
                self.store.changed.disconnect(self.editor._legacy.refresh)
                self.store.changed.connect(self._refresh_legacy)
                self._legacy_source = self._editor_source_snapshot()
            self._install_actions()
            for key in ('add_layer', 'add_shape', 'add_contact', 'add_doping', 'duplicate'):
                self.editor.action_buttons[key].clicked.connect(lambda: self.pane_tabs.setCurrentIndex(2))
            self.editor.object_tree.itemClicked.connect(lambda item, column: self.pane_tabs.setCurrentIndex(2) if item.data(0, Qt.ItemDataRole.UserRole) else None)
            for tool, button in self.editor.tool_buttons.items():
                button.clicked.connect(lambda checked=False, tool=tool: self._show_drawing_tool(tool))
            self._doping_button = next(button for button in self.editor.inspector_panel.findChildren(QPushButton) if button.text() == 'Edit doping regions…')
            self.editor.tabs.currentChanged.connect(self._editor_kind_changed)
            self.layout().addWidget(self.editor, 1)
            self.open_button.hide(); self.actions.show()
        if identity and self.editor.selected_id != identity:
            if not self.editor.open_diagnostic(dict(object_id=identity)):
                return False
        if source is not None:
            self.editor.tabs.setCurrentIndex(1 if source == 'original_tables' else 0)
        self._editor_kind_changed(self.editor.tabs.currentIndex())
        self._adapt_editor()
        return True

    def _install_actions(self):
        from qt_reference_style import reference_icon
        self.menu_buttons['objects'].setMenu(self.editor.tree_actions)
        first = self.editor.tree_actions.actions()[0]
        self.add_object_actions = {}
        for key, title in [('add_layer', 'Add layer'), ('add_shape', 'Add shape'), ('add_contact', 'Add contact')]:
            action = QAction(title, self.editor.tree_actions)
            action.triggered.connect(self.editor.action_buttons[key].click)
            self.editor.tree_actions.insertAction(first, action)
            self.add_object_actions[key] = action
        self.editor.tree_actions.addAction('Edit doping regions…', self.editor.edit_doping_regions)
        # Keep the authoritative Apply action next to navigation, rather than
        # below the full-height inspector in an outer scrolling study page.
        self.editor.inspector_panel.layout().removeWidget(self.editor.apply_button)
        self.actions.layout().insertWidget(self.actions.layout().indexOf(self.continue_button), self.editor.apply_button)
        self.editor.undo_shortcut.setParent(self)
        self.editor.apply_button.setAccessibleName('Apply selected object')
        self.editor.apply_button.setToolTip('Apply the current selected object properties to this study.')
        self.menu_buttons['drawing'].setMenu(self.editor.toolbar_menu)
        materials = QMenu(self.menu_buttons['materials'])
        self.electrical_material_actions = [
            materials.addAction('Edit selected device material…', self.editor.library_edit_button.click),
            materials.addAction('Import device material data…', self.editor.library_import_button.click)]
        if self.optical_materials:
            materials.addSeparator()
            self.optical_material_action = materials.addAction('Optical materials / n,k data…', self._open_optical_materials)
        self.menu_buttons['materials'].setMenu(materials)
        self.menu_buttons['export'].setMenu(self.editor.export_menu)
        from qt_common import COLORS, theme_manager
        accent = COLORS[theme_manager().mode]['accent']
        for key, icon in [('objects', 'layers'), ('drawing', 'structure'), ('materials', 'materials'), ('export', 'export')]:
            self.menu_buttons[key].setIcon(reference_icon(icon, accent))
        self.back_button.setIcon(reference_icon('back', accent))
        self.continue_button.setIcon(reference_icon('next', accent))
        for button in self.menu_buttons.values():
            button.setMinimumWidth(button.sizeHint().width() + 8)

    def _editor_kind_changed(self, index):
        periodic = index > 0
        self.editor.apply_button.setVisible(not periodic)
        for key in ('objects', 'drawing'):
            self.menu_buttons[key].setVisible(not periodic)
        self.menu_buttons['materials'].setVisible(not periodic or self.optical_materials)
        for action in self.electrical_material_actions:
            action.setVisible(not periodic)
        if periodic:
            self.menu_buttons['export'].setMenu(self.editor._legacy.export_button.menu())
            self.note.setText('Full periodic optical editor · Original layer stack, regions, repeats, lattice, material assignments, CAD/COMSOL export and undo controls.')
        else:
            self.menu_buttons['export'].setMenu(self.editor.export_menu)
            self.note.setText('Full device editor · Layers, shapes, arrays, contacts, doping, materials and mesh. Apply commits the selected object; navigation preserves its draft.')
        self._update_optical_preview_note()
        self._adapt_editor()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._adapt_editor()

    def _adapt_editor(self, *_):
        if self.editor is None:
            return
        compact = self.width() < 1100 and self.editor.tabs.currentIndex() == 0
        if compact and not self._compact_editor and self._layout_initialized:
            self._desktop_sizes = self.editor.builder_splitter.sizes()
        self.note.setVisible(self.width() >= 1100)
        self.back_button.setText('Back to setup' if self.width() < 1100 else self._back_label)
        self.editor.apply_button.setText('Apply' if self.width() < 1100 else 'Apply selected object')
        self.continue_button.setText('Next setup' if self.width() < 1100 else 'Continue to simulation setup')
        self.compact_navigation.setVisible(compact)
        pane = self.pane_tabs.currentIndex()
        self.canvas_choice.setVisible(compact and pane == 1)
        e = self.editor
        e.tree_panel.setVisible(not compact or pane == 0)
        e.canvas_panel.setVisible(not compact or pane in (1, 3))
        e.inspector_panel.setVisible(not compact or pane == 2)
        e.material_properties_group.setVisible(not compact)
        self._doping_button.setVisible(not compact)
        e.toolbar_panel.setVisible(not compact or pane == 1)
        e.views.setVisible(not compact or pane == 1)
        e.library_panel.setVisible(not compact or pane == 3)
        e.library_panel.setMinimumHeight(0 if compact else 193)
        e.library_panel.setMaximumHeight(16777215 if compact else 193)
        e.library_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding if compact else QSizePolicy.Policy.Fixed)
        view = self.canvas_choice.currentIndex()
        e.upper_views.setVisible(not compact or view != 0)
        e.upper_views.widget(0).setVisible(not compact or view == 1)
        e.upper_views.widget(1).setVisible(not compact or view == 2)
        e.views.widget(1).setVisible(not compact or view == 0)
        if self._compact_editor and not compact:
            e.builder_splitter.setSizes(self._desktop_sizes)
        self._compact_editor = compact
        self._layout_initialized = True

    def _show_drawing_tool(self, tool):
        if self._compact_editor:
            self.pane_tabs.setCurrentIndex(1)
            if tool in ('move', 'rectangle', 'circle', 'ellipse', 'polygon', 'square_ring'):
                self.canvas_choice.setCurrentIndex(1)

    def _open_optical_materials(self):
        if not self._active():
            return
        if hasattr(self.owner, 'routeRequested'):
            self.owner.routeRequested.emit('materials.optical')
        elif hasattr(self.owner.window(), '_route_setup_action'):
            self.owner.window()._route_setup_action('materials.optical')

    def _editor_source_snapshot(self):
        snapshot = {}
        for key in ('device', 'electrical_materials', 'materials', 'layers', 'patterns', 'settings'):
            value = getattr(self.store, key, None)
            snapshot[key] = value.to_dict('records') if hasattr(value, 'to_dict') else deepcopy(value)
        return snapshot

    def _refresh_legacy(self, reason='structure'):
        if not self._document_current():
            return
        source = self._editor_source_snapshot()
        if reason == 'study' and source == getattr(self, '_legacy_source', None):
            return
        self.editor._legacy.refresh('project' if reason == 'study' else reason)
        self._legacy_source = source

    def _continue(self):
        if self._active():
            self.continue_requested.emit()

    def _status(self, text):
        self.message.setText(str(text)); self.message.setVisible(bool(text))
        if self._active():
            setter = getattr(self.owner, 'set_status', None)
            if setter:
                setter(str(text))
            elif hasattr(self.owner, 'status'):
                self.owner.status.setText(str(text))
