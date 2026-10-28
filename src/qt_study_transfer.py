"""Explicit, reviewable transfer of compatible structure inputs."""
import json
from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QLabel,
    QVBoxLayout, QTreeWidget, QTreeWidgetItem)
from qt_simulation_picker import SIMULATIONS
from simulation_documents import transfer_sections, transfer_inputs, payload


def _research_state(project, key):
    return project.get('desktop_search', {}).get('research_workspaces', {}).get(key, {})


def _structured_values(raw):
    """Read display values from the saved typed tree without coercing drafts."""
    if not isinstance(raw, dict) or 'type' not in raw:
        return raw
    children = raw.get('children', [])
    if raw['type'] == 'array':
        return [_structured_values(child) for child in children]
    if raw['type'] == 'object':
        return {child['name']: _structured_values(child) for child in children}
    return raw.get('value')


def transfer_preview_rows(before, after, destination_id):
    """Describe copied physical inputs, not their project-storage containers."""
    rows = []
    def add(title, old, new):
        if old != new:
            rows.append((title, old, new))
    if destination_id.startswith('photonic_bands'):
        old, new = (_research_state(value, 'bands') for value in (before, after))
        for key, title in (('lattice', 'Crystal lattice vectors'), ('geometry', 'Crystal objects')):
            add(title, old.get(key), new.get(key))
        def materials(state):
            names = {identity: row[0] for identity, row in zip(state.get('object_ids', []), state.get('geometry', [])) if row}
            return [{'name': names.get(identity, 'Crystal object'), 'relative permittivity': value}
                    for identity, value in state.get('epsilons', {}).items()]
        add('Crystal material permittivities', materials(old), materials(new))
        for key, title in (('reference_length_um', 'Crystal length scale (µm)'),
                           ('background_epsilon', 'Background relative permittivity')):
            add(title, old.get('fields', {}).get(key), new.get('fields', {}).get(key))
        add('Paper comparison attachment', old.get('benchmark_request'), new.get('benchmark_request'))
    elif destination_id.startswith('pcsel.'):
        old, new = (_research_state(value, 'model_pcsel_research') for value in (before, after))
        for key, title in (('layers', 'Layer stack and refractive indices'), ('shapes', 'Crystal inclusions')):
            add(title, _structured_values(old.get('structured', {}).get(key)), _structured_values(new.get('structured', {}).get(key)))
        for key, title in (('lattice_nm', 'Square lattice pitch (nm)'), ('inclusion_index', 'Inclusion refractive index'),
                           ('top_index', 'Top half-space refractive index'), ('bottom_index', 'Bottom half-space refractive index')):
            add(title, old.get('fields', {}).get(key), new.get('fields', {}).get(key))
        add('Paper comparison attachment', old.get('benchmark_request'), new.get('benchmark_request'))
    else:
        labels = {'materials': 'Optical material data', 'layers': 'Optical layer stack', 'patterns': 'Optical material regions',
                  'electrical_materials': 'Device material properties', 'optical_constants': 'Optical constant tables',
                  'material_provenance': 'Material sources'}
        for key, title in labels.items():
            add(title, before.get(key), after.get(key))
        old, new = before.get('device') or {}, after.get('device') or {}
        labels = {'name': 'Device name', 'width_um': 'Device width (µm)', 'depth_um': 'Device depth (µm)',
                  'layers': 'Device layers', 'shapes': 'Device shapes', 'contacts': 'Contact geometry',
                  'doping_regions': 'Doping regions', 'pc_arrays': 'Pattern arrays'}
        for key, title in labels.items():
            add(title, old.get(key), new.get(key))
        old, new = before.get('settings') or {}, after.get('settings') or {}
        labels = {'ax_um': 'Period X (µm)', 'ay_um': 'Period Y (µm)', 'a1': 'First lattice vector',
                  'a2': 'Second lattice vector', 'lattice': 'Lattice geometry',
                  'material_interpolations': 'Optical material interpolation', 'optical_unit_cell': 'Optical unit cell'}
        for key, title in labels.items():
            add(title, old.get(key), new.get(key))
    add('Project paper comparison attachment', before.get('benchmark_request'), after.get('benchmark_request'))
    return rows


def describe_component(value):
    if value is None:
        return 'Not set'
    if value == [] or value == {}:
        return 'Empty'
    if isinstance(value, list):
        labels = []
        for row in value[:3]:
            if isinstance(row, dict):
                title = str(row.get('name', row.get('Name', row.get('shape', 'Item'))))
                if 'relative permittivity' in row:
                    title += ': ε = ' + str(row['relative permittivity'])
                elif 'thickness_nm' in row:
                    title += ': ' + str(row['thickness_nm']) + ' nm'
                labels.append(title)
            elif isinstance(row, list):
                labels.append(', '.join(map(str, row[:3])))
            else:
                labels.append(str(row))
        return str(len(value)) + (' item: ' if len(value) == 1 else ' items: ') + '; '.join(labels) + ('; …' if len(value) > 3 else '')
    if isinstance(value, dict):
        return str(value.get('label') or value.get('title') or value.get('id') or str(len(value)) + ' properties')
    return str(value)


class StudyTransferDialog(QDialog):
    def __init__(self,store,parent=None):
        super().__init__(parent)
        self.store=store
        self.setWindowTitle('Transfer inputs to this simulation')
        self.resize(850,560)
        layout=QVBoxLayout(self)
        names={row[0]:row[1] for row in SIMULATIONS}
        heading=QLabel('Destination: '+names.get(store.active_study,store.active_study))
        heading.setWordWrap(True);layout.addWidget(heading)
        self.source=QComboBox();self.source.setAccessibleName('Simulation to copy structure from')
        for identifier in store.project()['simulation_documents']['documents']:
            if transfer_sections(identifier,store.active_study):self.source.addItem(names.get(identifier,identifier),identifier)
        layout.addWidget(self.source)
        self.summary=QLabel();self.summary.setWordWrap(True);layout.addWidget(self.summary,1)
        self.preview=QTreeWidget(self)
        self.preview.setHeaderLabels(['Component', 'Destination now', 'After copying'])
        self.preview.setRootIsDecorated(False)
        self.preview.setAccessibleName('Exact compatible input replacement preview')
        layout.addWidget(self.preview,3)
        self.scope=QLabel('Solver, sampling and operating parameters stay in this simulation. Copying creates independent values.',self)
        self.scope.setWordWrap(True);layout.addWidget(self.scope)
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
        self.preview.clear()
        if not identifier:return
        try:
            project=self.store.project()
            destination=payload(project)
            incoming=project['simulation_documents']['documents'][identifier]
            result=transfer_inputs(incoming,destination,identifier,self.store.active_study)
            for title, old, new in transfer_preview_rows(destination, result, self.store.active_study):
                item = QTreeWidgetItem([title, describe_component(old), describe_component(new)])
                item.setToolTip(1, json.dumps(old, ensure_ascii=False, indent=2)[:12000])
                item.setToolTip(2, json.dumps(new, ensure_ascii=False, indent=2)[:12000])
                self.preview.addTopLevelItem(item)
            if not self.preview.topLevelItemCount():
                self.preview.addTopLevelItem(QTreeWidgetItem(['No input differences','Already matches','Already matches']))
            for column in (0,1):self.preview.resizeColumnToContents(column)
        except (ValueError,TypeError,KeyError) as exc:
            self.summary.setText('Cannot preview this transfer: '+str(exc))
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
