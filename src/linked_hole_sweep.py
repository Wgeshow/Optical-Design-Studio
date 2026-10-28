"""One shared radius dimension for selected circular air regions."""
import copy
from model import number,integer

def validate_shared_options(options):
    if not isinstance(options,dict):raise ValueError('Shared hole options must be an object.')
    result=copy.deepcopy(options)
    if not isinstance(result.get('enabled',False),bool):raise ValueError('Shared hole enabled must be true or false.')
    targets=result.get('targets',[])
    if not isinstance(targets,list) or len(targets)>1000:raise ValueError('Invalid shared hole selection.')
    result['targets']=[integer(i,'Shared hole index',1) for i in targets]
    if len(set(result['targets']))!=len(targets):raise ValueError('Shared hole targets must be unique.')
    for key in ('min_um','max_um','step_um'):
        if key in result:result[key]=number(result[key],key,minimum=0)
    return result

def shared_radius_bounds(model,bounds,options):
    if options is not None:options=validate_shared_options(options)
    if not options or not options.get('enabled',False):return copy.deepcopy(bounds)
    selected=options.get('targets',[])
    if not selected:raise ValueError('Select the air holes that share a radius.')
    indices=[integer(i,'Shared hole index',1)-1 for i in selected]
    if len(indices)!=len(set(indices)):raise ValueError('Shared holes must be distinct.')
    air={m['name'] for m in model['materials'] if (m['model']=='constant_nk' and m['a']==1 and m['b']==0) or (m['model']=='constant_eps' and m['a']==1 and m['b']==0)}
    for i in indices:
        if i>=len(model['patterns']) or model['patterns'][i]['shape']!='circle' or model['patterns'][i]['material'] not in air:
            raise ValueError('Shared radius requires circular air holes from the current Structure. Reselect holes after changing Structure.')
    minimum=number(options.get('min_um'),'Shared minimum radius',minimum=0)
    maximum=number(options.get('max_um'),'Shared maximum radius',minimum=0)
    step=number(options.get('step_um'),'Shared radius step',minimum=0)
    if minimum<=0 or maximum<minimum or step<=0:raise ValueError('Shared radius requires 0 < minimum â‰¤ maximum and positive step.')
    chosen={str(i+1) for i in indices}
    result=[]
    for row in bounds:
        if str(row.get('Target')) in chosen and row.get('Parameter') in ('radius','r_over_a','size_x'):
            continue # The explicitly enabled shared controls replace per-hole radius bounds.
        if str(row.get('Target')) in chosen and row.get('Parameter')=='pattern_material':
            raise ValueError('Remove material bounds for linked air holes to keep the etched regions air.')
        result.append(copy.deepcopy(row))
    result.append(dict(Parameter='radius',Target=str(indices[0]+1),Min=minimum,Max=maximum,Step=step,Choices='',linked_targets=[i+1 for i in indices[1:]]))
    return result

def make_widget(store):
    from PyQt6.QtCore import Qt,pyqtSignal
    from PyQt6.QtWidgets import QGroupBox,QVBoxLayout,QFormLayout,QListWidget,QListWidgetItem,QCheckBox,QComboBox,QLabel
    from qt_common import number as spin
    class SharedHoleWidget(QGroupBox):
        changed=pyqtSignal()
        def __init__(self):
            super().__init__('Air hole through multiple layers')
            self.restoring=False
            layout=QVBoxLayout(self)
            self.enabled=QCheckBox('Link radii across layers');layout.addWidget(self.enabled)
            self.enabled.setToolTip('Use one shared radius variable for all checked circular air holes.')
            self.holes=QListWidget();self.holes.setMaximumHeight(145);layout.addWidget(self.holes)
            self.unit=QComboBox();self.unit.addItems(['nm','Âµm']);self.factor=1000.
            self.minimum=spin(50,1e-9,1e9,6);self.maximum=spin(150,1e-9,1e9,6);self.step=spin(25,1e-9,1e9,6)
            form=QFormLayout();form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            for label,widget in [('Radius units',self.unit),('Minimum radius',self.minimum),('Maximum radius',self.maximum),('Radius step',self.step)]:form.addRow(label,widget)
            layout.addLayout(form)
            note=QLabel('Each candidate uses exactly the same radius in every checked region. These limits replace its individual radius bounds; centers stay unchanged.');note.setWordWrap(True);layout.addWidget(note)
            self.enabled.toggled.connect(self.update_enabled)
            self.unit.currentIndexChanged.connect(self.change_unit)
            for widget in (self.minimum,self.maximum,self.step):widget.editingFinished.connect(self.changed)
            self.holes.itemChanged.connect(lambda *_:self.changed.emit() if not self.restoring else None)
            store.changed.connect(self.refresh)
            self.refresh();self.update_enabled()
        def update_enabled(self,*_):
            for w in (self.holes,self.unit,self.minimum,self.maximum,self.step):w.setEnabled(self.enabled.isChecked())
            if not self.restoring:self.changed.emit()
        def change_unit(self,*_):
            new=1000. if self.unit.currentText()=='nm' else 1.
            for widget in (self.minimum,self.maximum,self.step):widget.setValue(widget.value()*new/self.factor)
            self.factor=new
            if not self.restoring:self.changed.emit()
        def refresh(self,*_):
            selected={self.holes.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.holes.count()) if self.holes.item(i).checkState()==Qt.CheckState.Checked}
            first=self.holes.count()==0
            self.restoring=True;self.holes.clear()
            mats=store.materials.to_dict('records')
            air={m['Name'] for m in mats if m['Model'] in ('constant_nk','constant_eps') and m['A']==1 and m['B']==0}
            for i,p in enumerate(store.patterns.to_dict('records'),1):
                if p['Shape']=='circle' and p['Material'] in air:
                    item=QListWidgetItem(f"#{i} Â· {p['Layer']} Â· x={p['CenterX_um']:g}, y={p['CenterY_um']:g} Âµm")
                    item.setData(Qt.ItemDataRole.UserRole,i);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if first or i in selected else Qt.CheckState.Unchecked);self.holes.addItem(item)
            self.restoring=False
        def options(self):
            return dict(enabled=self.enabled.isChecked(),targets=[self.holes.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.holes.count()) if self.holes.item(i).checkState()==Qt.CheckState.Checked],min_um=self.minimum.value()/self.factor,max_um=self.maximum.value()/self.factor,step_um=self.step.value()/self.factor)
        def restore(self,options):
            # A new document has no saved options; restore every default rather
            # than inheriting the previous document's bounds or selection.
            values=dict(enabled=False,min_um=.05,max_um=.15,step_um=.025,
                targets=[self.holes.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.holes.count())])
            values.update(options)
            self.restoring=True
            self.enabled.setChecked(values['enabled'])
            for key,widget in [('min_um',self.minimum),('max_um',self.maximum),('step_um',self.step)]:
                widget.setValue(values[key]*self.factor)
            for i in range(self.holes.count()):
                item=self.holes.item(i);item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in values['targets'] else Qt.CheckState.Unchecked)
            self.restoring=False;self.update_enabled()
    return SharedHoleWidget()
