"""Native inspection of field movement between saved design snapshots."""
from pathlib import Path
import re
import shutil
import textwrap

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QLineEdit,
    QPushButton, QLabel, QCheckBox, QFileDialog, QTabWidget,
)

from field_tracking_ui import (
    MODES, saved_datasets, common_layers, dataset_selection,
    compare_saved, save_comparison, comparison_summary,
)
from qt_common import PlotWidget
from qt_materials import choices, group, make_table, show_frame, spin, readable_form


class FieldComparisonWidget(QWidget):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._pending = None
        self._payload = None
        self._datasets = []
        root = QVBoxLayout(self)
        text = QLabel('Track how field concentration and position change across saved designs. Reference and comparison maps share one intensity scale.')
        text.setWordWrap(True)
        root.addWidget(text)
        box, body = group('Choose saved electric-field snapshots')
        filters = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(list(MODES))
        self.mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.mode.setMinimumContentsLength(20)
        self.query = QLineEdit()
        self.query.setPlaceholderText('Filter runs, layers, materials, or designs…')
        self.wavelength = spin(0, 0, 1e8, 3)
        self.wavelength.setSpecialValueText('Any wavelength')
        self.wavelength.setSuffix(' nm')
        self.refresh_button = QPushButton('Refresh')
        body.addWidget(self.query)
        filters.addWidget(self.mode, 1)
        filters.addWidget(self.wavelength)
        filters.addWidget(self.refresh_button)
        body.addLayout(filters)
        form = readable_form()
        self.reference, self.current = QComboBox(), QComboBox()
        self.reference.setAccessibleName('Reference field snapshot')
        self.current.setAccessibleName('Comparison field snapshot')
        form.addRow('Reference', self.reference)
        form.addRow('Comparison', self.current)
        self.layer = QComboBox()
        form.addRow('XY slice layer', self.layer)
        self.alignment = QComboBox()
        self.alignment.addItems(['Physical coordinates', 'Layer-relative coordinates'])
        form.addRow('Coordinate view', self.alignment)
        body.addLayout(form)
        actions = QHBoxLayout()
        self.previous = QPushButton('← Previous design')
        self.next = QPushButton('Next design →')
        self.arrows = QCheckBox('Show energy-flow direction')
        self.compare = QPushButton('Compare fields')
        self.compare.setProperty('primary', True)
        actions.addWidget(self.previous)
        actions.addWidget(self.next)
        actions.addStretch()
        body.addLayout(actions)
        compare_actions = QHBoxLayout()
        compare_actions.addWidget(self.arrows)
        compare_actions.addStretch()
        compare_actions.addWidget(self.compare)
        body.addLayout(compare_actions)
        root.addWidget(box)
        self.plot = PlotWidget()
        self.plot.setMinimumHeight(630)
        root.addWidget(self.plot, 1)
        self.summary = make_table()
        self.summary.setMaximumHeight(210)
        root.addWidget(self.summary)
        self.tabs = QTabWidget()
        self.conditions, self.metrics = make_table(), make_table()
        self.tabs.addTab(self.conditions, 'Design conditions')
        self.tabs.addTab(self.metrics, 'All field measurements')
        self.tabs.setMinimumHeight(200)
        root.addWidget(self.tabs)
        footer = QHBoxLayout()
        self.save = QPushButton('Save comparison & complete data…')
        self.save.clicked.connect(self.save_result)
        footer.addWidget(self.save)
        footer.addStretch()
        root.addLayout(footer)
        self.status = QLabel('Generate field maps for at least two designs to compare their optical fields.')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.status)
        self.refresh_button.clicked.connect(self.refresh)
        self.mode.currentIndexChanged.connect(self.refresh)
        self.query.returnPressed.connect(self.refresh)
        self.wavelength.valueChanged.connect(self.refresh)
        self.reference.currentIndexChanged.connect(self.update_layers)
        self.current.currentIndexChanged.connect(self.update_layers)
        self.previous.clicked.connect(lambda: self.step(-1))
        self.next.clicked.connect(lambda: self.step(1))
        self.compare.clicked.connect(self.compare_now)
        store.library_changed.connect(self.refresh)
        store.busy_changed.connect(self._actions)
        store.task_finished.connect(self.task_finished)
        store.task_failed.connect(self.task_failed)
        self.refresh()

    def _actions(self, *_):
        idle = not self.store.busy
        valid = self.reference.currentData() is not None and self.current.currentData() is not None and self.layer.currentData() is not None
        self.compare.setEnabled(idle and valid)
        self.save.setEnabled(idle and valid)
        self.previous.setEnabled(idle and self.current.currentIndex() > 0)
        self.next.setEnabled(idle and 0 <= self.current.currentIndex() < self.current.count() - 1)
        for widget in (self.mode, self.query, self.wavelength, self.reference, self.current, self.layer, self.alignment, self.arrows, self.refresh_button):
            widget.setEnabled(idle)

    def refresh(self, *_):
        self._datasets = saved_datasets(self.store.library, self.mode.currentText(), self.query.text(), self.wavelength.value())
        reference, current, _, _ = dataset_selection(self._datasets, self.reference.currentData(), self.current.currentData())
        choices(self.reference, self._datasets, reference)
        choices(self.current, self._datasets, current)
        self.update_layers()

    def update_layers(self, *_):
        items, selected = common_layers(self.store.library, self.reference.currentData(), self.current.currentData(), self.layer.currentData())
        choices(self.layer, items, selected)
        self._actions()

    def step(self, direction):
        index = self.current.currentIndex() + direction
        if 0 <= index < self.current.count():
            self.current.setCurrentIndex(index)
            self.compare_now()

    def arguments(self):
        reference, current, layer = self.reference.currentData(), self.current.currentData(), self.layer.currentData()
        if reference is None or current is None or layer is None:
            raise ValueError('Choose two saved field snapshots with a common finite layer.')
        return reference, current, layer, self.alignment.currentText(), self.arrows.isChecked()

    def compare_now(self):
        if self.store.busy:
            return
        try:
            arguments = self.arguments()
            library = self.store.library
            self._pending = 'field-comparison-preview'
            self.status.setText('Comparing field maps, confinement, position, and complex-field overlap…')
            self.store.run_task(self._pending, lambda: compare_saved(library, *arguments))
        except Exception as exc:
            self._pending = None
            self.status.setText(str(exc))

    def save_result(self):
        if self.store.busy:
            return
        try:
            arguments = self.arguments()
            path, _ = QFileDialog.getSaveFileName(self, 'Save complete field comparison', 's4_field_comparison.zip', 'ZIP archives (*.zip)')
            if not path:
                return
            library = self.store.library
            def save():
                generated, message = save_comparison(library, *arguments)
                if Path(generated).resolve() != Path(path).resolve():
                    shutil.copy2(generated, path)
                return path, message
            self._pending = 'field-comparison-save'
            self.status.setText('Saving raw field samples, design conditions, metrics, and plots…')
            self.store.run_task(self._pending, save)
        except Exception as exc:
            self._pending = None
            self.status.setText(str(exc))

    def task_finished(self, name, result):
        if name != self._pending:
            return
        self._pending = None
        if name == 'field-comparison-preview':
            figure, conditions, metrics, explanation, payload = result
            self._payload = payload
            # The export figure was designed for a full page. Native panels can
            # be narrower, so wrap explanatory titles without shrinking labels.
            if figure._suptitle is not None:
                text = figure._suptitle.get_text()
                text = text.replace('; white outlines = geometry, black = sampled material boundary',
                                    '\nWhite outlines: geometry · Black lines: sampled material boundary')
                text = text.replace('Arrows: local time-averaged energy-flow direction (equal length; magnitude not encoded)',
                                    'Arrows: time-averaged energy flow\nEqual length; magnitude is not encoded')
                figure._suptitle.set_text(text)
            for axis in figure.axes[:4]:
                axis.set_title('\n'.join(textwrap.fill(line, width=40) for line in axis.get_title().splitlines()))
                if axis.get_ylabel() == 'layer index + depth fraction':
                    axis.set_ylabel('Layer index\n+ depth fraction')
            self.plot.draw_figure(figure)
            show_frame(self.conditions, conditions)
            show_frame(self.metrics, metrics)
            show_frame(self.summary, comparison_summary(payload))
            self.status.setText(re.sub(r'\*\*', '', explanation))
        else:
            path, _ = result
            self.store.notify_library()
            self.status.setText('Saved complete comparison to the library and ' + path)
        self._actions()

    def task_failed(self, name, error):
        if name == self._pending:
            self._pending = None
            self.status.setText('Comparison needs attention: ' + str(error))
            self._actions()
