"""Band-focused presentation of the existing saved research artifacts."""
from __future__ import annotations

from pathlib import Path
import re
import numpy as np

from PyQt6.QtCore import Qt, QSignalBlocker
from PyQt6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from qt_research_common import label
from qt_research_results import ResearchResultsPanel


def _path_vertex_ticks(summary, data):
    """Recognize conventional cell coordinates, registered to saved samples.

    Unknown lattices or vertices retain numeric distance ticks. These names
    describe the reciprocal cell and do not assert symmetry of the motif.
    """
    try:
        cfg = summary.get('options', {})
        if not summary.get('path_connectivity', True) or cfg.get('sampling') != 'k_vertices':
            return None
        dim = cfg['dimension']
        if dim not in (2, 3):
            return None
        lattice = np.asarray(cfg['lattice_vectors'], dtype=float)[:dim]
        gram = lattice @ lattice.T
        if not np.isfinite(gram).all() or gram[0, 0] <= 0:
            return None
        metric = gram / gram[0, 0]
        if np.allclose(metric, np.eye(dim), rtol=1e-8, atol=1e-10):
            coordinates = ([(0, 0), (.5, 0), (.5, .5)] if dim == 2 else
                [(0, 0, 0), (.5, 0, 0), (.5, .5, 0), (.5, .5, .5)])
            names = ['Γ', 'X', 'M'] if dim == 2 else ['Γ', 'X', 'M', 'R']
        elif np.allclose(metric, .5 * (np.eye(dim) + np.ones((dim, dim))), rtol=1e-8, atol=1e-10):
            coordinates = ([(0, 0), (.5, 0), (2/3, 1/3)] if dim == 2 else
                [(0, 0, 0), (.5, 0, .5), (.5, .25, .75), (.375, .375, .75),
                 (.5, .5, .5), (.625, .25, .625)])
            names = ['Γ', 'M', 'K'] if dim == 2 else ['Γ', 'X', 'W', 'K', 'L', 'U']
        else:
            return None
        vertices = np.asarray(cfg['k_vertices'], dtype=float)
        if vertices.ndim != 2 or len(vertices) < 2 or vertices.shape[1] < dim or not np.isfinite(vertices).all():
            return None
        labels = []
        for vertex in vertices:
            matches = [name for point, name in zip(coordinates, names)
                       if np.allclose(vertex[:dim], point, rtol=0, atol=1e-9)]
            if len(matches) != 1:
                return None
            labels.append(matches[0])
        intervals = cfg['points_per_segment']
        if isinstance(intervals, bool) or not isinstance(intervals, int) or intervals < 1:
            return None
        distance = np.asarray(data['path_distance_reciprocal_a'], dtype=float)
        indices = np.arange(len(vertices)) * intervals
        if len(distance) != indices[-1] + 1 or not np.isfinite(distance).all() or np.any(np.diff(distance) <= 0):
            return None
        sampled = np.column_stack([data['k'+str(i+1)] for i in range(dim)])
        if sampled.shape[0] != len(distance) or not np.allclose(sampled[indices], vertices[:, :dim], rtol=0, atol=1e-9):
            return None
        return distance[indices], labels
    except (KeyError, TypeError, ValueError, IndexError):
        return None


class PhotonicBandResultsPanel(ResearchResultsPanel):
    """Keep artifact access while making the band diagram the starting point."""

    def __init__(self, store=None, engine='photonic_bands', parent=None):
        super().__init__(store, engine, parent)
        self.files.setMinimumContentsLength(12)
        self.files.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.files.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.files.setAccessibleName('Saved band dataset')
        self.export_button.setText('Export CSV…')
        actions = self.layout().itemAt(0).layout()
        actions.itemAt(0).widget().setText('Open run…')
        self.tabs.tabBar().hide()
        self.tabs.setAccessibleName('Band result views')
        self.tabs.setTabVisible(self.tabs.indexOf(self.unstructured), False)
        gap_page = QWidget()
        gap_layout = QVBoxLayout(gap_page)
        gap_layout.addWidget(label('Gaps between the calculated bands', 'setupHeading'))
        self.gap_note = label('Run a calculation to inspect gaps over its sampled wavevectors.')
        gap_layout.addWidget(self.gap_note)
        self.gaps = QTableWidget(0, 5)
        self.gaps.setAccessibleName('Sampled photonic band gaps')
        self.gaps.setHorizontalHeaderLabels(['Modes', 'After band', 'Lower a/λ', 'Upper a/λ', 'Gap / midpoint (%)'])
        self.gaps.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.gaps.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        gap_layout.addWidget(self.gaps, 1)
        gap_index = self.tabs.addTab(gap_page, 'Band gaps')
        choices = [('Band diagram', 0), ('Band gaps', gap_index), ('Data table', 1),
                   ('Paper comparison', 6), ('Compare a reference CSV', 5),
                   ('Saved arrays', 2), ('Exact run details', 4)]
        controls = QHBoxLayout()
        controls.addWidget(label('Show'))
        self.view_choice = QComboBox()
        self.view_choice.setAccessibleName('Band result view')
        for title, index in choices:
            self.view_choice.addItem(title, index)
        controls.addWidget(self.view_choice, 1)
        self.plot_controls = QCheckBox('Plot controls')
        self.plot_controls.setAccessibleName('Show custom plot axes')
        controls.addWidget(self.plot_controls)
        controls.addStretch()
        self.layout().insertLayout(2, controls)
        axis_layout = self.tabs.widget(0).layout().itemAt(0).layout()
        self._axis_controls = [axis_layout.itemAt(i).widget() for i in range(axis_layout.count())]
        self.plot_controls.toggled.connect(self._set_axis_visibility)
        self._set_axis_visibility()
        self.view_choice.currentIndexChanged.connect(self._select_view)
        self.tabs.currentChanged.connect(self._sync_view)
        self.status.setText('Your band diagram will appear here after a calculation. You can also open a saved run.')

    def _select_view(self, *_):
        index = self.view_choice.currentData()
        if index is not None:
            self.tabs.setCurrentIndex(index)

    def _set_axis_visibility(self, *_):
        show = self.plot_controls.isChecked() or bool(self.data and not any(key.startswith('band_') for key in self.data))
        for control in self._axis_controls:
            control.setVisible(show)

    def _sync_view(self, index):
        with QSignalBlocker(self.view_choice):
            self.view_choice.setCurrentIndex(self.view_choice.findData(index))

    def load_directory(self, path):
        if not super().load_directory(path):
            return False
        # An atlas may sort its bookkeeping CSV before the actual band data.
        # Select a real band dataset while keeping every saved CSV available.
        first_band = next((i for i in range(self.files.count())
            if Path(self.files.itemData(i)).name.startswith('bands_')), -1)
        if first_band >= 0:
            self.files.setCurrentIndex(first_band)
        for index in range(self.files.count()):
            raw = self.files.itemData(index)
            relative = Path(raw).relative_to(self.directory).as_posix()
            stem = Path(raw).stem
            if stem.startswith('bands_'):
                pol = stem.removeprefix('bands_')
                title = {'te': 'TE bands', 'tm': 'TM bands', 'vector': '3D vector bands'}.get(pol, pol+' bands')
                if Path(relative).parent.as_posix() != '.':
                    title += ' · '+Path(relative).parent.as_posix()
                self.files.setItemText(index, title)
            self.files.setItemData(index, relative, Qt.ItemDataRole.ToolTipRole)
        self.status.setToolTip(str(self.directory))
        self._update_summary()
        self.tabs.setCurrentIndex(0)
        return True

    def _file_changed(self, *args):
        self._data_summary = self.summary
        super()._file_changed(*args)
        if not hasattr(self, 'gaps'):
            return
        if self.data and not self._data_summary.get('path_connectivity', True) and 'k_index' in self.data:
            self.x_axis.setCurrentIndex(self.x_axis.findData('k_index'))
        for combo in (self.x_axis, self.y_axis):
            with QSignalBlocker(combo):
                for index in range(combo.count()):
                    key = combo.itemData(index)
                    combo.setItemText(index, self._column_label(key))
        self._set_axis_visibility()
        self._update_summary()

    @staticmethod
    def _column_label(key):
        if isinstance(key, str) and key.startswith('band_'):
            match = re.match(r'band_(\d+)(?:_|$)', key)
            return 'Band '+(match.group(1) if match else key[5:])
        return {'__bands__': 'All bands', 'path_distance_reciprocal_a': 'Distance along k path',
                'k_index': 'Wavevector sample', 'k1': 'Reciprocal coordinate k₁',
                'k2': 'Reciprocal coordinate k₂', 'k3': 'Reciprocal coordinate k₃'}.get(key, str(key))

    def _update_summary(self):
        summary = self._data_summary or self.summary
        state = str(self.summary.get('status', 'unreported')).replace('_', ' ').capitalize()
        parts = [state]
        if summary.get('dimension'):
            parts.append(str(summary['dimension'])+'D crystal')
        if summary.get('num_bands'):
            parts.append(str(summary['num_bands'])+' bands')
        if summary.get('k_points'):
            parts.append(str(summary['k_points'])+' wavevectors')
        parts.append('Accuracy convergence '+('established for the saved check' if
            summary.get('spatial_convergence_established') is True else 'not established'))
        self.status.setText(' · '.join(parts))
        self.gaps.setRowCount(0)
        gaps = summary.get('sampled_path_gaps', {})
        for pol, records in (gaps.items() if isinstance(gaps, dict) else []):
            if not isinstance(records, list):
                continue
            for record in records:
                if not isinstance(record, dict):
                    continue
                row = self.gaps.rowCount()
                self.gaps.insertRow(row)
                values = [pol.upper() if pol != 'vector' else '3D vector', record.get('after_band', ''),
                    record.get('lower_a_over_lambda', ''), record.get('upper_a_over_lambda', ''),
                    record.get('relative_percent', '')]
                for column, value in enumerate(values):
                    self.gaps.setItem(row, column, QTableWidgetItem(f'{value:.6g}' if isinstance(value, float) else str(value)))
        sampled = 'chosen path' if summary.get('path_connectivity', True) else 'sampled wavevectors'
        self.gap_note.setText(('No gaps recorded for this dataset. ' if not self.gaps.rowCount() else '')+
            'These bounds cover the '+sampled+'. They do not establish a complete band gap; check both accuracy and wavevector sampling.')

    def draw(self, *args):
        super().draw(*args)
        if not self.data or not self.plot.figure.axes:
            return
        axis = self.plot.figure.axes[0]
        x_key, y_key = self.x_axis.currentData(), self.y_axis.currentData()
        axis.set_xlabel('Distance along k path (normalized)' if x_key == 'path_distance_reciprocal_a'
            else self._column_label(x_key))
        axis.set_ylabel('Normalized frequency a/λ' if y_key == '__bands__' or str(y_key).startswith('band_')
            else self._column_label(y_key))
        if x_key == 'path_distance_reciprocal_a' and (y_key == '__bands__' or str(y_key).startswith('band_')):
            ticks = _path_vertex_ticks(self._data_summary or self.summary, self.data)
            if ticks is not None:
                positions, names = ticks
                axis.set_xticks(positions, names)
                axis.set_xlim(positions[0], positions[-1])
                axis.set_xlabel('Wavevector path (distance in reciprocal a)')
                for position in positions[1:-1]:
                    axis.axvline(position, color='0.5', linewidth=.7, alpha=.35)
        for line in axis.lines:
            if line.get_label().startswith('band_'):
                line.set_label(self._column_label(line.get_label()))
        handles, labels = axis.get_legend_handles_labels()
        if handles:
            axis.legend(handles, [self._column_label(name) if name.startswith('band_') else name for name in labels], fontsize=8)
        self.plot.draw_figure(self.plot.figure)

