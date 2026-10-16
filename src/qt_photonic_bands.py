"""Independent editable periodic-domain workspace for MPB and Legume bands."""
from __future__ import annotations

from copy import deepcopy
import json
import sys
import uuid
from html import escape
from itertools import product

import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Circle, Polygon
from PyQt6.QtCore import Qt, QSignalBlocker, QTimer, QSize, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog,
    QFormLayout, QHBoxLayout, QHeaderView, QPlainTextEdit, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QLineEdit, QListWidget, QListWidgetItem,
    QSplitter, QGroupBox, QTextBrowser, QSizePolicy, QStyledItemDelegate, QStackedWidget,
    QPushButton, QMenu, QScrollArea, QBoxLayout)

from qt_common import PlotWidget, preferences, COLORS, theme_manager
from qt_input_diagnostics import reveal_and_focus
from qt_research_common import ResearchWorkspaceBase, FieldError, button, label, number, vector
from qt_photonic_band_results import PhotonicBandResultsPanel
from qt_photonic_crystal_3d import PhotonicCrystal3D


def _table(headers, accessible):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setAccessibleName(accessible)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setMinimumHeight(160)
    return table


def _fill(table, rows):
    blocker = QSignalBlocker(table)
    table.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            table.setItem(i, j, QTableWidgetItem(str(value)))
    del blocker


def _rows(table):
    return [[table.item(i, j).text() if table.item(i, j) else '' for j in range(table.columnCount())]
            for i in range(table.rowCount())]


class _ShapeCaptionDelegate(QStyledItemDelegate):
    def displayText(self, value, locale):
        return str(value).capitalize()


class _CartesianInput(QWidget):
    """Separate Cartesian components while retaining malformed legacy/raw vectors."""
    textChanged = pyqtSignal(str)

    def __init__(self, dimension=3, parent=None):
        super().__init__(parent)
        self._text, self._updating, self.dimension = '', False, dimension
        layout = QHBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        self.components = []
        self.component_labels = []
        for axis in ('X', 'Y', 'Z'):
            column = QWidget(); rows = QVBoxLayout(column); rows.setContentsMargins(0, 0, 0, 0); rows.setSpacing(2)
            rows.addWidget(label(axis))
            edit = QLineEdit(); edit.setMinimumWidth(34); edit.setAccessibleName(axis+' component in units of a')
            rows.addWidget(edit); layout.addWidget(column)
            edit.textChanged.connect(self._component_edited)
            self.components.append(edit); self.component_labels.append(column)
        self.raw = QLineEdit(); self.raw.setAccessibleName('Unfinished Cartesian vector')
        self.raw.setPlaceholderText('Enter comma-separated X, Y, Z values')
        layout.addWidget(self.raw); self.raw.textChanged.connect(self._raw_edited)
        self.set_dimension(dimension)

    def text(self):
        return self._text

    def setText(self, value):
        value = str(value)
        changed = value != self._text
        self._text = value
        self._updating = True
        parts = value.replace(',', ' ').split()
        valid_count = len(parts) == self.dimension
        for i, (edit, column) in enumerate(zip(self.components, self.component_labels)):
            column.setVisible(valid_count and i < self.dimension)
            edit.setText(parts[i] if valid_count and i < self.dimension else '')
            edit.setCursorPosition(0)
        self.raw.setVisible(not valid_count); self.raw.setText(value)
        self.raw.setCursorPosition(0)
        self.setFocusProxy(self.components[0] if valid_count else self.raw)
        self._updating = False
        if changed: self.textChanged.emit(value)

    def set_dimension(self, dimension):
        self.dimension = dimension
        self.setText(self._text)

    def _component_edited(self):
        if not self._updating:
            self._text = ', '.join(edit.text() for edit in self.components[:self.dimension])
            self.textChanged.emit(self._text)

    def _raw_edited(self, value):
        if not self._updating:
            self._text = value
            self.textChanged.emit(value)

    def focus_component(self, index=0):
        return self.raw if not self.raw.isHidden() else self.components[min(index, self.dimension-1)]


def _xy_hull(vertices):
    points = sorted(set(tuple(float(v) for v in point[:2]) for point in vertices))
    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    lower, upper = [], []
    for p in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0: lower.pop()
        lower.append(p)
    for p in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0: upper.pop()
        upper.append(p)
    return np.asarray(lower[:-1]+upper[:-1])


class PhotonicBandsWorkspace(ResearchWorkspaceBase):
    workspace_id = 'photonic_bands'
    state_key = 'bands'
    geometry_columns = ('name', 'shape', 'center', 'radius', 'size', 'height', 'axis', 'axes')

    def __init__(self, store, parent=None):
        super().__init__(store, parent)
        self._object_ids = []
        self._epsilons = {}
        self._sweep_targets = []
        self.heading.setText('Photonic Bands')
        self.heading.setObjectName('bandsTitle')
        self.description.setText('Define an independent periodic crystal and solve its optical modes. '
            'Dimensions are Cartesian multiples of a; k coordinates are fractional reciprocal-lattice coordinates.')
        _, overview = self.add_section('Overview')
        overview.addWidget(label('A periodic crystal, independent of the finite optical device', 'setupHeading'))
        overview.addWidget(label('1. Define the lattice and dielectric primitives.  2. Choose the reciprocal-space samples. '
            '3. Select an available solver and accuracy.  4. Review, run and inspect the saved bands. '
            'Changing this crystal does not change the existing optical or electrical device.'))
        overview.addWidget(label('MPB: 2D TE/TM and full-vector 3D. Legume: 2D plane-wave expansion. '
            'Both require an explicitly configured optional runtime. Positive real scalar dielectric constants only; '
            'loss, gain, dispersion and finite-device boundaries are outside these models.'))
        overview.addWidget(label('The initial crystal is an illustrative 3D simple-cubic sphere in air: radius 0.25a and εr = 12 (n ≈ 3.464). '
            'Every value is editable. For a finite-thickness slab, use the slab GME study under More studies.'))
        overview.addWidget(button('Edit crystal structure', lambda: self.select_section('Crystal structure')))
        overview.addStretch()
        _, crystal = self.add_section('Crystal structure')
        form = QFormLayout()
        self.dimension = self.choice(form, 'Periodic dimensions', 'dimension', [('2D · invariant along z', 2), ('3D · full vector', 3)], 2)
        self.reference_length = self.line(form, 'Reference length a (optional)', 'reference_length_um', '', 'µm', 'Leave blank for normalized units')
        crystal.addLayout(form)
        crystal.addWidget(label('Real-space lattice vectors (Cartesian / a). Edit all components; vectors must be independent.'))
        self.lattice = _table(['x / a', 'y / a', 'z / a'], 'Real-space lattice vectors')
        _fill(self.lattice, [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        self.fields['lattice_vectors'] = self.lattice
        crystal.addWidget(self.lattice)
        crystal.addWidget(label('Primitives use Cartesian coordinates / a. Radius is explicitly a radius. '
            'Later primitives override earlier overlapping objects. Block axes are semicolon-separated vectors.'))
        self.geometry = _table(['Name', 'Shape', 'Center / a', 'Radius / a', 'Size / a', 'Height / a', 'Axis', 'Block axes'], 'Editable dielectric primitives')
        self.fields['geometry'] = self.geometry
        crystal.addWidget(self.geometry)
        controls = QHBoxLayout()
        self.new_shape = QComboBox()
        self.new_shape.addItems(['circle', 'block', 'sphere', 'cylinder'])
        self.new_shape.setAccessibleName('New primitive shape')
        controls.addWidget(self.new_shape)
        controls.addWidget(button('Add primitive', self.add_primitive))
        controls.addWidget(button('Remove selected primitive', self.remove_primitive))
        controls.addWidget(button('Preview geometry', self.preview_geometry))
        controls.addStretch()
        crystal.addLayout(controls)
        self.preview = PlotWidget()
        self.preview.setMinimumHeight(330)
        self.preview.setMinimumWidth(450)
        self.preview.setMaximumWidth(740)
        crystal.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)
        self.preview_note = label('Preview is a geometry sketch, not a field solution.')
        crystal.addWidget(self.preview_note)
        _, materials = self.add_section('Materials')
        material_form = QFormLayout()
        self.background = self.line(material_form, 'Background relative permittivity', 'background_epsilon', '1', 'dimensionless')
        materials.addLayout(material_form)
        materials.addWidget(label('Each primitive has an editable positive, real, nondispersive relative permittivity. '
            'These values belong to this periodic crystal; optical-stack material tables are not inferred.'))
        self.materials = _table(['Primitive', 'Relative permittivity εr'], 'Primitive dielectric constants')
        materials.addWidget(self.materials)
        materials.addStretch()
        _, kspace = self.add_section('k-space path')
        kform = QFormLayout()
        self.sampling = self.choice(kform, 'Sampling', 'sampling', [('Path between vertices', 'path'), ('Explicit points', 'points'), ('Interior reciprocal grid', 'grid')])
        self.points_per_segment = self.line(kform, 'Intervals per path segment', 'points_per_segment', '10')
        self.grid_counts = self.line(kform, 'Grid counts', 'k_grid.counts', '8, 8')
        self.grid_offset = self.line(kform, 'Grid offset', 'k_grid.offset', '0, 0', 'fractional reciprocal')
        kspace.addLayout(kform)
        kspace.addWidget(label('Coordinates are fractions of reciprocal lattice vectors. The first row is not silently moved to Γ. '
            'Grid offsets and counts are explicit; no hidden symmetry reduction is applied.'))
        self.kpoints = _table(['k1', 'k2', 'k3'], 'Reciprocal-space vertices or points')
        _fill(self.kpoints, [[0, 0, 0], [.5, 0, 0], [.5, .5, 0], [0, 0, 0]])
        self.fields['k_vertices'] = self.fields['k_points'] = self.kpoints
        kspace.addWidget(self.kpoints)
        row = QHBoxLayout()
        row.addWidget(button('Add k point', self.add_kpoint))
        row.addWidget(button('Remove selected k point', self.remove_kpoint))
        row.addStretch()
        kspace.addLayout(row)
        _, solver = self.add_section('Solver & accuracy')
        solver_form = QFormLayout()
        self.solver = self.choice(solver_form, 'Solver', 'solver', [('MPB', 'mpb'), ('Legume · 2D PWE', 'legume')])
        self.num_bands = self.line(solver_form, 'Number of bands', 'num_bands', '8')
        self.resolution = self.line(solver_form, 'MPB resolution', 'resolution', '32', 'pixels / a')
        self.gmax = self.line(solver_form, 'Legume reciprocal cutoff', 'gmax', '5', '2π / a')
        self.tolerance = self.line(solver_form, 'MPB eigenproblem tolerance', 'tolerance', '1e-8')
        self.mesh_size = self.line(solver_form, 'MPB material averaging mesh', 'mesh_size', '5')
        self.runtime_mode = self.choice(solver_form, 'Runtime location', 'runtime.mode', [('WSL', 'wsl'), ('Local', 'local')], 'wsl' if sys.platform == 'win32' else 'local')
        self.distro = self.line(solver_form, 'WSL distribution', 'runtime.distro', 'Ubuntu')
        self.executable = self.line(solver_form, 'Executable (MPB or Python)', 'runtime.executable', 'mpb')
        self.module_paths = self.line(solver_form, 'Python package folders (Legume)', 'runtime.module_paths', '', '', 'Separate explicit paths with semicolons')
        self.library_paths = self.line(solver_form, 'Native library folders (Legume)', 'runtime.library_paths', '', '', 'Separate explicit paths with semicolons')
        self.timeout = self.line(solver_form, 'Runtime limit', 'runtime.timeout_s', '86400', 's')
        solver.addLayout(solver_form)
        solver.addWidget(label('MPB on Windows runs through WSL. For Legume select the Python executable containing its installation '
            '(an absolute Linux path for WSL). Changing solver never silently rewrites the runtime or device.'))
        solver.addStretch()
        _, outputs = self.add_section('Outputs')
        outputs.addWidget(label('Polarizations'))
        self.te = QCheckBox('TE · 2D')
        self.tm = QCheckBox('TM · 2D')
        self.te.setChecked(True)
        self.tm.setChecked(True)
        outputs.addWidget(self.te)
        outputs.addWidget(self.tm)
        self.fields['polarizations'] = self.te
        outputs.addWidget(label('3D uses full-vector modes. Every run saves the exact inputs, engine log, frequencies as CSV/NPZ '
            'and a status manifest. Frequency is a/λ = ωa/(2πc). Gaps reported from a path or a finite grid are sampled gaps, '
            'not proof of a complete Brillouin-zone gap.'))
        outputs.addStretch()
        _, review = self.add_section('Review & Run')
        review.addWidget(label('Review the exact solver request. Geometry and material values remain editable in the preceding sections.'))
        row = QHBoxLayout()
        row.addWidget(button('Refresh review', self.review_inputs))
        row.addWidget(button('Import editable settings…', self.import_settings))
        row.addWidget(button('Export settings…', self.export_settings))
        review.addLayout(row)
        self.review = QPlainTextEdit()
        self.review.setReadOnly(True)
        self.review.setAccessibleName('Exact periodic-domain solver request')
        review.addWidget(self.review, 1)
        self.results = PhotonicBandResultsPanel(store, 'photonic_bands', self)
        self.results.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.tabs.addTab(self.results, 'Results')
        _, sweep = self.add_section('Parameter sweep')
        sweep.addWidget(label('Optional editable geometry/material atlas. Each parameter lists explicit values; multiple parameters '
            'form a Cartesian product. Repeat a parameter ID with the same values to link more than one primitive. '
            'Every variant is validated before execution, with at most 1,000 combinations.'))
        sweep.addWidget(label('Primitive fields: radius, height, epsilon, center.0, size.0, axis.0, axes.0.0. '
            'Global fields: background_epsilon or lattice_vectors.0.0. Only existing fields may be varied.'))
        self.sweeps = _table(['Parameter ID', 'Target', 'Field', 'Explicit values'], 'Geometry and material parameter sweep')
        self.fields['parameter_sweep'] = self.sweeps
        sweep.addWidget(self.sweeps)
        sweep_controls = QHBoxLayout()
        self.sweep_target = QComboBox()
        self.sweep_target.setAccessibleName('New sweep target')
        sweep_controls.addWidget(self.sweep_target, 1)
        sweep_controls.addWidget(button('Add parameter target', self.add_sweep))
        sweep_controls.addWidget(button('Remove selected target', self.remove_sweep))
        sweep.addLayout(sweep_controls)
        sweep.addWidget(label('Variants retain their exact values, folders and statuses. Parameter sweeps can include the accuracy '
            'levels on the Convergence page. A sampled gap is never promoted to a complete-gap claim.'))
        sweep.addStretch()
        _, convergence = self.add_section('Convergence')
        convergence.addWidget(label('An optional accuracy sweep runs the same editable crystal at each supplied level. '
            'A successful last-pair comparison is evidence for that sweep only; k sampling must also be checked.'))
        cform = QFormLayout()
        self.levels = self.line(cform, 'Accuracy levels (optional)', 'convergence.levels', '', '', 'MPB resolutions or Legume gmax, comma separated')
        self.frequency_tolerance = self.line(cform, 'Last-pair frequency tolerance (optional)', 'frequency_tolerance', '', 'a / λ')
        convergence.addLayout(cform)
        convergence.addWidget(label('Leave levels empty for a single run. Convergence CSV/JSON and the individual run folders '
            'are retained under the result directory. Open those files on the Results page.'))
        convergence.addStretch()
        _, benchmarks = self.add_section('Paper benchmarks')
        benchmarks.addWidget(label('Paper benchmarks preserve their reference inputs and provenance. Duplicate a reference into '
            'the editable crystal to explore another geometry; modified devices are not represented as the original reproduction.'))
        self.benchmark_picker = QComboBox()
        self.benchmark_picker.setAccessibleName('Photonic band paper benchmark')
        benchmarks.addWidget(self.benchmark_picker)
        buttons = QHBoxLayout()
        buttons.addWidget(button('Refresh benchmark list', self.refresh_benchmarks))
        buttons.addWidget(button('Duplicate into editor', self.duplicate_benchmark))
        buttons.addWidget(button('Run immutable reference', self.run_benchmark))
        benchmarks.addLayout(buttons)
        self.benchmark_note = label('')
        benchmarks.addWidget(self.benchmark_note)
        benchmarks.addWidget(label('To compare an existing run against a compatible reference curve, use Results → Reference comparison. '
            'Partial results and disagreements remain visible in the saved manifest.'))
        benchmarks.addStretch()
        self.geometry.cellChanged.connect(self._geometry_changed)
        self.materials.cellChanged.connect(self._material_changed)
        self.lattice.cellChanged.connect(self._edited)
        self.kpoints.cellChanged.connect(self._edited)
        self.sweeps.cellChanged.connect(self._edited)
        self.dimension.currentIndexChanged.connect(self._dimension_changed)
        self.solver.currentIndexChanged.connect(self._solver_changed)
        self.sampling.currentIndexChanged.connect(self._sampling_changed)
        self.te.toggled.connect(self._edited)
        self.tm.toggled.connect(self._edited)
        self.tabs.currentChanged.connect(self._section_changed)
        self.add_primitive()
        self._dimension_changed()
        self._solver_changed()
        self._sampling_changed()
        self._build_guided_editor()
        self._build_crystal_workflow()
        self.finish_build()
        self.refresh_benchmarks()
        self._refresh_inspector()
        self._queue_preview()

    def _replace_section_body(self, index, body):
        scroll = self.tabs.widget(index)
        previous = scroll.takeWidget()
        scroll.setWidget(body)
        previous.deleteLater()

    @staticmethod
    def _form_row_visible(form, widget, visible):
        widget.setVisible(visible)
        caption = form.labelForField(widget)
        if caption is not None:
            caption.setVisible(visible)

    def _build_guided_editor(self):
        """Rearrange band controls without changing their saved fields or page indices."""
        self.tabs.tabBar().hide()
        self.section_nav = QListWidget()
        self.section_nav.setObjectName('navigation')
        self.section_nav.setAccessibleName('Photonic Bands setup steps')
        self.section_nav.setFixedWidth(185)
        self.section_picker = QComboBox()
        self.section_picker.setAccessibleName('Photonic Bands section')
        self.section_picker.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.section_picker.setMinimumContentsLength(12)
        groups = [('START', [(0, 'Overview')]), ('SETUP', [(1, '1  Crystal'), (2, '2  Materials'),
            (3, '3  Wavevectors'), (4, '4  Solver'), (5, '5  Outputs'), (6, '6  Review & run')]),
            ('EXPLORE', [(7, 'Results'), (8, 'Parameter sweep'), (9, 'Convergence'), (10, 'Paper benchmarks')])]
        self._navigation_rows = {}
        for group, entries in groups:
            heading = QListWidgetItem(group)
            heading.setFlags(Qt.ItemFlag.NoItemFlags)
            self.section_nav.addItem(heading)
            for index, caption in entries:
                item = QListWidgetItem(caption)
                item.setData(Qt.ItemDataRole.UserRole, index)
                item.setSizeHint(QSize(170, 34))
                self._navigation_rows[index] = self.section_nav.count()
                self.section_nav.addItem(item)
                self.section_picker.addItem(caption, index)
        self.section_nav.currentItemChanged.connect(lambda current, old:
            self.tabs.setCurrentIndex(current.data(Qt.ItemDataRole.UserRole)) if current and current.data(Qt.ItemDataRole.UserRole) is not None else None)
        self.section_picker.currentIndexChanged.connect(lambda i: self.tabs.setCurrentIndex(self.section_picker.itemData(i)))
        self.body_layout.removeWidget(self.tabs)
        self.navigation_body = QWidget()
        nav_layout = QHBoxLayout(self.navigation_body)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.addWidget(self.section_nav)
        nav_layout.addWidget(self.tabs, 1)
        self.flow_bar = QWidget()
        flow = QHBoxLayout(self.flow_bar)
        flow.setContentsMargins(0, 0, 0, 0)
        self.step_label = label('1 · Crystal', 'setupHeading')
        self.back_step = button('Back', lambda: self._step(-1))
        self.next_step = button('Next: Materials', lambda: self._step(1))
        flow.addWidget(self.step_label, 1)
        flow.addWidget(self.section_picker, 1)
        flow.addWidget(self.back_step)
        flow.addWidget(self.next_step)
        self.body_layout.insertWidget(2, self.flow_bar)
        self.body_layout.insertWidget(3, self.navigation_body, 1)
        self.description.setText('Build a periodic crystal, choose wavevectors, then calculate its optical bands.')
        self._inspector_updating = False
        self._preset_signature = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(180)
        self._preview_timer.timeout.connect(self.preview_geometry)

        body = QWidget()
        crystal = QVBoxLayout(body)
        crystal.setContentsMargins(12, 8, 12, 12)
        self.geometry_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.geometry_splitter.setChildrenCollapsible(False)
        editor = QWidget()
        self.crystal_editor = editor
        edit_layout = QVBoxLayout(editor)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        self.lattice_summary = label('')
        edit_layout.addWidget(self.lattice_summary)
        self.lattice_details_toggle = QCheckBox('Edit lattice and dimensions')
        self.lattice_details_toggle.setChecked(True)
        edit_layout.addWidget(self.lattice_details_toggle)
        self.lattice_settings = QWidget()
        lattice_layout = QVBoxLayout(self.lattice_settings)
        lattice_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.addWidget(self.lattice_settings)
        self.lattice_details_toggle.toggled.connect(self.lattice_settings.setVisible)
        form = QFormLayout()
        form.addRow('Crystal dimensions', self.dimension)
        form.addRow('Physical scale a (µm, optional)', self.reference_length)
        self.reference_length.setPlaceholderText('Blank = normalized units')
        lattice_layout.addLayout(form)
        self.dimension_note = label('2D is an infinite cross-section along z, not a finite-thickness slab.')
        lattice_layout.addWidget(self.dimension_note)
        presets = QHBoxLayout()
        self.lattice_preset = QComboBox()
        self.lattice_preset.setAccessibleName('Lattice preset')
        for caption, key in [('Custom / keep current', 'custom'), ('Square · 2D', 'square'),
                             ('Triangular · 2D', 'triangular'), ('Cubic · 3D', 'cubic')]:
            self.lattice_preset.addItem(caption, key)
        presets.addWidget(self.lattice_preset, 1)
        self.apply_preset_button = button('Apply lattice + path', self.apply_lattice_preset)
        presets.addWidget(self.apply_preset_button)
        lattice_layout.addLayout(presets)
        self.custom_vectors_toggle = QCheckBox('Edit lattice vectors')
        lattice_layout.addWidget(self.custom_vectors_toggle)
        self.lattice.setMinimumHeight(0)
        self.lattice.setMaximumHeight(125)
        self.lattice.verticalHeader().setDefaultSectionSize(28)
        self.lattice.setVerticalHeaderLabels(['a₁', 'a₂', 'a₃'])
        lattice_layout.addWidget(self.lattice)
        self.custom_vectors_toggle.toggled.connect(self.lattice.setVisible)
        self.lattice.hide()
        edit_layout.addWidget(label('Objects', 'setupHeading'))
        self.geometry.setAccessibleName('Crystal objects')
        self.geometry.setMinimumHeight(0)
        self.geometry.setMaximumHeight(78)
        self.geometry.verticalHeader().hide()
        self.geometry.setItemDelegateForColumn(1, _ShapeCaptionDelegate(self.geometry))
        for col in range(2, self.geometry.columnCount()):
            self.geometry.setColumnHidden(col, True)
        edit_layout.addWidget(self.geometry)
        actions = QHBoxLayout()
        self.new_shape.clear()
        for shape in ('circle', 'block', 'sphere', 'cylinder'):
            self.new_shape.addItem(shape.title(), shape)
        actions.addWidget(self.new_shape)
        actions.addWidget(button('Add object', self.add_primitive))
        actions.addWidget(button('Remove', self.remove_primitive))
        actions.addStretch()
        edit_layout.addLayout(actions)
        self.inspector_group = QGroupBox('Selected object')
        self.primitive_form = QFormLayout(self.inspector_group)
        self.primitive_fields = {}
        self.primitive_shape = QComboBox()
        for shape in ('circle', 'block', 'sphere', 'cylinder'):
            self.primitive_shape.addItem(shape.title(), shape)
        captions = [('name', 'Name'), ('center', 'Center (x, y) / a'), ('radius', 'Radius / a'),
                    ('size', 'Size along each axis / a'), ('height', 'Height / a'), ('axis', 'Cylinder axis (x, y, z)'),
                    ('axes', 'Block directions'), ('epsilon', 'Relative permittivity εr')]
        for key, caption in captions:
            widget = QLineEdit()
            widget.setAccessibleName('Selected object '+caption)
            widget.setObjectName('band_object_'+key)
            self.primitive_fields[key] = widget
            self.primitive_form.addRow(caption, widget)
            widget.textChanged.connect(lambda text, field=key: self._inspector_edited(field, text))
        self.primitive_form.insertRow(1, 'Shape', self.primitive_shape)
        self.primitive_shape.setAccessibleName('Selected object shape')
        self.primitive_shape.currentIndexChanged.connect(lambda _: self._inspector_edited('shape', self.primitive_shape.currentData()))
        self.index_hint = label('For lossless, nonmagnetic materials: εr = n².')
        self.primitive_form.addRow(self.index_hint)
        edit_layout.addWidget(self.inspector_group)
        self.compact_preview_toggle = QCheckBox('Show crystal preview')
        actions.addWidget(self.compact_preview_toggle)
        edit_layout.addStretch()
        preview_body = QWidget()
        self.preview_body = preview_body
        preview_layout = QVBoxLayout(preview_body)
        preview_layout.setContentsMargins(6, 0, 0, 0)
        preview_layout.addWidget(label('Crystal preview', 'setupHeading'))
        self.preview.setMinimumWidth(0)
        self.preview.setMaximumWidth(16777215)
        self.preview.setMinimumHeight(260)
        self.preview.setMaximumHeight(470)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        preview_layout.addWidget(self.preview, 1)
        preview_layout.addWidget(self.preview_note)
        preview_layout.addStretch()
        self.compact_preview_toggle.toggled.connect(self._compact_preview_changed)
        self.geometry_splitter.addWidget(editor)
        self.geometry_splitter.addWidget(preview_body)
        self.geometry_splitter.setStretchFactor(0, 5)
        self.geometry_splitter.setStretchFactor(1, 6)
        crystal.addWidget(self.geometry_splitter)
        self._replace_section_body(1, body)

        # Retain the canonical material table and give its physical convention a clear label.
        self.materials.setHorizontalHeaderLabels(['Object', 'Relative permittivity εr = n²'])
        self.te.setText('Electric field in plane (TE; Hz)')
        self.tm.setText('Electric field along z (TM; Ez)')
        self.sampling.setItemText(self.sampling.findData('grid'), 'Full reciprocal-cell grid')
        kbody = QWidget(); klayout = QVBoxLayout(kbody)
        self.kform = QFormLayout()
        for caption, widget in [('Sample wavevectors', self.sampling), ('Intervals per path segment', self.points_per_segment),
                                ('Points per reciprocal direction', self.grid_counts), ('Fractional offset', self.grid_offset)]:
            self.kform.addRow(caption, widget)
        klayout.addLayout(self.kform)
        self.kpath_note = label('Custom fractional reciprocal coordinates. No symmetry reduction is assumed.')
        klayout.addWidget(self.kpath_note)
        self.kpoints.setMinimumHeight(0); self.kpoints.setMaximumHeight(260)
        klayout.addWidget(self.kpoints)
        self.kpoint_actions = QWidget(); ka = QHBoxLayout(self.kpoint_actions)
        ka.addWidget(button('Add point', self.add_kpoint)); ka.addWidget(button('Remove selected point', self.remove_kpoint)); ka.addStretch()
        klayout.addWidget(self.kpoint_actions)
        klayout.addWidget(label('Coordinates multiply reciprocal vectors b₁, b₂ (and b₃ in 3D). A grid uses kᵢ = jᵢ/Nᵢ + offsetᵢ and samples the primitive reciprocal cell, not a symmetry-reduced zone.'))
        klayout.addStretch(); self._replace_section_body(3, kbody)

        sbody = QWidget(); slayout = QVBoxLayout(sbody)
        slayout.addWidget(label('Calculation', 'setupHeading'))
        self.solver_form = QFormLayout()
        for caption, widget in [('Solver', self.solver), ('Lowest bands per wavevector', self.num_bands),
                ('Grid points per lattice direction', self.resolution), ('Reciprocal cutoff gmax (2π / a)', self.gmax)]:
            self.solver_form.addRow(caption, widget)
        slayout.addLayout(self.solver_form)
        self.solver_note = label('')
        slayout.addWidget(label('Solver installation', 'setupHeading'))
        self.runtime_form = QFormLayout()
        for caption, widget in [('Run on', self.runtime_mode), ('WSL distribution', self.distro), ('Executable', self.executable)]:
            self.runtime_form.addRow(caption, widget)
        slayout.addLayout(self.runtime_form)
        self.advanced_solver_toggle = QCheckBox('Advanced accuracy and installation options')
        slayout.addWidget(self.advanced_solver_toggle)
        self.advanced_solver = QWidget()
        self.advanced_solver_form = QFormLayout(self.advanced_solver)
        for caption, widget in [('Eigensolver tolerance', self.tolerance), ('Material averaging mesh', self.mesh_size),
                ('Python package folders', self.module_paths), ('Native library folders', self.library_paths), ('Time limit (s)', self.timeout)]:
            self.advanced_solver_form.addRow(caption, widget)
        slayout.addWidget(self.advanced_solver)
        self.advanced_solver_toggle.toggled.connect(self.advanced_solver.setVisible)
        self.advanced_solver.hide()
        slayout.addWidget(self.solver_note)
        slayout.addWidget(label('Choose your installed solver. Switching solver keeps your runtime paths unchanged. Accuracy should be checked on the Convergence page.'))
        slayout.addStretch(); self._replace_section_body(4, sbody)

        rbody = QWidget(); rlayout = QVBoxLayout(rbody)
        self.review_summary = QTextBrowser()
        self.review_summary.setAccessibleName('Band calculation summary')
        rlayout.addWidget(self.review_summary, 1)
        self.exact_request_toggle = QCheckBox('Show exact solver request')
        rlayout.addWidget(self.exact_request_toggle)
        self.review.setMinimumHeight(160)
        rlayout.addWidget(self.review)
        self.review.hide()
        self.exact_request_toggle.toggled.connect(self.review.setVisible)
        ra = QHBoxLayout()
        ra.addWidget(button('Refresh summary', self.review_inputs))
        ra.addWidget(button('Import settings…', self.import_settings))
        ra.addWidget(button('Export settings…', self.export_settings))
        rlayout.addLayout(ra); self._replace_section_body(6, rbody)
        self.geometry.currentCellChanged.connect(lambda *args: self._refresh_inspector())
        self.lattice.cellChanged.connect(self._lattice_edited)
        self.reference_length.textChanged.connect(self._lattice_summary)
        self.kpoints.cellChanged.connect(self._clear_path_labels)
        self.runtime_mode.currentIndexChanged.connect(self._solver_changed)
        self._dimension_changed(); self._solver_changed(); self._sampling_changed()
        self.geometry.setCurrentCell(0, 0)
        self.tabs.setCurrentIndex(1)
        self._section_changed(self.tabs.currentIndex())

    def _build_crystal_workflow(self):
        """Three task steps around a persistent editable periodic-crystal scene."""
        self._workflow_ready = False
        self.setObjectName('photonicBandsWorkspace')
        self._crystal_stage = 'unit'
        self._scale_sync = False
        self.section_nav.hide()
        self.heading.setText('Photonic Bands')
        heading_font = self.heading.font(); heading_font.setPointSize(18); heading_font.setBold(True); self.heading.setFont(heading_font)
        self.description.setText('Build a 3D periodic crystal and calculate its optical bands.')
        flow = self.flow_bar.layout()
        while flow.count():
            item = flow.takeAt(0)
            if item.widget(): item.widget().hide()
        self.stage_buttons = {}
        for key, caption in [('unit', '1  Unit cell'), ('build', '2  Build crystal'), ('calculate', '3  Calculate')]:
            control = button(caption, lambda checked=False, stage=key: self.show_stage(stage))
            control.setMinimumHeight(40)
            control.setMinimumWidth(128); control.setMaximumWidth(190)
            control.setObjectName('bandsStep')
            control.setCheckable(True)
            self.stage_buttons[key] = control
            flow.addWidget(control)
        flow.addStretch()
        flow.addWidget(button('Results', lambda: self.select_section('Results')))
        more = QPushButton('More')
        menu = QMenu(more)
        for title in ('Overview', 'Materials', 'k-space path', 'Outputs', 'Review & Run',
                      'Parameter sweep', 'Convergence', 'Paper benchmarks'):
            menu.addAction({'k-space path': 'Customize wavevector sampling', 'Review & Run': 'Exact review and settings files'}.get(title, title),
                lambda checked=False, section=title: self.select_section(section))
        more.setMenu(menu); flow.addWidget(more)
        self.workflow_instruction = label('Choose the unit cell and scale. All template geometry remains editable.', 'setupHeading')
        self.body_layout.insertWidget(3, self.workflow_instruction)

        # Keep the canonical micrometre field for old drafts, using nm in the visible setup.
        self.reference_length.setParent(self); self.reference_length.hide()
        self.new_shape.setParent(self); self.new_shape.hide()
        self.lattice_details_toggle.setParent(self); self.lattice_details_toggle.hide()
        self.compact_preview_toggle.setParent(self); self.compact_preview_toggle.hide()
        body = QWidget(); crystal = QVBoxLayout(body); crystal.setContentsMargins(0, 0, 0, 0)
        self.geometry_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.geometry_splitter.setChildrenCollapsible(False)

        cell_content = QWidget(); cell = QVBoxLayout(cell_content); cell.setContentsMargins(12, 8, 12, 8)
        cell.addWidget(label('Define the unit cell', 'setupHeading'))
        cellform = QFormLayout()
        self.unit_form = cellform
        cellform.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.dimension.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.dimension.setMinimumContentsLength(10)
        cellform.addRow('Crystal model', self.dimension)
        self.scale_nm = QLineEdit(); self.scale_nm.setAccessibleName('Reference scale a in nanometres')
        self.scale_nm.setPlaceholderText('Optional — normalized units if blank')
        self.fields['physical_scale_nm'] = self.scale_nm
        cellform.addRow('Reference scale a (nm)', self.scale_nm)
        cell.addLayout(cellform)
        self.scale_help = label('Set a to convert normalized dimensions to nm. In a cubic cell, a is the edge length.')
        cell.addWidget(self.scale_help)
        cell.addWidget(label('Starting crystal', 'setupHeading'))
        self.crystal_template = QComboBox()
        self.crystal_template.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.crystal_template.setMinimumContentsLength(12)
        for caption, key in [('Simple cubic spheres · illustrative', 'simple_cubic'),
                             ('Diamond network · FCC', 'diamond'), ('Custom / saved crystal', 'custom')]:
            self.crystal_template.addItem(caption, key)
        self.crystal_template.setAccessibleName('Editable three-dimensional starting crystal')
        cell.addWidget(self.crystal_template)
        self.template_apply = button('Apply starting crystal', self.apply_crystal_template)
        cell.addWidget(self.template_apply)
        self.template_note = label('Illustrative sphere in air. This starting geometry does not promise a band gap.')
        cell.addWidget(self.template_note)
        self.unit_custom_toggle = QCheckBox('Custom lattice vectors')
        cell.addWidget(self.unit_custom_toggle)
        self.unit_custom = QWidget(); custom = QVBoxLayout(self.unit_custom); custom.setContentsMargins(0, 0, 0, 0)
        custom.addWidget(self.lattice_preset); custom.addWidget(self.apply_preset_button)
        custom.addWidget(self.lattice_summary); custom.addWidget(self.lattice)
        self.lattice.setMinimumHeight(105); self.lattice.setMaximumHeight(150); self.lattice.show()
        cell.addWidget(self.unit_custom); self.unit_custom.hide()
        self.unit_custom_toggle.toggled.connect(self.unit_custom.setVisible)
        self.custom_vectors_toggle.setParent(self); self.custom_vectors_toggle.hide()
        self.dimension_note.setParent(self); self.dimension_note.hide()
        cell.addStretch()
        cell.addWidget(button('Continue to build crystal', lambda: self.show_stage('build')))
        self.unit_panel = QScrollArea(); self.unit_panel.setWidgetResizable(True); self.unit_panel.setWidget(cell_content)
        self.unit_panel.setMinimumWidth(340); self.unit_panel.setMaximumWidth(370)
        self.geometry_splitter.addWidget(self.unit_panel)

        self.object_panel = QWidget(); objects = QVBoxLayout(self.object_panel); objects.setContentsMargins(8, 8, 8, 8)
        objects.addWidget(label('Crystal objects', 'setupHeading'))
        self.geometry.setMinimumHeight(100); self.geometry.setMaximumHeight(16777215)
        self.geometry.setColumnHidden(1, True)
        self.geometry.setHorizontalHeaderLabels(['Name', 'Shape', 'Center / a', 'Radius / a', 'Size / a', 'Height / a', 'Axis', 'Block axes'])
        objects.addWidget(self.geometry, 1)
        self.add_shape_buttons = {}
        for shape in ('sphere', 'block', 'cylinder', 'circle'):
            add = button('+ Add '+shape, lambda checked=False, s=shape: self.add_shape(s))
            self.add_shape_buttons[shape] = add; objects.addWidget(add)
        objects.addWidget(button('Remove object', self.remove_primitive))
        objects.addSpacing(12); objects.addWidget(label('Background material', 'setupHeading'))
        self.background.setAccessibleName('Background relative permittivity')
        background_form = QFormLayout(); background_form.addRow('εr', self.background); objects.addLayout(background_form)
        objects.addWidget(label('Air: εr = 1. Lossless, nondispersive dielectrics only.'))
        self.object_panel.setMinimumWidth(170); self.object_panel.setMaximumWidth(220)
        self.geometry_splitter.addWidget(self.object_panel)

        self.preview_body = QWidget(); scene_layout = QVBoxLayout(self.preview_body); scene_layout.setContentsMargins(6, 8, 6, 8)
        scene_controls = QHBoxLayout()
        self.view_direction = QComboBox()
        for title, key in [('Isometric', 'isometric'), ('Top', 'top'), ('Front', 'front'), ('Right', 'right')]:
            self.view_direction.addItem(title, key)
        self.view_direction.setAccessibleName('3D crystal view direction')
        self.view_direction.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.view_direction.setFixedWidth(118)
        self.repeat_cells = QComboBox()
        self.repeat_cells.addItem('One cell', 1); self.repeat_cells.addItem('3 × 3 × 3 cells', 3)
        self.repeat_cells.setAccessibleName('Repeated periodic cells')
        self.repeat_cells.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.repeat_cells.setFixedWidth(145)
        scene_controls.addWidget(self.view_direction); scene_controls.addWidget(self.repeat_cells)
        reset_view = button('Reset view', lambda: self.crystal_3d.reset_camera())
        reset_view.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        reset_view.setFixedWidth(100)
        scene_controls.addWidget(reset_view)
        scene_controls.addStretch(); scene_layout.addLayout(scene_controls)
        self.scene_stack = QStackedWidget()
        self.preview.setMinimumSize(240, 260); self.preview.setMaximumHeight(16777215)
        self.scene_stack.addWidget(self.preview)
        self.crystal_3d = PhotonicCrystal3D()
        self.scene_stack.addWidget(self.crystal_3d)
        scene_layout.addWidget(self.scene_stack, 1)
        self.scene_scale_note = label('Drag to rotate · Scroll to zoom · Shift-drag to pan · Click an object to edit')
        scene_layout.addWidget(self.scene_scale_note)
        scene_layout.addWidget(self.preview_note)
        self.geometry_splitter.addWidget(self.preview_body)

        inspector_content = QWidget(); inspector = QVBoxLayout(inspector_content); inspector.setContentsMargins(8, 8, 8, 8)
        self.compact_object_picker = QComboBox(); self.compact_object_picker.setAccessibleName('Selected crystal object')
        inspector.addWidget(self.compact_object_picker)
        self.compact_add_button = QPushButton('Add object…'); add_menu = QMenu(self.compact_add_button)
        for shape in ('sphere', 'block', 'cylinder', 'circle'):
            add_menu.addAction('Add '+shape, lambda checked=False, s=shape: self.add_shape(s))
        add_menu.addAction('Remove selected object', self.remove_primitive)
        self.compact_add_button.setMenu(add_menu); inspector.addWidget(self.compact_add_button)
        self.inspector_group.setTitle('Selected object')
        self.primitive_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        # Cartesian components replace comma-delimited primary editing, with a raw fallback for invalid drafts.
        for field in ('center', 'size', 'axis'):
            old = self.primitive_fields[field]
            row, _ = self.primitive_form.getWidgetPosition(old)
            caption = self.primitive_form.labelForField(old).text()
            self.primitive_form.removeRow(row)
            edit = _CartesianInput(3)
            edit.setAccessibleName('Selected object '+field)
            edit.textChanged.connect(lambda text, key=field: self._inspector_edited(key, text))
            self.primitive_fields[field] = edit
            self.primitive_form.insertRow(row, caption, edit)
        self.material_choice = QComboBox()
        self.material_choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.material_choice.setMinimumContentsLength(10)
        for title, value in [('Custom dielectric', None), ('Air', 1), ('Dielectric (example)', 12)]:
            self.material_choice.addItem(title, value)
        self.material_choice.setAccessibleName('Selected object material')
        material_row, _ = self.primitive_form.getWidgetPosition(self.primitive_fields['epsilon'])
        self.primitive_form.insertRow(material_row, 'Material', self.material_choice)
        self.material_choice.currentIndexChanged.connect(self._assign_material)
        inspector.addWidget(self.inspector_group)
        self.physical_dimensions = label('Object dimensions are Cartesian multiples of a.')
        inspector.addWidget(self.physical_dimensions)
        self.compact_background_group = QGroupBox('Background material')
        compact_material_form = QFormLayout(self.compact_background_group)
        compact_material_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.compact_material_form = compact_material_form
        self.compact_background = QLineEdit(self.background.text())
        self.compact_background.setAccessibleName('Background relative permittivity')
        compact_material_form.addRow('Permittivity εr', self.compact_background)
        inspector.addWidget(self.compact_background_group)
        self.compact_background.textChanged.connect(self.background.setText)
        self.background.textChanged.connect(self.compact_background.setText)
        inspector.addStretch()
        inspector.addWidget(button('Continue to calculate', lambda: self.show_stage('calculate')))
        self.inspector_panel = QScrollArea(); self.inspector_panel.setWidgetResizable(True); self.inspector_panel.setWidget(inspector_content)
        self.inspector_panel.setMinimumWidth(275); self.inspector_panel.setMaximumWidth(355)
        self.geometry_splitter.addWidget(self.inspector_panel)
        self._panel_widgets = [cell_content, self.object_panel, inspector_content]
        for panel in self._panel_widgets:
            panel.setObjectName('bandsPanel'); panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        for panel in (self.unit_panel, self.inspector_panel):
            panel.setObjectName('bandsSideScroll')
        self.geometry.setObjectName('bandObjectList'); self.geometry.horizontalHeader().hide(); self.geometry.setShowGrid(False)
        self.geometry.verticalHeader().setDefaultSectionSize(36)
        self.inspector_group.setObjectName('bandsInspector')
        crystal.addWidget(self.geometry_splitter, 1)
        self.crystal_editor = cell_content
        self._replace_section_body(1, body)

        # Calculation is a short task page; detailed sampling and outputs remain separately reachable.
        calc_body = QWidget(); calc = QHBoxLayout(calc_body); calc.setContentsMargins(8, 8, 8, 8)
        self.calculation_layout = calc
        settings = QWidget(); setup = QVBoxLayout(settings)
        setup.addWidget(label('Calculate the band structure', 'setupHeading'))
        self.calculation_mode = label('3D full-vector MPB modes')
        setup.addWidget(self.calculation_mode)
        sample_group = QGroupBox('1. Sample wavevectors'); sample_box = QVBoxLayout(sample_group)
        self.sampling_summary = label('')
        sample_box.addWidget(self.sampling_summary)
        sample_box.addWidget(button('Edit path or choose a reciprocal grid…', lambda: self.select_section('k-space path')))
        setup.addWidget(sample_group)
        accuracy_group = QGroupBox('2. Choose how many bands and the accuracy'); accuracy = QFormLayout(accuracy_group)
        accuracy.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.solver_form = accuracy
        for title, control in [('Solver', self.solver), ('Lowest bands at each wavevector', self.num_bands),
                               ('Grid points per lattice direction', self.resolution), ('Legume reciprocal cutoff gmax', self.gmax)]:
            accuracy.addRow(title, control)
        setup.addWidget(accuracy_group)
        setup.addWidget(label('Start with the supplied grid, then use Convergence to check that the frequencies stabilize.'))
        runtime_group = QGroupBox('3. Connect your solver'); runtime_box = QVBoxLayout(runtime_group)
        from qt_photonic_runtime import PhotonicRuntimeCheck
        self.runtime_check = PhotonicRuntimeCheck(lambda: dict(solver=self.solver.currentData(), runtime=self.runtime_settings()), self)
        runtime_box.addWidget(self.runtime_check)
        self.runtime_setup_toggle = QCheckBox('Set up or change the solver installation')
        runtime_box.addWidget(self.runtime_setup_toggle)
        self.runtime_setup = QWidget(); self.runtime_form = QFormLayout(self.runtime_setup)
        self.runtime_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for title, control in [('Run on', self.runtime_mode), ('WSL distribution', self.distro), ('Executable', self.executable)]:
            self.runtime_form.addRow(title, control)
        remember = button('Remember solver setup on this computer', self.remember_runtime)
        self.runtime_form.addRow(remember)
        runtime_box.addWidget(self.runtime_setup); self.runtime_setup.hide()
        self.runtime_setup_toggle.toggled.connect(self.runtime_setup.setVisible)
        setup.addWidget(runtime_group)
        setup.addWidget(self.advanced_solver_toggle); setup.addWidget(self.advanced_solver)
        self.solver_note.setParent(self); self.solver_note.hide()
        setup.addStretch(); calc.addWidget(settings, 5)
        self.calculation_summary = QTextBrowser(); self.calculation_summary.setAccessibleName('What will be calculated')
        calc.addWidget(self.calculation_summary, 4)
        self._replace_section_body(4, calc_body)

        self.crystal_3d.objectSelected.connect(self._select_scene_object)
        self.view_direction.currentIndexChanged.connect(lambda _: self.crystal_3d.set_standard_view(self.view_direction.currentData()))
        self.repeat_cells.currentIndexChanged.connect(lambda _: self.crystal_3d.set_repeat(self.repeat_cells.currentData()))
        self.compact_object_picker.currentIndexChanged.connect(lambda _: self._select_scene_object(self.compact_object_picker.currentData()))
        self.scale_nm.textChanged.connect(self._nm_scale_edited)
        self.reference_length.textChanged.connect(self._reference_scale_edited)
        self.background.textChanged.connect(self._queue_preview)
        self.background.textChanged.connect(self._mark_custom_crystal)
        for control in (self.executable, self.distro, self.module_paths, self.library_paths, self.timeout):
            control.textChanged.connect(self.runtime_check.invalidate)
        for control in (self.solver, self.runtime_mode):
            control.currentIndexChanged.connect(self.runtime_check.invalidate)
        self._workflow_ready = True
        theme_manager().changed.connect(self._style_workspace)
        theme_manager().appearance_changed.connect(self._style_workspace)
        self._style_workspace()
        self._apply_template_values('simple_cubic')
        self._restore_remembered_runtime()
        self.show_stage('unit')
        self._reference_scale_edited()
        self.adapt_layout()

    def show_stage(self, stage):
        self._crystal_stage = stage
        self.tabs.setCurrentIndex(4 if stage == 'calculate' else 1)
        self._update_workflow()
        if stage == 'calculate': self._refresh_calculation_summary()
        self._edited()

    def _update_workflow(self):
        if not getattr(self, '_workflow_ready', False): return
        index = self.tabs.currentIndex()
        stage = self._crystal_stage if index == 1 else 'calculate' if index in (3, 4, 5, 6) else ''
        for name, control in self.stage_buttons.items():
            control.setChecked(name == stage)
        self.workflow_instruction.setText({'unit': 'Choose the unit cell and scale. Then build and edit the crystal.',
            'build': 'Add an object, select it in the scene, and enter its size and material.',
            'calculate': 'Choose the sampling and accuracy, check the solver, then calculate bands.'}.get(stage, self.tabs.tabText(index)))
        compact = self.width() < 1100
        self.section_nav.hide(); self.section_picker.hide(); self.step_label.hide(); self.back_step.hide(); self.next_step.hide()
        self.description.hide()
        self.calculation_summary.show()
        self.calculation_layout.setDirection(QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight)
        self.calculation_summary.setMinimumHeight(250)
        self.unit_panel.setVisible(stage == 'unit')
        self.object_panel.setVisible(stage == 'build' and not compact)
        self.inspector_panel.setVisible(stage == 'build')
        self.preview_body.show()
        self.compact_object_picker.setVisible(compact); self.compact_add_button.setVisible(compact)
        self.compact_background_group.setVisible(compact)
        self.geometry_splitter.setOrientation(Qt.Orientation.Horizontal)
        width = max(self.geometry_splitter.width(), self.width()-40)
        self.geometry_splitter.setSizes([350 if stage == 'unit' else 0, 185 if stage == 'build' and not compact else 0,
            max(280, width-(350 if stage == 'unit' else 505 if not compact else 305)), 320 if stage == 'build' else 0])
        self.scene_stack.setCurrentIndex(1 if self.dimension.currentData() == 3 else 0)
        self.view_direction.setVisible(self.dimension.currentData() == 3)
        self.repeat_cells.setVisible(self.dimension.currentData() == 3)

    def adapt_layout(self):
        """Reapply band-specific forms after the host adapts its legacy pages."""
        if not getattr(self, '_workflow_ready', False): return
        self.primitive_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.primitive_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.unit_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.unit_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.primitive_form.labelForField(self.primitive_fields['epsilon']).setText('Permittivity εr')
        for form in (self.primitive_form, self.unit_form, self.compact_material_form):
            for row in range(form.rowCount()):
                item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                caption = item.widget() if item is not None else None
                if caption is not None and hasattr(caption, 'setWordWrap'):
                    caption.setWordWrap(False)
                    caption.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
                    caption.setMinimumWidth(80)
        self._update_workflow()

    def _style_workspace(self, *args):
        colors = COLORS[theme_manager().mode]
        self.setStyleSheet(f'''
            QWidget#bandsPanel {{ background: {colors['panel']}; }}
            QLabel#bandsTitle {{ font-size: 24px; font-weight: 600; }}
            QScrollArea#bandsSideScroll {{ border: 0; background: {colors['panel']}; }}
            QPushButton#bandsStep {{ border: 0; border-radius: 6px; padding: 6px 12px; color: {colors['muted']}; background: transparent; font-weight: 500; }}
            QPushButton#bandsStep:hover {{ background: {colors['hover']}; }}
            QPushButton#bandsStep:checked {{ background: {colors['select']}; color: {colors['accent']}; font-weight: 600; }}
            QTableWidget#bandObjectList {{ border: 0; background: {colors['panel']}; gridline-color: transparent; }}
            QTableWidget#bandObjectList::item {{ padding: 5px 9px; border: 0; }}
            QTableWidget#bandObjectList::item:selected {{ background: {colors['select']}; color: {colors['accent']}; }}
            QGroupBox#bandsInspector {{ border: 0; margin-top: 20px; padding: 8px 4px; background: {colors['panel']}; }}
            QGroupBox#bandsInspector::title {{ subcontrol-origin: margin; left: 8px; color: {colors['text']}; font-size: 16px; font-weight: 600; }}
            QWidget#bandsPanel QLabel {{ background: transparent; }}
            QWidget#bandsPanel QLabel#setupHeading {{ font-size: 15px; font-weight: 600; color: {colors['text']}; }}
            QWidget#bandsPanel QLineEdit {{ background: {colors['panel']}; border: 1px solid {colors['border']}; border-radius: 5px; padding: 5px 7px; min-height: 22px; }}
        ''')
        font = self.heading.font(); font.setPointSize(18); font.setBold(True); self.heading.setFont(font)

    def _select_scene_object(self, identity):
        if identity not in self._object_ids: return
        row = self._object_ids.index(identity)
        self.geometry.setCurrentCell(row, 0)
        self._refresh_inspector()
        if self.tabs.currentIndex() == 1 and self._crystal_stage != 'build': self.show_stage('build')

    def add_shape(self, shape):
        self.new_shape.setCurrentIndex(self.new_shape.findData(shape))
        self.add_primitive()

    def _assign_material(self):
        value = self.material_choice.currentData()
        if value is not None and not self._inspector_updating:
            self.primitive_fields['epsilon'].setText(str(value))

    def _nm_scale_edited(self):
        if self._scale_sync: return
        self._scale_sync = True
        raw = self.scale_nm.text()
        try: converted = str(float(raw)/1000) if raw.strip() else ''
        except ValueError: converted = raw
        self.reference_length.setText(converted)
        self._scale_sync = False
        self._update_physical_dimensions(); self._edited()

    def _reference_scale_edited(self):
        if self._scale_sync or not hasattr(self, 'scale_nm'): return
        self._scale_sync = True
        raw = self.reference_length.text()
        try: converted = str(float(raw)*1000) if raw.strip() else ''
        except ValueError: converted = raw
        self.scale_nm.setText(converted)
        self._scale_sync = False
        self._update_physical_dimensions()

    def _update_physical_dimensions(self):
        if not hasattr(self, 'physical_dimensions'): return
        try:
            a = float(self.scale_nm.text())
            if not np.isfinite(a) or a <= 0: raise ValueError('Invalid physical scale')
            radius = float(self.primitive_fields['radius'].text())
            valid = np.isfinite(a) and a > 0 and np.isfinite(radius) and radius > 0
            text = f'a = {a:g} nm. Radius {radius:g}a = {radius*a:g} nm.' if valid and self.primitive_shape.currentData() in ('sphere','circle','cylinder') else f'a = {a:g} nm. Multiply each normalized dimension by a.'
        except ValueError:
            text = 'Dimensions are Cartesian multiples of a. Set a physical scale in Unit cell to see dimensions in nm.'
        self.physical_dimensions.setText(text)

    def remember_runtime(self):
        try:
            value = self.runtime_settings()
            preferences().setValue('photonic_bands_runtime/'+self.solver.currentData(), json.dumps(value))
            self.status.setText('Solver setup saved for new workspaces on this computer. Use Check solver to verify the installation.')
        except ValueError as exc:
            self.diagnostics.set_diagnostics([self._issue(exc)], workspace=self.workspace_id)

    def _restore_remembered_runtime(self):
        raw = preferences().value('photonic_bands_runtime/'+self.solver.currentData(), '')
        try: runtime = json.loads(raw) if raw else {}
        except (ValueError, TypeError): return
        if not isinstance(runtime, dict): return
        for key, value in runtime.items():
            control = self.fields.get('runtime.'+key)
            if isinstance(control, QLineEdit): control.setText('; '.join(map(str, value)) if isinstance(value, list) else str(value))
            elif isinstance(control, QComboBox): control.setCurrentIndex(max(0, control.findData(value)))

    def _refresh_calculation_summary(self):
        dim = self.dimension.currentData()
        mode = self.sampling.currentData()
        self.calculation_mode.setText('3D full-vector modes. TE/TM separation does not apply.' if dim == 3 else '2D crystal, invariant along z. Select TE/TM under More → Outputs.')
        if mode == 'grid': summary = 'Full reciprocal-cell grid: '+self.grid_counts.text()+' points per direction.'
        elif mode == 'points': summary = str(self.kpoints.rowCount())+' explicit reciprocal points.'
        else: summary = str(self.kpoints.rowCount())+' path vertices · '+self.points_per_segment.text()+' intervals per segment.'
        self.sampling_summary.setText(summary+' Coordinates are fractional reciprocal coordinates.')
        self.calculation_summary.setHtml('<h2>What will be calculated</h2><p><b>'+str(dim)+'D periodic crystal</b><br>'+str(len(self._object_ids))+ ' editable objects</p>'+
            '<h3>Bands</h3><p>'+escape(self.num_bands.text())+' lowest modes at each sampled wavevector.<br>'+escape(summary)+'</p>'+
            '<h3>Before you run</h3><p>1. Check the geometry and material values.<br>2. Check solver confirms that the installation is usable.<br>3. Choose <b>Calculate bands</b> in the bottom bar.</p>'+
            '<h3>After the calculation</h3><p>Open Results for the band diagram and sampled gaps. Use Convergence to compare accuracy levels. A finite path does not establish a complete band gap.</p>')

    def apply_crystal_template(self):
        key = self.crystal_template.currentData()
        if key == 'custom':
            self.unit_custom_toggle.setChecked(True)
            return
        self._apply_template_values(key)
        self._edited()

    def _mark_custom_crystal(self):
        if not getattr(self, '_workflow_ready', False) or getattr(self, '_applying_template', False): return
        with QSignalBlocker(self.crystal_template):
            self.crystal_template.setCurrentIndex(self.crystal_template.findData('custom'))
        self.template_note.setText('Custom / saved crystal. Geometry and its reference-scale convention are preserved.')
        self.template_note.setToolTip('No lattice-template normalization is assumed. All lattice vectors and object dimensions use the saved reference scale a.')
        self.scale_help.setText('a is the reference length for all saved coordinates. It need not equal every lattice-vector length.')

    def _apply_template_values(self, key):
        self._applying_template = True
        try: self._set_template_values(key)
        finally: self._applying_template = False

    def _set_template_values(self, key):
        self.dimension.setCurrentIndex(self.dimension.findData(3))
        self.solver.setCurrentIndex(self.solver.findData('mpb'))
        if key == 'diamond':
            lattice = [[0,.5,.5],[.5,0,.5],[.5,.5,0]]
            centers = [[-.125,-.125,-.125],[.125,.125,.125]]
            radius, epsilon = .33/np.sqrt(2), 16
            names = ['Γ','X','W','K','Γ','L','U','W','L','K','U','X']
            points = [[0,0,0],[.5,0,.5],[.5,.25,.75],[.375,.375,.75],[0,0,0],[.5,.5,.5],
                [.625,.25,.625],[.5,.25,.75],[.5,.5,.5],[.375,.375,.75],[.625,.25,.625],[.5,0,.5]]
            self.template_note.setText('Diamond network · conventional cubic a. FCC primitive vectors have length a/√2.')
            self.template_note.setToolTip('Overlapping εr = 16 spheres. This editable template uses the conventional cubic scale; the paper benchmark retains its original primitive-vector normalization.')
            self.repeat_cells.setCurrentIndex(self.repeat_cells.findData(3))
        else:
            lattice = np.eye(3).tolist(); centers = [[0,0,0]]; radius, epsilon = .25, 12
            names = ['Γ','X','M','Γ','R','X','M','R']
            points = [[0,0,0],[.5,0,0],[.5,.5,0],[0,0,0],[.5,.5,.5],[.5,0,0],[.5,.5,0],[.5,.5,.5]]
            self.template_note.setText('Illustrative sphere in air: r = 0.25a, εr = 12. Edit every value in Build crystal.')
            self.template_note.setToolTip('An illustrative starting geometry; a band gap is not guaranteed.')
            self.repeat_cells.setCurrentIndex(self.repeat_cells.findData(1))
        _fill(self.lattice, lattice); self.background.setText('1')
        self._object_ids = [uuid.uuid4().hex for _ in centers]
        self._epsilons = {identity: str(epsilon) for identity in self._object_ids}
        _fill(self.geometry, [['Sphere '+str(i+1), 'sphere', ', '.join(map(str, center)), str(radius), '.4, .4, .4', '.4', '0, 0, 1', '1, 0, 0; 0, 1, 0; 0, 0, 1'] for i, center in enumerate(centers)])
        _fill(self.kpoints, points); self.kpoints.setVerticalHeaderLabels(names)
        self.kpath_note.setText('Suggested path: '+' → '.join(names)+'. No motif symmetry reduction is assumed.')
        self.sampling.setCurrentIndex(self.sampling.findData('path')); self.grid_counts.setText('8, 8, 8'); self.grid_offset.setText('0, 0, 0')
        _fill(self.sweeps, []); self._sweep_targets = []
        self._sync_materials(); self.geometry.setCurrentCell(0, 0); self._refresh_inspector(); self._queue_preview()
        self._lattice_summary(); self._solver_changed(); self._sampling_changed(); self._update_workflow()
        self.crystal_template.setCurrentIndex(self.crystal_template.findData(key))

    def _step(self, direction):
        order = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        position = order.index(self.tabs.currentIndex())
        self.tabs.setCurrentIndex(order[max(0, min(len(order)-1, position+direction))])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, '_workflow_ready', False):
            self._update_workflow()
            return
        if not hasattr(self, 'section_nav'):
            return
        compact = self.width() < 1050
        was_compact = getattr(self, '_compact', None)
        self._compact = compact
        self.section_nav.setVisible(not compact)
        self.section_picker.setVisible(compact)
        self.step_label.setVisible(not compact)
        self.description.setVisible(not compact)
        if was_compact != compact:
            self.lattice_details_toggle.setChecked(not compact)
            self.compact_preview_toggle.setChecked(False)
        self.compact_preview_toggle.setVisible(compact)
        self.preview_body.setVisible(not compact or self.compact_preview_toggle.isChecked())
        self.geometry_splitter.setOrientation(Qt.Orientation.Vertical if compact else Qt.Orientation.Horizontal)
        if not compact:
            self._balance_preview()

    def _balance_preview(self):
        if getattr(self, '_workflow_ready', False):
            self._update_workflow()
            return
        if not getattr(self, '_compact', False):
            available = max(600, self.geometry_splitter.width())
            self.geometry_splitter.setSizes([int(available*.48), int(available*.52)])

    def _compact_preview_changed(self, checked):
        if getattr(self, '_compact', False):
            self.preview_body.setVisible(checked)
            if checked:
                QTimer.singleShot(0, lambda: self.tabs.widget(1).ensureWidgetVisible(self.preview, 16, 16))

    def _inspector_edited(self, key, value):
        if self._inspector_updating or value is None:
            return
        row = self.geometry.currentRow()
        if not 0 <= row < len(self._object_ids):
            return
        self._inspector_updating = True
        try:
            if key == 'epsilon':
                self._epsilons[self._object_ids[row]] = value
                self._sync_materials()
                self._edited()
            else:
                self.geometry.item(row, self.geometry_columns.index(key)).setText(value)
        finally:
            self._inspector_updating = False
        self._shape_field_visibility()
        self._mark_custom_crystal()
        self._update_index_hint()
        self._update_physical_dimensions()
        self._queue_preview()

    def _refresh_inspector(self):
        if not hasattr(self, 'primitive_fields') or self._inspector_updating:
            return
        row = self.geometry.currentRow()
        valid = 0 <= row < len(self._object_ids)
        self.inspector_group.setEnabled(valid)
        self._inspector_updating = True
        try:
            values = dict(zip(self.geometry_columns, _rows(self.geometry)[row])) if valid else {}
            for key, edit in self.primitive_fields.items():
                edit.setText(self._epsilons.get(self._object_ids[row], '') if key == 'epsilon' and valid else values.get(key, ''))
                if isinstance(edit, QLineEdit): edit.setCursorPosition(0)
            shape = values.get('shape', '')
            if shape and self.primitive_shape.findData(shape) < 0:
                self.primitive_shape.addItem('Unsupported: '+shape, shape)
            self.primitive_shape.setCurrentIndex(self.primitive_shape.findData(shape))
        finally:
            self._inspector_updating = False
        self._shape_field_visibility(); self._update_index_hint()
        if getattr(self, '_workflow_ready', False):
            with QSignalBlocker(self.compact_object_picker):
                self.compact_object_picker.setCurrentIndex(self.compact_object_picker.findData(self._object_ids[row] if valid else ''))
            if valid: self.crystal_3d.set_selected(self._object_ids[row])
            self._update_physical_dimensions()
            try: value = float(self.primitive_fields['epsilon'].text())
            except ValueError: value = None
            with QSignalBlocker(self.material_choice):
                self.material_choice.setCurrentIndex(max(0, self.material_choice.findData(value) if value in (1,12) else 0))

    def _shape_field_visibility(self):
        if not hasattr(self, 'primitive_form'):
            return
        shape = self.primitive_shape.currentData()
        active = {'name', 'center', 'epsilon'} | ({'radius'} if shape in ('circle', 'sphere', 'cylinder') else set())
        if shape == 'cylinder': active |= {'height', 'axis'}
        if shape == 'block': active |= {'size', 'axes'}
        for key, edit in self.primitive_fields.items():
            self._form_row_visible(self.primitive_form, edit, key in active)
        self.primitive_form.labelForField(self.primitive_fields['center']).setText('Center (x, y'+(', z' if self.dimension.currentData() == 3 else '')+') / a')

    def _update_index_hint(self):
        try:
            value = float(self.primitive_fields['epsilon'].text())
            text = f'εr = n² → refractive index n ≈ {np.sqrt(value):.4g}' if np.isfinite(value) and value > 0 else 'Enter positive εr; n = √εr.'
        except ValueError:
            text = 'Enter positive εr; n = √εr.'
        self.index_hint.setText(text+' (lossless, nonmagnetic)')

    def apply_lattice_preset(self):
        key = self.lattice_preset.currentData()
        presets = {'square': (2, [[1,0,0],[0,1,0],[0,0,1]], [[0,0,0],[.5,0,0],[.5,.5,0],[0,0,0]], ['Γ','X','M','Γ']),
            'triangular': (2, [[1,0,0],[.5,np.sqrt(3)/2,0],[0,0,1]], [[0,0,0],[.5,0,0],[2/3,1/3,0],[0,0,0]], ['Γ','M','K','Γ']),
            'cubic': (3, np.eye(3).tolist(), [[0,0,0],[.5,0,0],[.5,.5,0],[.5,.5,.5],[0,0,0]], ['Γ','X','M','R','Γ'])}
        if key not in presets:
            self.custom_vectors_toggle.setChecked(True)
            return
        dim, lattice, points, names = presets[key]
        self.dimension.setCurrentIndex(self.dimension.findData(dim))
        _fill(self.lattice, lattice); _fill(self.kpoints, points)
        self.sampling.setCurrentIndex(self.sampling.findData('path'))
        self._dimension_changed()
        self._preset_signature = {'lattice': _rows(self.lattice), 'kpoints': _rows(self.kpoints), 'names': names, 'key': key}
        self.kpoints.setVerticalHeaderLabels(names)
        self.kpath_note.setText('Suggested '+key+' path: '+' → '.join(names)+'. This does not assume motif symmetry or prove a complete gap.')
        self._lattice_summary(); self._edited(); self._queue_preview(); self._mark_custom_crystal()

    def _clear_path_labels(self, *args):
        if not hasattr(self, 'kpath_note'):
            return
        self._preset_signature = None
        self.kpoints.setVerticalHeaderLabels([str(i+1) for i in range(self.kpoints.rowCount())])
        self.kpath_note.setText('Custom fractional reciprocal coordinates. No symmetry reduction is assumed.')

    def _lattice_summary(self):
        dim = self.dimension.currentData()
        rows = _rows(self.lattice)[:dim]
        scale = self.reference_length.text().strip()
        self.lattice_summary.setText(str(dim)+'D · '+('a = '+scale+' µm' if scale else 'Normalized units')+' · '+
            ' · '.join('a'+str(i+1)+' = ('+', '.join(row[:dim])+')' for i, row in enumerate(rows)))

    def _lattice_edited(self, *args):
        self._mark_custom_crystal()
        self._clear_path_labels()
        self.lattice_preset.setCurrentIndex(self.lattice_preset.findData('custom'))
        self._lattice_summary(); self._queue_preview()

    def _queue_preview(self, *args):
        if hasattr(self, '_preview_timer'):
            self._preview_timer.start()

    def select_section(self, title):
        title = {'Crystal': 'Crystal structure', 'Wavevectors': 'k-space path', 'Solver': 'Solver & accuracy',
                 'Review': 'Review & Run'}.get(title, title)
        if getattr(self, '_workflow_ready', False) and title == 'Crystal structure':
            self.show_stage('build')
            return True
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == title:
                self.tabs.setCurrentIndex(index)
                return True
        return False

    def _section_changed(self, index):
        if hasattr(self, 'section_nav'):
            with QSignalBlocker(self.section_nav), QSignalBlocker(self.section_picker):
                self.section_nav.setCurrentRow(self._navigation_rows[index])
                self.section_picker.setCurrentIndex(self.section_picker.findData(index))
            self.step_label.setText(self.section_picker.currentText())
            self.back_step.setEnabled(index > 0)
            self.next_step.setEnabled(index < self.tabs.count()-1)
            next_caption = self.tabs.tabText(min(index+1, self.tabs.count()-1))
            next_caption = {'k-space path':'Wavevectors', 'Solver & accuracy':'Solver', 'Crystal structure':'Crystal', 'Review & Run':'Review'}.get(next_caption, next_caption)
            self.next_step.setText('Next: '+next_caption)
            if index == 1:
                QTimer.singleShot(0, self._balance_preview)
        if self.tabs.tabText(index) == 'Review & Run':
            self.review_inputs()
        if getattr(self, '_workflow_ready', False):
            self._update_workflow()
            if index == 4: self._refresh_calculation_summary()
        self._edited()

    def _dimension_changed(self, *args):
        dim = self.dimension.currentData()
        self.lattice.setRowHidden(2, dim == 2)
        self.lattice.setColumnHidden(2, dim == 2)
        self.kpoints.setColumnHidden(2, dim == 2)
        self.te.setEnabled(dim == 2)
        self.tm.setEnabled(dim == 2)
        if hasattr(self, 'dimension_note'):
            self._clear_path_labels()
            self.dimension_note.setText('2D is an infinite cross-section along z, not a finite-thickness slab.' if dim == 2 else
                '3D calculates full-vector modes. Object coordinates need three components.')
            self._shape_field_visibility()
            self._lattice_summary()
            self._queue_preview()
        if getattr(self, '_workflow_ready', False):
            for field in ('center', 'size'): self.primitive_fields[field].set_dimension(dim)
            for shape, add in self.add_shape_buttons.items():
                add.setVisible(shape in (('circle','block') if dim == 2 else ('sphere','block','cylinder')))
            self.new_shape.setCurrentIndex(self.new_shape.findData('sphere' if dim == 3 else 'circle'))
            self.crystal_template.setVisible(dim == 3); self.template_apply.setVisible(dim == 3)
            self.scale_help.setText('Set a to convert dimensions to nm. In a cubic cell, a is its edge length. Object positions use Cartesian coordinates.' if dim == 3 else
                '2D is invariant along z. Use the lattice editor to choose square, triangular or custom vectors. Coordinates remain in units of a.')
            if dim == 2: self.unit_custom_toggle.setChecked(True)
            self._update_workflow()
            self._mark_custom_crystal()

    def _solver_changed(self, *args):
        mpb = self.solver.currentData() == 'mpb'
        for widget in (self.resolution, self.tolerance, self.mesh_size):
            widget.setEnabled(mpb)
        self.gmax.setEnabled(not mpb)
        self.module_paths.setEnabled(not mpb)
        if hasattr(self, 'solver_form'):
            self._form_row_visible(self.solver_form, self.resolution, mpb)
            for widget in (self.tolerance, self.mesh_size):
                self._form_row_visible(self.advanced_solver_form, widget, mpb)
            self._form_row_visible(self.solver_form, self.gmax, not mpb)
            for widget in (self.module_paths, self.library_paths):
                self._form_row_visible(self.advanced_solver_form, widget, not mpb)
            self._form_row_visible(self.runtime_form, self.distro, self.runtime_mode.currentData() == 'wsl')
            self.runtime_form.labelForField(self.executable).setText('MPB executable' if mpb else 'Python executable with Legume')
            self.solver_note.setText('MPB supports 2D and 3D. Later objects replace earlier objects where they overlap. Cell vectors can have different lengths; refine the grid until frequencies stabilize.' if mpb else
                'Legume PWE supports 2D only. Objects and their periodic copies must not overlap; use MPB for overlapping objects. Increase gmax to check accuracy.')

    def _sampling_changed(self, *args):
        mode = self.sampling.currentData()
        self.kpoints.setEnabled(mode != 'grid')
        self.points_per_segment.setEnabled(mode == 'path')
        self.grid_counts.setEnabled(mode == 'grid')
        self.grid_offset.setEnabled(mode == 'grid')
        if hasattr(self, 'kform'):
            self._form_row_visible(self.kform, self.points_per_segment, mode == 'path')
            self._form_row_visible(self.kform, self.grid_counts, mode == 'grid')
            self._form_row_visible(self.kform, self.grid_offset, mode == 'grid')
            self.kpoints.setVisible(mode != 'grid')
            self.kpoint_actions.setVisible(mode != 'grid')

    def add_primitive(self):
        dim = self.dimension.currentData()
        shape = self.new_shape.currentData() or self.new_shape.currentText()
        identity = uuid.uuid4().hex
        rows = _rows(self.geometry)
        rows.append(['Object '+str(len(rows)+1), shape, ', '.join(['0']*dim), '0.2', ', '.join(['0.4']*dim), '0.4', '0, 0, 1',
                     '; '.join(', '.join('1' if i == j else '0' for j in range(dim)) for i in range(dim))])
        self._object_ids.append(identity)
        self._epsilons[identity] = '12'
        _fill(self.geometry, rows)
        self._sync_materials()
        self.geometry.setCurrentCell(len(rows)-1, 0)
        self._mark_custom_crystal()
        self._refresh_inspector()
        self._queue_preview()
        self._edited()

    def remove_primitive(self):
        row = self.geometry.currentRow()
        if 0 <= row < len(self._object_ids):
            identity = self._object_ids.pop(row)
            self._epsilons.pop(identity, None)
            rows = _rows(self.geometry)
            rows.pop(row)
            _fill(self.geometry, rows)
            self._sync_materials()
            self.geometry.setCurrentCell(min(row, len(rows)-1), 0)
            self._mark_custom_crystal()
            self._refresh_inspector()
            self._queue_preview()
            self._edited()

    def _geometry_changed(self, *args):
        self._mark_custom_crystal()
        self._sync_materials()
        self._refresh_inspector()
        self._queue_preview()
        self._edited()

    def _sync_materials(self):
        _fill(self.materials, [[row[0], self._epsilons.get(identity, '')] for row, identity in zip(_rows(self.geometry), self._object_ids)])
        for row in range(self.materials.rowCount()):
            self.materials.item(row, 0).setFlags(self.materials.item(row, 0).flags() & ~Qt.ItemFlag.ItemIsEditable)
        if hasattr(self, 'sweep_target'):
            selected = self.sweep_target.currentData()
            self.sweep_target.clear()
            self.sweep_target.addItem('Global lattice / background', '')
            for row, identity in zip(_rows(self.geometry), self._object_ids):
                self.sweep_target.addItem(row[0]+' · '+row[1], identity)
            self.sweep_target.setCurrentIndex(max(0, self.sweep_target.findData(selected)))
        if hasattr(self, 'compact_object_picker'):
            with QSignalBlocker(self.compact_object_picker):
                selected = self.compact_object_picker.currentData()
                self.compact_object_picker.clear()
                for row, identity in zip(_rows(self.geometry), self._object_ids): self.compact_object_picker.addItem(row[0], identity)
                self.compact_object_picker.setCurrentIndex(max(0, self.compact_object_picker.findData(selected)))

    def add_sweep(self):
        identity = self.sweep_target.currentData() or ''
        rows = _rows(self.sweeps)
        rows.append(['parameter_'+str(len(rows)+1), self.sweep_target.currentText(), 'radius' if identity else 'background_epsilon', ''])
        self._sweep_targets.append(identity)
        _fill(self.sweeps, rows)
        for i in range(self.sweeps.rowCount()):
            self.sweeps.item(i, 1).setFlags(self.sweeps.item(i, 1).flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._edited()

    def remove_sweep(self):
        row = self.sweeps.currentRow()
        if 0 <= row < len(self._sweep_targets):
            self._sweep_targets.pop(row)
            self.sweeps.removeRow(row)
            self._edited()

    def _material_changed(self, row, column):
        if column == 1 and row < len(self._object_ids):
            self._epsilons[self._object_ids[row]] = self.materials.item(row, column).text()
            self._mark_custom_crystal()
            self._refresh_inspector()
            self._edited()

    def add_kpoint(self):
        rows = _rows(self.kpoints)
        rows.append(['0', '0', '0'])
        _fill(self.kpoints, rows)
        self._clear_path_labels()
        self._edited()

    def remove_kpoint(self):
        row = self.kpoints.currentRow()
        if row >= 0:
            self.kpoints.removeRow(row)
            self._clear_path_labels()
            self._edited()

    def draft(self):
        state = super().draft()
        state.update(lattice=_rows(self.lattice), geometry=_rows(self.geometry), object_ids=list(self._object_ids),
            epsilons=dict(self._epsilons), kpoints=_rows(self.kpoints), sweeps=_rows(self.sweeps), sweep_targets=list(self._sweep_targets),
            polarizations={'te': self.te.isChecked(), 'tm': self.tm.isChecked()})
        if getattr(self, '_workflow_ready', False): state['workflow_stage'] = self._crystal_stage
        return state

    def restore_draft(self, state):
        super().restore_draft(state)
        for key, table in [('lattice', self.lattice), ('geometry', self.geometry), ('kpoints', self.kpoints), ('sweeps', self.sweeps)]:
            if key in state:
                _fill(table, state[key])
        self._object_ids = list(state.get('object_ids', self._object_ids))
        self._epsilons = dict(state.get('epsilons', self._epsilons))
        self._sweep_targets = list(state.get('sweep_targets', []))
        self.te.setChecked(state.get('polarizations', {}).get('te', True))
        self.tm.setChecked(state.get('polarizations', {}).get('tm', True))
        self._sync_materials()
        self._dimension_changed()
        self._solver_changed()
        self._sampling_changed()

        if hasattr(self, 'primitive_fields'):
            self.geometry.setCurrentCell(0, 0)
            self._refresh_inspector()
            self._clear_path_labels()
            self._lattice_summary()
            self._queue_preview()
            if self.tabs.currentIndex() == 6:
                self.review_inputs()
        if getattr(self, '_workflow_ready', False):
            self._crystal_stage = state.get('workflow_stage', 'build' if self.tabs.currentIndex() == 1 else 'calculate')
            self._reference_scale_edited()
            self._update_workflow()
            self.runtime_check.invalidate()
            self._mark_custom_crystal()

    def _geometry_inputs(self, materials=True):
        dim = self.dimension.currentData()
        lattice = [[number(v, f'lattice_vectors.{i}.{j}', units='a') for j, v in enumerate(row[:dim])]
                   for i, row in enumerate(_rows(self.lattice)[:dim])]
        if len(lattice) != dim or abs(np.linalg.det(np.asarray(lattice))) < 1e-12:
            raise FieldError('lattice_vectors', 'Real-space lattice vectors must be nonzero and independent.', units='a')
        geometry = []
        for values, identity in zip(_rows(self.geometry), self._object_ids):
            row = dict(zip(self.geometry_columns, values))
            shape = row['shape'].strip().lower()
            if shape not in ('circle', 'sphere', 'cylinder', 'block'):
                raise FieldError('shape', 'Choose circle, block, sphere or cylinder.', identity)
            if (dim == 2 and shape in ('sphere', 'cylinder')) or (dim == 3 and shape == 'circle'):
                raise FieldError('shape', 'Circle is 2D; sphere and finite cylinder require 3D.', identity)
            obj = dict(id=identity, name=row['name'], shape=shape, center=vector(row['center'], dim, 'center', object_id=identity),
                       epsilon=number(self._epsilons.get(identity), 'epsilon', positive=True, object_id=identity) if materials else 1)
            if shape in ('circle', 'sphere', 'cylinder'):
                obj['radius'] = number(row['radius'], 'radius', positive=True, object_id=identity, units='a')
            if shape == 'cylinder':
                obj['height'] = number(row['height'], 'height', positive=True, object_id=identity, units='a')
                obj['axis'] = vector(row['axis'], 3, 'axis', object_id=identity)
            if shape == 'block':
                obj['size'] = vector(row['size'], dim, 'size', positive=True, object_id=identity)
                obj['axes'] = [vector(value.strip(), dim, 'axes', object_id=identity) for value in row['axes'].split(';')]
                if len(obj['axes']) != dim:
                    raise FieldError('axes', 'Supply one semicolon-separated axis per dimension.', identity)
                if abs(np.linalg.det(np.asarray(obj['axes']))) < 1e-12:
                    raise FieldError('axes', 'Block axes must be nonzero and independent.', identity)
            geometry.append(obj)
        return dim, lattice, geometry

    def options(self):
        dim, lattice, geometry = self._geometry_inputs()
        solver = self.solver.currentData()
        if solver == 'legume' and dim != 2:
            raise FieldError('dimension', 'Legume PWE currently supports a 2D periodic domain. Select MPB for full-vector 3D.')
        cfg = dict(dimension=dim, lattice_vectors=lattice, geometry=geometry, solver=solver,
            background_epsilon=number(self.background.text(), 'background_epsilon', positive=True),
            num_bands=number(self.num_bands.text(), 'num_bands', positive=True, integer=True),
            polarizations=([pol for pol, widget in [('te', self.te), ('tm', self.tm)] if widget.isChecked()] if dim == 2 else ['vector']),
            runtime=self.runtime_settings())
        if not cfg['polarizations']:
            raise FieldError('polarizations', 'Select at least one 2D polarization.')
        if solver == 'mpb':
            cfg.update(resolution=number(self.resolution.text(), 'resolution', integer=True, minimum=2),
                tolerance=number(self.tolerance.text(), 'tolerance', positive=True),
                mesh_size=number(self.mesh_size.text(), 'mesh_size', integer=True, minimum=1))
        else:
            cfg['gmax'] = number(self.gmax.text(), 'gmax', positive=True)
            # The adapter retains these MPB-only values in normalized requests.
            # Preserve valid imported values without blocking Legume on inactive drafts.
            for key, widget, criteria in [('resolution', self.resolution, dict(integer=True, minimum=2)),
                    ('tolerance', self.tolerance, dict(positive=True)), ('mesh_size', self.mesh_size, dict(integer=True, minimum=1))]:
                try:
                    cfg[key] = number(widget.text(), key, **criteria)
                except FieldError:
                    pass
        if self.reference_length.text().strip():
            cfg['reference_length_um'] = number(self.reference_length.text(), 'reference_length_um', positive=True, units='µm')
        sampling = self.sampling.currentData()
        if sampling == 'grid':
            cfg['k_grid'] = {'counts': [number(v, 'k_grid.counts', integer=True, minimum=1) for v in self.grid_counts.text().replace(',', ' ').split()],
                             'offset': vector(self.grid_offset.text(), dim, 'k_grid.offset')}
            if len(cfg['k_grid']['counts']) != dim:
                raise FieldError('k_grid.counts', 'Supply one grid count per dimension.')
        else:
            key = 'k_vertices' if sampling == 'path' else 'k_points'
            cfg[key] = [[number(v, f'{key}.{i}.{j}') for j, v in enumerate(row[:dim])] for i, row in enumerate(_rows(self.kpoints))]
            if len(cfg[key]) < (2 if sampling == 'path' else 1):
                raise FieldError(key, 'Supply at least two path vertices or one explicit k point.')
            if sampling == 'path' and any(a == b for a, b in zip(cfg[key], cfg[key][1:])):
                raise FieldError(key, 'Adjacent k-path vertices must be distinct.')
            if sampling == 'path':
                cfg['points_per_segment'] = number(self.points_per_segment.text(), 'points_per_segment', integer=True, minimum=1)
        if self.levels.text().strip():
            cfg['resolution_levels' if solver == 'mpb' else 'gmax_levels'] = [number(v, 'convergence.levels', positive=True, integer=solver == 'mpb')
                 for v in self.levels.text().replace(',', ' ').split()]
        if self.frequency_tolerance.text().strip():
            cfg['frequency_tolerance'] = number(self.frequency_tolerance.text(), 'frequency_tolerance', positive=True, units='a/λ')
        parameters = {}
        for row, identity in zip(_rows(self.sweeps), self._sweep_targets):
            parameter, _, field, raw = row
            if not parameter.strip():
                raise FieldError('parameter_sweep', 'Give each sweep parameter a nonempty ID.')
            values = [number(value, 'parameter_sweep') for value in raw.replace(',', ' ').split()]
            if not values:
                raise FieldError('parameter_sweep', 'Supply explicit values for every sweep parameter.')
            if identity and identity not in self._object_ids:
                raise FieldError('parameter_sweep', 'A sweep target was removed. Remove or replace its parameter target.')
            target = dict(field=field.strip())
            if identity:
                target['object_id'] = identity
            entry = parameters.setdefault(parameter, dict(id=parameter, targets=[], values=values))
            if entry['values'] != values:
                raise FieldError('parameter_sweep', 'Linked targets with the same parameter ID must use identical values.')
            entry['targets'].append(target)
        if parameters:
            cfg['parameter_sweep'] = dict(parameters=list(parameters.values()))
        return dict(engine='photonic_bands', study='band_structure', settings=cfg)

    def runtime_settings(self):
        """Read runtime independently so unfinished geometry cannot block a reference run."""
        solver = self.solver.currentData()
        required = [('runtime.executable', self.executable)]
        if self.runtime_mode.currentData() == 'wsl':
            required.append(('runtime.distro', self.distro))
        for key, widget in required:
            text = widget.text().strip()
            if not text or text.startswith('-') or any(c in text for c in '\r\n\0'):
                raise FieldError(key, 'Enter an explicit runtime '+key.split('.')[-1]+'.')
        if solver == 'mpb' and sys.platform == 'win32' and self.runtime_mode.currentData() == 'local':
            raise FieldError('runtime.mode', 'The MPB executable adapter on Windows requires WSL.')
        if solver == 'legume' and self.runtime_mode.currentData() == 'wsl' and not self.executable.text().strip().startswith('/'):
            raise FieldError('runtime.executable', 'WSL requires an absolute Linux Python path for Legume.')
        runtime = dict(mode=self.runtime_mode.currentData(), distro=self.distro.text(), executable=self.executable.text(),
                       timeout_s=number(self.timeout.text(), 'runtime.timeout_s', positive=True, units='s'))
        if solver == 'legume':
            runtime['module_paths'] = [path.strip() for path in self.module_paths.text().split(';') if path.strip()]
            if self.library_paths.text().strip():
                runtime['library_paths'] = [path.strip() for path in self.library_paths.text().split(';') if path.strip()]
        return runtime

    def open_diagnostic(self, target):
        if target.get('workspace') not in (None, '', self.workspace_id):
            return super().open_diagnostic(target)
        field = target.get('field', '').removeprefix('settings.')
        if getattr(self, '_workflow_ready', False):
            if field == 'background_epsilon':
                self.show_stage('build')
                return reveal_and_focus(self.compact_background if self.width() < 1100 else self.background, message=target.get('message', ''))
            if field in ('dimension', 'reference_length_um', 'physical_scale_nm', 'lattice_vectors') or field.startswith('lattice_vectors.'):
                self.show_stage('unit')
                if field.startswith('lattice_vectors'): self.unit_custom_toggle.setChecked(True)
                if field in ('reference_length_um', 'physical_scale_nm'):
                    return reveal_and_focus(self.scale_nm, message=target.get('message', ''))
            if field.startswith('runtime.'):
                self.show_stage('calculate'); self.runtime_setup_toggle.setChecked(True)
        if field in ('dimension', 'reference_length_um', 'lattice_vectors') or field.startswith('lattice_vectors.'):
            self.lattice_details_toggle.setChecked(True)
        if field in ('tolerance', 'mesh_size', 'runtime.timeout_s', 'runtime.module_paths', 'runtime.library_paths'):
            self.advanced_solver_toggle.setChecked(True)
        identity = target.get('object_id', '')
        if identity:
            if identity not in self._object_ids:
                self.validate_inputs()
                self.status.setText('That primitive was removed. The missing-input list has been refreshed.')
                return False
            row = self._object_ids.index(identity)
            name = next((part for part in field.split('.') if part in (*self.geometry_columns, 'epsilon')), field.rsplit('.', 1)[-1])
            self.select_section('Crystal structure')
            column = self.geometry_columns.index(name) if name in self.geometry_columns else 0
            self.geometry.setCurrentCell(row, column)
            self._refresh_inspector()
            widget = self.primitive_shape if name == 'shape' else self.primitive_fields.get(name, self.primitive_fields['name'])
            if name in self.primitive_fields:
                self._form_row_visible(self.primitive_form, widget, True)
            if isinstance(widget, _CartesianInput):
                parts = field.split('.')
                component = int(parts[-1]) if parts[-1].isdigit() else 0
                widget = widget.focus_component(component)
            return reveal_and_focus(widget, message=target.get('message', ''))
        for prefix, table in [('lattice_vectors', self.lattice), ('k_vertices', self.kpoints), ('k_points', self.kpoints)]:
            if field.startswith(prefix+'.'):
                parts = field.split('.')
                try:
                    row, column = int(parts[1]), int(parts[2]) if len(parts) > 2 else 0
                except ValueError:
                    break
                if 0 <= row < table.rowCount() and 0 <= column < table.columnCount():
                    if table is self.lattice:
                        self.custom_vectors_toggle.setChecked(True)
                    table.setCurrentCell(row, column)
                    return reveal_and_focus(table, message=target.get('message', ''))
        if field == 'lattice_vectors':
            self.custom_vectors_toggle.setChecked(True)
        if field in ('resolution_levels', 'gmax_levels'):
            target = dict(target, field='convergence.levels')
        return super().open_diagnostic(target)

    def review_inputs(self):
        try:
            request = self.options()
            cfg = request['settings']
            self.review.setPlainText(json.dumps(request, indent=2, ensure_ascii=False))
            if not hasattr(self, 'review_summary'):
                return
            objects = ''.join('<li>'+escape(obj['name'] or obj['shape'])+' · '+escape(obj['shape'])+
                f' · εr {obj["epsilon"]:g} (n ≈ {np.sqrt(obj["epsilon"]):.4g})</li>' for obj in cfg['geometry']) or '<li>Uniform background (no objects)</li>'
            samples = ('Full reciprocal-cell grid: '+ ' × '.join(map(str, cfg['k_grid']['counts']))) if 'k_grid' in cfg else (
                str(len(cfg.get('k_vertices', cfg.get('k_points', []))))+(' path vertices, '+str(cfg['points_per_segment'])+' intervals per segment' if 'k_vertices' in cfg else ' explicit points'))
            accuracy = ('Grid '+str(cfg['resolution'])+' points per lattice direction') if cfg['solver'] == 'mpb' else 'Reciprocal cutoff gmax '+str(cfg['gmax'])
            optional = []
            if 'parameter_sweep' in cfg: optional.append(str(len(cfg['parameter_sweep']['parameters']))+' sweep parameters')
            levels = cfg.get('resolution_levels', cfg.get('gmax_levels'))
            if levels: optional.append('Accuracy levels: '+', '.join(map(str, levels)))
            scale = str(cfg['reference_length_um'])+' µm' if 'reference_length_um' in cfg else 'Normalized units only'
            self.review_summary.setHtml('<h2>Ready to check and calculate</h2><p>Checking inputs verifies the setup. The installed solver is checked when the calculation starts.</p>'+
                '<h3>Crystal</h3><p>'+str(cfg['dimension'])+'D periodic domain · scale a: '+escape(scale)+
                f' · background εr {cfg["background_epsilon"]:g}</p><ul>'+objects+'</ul><h3>Calculation</h3><p>'+escape(samples)+
                '<br>'+escape(cfg['solver'].upper())+' · '+str(cfg['num_bands'])+' lowest bands · '+escape(', '.join(cfg['polarizations']).upper())+
                '<br>'+escape(accuracy)+'<br>Run on '+escape(cfg['runtime']['mode'].upper())+' · '+escape(cfg['runtime']['executable'])+'</p>'+
                ('<h3>Additional studies</h3><p>'+escape(' · '.join(optional))+'</p>' if optional else '')+
                '<h3>Saved results</h3><p>Band diagram, frequency tables, exact inputs and solver log. Frequency is a/λ. Reported gaps are sampled gaps; a finite path or grid does not prove a complete gap.</p>')
        except ValueError as exc:
            self.review.setPlainText('The draft is preserved. Resolve this input to construct the solver request:\n'+str(exc))
            if hasattr(self, 'review_summary'):
                self.review_summary.setHtml('<h2>One input needs attention</h2><p>'+escape(str(exc))+'</p><p>Your draft is preserved. Choose <b>Check inputs</b>, then click the issue to go directly to its field.</p>')

    def preview_geometry(self):
        try:
            dim, vectors, objects = self._geometry_inputs(materials=False)
            if hasattr(self, 'crystal_3d') and dim == 3:
                for obj in objects:
                    try:
                        epsilon = float(self._epsilons.get(obj['id'], ''))
                        if np.isfinite(epsilon) and epsilon > 0: obj['epsilon'] = epsilon
                    except ValueError: pass
                try: background = float(self.background.text())
                except ValueError: background = 1.
                if not np.isfinite(background) or background <= 0: background = 1.
                row = self.geometry.currentRow()
                selected = self._object_ids[row] if 0 <= row < len(self._object_ids) else ''
                self.crystal_3d.set_crystal(dict(dimension=3, lattice_vectors=vectors, geometry=objects, background_epsilon=background), selected_id=selected)
                self.scene_stack.setCurrentWidget(self.crystal_3d)
                self.preview_note.setText('Primitive geometry preview · Repeat cells to inspect periodic neighbors.')
                self.preview_note.setToolTip('Periodic copies enter the cell across its boundaries. Overlapping surfaces are not a Boolean-resolved material mesh; the solver applies its material precedence rules.')
                return
            if hasattr(self, 'scene_stack'): self.scene_stack.setCurrentWidget(self.preview)
            lattice = np.asarray(vectors)
            figure = Figure(figsize=(7, 4), layout='constrained')
            axis = figure.add_subplot(111)
            cell = _xy_hull(np.asarray(list(product([-.5, .5], repeat=dim)))@lattice)
            axis.add_patch(Polygon(cell, fill=False, linewidth=2))
            for obj in objects:
                center = np.asarray(obj['center'][:2])
                if obj['shape'] in ('circle', 'sphere'):
                    axis.add_patch(Circle(center, obj['radius'], alpha=.4))
                elif obj['shape'] == 'block':
                    axes = np.asarray(obj['axes'])
                    norms = np.linalg.norm(axes, axis=1)
                    if np.any(norms == 0):
                        continue
                    vertices = np.asarray(list(product([-.5, .5], repeat=dim)))*np.asarray(obj['size'])
                    projected = _xy_hull(vertices@(axes/norms[:, None])+np.asarray(obj['center']))
                    axis.add_patch(Polygon(projected, alpha=.4))
                else:
                    axis.plot(*center, marker='x')
                axis.text(*center, obj['name'], fontsize=8)
            axis.set_aspect('equal', adjustable='box')
            axis.set_box_aspect(1)
            axis.autoscale_view()
            extent = np.vstack([cell, *[np.asarray(obj['center'][:2])[None, :] for obj in objects]])
            low, high = extent.min(axis=0), extent.max(axis=0)
            width = max(float(np.max(high-low)), 1e-6)*1.15
            center = (high+low)/2
            axis.set_xlim(center[0]-width/2, center[0]+width/2)
            axis.set_ylim(center[1]-width/2, center[1]+width/2)
            axis.set_xlabel('x / a')
            axis.set_ylabel('y / a')
            axis.grid(True, alpha=.2)
            self.preview.draw_figure(figure)
            self.preview_note.setText('Geometry sketch · '+('2D cell. Periodic copies are omitted.' if dim == 2 else
                'XY projection only. Spheres appear as circles; cylinders are center markers. Z extents and periodic copies are omitted.')+
                ' This is not a field solution.')
        except ValueError as exc:
            self.preview_note.setText('Preview is out of date; the last valid geometry is shown. '+str(exc)+' Your draft is preserved.')

    def load_settings(self, cfg):
        """Load explicit canonical settings into editable fields; never infer device geometry."""
        from photonic_bands import prepare
        prepare({}, cfg)
        self._loading = True
        try:
            self.restore_draft(self._default_draft)
            dim = cfg.get('dimension', 2)
            for key in ('dimension', 'solver'):
                value = cfg.get(key, 2 if key == 'dimension' else 'mpb')
                self.fields[key].setCurrentIndex(self.fields[key].findData(value))
            for key in ('background_epsilon', 'num_bands', 'resolution', 'gmax', 'tolerance', 'mesh_size', 'points_per_segment', 'reference_length_um'):
                if key in cfg:
                    self.fields[key].setText(str(cfg[key]))
            runtime = cfg.get('runtime', {})
            for key in ('distro', 'executable', 'timeout_s'):
                if key in runtime:
                    self.fields['runtime.'+key].setText(str(runtime[key]))
            if 'mode' in runtime:
                self.runtime_mode.setCurrentIndex(self.runtime_mode.findData(runtime['mode']))
            self.module_paths.setText('; '.join(runtime.get('module_paths', [])))
            self.library_paths.setText('; '.join(runtime.get('library_paths', [])))
            lattice = [list(row)+[0]*(3-len(row)) for row in cfg['lattice_vectors'][:dim]]
            if dim == 2:
                lattice.append([0, 0, 1])
            _fill(self.lattice, lattice)
            objects = cfg.get('geometry', [])
            self._object_ids = [obj.get('id') or uuid.uuid4().hex for obj in objects]
            self._epsilons = {identity: str(obj['epsilon']) for identity, obj in zip(self._object_ids, objects)}
            rows = []
            join = lambda values: ', '.join(str(v) for v in values)
            for obj in objects:
                rows.append([obj.get('name', obj['shape']), obj['shape'], join(obj.get('center', [0]*dim)[:dim]),
                    str(obj.get('radius', '.2')), join(obj.get('size', [.4]*dim)[:dim]), str(obj.get('height', '.4')),
                    join(obj.get('axis', [0, 0, 1])), '; '.join(join(v[:dim]) for v in obj.get('axes', np.eye(dim).tolist())[:dim])])
            _fill(self.geometry, rows)
            self._sync_materials()
            mode = 'grid' if 'k_grid' in cfg else 'points' if 'k_points' in cfg else 'path'
            self.sampling.setCurrentIndex(self.sampling.findData(mode))
            if mode == 'grid':
                self.grid_counts.setText(join(cfg['k_grid']['counts']))
                self.grid_offset.setText(join(cfg['k_grid'].get('offset', [0]*dim)))
            else:
                _fill(self.kpoints, [list(row)+[0]*(3-len(row)) for row in cfg['k_points' if mode == 'points' else 'k_vertices']])
            self.te.setChecked('te' in cfg.get('polarizations', ['te', 'tm']))
            self.tm.setChecked('tm' in cfg.get('polarizations', ['te', 'tm']))
            self.levels.setText(join(cfg.get('resolution_levels', cfg.get('gmax_levels', []))))
            self.frequency_tolerance.setText(str(cfg.get('frequency_tolerance', '')))
            sweep_rows, self._sweep_targets = [], []
            names = {identity: obj.get('name', obj['shape']) for identity, obj in zip(self._object_ids, objects)}
            for param in cfg.get('parameter_sweep', {}).get('parameters', []):
                for target in param['targets']:
                    identity = target.get('object_id', '')
                    self._sweep_targets.append(identity)
                    sweep_rows.append([param['id'], names.get(identity, 'Global lattice / background'), target['field'], join(param['values'])])
            _fill(self.sweeps, sweep_rows)
            self._dimension_changed(); self._solver_changed(); self._sampling_changed()
        finally:
            self._loading = False
        self.save_draft()
        self.select_section('Crystal structure')
        self.geometry.setCurrentCell(0, 0)
        self._refresh_inspector()
        self._clear_path_labels()
        self._lattice_summary()
        self._queue_preview()

        self._mark_custom_crystal()

    def import_settings(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import editable periodic-domain settings', '', 'JSON (*.json)')
        if path:
            try:
                with open(path, encoding='utf-8') as stream:
                    value = json.load(stream)
                self.load_settings(value.get('settings', value))
            except (ValueError, OSError, KeyError) as exc:
                self.status.setText('Could not import settings: '+str(exc))

    def export_settings(self):
        try:
            value = self.options()
        except ValueError as exc:
            self.diagnostics.set_diagnostics([self._issue(exc)], workspace=self.workspace_id)
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export editable periodic-domain settings', 'photonic-bands.json', 'JSON (*.json)')
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as stream:
                    json.dump(value, stream, indent=2, allow_nan=False)
            except OSError as exc:
                self.status.setText('Could not export settings: '+str(exc))

    def refresh_benchmarks(self):
        self.benchmark_picker.clear()
        try:
            from benchmark_registry import list_benchmarks
            for item in list_benchmarks():
                if item.get('family') in ('photonic_bands', 'photonic', 'bands') or item.get('engine') == 'photonic_bands':
                    self.benchmark_picker.addItem(item.get('label', item['id']), item['id'])
        except (ImportError, OSError, ValueError):
            pass
        self.benchmark_note.setText('Select a versioned reference case.' if self.benchmark_picker.count() else
            'No band reference is currently installed. You can still define and run an editable crystal or compare explicit reference data.')

    def duplicate_benchmark(self):
        identity = self.benchmark_picker.currentData()
        if not identity:
            return
        try:
            from benchmark_registry import editable_copy
            case = editable_copy(identity)
            settings = deepcopy(case['options']['settings'])
            if settings.get('solver', 'mpb') == self.solver.currentData():
                settings['runtime'] = self.runtime_settings()
            self.load_settings(settings)
            self.attach_benchmark(case)
            self.benchmark_note.setText('Reference copied into editable settings. The immutable reference remains unchanged.')
        except (ValueError, KeyError, OSError) as exc:
            self.benchmark_note.setText(str(exc))

    def run_benchmark(self):
        identity = self.benchmark_picker.currentData()
        if not identity or self.store.busy:
            return
        try:
            self._owns_run = True
            from benchmark_registry import load_benchmark
            if load_benchmark(identity)['options']['settings'].get('solver', 'mpb') != self.solver.currentData():
                raise FieldError('solver', 'Select the reference solver and configure its runtime before running this reference.')
            self.store.start_benchmark(identity, runtime=self.runtime_settings())
        except Exception as exc:
            self._owns_run = False
            self.benchmark_note.setText(str(exc))
