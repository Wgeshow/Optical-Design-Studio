"""Presentation-only three-column flow for the canonical simulation editors.

The existing setup state, field objects and section identities remain the source
of truth. Moving a panel never commits a draft or substitutes a device.
"""
from PyQt6.QtCore import Qt, QSignalBlocker, QSize
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QComboBox,
    QTreeWidget, QTreeWidgetItem, QHBoxLayout, QVBoxLayout, QStackedWidget, QScrollArea,
    QSizePolicy)
from qt_common import COLORS, theme_manager
from qt_reference_style import reference_icon


STAGES = {
    'optical': [('Device', ['overview', 'domain']),
                ('Light & materials', ['incident', 'sweep', 'materials']),
                ('Calculate', ['accuracy', 'outputs'])],
    'electrical': [('Device', ['overview', 'contacts', 'materials']),
                   ('Bias & physics', ['study', 'temperature']),
                   ('Calculate', ['mesh', 'outputs'])],
    'coupled': [('Device', ['overview']),
                ('Link physics', ['electrical-setup', 'optical-setup', 'transfer']),
                ('Calculate', ['response', 'outputs'])],
}


class SimulationSetupFlow:
    def __init__(self, workspace):
        self.page = w = workspace
        self.compact = None
        self.compact_view = 'settings'
        self._object_signature = None
        self._device_snapshot = None
        self._syncing = False
        w.setProperty('simulationFlowOwned', True)
        self.header = QWidget(w)
        header = QVBoxLayout(self.header); header.setContentsMargins(4, 2, 4, 0); header.setSpacing(6)
        w.center.layout().removeWidget(w.title)
        header.addWidget(w.title)
        steps = QHBoxLayout(); steps.setSpacing(6)
        self.step_buttons = []
        for i in range(3):
            button = QPushButton(); button.setObjectName('setupStep'); button.setCheckable(True)
            button.setMinimumHeight(34)
            button.clicked.connect(lambda checked=False, index=i: self.show_stage(index))
            steps.addWidget(button, 1); self.step_buttons.append(button)
        header.addLayout(steps)
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
        self.object_tree.setAccessibleName('Shared device objects')
        self.object_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.object_tree.currentItemChanged.connect(self._object_selected)
        nav.insertWidget(3, self.object_tree, 1)
        self.edit_object = QPushButton('Edit selected object'); self.edit_object.setProperty('flowIcon', 'cube')
        self.edit_object.clicked.connect(self.edit_selected)
        nav.insertWidget(4, self.edit_object)
        self.edit_structure = QPushButton('Open Structure editor'); self.edit_structure.setProperty('flowIcon', 'structure')
        self.edit_structure.clicked.connect(lambda: w.routeRequested.emit('global.structure'))
        nav.insertWidget(5, self.edit_structure)

        self.scene = QFrame(); self.scene.setObjectName('setupScene')
        scene = QVBoxLayout(self.scene); scene.setContentsMargins(12, 10, 12, 10); scene.setSpacing(8)
        tools = QHBoxLayout()
        caption = QLabel('Shared device'); caption.setObjectName('setupCardTitle'); tools.addWidget(caption, 1)
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
        self.apply_style()
        self.sync_section()
        self.adapt_layout()

    def _pick_section(self, index):
        if not self._syncing and index >= 0:
            self.page.select_section(self.section_picker.itemData(index))
            self.show_compact('settings')

    def show_stage(self, index):
        mode = self.page.current_mode
        suffix = STAGES[mode][index][1][0]
        self.page.select_section(mode + '.' + suffix)
        self.show_compact('settings')

    def sync_section(self):
        w = self.page
        mode = w.current_mode
        section = getattr(w, 'current_section', mode + '.overview')
        stage = next((i for i, (_, sections) in enumerate(STAGES[mode]) if section.split('.')[-1] in sections), 1)
        self._syncing = True
        try:
            for i, (label, sections) in enumerate(STAGES[mode]):
                self.step_buttons[i].setText(f'{i+1}   {label}'.replace('&', '&&'))
                self.step_buttons[i].setChecked(i == stage)
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

    def refresh(self):
        w = self.page; device = w.store.device or {}
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

    def _object_selected(self, current, previous):
        if current and current.data(0, Qt.ItemDataRole.UserRole):
            self.page.select_object(current.data(0, Qt.ItemDataRole.UserRole))

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
        if ident:
            self.page.diagnosticRequested.emit(dict(workspace='structure', section='structure', object_id=ident,
                field='', message='Edit the selected shared device object.'))
        else:
            self.page.routeRequested.emit('global.structure')

    def show_compact(self, view):
        self.compact_view = view
        if self.compact:
            self.page.nav_panel.setVisible(view == 'objects')
            self.scene.setVisible(view == 'device')
            self.page.center.setVisible(view == 'settings')
        for key, button in self.compact_buttons.items(): button.setChecked(key == view)

    def adapt_layout(self):
        w = self.page; compact = w.width() < 1120
        if compact != self.compact:
            self.compact = compact
            while w.body.count(): w.body.takeAt(0)
            if compact:
                for panel in (w.nav_panel, self.scene, w.center):
                    panel.setMinimumWidth(0); panel.setMaximumWidth(16777215)
                    w.body.addWidget(panel, 1)
            else:
                w.nav_panel.setMinimumWidth(175); w.nav_panel.setMaximumWidth(215)
                self.scene.setMinimumWidth(280); self.scene.setMaximumWidth(16777215)
                w.center.setMinimumWidth(330); w.center.setMaximumWidth(440)
                w.body.addWidget(w.nav_panel, 0); w.body.addWidget(self.scene, 1); w.body.addWidget(w.center, 0)
                for panel in (w.nav_panel, self.scene, w.center): panel.show()
        self.compact_bar.setVisible(compact)
        note = w.findChild(QLabel, 'setupModeNote')
        if note is not None: note.setVisible(not compact)
        if compact: self.show_compact(self.compact_view)
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
