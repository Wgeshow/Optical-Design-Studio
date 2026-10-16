"""Editable circle primitives for multiple vertically extruded openings per cell."""
import copy
import math
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QComboBox, QPushButton, QTableWidget, QTableWidgetItem, QCheckBox, QDialogButtonBox)
from qt_common import number
from model import PAT_COLS
from structure_sync import air_materials


class MultiHoleDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store, self.bounds = store, []
        self.setWindowTitle('Multiple holes in one periodic cell')
        self.resize(700, 570)
        layout = QVBoxLayout(self)
        explanation = QLabel('Each row is one circle primitive. Separate circles form separate holes; overlapping circles can form one irregular opening. All walls are vertical through the selected layer. Applying replaces air regions in that layer only. Dimensions are µm.')
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.layer = QComboBox()
        self.layer.addItems([r['Name'] for r in store.layers.to_dict('records')[1:-1]])
        form = QFormLayout()
        form.addRow('Etched layer', self.layer)
        self.variation = number(10., 0., 100., 2)
        form.addRow('Radius search range ± (%)', self.variation)
        layout.addLayout(form)
        self.positions = QCheckBox('Also optimize each center within ±5% of the cell period')
        self.positions.setChecked(True)
        self.merge = QCheckBox('Allow circle unions for irregular openings')
        layout.addWidget(self.positions)
        layout.addWidget(self.merge)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Center X (µm)', 'Center Y (µm)', 'Radius (µm)'])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        for label, callback in [('Load current circles', self.load_current), ('Double lattice', self.double_lattice),
                ('Add circle', self.add_circle), ('Remove selected', self.remove_circle)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.status = QLabel('The double-lattice preset supplies two offset holes in one repeating cell.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        actions.button(QDialogButtonBox.StandardButton.Ok).setText('Apply cell and search ranges')
        actions.accepted.connect(self.apply)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)
        self.layer.currentIndexChanged.connect(self.load_current)
        self.load_current()

    def add_circle(self, checked=False, values=None):
        values = values or (0., 0., min(self.store.settings['ax_um'], self.store.settings['ay_um']) * .08)
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, value in enumerate(values):
            self.table.setItem(row, col, QTableWidgetItem(f'{value:.9g}'))

    def remove_circle(self):
        if self.table.currentRow() >= 0:
            self.table.removeRow(self.table.currentRow())

    def load_current(self, *_):
        self.table.setRowCount(0)
        air = air_materials(self.store.materials)
        for p in self.store.patterns.to_dict('records'):
            if p['Layer'] == self.layer.currentText() and p['Material'] in air and p['Shape'] == 'circle':
                self.add_circle(values=(p['CenterX_um'], p['CenterY_um'], p['SizeX_um']))

    def double_lattice(self):
        self.table.setRowCount(0)
        ax, ay = self.store.settings['ax_um'], self.store.settings['ay_um']
        r = min(ax, ay) * .1
        self.add_circle(values=(-ax / 4, -ay / 4, r))
        self.add_circle(values=(ax / 4, ay / 4, r * .8))

    def apply(self):
        try:
            if self.store.busy:
                raise ValueError('Finish or stop the current calculation before editing the cell.')
            if not 1 <= self.table.rowCount() <= 64:
                raise ValueError('Use between 1 and 64 circle primitives.')
            layer = self.layer.currentText()
            air = air_materials(self.store.materials)
            if not layer or not air:
                raise ValueError('A finite layer and an explicit air material are required.')
            material = sorted(air)[0]
            patterns = [copy.deepcopy(p) for p in self.store.patterns.to_dict('records')
                        if not (p['Layer'] == layer and p['Material'] in air)]
            bounds = []
            ax, ay = self.store.settings['ax_um'], self.store.settings['ay_um']
            for row in range(self.table.rowCount()):
                x, y, radius = [float(self.table.item(row, col).text()) for col in range(3)]
                if not all(math.isfinite(v) for v in (x,y,radius)) or radius <= 0:
                    raise ValueError('Each circle needs finite centers and a positive radius.')
                x, y = (x+ax/2)%ax-ax/2, (y+ay/2)%ay-ay/2
                patterns.append(dict(zip(PAT_COLS,['circle',layer,material,x,y,radius,0.,0.])))
                target = str(len(patterns))
                fraction = self.variation.value() / 100
                low, high = max(radius*(1-fraction), radius*.01), radius*(1+fraction)
                bounds.append(dict(Parameter='radius',Target=target,Min=low,Max=high,Step=(high-low)/10 or .001,Choices=''))
                if self.positions.isChecked():
                    for parameter, value, period in [('center_x',x,ax),('center_y',y,ay)]:
                        bounds.append(dict(Parameter=parameter,Target=target,Min=value-.05*period,Max=value+.05*period,Step=.01*period,Choices=''))
            from model import prepare
            from peak_optimizer import geometry_error
            project = self.store.portable_project()
            model = prepare(project['materials'],project['layers'],patterns,self.store.library.files_for(project),project['settings'])
            error = geometry_error(model,dict(ratio_limit=.6,min_bridge_um=0.,separate_circles=True,
                all_shape_bridges=True,merge_circles=self.merge.isChecked()))
            if error:
                raise ValueError(error)
            self.store.set_structure(self.store.materials,self.store.layers,patterns)
            self.bounds = bounds
            self.accept()
        except Exception as exc:
            self.status.setText(str(exc))
