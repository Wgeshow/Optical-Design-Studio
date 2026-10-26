"""Saved electromagnetic phasor fields and specular phase, independent of DC fields."""
from pathlib import Path
import json
import shutil

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt,QSignalBlocker
from PyQt6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QComboBox,QLabel,
    QPushButton,QTabWidget,QSpinBox,QCheckBox,QFileDialog)
from qt_common import PlotWidget,table,fill_table
from qt_compute import FieldSamplesModel,phase_preview
from qt_field_volume import FieldVolumeWidget
from field_storage import load_field_frame,field_data_exists,field_data_path,export_field_csv


QUANTITIES=[('|E|','E2'),('|Ex|','Ex'),('|Ey|','Ey'),('|Ez|','Ez'),
    ('|H|','H2'),('|Hx|','Hx'),('|Hy|','Hy'),('|Hz|','Hz'),
    ('Energy flow |S|','S2')]


def optical_map_figure(frame,quantity='E2',layer=None,logarithmic=False):
    """Plot saved values; never relabel electromagnetic fields as DC volts/metre."""
    figure=Figure(figsize=(10,5),layout='constrained')
    axes=figure.subplots(1,2)
    data=frame.copy()
    if quantity in ('E2','H2'):
        prefix=quantity[0]
        cols=[prefix+axis+suffix for axis in 'xyz' for suffix in ('_real','_imag')]
        if not all(key in data for key in cols):
            if quantity!='E2' or 'E2' not in data:
                data=pd.DataFrame()
            else:data['value']=np.sqrt(np.maximum(data['E2'],0))
        else:data['value']=np.sqrt(sum(np.square(pd.to_numeric(data[key],errors='coerce')) for key in cols))
    elif quantity=='S2':
        cols=['Sx','Sy','Sz']
        if not all(key in data for key in cols):data=pd.DataFrame()
        else:data['value']=np.sqrt(sum(np.square(pd.to_numeric(data[key],errors='coerce')) for key in cols))
    elif all(quantity+suffix in data for suffix in ('_real','_imag')):
        data['value']=np.hypot(data[quantity+'_real'],data[quantity+'_imag'])
    else:data=pd.DataFrame()
    for axis,plane,vertical in ((axes[0],'xy','y_um'),(axes[1],'xz','z_um')):
        rows=data[data['plane']==plane] if 'plane' in data else pd.DataFrame()
        if plane=='xy' and layer is not None and 'layer' in rows:rows=rows[rows['layer']==layer]
        if rows.empty:
            axis.text(.5,.5,'No saved samples for this quantity/plane',ha='center',va='center',transform=axis.transAxes)
            axis.set_axis_off();continue
        grid=rows.pivot_table(index=vertical,columns='x_um',values='value',aggfunc='first').sort_index()
        values=grid.to_numpy()
        if logarithmic:values=np.log10(np.maximum(values,1e-16))
        image=axis.pcolormesh(grid.columns,grid.index,values,shading='nearest',cmap='turbo')
        label=next((label for label,key in QUANTITIES if key==quantity),quantity)
        unit='Saved S4 source normalization' if quantity[0]=='E' else 'Saved S4 magnetic-field units' if quantity[0]=='H' else 'Time-averaged ½ Re(E × H*)'
        figure.colorbar(image,ax=axis,label=('log₁₀ ' if logarithmic else '')+label+' · '+unit)
        axis.set(xlabel='X (µm)',ylabel='Y (µm)' if plane=='xy' else 'Depth (µm)',
            title=('XY · '+str(layer) if layer else 'XY') if plane=='xy' else 'XZ · full saved stack')
        axis.set_aspect('equal',adjustable='box')
        if plane=='xz':axis.invert_yaxis()
    return figure


class OpticalFieldResultsPanel(QWidget):
    def __init__(self,store,parent=None):
        super().__init__(parent)
        self.store=store;self.directory=None;self.sample_directory=None
        self.frame=pd.DataFrame();self.sample_count=0;self._model=None
        self.setObjectName('opticalFieldResults')
        layout=QVBoxLayout(self);layout.setContentsMargins(10,10,10,10);layout.setSpacing(8)
        note=QLabel('Optical E/H phasors from saved S4 solutions. These are source-normalized electromagnetic fields; electrical Poisson fields use a separate category.')
        note.setWordWrap(True);layout.addWidget(note)
        row=QHBoxLayout();self.samples=QComboBox();self.samples.setAccessibleName('Saved optical field sample')
        self.samples.setMinimumContentsLength(18);self.samples.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.position=QSpinBox();self.position.setRange(1,1);self.position.setAccessibleName('Optical field sample number')
        self.quantity=QComboBox()
        for label,key in QUANTITIES:self.quantity.addItem(label,key)
        self.layer=QComboBox();self.layer.setAccessibleName('Optical XY layer')
        self.logarithmic=QCheckBox('Log amplitude')
        for widget in (self.samples,self.position,self.quantity,self.layer,self.logarithmic):row.addWidget(widget)
        layout.addLayout(row)
        self.tabs=QTabWidget();self.plot=PlotWidget();self.plot.setMinimumHeight(300);self.plot.toolbar.hide()
        self.volume=FieldVolumeWidget(store,campaign=True);self.volume.plot.setMinimumHeight(300)
        self.data_table=table([])
        self.tabs.addTab(self.plot,'XY / XZ maps');self.tabs.addTab(self.volume,'3D E/H playback');self.tabs.addTab(self.data_table,'Saved samples')
        layout.addWidget(self.tabs,1)
        exports=QHBoxLayout()
        for label,handler in [('Export selected sample CSV…',self.export_csv),('Export selected sample NPZ…',self.export_npz),('Export field figure…',self.export_figure)]:
            button=QPushButton(label);button.clicked.connect(handler);exports.addWidget(button)
        layout.addLayout(exports)
        self.status=QLabel('No saved optical field samples.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.samples.currentIndexChanged.connect(self._sample_changed)
        self.position.valueChanged.connect(self._position_changed)
        self.quantity.currentIndexChanged.connect(self.draw)
        self.layer.currentIndexChanged.connect(self.draw)
        self.logarithmic.toggled.connect(self.draw)
        self.tabs.currentChanged.connect(self.draw)

    def set_directory(self,directory):
        self.directory=Path(directory) if directory else None
        self.sample_directory=None;self.frame=pd.DataFrame();self.sample_count=0
        old=self.samples.model()
        with QSignalBlocker(self.samples):
            self.samples.clear()
            root=self.directory/'fields' if self.directory else None
            if root and (root/'samples.sqlite').is_file():
                self._model=FieldSamplesModel(root,self.samples);self.samples.setModel(self._model);self.sample_count=len(self._model.index)
            else:
                from PyQt6.QtGui import QStandardItemModel
                self.samples.setModel(QStandardItemModel(self.samples));self._model=None
                manifest=root/'samples.json' if root else None
                if manifest and manifest.is_file():
                    saved=json.loads(manifest.read_text(encoding='utf-8'))
                    for ordinal,sample in enumerate(saved.get('samples',[])):
                        folder=Path(sample['directory']);folder=folder if folder.is_absolute() else root/folder
                        local=root if ordinal==0 else root/'samples'/f'{ordinal+1:06d}'
                        if field_data_exists(local):folder=local
                        elif not folder.exists() and (root/folder.name).exists():folder=root/folder.name
                        self.samples.addItem(f"{sample['wavelength_nm']:g} nm · {sample['angle_deg']:g}°",str(folder))
                    self.sample_count=self.samples.count()
            if self.samples.count():self.samples.setCurrentIndex(0)
        if isinstance(old,FieldSamplesModel) and old is not self._model:old.deleteLater()
        with QSignalBlocker(self.position):self.position.setRange(1,max(1,self.sample_count));self.position.setValue(1)
        self.samples.setEnabled(bool(self.sample_count));self.position.setEnabled(bool(self.sample_count))
        self._sample_changed()

    def _position_changed(self,value):
        if self._model:
            with QSignalBlocker(self.samples):self._model.set_page(value-1);self.samples.setCurrentIndex(value-1-self._model.offset)
            self._sample_changed()
        else:self.samples.setCurrentIndex(value-1)

    def _sample_changed(self,*_):
        path=self.samples.currentData()
        self.sample_directory=Path(path) if path else None
        self.frame=pd.DataFrame()
        try:
            if self.sample_directory and field_data_exists(self.sample_directory):self.frame=load_field_frame(self.sample_directory)
            with QSignalBlocker(self.layer):
                self.layer.clear()
                if 'layer' in self.frame and 'plane' in self.frame:
                    for name in self.frame.loc[self.frame['plane']=='xy','layer'].unique():self.layer.addItem(str(name),str(name))
            offset=self._model.offset if self._model else 0
            with QSignalBlocker(self.position):self.position.setValue(max(1,offset+self.samples.currentIndex()+1))
            fill_table(self.data_table,self.frame.iloc[:5000])
            self.status.setText(f'{self.sample_count:,} saved wavelength/angle samples · {len(self.frame):,} actual field points in this sample. Table previews up to 5,000 rows; exports retain all rows.' if not self.frame.empty else 'No complete field arrays are saved for this sample.')
            self.volume.invalidate();self.volume.directory=None
            self.draw()
        except (ValueError,KeyError,TypeError,OSError) as exc:self.status.setText(str(exc))

    def draw(self,*_):
        if self.tabs.currentIndex()==1:
            self.volume.load_directory(self.sample_directory)
        elif self.tabs.currentIndex()==0:
            self.plot.draw_figure(optical_map_figure(self.frame,self.quantity.currentData(),self.layer.currentData(),self.logarithmic.isChecked()))

    def export_csv(self):
        if self.sample_directory is None:return
        filename,_=QFileDialog.getSaveFileName(self,'Export complete optical field sample','optical-fields.csv','CSV (*.csv)')
        if filename:export_field_csv(self.sample_directory,filename)

    def export_figure(self):
        if self.tabs.currentIndex()==1:self.volume.plot.export_dialog()
        else:self.plot.export_dialog()

    def export_npz(self):
        if self.sample_directory is None:return
        source=field_data_path(self.sample_directory)
        if source.suffix!='.npz':self.status.setText('This legacy sample stores CSV only; export CSV to retain its complete data.');return
        filename,_=QFileDialog.getSaveFileName(self,'Export complete optical field arrays','optical-fields.npz','NumPy arrays (*.npz)')
        if filename:shutil.copyfile(source,filename)


class SpecularPhaseResultsPanel(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.frame=pd.DataFrame();self.path=None;self.reference_path=None
        layout=QVBoxLayout(self);layout.setContentsMargins(10,10,10,10)
        note=QLabel('One full cycle is 2π radians = 2 in Phase / π = 360°. Unwrapping uses every saved sample before preview selection and resets after undefined signals or independent sweep branches. Resolve adjacent phase changes below π with sufficiently fine sampling.')
        note.setWordWrap(True);layout.addWidget(note)
        from spectral_phase import PHASE_MODES,PHASE_UNITS
        controls=QHBoxLayout()
        self.phase_mode=QComboBox();self.phase_mode.setAccessibleName('Phase wrapping mode')
        self.phase_unit=QComboBox();self.phase_unit.setAccessibleName('Phase display units')
        for label,key in PHASE_MODES:self.phase_mode.addItem(label,key)
        for label,key in PHASE_UNITS:self.phase_unit.addItem(label,key)
        controls.addWidget(QLabel('Display'));controls.addWidget(self.phase_mode)
        controls.addWidget(QLabel('Units'));controls.addWidget(self.phase_unit);controls.addStretch()
        layout.addLayout(controls)
        references=QHBoxLayout();self.phase_reference=QComboBox();self.phase_reference.setAccessibleName('Phase reference convention')
        self.phase_reference.addItem('Absolute · stack boundary planes','boundary')
        self.phase_reference.addItem('Relative · physical reference CSV','csv')
        references.addWidget(QLabel('Reference'));references.addWidget(self.phase_reference)
        choose=QPushButton('Choose reference CSV…');choose.clicked.connect(self.choose_reference_csv);references.addWidget(choose);references.addStretch()
        layout.addLayout(references)
        self.reference_label=QLabel('Boundary phase includes propagation between the saved stack planes. A physical reference must use matching polarization and boundary planes; CSV coordinates are checked exactly.')
        self.reference_label.setWordWrap(True);layout.addWidget(self.reference_label)
        self.plot=PlotWidget();self.plot.toolbar.hide();layout.addWidget(self.plot,1)
        self.data_table=table([]);self.data_table.setMaximumHeight(180);layout.addWidget(self.data_table)
        row=QHBoxLayout()
        export=QPushButton('Export complete phase CSV…');export.clicked.connect(self.export_csv);row.addWidget(export)
        display=QPushButton('Export display CSV…');display.clicked.connect(self.export_display_csv);row.addWidget(display)
        figure=QPushButton('Export phase figure…');figure.clicked.connect(self.plot.export_dialog);row.addWidget(figure)
        layout.addLayout(row);self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        self.phase_mode.currentIndexChanged.connect(self.draw)
        self.phase_unit.currentIndexChanged.connect(self.draw)
        self.phase_reference.currentIndexChanged.connect(self._reference_changed)

    def set_path(self,path):
        self.path=Path(path) if path and Path(path).is_file() else None
        self.frame=pd.DataFrame()
        reference_error=''
        if self.path:
            try:self._load_phase()
            except (OSError,ValueError) as exc:
                reference_error=str(exc)
                with QSignalBlocker(self.phase_reference):self.phase_reference.setCurrentIndex(0)
                self._load_phase()
        self.draw()
        if reference_error:self.status.setText(reference_error+' Showing absolute boundary phase.')

    def _load_phase(self):
        reference=self.reference_path if self.phase_reference.currentData()=='csv' else None
        self.frame=phase_preview(self.path,None,reference_path=reference) if self.path else pd.DataFrame()

    def _reference_changed(self,*_):
        if self.phase_reference.currentData()=='csv' and self.reference_path is None:
            with QSignalBlocker(self.phase_reference):self.phase_reference.setCurrentIndex(0)
            self.status.setText('Choose a complete matching reference phase CSV first.');return
        try:self._load_phase();self.draw()
        except (OSError,ValueError) as exc:
            with QSignalBlocker(self.phase_reference):self.phase_reference.setCurrentIndex(0)
            self._load_phase();self.draw();self.status.setText(str(exc)+' Showing absolute boundary phase.')

    def set_reference_path(self,path):
        from spectral_phase import read_phase_preview
        path=Path(path)
        try:frame=read_phase_preview(self.path,reference_path=path) if self.path else pd.DataFrame()
        except (OSError,ValueError) as exc:self.status.setText(str(exc));return False
        self.reference_path=path;self.frame=frame
        with QSignalBlocker(self.phase_reference):self.phase_reference.setCurrentIndex(self.phase_reference.findData('csv'))
        self.draw();return True

    def choose_reference_csv(self):
        if not self.path:return
        filename,_=QFileDialog.getOpenFileName(self,'Choose complete physical reference phase CSV',str(self.path.parent),'CSV (*.csv)')
        if filename:self.set_reference_path(filename)

    def draw(self,*_):
        from spectral_phase import phase_figure,phase_display_frame
        mode,unit=self.phase_mode.currentData(),self.phase_unit.currentData()
        self.plot.draw_figure(phase_figure(self.frame,mode,unit))
        fill_table(self.data_table,phase_display_frame(self.frame,mode,unit).iloc[:5000])
        count=self.frame.attrs.get('phase_sample_count',len(self.frame))
        if self.frame.attrs.get('phase_reference_mode')=='reference_csv':
            label='/'.join(self.reference_path.parts[-3:])
            self.reference_label.setText(f'Reference-relative phase: {label}. Exact matching grid; arg(response / reference). Assumes matching polarization and physical boundary planes; undefined sample or reference signals remain gaps.')
            self.reference_label.setToolTip(str(self.reference_path.resolve()))
        else:
            self.reference_label.setText('Absolute boundary phase includes propagation between the top and bottom stack planes. Compare a physical reference CSV only when polarization and reference planes match.')
            self.reference_label.setToolTip('')
        self.status.setText(f'{len(self.frame):,} preview rows from {count:,} complete saved phase samples. Full raw CSV remains in degrees; display CSV adds the selected mode / units for every sample.' if self.path else 'No specular phase CSV was saved. Enable phase in Optical outputs and run an S4 spectrum.')

    def export_csv(self):
        if not self.path:return
        filename,_=QFileDialog.getSaveFileName(self,'Export complete specular phase','specular-phase.csv','CSV (*.csv)')
        if filename:shutil.copyfile(self.path,filename)

    def export_display_csv(self):
        if not self.path:return
        from spectral_phase import export_phase_display_csv
        filename,_=QFileDialog.getSaveFileName(self,'Export complete phase with display units','specular-phase-display.csv','CSV (*.csv)')
        if filename:
            try:export_phase_display_csv(self.path,filename,self.phase_mode.currentData(),self.phase_unit.currentData(),self.reference_path if self.phase_reference.currentData()=='csv' else None)
            except (OSError,ValueError) as exc:self.status.setText(str(exc))
