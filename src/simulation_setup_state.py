"""Shared native setup bindings for standalone and coupled simulations.

The plan supplies presentation metadata. The project and existing solver
validators remain authoritative: illustrative mockup values are never loaded
into a user's device. Optical cell selection never changes its finite size.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal


@lru_cache(maxsize=1)
def _plan():
    return json.loads(Path(__file__).with_name('simulation_setup_plan.json').read_text(encoding='utf-8'))


def load_plan():
    """Return the packaged, editable presentation catalog, without demo state."""
    return copy.deepcopy(_plan())


def _nested(value, path, default=None):
    for part in path.split('.') if path else []:
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def _assign(value, path, item):
    parts = path.split('.')
    for part in parts[:-1]:
        value = value.setdefault(part, {})
    value[parts[-1]] = copy.deepcopy(item)


def _finite(value, label, low=None, high=None, integer=False):
    if isinstance(value, bool):
        raise ValueError(label + ' must be a finite number.')
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(label + ' must be a finite number.') from None
    if not math.isfinite(number):
        raise ValueError(label + ' must be a finite number.')
    if low is not None and number < low or high is not None and number > high:
        raise ValueError(label + ' is outside its allowed range.')
    if integer and not number.is_integer():
        raise ValueError(label + ' must be a whole number.')
    return int(number) if integer else number


class SimulationSetupState(QObject):
    changed = pyqtSignal(str)
    UI_NAMESPACE = 'simulation_setup'
    ELECTRICAL_KEYS = {'model', 'biases_V', 'charge_model', 'swept_contact_id',
        'terminal_studies', 'transport', 'mesh_level', 'ito_thickness_nm', 'ito_density_cm3',
        'sheet_resistance_ohm_square', 'geometry', 'current_offset',
        'temperature_K', 'measured_current'}
    TRANSFER_KEYS = {'optical_reference', 'optical_mapping', 'optical_slices_per_layer',
        'electro_optic', 'interband', 'interband_extrapolation', 'r41_gaas_m_V',
        'r41_algaas_m_V', 'response', 'feature', 'reference_nm', 'tracking_window_nm'}

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._fields = {}
        self._readonly = {}
        for mode in _plan()['modes'].values():
            for tab in mode['tabs']:
                for card in tab.get('cards', []):
                    for field in card.get('fields', []):
                        key = field['key']
                        if key not in self._fields or field['widget'] != 'readonly':
                            self._fields[key] = field
                        self._readonly[key] = self._readonly.get(key, True) and field['widget'] in ('readonly', 'table')
        self._validation = {}
        self._model = None
        self._implicit_cell = None
        self._implicit_cell_key = None
        self._mesh = None
        self._runtime = {}
        store.changed.connect(self._source_changed)
        store.busy_changed.connect(lambda busy: self.changed.emit('busy'))

    def _source_changed(self, reason='project'):
        presentation = str(reason).startswith('ui.') and not str(reason).startswith(('ui.optical.outputs.', 'ui.optical.engine', 'ui.coupled.unsupported_output_policy'))
        if not presentation:
            self._model = None
            self._implicit_cell = None
            self._implicit_cell_key = None
            self._mesh = None
            self._validation.clear()
        self.changed.emit(reason)

    def project(self):
        return self.store.project()

    def _ui(self):
        return self.store.search_state.get(self.UI_NAMESPACE, {}).get('values', {})

    def _ui_default(self, key, fallback=None):
        if key in self._ui():
            return copy.deepcopy(self._ui()[key])
        field = self._fields.get(key, {})
        if field.get('widget') == 'table':
            return []
        if field.get('widget') == 'readonly' and field.get('derived_from'):
            return 'Not checked'
        return copy.deepcopy(field.get('default', fallback))

    def _save_ui(self, key, value):
        state = copy.deepcopy(self.store.search_state.get(self.UI_NAMESPACE, {}))
        _assign(state, 'values', dict(self._ui(), **{key: copy.deepcopy(value)}))
        self.store.save_search(self.UI_NAMESPACE, state)
        self._source_changed(key)

    def _commit_parts(self, *, settings=None, performance=None, search=None):
        """Use the store's atomic whole-project validator for linked controls."""
        project = self.store.project()
        if settings is not None:
            project['settings'] = settings
        if performance is not None:
            project['performance'] = performance
        if search is not None:
            project['desktop_search'] = search
        undo = list(self.store._undo)
        self.store.load_project(project)
        self.store._undo = undo

    def _electrical_options(self):
        from electrical_solver import DEFAULT_OPTIONS
        model = self.store.search_state.get('electrical', {}).get('model')
        source = self.store.search_state.get('electrical')
        if not source:
            source = self.store.search_state.get('coupled', {})
            model = source.get('model')
        model = model or ('custom_device' if self.store.device else DEFAULT_OPTIONS['model'])
        if model == 'custom_device':
            result = dict(model=model, biases_V=[0., -2.], charge_model='semiconductor',
                swept_contact_id='', terminal_studies=dict(iv_enabled=False, cv_enabled=False,
                    measured_iv_path='', measured_cv_path=''))
            allowed = {'model', 'biases_V', 'charge_model', 'swept_contact_id', 'terminal_studies', 'transport'}
        else:
            result = copy.deepcopy(DEFAULT_OPTIONS)
            result['model'] = model
            allowed = self.ELECTRICAL_KEYS - {'charge_model', 'swept_contact_id', 'terminal_studies', 'transport'}
        result.update({k: copy.deepcopy(v) for k, v in source.items() if k in allowed})
        if model == 'custom_device':
            # Getters often read only one scalar. Defer the full canonical
            # copy to solver validation/job creation, not every widget refresh.
            result['device'] = self.store.device
            result['material_library'] = self.store.electrical_materials
            # Electrical-only preparation is independent of optical cell
            # drafts. Coupled jobs add the real current selection below.
            result['optical_unit_cell'] = dict(enabled=False,
                width_um=(self.store.device or {}).get('width_um', 1.),
                depth_um=(self.store.device or {}).get('depth_um', 1.),
                cx_um=0., cy_um=0.)
            if not result.get('swept_contact_id'):
                active = self._contacts()
                result['swept_contact_id'] = active[-1]['id'] if active else ''
        result['optical_enabled'] = False
        return result

    def _transfer_options(self):
        source = self.store.search_state.get('coupled') or self.store.search_state.get('electrical', {})
        start, stop = self._band()
        result = dict(optical_reference='undoped', optical_slices_per_layer=8,
            electro_optic=False, interband=False, interband_extrapolation=False,
            r41_gaas_m_V=1.68e-12, response='Absorption', feature='Peak',
            reference_nm=min(stop, max(start, 1550.)), tracking_window_nm=30., optical_mapping={})
        result.update({k: copy.deepcopy(v) for k, v in source.items() if k in self.TRANSFER_KEYS})
        if self._electrical_options()['model'] != 'custom_device':
            result.setdefault('r41_algaas_m_V', 1.2e-12)
        else:
            result.pop('r41_algaas_m_V', None)
        return result

    def _contacts(self):
        layers = {row['id'] for row in (self.store.device or {}).get('layers', []) if row.get('enabled', True)}
        return [row for row in (self.store.device or {}).get('contacts', [])
            if row.get('enabled', True) and row['layer_id'] in layers]

    def _layers(self):
        return [row for row in (self.store.device or {}).get('layers', []) if row.get('enabled', True)]

    def selected_contact(self):
        ident = self._ui().get('ui.electrical.selected_contact_id')
        all_contacts = (self.store.device or {}).get('contacts', [])
        return copy.deepcopy(next((row for row in all_contacts if row['id'] == ident),
            self._contacts()[-1] if self._contacts() else all_contacts[-1] if all_contacts else {}))

    def _selected_material(self):
        ident = self._ui().get('ui.electrical.selected_material_id')
        materials = self.store.electrical_materials
        if ident is None and self._layers():
            ident = self._layers()[0]['material_id']
        return next((row for row in materials if row['id'] == ident), materials[0] if materials else {})

    def _band(self):
        settings = self.store.settings
        if self.get('ui.optical.engine') == 'meep':
            return (self.get('search.fdtd.wavelength_min_nm'), self.get('search.fdtd.wavelength_max_nm'))
        if settings['mode'] == 'Angle sweep':
            return (float(settings['fixed_wl_nm']),) * 2
        return sorted((float(settings['wl_start_nm']), float(settings['wl_stop_nm'])))

    def _sampling(self):
        from model import sweep_range
        s = self.store.settings
        if self.get('ui.optical.engine') == 'meep':
            lo, hi = self._band()
            count = self.get('search.fdtd.frequency_points')
            return dict(first=lo, last=hi, count=count, stop=hi, theta=0., axis='frequency', start=lo, step=0.)
        angle = s['mode'] == 'Angle sweep'
        start, step, count = sweep_range(s['angle_start' if angle else 'wl_start_nm'],
            s['angle_stop' if angle else 'wl_stop_nm'], s['angle_step' if angle else 'wl_step_nm'],
            'Angle' if angle else 'Wavelength', limit=361 if angle else 20_000_000)
        return dict(first=start, last=start+(count-1)*step, count=count,
            stop=s['angle_stop' if angle else 'wl_stop_nm'], theta=s['theta_deg'],
            axis='angle' if angle else 'wavelength', start=start, step=step)

    def _prepared_model(self):
        if self._model is None:
            from model import prepare
            from device_project_bridge import apply_polygons, validate_optical_assignment
            from optical_unit_cell import pc_unit_cell_issue
            message=pc_unit_cell_issue(self.get('settings.optical_unit_cell'),self.store.device)
            if message:raise ValueError(message)
            project = self.store.project()
            self._model = prepare(project['materials'], project['layers'], project['patterns'],
                self.store.library.files_for(project), project['settings'], compact_points=True)
            apply_polygons(self._model, project)
            validate_optical_assignment(self._model)
        return self._model

    def get(self, key, default=None):
        """Read current project values or an honest derived presentation value."""
        if key == 'ui.constant.false':
            return False
        if key.startswith('device.contacts[{'):
            return _nested(self.selected_contact(), key.split('].', 1)[1], default)
        if key.startswith('settings.'):
            if key.startswith('settings.optical_unit_cell'):
                from optical_unit_cell import resolve_unit_cell
                # A complete numeric draft may temporarily extend outside its
                # device; physical fit belongs to Validate/Run, not readback.
                device=self.store.device or dict(width_um=self.store.settings['ax_um'],depth_um=self.store.settings['ay_um'])
                config=self.store.settings.get('optical_unit_cell')
                if config is None or config=={}:
                    # All setup tabs share this resolver. Scan a dense PC's
                    # members once per applied source change, not per control.
                    token=(id(self.store.device),device.get('width_um'),device.get('depth_um'))
                    if token!=self._implicit_cell_key:
                        self._implicit_cell=resolve_unit_cell(config,device,require_fit=False)
                        self._implicit_cell_key=token
                    value=self._implicit_cell
                else:
                    value=resolve_unit_cell(config,device,require_fit=False)
                suffix = key[len('settings.optical_unit_cell'):].lstrip('.')
                return copy.deepcopy(_nested(value, suffix, default))
            return copy.deepcopy(_nested(self.store.settings, key[9:], default))
        if key.startswith('performance.'):
            return copy.deepcopy(_nested(self.store.performance, key[12:], default))
        if key.startswith('device.'):
            return copy.deepcopy(_nested(self.store.device or {}, key[7:], default))
        if key.startswith('search.electrical.'):
            return copy.deepcopy(_nested(self._electrical_options(), key[18:], default))
        if key.startswith('search.coupled.'):
            return copy.deepcopy(_nested(self._transfer_options(), key[15:], default))
        if key.startswith('search.fdtd.'):
            from fdtd_model import DEFAULTS
            return copy.deepcopy(_nested(dict(DEFAULTS, **self.store.search_state.get('fdtd', {})), key[12:], default))
        if key.startswith('search.simulation.'):
            from simulation_fields import DEFAULTS
            values = dict(measure_phase=False, single_wavelength=True, wavelength_source='manual',
                wavelength_nm=1550., electric_fields=copy.deepcopy(DEFAULTS))
            values.update(self.store.search_state.get('simulation', {}))
            return copy.deepcopy(_nested(values, key[18:], default))
        if key == 'ui.optical.engine':
            return self._ui().get(key, 's4')
        if key == 'ui.optical.study_type':
            s = self.store.settings
            return ('angle_sweep' if s['mode'] == 'Angle sweep' else
                'single' if s['wl_start_nm'] == s['wl_stop_nm'] else 'wavelength_sweep')
        if key == 'ui.optical.single.wavelength_nm':
            return float(self.store.settings['wl_start_nm']) if self.get('ui.optical.study_type') == 'single' else self._ui().get(key, self.store.settings['fixed_wl_nm'])
        if key == 'ui.electrical.study':
            iv = self.get('search.electrical.terminal_studies.iv_enabled', False)
            cv = self.get('search.electrical.terminal_studies.cv_enabled', False)
            return 'both' if iv and cv else 'iv' if iv else 'cv' if cv else 'bias'
        if key == 'ui.electrical.selected_contact_id':
            return self.selected_contact().get('id', '')
        if key == 'ui.electrical.selected_material_id':
            return self._selected_material().get('id', '')
        if key.startswith('ui.electrical.transport_'):
            cfg = self.get('search.electrical.transport', {}) or {}
            mode = cfg.get('mode', 'disabled')
            if key == 'ui.electrical.transport_requires_native': return mode == 'semiconductor_dd'
            if key == 'ui.electrical.transport_mode':
                from qt_transport_setup import MODE_LABELS
                return MODE_LABELS.get(mode, mode)
            if key == 'ui.electrical.transport_scope':
                if mode == 'semiconductor_dd':
                    from qt_transport_setup import transport_path_hint
                    path = transport_path_hint(self.store.device, cfg)
                    return 'Expected actual 3D transport mesh for this geometry/statistics; Validate setup checks the supported materials and interfaces.' if path == 'graph' else 'Expected uniform planar transport with a native depth grid; Validate setup checks the current model and geometry.'
                return 'Explicit material laws require geometry and voltage validity checks; field criteria do not predict post-damage conduction.' if mode == 'dielectric_leakage' else 'Transport disabled. Static electrostatic reservoirs and optional frozen Ohmic estimates keep their existing scope.'
            if key == 'ui.electrical.transport_sources':
                rows = [[name.replace('_', ' ').title(), 'Semiconductor', cfg[name]['parameter_source']] for name in ('srh', 'high_field_mobility', 'avalanche') if cfg.get(name)]
                if cfg.get('heterojunction'): rows.append(['Ideal quasi-Fermi interface', 'Semiconductor interfaces', cfg['heterojunction']['parameter_source']])
                materials = {row['id']: row['name'] for row in self.store.electrical_materials}
                rows += [[model['mechanism'].replace('_', ' ').title(), materials.get(mid, mid), model['parameters']['parameter_source']] for mid, model in cfg.get('material_models', {}).items()]
                rows += [['Critical field criterion', materials.get(mid, mid), group['parameter_source']] for mid, group in cfg.get('breakdown_fields', {}).items()]
                return rows
            if key == 'ui.electrical.transport_discretization':
                from qt_transport_setup import transport_path_hint
                if transport_path_hint(self.store.device, cfg) == 'graph':
                    mesh = (self.store.device or {}).get('mesh', {})
                    layers = sum(row.get('enabled', True) for row in (self.store.device or {}).get('layers', []))
                    return f"Actual 3D Structure mesh {mesh.get('nx', 0)} × {mesh.get('ny', 0)} × {mesh.get('nz_per_layer', 0)*layers} · planar depth setting inactive · continuation maximum {cfg.get('max_bias_step_V', .1):g} V"
                per = cfg.get('nodes_per_layer', max(4, (self.store.device or {}).get('mesh', {}).get('nz_per_layer', 4)))
                return f'{per:,} target depth intervals / layer · maximum internal continuation step {cfg.get("max_bias_step_V", .1):g} V · separate from the finite mesh and output voltage samples'
        if key == 'ui.electrical.custom_bounds':
            return 'Finite voltage inputs and exact requested sweep points; RAM planning and the selected physical model are validated before Run.'
        transport_mode = (self.get('search.electrical.transport', {}) or {}).get('mode', 'disabled') if key in ('ui.electrical.method', 'ui.electrical.iv_method', 'ui.electrical.iv_properties', 'ui.electrical.statistics', 'ui.electrical.semiconductor_gate', 'ui.electrical.dielectric_gate', 'ui.electrical.semiconductor_equation', 'ui.electrical.reservoirs', 'ui.electrical.outer_boundary', 'ui.electrical.saved_checks') else 'disabled'
        if transport_mode != 'disabled':
            if key == 'ui.electrical.method': return 'DEVSIM coupled Poisson + electron/hole continuity' if transport_mode == 'semiconductor_dd' else 'Static dielectric field + explicit sourced leakage laws'
            if key == 'ui.electrical.iv_method': return 'Contact current from electron/hole continuity with the configured generation/recombination laws.' if transport_mode == 'semiconductor_dd' else 'Configured material leakage laws; points outside their validity are reported unavailable.'
            if key == 'ui.electrical.statistics' and transport_mode == 'semiconductor_dd': return 'Experimental bulk parabolic-band Fermi–Dirac statistics on the actual 3D graph; Boltzmann SRH is unavailable.' if (self.get('search.electrical.transport', {}) or {}).get('statistics', 'boltzmann') == 'fermi_dirac' else 'Boltzmann transport statistics; model checks nondegenerate carrier limits.'
            if key == 'ui.electrical.semiconductor_gate' and transport_mode == 'semiconductor_dd': return 'Forward/reverse states require validated transport geometry, model parameters and converged continuity equations.'
            if key == 'ui.electrical.semiconductor_equation' and transport_mode == 'semiconductor_dd': return 'Coupled Poisson + electron/hole continuity with the selected statistics, full ionization and configured compatible generation/recombination laws.'
            if key == 'ui.electrical.dielectric_gate' and transport_mode == 'dielectric_leakage': return 'Finite voltages with explicit sourced material leakage laws and optional critical-field screening; invalid current points are unavailable. No AC or post-damage conduction.'
            if key == 'ui.electrical.iv_properties': return 'Evaluated semiconductor bands, populations and mobilities plus the applied generation/recombination groups; current follows continuity.' if transport_mode == 'semiconductor_dd' else 'Applied material leakage law and its sourced parameters; current availability follows model and field validity.'
            if key == 'ui.electrical.reservoirs' and transport_mode == 'semiconductor_dd': return 'Ideal ohmic contact populations use local material and doping; contact currents are solved by continuity, with geometry and model validity checked.'
            if key == 'ui.electrical.outer_boundary' and transport_mode == 'semiconductor_dd': return 'Uncontacted/void faces have zero normal carrier current and natural zero displacement flux; interfaces follow the selected transport model.'
            if key == 'ui.electrical.saved_checks': return 'Native Poisson/continuity convergence, independent Gauss and terminal-current balance, requested state counts, sources and model validity.' if transport_mode == 'semiconductor_dd' else 'Static field convergence, independent Gauss balance, sourced leakage evaluation and explicit field/model validity for every requested state.'
        if key == 'ui.electrical.sweep_mode':
            return self._ui().get(key, 'manual')
        if key == 'ui.electrical.range_sampling':
            return self._ui().get(key, 'step')
        if key == 'ui.electrical.bias_point_count':
            return self._ui().get(key, 101)
        if key in ('ui.electrical.bias_start_V', 'ui.electrical.bias_stop_V'):
            values = self.get('search.electrical.biases_V', [0.])
            return self._ui().get(key, min(values) if 'start' in key else max(values))
        if key == 'ui.electrical.bias_step_V':
            values = sorted(set(self.get('search.electrical.biases_V', [0.])))
            return self._ui().get(key, min((b-a for a,b in zip(values,values[1:])), default=.05))
        if key == 'ui.electrical.bias_list_text':
            return self._ui().get(key, ', '.join(f'{v:.17g}' for v in self.get('search.electrical.biases_V', [])))
        if key == 'ui.electrical.range_summary':
            try:
                from electrical_sweep import describe_sweep
                plan = describe_sweep(**self._range_options())
                spacing = f"{plan['spacing_V']:.12g} V " + ('spacing' if plan['sampling'] == 'count' else 'step') if plan['requested_count'] > 1 else 'single state'
                if plan['requested_count'] > 1 and not math.isclose(plan['final_interval_V'], plan['spacing_V'], rel_tol=1e-12, abs_tol=0.):
                    spacing += f" · final interval {plan['final_interval_V']:.12g} V"
                return f"{plan['requested_count']:,} range points · {plan['resolved_count']:,} distinct solved states including zero reference · both endpoints included · {spacing}"
            except (ValueError, TypeError, OverflowError) as exc:
                return 'Range needs correction: ' + str(exc)
        if key == 'ui.optical.requested_field_maps':
            return self.get('ui.optical.outputs.fields_enabled') or self.get('ui.optical.outputs.execution_plan') != 'spectrum_only'
        if key == 'ui.optical.outputs.rta':
            return self.get('ui.optical.outputs.execution_plan') != 'fields_only'
        if key == 'ui.run.busy': return bool(self.store.busy)
        if key == 'ui.coupled.has_gaas':
            ids={row['material_id'] for row in self._layers()}
            return any(row['id'] in ids and (row['id']=='gaas' or row.get('model')=='gaas_reference') for row in self.store.electrical_materials)
        if key == 'ui.coupled.has_blocker': return bool(self._validation.get('coupled'))
        if key == 'ui.coupled.compatible_profile_available': return bool(self._last_compatible_profile())
        if key == 'ui.optical.selected_material_is_table':
            name=self.get('ui.optical.selected_material_name')
            return any(row['Name']==name and row['Model']=='table_nk' for row in self.store.materials.to_dict('records'))
        if key in ('ui.project.name',):
            return (self.store.device or {}).get('name', 'Current optical project')
        if key == 'ui.project.revision':
            return self.revision()
        if key == 'ui.preset.active_name':
            return self._ui().get(key, 'Current project')
        if key in ('ui.storage.run_library', 'ui.optical.run_destination'):
            return str(self.store.library.runs)
        try:
            value = self._derived(key)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return [] if self._fields.get(key, {}).get('widget') == 'table' else 'Needs attention: '+str(exc)
        if value is not None:
            return copy.deepcopy(value)
        return self._ui_default(key, default)

    def _derived(self, key):
        d = self.store.device or {}
        layers = self._layers()
        mesh = d.get('mesh', {})
        pc = next((row for row in reversed(d.get('pc_arrays', [])) if row.get('enabled', True)), {})
        materials = {row['id']: row for row in self.store.electrical_materials}
        if key in ('ui.optical.full_device_extent', 'ui.electrical.dimensions'):
            text = f"{d.get('width_um',self.store.settings['ax_um']):g} × {d.get('depth_um',self.store.settings['ay_um']):g}"
            if key == 'ui.electrical.dimensions':
                text += f" × {sum(row['thickness_um'] for row in layers):g}"
            return text + ' µm'
        if key == 'ui.optical.selected_pc_name': return pc.get('name', 'No PC area')
        if key == 'ui.optical.pc_extent': return f"{pc['width_um']:g} × {pc['depth_um']:g} µm" if pc else 'No PC area'
        if key == 'ui.optical.pc_period': return f"{pc['cell_width_um']:g} × {pc['cell_depth_um']:g} µm" if pc else 'No PC area'
        if key == 'ui.optical.pc_hole_count':
            return sum(row.get('enabled',True) and row.get('pc_array_id') == pc.get('id') for row in d.get('shapes', [])) if pc else 0
        if key == 'ui.electrical.pc_summary':
            return f"{pc['width_um']:g} × {pc['depth_um']:g} µm · {pc['nx']} × {pc['ny']} cells · {self.get('ui.optical.pc_hole_count'):,} enabled holes" if pc else 'No PC area'
        if key == 'ui.optical.compiled_domain_extent':
            cell = self.get('settings.optical_unit_cell')
            return f"{cell['width_um'] if cell['enabled'] else d.get('width_um',self.store.settings['ax_um']):g} × {cell['depth_um'] if cell['enabled'] else d.get('depth_um',self.store.settings['ay_um']):g} µm · periodic X/Y"
        if key == 'ui.optical.domain_pattern_counts':
            cell = self._prepared_model().get('optical_unit_cell', {})
            return f"{cell.get('retained_patterns',0):,} retained · {cell.get('outside_patterns',0):,} outside · {cell.get('clipped_patterns',0):,} clipped"
        if key == 'ui.optical.domain_rows':
            return [['Electrical finite footprint', self.get('ui.optical.full_device_extent'), 'Unaffected'],
                ['PC patterned area', self.get('ui.optical.pc_extent'), f"{self.get('ui.optical.pc_hole_count')} enabled holes"],
                ['Optical periodic cell', self.get('ui.optical.compiled_domain_extent'), 'Repeats periodically']]
        if key in ('ui.optical.runtime_status','ui.optical.meep_runtime_status','ui.optical.meep_runtime'):
            engine = 'meep' if 'meep' in key else self.get('ui.optical.engine')
            return self._runtime.get(engine, {}).get('message', 'Not checked · use Check selected runtime')
        if key == 'ui.electrical.devsim_status': return self._runtime.get('electrical',{}).get('message', 'Not checked · use Check runtime')
        if key == 'ui.optical.meep_bridge_status': return 'Existing Meep uses legacy periodic tables; selected-cell, contact and polygon bridging is unavailable.'
        if key == 'ui.optical.meep_effective_section':
            extent = self.get('settings.optical_unit_cell.depth_um') if self.get('settings.optical_unit_cell.enabled') else d.get('depth_um', self.store.settings['ay_um'])
            return f"{(self.get('search.fdtd.section_y_um')+extent/2)%extent-extent/2:g} µm"
        if key in ('ui.optical.meep_estimated_grid','ui.optical.meep_estimated_memory'):
            cell=self.get('settings.optical_unit_cell'); res=self.get('search.fdtd.resolution')
            width=cell['width_um'] if cell['enabled'] else d.get('width_um',self.store.settings['ax_um'])
            depth=cell['depth_um'] if cell['enabled'] else d.get('depth_um',self.store.settings['ay_um'])
            thickness=sum(row['thickness_um'] for row in layers)+2*(self.get('search.fdtd.pml_um')+self.get('search.fdtd.padding_um'))
            shape=[math.ceil(width*res),math.ceil(thickness*res)]
            if self.get('search.fdtd.dimensions')==3: shape.insert(1,math.ceil(depth*res))
            count=math.prod(shape)
            return ' × '.join(map(str,shape))+f' · {count:,} cells' if key.endswith('grid') else f'{count*192/1024**2:.1f} MiB minimum field allocation · dispersion adds memory'
        if key == 'ui.optical.meep_field_wavelength':
            lo,hi=self._band(); return f'{2/(1/lo+1/hi):g} nm'
        if key == 'ui.optical.logical_cpu_count': return os.cpu_count() or 1
        if key == 'ui.optical.effective_resources':
            from model import performance
            p = performance(self.store.performance, self._sampling()['count'], os.cpu_count() or 1)
            return f"{p['effective_workers']} workers × {p['threads']} threads · {p['mode']}"
        if key in ('ui.optical.compiled_samples','ui.optical.s4_solve_count','ui.optical.actual_last_sample',
            'ui.optical.stop_included','ui.optical.first_sample','ui.optical.compiled_wavelength','ui.optical.resolved_points',
            'ui.optical.sample_preview','ui.coupled.sampled_spacing'):
            sample = self._sampling()
            count, first, last = sample['count'], sample['first'], sample['last']
            angle = sample['axis'] == 'angle'
            suffix = '°' if angle else 'nm'
            if key in ('ui.optical.compiled_samples','ui.optical.s4_solve_count'): return count
            if key == 'ui.optical.actual_last_sample': return f'{last:g} {suffix}'
            if key == 'ui.optical.stop_included': return 'Yes' if math.isclose(last, sample['stop'], rel_tol=1e-12, abs_tol=1e-10) else 'No · last grid sample shown above'
            if key == 'ui.optical.first_sample': return f"{self.store.settings['fixed_wl_nm'] if angle else first:g} nm · θ {first if angle else sample['theta']:g}°"
            if key == 'ui.coupled.sampled_spacing': return f"{sample['step']:g} nm" if not angle and count > 1 else 'One wavelength sample'
            if key == 'ui.optical.sample_preview':
                indices = list(range(min(count,3))) + ([count-1] if count>3 else [])
                if sample['axis']=='frequency':
                    return [[i+1,1000/(1000/first+(1000/last-1000/first)*i/(count-1)),0.] for i in indices]
                return [[i+1, self.store.settings['fixed_wl_nm'] if angle else first+i*sample['step'], first+i*sample['step'] if angle else sample['theta']] for i in indices]
            return f"{first:g}–{last:g} {suffix} · {sample['step']:g} step · {count:,} samples"
        if key == 'ui.optical.active_band':
            lo, hi = self._band(); return f'{lo:g}–{hi:g} nm'
        if key in ('ui.optical.compiled_incidence','ui.optical.source_summary','ui.optical.excitation_summary'):
            return f"{self.store.settings['polarization']} · θ {self.store.settings['theta_deg']:g}° · φ {self.store.settings['phi_deg']:g}° · from top"
        if key == 'ui.optical.compiled_polarization': return self.store.settings['polarization']
        if key == 'ui.optical.phase_measure_count': return self._sampling()['count'] if self.get('search.simulation.measure_phase') else 0
        if key == 'ui.optical.field_sample_count':
            if not self.get('ui.optical.requested_field_maps'): return 0
            return 1 if self.get('search.simulation.single_wavelength') else self._sampling()['count']
        if key in ('ui.optical.field_workload','ui.optical.field_value_count'):
            count = self.get('ui.optical.field_sample_count')
            grid = self.get('search.simulation.electric_fields.grid')
            depth = self.get('search.simulation.electric_fields.depth_samples')
            return f'{count:,} samples × {grid} × {grid} × {depth} depths/layer × {len(layers)} layers × 6 complex E/H components'
        if key == 'ui.optical.selected_field_sample':
            return f"{self.get('search.simulation.wavelength_nm'):g} nm · manual" if self.get('search.simulation.wavelength_source')=='manual' else 'Selected from matching completed spectrum'
        if key == 'ui.optical.outputs.selected_spectrum_id': return self._ui().get(key, 'None selected')
        if key in ('ui.optical.selected_material_name','ui.optical.selected_material_model','ui.optical.selected_material_coverage',
            'ui.optical.selected_material_source','ui.optical.selected_material_interpolation','ui.optical.selected_nk'):
            name = self._ui().get('ui.optical.selected_material_name') or (self.store.layers.iloc[1]['Material'] if len(self.store.layers)>2 else self.store.materials.iloc[0]['Name'])
            raw = next((row for row in self.store.materials.to_dict('records') if row['Name']==name),{})
            if key=='ui.optical.selected_material_name': return name
            if key=='ui.optical.selected_material_model': return raw.get('Model','Not assigned')
            if key=='ui.optical.selected_material_interpolation': return self.store.settings.get('material_interpolations',{}).get(name,'linear')
            if key=='ui.optical.selected_material_source': return raw.get('DataFile') or 'Constant material'
            mat = next((row for row in self._prepared_model()['materials'] if row['name']==name),{})
            if key=='ui.optical.selected_material_coverage': return f"{mat['grid'][0]:g}–{mat['grid'][-1]:g} nm" if mat.get('grid') else 'All wavelengths · constant'
            from model import sample_nk
            n,k = sample_nk(mat,[self.get('ui.optical.material_inspection_wavelength_nm')]); return f'n {n[0]:g} · k {k[0]:g}'
        if key in ('ui.optical.incident_material','ui.optical.exit_material'):
            row = self.store.layers.iloc[0 if 'incident' in key else -1]
            return str(row['Material'])
        if key in ('ui.optical.assignment_rows','ui.optical.band_coverage_rows','ui.optical.band_coverage_status'):
            model = self._prepared_model()
            mats = {row['name']:row for row in model['materials']}
            lo,hi = self._band()
            coverage = lambda mat: f"{mat['grid'][0]:g}–{mat['grid'][-1]:g}" if mat.get('grid') else 'All λ'
            covered = lambda mat: not mat.get('grid') or mat['grid'][0]<=lo<=hi<=mat['grid'][-1]
            if key == 'ui.optical.band_coverage_rows':
                used = {r['material'] for r in model['layers']} | {r['material'] for r in model['patterns']}
                return [[name,coverage(mat),f'{lo:g}–{hi:g}', 'Covered' if covered(mat) else 'Outside table · endpoint clamping'] for name,mat in mats.items() if name in used]
            if key == 'ui.optical.band_coverage_status':
                return 'Covered' if all(covered(mats[r['material']]) for r in model['layers']+model['patterns']) else 'Outside tabulated range · inspect coverage'
            rows=[]
            for row in d.get('layers',[]) + d.get('shapes',[]) + d.get('contacts',[]):
                if not row.get('enabled',True): continue
                kind='layer' if 'thickness_um' in row else 'contact' if 'boundary' in row else 'shape'
                name=row.get('optical_material_name') or (materials.get(row.get('material_id'),{}).get('optical_material_name'))
                if not name and kind=='layer':
                    target=next((x for x in model['layers'] if x.get('device_layer_id')==row['id'] or x['name']==row['name']),{})
                    name=target.get('material')
                if row.get('operation')=='void': name='Air'
                mat=mats.get(name,{})
                rows.append(dict(id=row['id'],kind=kind,region=row['name'],electrical_material=materials.get(row.get('material_id'),{}).get('name','Ideal contact'),optical_material=name or '',model=mat.get('model','No optical volume' if kind=='contact' else 'Not assigned'),coverage=coverage(mat),status='Covered' if mat and covered(mat) else 'Needs assignment' if kind!='contact' else 'Boundary only'))
            return rows
        if key in ('ui.optical.readiness_rows','ui.electrical.readiness'):
            mode='optical' if 'optical' in key else 'electrical'
            issues=self._validation.get(mode)
            return [['Setup','Not validated','Use Validate setup']] if issues is None else [['Setup','Ready' if not issues else 'Needs changes',f'{len(issues)} blocking issues']]+[[i['tab'],'Needs changes',i['message']] for i in issues]
        if key == 'ui.electrical.layers': return ' / '.join(f"{r['name']} {r['thickness_um']*1000:g} nm" for r in layers)
        if key == 'ui.electrical.run_title': return self._ui().get(key,d.get('name','Device')+' · electrical')
        if key == 'ui.electrical.run_notes': return self._ui().get(key,'')
        if key == 'ui.optical.optical_contact_summary':
            return ' / '.join(f"{r['name']}: {r.get('optical_material_name','No material')} {r.get('optical_thickness_um',0)*1000:g} nm" for r in self._contacts()) or 'No active electrical contacts'
        if key == 'ui.coupled.last_compatible_run':
            return self._last_compatible_profile() or 'No compatible coupled profile from this session'
        if key == 'ui.electrical.contact_summary': return ' / '.join(f"{r['name']} · {r['surface']}" for r in self._contacts()) or 'No active contacts'
        if key in ('ui.electrical.offset_summary','ui.electrical.bias_counts','ui.electrical.resolved_biases'):
            values=self.get('search.electrical.biases_V',[])
            resolved = list(dict.fromkeys([0., *values]))
            if key=='ui.electrical.bias_counts': return f'{len(values):,} submitted · {len(resolved):,} distinct states including zero reference'
            if len(resolved) > 12:
                return f'{min(resolved):.12g} to {max(resolved):.12g} V · {len(resolved):,} distinct states including zero reference'
            return ', '.join(f'{v:.12g}' for v in resolved)+' V'
        if key == 'ui.electrical.applied_summary':
            swept=self.get('search.electrical.swept_contact_id')
            return ' / '.join(f"{r['name']}: base {r['voltage_V']:g} V"+(' + offset' if r['id']==swept else ' · fixed') for r in self._contacts())
        if key in ('ui.electrical.voltage_schedule', 'ui.electrical.voltage_schedule_count'):
            contacts=self._contacts(); swept=self.get('search.electrical.swept_contact_id')
            values = list(dict.fromkeys([0., *self.get('search.electrical.biases_V', [])]))
            if key == 'ui.electrical.voltage_schedule_count': return len(values)
            indexes = range(len(values)) if len(values) <= 200 else [*range(100), *range(len(values)-100, len(values))]
            return [[i+1,values[i],*[r['voltage_V']+(values[i] if r['id']==swept else 0) for r in contacts], 'Reference' if values[i]==0 else 'Requested'] for i in indexes]
        if key.startswith('ui.electrical.selected_'):
            contact=self.selected_contact()
            if key=='ui.electrical.selected_attachment':
                parent=next((r for r in layers if r['id']==contact.get('layer_id')),{}); return parent.get('name','No layer')+' · '+contact.get('surface','')
            if key=='ui.electrical.selected_footprint': return f"{contact.get('shape','')} · {contact.get('size_x_um',0):g} × {contact.get('size_y_um',0):g} µm"
            if key=='ui.electrical.selected_reservoir': return contact.get('boundary','No contact')+' · dopants evaluated at exposed contact faces'
            if key=='ui.electrical.selected_contact_faces': return 'Build mesh to inspect contact face coverage'
        if key in ('ui.electrical.evaluated_parameters','ui.electrical.material_sources','ui.electrical.temperature_table'):
            from electrical_material_library import evaluate_material, PROPERTY_FIELDS
            selected=self._selected_material(); temperature=d.get('temperature_K',300.)
            if key=='ui.electrical.material_sources': return [[r.get('title',''),r.get('note',''),r.get('kind','reference')] for r in selected.get('sources',[])]
            if key=='ui.electrical.evaluated_parameters':
                props=evaluate_material(selected,temperature_K=temperature)['properties']; return [[label,props.get(k,'Not supplied'),unit] for k,label,unit in PROPERTY_FIELDS]
            used={row['material_id'] for row in layers}
            rows=[]
            for mat in self.store.electrical_materials:
                if mat['id'] not in used: continue
                props=evaluate_material(mat,temperature_K=temperature)['properties']
                rows.append([mat['name'],mat.get('model','constant'),mat.get('temperature_K',300),temperature,props.get('bandgap_eV',0),props.get('Nc_cm3',0),props.get('Nv_cm3',0),props.get('intrinsic_cm3',0),', '.join(mat.get('property_overrides',[])) or 'None'])
            return rows
        if key in ('ui.electrical.mesh_domain','ui.electrical.mesh_shape','ui.electrical.mesh_cells','ui.electrical.dx_um','ui.electrical.dy_um','ui.electrical.dz_summary','ui.electrical.feature_ratio'):
            nx,ny,per=mesh.get('nx',16),mesh.get('ny',16),mesh.get('nz_per_layer',8)
            dx,dy=d.get('width_um',0)/nx,d.get('depth_um',0)/ny
            if key=='ui.electrical.mesh_domain': return 'Full '+self.get('ui.electrical.dimensions')+' finite device · not cropped by optical cell'
            if key=='ui.electrical.mesh_shape': return f'{nx} × {ny} × {per*len(layers)}'
            if key=='ui.electrical.mesh_cells': return nx*ny*per*len(layers)
            if key=='ui.electrical.dx_um': return dx
            if key=='ui.electrical.dy_um': return dy
            if key=='ui.electrical.dz_summary': return ' / '.join(f"{r['name']} {r['thickness_um']/per*1000:g} nm/cell" for r in layers)
            sizes=[r['size_x_um'] for r in d.get('shapes',[]) if r.get('enabled',True) and r.get('operation')=='void']
            return f'{min(sizes)/max(dx,dy):g} cells across smallest void' if sizes and dx and dy else 'No void features'
        if key in ('ui.electrical.mesh_peak_memory','ui.electrical.mesh_volume_memory','ui.electrical.mesh_sweep_storage','ui.electrical.mesh_linear_solver','ui.electrical.mesh_resource_budget'):
            from electrical_mesh import mesh_resource_estimate,available_memory_bytes
            estimate=mesh_resource_estimate(d)
            if key=='ui.electrical.mesh_peak_memory':return f"{estimate['estimated_peak_bytes']/1024**2:,.1f} MiB · planning estimate"
            if key=='ui.electrical.mesh_volume_memory':return f"{estimate['estimated_volume_bytes']/1024**2:,.1f} MiB / bias · planning estimate"
            if key=='ui.electrical.mesh_sweep_storage':
                count = len(set([0., *self.get('search.electrical.biases_V', [])]))
                return f"{estimate['estimated_volume_bytes']*count/1024**3:,.2f} GiB for {count:,} resolved states · uncompressed planning estimate"
            if key=='ui.electrical.mesh_linear_solver':return estimate['linear_solver']
            available=available_memory_bytes()
            if estimate['cell_budget']:return f"Explicit {estimate['cell_budget']:,} cells · available-RAM check still applies"
            return f'Automatic · 60% of available RAM ({available*.6/1024**2:,.0f} MiB)' if available else 'Automatic · available RAM unknown'
        if key=='ui.electrical.mesh_coverage':
            if self._mesh is None: return []
            return [[c['object']['name'],c['object']['layer_id'],'Contact',len(c['ids']),float(c['area_m2'])] for c in self._mesh['contacts']]
        if key=='ui.electrical.measured_preview':
            from electrical_terminal_studies import read_measured_csv
            rows=[]
            for kind,column,unit in (('iv','current_A','A'),('cv','capacitance_F','F')):
                path=self.get('search.electrical.terminal_studies.measured_'+kind+'_path','')
                if path: rows.extend([[kind.upper(),r['bias_V'],r[column],unit] for r in read_measured_csv(path)[:20]])
            return rows
        if key in ('ui.coupled.solve_count','ui.coupled.index_record_estimate','ui.coupled.tracking_interval','ui.coupled.mapping_summary','ui.coupled.correction_eligibility','ui.coupled.validation_issues','ui.coupled.tracking_warnings','ui.coupled.output_summary'):
            transfer=self._transfer_options()
            if key=='ui.coupled.solve_count': return len(set([0.,*self.get('search.electrical.biases_V',[])]))*self._sampling()['count']
            if key=='ui.coupled.index_record_estimate': return self._sampling()['count']*len(layers)*(mesh.get('nz_per_layer',8)+transfer['optical_slices_per_layer'])*len(set([0.,*self.get('search.electrical.biases_V',[])]))
            if key=='ui.coupled.tracking_interval': return f"{transfer['reference_nm']-transfer['tracking_window_nm']:g}–{transfer['reference_nm']+transfer['tracking_window_nm']:g} nm · feature must lie inside sampled sweep"
            if key=='ui.coupled.correction_eligibility':
                return [[mat['name'],'Drude' if mat['kind']!='dielectric' else 'None','Eligible' if mat['id']=='gaas' or mat.get('model')=='gaas_reference' else 'Unavailable','Eligible' if mat['id']=='gaas' or mat.get('model')=='gaas_reference' else 'Unavailable'] for mat in self.store.electrical_materials if mat['id'] in {r['material_id'] for r in layers}]
            if key=='ui.coupled.mapping_summary':
                return [[row['name'],transfer['optical_mapping'].get(row['id'],{}).get('layer',row.get('optical_layer_name',row['name'])),transfer['optical_mapping'].get(row['id'],{}).get('material','Automatic background'), 'Not validated'] for row in layers]
            if key=='ui.coupled.validation_issues': return [['Error',r['key'],r['message'],r['tab']] for r in self._validation.get('coupled',[])]
            if key=='ui.coupled.tracking_warnings':
                lo,hi=self._band(); ref=transfer['reference_nm']; window=transfer['tracking_window_nm']
                return [['Warning','Tracking window extends beyond sampled band','coupled.response']] if ref-window<lo or ref+window>hi else []
            return 'Electrical fields · R/T/A · index profiles · response features'+(' · I–V' if self.get('search.electrical.terminal_studies.iv_enabled') else '')+(' · C–V' if self.get('search.electrical.terminal_studies.cv_enabled') else '')
        if key=='ui.coupled.first_blocker.target': return self._validation.get('coupled',[{}])[0].get('tab','coupled.overview') if self._validation.get('coupled') else 'coupled.overview'
        return None

    def options(self, field):
        key=field.get('key','') if isinstance(field,dict) else str(field)
        if key == 'search.electrical.charge_model':
            mode = (self.get('search.electrical.transport', {}) or {}).get('mode', 'disabled')
            if mode == 'semiconductor_dd':
                stats = (self.get('search.electrical.transport', {}) or {}).get('statistics', 'boltzmann')
                return [dict(label='Semiconductor Poisson + continuity · ' + ('Fermi–Dirac' if stats == 'fermi_dirac' else 'Boltzmann'), value='semiconductor')]
            if mode == 'dielectric_leakage': return [dict(label='Charge-free dielectric field + leakage law', value='dielectric')]
        if key in ('search.electrical.swept_contact_id','ui.electrical.selected_contact_id'):
            rows=self._contacts() if key.startswith('search.') else (self.store.device or {}).get('contacts',[])
            return [dict(label=row['name'],value=row['id']) for row in rows]
        if key=='ui.electrical.selected_material_id':
            return [dict(label=row['name'],value=row['id']) for row in self.store.electrical_materials]
        if key in ('ui.optical.selected_material_name','device.optical_material_name'):
            return [dict(label=row['Name'],value=row['Name']) for row in self.store.materials.to_dict('records')]
        return copy.deepcopy(field.get('options',[]) if isinstance(field,dict) else self._fields.get(key,{}).get('options',[]))

    def set(self, key, value):
        """Commit valid individual controls; cross-field errors remain drafts."""
        field=self._fields.get(key)
        if field:
            if field.get('widget')=='number':
                value=_finite(value,field['label'],field.get('min'),field.get('max'),field.get('precision')==0)
            elif field.get('widget')=='checkbox' and not isinstance(value,bool):
                raise ValueError(field['label']+' must be true or false.')
            elif field.get('widget')=='select':
                choices=self.options(field)
                if choices and value not in [choice['value'] for choice in choices]:
                    raise ValueError('Choose a valid '+field['label'].lower()+'.')
        if key.startswith('device.contacts[{'):
            return self.update_contact(self.selected_contact().get('id'), {key.split('].',1)[1]:value})
        if key.startswith('device.'):
            device=copy.deepcopy(self.store.device)
            if not device: raise ValueError('Create a device in Structure first.')
            _assign(device,key[7:],value)
            self.store.set_device(device)
        elif key.startswith('settings.'):
            settings=copy.deepcopy(self.store.settings)
            if key.startswith('settings.optical_unit_cell.') and 'optical_unit_cell' not in settings:
                settings['optical_unit_cell']=self.get('settings.optical_unit_cell')
            _assign(settings,key[9:],value)
            self.store.update_settings(settings)
        elif key.startswith('performance.'):
            perf=copy.deepcopy(self.store.performance); _assign(perf,key[12:],value)
            self.store.update_performance(perf)
        elif key.startswith('search.electrical.'):
            suffix=key[18:]
            values=self._electrical_options()
            if suffix=='model' and value!=values['model']:
                if value=='custom_device':
                    values=dict(model=value,device=copy.deepcopy(self.store.device),material_library=copy.deepcopy(self.store.electrical_materials),biases_V=[0.,-2.],charge_model='semiconductor',swept_contact_id='',terminal_studies=dict(iv_enabled=False,cv_enabled=False,measured_iv_path='',measured_cv_path=''),optical_unit_cell=dict(enabled=False,width_um=(self.store.device or {}).get('width_um',1.),depth_um=(self.store.device or {}).get('depth_um',1.),cx_um=0.,cy_um=0.))
                else:
                    from electrical_solver import DEFAULT_OPTIONS
                    values=copy.deepcopy(DEFAULT_OPTIONS); values['model']=value
            else:
                _assign(values,suffix,value)
            if suffix.startswith('terminal_studies') and values['model']!='custom_device':
                raise ValueError('Terminal I–V/C–V studies require the editable finite device model.')
            self.store.save_search('electrical',values)
            self._source_changed(key)
        elif key.startswith('search.coupled.'):
            values=self._electrical_options(); values.update(self._transfer_options()); values['optical_enabled']=True
            if values['model']=='custom_device': values['optical_unit_cell']=self.get('settings.optical_unit_cell')
            _assign(values,key[15:],value)
            self.store.save_search('coupled',values)
            self._source_changed(key)
        elif key.startswith('search.'):
            namespace, suffix=key[7:].split('.',1)
            values=copy.deepcopy(self.store.search_state.get(namespace,{}))
            _assign(values,suffix,value)
            if namespace=='fdtd':
                from fdtd_model import DEFAULTS
                # Individual controls may form an incomplete band draft; validate
                # the complete band at Run rather than rejecting a one-end edit.
                base=dict(DEFAULTS,**values)
                for flag in ('fit_materials','save_fields'):
                    if not isinstance(base[flag],bool): raise ValueError(flag+' must be true or false.')
            self.store.save_search(namespace,values)
            self._source_changed(key)
        elif key=='ui.optical.study_type':
            self._set_study(value)
        elif key=='ui.optical.single.wavelength_nm':
            value=_finite(value,'Wavelength',1e-6)
            settings=dict(self.store.settings,mode='Wavelength sweep',wl_start_nm=value,wl_stop_nm=value)
            search=copy.deepcopy(self.store.search_state)
            search.setdefault(self.UI_NAMESPACE,{}).setdefault('values',{})[key]=value
            self._commit_parts(settings=settings,search=search)
        elif key=='ui.electrical.study':
            if self.get('search.electrical.model')!='custom_device' and value!='bias':
                raise ValueError('Use the editable device for terminal I–V and C–V.')
            studies=dict(self.get('search.electrical.terminal_studies',{}) or {},iv_enabled=value in ('iv','both'),cv_enabled=value in ('cv','both'))
            self.set('search.electrical.terminal_studies',studies)
        elif key=='ui.optical.selected_material_interpolation':
            name=self.get('ui.optical.selected_material_name')
            values=dict(self.store.settings.get('material_interpolations',{})); values[name]=value
            self.store.update_settings(dict(material_interpolations=values))
        elif key=='ui.optical.outputs.fields_enabled':
            search=copy.deepcopy(self.store.search_state)
            state=search.setdefault(self.UI_NAMESPACE,{})
            ui=state.setdefault('values',{})
            ui[key]=bool(value)
            ui['ui.optical.outputs.execution_plan']='spectrum_then_fields' if value else 'spectrum_only'
            self._commit_parts(search=search)
        elif key=='ui.optical.outputs.rta':
            if bool(value)!=self.get(key): raise ValueError('A spectrum stage always saves R, T and A. A fields-only job does not calculate a new spectrum.')
        elif key=='ui.optical.outputs.execution_plan':
            search=copy.deepcopy(self.store.search_state)
            ui=search.setdefault(self.UI_NAMESPACE,{}).setdefault('values',{})
            ui[key]=value; ui['ui.optical.outputs.fields_enabled']=value!='spectrum_only'
            self._commit_parts(search=search)
        elif key.startswith('ui.'):
            self._save_ui(key,value)
        else:
            raise ValueError('Unknown setup binding: '+key)
        return value

    def _set_study(self, kind):
        if kind not in ('single','wavelength_sweep','angle_sweep'):
            raise ValueError('Choose a single wavelength, wavelength sweep or angle sweep.')
        settings=copy.deepcopy(self.store.settings)
        search=copy.deepcopy(self.store.search_state)
        ui=search.setdefault(self.UI_NAMESPACE,{}).setdefault('values',{})
        previous=self.get('ui.optical.study_type')
        if previous=='wavelength_sweep':
            ui['ui.optical.remembered_sweep']={key:settings[key] for key in ('wl_start_nm','wl_stop_nm','wl_step_nm')}
        if kind=='single':
            wave=ui.get('ui.optical.single.wavelength_nm',settings['fixed_wl_nm'])
            settings.update(mode='Wavelength sweep',wl_start_nm=wave,wl_stop_nm=wave)
        elif kind=='angle_sweep': settings['mode']='Angle sweep'
        else:
            settings['mode']='Wavelength sweep'
            if previous!='wavelength_sweep' and ui.get('ui.optical.remembered_sweep'):
                settings.update(ui['ui.optical.remembered_sweep'])
            elif previous=='single':
                wave=settings['wl_start_nm']; settings.update(wl_start_nm=wave,wl_stop_nm=wave+10.,wl_step_nm=1.)
        self._commit_parts(settings=settings,search=search)

    def update_contact(self, ident, changes):
        device=copy.deepcopy(self.store.device)
        row=next((r for r in device['contacts'] if r['id']==ident),None) if device else None
        if row is None: raise ValueError('Select a current contact.')
        row.update(copy.deepcopy(changes)); self.store.set_device(device)
        return copy.deepcopy(row)

    def update_layer(self, ident, changes):
        device=copy.deepcopy(self.store.device)
        row=next((r for r in device['layers'] if r['id']==ident),None) if device else None
        if row is None: raise ValueError('Select a current layer.')
        row.update(copy.deepcopy(changes)); self.store.set_device(device)
        return copy.deepcopy(row)

    def update_optical_assignment(self, ident, material):
        if material not in set(self.store.materials['Name']): raise ValueError('Choose an existing optical material.')
        device=copy.deepcopy(self.store.device)
        row=next((r for group in ('layers','shapes','contacts') for r in device[group] if r['id']==ident),None) if device else None
        if row is None: raise ValueError('Select a current device object.')
        row['optical_material_name']=material
        self.store.set_device(device)

    def set_optical_mapping(self, rows):
        if isinstance(rows,dict):
            values=rows
        else:
            values={row['source_id']:dict(layer=row.get('target',row.get('layer','')),material=row.get('optical_material',row.get('material',''))) for row in rows}
        self.set('search.coupled.optical_mapping',values)

    def auto_map(self):
        model=self._prepared_model()
        targets={row.get('device_layer_id'):row for row in model['layers'] if row.get('device_layer_id')}
        mapping={}
        for row in self._layers():
            target=targets.get(row['id']) or next((x for x in model['layers'] if x['name']==row.get('optical_layer_name',row['name'])),None)
            if target is None: raise ValueError(row['name']+': no matching optical layer.')
            mapping[row['id']]=dict(layer=target['name'],material=target['material'])
        self.set_optical_mapping(mapping)
        return mapping

    def use_pc_lattice(self):
        device=self.store.device or {}
        pc=next((row for row in reversed(device.get('pc_arrays',[])) if row.get('enabled',True)),None)
        if pc is None: raise ValueError('Create an enabled PC area in Structure first.')
        holes=[row for row in device.get('shapes',[]) if row.get('pc_array_id')==pc['id'] and row.get('enabled',True)]
        center=min(holes,key=lambda row:(row['cx_um']-pc['cx_um'])**2+(row['cy_um']-pc['cy_um'])**2) if holes else pc
        cell=dict(self.get('settings.optical_unit_cell'),width_um=pc['cell_width_um'],depth_um=pc['cell_depth_um'],cx_um=center['cx_um'],cy_um=center['cy_um'])
        self.set('settings.optical_unit_cell',cell)
        return cell

    def center_cell(self):
        cell=dict(self.get('settings.optical_unit_cell'),cx_um=0.,cy_um=0.)
        self.set('settings.optical_unit_cell',cell)
        return cell

    def parse_biases(self, text=None):
        from electrical_sweep import resolve_biases
        text=self.get('ui.electrical.bias_list_text') if text is None else text
        if not isinstance(text,str): raise ValueError('Enter comma, space or newline separated voltages.')
        pieces=[part for part in re.split(r'[,;\s]+',text.strip()) if part]
        if not pieces: raise ValueError('Enter at least one voltage.')
        values=resolve_biases(pieces, **self._bias_bounds())
        self.set('search.electrical.biases_V',values)
        return values

    def _bias_bounds(self):
        return {} if self.get('search.electrical.model') == 'custom_device' else dict(low=-4., high=0., max_states=21)

    def _range_options(self):
        start=_finite(self.get('ui.electrical.bias_start_V'),'Start voltage')
        stop=_finite(self.get('ui.electrical.bias_stop_V'),'Stop voltage')
        sampling = self.get('ui.electrical.range_sampling')
        if sampling == 'count':
            count = _finite(self.get('ui.electrical.bias_point_count'), 'Voltage point count', 1, integer=True)
            return dict(start=start, stop=stop, count=count, **self._bias_bounds())
        step=_finite(self.get('ui.electrical.bias_step_V'),'Voltage step',1e-12)
        return dict(start=start, stop=stop, step=step, **self._bias_bounds())

    def _generated_biases(self):
        """Resolve the visible range without modifying the submitted schedule."""
        from electrical_sweep import generate_biases
        return generate_biases(**self._range_options())

    def generate_biases(self):
        values = self._generated_biases()
        self.set('search.electrical.biases_V', values)
        return values

    def apply_transport(self, cfg):
        """Atomically apply a valid sourced model and its compatible charge mode."""
        from electrical_transport import validate_transport
        result = validate_transport(cfg)
        options = self._electrical_options()
        if options['model'] != 'custom_device':
            raise ValueError('Physical transport settings require the editable finite-device model.')
        options['transport'] = result
        if result['mode'] != 'disabled':
            options['charge_model'] = 'semiconductor' if result['mode'] == 'semiconductor_dd' else 'dielectric'
        self.store.save_search('electrical', options)
        self._source_changed('search.electrical.transport')
        return copy.deepcopy(result)

    def job_options(self, mode):
        """Return real backend options, composed from the shared source config."""
        if mode=='optical':
            if self.get('ui.optical.engine')=='meep':
                from fdtd_model import validate_options
                return validate_options(self.store.search_state.get('fdtd',{}))
            from simulation_fields import validate_settings
            result=copy.deepcopy(self.store.search_state.get('simulation',{}))
            # Saved jobs keep their original source, but a fresh submission
            # follows the active workspace rather than that recorded history.
            result['optical_geometry_source']=getattr(self.store,'optical_geometry_source','device')
            result.update(measure_phase=self.get('search.simulation.measure_phase'),
                electric_fields=validate_settings(self.get('search.simulation.electric_fields')),
                single_wavelength=self.get('search.simulation.single_wavelength'),
                wavelength_source=self.get('search.simulation.wavelength_source'),
                wavelength_nm=self.get('search.simulation.wavelength_nm'))
            identifier=self.get('ui.optical.outputs.selected_spectrum_id')
            if identifier and identifier!='None selected': result['spectrum_id']=identifier
            return result
        if mode not in ('electrical','coupled'): raise ValueError('Unknown simulation mode: '+mode)
        from electrical_optics import validate_options
        result=self._electrical_options()
        if mode=='coupled':
            result.update(self._transfer_options()); result['optical_enabled']=True
            if result['model']=='custom_device': result['optical_unit_cell']=self.get('settings.optical_unit_cell')
        return validate_options(result)

    def validate(self, mode):
        """Run physical/model/job preflight without launching any solver."""
        issues=[]
        def error(key,message,tab): issues.append(dict(key=key,message=str(message),tab=tab))
        try:
            options=self.job_options(mode)
        except (ValueError,OSError,TypeError,KeyError) as exc:
            error('search.'+('simulation' if mode=='optical' else 'electrical'),exc,'optical.outputs' if mode=='optical' else 'electrical.study')
            self._validation[mode]=issues
            return issues
        if mode=='coupled':
            if self.get('ui.optical.engine')!='s4': error('ui.optical.engine','Coupled optical response requires S4. Meep coupling is unavailable.','coupled.optical-setup')
            if self.store.settings['mode']!='Wavelength sweep': error('settings.mode','Coupled response requires a wavelength sweep.','optical.sweep')
            requested=self.get('search.simulation.measure_phase') or self.get('ui.optical.requested_field_maps')
            if requested and self.get('ui.coupled.unsupported_output_policy')=='require_all':
                error('ui.coupled.unsupported_output_policy','Coupled phase and optical E/H maps are unavailable. Select supported coupled outputs or run the shared Optical setup separately.','coupled.outputs')
        if mode in ('optical','coupled') and self.get('ui.optical.engine')=='s4' and (
                mode=='coupled' or getattr(self.store,'optical_geometry_source','device')!='original_tables'):
            from optical_unit_cell import pc_unit_cell_issue
            message=pc_unit_cell_issue(self.store.settings.get('optical_unit_cell'),self.store.device)
            if message:
                error('settings.optical_unit_cell',message,'optical.domain')
                self._validation[mode]=issues
                self.changed.emit('validation')
                return copy.deepcopy(issues)
        if mode=='optical' and self.get('ui.optical.engine')=='meep':
            try:
                from fdtd_model import build_job
                # Older Meep bridges used only legacy tables. A selected-cell
                # or contact/polygon run must never silently use another domain.
                if not getattr(__import__('fdtd_model'), 'CANONICAL_DEVICE_BRIDGE', False) and (
                        self.get('settings.optical_unit_cell.enabled') or
                        any(r.get('shape')=='polygon' for r in (self.store.device or {}).get('shapes',[])) or
                        any(r.get('enabled',True) and r.get('optical_thickness_um',0)>0 for r in (self.store.device or {}).get('contacts',[]))):
                    raise ValueError('Meep canonical selected-cell, polygon and optical-contact bridge is unavailable. Use S4 for this device until the Meep bridge is updated.')
                self._fdtd_job=build_job(self.store.project(),self.store.library.files_for(self.store.project()),options)
                if not self._runtime.get('meep',{}).get('available'):
                    error('ui.optical.meep_runtime_status','Check the configured Meep runtime before running.','optical.accuracy')
            except (ValueError,OSError,TypeError,KeyError) as exc: error('search.fdtd',exc,'optical.accuracy')
        else:
            try:
                from qt_core import prepare_job
                kind='simulation' if mode=='optical' else mode
                if mode=='optical' and self.get('ui.optical.outputs.execution_plan')=='fields_only': kind='simulation_fields'
                project,cfg=prepare_job(kind,self.store.project(),options,self.store.library)
                if mode=='optical': self._model=cfg.get('model')
                if mode in ('electrical','coupled') and options['model']=='custom_device':
                    from electrical_transport import validate_transport
                    transport = validate_transport(options.get('transport'))
                    if transport['mode'] != 'disabled':
                        from electrical_transport_adapter import validate_transport_device
                        try:
                            validate_transport_device(options, transport)
                        except (ValueError, TypeError, KeyError) as exc:
                            error('ui.electrical.transport_scope', exc, 'electrical.temperature')
                            self._validation[mode] = copy.deepcopy(issues)
                            return copy.deepcopy(issues)
                    if transport['mode'] != 'semiconductor_dd':
                        from custom_electrical_solver import build_mesh, _reservoirs
                        self._mesh=build_mesh(options['device'],options['material_library'])
                        for bias in options['biases_V']:
                            voltages={row['id']:row['voltage_V']+(bias if row['id']==options['swept_contact_id'] else 0.) for row in self._contacts()}
                            _reservoirs(self._mesh,voltages,options['charge_model'])
                    from electrical_terminal_studies import read_measured_csv
                    for kind in ('iv','cv'):
                        path=options['terminal_studies']['measured_'+kind+'_path']
                        if path: read_measured_csv(path,kind)
                elif mode in ('electrical','coupled') and not self._runtime.get('electrical',{}).get('available'):
                    error('ui.electrical.devsim_status','Check the optional DEVSIM runtime before using the fixed study.','electrical.mesh')
            except (ValueError,OSError,TypeError,KeyError) as exc:
                text=str(exc)
                physical_error = mode != 'optical' and (options.get('transport') or {}).get('mode', 'disabled') != 'disabled' and any(w in text.lower() for w in ('transport','drift diffusion','continuity','leakage','parameter_source','srh','avalanche','fowler','schottky','poole'))
                if physical_error:
                    tab = 'electrical.temperature'
                elif mode == 'optical':
                    tab = 'optical.materials' if any(w in text.lower() for w in ('material','table','optical assignment')) else 'optical.sweep'
                else:
                    tab = 'coupled.transfer' if mode=='coupled' and any(w in text.lower() for w in ('mapping','optical layer','interband','gaas','reference wavelength','optical correction')) else 'electrical.mesh' if any(w in text.lower() for w in ('mesh','contact face','feature','cells','exposed')) else 'electrical.study'
                error('settings' if mode=='optical' else 'search.electrical',text,tab)
        self._validation[mode]=issues
        self.changed.emit('validation')
        return copy.deepcopy(issues)

    def build_mesh(self):
        from custom_electrical_solver import build_mesh
        if self.get('search.electrical.model')!='custom_device': raise ValueError('Mesh preview uses the editable finite device.')
        self._mesh=build_mesh(self.store.device,self.store.electrical_materials)
        self.changed.emit('mesh_preview')
        return self._mesh

    def check_runtime(self, engine=None):
        engine=engine or self.get('ui.optical.engine')
        if engine=='meep':
            from meep_runtime import probe
            result=probe()
        elif engine=='electrical':
            if self.get('search.electrical.model')=='custom_device' and not self.get('ui.electrical.transport_requires_native'):
                result=dict(available=True,message='Finite-volume electrical solver is available · SciPy')
            else:
                try:
                    from electrical_solver import _load_core
                    _load_core(); result=dict(available=True,message='DEVSIM and native math libraries are available')
                except (ValueError,RuntimeError,ImportError,OSError) as exc: result=dict(available=False,message=str(exc))
        else:
            try:
                from model import performance
                from backend import load_runtime
                perf=performance(self.store.performance,1,os.cpu_count() or 1)
                module=load_runtime(perf,gpu=perf['mode']!='CPU only')
                result=dict(available=True,message='S4 native runtime is available',module=str(module.__file__))
            except (ValueError,RuntimeError,ImportError,OSError) as exc: result=dict(available=False,message=str(exc))
        self._runtime[engine]=result
        self.changed.emit('runtime')
        return copy.deepcopy(result)

    def revision(self):
        project=self.store.project()
        project.pop('desktop_search',None)
        return hashlib.sha256(json.dumps(project,sort_keys=True,allow_nan=False,default=str).encode()).hexdigest()[:12]

    def _last_compatible_profile(self):
        event=self.store.last_result or {}
        directory=event.get('directory')
        if not directory: return ''
        folder=Path(directory)
        try:
            request=json.loads((folder/'desktop_request.json').read_text('utf-8'))
            saved=json.loads((folder/'project.json').read_text('utf-8'))
            if request.get('kind')!='coupled': return ''
            current=self.store.project()
            keys=('device','electrical_materials','settings','materials','layers','patterns')
            if any(saved.get(key)!=current.get(key) for key in keys): return ''
            options=request.get('options',{})
            expected=self.job_options('coupled')
            relevant=self.ELECTRICAL_KEYS|self.TRANSFER_KEYS|{'optical_unit_cell'}
            if any(options.get(key)!=expected.get(key) for key in relevant if key in options or key in expected): return ''
            return folder.name if (folder/'electrical_summary.json').is_file() else ''
        except (OSError,ValueError,TypeError,KeyError):
            return ''

    def export_preset(self, mode='all'):
        if mode not in ('all','optical','electrical','coupled'): raise ValueError('Choose a preset scope.')
        data=dict(schema_version=1,kind='ods_simulation_setup',scope=mode,
            device_layer_ids=[r['id'] for r in self._layers()],contact_ids=[r['id'] for r in self._contacts()])
        if mode in ('all','optical','coupled'):
            data.update(settings=copy.deepcopy(self.store.settings),performance=copy.deepcopy(self.store.performance),
                simulation=copy.deepcopy(self.store.search_state.get('simulation',{})),fdtd=copy.deepcopy(self.store.search_state.get('fdtd',{})))
        if mode in ('all','electrical','coupled'):
            data['electrical']={k:v for k,v in self._electrical_options().items() if k not in ('device','material_library','optical_unit_cell','optical_enabled')}
        if mode in ('all','coupled'): data['coupled']=self._transfer_options()
        prefixes=('ui.optical.',) if mode=='optical' else ('ui.electrical.',) if mode=='electrical' else ('ui.optical.','ui.electrical.','ui.coupled.')
        data['values']={k:copy.deepcopy(v) for k,v in self._ui().items() if k.startswith(prefixes)}
        return data

    def _preset_project(self, payload):
        if not isinstance(payload,dict) or payload.get('kind')!='ods_simulation_setup' or payload.get('schema_version')!=1:
            raise ValueError('Choose an Optical Design Studio simulation setup preset.')
        project=self.store.project(); search=project['desktop_search']
        if 'settings' in payload:
            # Finite geometry is never resized by importing an optical setup.
            settings=copy.deepcopy(payload['settings']); settings['ax_um']=self.store.settings['ax_um']; settings['ay_um']=self.store.settings['ay_um']
            project['settings'].update(settings)
        if 'performance' in payload: project['performance'].update(copy.deepcopy(payload['performance']))
        for namespace in ('simulation','fdtd'):
            if namespace in payload: search[namespace]=copy.deepcopy(payload[namespace])
        if 'electrical' in payload:
            cfg=copy.deepcopy(payload['electrical'])
            if cfg.get('model')=='custom_device':
                swept=cfg.get('swept_contact_id')
                if swept and swept not in {r['id'] for r in self._contacts()}:
                    raise ValueError('Preset swept contact is absent from this device. Choose or remap that contact first.')
                cfg.update(device=copy.deepcopy(self.store.device),material_library=copy.deepcopy(self.store.electrical_materials),optical_unit_cell=project['settings'].get('optical_unit_cell'))
            cfg['optical_enabled']=False
            search['electrical']=cfg
        if 'coupled' in payload:
            transfer=copy.deepcopy(payload['coupled'])
            if set(transfer.get('optical_mapping',{}))-{r['id'] for r in self._layers()}:
                raise ValueError('Preset optical mappings refer to absent device layers. Remap the layers before importing.')
            cfg=copy.deepcopy(search.get('electrical') or self._electrical_options()); cfg.update(transfer,optical_enabled=True)
            search['coupled']=cfg
        values=payload.get('values',{})
        if not isinstance(values,dict): raise ValueError('Preset UI values must be an object.')
        for key,value in values.items():
            field=self._fields.get(key,{})
            if field.get('widget')=='number': _finite(value,field['label'],field.get('min'),field.get('max'),field.get('precision')==0)
            if field.get('widget')=='checkbox' and not isinstance(value,bool): raise ValueError(field['label']+' must be true or false.')
            if field.get('widget')=='select' and field.get('options') and value not in {r['value'] for r in field['options']}:
                # Dynamic contact/material choices are resolved separately.
                if key not in ('ui.electrical.selected_contact_id','ui.electrical.selected_material_id'):
                    raise ValueError('Preset contains an invalid '+field['label'].lower()+'.')
        search.setdefault(self.UI_NAMESPACE,{}).setdefault('values',{}).update(copy.deepcopy(values))
        from qt_core import desktop_settings,desktop_performance,desktop_search
        desktop_settings(project['settings']); desktop_performance(project['performance']); desktop_search(search)
        from optical_unit_cell import validate_unit_cell
        validate_unit_cell(project['settings'].get('optical_unit_cell'),self.store.device)
        return project

    def preview_preset(self, payload):
        try:
            project=self._preset_project(payload)
            current=self.store.project(); changes=[]
            for namespace in ('settings','performance','desktop_search'):
                for key,value in project[namespace].items():
                    if current[namespace].get(key)!=value:
                        changes.append(dict(key=namespace+'.'+key,before=current[namespace].get(key),after=copy.deepcopy(value)))
            return dict(changes=changes,errors=[])
        except (ValueError,TypeError,KeyError,OSError) as exc:
            return dict(changes=[],errors=[str(exc)])

    def import_preset(self, payload):
        project=self._preset_project(payload)
        undo=list(self.store._undo)
        self.store.load_project(project)
        self.store._undo=undo
        return self.export_preset(payload.get('scope','all'))
