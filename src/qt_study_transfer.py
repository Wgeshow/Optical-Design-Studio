"""Explicit, reviewable transfer of compatible structure inputs."""
from PyQt6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout
from qt_simulation_picker import SIMULATIONS
from simulation_documents import transfer_sections


class StudyTransferDialog(QDialog):
    def __init__(self,store,parent=None):
        super().__init__(parent)
        self.store=store
        self.setWindowTitle('Transfer inputs to this simulation')
        self.resize(540,310)
        layout=QVBoxLayout(self)
        names={row[0]:row[1] for row in SIMULATIONS}
        heading=QLabel('Destination: '+names.get(store.active_study,store.active_study))
        heading.setWordWrap(True);layout.addWidget(heading)
        self.source=QComboBox();self.source.setAccessibleName('Simulation to copy structure from')
        for identifier in store.project()['simulation_documents']['documents']:
            if transfer_sections(identifier,store.active_study):self.source.addItem(names.get(identifier,identifier),identifier)
        layout.addWidget(self.source)
        self.summary=QLabel();self.summary.setWordWrap(True);layout.addWidget(self.summary,1)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Copy compatible inputs')
        self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.source.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        identifier=self.source.currentData()
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(identifier))
        self.summary.setText(('Copy:\n• '+'\n• '.join(transfer_sections(identifier,self.store.active_study))+
            '\n\nThis replaces the destination structure. Its solver, sampling and operating parameters stay as configured. '
            'The source remains independent. Review missing inputs before running.') if identifier else
            'No other saved simulation has a compatible structure. Create a setup in another compatible simulation first. '
            'Crystal, finite-device and semiconductor-domain formats are not automatically converted.')
