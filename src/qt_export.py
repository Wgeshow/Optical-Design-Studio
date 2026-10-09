"""Shared array and physical-unit controls for structure exports."""
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout, QFormLayout, QSpinBox, QComboBox, QCheckBox, QLabel, QDoubleSpinBox
from export_geometry import ExportOptions, UNITS


class ExportDialog(QDialog):
    def __init__(self, settings, cad=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Export CAD (STEP)' if cad else 'Export COMSOL')
        self.resize(440, 360)
        self.settings = settings
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.nx, self.ny = QSpinBox(), QSpinBox()
        for spin in (self.nx, self.ny):
            spin.setRange(1, 1000000)
            spin.setValue(1)
            spin.valueChanged.connect(self.refresh_size)
        form.addRow('Cells along X', self.nx)
        form.addRow('Cells along Y', self.ny)
        self.unit = QComboBox()
        for label, value in [('Nanometers (nm)', 'nm'), ('Micrometers (µm)', 'um'), ('Millimeters (mm)', 'mm'), ('Meters (m)', 'm')]:
            self.unit.addItem(label, value)
        self.unit.setCurrentIndex(2 if cad else 1)
        self.unit.currentIndexChanged.connect(self.refresh_size)
        form.addRow('File units', self.unit)
        self.exterior = QCheckBox('Include finite incident and exit media')
        self.exterior.setChecked(not cad)
        form.addRow(self.exterior)
        self.incident, self.exit = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (self.incident, self.exit):
            spin.setDecimals(9)
            spin.setRange(.000000001, 1e9)
            spin.setValue(max(settings['ax_um'], settings['ay_um']))
            spin.setSuffix(' µm')
            spin.setEnabled(not cad)
            self.exterior.toggled.connect(spin.setEnabled)
        form.addRow('Incident thickness', self.incident)
        form.addRow('Exit thickness', self.exit)
        self.air = QCheckBox('Include air/vacuum solids')
        if cad:
            form.addRow(self.air)
        layout.addLayout(form)
        self.size_label = QLabel()
        self.size_label.setWordWrap(True)
        layout.addWidget(self.size_label)
        note = QLabel('1 × 1 is one unit cell (ax × ay). Export uses the applied structure; repeat counts are independent of preview cells. Large arrays take longer; at most 100,000 patterned copies can be exported.')
        note.setWordWrap(True)
        layout.addWidget(note)
        if not cad:
            java_note = QLabel('COMSOL export creates Java source plus build instructions. Compile it with COMSOL before using File → Open → Compiled Model File for Java (*.class). The .java file cannot be opened as an MPH model or imported as geometry.')
            java_note.setWordWrap(True)
            layout.addWidget(java_note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh_size()

    def refresh_size(self):
        if not hasattr(self, 'size_label'):
            return
        scale = UNITS[self.unit.currentData()]
        x = self.settings['ax_um'] * self.nx.value() * scale
        y = self.settings['ay_um'] * self.ny.value() * scale
        self.size_label.setText(f'Physical footprint: {x:.9g} × {y:.9g} {self.unit.currentData()}')

    def options(self):
        return ExportOptions(self.nx.value(), self.ny.value(), self.unit.currentData(), self.exterior.isChecked(), self.incident.value(), self.exit.value())
