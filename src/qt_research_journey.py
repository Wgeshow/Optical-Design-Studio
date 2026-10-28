"""Review and execution surfaces for the existing research job pipeline."""
from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QTreeWidget,
    QTreeWidgetItem, QComboBox)


from qt_research_common import run_failure_summary


def _structured_review_value(editor):
    """Bounded preview of the current typed draft, including invalid tokens."""
    root = editor.tree.topLevelItem(0)
    if root is None:
        return 'No values supplied'
    kind = root.data(0, Qt.ItemDataRole.UserRole)
    if not root.childCount():
        return 'No items supplied' if kind == 'array' else 'No properties supplied' if kind == 'object' else root.text(1) or 'Not supplied'
    leaves = []
    visited = 0
    truncated = False
    def visit(node, path):
        nonlocal visited, truncated
        if visited >= 128 or len(leaves) >= 8:
            truncated = True
            return
        visited += 1
        if node.childCount():
            for index in range(node.childCount()):
                child = node.child(index)
                visit(child, path + '.' + child.text(0) if path else child.text(0))
                if visited >= 128 or len(leaves) >= 8:
                    if index + 1 < node.childCount(): truncated = True
                    break
        else:
            value = node.text(1) or ('No values' if node.data(0, Qt.ItemDataRole.UserRole) in ('array', 'object') else 'Not supplied')
            leaves.append((path + ' = ' if kind != 'array' or not path.isdigit() else '') + value)
    for index in range(root.childCount()):
        child = root.child(index)
        visit(child, child.text(0))
        if visited >= 128 or len(leaves) >= 8:
            if index + 1 < root.childCount(): truncated = True
            break
    text = f'{root.childCount()} ' + ('items' if kind == 'array' else 'properties') + ' · ' + '; '.join(leaves)
    if len(text) > 620:
        text = text[:620].rstrip()
        truncated = True
    return text + (' … Open editor for all values.' if truncated else '')


class ResearchExecutionPanels(QObject):
    def __init__(self, workspace):
        # Store signals outlive a removed workspace. Qt must own this receiver
        # so its connections disappear before the child controls are deleted.
        super().__init__(workspace)
        self.workspace = w = workspace
        self.check_page, layout = w.add_section('Check inputs', '__journey_check')
        title = QLabel('Review this simulation before running', self.check_page)
        title.setObjectName('studyPageTitle')
        layout.addWidget(title)
        self.context = QLabel(self.check_page)
        self.context.setWordWrap(True)
        layout.addWidget(self.context)
        self.inputs = QTreeWidget(self.check_page)
        self.inputs.setHeaderLabels(['Input', 'Current value'])
        self.inputs.setRootIsDecorated(False)
        self.inputs.setAlternatingRowColors(True)
        self.inputs.setAccessibleName('Current simulation input review; activate an input to edit it')
        self.inputs.itemActivated.connect(self._open)
        self.inputs.itemDoubleClicked.connect(self._open)
        layout.addWidget(self.inputs, 1)
        self.validation_status = QLabel('Inputs have not been checked here.', self.check_page)
        self.validation_status.setWordWrap(True)
        layout.addWidget(self.validation_status)
        check = QPushButton('Check inputs', self.check_page)
        check.clicked.connect(self.validate)
        layout.addWidget(check)
        self.run_page, run = w.add_section('Run & progress', '__journey_run')
        title = QLabel('Run this simulation', self.run_page)
        title.setObjectName('studyPageTitle')
        run.addWidget(title)
        self.run_context = QLabel(self.run_page)
        self.run_context.setWordWrap(True)
        run.addWidget(self.run_context)
        self.run_status = QLabel('No run started from this workspace.', self.run_page)
        self.run_status.setWordWrap(True)
        self.run_status.setTextFormat(Qt.TextFormat.PlainText)
        run.addWidget(self.run_status)
        self.log = QTreeWidget(self.run_page)
        self.log.setHeaderLabels(['State', 'Details'])
        self.log.setRootIsDecorated(False)
        self.log.setAccessibleName('Simulation progress events')
        run.addWidget(self.log, 1)
        row = QHBoxLayout()
        self.start = QPushButton('Run simulation', self.run_page)
        self.start.setObjectName('setupPrimary')
        self.start.clicked.connect(self.start_run)
        self.stop = QPushButton('Stop this run', self.run_page)
        self.stop.clicked.connect(self.cancel_run)
        self.stop.setEnabled(False)
        self.results = QPushButton('View results', self.run_page)
        self.results.clicked.connect(lambda: w.select_section('Results'))
        for action in (self.start, self.stop, self.results):
            row.addWidget(action)
        run.addLayout(row)
        w.tabs.currentChanged.connect(self.refresh)
        w.store.changed.connect(self.invalidate)
        w.settingsChanged.connect(self.invalidate)
        # Research drafts emit search_changed rather than store.changed. Mark
        # the check stale as soon as a user edits, including incomplete text.
        for editor in w.fields.values():
            signal = getattr(editor, 'textChanged', None) or getattr(editor, 'currentIndexChanged', None) or getattr(editor, 'changed', None)
            if signal is not None:
                signal.connect(self.invalidate)
        w.store.busy_changed.connect(self.busy)
        w.store.progress.connect(self.progress)
        w.store.run_finished.connect(self.finished)
        w.store.run_failed.connect(self.failed)
        self._observing_run = False
        self.refresh()
        self.busy(w.store.busy)

    def _open(self, item, *_):
        if item is not None:
            target=item.data(0, Qt.ItemDataRole.UserRole)
            if target.get('section'):
                self.workspace.select_section(target['section'])
            elif target.get('field'):
                self.workspace.open_diagnostic({'workspace': self.workspace.workspace_id,**target})

    def _review_rows(self):
        w=self.workspace
        if hasattr(w,'journey_review_fields'):
            return w.journey_review_fields()
        rows=[]
        schema={row['path']:row for row in getattr(w,'schema',[])}
        for key,editor in w.fields.items():
            visible_editor=getattr(w,'input_forms',{}).get(key,editor)
            owner=next((w.tabs.widget(i) for i in range(w.tabs.count()) if
                w.tabs.isTabVisible(i) and w.tabs.widget(i).isAncestorOf(visible_editor)),None)
            if owner is None or not visible_editor.isVisibleTo(owner):continue
            if key in getattr(w,'structured',{}) and hasattr(editor,'tree'):
                spec=schema.get(key,{})
                name=spec.get('label',key.replace('_',' '))
                if spec.get('unit'):name+=' ('+spec['unit']+')'
                section=spec.get('section','')
                rows.append((key,name,_structured_review_value(editor),section if section in w.sections else ''))
                continue
            if isinstance(editor,QComboBox):value=editor.currentText()
            elif hasattr(editor,'text'):value=editor.text()
            else:continue
            rows.append((key if editor.isEnabled() else '',editor.accessibleName() or key.replace('_',' '),str(value)))
        return rows

    def refresh(self, *_):
        w = self.workspace
        identity = getattr(w, '_bound_study_id', None) or w.workspace_id
        self.context.setText(f'{w.heading.text()} · independent setup\nActivate an input to return to its editor. Nested inputs are summarized here; activate a row to inspect all values in its editing step.')
        self.run_context.setText(f'{w.heading.text()}\nInputs are checked again before launch. Results retain the actual job status and model limits.')
        if w.tabs.currentIndex() == w.sections['__journey_check'] or not self.inputs.topLevelItemCount():
            self.inputs.clear()
            for row in self._review_rows():
                key,name,value=row[:3]
                item = QTreeWidgetItem([name, str(value)])
                target={'section':row[3]} if len(row)>3 and row[3] else {'field':key}
                item.setData(0, Qt.ItemDataRole.UserRole, target)
                item.setToolTip(0, 'Go to input: ' + key if key else 'Study identity · read only')
                item.setToolTip(1,str(value))
                self.inputs.addTopLevelItem(item)
            self.inputs.resizeColumnToContents(0)
        self.busy(w.store.busy)

    def invalidate(self, *_):
        self.validation_status.setText('Inputs changed. Check this setup before running.')
        # Returning to this document need not change its already-selected tab.
        self.busy(self.workspace.store.busy)

    def validate(self):
        valid = self.workspace.validate_inputs()
        self.validation_status.setText(self.workspace.status.text())
        self.refresh()
        return valid

    def start_run(self):
        w = self.workspace
        if w.store.busy or not w._is_active_document(): return
        w.run()
        self._observing_run = bool(w._owns_run)
        self.run_status.setText(w.status.text())
        self.busy(w.store.busy)

    def cancel_run(self):
        if self.workspace._owns_run and self.workspace.store.busy:
            self.workspace.store.cancel()

    def busy(self, busy):
        self.start.setEnabled(not busy and self.workspace._is_active_document())
        self.stop.setEnabled(bool(busy and self.workspace._owns_run))
        if self.workspace._owns_run:
            self._observing_run = True

    def progress(self, event):
        if not self.workspace._owns_run: return
        self._observing_run = True
        message = str(event.get('message') or event.get('text') or 'Running…')
        self.run_status.setText(message)
        self.log.addTopLevelItem(QTreeWidgetItem(['Running', message]))
        while self.log.topLevelItemCount() > 200:
            self.log.takeTopLevelItem(0)
        self.log.scrollToBottom()

    def finished(self, event):
        if not self._observing_run: return
        self._observing_run = False
        state = str(event.get('summary', {}).get('status', 'finished'))
        self.run_status.setText('Run ' + state + '. Inspect saved results and validity notes.')
        self.log.addTopLevelItem(QTreeWidgetItem([state, str(event.get('directory', ''))]))
        self.busy(self.workspace.store.busy)

    def failed(self, message):
        if not self._observing_run: return
        self._observing_run = False
        summary = run_failure_summary(message)
        self.run_status.setText('Run failed: ' + summary)
        self.run_status.setToolTip(str(message))
        item = QTreeWidgetItem(['Failed', summary])
        item.setToolTip(1, str(message))
        item.setData(1, Qt.ItemDataRole.UserRole, str(message))
        self.log.addTopLevelItem(item)
        self.busy(self.workspace.store.busy)


def ensure_execution_panels(workspace):
    if not hasattr(workspace, 'journey_execution'):
        workspace.journey_execution = ResearchExecutionPanels(workspace)
    return workspace.journey_execution
