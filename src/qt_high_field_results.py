"""Physical-wavelength plots of saved high-field sensitivity results."""
from pathlib import Path
import zipfile
import numpy as np
from PyQt6.QtCore import QSignalBlocker
from matplotlib.figure import Figure
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QVBoxLayout, QWidget
from qt_common import PlotWidget
from qt_research_common import label
from qt_research_results import ResearchResultsPanel


class HighFieldResultsPanel(ResearchResultsPanel):
    quantities = (
        ('Absorption', 'absorption_cm1', 'Absorption (cm⁻¹)'),
        ('Refractive-index change Δn', 'delta_n', 'Δn'),
        ('Extinction change Δk', 'delta_k', 'Δk'),
        ('Interband extinction k', 'interband_k', 'Interband k'),
        ('Reference absorption', 'reference_absorption_cm1', 'Reference absorption (cm⁻¹)'),
        ('Integration error estimate', 'kk_quadrature_error_estimate', 'Absolute quadrature error estimate'))

    def __init__(self, store, parent=None):
        super().__init__(store, 'high_field_optics', parent)
        self.response_data = {}
        self.response = QWidget()
        layout = QVBoxLayout(self.response)
        controls = QHBoxLayout()
        self.state = QComboBox()
        self.state.setAccessibleName('Optical material state')
        self.quantity = QComboBox()
        self.quantity.setAccessibleName('Optical response quantity')
        for title, key, _ in self.quantities:
            self.quantity.addItem(title, key)
        controls.addWidget(self.state, 1)
        controls.addWidget(self.quantity, 1)
        layout.addLayout(controls)
        self.response_plot = PlotWidget()
        layout.addWidget(self.response_plot, 1)
        self.response_note = label('Run the calculation to view the response of each material state.')
        layout.addWidget(self.response_note)
        self.tabs.insertTab(0, self.response, 'Optical response')
        self.tabs.setCurrentIndex(0)
        self.state.currentIndexChanged.connect(self.draw_response)
        self.quantity.currentIndexChanged.connect(self.draw_response)

    def load_directory(self, path):
        self.response_data = {}
        self.response_plot.clear()
        with QSignalBlocker(self.state):
            self.state.clear()
        self.response_note.setText('No optical response is loaded for this run.')
        for index in range(self.quantity.count()):
            self.quantity.model().item(index).setEnabled(False)
        if not super().load_directory(path):
            return False
        self.state.blockSignals(True)
        try:
            with np.load(Path(path)/'high_field_optics.npz', allow_pickle=False) as archive:
                wavelengths = np.asarray(archive['wavelengths_nm'], dtype=float)
                ids = [str(value) for value in archive['sample_ids']]
                if wavelengths.ndim != 1 or not len(wavelengths) or not np.isfinite(wavelengths).all():
                    raise ValueError('Missing or invalid wavelength coordinates.')
                if not ids:
                    raise ValueError('Missing saved material states.')
                response = {'wavelengths_nm': wavelengths.copy()}
                for _, key, _ in self.quantities:
                    if key not in archive:
                        continue
                    values = np.asarray(archive[key], dtype=float)
                    if values.shape != (len(ids), len(wavelengths)):
                        raise ValueError('Saved '+key+' does not match the states and wavelengths.')
                    response[key] = values.copy()
                self.response_data = response
                self.state.addItems(ids)
        except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile) as exc:
            self.response_data = {}
            self.response_note.setText('Could not read optical response: '+str(exc))
            self.state.blockSignals(False)
            self.response_plot.clear()
            return False
        self.state.blockSignals(False)
        available = []
        for index in range(self.quantity.count()):
            exists = self.quantity.itemData(index) in self.response_data
            self.quantity.model().item(index).setEnabled(exists)
            if exists: available.append(index)
        with QSignalBlocker(self.quantity):
            if self.quantity.currentIndex() not in available:
                self.quantity.setCurrentIndex(available[0] if available else -1)
        self.tabs.setCurrentWidget(self.response)
        self.draw_response()
        return True

    def draw_response(self, *args):
        key = self.quantity.currentData()
        row = self.state.currentIndex()
        self.response_plot.clear()
        if row < 0 or key not in self.response_data:
            self.response_note.setText('The selected optical quantity was not saved for this run.')
            return
        wavelengths = self.response_data['wavelengths_nm']
        values = self.response_data[key][row]
        figure = Figure(figsize=(8, 4), constrained_layout=True)
        axis = figure.add_subplot(111)
        axis.plot(wavelengths, values, label=self.state.currentText())
        axis.set_xlabel('Wavelength (nm)')
        axis.set_ylabel(next(caption for _, name, caption in self.quantities if name == key))
        axis.grid(True, alpha=.25)
        self.response_plot.draw_figure(figure)
        warnings = self.summary.get('kk_quadrature_warning_count', 0)
        self.response_note.setText('State '+self.state.currentText()+' · saved wavelength samples. '
            'Δn and Δk use the supplied zero-field reference. '+
            (str(warnings)+' integration warnings; inspect Details and refine before quantitative use.' if warnings
             else 'Energy-grid and cutoff convergence remain separate checks.'))
