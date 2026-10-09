"""Native 3D replay of complete saved electromagnetic snapshots."""
import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel, QSlider, QCheckBox

from field_volume import load_volume, vectors, amplitude, field_surface, visible_samples, interaction_surface
from field_tracking_ui import saved_datasets, _safe_directory
from qt_common import ActionStatusLabel
from qt_native_field_volume import NativeFieldVolumePlot, NativeSurfaceMesh
from qt_materials import choices


class FieldVolumeWidget(QWidget):
    def __init__(self, store, parent=None, campaign=False):
        super().__init__(parent)
        self.store = store
        self.campaign = campaign
        self.directory = None
        self.data = None
        self.arrow = None
        self.surfaces = []
        self.dragging = False
        self.restore_timer = QTimer(self)
        self.restore_timer.setSingleShot(True)
        self.restore_timer.setInterval(120)
        self.restore_timer.timeout.connect(self.finish_interaction)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(lambda: self.phase.setValue((self.phase.value()+10) % 360))
        root = QVBoxLayout(self)
        note = QLabel('Replay a saved S4 solution in 3D. Colors show phasor intensity; arrows show the instantaneous field. Phase playback does not run a simulation or predict a changed design.')
        self.setToolTip(note.text())
        self.snapshot = QComboBox()
        self.snapshot.setAccessibleName('Saved field snapshot')
        self.snapshot.setMinimumContentsLength(25)
        self.snapshot.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        root.addWidget(self.snapshot)
        row = QHBoxLayout()
        self.refresh_button = QPushButton('Refresh snapshots')
        self.load_button = QPushButton('Load 3D fields')
        self.mode = QComboBox()
        self.mode.setAccessibleName('Field quantity')
        self.mode.addItems(['E', 'H', 'Energy flow'])
        self.mode.setToolTip('Electric field, magnetic field, or time-averaged Poynting vector')
        self.layer = QComboBox()
        self.layer.setAccessibleName('Visible field layer')
        for widget in (self.refresh_button, self.load_button, self.mode, self.layer):
            row.addWidget(widget)
        root.addLayout(row)
        visibility = QHBoxLayout()
        self.style = QComboBox()
        self.style.setAccessibleName('Field rendering style')
        self.style.addItems(['Continuous shape', 'Sample points'])
        self.style.setToolTip('Surface detail is reduced temporarily during rotation and arrow playback. Full detail returns when idle.')
        self.threshold = QSlider(Qt.Orientation.Horizontal)
        self.threshold.setRange(0,100)
        self.threshold.setValue(20)
        self.threshold.setTracking(False)
        self.threshold.setAccessibleName('Minimum visible intensity or power flow, percent of snapshot peak')
        self.threshold_label = QLabel('Hide below 20% of peak')
        self.show_arrows = QCheckBox('Field arrows')
        self.show_arrows.setChecked(False)
        visibility.addWidget(self.style)
        visibility.addWidget(self.threshold_label)
        visibility.addWidget(self.threshold,1)
        visibility.addWidget(self.show_arrows)
        root.addLayout(visibility)
        playback = QHBoxLayout()
        self.play = QPushButton('Play')
        self.play.setCheckable(True)
        self.phase = QSlider(Qt.Orientation.Horizontal)
        self.phase.setRange(0,359)
        self.phase.setAccessibleName('Optical phase in degrees')
        self.phase_label = QLabel('0°')
        playback.addWidget(self.play)
        playback.addWidget(self.phase,1)
        playback.addWidget(self.phase_label)
        root.addLayout(playback)
        self.plot = NativeFieldVolumePlot(paper_factory=self.publication_figure)
        self.plot.setMinimumHeight(420)
        root.addWidget(self.plot,1)
        self.plot.canvas.interaction_started.connect(self.start_interaction)
        self.plot.canvas.interaction_finished.connect(self.end_interaction)
        self.load_button.setToolTip('Calculate field maps in Simulation, then load a saved snapshot here. Phase playback replays the stored solution.')
        self.status = ActionStatusLabel('')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.status)
        self.refresh_button.clicked.connect(self.refresh)
        self.load_button.clicked.connect(self.load)
        self.mode.currentIndexChanged.connect(self.render)
        self.layer.currentIndexChanged.connect(self.render)
        self.style.currentIndexChanged.connect(self.render)
        self.threshold.valueChanged.connect(self.render)
        self.show_arrows.toggled.connect(self.animate)
        self.show_arrows.toggled.connect(self.update_playback_controls)
        self.phase.valueChanged.connect(self.animate)
        self.play.toggled.connect(self.toggle)
        self.snapshot.currentIndexChanged.connect(self.invalidate)
        if not campaign:
            store.library_changed.connect(self.refresh)
            self.refresh()
        else:
            for widget in (self.snapshot, self.refresh_button, self.load_button):
                widget.hide()
        self.controls(False)

    def controls(self, enabled):
        for widget in (self.mode, self.layer, self.phase, self.play, self.style, self.threshold, self.show_arrows):
            widget.setEnabled(enabled)

    def invalidate(self, *_):
        self.play.setChecked(False)
        self.restore_timer.stop()
        self.dragging = False
        self.surfaces = []
        self.data = None
        self.arrow = None
        self.controls(False)
        self.plot.clear()
        self.status.setText('')

    def refresh(self, *_):
        selected = self.snapshot.currentData()
        choices(self.snapshot, saved_datasets(self.store.library), selected)
        self.load_button.setEnabled(self.snapshot.currentData() is not None)
        if self.data is not None and self.snapshot.currentData() != selected:
            self.invalidate()

    def load(self):
        self.invalidate()
        try:
            self.data = load_volume(self.directory if self.campaign else _safe_directory(self.store.library, self.snapshot.currentData()))
            self.layer.blockSignals(True)
            self.layer.clear()
            self.layer.addItem('All layers', '')
            for name in self.data[1]['layer'].unique():
                self.layer.addItem(str(name), str(name))
            self.layer.blockSignals(False)
            self.mode.blockSignals(True)
            self.mode.clear()
            self.mode.addItems((['E', 'Ex', 'Ey', 'Ez'] if self.campaign else ['E']) + (['H', 'Energy flow'] if 'H' in self.data[3] else []))
            self.mode.blockSignals(False)
            self.controls(True)
            self.render()
        except Exception as exc:
            self.data = None
            self.controls(False)
            self.status.setText(str(exc))

    def load_directory(self, directory):
        """Bind the embedded viewer to the selected campaign observation."""
        from pathlib import Path
        path = Path(directory).resolve() if directory else None
        if path == self.directory and self.data is not None:
            return
        self.directory = path
        self.invalidate()
        if path is None:
            self.status.setText('')
            return
        self.load()

    def render(self, *_):
        if self.data is None:
            return
        self.play.setChecked(False)
        self.restore_timer.stop()
        self.dragging = False
        self.surfaces = []
        metadata, frame, xyz, fields = self.data
        mode = self.mode.currentText()
        mask = np.ones(len(frame), dtype=bool) if not self.layer.currentData() else (frame['layer'].to_numpy() == self.layer.currentData())
        values = amplitude(fields, mode)
        visible, cutoff = visible_samples(values,self.threshold.value())
        self.threshold_label.setText(f'Hide below {self.threshold.value()}% of peak')
        ids = np.flatnonzero(mask & visible)
        # Bound rendering work; all analysis and scales use the complete saved volume.
        ids = ids[np.linspace(0,len(ids)-1,min(len(ids),1800),dtype=int)]
        self.ids = ids
        self.arrow_ids = ids[np.linspace(0,len(ids)-1,min(len(ids),180),dtype=int)]
        peak=max(float(values.max()),1e-30)
        surface_error = ''
        self.surface_faces = 0
        self.interaction_faces = 0
        if self.style.currentText() == 'Continuous shape':
            layer_count = len(frame.loc[mask,'layer'].unique())
            for name in frame.loc[mask,'layer'].unique():
                layer_mask = frame['layer'].to_numpy() == name
                try:
                    faces = field_surface(xyz[layer_mask],values[layer_mask],cutoff)
                    self.surface_faces += len(faces)
                    if len(faces):
                        surface = NativeSurfaceMesh(faces,cutoff/peak)
                        reduced = interaction_surface(faces,max(24,900//layer_count))
                        self.interaction_faces += len(reduced)
                        fast = NativeSurfaceMesh(reduced,cutoff/peak,visible=False)
                        self.surfaces.append((surface,fast))
                except ValueError as exc:
                    surface_error = str(exc)+' Use Sample points for this snapshot.'
        label = '|⟨S⟩| (S4 units)' if mode == 'Energy flow' else f'|{mode}|² (S4 units)'
        self.arrow = None
        # Fixed normalization over the cycle preserves amplitude changes.
        bound = np.sqrt(values) if mode != 'Energy flow' else values
        self.scale = .12 * min(metadata['model']['ax'],metadata['model']['ay']) / max(float(bound.max()),1e-30)
        self.plot.set_scene(metadata['model'],xyz[ids],values[ids],
            [mesh for pair in self.surfaces for mesh in pair],peak,
            f'{mode} · {metadata["wavelength_nm"]:g} nm',label,
            samples_mode=self.style.currentText()=='Sample points')
        self.animate()
        dynamic = mode != 'Energy flow'
        self.update_playback_controls()
        self.phase.setEnabled(dynamic)
        depths = frame.loc[mask].groupby('layer')['z_um'].nunique()
        quantity = 'Power-flow magnitude' if mode == 'Energy flow' else 'Field intensity'
        details = f'{quantity} cutoff: {cutoff:.4g} S4 units ({self.threshold.value()}% of the complete snapshot peak). ' + ('Surface interpolated within each layer and capped at sampled boundaries; interpolation adds no simulated detail. ' if self.style.currentIndex()==0 else f'Up to 1,800 original sample points displayed; normalization uses all {len(frame):,} saved samples. ') + ('Energy flow is time averaged.' if not dynamic else 'Shape shows steady-state intensity; enable Field arrows to see phase oscillation.')
        self.status.setText(f'{int(np.sum(mask & visible)):,} / {int(mask.sum()):,} samples · cutoff {cutoff:.4g} S4 units' +
                            (' · No field above cutoff' if not np.any(mask & visible) else '') +
                            (' · ' + surface_error if surface_error else ''))
        self.status.setToolTip(details)

    def animate(self, *_):
        self.phase_label.setText(f'{self.phase.value()}°')
        if self.data is None:
            return
        if self.dragging:
            return
        if not self.show_arrows.isChecked():
            if self.arrow is not None:self.arrow.remove();self.arrow=None
            return
        ids = self.arrow_ids
        points = self.data[2][ids]
        selected_fields = {name: field[ids] for name,field in self.data[3].items()}
        values = vectors(selected_fields,self.mode.currentText(),self.phase.value()) * self.scale
        self.arrow = self.plot.canvas.set_vectors(points,values)

    def toggle(self, checked):
        self.play.setText('Pause' if checked else 'Play')
        self.set_interaction_detail(checked or self.dragging)
        self.timer.start() if checked and not self.dragging else self.timer.stop()
        if self.data is not None:
            self.plot.canvas.draw_idle()

    def update_playback_controls(self, *_):
        enabled = self.data is not None and self.mode.currentText() != 'Energy flow' and self.show_arrows.isChecked()
        if not enabled:
            self.play.setChecked(False)
        self.play.setEnabled(enabled)
        self.play.setToolTip('Enable Field arrows to animate their optical phase.' if not self.show_arrows.isChecked() else '')

    def set_interaction_detail(self, fast):
        self.plot.canvas.fast=bool(fast)
        for full, simplified in self.surfaces:
            full.set_visible(not fast)
            simplified.set_visible(fast)

    def start_interaction(self, event=None):
        if self.data is None:
            return
        self.restore_timer.stop()
        self.dragging = True
        self.timer.stop()
        self.set_interaction_detail(True)
        if self.arrow is not None:
            self.arrow.set_visible(False)
        self.plot.canvas.draw_idle()

    def end_interaction(self, event=None):
        if self.dragging:
            self.restore_timer.start()

    def finish_interaction(self):
        self.dragging = False
        self.set_interaction_detail(self.play.isChecked())
        if self.arrow is not None:
            self.arrow.set_visible(True)
        if self.data is not None:
            self.animate()
            self.plot.canvas.draw_idle()
        if self.play.isChecked():
            self.timer.start()

    def hideEvent(self, event):
        self.play.setChecked(False)
        self.restore_timer.stop()
        self.dragging = False
        self.set_interaction_detail(False)
        if self.arrow is not None:
            self.arrow.set_visible(True)
        super().hideEvent(event)

    def publication_figure(self):
        """Build an offline export only; live playback has no Matplotlib artists."""
        if self.data is None:raise ValueError('Load a saved field snapshot before exporting.')
        from matplotlib.figure import Figure
        from matplotlib.colors import Normalize, LightSource
        from matplotlib.cm import ScalarMappable
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        from field_volume import draw_geometry
        metadata,frame,xyz,fields=self.data
        mode=self.mode.currentText();values=amplitude(fields,mode)
        _,cutoff=visible_samples(values,self.threshold.value())
        figure=Figure(figsize=(8,6));figure.subplots_adjust(left=.02,right=.86,bottom=.12,top=.90)
        axis=figure.add_subplot(111,projection='3d')
        axis.view_init(elev=self.plot.canvas.elevation,azim=self.plot.canvas.azimuth)
        draw_geometry(axis,metadata['model'])
        colors=ScalarMappable(norm=Normalize(0,max(float(values.max()),1e-30)),cmap='inferno')
        if self.style.currentText()=='Continuous shape':
            for full,_ in self.surfaces:
                if len(full.faces):
                    axis.add_collection3d(Poly3DCollection(full.faces,facecolors=colors.to_rgba(cutoff),linewidths=0,alpha=1.,zsort='average',shade=True,lightsource=LightSource(azdeg=315,altdeg=45),antialiased=False))
        else:axis.scatter(*xyz[self.ids].T,c=values[self.ids],s=12,alpha=.65,cmap='inferno',norm=colors.norm)
        if self.show_arrows.isChecked():
            ids=self.arrow_ids;direction=vectors({name:field[ids] for name,field in fields.items()},mode,self.phase.value())*self.scale
            axis.quiver(*xyz[ids].T,*direction.T,color='#24a8d8',normalize=False,linewidth=.8)
        figure.colorbar(colors,ax=axis,shrink=.65,label='|⟨S⟩| (S4 units)' if mode=='Energy flow' else f'|{mode}|² (S4 units)')
        axis.set_title(f'{mode} · {metadata["wavelength_nm"]:g} nm')
        return figure
