"""Choose a categorical layer-material search from existing library entries."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QLabel,QComboBox,QListWidget,
    QListWidgetItem,QLineEdit,QDialogButtonBox,QPlainTextEdit)
from structure_builder import material_catalog, resolve_material
from material_viewer import material_data


class DesignMaterialsDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store, self.bound = store, None
        self.setWindowTitle('Materials allowed in the AI design search')
        self.resize(760,690)
        layout=QVBoxLayout(self)
        text=QLabel('Choose the film layer and allowed materials. Current materials, built-in presets and saved library datasets are available. Selected n/k tables are retained in the saved project. Only materials covering the search wavelength range can be used.')
        text.setWordWrap(True)
        layout.addWidget(text)
        self.layer=QComboBox()
        self.layer.addItems([r['Name'] for r in store.layers.to_dict('records')[1:-1]])
        layout.addWidget(self.layer)
        self.query=QLineEdit()
        self.query.setPlaceholderText('Filter materials…')
        layout.addWidget(self.query)
        self.items=QListWidget()
        layout.addWidget(self.items)
        self.catalog = material_catalog(store.context,store.materials)
        self.presets = store.library.presets()
        for key,(label,row) in self.catalog.items():
            model = 'tabulated n,k' if row.get('Model') == 'table_nk' else 'constant approximation'
            item=QListWidgetItem(label + ' · ' + model)
            item.setData(Qt.ItemDataRole.UserRole,key)
            item.setToolTip(label + '\nModel: ' + str(row.get('Model', '')) + '\n' + self.notes(key, row))
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.items.addItem(item)
        self.query.textChanged.connect(self.filter)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText('Select a material to inspect its optical data and source before checking it.')
        layout.addWidget(self.details)
        self.items.currentItemChanged.connect(self.show_details)
        self.status=QLabel('Choose one or more entries; each is a distinct material candidate.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def filter(self,text):
        for i in range(self.items.count()):
            item=self.items.item(i)
            item.setHidden(text.casefold() not in (item.text() + ' ' + item.toolTip()).casefold())

    def notes(self, key, row):
        if key.startswith('saved:'):
            return self.presets.get(key[6:], {}).get('notes', '') or 'No source notes recorded.'
        if key.startswith('builtin:'):
            return 'Built-in constant approximation; no measured dispersion table is attached.'
        for record in self.presets.values():
            saved = record.get('project', {}).get('materials', [{}])[0]
            if row.get('Model') == 'table_nk' and row.get('DataFile') and saved.get('DataFile') == row.get('DataFile'):
                return record.get('notes', '') or 'No source notes recorded.'
        return 'No source notes recorded for this project entry.'

    def show_details(self, item, *_):
        if item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        label, row = self.catalog[key]
        notes = self.notes(key, row)
        try:
            data, description, _ = material_data(self.store.library, (row, notes), self.store.materials, self.store.files)
            ranges = f"n range: {data.n.min():g}–{data.n.max():g}; k range: {data.k.min():g}–{data.k.max():g}"
            self.details.setPlainText(label + '\n\n' + description + '\n' + ranges + '\n\nSource / sample notes\n' + notes)
        except Exception as exc:
            self.details.setPlainText(label + '\nModel: ' + str(row.get('Model')) + '\n\n' + notes + '\n\nCannot inspect optical data: ' + str(exc))

    def apply(self):
        try:
            if self.store.busy:
                raise ValueError('Finish the running calculation before changing materials.')
            keys=[self.items.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.items.count())
                  if self.items.item(i).checkState()==Qt.CheckState.Checked]
            if not keys or not self.layer.currentText():
                raise ValueError('Choose a finite layer and at least one material.')
            materials=self.store.materials
            names=[]
            for key in keys:
                materials,name=resolve_material(self.store.context,materials,key)
                if ';' in name:
                    raise ValueError('Rename this material without a semicolon before using a categorical search.')
                names.append(name)
            self.store.set_structure(materials,self.store.layers,self.store.patterns,reason='materials')
            self.bound=dict(Parameter='layer_material',Target=self.layer.currentText(),Min=None,Max=None,Step=None,Choices=';'.join(dict.fromkeys(names)))
            self.accept()
        except Exception as exc:
            self.status.setText(str(exc))

