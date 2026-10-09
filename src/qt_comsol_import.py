"""Import paired COMSOL carrier exports for the GaAs/AlGaAs/GaAs stack."""
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QHBoxLayout,QLineEdit,QPushButton,QLabel,QCheckBox,QDialogButtonBox,QFileDialog,QMessageBox

class ComsolCarrierImport(QDialog):
    def __init__(self,parent=None,layer_names=None):
        super().__init__(parent);self.setWindowTitle('Import COMSOL carrier profiles');self.resize(820,480)
        layout=QVBoxLayout(self);note=QLabel('GaAs 200 nm / unchanged AlGaAs 20 nm / GaAs 200 nm. COMSOL arc length must run from 0 to 0.42 µm along the stack. Concentrations: cm⁻³. Import reference and biased electrons and holes separately.');note.setWordWrap(True);layout.addWidget(note)
        form=QFormLayout();self.paths={}
        for key,label in [('reference_electrons','0 V electrons'),('reference_holes','0 V holes'),('biased_electrons','Biased electrons'),('biased_holes','Biased holes')]:
            row=QHBoxLayout();edit=QLineEdit();self.paths[key]=edit;row.addWidget(edit);button=QPushButton('Browse…');button.clicked.connect(lambda _,e=edit:self.browse(e));row.addWidget(button);form.addRow(label,row)
        names=layer_names or ['GaAs top','GaAs bottom']
        self.top_layer=QLineEdit(names[0]);self.bottom_layer=QLineEdit(names[-1]);form.addRow('Top GaAs layer name',self.top_layer);form.addRow('Bottom GaAs layer name',self.bottom_layer)
        layout.addLayout(form)
        self.cleanup=QCheckBox('Set tiny negative concentrations (up to 10⁴ cm⁻³) to zero and record corrections')
        self.cleanup.setChecked(True);layout.addWidget(self.cleanup)
        info=QLabel('Larger negative values are rejected. Interface jumps and the original sample spacing are preserved. Each interval becomes an S4 slice; air holes keep the same geometry.');info.setWordWrap(True);layout.addWidget(info)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.import_data);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.result=None

    def browse(self,edit):
        path,_=QFileDialog.getOpenFileName(self,'COMSOL concentration export','','All files (*)')
        if path:edit.setText(path)

    def import_data(self):
        from comsol_carriers import import_comsol_profiles
        try:
            self.result=import_comsol_profiles(**{k:e.text() for k,e in self.paths.items()},top_layer=self.top_layer.text(),bottom_layer=self.bottom_layer.text(),negative_tolerance_cm3=1e4 if self.cleanup.isChecked() else 0)
        except (ValueError,OSError) as exc:QMessageBox.warning(self,'COMSOL import',str(exc));return
        self.accept()
