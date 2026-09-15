"""Native material library, optical-constant import, and dispersion inspection."""
from pathlib import Path
import csv
import io
import textwrap

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QComboBox, QLineEdit, QPushButton, QLabel, QCheckBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog,
    QTabWidget, QPlainTextEdit, QSizePolicy, QMessageBox, QSplitter,
)

from model import MAT_COLS
from material_import_ui import import_csvs, save_manual, merge_material
from material_viewer import material_data
from qt_common import PlotWidget, CompactDoubleSpinBox
from refractiveindex_online import search_catalog, download_dataset


def choices(combo, values, selected=None):
    """Refresh semantic choices without firing selection callbacks mid-refresh."""
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(20)
    if selected is None:
        selected = combo.currentData()
    blocked = combo.blockSignals(True)
    combo.clear()
    for label, value in values:
        combo.addItem(str(label), value)
    index = combo.findData(selected)
    combo.setCurrentIndex(index if index >= 0 else (0 if values else -1))
    combo.blockSignals(blocked)


def make_table(headers=(), editable=False):
    view = QTableWidget(0, len(headers))
    view.setHorizontalHeaderLabels(list(headers))
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.verticalHeader().setVisible(False)
    # Keep columns readable; wide scientific result sets scroll horizontally.
    view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    view.horizontalHeader().setMinimumSectionSize(100)
    view.horizontalHeader().setStretchLastSection(True)
    view.verticalHeader().setDefaultSectionSize(34)
    view.setWordWrap(False)
    view.setMinimumHeight(160)
    if not editable:
        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    return view


def show_frame(view, data):
    frame = pd.DataFrame(data)
    view.setColumnCount(len(frame.columns))
    view.setHorizontalHeaderLabels([str(v) for v in frame.columns])
    view.setRowCount(len(frame))
    for r, row in enumerate(frame.itertuples(index=False, name=None)):
        for c, value in enumerate(row):
            text = '' if pd.isna(value) else (f'{value:.8g}' if isinstance(value, float) else str(value))
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            view.setItem(r, c, item)
    view.resizeColumnsToContents()
    for column in range(view.columnCount()):
        view.setColumnWidth(column, min(320, max(120, view.columnWidth(column))))


def readable_form(parent=None):
    form = QFormLayout(parent)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setHorizontalSpacing(18)
    form.setVerticalSpacing(12)
    return form


def spin(value, minimum=0, maximum=1e9, decimals=6):
    widget = CompactDoubleSpinBox()
    widget.setDecimals(decimals)
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    widget.setKeyboardTracking(False)
    return widget


def group(title):
    widget = QGroupBox(title)
    layout = QVBoxLayout(widget)
    layout.setSpacing(12)
    return widget, layout


class MaterialsPage(QWidget):
    """Edits the same material collection used by all calculation pages."""
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._presets = {}
        root = QVBoxLayout(self)
        title = QLabel('Materials')
        title.setObjectName('pageTitle')
        root.addWidget(title)
        lead = QLabel('Saved materials appear immediately in every layer and region material selector.')
        lead.setWordWrap(True)
        lead.setObjectName('muted')
        root.addWidget(lead)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        inspect = QWidget()
        inspect_layout = QVBoxLayout(inspect)
        self.inspect_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.inspect_splitter.setChildrenCollapsible(False)
        inspect_layout.addWidget(self.inspect_splitter)
        details_panel = QWidget()
        body = QVBoxLayout(details_panel)
        self.inspect_splitter.addWidget(details_panel)
        chart_panel = QWidget()
        chart_layout = QVBoxLayout(chart_panel)
        self.inspect_splitter.addWidget(chart_panel)
        self.inspect_splitter.setStretchFactor(0, 0)
        self.inspect_splitter.setStretchFactor(1, 1)
        self.inspect_splitter.setSizes([330, 760])
        self.selection = QComboBox()
        self.selection.setMinimumWidth(220)
        self.selection.setAccessibleName('Material to inspect')
        body.addWidget(self.selection)
        self.selection.hide()
        self.material_query = QLineEdit()
        self.material_query.setPlaceholderText('Search project materials and saved presets…')
        self.material_query.setClearButtonEnabled(True)
        body.addWidget(self.material_query)
        self.material_list = make_table(['Material', 'Source'])
        self.material_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        body.addWidget(self.material_list, 1)
        self.material_query.textChanged.connect(self.filter_materials)
        self.material_list.cellClicked.connect(self.select_material_row)
        top = QVBoxLayout()
        self.add_preset = QPushButton('Add to structure materials')
        self.remove = QPushButton('Remove from project')
        top.addWidget(self.add_preset)
        top.addWidget(self.remove)
        body.addLayout(top)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setTextFormat(Qt.TextFormat.PlainText)
        chart_layout.addWidget(self.description)
        self.range_box = QWidget()
        form = readable_form(self.range_box)
        form.setContentsMargins(0, 0, 0, 0)
        self.low, self.high = spin(800, .001), spin(2000, .001)
        limits = QHBoxLayout()
        limits.addWidget(self.low, 1)
        connector = QLabel('to')
        connector.setFixedWidth(24)
        connector.setAlignment(Qt.AlignmentFlag.AlignCenter)
        limits.addWidget(connector)
        limits.addWidget(self.high, 1)
        form.addRow('Display range for constants (nm)', limits)
        chart_layout.addWidget(self.range_box)
        self.plot = PlotWidget()
        self.plot.setMinimumHeight(280)
        chart_layout.addWidget(self.plot, 1)
        self.values = make_table(['wavelength_nm', 'n', 'k'])
        self.values.setMaximumHeight(210)
        chart_layout.addWidget(self.values)
        save_box, save_layout = group('Save material preset')
        save_form = readable_form()
        self.preset_name = QLineEdit()
        self.preset_name.setPlaceholderText('Optional display name')
        self.preset_notes = QLineEdit()
        self.preset_notes.setPlaceholderText('Dataset source, temperature, sample conditions…')
        save_form.addRow('Preset name', self.preset_name)
        save_form.addRow('Source & notes', self.preset_notes)
        save_layout.addLayout(save_form)
        self.save_preset = QPushButton('Save selected material to library')
        self.save_preset.setProperty('primary', True)
        save_layout.addWidget(self.save_preset)
        body.addWidget(save_box)
        self.tabs.addTab(inspect, 'Inspect & manage')
        self._build_online()
        self._build_import()
        self._build_manual()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.status)
        self.selection.currentIndexChanged.connect(self.draw)
        self.low.valueChanged.connect(self.draw)
        self.high.valueChanged.connect(self.draw)
        self.add_preset.clicked.connect(self.use_preset)
        self.remove.clicked.connect(self.remove_material)
        self.save_preset.clicked.connect(self.save_selected)
        store.changed.connect(self.refresh)
        store.library_changed.connect(self.refresh)
        store.busy_changed.connect(self._busy)
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        orientation = Qt.Orientation.Vertical if self.width() < 900 else Qt.Orientation.Horizontal
        if self.inspect_splitter.orientation() != orientation:
            self.inspect_splitter.setOrientation(orientation)
            self.inspect_splitter.setSizes([330, 760])
        if hasattr(self, 'online_splitter'):
            self.online_splitter.setOrientation(orientation)

    def _build_online(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        search_box, search_body = group('Search refractiveindex.info')
        row = QHBoxLayout()
        self.online_query = QLineEdit()
        self.online_query.setPlaceholderText('Material name or formula, for example Silicon or SiO2')
        self.online_search = QPushButton('Search refractiveindex.info')
        self.online_search.setProperty('primary', True)
        row.addWidget(self.online_query, 1)
        row.addWidget(self.online_search)
        search_body.addLayout(row)
        notice = QLabel('Search reads the public catalog only. No material files are downloaded.')
        notice.setWordWrap(True)
        search_body.addWidget(notice)
        layout.addWidget(search_box)
        results_box, results_body = group('Results')
        self.online_results = make_table(['Material', 'Dataset', 'Wavelength range', 'Reference'])
        self.online_results.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        results_body.addWidget(self.online_results)
        detail_box, detail_body = group('Selected dataset')
        self.online_details = QLabel('Search for a material, then select a dataset to review it.')
        self.online_details.setWordWrap(True)
        self.online_details.setTextFormat(Qt.TextFormat.PlainText)
        detail_body.addWidget(self.online_details)
        detail_body.addStretch()
        actions = QVBoxLayout()
        self.online_open = QPushButton('Open source page')
        self.online_download = QPushButton('Download & review…')
        self.online_download.setProperty('primary', True)
        actions.addWidget(self.online_open)
        actions.addWidget(self.online_download)
        detail_body.addLayout(actions)
        reminder = QLabel('Nothing downloads until you click Download & review… and confirm the import.')
        reminder.setWordWrap(True)
        detail_body.addWidget(reminder)
        self.online_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.online_splitter.setChildrenCollapsible(False)
        self.online_splitter.addWidget(results_box)
        self.online_splitter.addWidget(detail_box)
        self.online_splitter.setSizes([700, 330])
        layout.addWidget(self.online_splitter, 1)
        self._online_items = []
        self.online_search.clicked.connect(self.search_online)
        self.online_query.returnPressed.connect(self.search_online)
        self.online_results.itemSelectionChanged.connect(self.online_selection_changed)
        self.online_open.clicked.connect(self.open_online_source)
        self.online_download.clicked.connect(self.confirm_online_download)
        self.store.task_finished.connect(self._online_task_finished)
        self.store.task_failed.connect(self._online_task_failed)
        self.tabs.addTab(page, 'Find online')

    def _build_import(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        box, body = group('Import wavelength-dependent n and k')
        description = QLabel('Choose CSV or TXT files containing wavelength,n,k columns, or the separate n / k sections exported by refractiveindex.info. Each file is saved permanently and added to the material dropdowns.')
        description.setWordWrap(True)
        body.addWidget(description)
        form = readable_form()
        self.import_unit = QComboBox()
        self.import_unit.addItems(['nm', 'um'])
        self.import_name = QLineEdit()
        self.import_name.setPlaceholderText('Leave empty to use each filename')
        self.import_source = QLineEdit('https://refractiveindex.info/')
        self.missing_k = QCheckBox('Explicitly use k = 0 when the file has no k data')
        form.addRow('Wavelength unit in files', self.import_unit)
        form.addRow('Material name (one file only)', self.import_name)
        form.addRow('Dataset page / reference', self.import_source)
        body.addLayout(form)
        body.addWidget(self.missing_k)
        self.import_button = QPushButton('Choose files & import materials')
        self.import_button.setProperty('primary', True)
        self.import_button.clicked.connect(self.choose_csvs)
        body.addWidget(self.import_button)
        layout.addWidget(box)
        layout.addStretch()
        self.tabs.addTab(page, 'Import CSV')

    def _build_manual(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        box, body = group('Add material values')
        form = readable_form()
        self.manual_name = QLineEdit()
        self.manual_mode = QComboBox()
        self.manual_mode.addItems(['Wavelength-dependent n,k', 'Constant n,k (explicit approximation)'])
        self.manual_mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.manual_mode.setMinimumContentsLength(20)
        self.manual_mode.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.manual_unit = QComboBox()
        self.manual_unit.addItems(['nm', 'um'])
        self.manual_source = QLineEdit('https://refractiveindex.info/')
        form.addRow('Material name', self.manual_name)
        form.addRow('Wavelength dependence', self.manual_mode)
        form.addRow('Wavelength unit', self.manual_unit)
        form.addRow('Dataset page / conditions', self.manual_source)
        body.addLayout(form)
        self.manual_rows = make_table(['Wavelength', 'n', 'k'], editable=True)
        self.manual_rows.setRowCount(3)
        self.manual_rows.setMinimumHeight(200)
        body.addWidget(self.manual_rows)
        self.row_actions = QWidget()
        actions = QHBoxLayout(self.row_actions)
        actions.setContentsMargins(0, 0, 0, 0)
        add = QPushButton('Add wavelength row')
        add.clicked.connect(lambda: self.manual_rows.insertRow(self.manual_rows.rowCount()))
        paste = QPushButton('Paste wavelength, n, k rows')
        paste.clicked.connect(self.paste_rows)
        actions.addWidget(add)
        actions.addWidget(paste)
        actions.addStretch()
        body.addWidget(self.row_actions)
        self.constants = QWidget()
        values = readable_form(self.constants)
        self.n, self.k = spin(1.5, -1e6), spin(0, -1e6)
        values.addRow('Constant refractive index n', self.n)
        values.addRow('Constant extinction coefficient k', self.k)
        body.addWidget(self.constants)
        self.manual_save = QPushButton('Save material to project & library')
        self.manual_save.setProperty('primary', True)
        self.manual_save.clicked.connect(self.save_values)
        body.addWidget(self.manual_save)
        layout.addWidget(box)
        layout.addStretch()
        self.manual_mode.currentIndexChanged.connect(self._mode)
        self._mode()
        self.tabs.addTab(page, 'Enter values')

    def _mode(self, *_):
        dependent = self.manual_mode.currentIndex() == 0
        self.manual_rows.setVisible(dependent)
        self.manual_unit.setEnabled(dependent)
        self.row_actions.setVisible(dependent)
        self.constants.setVisible(not dependent)

    def _busy(self, busy):
        for widget in (self.import_button, self.manual_save, self.add_preset, self.remove, self.save_preset,
                       self.online_search, self.online_download):
            widget.setEnabled(not busy)
        if not busy:
            self._selection_actions()

    def search_online(self):
        query = self.online_query.text().strip()
        self.status.setText('Searching the public catalog only…')
        try:
            self.store.run_task('online-material-search', lambda: search_catalog(query))
        except Exception as exc:
            self.status.setText('Online search needs attention: ' + str(exc))

    def _online_task_failed(self, name, error):
        if name in ('online-material-search', 'online-material-download'):
            self.status.setText(('Online search needs attention: ' if name.endswith('search') else 'Download needs attention: ') + error)

    def _online_task_finished(self, name, value):
        if name == 'online-material-search':
            self._online_items = list(value)
            self.online_results.setRowCount(len(self._online_items))
            for r, result in enumerate(self._online_items):
                for c, text in enumerate((result['material'], result['dataset'], result['wavelength_range'], result['page_url'])):
                    self.online_results.setItem(r, c, QTableWidgetItem(str(text)))
            self.online_results.resizeColumnsToContents()
            self.status.setText(f'Found {len(value)} matching datasets. No material files were downloaded.')
            if value:
                self.online_results.selectRow(0)
        elif name == 'online-material-download':
            self._import_online(value)

    def _selected_online(self):
        row = self.online_results.currentRow()
        return self._online_items[row] if 0 <= row < len(self._online_items) else None

    def online_selection_changed(self):
        item = self._selected_online()
        if item:
            self.online_details.setText(f"{item['material']}\n{item['dataset']}\nWavelength range: {item['wavelength_range']}\nDataset page: {item['page_url']}")

    def open_online_source(self):
        item = self._selected_online()
        if item:
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(item['page_url']))

    def confirm_online_download(self):
        item = self._selected_online()
        if not item:
            self.status.setText('Select a dataset first.')
            return
        box = QMessageBox(self)
        box.setWindowTitle('Download material dataset?')
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"{item['material']}\n{item['dataset']}")
        box.setInformativeText('This explicit action downloads this one YAML dataset, validates it, and adds it to your project library. Searching did not download it.')
        download = box.addButton('Download and add to library', QMessageBox.ButtonRole.AcceptRole)
        box.addButton('Cancel', QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not download:
            return
        missing = QMessageBox.question(self, 'Missing extinction data',
            'If this dataset contains n but no k, explicitly treat missing k as 0 (lossless)?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
        self.status.setText('Downloading the selected dataset…')
        try:
            self.store.run_task('online-material-download', lambda: download_dataset(item, missing))
        except Exception as exc:
            self.status.setText('Download needs attention: ' + str(exc))

    def _import_online(self, package):
        item, rows = package['result'], package['rows']
        name = f"{item['material_id']} — {item['page']}"
        conditions = ', '.join(f'{key}: {value}' for key, value in package['conditions'].items())
        notes = (f"Source: {item['page_url']}\nDataset: {item['dataset']}\nReference: {package['reference']}"
                 + (f"\nComments: {package['comments']}" if package['comments'] else '')
                 + (f"\nConditions: {conditions}" if conditions else '')
                 + '\nRefractiveindex.info database: CC0 1.0. Download initiated and confirmed by the user.')
        try:
            from material_import_ui import store_table
            row, _ = store_table(self.store.library, name, rows, notes)
            self._apply(merge_material(self.store.materials, row), name,
                        f'Downloaded, validated {len(rows):,} n,k samples, and added {name} to the project library.')
        except Exception as exc:
            self.status.setText('Downloaded data could not be imported: ' + str(exc))

    def refresh(self, *_):
        self._presets = self.store.library.presets()
        values = [('Project · ' + str(row['Name']), 'project:' + str(row['Name'])) for row in self.store.materials.to_dict('records') if row.get('Name')]
        values += [('Built-in · ' + name, 'builtin:' + name) for name in self.store.context.PRESETS]
        values += [('Saved · ' + name, 'saved:' + name) for name in self._presets]
        choices(self.selection, values)
        self.filter_materials()
        self.draw()

    def filter_materials(self, *_):
        query = self.material_query.text().strip().casefold()
        self._visible_materials = [i for i in range(self.selection.count())
            if query in self.selection.itemText(i).casefold()]
        rows = []
        for index in self._visible_materials:
            source, _, name = self.selection.itemText(index).partition(' · ')
            rows.append({'Material': name, 'Source': source})
        show_frame(self.material_list, pd.DataFrame(rows, columns=['Material', 'Source']))
        self.material_list.horizontalHeader().setStretchLastSection(False)
        self.material_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.material_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        if self.selection.currentIndex() in self._visible_materials:
            self.material_list.selectRow(self._visible_materials.index(self.selection.currentIndex()))

    def select_material_row(self, row, column=0):
        if 0 <= row < len(self._visible_materials):
            self.selection.setCurrentIndex(self._visible_materials[row])

    def selected_row(self):
        key = self.selection.currentData() or ''
        kind, _, name = key.partition(':')
        if kind == 'project':
            row = next((row for row in self.store.materials.to_dict('records') if row['Name'] == name), None)
            return row, ''
        if kind == 'builtin' and name in self.store.context.PRESETS:
            return dict(zip(MAT_COLS, self.store.context.PRESETS[name])), 'Built-in constant approximation; no measured dispersion table is attached.'
        if kind == 'saved' and name in self._presets:
            entry = self._presets[name]
            return entry['project']['materials'][0], entry.get('notes', '')
        return None, ''

    def _in_use(self, name):
        return bool((self.store.layers['Material'] == name).any() or (self.store.patterns['Material'] == name).any())

    def _selection_actions(self):
        row, _ = self.selected_row()
        project = str(self.selection.currentData()).startswith('project:')
        busy = self.store.busy
        self.add_preset.setEnabled(bool(row) and not project and not busy)
        self.save_preset.setEnabled(bool(row) and project and not busy)
        used = bool(row) and self._in_use(row['Name'])
        self.remove.setEnabled(bool(row) and project and not used and not busy)
        self.remove.setToolTip('This material is used by a layer or region.' if used else 'Remove from this project; saved presets are retained.')

    def draw(self, *_):
        self._selection_actions()
        row, notes = self.selected_row()
        self.range_box.setVisible(bool(row) and row.get('Model') != 'table_nk')
        try:
            data, description, notes = material_data(self.store.library, (row, notes) if row else None, self.store.materials, self.store.files, self.low.value(), self.high.value())
            figure = self.plot.figure
            figure.clear()
            axes = figure.subplots(2, 1, sharex=True)
            for axis, column, color, label in zip(axes, ('n', 'k'), ('#38a7ef', '#edaa4f'), ('Refractive index\nn', 'Extinction coefficient\nk')):
                axis.plot(data.wavelength_nm, data[column], color=color, linewidth=2)
                axis.set_ylabel(label)
                axis.grid(alpha=.2)
                axis.ticklabel_format(axis='y', useOffset=False)
            axes[0].set_title(textwrap.fill(str(row['Name']), width=58))
            axes[1].set_xlabel('Wavelength (nm)')
            figure.set_layout_engine('constrained')
            self.plot.draw_figure(figure)
            show_frame(self.values, data.head(5000))
            self.description.setText(description + ('\n' + notes if notes else ''))
        except Exception as exc:
            self.plot.clear()
            show_frame(self.values, pd.DataFrame(columns=['wavelength_nm', 'n', 'k']))
            self.description.setText(str(exc))

    def _apply(self, frame, name, message):
        self.store.set_structure(frame, self.store.layers, self.store.patterns, reason='materials')
        self.store.notify_library()
        index = self.selection.findData('project:' + name)
        self.selection.setCurrentIndex(index)
        self.status.setText(message)

    def choose_csvs(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Import optical constants', '', 'Optical constants (*.csv *.txt);;All files (*)')
        if paths:
            self.import_paths(paths)

    def import_paths(self, paths):
        if self.store.busy:
            return
        try:
            result, key, message = import_csvs(self.store.library, self.store.materials, paths, self.import_unit.currentText(), self.missing_k.isChecked(), self.import_source.text(), self.import_name.text())
            name = self.store.library.presets()[key]['project']['materials'][0]['Name']
            self._apply(result, name, message)
        except Exception as exc:
            self.status.setText('Import needs attention: ' + str(exc))

    def paste_rows(self):
        try:
            text = QApplication.clipboard().text().strip()
            delimiter = '\t' if '\t' in text else ','
            rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
            if rows and rows[0][0].strip().lower() in ('wavelength', 'wavelength_nm', 'wl'):
                rows = rows[1:]
            if not rows or any(len(row) != 3 for row in rows):
                raise ValueError('Paste three columns: wavelength, n, k (tab or comma separated).')
            values = [[float(value) for value in row] for row in rows]
            show_frame(self.manual_rows, pd.DataFrame(values, columns=['Wavelength', 'n', 'k']))
            self.status.setText(f'Pasted {len(values)} rows. Save the material when its source and units are correct.')
        except Exception as exc:
            self.status.setText(str(exc))

    def save_values(self):
        if self.store.busy:
            return
        try:
            rows = []
            for r in range(self.manual_rows.rowCount()):
                row = [self.manual_rows.item(r, c).text().strip() if self.manual_rows.item(r, c) else '' for c in range(3)]
                if any(row):
                    rows.append([value or None for value in row])
            result, _, message = save_manual(self.store.library, self.store.materials, self.manual_name.text(), self.manual_mode.currentText(), self.manual_unit.currentText(), rows, self.n.value(), self.k.value(), self.manual_source.text())
            self._apply(result, self.manual_name.text().strip(), message)
        except Exception as exc:
            self.status.setText('Material needs attention: ' + str(exc))

    def use_preset(self):
        if self.store.busy:
            return
        try:
            row, _ = self.selected_row()
            if row is None:
                raise ValueError('Select a built-in or saved material first.')
            row = dict(row)
            existing = self.store.materials.to_dict('records')
            same = next((entry for entry in existing if entry['Name'] == row['Name']), None)
            if same is not None and any(str(same.get(k) or '') != str(row.get(k) or '') for k in MAT_COLS):
                names = {entry['Name'] for entry in existing}
                base, index = row['Name'], 2
                while row['Name'] in names:
                    row['Name'] = f'{base} {index}'
                    index += 1
            self._apply(merge_material(self.store.materials, row), row['Name'], f"{row['Name']} is available in every structure material selector.")
        except Exception as exc:
            self.status.setText(str(exc))

    def remove_material(self):
        if self.store.busy:
            return
        row, _ = self.selected_row()
        if row is None or not str(self.selection.currentData()).startswith('project:'):
            return
        if self._in_use(row['Name']):
            self.status.setText('Change the layers or regions that use this material before removing it.')
            return
        frame = self.store.materials[self.store.materials['Name'] != row['Name']].reset_index(drop=True)
        self.store.set_structure(frame, self.store.layers, self.store.patterns, reason='materials')
        self.status.setText(f"Removed {row['Name']} from the project. Saved presets remain available.")

    def save_selected(self):
        if self.store.busy:
            return
        try:
            row, _ = self.selected_row()
            if row is None:
                raise ValueError('Select a project material first.')
            self.store.library.save_preset(row, self.preset_name.text(), self.preset_notes.text(), self.store.files)
            self.store.notify_library()
            self.status.setText('Saved a permanent preset version with its optical-constant data.')
        except Exception as exc:
            self.status.setText('Unable to save preset: ' + str(exc))
