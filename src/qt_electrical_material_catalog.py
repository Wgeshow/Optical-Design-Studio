"""Full-width native electrical library, shared with the device and solver."""
from copy import deepcopy

from PyQt6.QtCore import Qt, QSignalBlocker, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFileDialog,
    QFormLayout, QGridLayout, QHeaderView, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPlainTextEdit, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget)

from electrical_material_library import (PROPERTY_FIELDS, builtin_materials,
    conductivity_S_m, evaluate_material, export_materials, import_materials,
    lookup_material, merge_materials, new_material, validate_materials)
from qt_common import ActionStatusLabel, number
from qt_electrical_materials import ElectricalMaterialDialog
from qt_surfaces import WorkspacePanel


class ElectricalMaterialCatalog(QWidget):
    materialSelected=pyqtSignal(str)

    def __init__(self,store,parent=None):
        super().__init__(parent)
        self.setObjectName('electricalMaterialsWorkspace')
        self.store=store
        self._presets={row['id']:row for row in builtin_materials()}
        self._loading=False
        root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0);root.setSpacing(10)
        self.columns=QSplitter(Qt.Orientation.Horizontal);self.columns.setChildrenCollapsible(False)
        root.addWidget(self.columns,1)
        library,left=self._panel('Electrical material library')
        self.columns.addWidget(library)
        from PyQt6.QtWidgets import QLineEdit
        self.query=QLineEdit();self.query.setPlaceholderText('Search name, ID, or material type…');self.query.setClearButtonEnabled(True)
        self.query.setAccessibleName('Search electrical materials');left.addWidget(self.query)
        self.material_list=QListWidget();self.material_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.material_list.setIconSize(QSize(26,26))
        self.material_list.setAccessibleName('Project electrical materials');left.addWidget(self.material_list,1)
        self.count=QLabel();self.count.setObjectName('muted');left.addWidget(self.count)
        actions=QGridLayout();actions.setSpacing(6);left.addLayout(actions)
        self.add_button=QPushButton('Add custom');self.add_button.setProperty('primary',True)
        self.edit_button=QPushButton('Edit');self.clone_button=QPushButton('Duplicate')
        self.import_button=QPushButton('Import JSON');self.export_button=QPushButton('Export JSON')
        self.remove_button=QPushButton('Remove')
        for index,(button,handler) in enumerate(((self.add_button,self.add_material),(self.edit_button,self.edit_material),
                (self.clone_button,self.duplicate_material),(self.import_button,self.import_library),
                (self.export_button,self.export_library),(self.remove_button,self.remove_material))):
            actions.addWidget(button,index//3,index%3);button.clicked.connect(handler)
        self.reset_button=QPushButton('Add missing built-in presets');self.reset_button.clicked.connect(self.add_missing_presets)
        left.addWidget(self.reset_button)
        properties,center=self._panel('Electrical properties')
        self.columns.addWidget(properties)
        self.property_title=QLabel();self.property_title.setObjectName('sectionTitle');center.addWidget(self.property_title)
        self.model_summary=QLabel();self.model_summary.setWordWrap(True);self.model_summary.setObjectName('muted');center.addWidget(self.model_summary)
        temperature_row=QHBoxLayout();temperature_row.addWidget(QLabel('Evaluate at temperature'))
        self.temperature=number(float(getattr(store,'device',{}).get('temperature_K',300.)),50.,1500.,2)
        self.temperature.setSuffix(' K');self.temperature.setAccessibleName('Electrical material evaluation temperature')
        temperature_row.addWidget(self.temperature);temperature_row.addStretch(1);center.addLayout(temperature_row)
        self.property_table=QTableWidget(0,4);self.property_table.setHorizontalHeaderLabels(['Property','Saved reference','Evaluated','Unit'])
        self.property_table.verticalHeader().hide();self.property_table.setAlternatingRowColors(True)
        self.property_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.property_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.property_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        for column in (1,2,3):self.property_table.horizontalHeader().setSectionResizeMode(column,QHeaderView.ResizeMode.ResizeToContents)
        self.property_table.setMinimumHeight(300);self.property_table.setAccessibleName('Saved and temperature evaluated electrical properties')
        center.addWidget(self.property_table,1)
        self.conductivity=QLabel();self.conductivity.setWordWrap(True);center.addWidget(self.conductivity)
        note=QLabel('Static εr is used by Poisson. Optical dispersion uses the linked optical dataset. Evaluation here previews the saved model; it does not change device temperature or doping.')
        note.setWordWrap(True);note.setObjectName('muted');center.addWidget(note)
        details,right=self._panel('Identity, links & sources')
        self.columns.addWidget(details)
        self.identity=QLabel();self.identity.setWordWrap(True);self.identity.setTextFormat(Qt.TextFormat.PlainText);right.addWidget(self.identity)
        self.optical_link=QComboBox();self.optical_link.setAccessibleName('Linked optical material dataset')
        form=QFormLayout();form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow('Optical dataset',self.optical_link);right.addLayout(form)
        self.link_button=QPushButton('Save optical link');self.link_button.clicked.connect(self.save_optical_link);right.addWidget(self.link_button)
        self.link_note=QLabel();self.link_note.setWordWrap(True);self.link_note.setObjectName('muted');right.addWidget(self.link_note)
        self.assignment=QComboBox();self.assignment.setAccessibleName('Device layer for electrical material assignment')
        assignment_form=QFormLayout();assignment_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        assignment_form.addRow('Device layer',self.assignment);right.addLayout(assignment_form)
        self.assign_button=QPushButton('Apply material to layer');self.assign_button.clicked.connect(self.assign_to_layer);right.addWidget(self.assign_button)
        self.sources=QPlainTextEdit();self.sources.setReadOnly(True);self.sources.setMinimumHeight(210)
        self.sources.setAccessibleName('Electrical material authentic source records and assumptions');right.addWidget(self.sources,1)
        self.details=self.sources
        self.status=ActionStatusLabel();self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText);root.addWidget(self.status)
        self.query.textChanged.connect(self.filter_materials)
        self.material_list.currentItemChanged.connect(self._selection_changed)
        self.material_list.itemDoubleClicked.connect(lambda _:self.edit_material())
        self.temperature.valueChanged.connect(self._selection_changed)
        if hasattr(store,'changed'):store.changed.connect(self.refresh)
        if hasattr(store,'busy_changed'):store.busy_changed.connect(self._busy)
        self.columns.setSizes([300,650,380]);self.refresh()

    @staticmethod
    def _panel(title):
        panel=WorkspacePanel();layout=QVBoxLayout(panel);layout.setContentsMargins(14,14,14,14);layout.setSpacing(10)
        label=QLabel(title);label.setObjectName('sectionTitle');layout.addWidget(label)
        panel.setMinimumWidth(0)
        return panel,layout

    def _library(self):
        values=self.store.electrical_materials
        return validate_materials(values() if callable(values) else values)

    def selected_material_id(self):
        item=self.material_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def select_material(self,ident):
        self.query.clear()
        for index in range(self.material_list.count()):
            item=self.material_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole)==ident:
                self.material_list.setCurrentItem(item);return True
        return False

    def refresh(self,reason=None,selected=None):
        if self._loading:return
        selected=selected or self.selected_material_id()
        self._loading=True
        materials=self._library();self._material_by_id={row['id']:row for row in materials}
        with QSignalBlocker(self.material_list):
            self.material_list.clear()
            for material in materials:
                origin='Built-in preset' if material['id'] in self._presets else 'Custom material'
                if material['id'] in self._presets and material!=self._presets[material['id']]:origin+=' · edited'
                item=QListWidgetItem(f"{material['name']}\n{material['kind']} · {origin}")
                swatch=QPixmap(24,24);color=QColor(material.get('color','#64b7ac'))
                swatch.fill(color if color.isValid() else QColor('#64b7ac'));item.setIcon(QIcon(swatch))
                item.setSizeHint(QSize(0,62))
                item.setData(Qt.ItemDataRole.UserRole,material['id']);item.setToolTip(material['id'])
                self.material_list.addItem(item)
                if material['id']==selected:self.material_list.setCurrentItem(item)
            if self.material_list.currentItem() is None and self.material_list.count():self.material_list.setCurrentRow(0)
        self._loading=False;self.filter_materials();self._selection_changed()

    def filter_materials(self,*_):
        term=self.query.text().strip().casefold();visible=0
        for index in range(self.material_list.count()):
            item=self.material_list.item(index)
            material=self._material_by_id[item.data(Qt.ItemDataRole.UserRole)]
            hidden=term not in ' '.join([item.text(),material['id'],*material.get('aliases',[])]).casefold()
            item.setHidden(hidden);visible+=not hidden
        self.count.setText(f'{visible} of {self.material_list.count()} materials · stable project IDs' if visible else 'No materials match. Clear the search to see the library.')

    def _selection_changed(self,*_):
        ident=self.selected_material_id()
        for button in (self.edit_button,self.clone_button,self.remove_button,self.link_button,self.assign_button):button.setEnabled(bool(ident) and not getattr(self.store,'busy',False))
        if not ident:
            self.property_title.setText('Select a material');self.property_table.setRowCount(0);self.sources.clear();return
        material=lookup_material(self._library(),ident)
        try:evaluated=evaluate_material(material,self.temperature.value())
        except ValueError as exc:
            self.status.setText(str(exc));return
        self.property_title.setText(material['name'])
        self.model_summary.setText(f"{material['kind'].title()} · {material.get('model','constant')} · reference {material['temperature_K']:g} K")
        self.identity.setText(f"Stable ID: {ident}\nReference model: {material.get('model','constant')}"+
            (f"\nAl fraction x: {material['al_fraction']:g}" if 'al_fraction' in material else ''))
        rows=[(key,label,unit) for key,label,unit in PROPERTY_FIELDS if key in material['properties'] or key in evaluated['properties']]
        self.property_table.setRowCount(len(rows))
        for index,(key,label,unit) in enumerate(rows):
            for column,value in enumerate((label,material['properties'].get(key),evaluated['properties'].get(key),unit)):
                text='—' if value is None else f'{value:.8g}' if isinstance(value,(int,float)) else str(value)
                item=QTableWidgetItem(text);item.setToolTip(text);self.property_table.setItem(index,column,item)
        try:self.conductivity.setText(f'Material equilibrium / fixed conductivity: {conductivity_S_m(evaluated):.8g} S/m. Device carrier density is evaluated separately by the selected electrical model.')
        except ValueError as exc:self.conductivity.setText(str(exc))
        names=getattr(self.store,'materials',[])
        names=list(names['Name']) if hasattr(names,'columns') else [row.get('Name',row.get('name','')) for row in names]
        link=material.get('optical_material_name','')
        with QSignalBlocker(self.optical_link):
            self.optical_link.clear();self.optical_link.addItem('No linked dataset','')
            for name in names:self.optical_link.addItem(str(name),str(name))
            if link and self.optical_link.findData(link)<0:self.optical_link.addItem(link+' (missing from optical project)',link)
            self.optical_link.setCurrentIndex(max(0,self.optical_link.findData(link)))
        self.link_note.setText('Linked dataset is available in Optical materials.' if link in names else 'The selected optical dataset is not in the optical project.' if link else 'No optical dataset is linked. Electrical properties remain usable by themselves.')
        previous=self.assignment.currentData()
        with QSignalBlocker(self.assignment):
            self.assignment.clear()
            for layer in getattr(self.store,'device',{}).get('layers',[]):self.assignment.addItem(layer['name'],layer['id'])
            self.assignment.setCurrentIndex(max(0,self.assignment.findData(previous)))
        self.assign_button.setEnabled(bool(self.assignment.count()) and not getattr(self.store,'busy',False))
        lines=['Sources and assumptions',material.get('notes','')]
        for source in material.get('sources',[]):lines.extend(['',source.get('title',''),source.get('url',''),source.get('note','')])
        self.sources.setPlainText('\n'.join(lines))

    def _edit(self,material):
        if getattr(self.store,'busy',False):return
        dialog=ElectricalMaterialDialog(material,self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            value=dialog.material();self.store.set_electrical_materials(merge_materials(self._library(),[value]))
            self.refresh(selected=value['id']);self.status.setText(f"Saved {value['name']} ({value['id']}).")

    def add_material(self):self._edit(new_material())

    def edit_material(self):
        ident=self.selected_material_id()
        if ident:self._edit(lookup_material(self._library(),ident))

    def duplicate_material(self):
        ident=self.selected_material_id()
        if ident:
            original=lookup_material(self._library(),ident)
            self._edit(new_material(original['name']+' copy',original))

    def remove_material(self):
        ident=self.selected_material_id()
        if not ident or getattr(self.store,'busy',False):return
        uses=[obj['name'] for group in ('layers','shapes','doping_regions') for obj in getattr(self.store,'device',{}).get(group,[]) if obj.get('material_id')==ident]
        if uses:
            self.status.setText('Reassign this material before removing it. Used by: '+', '.join(uses[:12]));return
        self.store.set_electrical_materials([row for row in self._library() if row['id']!=ident]);self.refresh()
        self.status.setText('Removed unused electrical material '+ident+'.')

    def import_library(self):
        if getattr(self.store,'busy',False):return
        filename,_=QFileDialog.getOpenFileName(self,'Import electrical materials','','Electrical material library (*.json)')
        if not filename:return
        try:
            incoming=import_materials(filename);self.store.set_electrical_materials(merge_materials(self._library(),incoming))
            self.refresh(selected=incoming[0]['id'] if incoming else None);self.status.setText(f'Imported {len(incoming)} material definitions.')
        except (OSError,ValueError) as exc:self.status.setText('Import failed: '+str(exc))

    def export_library(self):
        filename,_=QFileDialog.getSaveFileName(self,'Export electrical materials','electrical-materials.json','Electrical material library (*.json)')
        if not filename:return
        try:export_materials(filename,self._library());self.status.setText('Exported electrical library to '+filename+'.')
        except (OSError,ValueError) as exc:self.status.setText('Export failed: '+str(exc))

    def add_missing_presets(self):
        if getattr(self.store,'busy',False):return
        current=self._library();ids={row['id'] for row in current}
        missing=[row for row in builtin_materials() if row['id'] not in ids]
        self.store.set_electrical_materials(current+missing);self.refresh();self.status.setText(f'Added {len(missing)} missing presets; existing edits retained.')

    def save_optical_link(self):
        ident=self.selected_material_id()
        if not ident or getattr(self.store,'busy',False):return
        material=lookup_material(self._library(),ident);material['optical_material_name']=self.optical_link.currentData() or ''
        self.store.set_electrical_materials(merge_materials(self._library(),[material]));self.refresh(selected=ident)
        self.status.setText('Saved optical dataset link for '+material['name']+'.')

    def assign_to_layer(self):
        ident=self.selected_material_id();layer_id=self.assignment.currentData()
        if not ident or not layer_id or getattr(self.store,'busy',False):return
        device=deepcopy(self.store.device)
        layer=next(row for row in device['layers'] if row['id']==layer_id);layer['material_id']=ident
        self.store.set_device(device);self.status.setText(f"Assigned {lookup_material(self._library(),ident)['name']} to {layer['name']}.")
        self.materialSelected.emit(ident)

    def _busy(self,busy):
        for button in (self.add_button,self.edit_button,self.clone_button,self.import_button,self.remove_button,self.reset_button,self.link_button,self.assign_button):button.setEnabled(not busy)
        if not busy:self._selection_changed()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if not hasattr(self,'columns'):return
        orientation=Qt.Orientation.Vertical if self.width()<1000 else Qt.Orientation.Horizontal
        if self.columns.orientation()!=orientation:
            self.columns.setOrientation(orientation);self.columns.setSizes([320,600,380] if orientation==Qt.Orientation.Horizontal else [350,600,450])

