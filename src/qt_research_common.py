"""Shared, draft-preserving controls for the additional research workspaces."""
from __future__ import annotations

from copy import deepcopy
import math

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QComboBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QTabWidget, QTableWidget, QTreeWidget, QVBoxLayout, QWidget)

from qt_input_diagnostics import DiagnosticPanel, reveal_and_focus


class FieldError(ValueError):
    def __init__(self, field, message, object_id='', units=''):
        super().__init__(message)
        self.field, self.object_id, self.units = field, object_id, units


def number(value, field, *, positive=False, integer=False, minimum=None, units='', object_id=''):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        result = float('nan')
    if not math.isfinite(result) or (positive and result <= 0) or (integer and result != int(result)) or (minimum is not None and result < minimum):
        qualifier = 'positive ' if positive else ''
        qualifier += 'integer' if integer else 'number'
        if minimum is not None:
            qualifier += ' of at least '+str(minimum)
        raise FieldError(field, 'Enter a finite '+qualifier+'.', object_id, units)
    return int(result) if integer else result


def vector(value, dimension, field, *, positive=False, object_id=''):
    parts = str(value).replace(',', ' ').split() if isinstance(value, str) else value
    if not isinstance(parts, (list, tuple)) or len(parts) != dimension:
        raise FieldError(field, 'Enter '+str(dimension)+' comma-separated components.', object_id, 'a')
    return [number(v, field, positive=positive, object_id=object_id, units='a') for v in parts]


def label(text, name='setupMuted'):
    item = QLabel(text)
    item.setWordWrap(True)
    item.setObjectName(name)
    item.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return item


def button(text, action):
    item = QPushButton(text)
    item.setMinimumHeight(32)
    item.clicked.connect(action)
    return item


class ResearchWorkspaceBase(QWidget):
    diagnosticRequested = pyqtSignal(dict)
    settingsChanged = pyqtSignal(dict)
    workspace_id = 'research_studies'
    state_key = 'studies'

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._loading = True
        self._revision = 0
        self._owns_run = False
        self._benchmark_request = None
        self.fields = {}
        self.sections = {}
        self._last_state = None
        self.body_layout = QVBoxLayout(self)
        self.body_layout.setContentsMargins(16, 12, 16, 12)
        self.heading = label('', 'setupTitle')
        self.body_layout.addWidget(self.heading)
        self.description = label('')
        self.body_layout.addWidget(self.description)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setAccessibleName('Study sections')
        self.body_layout.addWidget(self.tabs, 1)
        self.diagnostics = DiagnosticPanel(self)
        self.diagnostics.activated.connect(self.open_diagnostic)
        self.diagnostics.recheckRequested.connect(self.validate_inputs)
        self.diagnostics.returnRequested.connect(lambda: self.diagnostics.list.setFocus())
        self.body_layout.addWidget(self.diagnostics)
        footer = QHBoxLayout()
        self.status = label('Edit the inputs, then review and run.')
        footer.addWidget(self.status, 1)
        self.validate_button = button('Check inputs', self.validate_inputs)
        self.run_button = button('Run simulation', self.run)
        self.run_button.setObjectName('setupPrimary')
        self.cancel_button = button('Stop', self.store.cancel)
        self.cancel_button.setEnabled(False)
        for item in (self.validate_button, self.run_button, self.cancel_button):
            footer.addWidget(item)
        self.body_layout.addLayout(footer)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(180)
        self._save_timer.timeout.connect(self.save_draft)
        self.store.busy_changed.connect(self._busy_changed)
        self.store.progress.connect(self._progress)
        self.store.run_finished.connect(self._finished)
        self.store.run_failed.connect(self._failed)
        self.store.changed.connect(self._store_changed)

    def add_section(self, title, key=None):
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(14, 14, 14, 14)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        index = self.tabs.addTab(scroll, title)
        self.sections[key or title] = index
        return body, layout

    def line(self, form, title, key, value='', units='', placeholder=''):
        edit = QLineEdit(str(value))
        edit.setAccessibleName(title + (' in '+units if units else ''))
        edit.setObjectName(self.workspace_id+'_'+key.replace('.', '_'))
        edit.setPlaceholderText(placeholder)
        edit.setToolTip(title+(' ['+units+']' if units else ''))
        form.addRow(title+(' ('+units+')' if units else ''), edit)
        self.fields[key] = edit
        edit.textChanged.connect(self._edited)
        return edit

    def choice(self, form, title, key, options, selected=None):
        edit = QComboBox()
        for item in options:
            caption, value = item if isinstance(item, tuple) else (str(item), item)
            edit.addItem(caption, value)
        if selected is not None:
            edit.setCurrentIndex(max(0, edit.findData(selected)))
        edit.setAccessibleName(title)
        edit.setObjectName(self.workspace_id+'_'+key.replace('.', '_'))
        form.addRow(title, edit)
        self.fields[key] = edit
        edit.currentIndexChanged.connect(self._edited)
        return edit

    def _edited(self, *args):
        if self._loading:
            return
        self._revision += 1
        self._save_timer.start()
        if self.diagnostics.list.count():
            QTimer.singleShot(0, self.validate_inputs)

    def draft(self):
        state = {'fields': {key: value.text() if isinstance(value, QLineEdit) else value.currentData()
                           for key, value in self.fields.items() if isinstance(value, (QLineEdit, QComboBox))},
                'section': self.tabs.currentIndex()}
        if self._benchmark_request is not None:
            state['benchmark_request'] = deepcopy(self._benchmark_request)
        return state

    def restore_draft(self, state):
        self._benchmark_request = deepcopy(state.get('benchmark_request'))
        for key, value in state.get('fields', {}).items():
            edit = self.fields.get(key)
            if isinstance(edit, QLineEdit):
                edit.setText(str(value))
            elif isinstance(edit, QComboBox):
                index = edit.findData(value)
                if index >= 0:
                    edit.setCurrentIndex(index)
        index = state.get('section', 0)
        if isinstance(index, int) and 0 <= index < self.tabs.count():
            self.tabs.setCurrentIndex(index)

    def save_draft(self):
        if self._loading:
            return
        state = self.draft()
        if state == self._last_state:
            return
        namespace = deepcopy(self.store.search_state.get('research_workspaces', {}))
        namespace.update(schema_version=1)
        namespace[self.state_key] = state
        self._last_state = deepcopy(state)
        self.store.save_search('research_workspaces', namespace)
        self.settingsChanged.emit(state)

    def flush_draft(self):
        """Capture even intermediate text before project Save or replacement."""
        focused = QApplication.focusWidget()
        if isinstance(focused, QLineEdit) and self.isAncestorOf(focused):
            parent = focused.parentWidget()
            while parent is not None and parent is not self:
                if isinstance(parent, (QTableWidget, QTreeWidget)):
                    index = parent.currentIndex()
                    if index.isValid():
                        parent.model().setData(index, focused.text(), Qt.ItemDataRole.EditRole)
                    break
                parent = parent.parentWidget()
        self._save_timer.stop()
        self.save_draft()

    def refresh(self):
        state = self.store.search_state.get('research_workspaces', {}).get(self.state_key)
        if state is not None and state != self._last_state:
            self._loading = True
            try:
                self.restore_draft(deepcopy(state))
                self._last_state = deepcopy(state)
            finally:
                self._loading = False
        self._busy_changed(self.store.busy)

    def _store_changed(self, reason=''):
        # A different project's empty namespace must not inherit the previous draft.
        if reason in ('project', 'load', 'reset', 'all'):
            state = self.store.search_state.get('research_workspaces', {}).get(self.state_key)
            self._loading = True
            try:
                self.restore_draft(deepcopy(state if state is not None else self._default_draft))
                self._last_state = deepcopy(state)
            finally:
                self._loading = False
        self.refresh()

    def finish_build(self):
        self._default_draft = deepcopy(self.draft())
        self._loading = False
        self.refresh()

    def options(self):
        raise NotImplementedError

    def runtime_settings(self):
        structured = getattr(self, 'structured', {}).get('runtime')
        if structured is not None:
            return structured.value() or None
        values = {}
        for key, widget in self.fields.items():
            if not key.startswith('runtime.'):
                continue
            name = key[8:]
            value = widget.currentData() if isinstance(widget, QComboBox) else widget.text()
            if name == 'timeout_s':
                value = number(value, key, positive=True, units='s')
            elif name == 'module_paths':
                value = [part.strip() for part in value.split(';') if part.strip()]
            values[name] = value
        return values or None

    def _issue(self, exc):
        return dict(code='invalid_input', message=str(exc), severity='error', workspace=self.workspace_id,
            section='', object_id=getattr(exc, 'object_id', ''), field=getattr(exc, 'field', ''),
            units=getattr(exc, 'units', ''), revision=str(self._revision))

    def validate_inputs(self):
        # A keyboard/global action need not move focus out of a cell delegate.
        self.flush_draft()
        try:
            options = self.options()
            from research_diagnostics import validate_request
            rows = validate_request(self.store.project(), options)
        except (ValueError, TypeError, KeyError) as exc:
            rows = [self._issue(exc)]
        self.diagnostics.set_diagnostics(rows, workspace=self.workspace_id, revision=str(self._revision))
        errors = [row for row in rows if row.get('severity', 'error') == 'error']
        self.status.setText('Inputs need attention.' if errors else 'Inputs are valid. The selected runtime is checked when the job starts.')
        return not errors

    def validate_setup(self):
        return self.validate_inputs()

    def return_to_issues(self):
        self.diagnostics.list.setFocus()
        if self.diagnostics.list.count():
            self.diagnostics.show()

    def select_section(self, title):
        index = self.sections.get(title)
        if index is None:
            index = next((i for i in range(self.tabs.count()) if self.tabs.tabText(i) == title), None)
        if index is None:
            return False
        self.tabs.setCurrentIndex(index)
        return True

    def run(self):
        if self.store.busy or not self.validate_inputs():
            return
        try:
            self._owns_run = True
            if self._benchmark_request is not None:
                snapshot = deepcopy(self.store.project())
                snapshot['benchmark_request'] = deepcopy(self._benchmark_request)
                self.store.start_run('research_simulation', self.options(), project_snapshot=snapshot)
            else:
                self.store.start_run('research_simulation', self.options())
        except Exception as exc:
            self._owns_run = False
            self.diagnostics.set_diagnostics([self._issue(exc)], workspace=self.workspace_id)
            self.status.setText(str(exc))

    def attach_benchmark(self, case):
        """Keep reference identity with this editable draft, not the shared device."""
        self._benchmark_request = deepcopy(case['project'].get('benchmark_request'))
        self.save_draft()

    def _busy_changed(self, busy):
        self.run_button.setEnabled(not busy)
        self.cancel_button.setEnabled(bool(busy and self._owns_run))

    def set_embedded(self, embedded=True):
        """The main window supplies the persistent Check/Run/Stop actions."""
        for widget in (self.validate_button, self.run_button, self.cancel_button):
            widget.setVisible(not embedded)

    def _progress(self, event):
        if self._owns_run:
            self.status.setText(str(event.get('message', 'Simulation is running…')))

    def _finished(self, event):
        if not self._owns_run:
            return
        self._owns_run = False
        self.cancel_button.setEnabled(False)
        self.status.setText('Run '+str(event.get('summary', {}).get('status', 'finished'))+'. Results retain the solver status and limitations.')
        if hasattr(self, 'results') and event.get('directory'):
            self.results.load_directory(event['directory'])
            index = self.tabs.indexOf(self.results)
            if index >= 0:
                self.tabs.setCurrentIndex(index)

    def _failed(self, message):
        if self._owns_run:
            self._owns_run = False
            self.cancel_button.setEnabled(False)
            self.status.setText(str(message))
            issue = self._issue(ValueError(message))
            issue.update(code='run_failed', section='Solver & accuracy' if 'runtime.executable' in self.fields else '',
                         field='runtime.executable' if 'runtime.executable' in self.fields else '')
            self.diagnostics.set_diagnostics([issue], workspace=self.workspace_id)

    def open_diagnostic(self, target):
        if target.get('workspace') and target['workspace'] != self.workspace_id:
            self.diagnosticRequested.emit(target)
            return False
        field = target.get('field', target.get('field_path', ''))
        if field.startswith('settings.'):
            field = field[9:]
        widget = self.fields.get(field)
        if widget is None:
            section = self.sections.get(target.get('section', ''))
            if section is not None:
                self.tabs.setCurrentIndex(section)
            self.status.setText('This input changed or is no longer available. Recheck inputs for the current draft.')
            return False
        return reveal_and_focus(widget, message=target.get('message', ''))
