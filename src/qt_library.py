"""Native saved-work browser with portable project and library sharing."""
from pathlib import Path
import json
import shutil

import pandas as pd
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QComboBox,
    QLineEdit, QPlainTextEdit, QPushButton, QCheckBox, QFileDialog, QTabWidget, QSplitter,
)

from data_library import read_json
from library_ui import saved_entry_choices, csv_choices, saved_design_choices
from qt_common import PlotWidget
from qt_materials import choices, group, make_table, show_frame, readable_form


class LibraryPage(QWidget):
    """Browse existing Gradio data and new desktop data without conversion."""
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._entries = []
        self._pending = None
        self._csv_path = None
        self._export_path = None
        root = QVBoxLayout(self)
        title = QLabel('Saved work')
        title.setObjectName('pageTitle')
        root.addWidget(title)
        lead = QLabel('Reopen a saved structure, inspect every result, or share the complete application and its material data.')
        lead.setWordWrap(True)
        lead.setObjectName('muted')
        root.addWidget(lead)
        files = QHBoxLayout()
        self.open_project_button = QPushButton('Open project JSON')
        self.save_project_button = QPushButton('Save current project')
        self.refresh_button = QPushButton('Refresh library')
        files.addWidget(self.open_project_button)
        files.addWidget(self.save_project_button)
        files.addStretch()
        files.addWidget(self.refresh_button)
        root.addLayout(files)
        controls, controls_body = group('Find saved work')
        filters = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText('Search titles, notes, status, or run IDs…')
        self.query.setClearButtonEnabled(True)
        self.kind = QComboBox()
        self.kind.addItem('All types', '')
        self.run_status = QComboBox()
        self.run_status.addItem('All statuses', '')
        controls_body.addWidget(self.query)
        filters.addWidget(self.kind)
        filters.addWidget(self.run_status)
        filters.addStretch()
        controls_body.addLayout(filters)
        self.selection = QComboBox()
        self.selection.setAccessibleName('Saved run or project')
        controls_body.addWidget(self.selection)
        self.selection.hide()
        self.entry_list = make_table(['Name', 'Type', 'Status'])
        controls_body.addWidget(self.entry_list, 1)
        self.entry_list.cellClicked.connect(self.select_entry_row)
        restore = QVBoxLayout()
        self.design = QComboBox()
        self.design.setAccessibleName('Saved setup to reopen')
        self.restore = QPushButton('Reopen in Structure')
        self.restore.setProperty('primary', True)
        restore.addWidget(self.design, 1)
        restore.addWidget(self.restore)
        controls_body.addLayout(restore)
        self.browser_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.browser_splitter.setChildrenCollapsible(False)
        self.browser_splitter.addWidget(controls)
        root.addWidget(self.browser_splitter, 1)
        self.tabs = QTabWidget()
        self.browser_splitter.addWidget(self.tabs)
        self.browser_splitter.setSizes([480, 680])
        self._build_results()
        self._build_details()
        self._build_sharing()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.status)
        self.query.textChanged.connect(self.filter_entries)
        self.kind.currentIndexChanged.connect(self.filter_entries)
        self.run_status.currentIndexChanged.connect(self.filter_entries)
        self.selection.currentIndexChanged.connect(self.inspect)
        self.design.currentIndexChanged.connect(self._actions)
        self.restore.clicked.connect(self.restore_project)
        self.csv.currentIndexChanged.connect(self.preview)
        self.refresh_button.clicked.connect(self.refresh)
        self.open_project_button.clicked.connect(self.open_project)
        self.save_project_button.clicked.connect(self.save_project)
        store.library_changed.connect(self.refresh)
        store.busy_changed.connect(self._actions)
        store.task_finished.connect(self.task_finished)
        store.task_failed.connect(self.task_failed)
        self.refresh()

    def _build_results(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.csv = QComboBox()
        self.csv.setAccessibleName('Saved result to view')
        self.copy_csv = QPushButton('Save complete CSV as…')
        self.copy_csv.clicked.connect(self.save_csv)
        row.addWidget(self.csv, 1)
        row.addWidget(self.copy_csv)
        layout.addLayout(row)
        self.plot = PlotWidget()
        self.plot.setMinimumHeight(350)
        layout.addWidget(self.plot, 1)
        self.table = make_table()
        self.table.setMinimumHeight(190)
        layout.addWidget(self.table, 1)
        description = QLabel('The table previews up to 5,000 rows. Save the complete CSV to retain every data point.')
        description.setWordWrap(True)
        layout.addWidget(description)
        self.tabs.addTab(page, 'Results')

    def _build_details(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = readable_form()
        self.title_edit = QLineEdit()
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(110)
        form.addRow('Run title', self.title_edit)
        form.addRow('Notes', self.notes)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.save_notes = QPushButton('Save title & notes')
        self.save_notes.clicked.connect(self.rename)
        self.open_folder = QPushButton('Open saved-run folder')
        self.open_folder.clicked.connect(self.open_run_folder)
        row.addWidget(self.save_notes)
        row.addWidget(self.open_folder)
        row.addStretch()
        layout.addLayout(row)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 1)
        storage = QLabel('Storage folder: ' + str(self.store.library.root))
        storage.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        storage.setWordWrap(True)
        layout.addWidget(storage)
        self.tabs.addTab(page, 'Details & notes')

    def _build_sharing(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        box, body = group('Back up or share your work')
        text = QLabel('Whole-library backups contain every saved run, material preset, and optical-constant table. Include the application to share a runnable code set. Importing a bundle merges its data and keeps existing entries.')
        text.setWordWrap(True)
        body.addWidget(text)
        self.include_source = QCheckBox('Include application source and bundled runtime')
        self.include_source.setChecked(True)
        body.addWidget(self.include_source)
        self.export_all = QPushButton('Export whole library…')
        self.export_all.setProperty('primary', True)
        self.export_one = QPushButton('Export selected saved run…')
        self.import_button = QPushButton('Import a library ZIP…')
        self.open_export = QPushButton('Show exported file')
        self.open_export.setEnabled(False)
        self.export_all.clicked.connect(lambda: self.export_bundle(False))
        self.export_one.clicked.connect(lambda: self.export_bundle(True))
        self.import_button.clicked.connect(self.import_bundle)
        self.open_export.clicked.connect(self.show_export)
        body.addWidget(self.export_all)
        body.addWidget(self.export_one)
        body.addWidget(self.import_button)
        body.addWidget(self.open_export)
        layout.addWidget(box)
        layout.addStretch()
        self.tabs.addTab(page, 'Back up & share')

    def _actions(self, *_):
        idle = not self.store.busy
        selected = self.selection.currentData() is not None
        self.restore.setEnabled(idle and selected and self.design.currentData() is not None)
        self.save_notes.setEnabled(idle and selected)
        self.open_folder.setEnabled(selected)
        self.copy_csv.setEnabled(self._csv_path is not None)
        self.export_one.setEnabled(idle and selected)
        for widget in (self.export_all, self.import_button, self.open_project_button, self.save_project_button):
            widget.setEnabled(idle)

    def refresh(self, *_):
        message = self.status.text()
        self._entries = self.store.library.entries()
        choices(self.kind, [('All types', '')] + [(value, value) for value in sorted({item.get('kind', '') for item in self._entries if item.get('kind')})])
        choices(self.run_status, [('All statuses', '')] + [(value, value) for value in sorted({item.get('status', '') for item in self._entries if item.get('status')})])
        self.filter_entries()
        if message:
            self.status.setText(message)

    def filter_entries(self, *_):
        query = self.query.text().strip().lower()
        entries = [item for item in self._entries if (not self.kind.currentData() or item.get('kind') == self.kind.currentData()) and (not self.run_status.currentData() or item.get('status') == self.run_status.currentData()) and query in json.dumps(item, ensure_ascii=False).lower()]
        choices(self.selection, saved_entry_choices(entries))
        self._visible_entries = [self.selection.itemData(i) for i in range(self.selection.count())]
        by_id = {entry['id']: entry for entry in entries}
        rows = [{'Name': by_id.get(identifier, {}).get('title') or identifier,
                 'Type': by_id.get(identifier, {}).get('kind', ''),
                 'Status': by_id.get(identifier, {}).get('status', '')} for identifier in self._visible_entries]
        show_frame(self.entry_list, pd.DataFrame(rows, columns=['Name', 'Type', 'Status']))
        if self.selection.currentIndex() >= 0:
            self.entry_list.selectRow(self.selection.currentIndex())
        self.inspect()

    def select_entry_row(self, row, column=0):
        if 0 <= row < self.selection.count():
            self.selection.setCurrentIndex(row)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.browser_splitter.setOrientation(Qt.Orientation.Vertical if self.width() < 900 else Qt.Orientation.Horizontal)

    def inspect(self, *_):
        identifier = self.selection.currentData()
        if not identifier:
            choices(self.design, [])
            choices(self.csv, [])
            self.title_edit.clear()
            self.notes.clear()
            self.details.clear()
            self.status.setText('No matching saved work. Completed simulations and searches appear here automatically.')
            self.preview()
            self._actions()
            return
        try:
            directory = self.store.library.directory(identifier)
            record = next((item for item in self._entries if item['id'] == identifier), {})
            files = [path.relative_to(directory).as_posix() for path in directory.rglob('*') if path.is_file() and not path.is_symlink()]
            csvs = [name for name in files if name.lower().endswith('.csv')]
            preferred = next((name for name in ('target_results.csv', 'design_results.csv', 'results.csv', 'best_spectrum.csv') if name in csvs), csvs[0] if csvs else None)
            choices(self.csv, csv_choices(csvs), preferred)
            choices(self.design, saved_design_choices(directory))
            self.title_edit.setText(str(record.get('title', identifier)))
            self.notes.setPlainText(str(record.get('notes', '')))
            details = dict(record=record, files=sorted(files))
            for name in ('search_summary.json', 'diagnostics.json'):
                if (directory / name).is_file():
                    try:
                        details[name] = read_json(directory / name)
                    except (OSError, ValueError):
                        details[name] = 'Unable to read this metadata file.'
            self.details.setPlainText(json.dumps(details, indent=2, ensure_ascii=False))
            self.status.setText(f'{len(files):,} saved files. Reopen a setup to load its materials, layers, and calculation settings.')
            self.preview()
        except Exception as exc:
            choices(self.design, [])
            choices(self.csv, [])
            self.preview()
            self.status.setText('Unable to inspect saved work: ' + str(exc))
        self._actions()

    def result_path(self):
        directory = self.store.library.directory(self.selection.currentData())
        filename = self.csv.currentData()
        if not filename:
            raise ValueError('Select a saved result CSV.')
        path = (directory / filename).resolve()
        if not path.is_relative_to(directory) or path.suffix.lower() != '.csv' or not path.is_file():
            raise ValueError('Select a CSV inside this saved run.')
        return path

    def preview(self, *_):
        self._csv_path = None
        if not self.csv.currentData():
            self.plot.clear()
            show_frame(self.table, pd.DataFrame())
            self._actions()
            return
        try:
            path = self.result_path()
            data = pd.read_csv(path, nrows=5000)
            self._csv_path = path
            show_frame(self.table, data)
            figure = self.plot.figure
            figure.clear()
            axis = figure.add_subplot(111)
            x = 'wavelength_nm' if 'wavelength_nm' in data else None
            if 'angle_deg' in data and data.angle_deg.nunique() > 1 and (not x or data[x].nunique() <= 1):
                x = 'angle_deg'
            ys = [name for name in ('R', 'T', 'A') if name in data]
            if x and ys and not data.empty:
                for name, color in zip(ys, ('#38a7ef', '#8d88ed', '#35bf9d')):
                    ordered = data[[x, name]].sort_values(x)
                    axis.plot(ordered[x], ordered[name], label=name, color=color, linewidth=1.8)
                axis.set(xlabel='Wavelength (nm)' if x == 'wavelength_nm' else 'Angle (degrees)', ylabel='Fraction', title=path.name)
                axis.legend()
                axis.grid(alpha=.2)
            else:
                axis.text(.5, .5, 'Numeric results are available in the table below.', ha='center', va='center', transform=axis.transAxes)
                axis.set_axis_off()
            figure.set_layout_engine('constrained')
            self.plot.draw_figure(figure)
        except Exception as exc:
            self.plot.clear()
            show_frame(self.table, pd.DataFrame())
            self.status.setText('Unable to preview result: ' + str(exc))
        self._actions()

    def restore_project(self):
        if self.store.busy:
            return
        try:
            identifier, design = self.selection.currentData(), self.design.currentData()
            if identifier is None or design is None:
                raise ValueError('Choose a saved setup to reopen.')
            project, search = self.store.library.project_for(identifier, int(design))
            if search:
                project['search'] = search
            self.store.load_project(project)
            self.status.setText('Loaded the saved materials, structure, and settings. Every calculation page now uses this structure.')
        except Exception as exc:
            self.status.setText('Unable to reopen setup: ' + str(exc))

    def rename(self):
        if self.store.busy:
            return
        try:
            identifier = self.selection.currentData()
            self.store.library.record(self.store.library.directory(identifier), title=self.title_edit.text().strip() or identifier, notes=self.notes.toPlainText())
            self.store.notify_library()
            self.status.setText('Saved the run title and notes.')
        except Exception as exc:
            self.status.setText('Unable to save notes: ' + str(exc))

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open S4 project', '', 'S4 project (*.json)')
        if path:
            try:
                self.store.load_project(path)
                self.status.setText('Project loaded into the shared Structure editor.')
            except Exception as exc:
                self.status.setText('Unable to load project: ' + str(exc))

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save portable S4 project', 's4_project.json', 'S4 project (*.json)')
        if path:
            try:
                self.store.save_project(path)
                self.status.setText('Saved portable project with its optical-constant data: ' + path)
            except Exception as exc:
                self.status.setText('Unable to save project: ' + str(exc))

    def save_csv(self):
        try:
            source = self.result_path()
            path, _ = QFileDialog.getSaveFileName(self, 'Save complete result CSV', source.name, 'CSV files (*.csv)')
            if path:
                if Path(path).resolve() != source.resolve():
                    shutil.copy2(source, path)
                self.status.setText('Saved complete result data: ' + path)
        except Exception as exc:
            self.status.setText('Unable to save CSV: ' + str(exc))

    def open_run_folder(self):
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.library.directory(self.selection.currentData()))))
        except Exception as exc:
            self.status.setText(str(exc))

    def export_bundle(self, selected=False):
        if self.store.busy:
            return
        identifier = self.selection.currentData() if selected else None
        if selected and not identifier:
            self.status.setText('Select a saved run before exporting it.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export S4 library', 's4_saved_run.zip' if selected else 's4_library.zip', 'ZIP archives (*.zip)')
        if not path:
            return
        if not selected:
            try:
                # Preserve the current applied design even if it has only been
                # autosaved; bundles intentionally do not replace desktop sessions.
                self.store.save_project()
            except Exception as exc:
                self.status.setText('Unable to save the active project for export: ' + str(exc))
                return
        from desktop_runtime import source_root
        source = source_root() if self.include_source.isChecked() and not selected else None
        library = self.store.library
        def export():
            generated = Path(library.export(identifier, source))
            if generated.resolve() != Path(path).resolve():
                shutil.copy2(generated, path)
            return dict(path=path)
        self._pending = 'library-export'
        self.status.setText('Exporting a verified library snapshot…')
        self.store.run_task(self._pending, export)

    def import_bundle(self):
        if self.store.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Import S4 library', '', 'ZIP archives (*.zip)')
        if not path:
            return
        library = self.store.library
        self._pending = 'library-import'
        self.status.setText('Verifying and merging the library bundle…')
        self.store.run_task(self._pending, lambda: library.import_bundle(path))

    def task_finished(self, name, result):
        if name != self._pending:
            return
        self._pending = None
        if name == 'library-import':
            self.store.notify_library()
            self.status.setText(f"Imported {result['runs']} saved entries, {result['presets']} presets, and {result['assets']} optical-constant tables. Existing work was retained.")
        else:
            self._export_path = result['path']
            self.open_export.setEnabled(True)
            self.status.setText('Library exported: ' + self._export_path)
        self._actions()

    def task_failed(self, name, error):
        if name == self._pending:
            self._pending = None
            self.status.setText('Library operation needs attention: ' + str(error))
            self._actions()

    def show_export(self):
        if self._export_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._export_path).parent)))
