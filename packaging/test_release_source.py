"""Exercise the staged release source in isolated native/core test batches."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source'
DEPENDENCIES = Path(os.environ.get('ODS_RELEASE_DEPENDENCIES', ROOT.parent / 's4_ui_redesign'))
GROUPS = {
    'scientific-rendering': [
        'tests.test_native_figure', 'tests.test_native_material_saved_plots',
        'tests.test_native_scientific_callers', 'tests.test_native_field_volume',
        'tests.test_field_volume', 'tests.test_qt_native_spectrum',
        'tests.test_publication_plot', 'tests.test_plot_hover',
        'tests.test_material_display_metadata', 'tests.test_material_policy_transactions',
        'tests.test_material_interpolation', 'tests.test_material_provenance',
        'tests.test_material_inspector_metadata', 'tests.test_geometry_material_colors',
        'tests.test_geometry_material_opacity', 'tests.test_material_preview_opacity',
    ],
    'desktop-interface': [
        'tests.test_qt_app', 'tests.test_qt_core', 'tests.test_project_file_ui',
        'tests.test_qt_materials_library', 'tests.test_reference_materials',
        'tests.test_qt_fdtd', 'tests.test_qt_ai_search',
        'tests.test_reference_structure', 'tests.test_four_looks',
        'tests.test_settings_layout', 'tests.test_reference_help',
        'tests.test_help_capture_portability', 'tests.test_redesign_interactions',
        'tests.test_qt_structure', 'tests.test_structure_sync.StructureSyncTests',
        'tests.test_lattice_diagram',
        'tests.test_windows_desktop_glass', 'tests.test_qt_chrome', 'tests.test_windows_custom_frame',
        'tests.test_qt_desktop_surfaces', 'tests.test_window_state_restore',
        'tests.test_qt_simulation_setup', 'tests.test_qt_device_lighting', 'tests.test_qt_optical_results',
        'tests.test_qt_original_optical_workspace','tests.test_qt_workspace_start','tests.test_device_studio_help','tests.test_qt_setup_dispatch',
        'tests.test_qt_startup_transition', 'tests.test_installer_chrome_smoke',
        'tests.test_qt_input_diagnostics', 'tests.test_qt_research_workspaces',
        'tests.test_qt_photonic_bands_usability',
        'tests.test_qt_photonic_band_results',
        'tests.test_qt_photonic_crystal_3d',
        'tests.test_qt_photonic_runtime',
        'tests.test_simulation_documents',
    ],
    'release-and-data': [
        'tests.test_app_version', 'tests.test_desktop_runtime',
        'tests.test_startup_helpers', 'tests.test_update_client',
        'tests.test_solver_environment',
        'tests.test_update_install', 'tests.test_update_credentials',
    ],
    'simulation-performance': [
        'tests.test_compute_speed', 'tests.test_scan_scaling',
        'tests.test_grid_sweep', 'tests.test_peak_optimizer', 'tests.test_spectral_features',
        'tests.test_scan_scaling_ui', 'tests.test_backend',
        'tests.test_simulation_fields', 'tests.test_contour_sweep',
        'tests.test_field_tracking',
        'tests.test_contour_learning', 'tests.test_airhole_field_objective',
        'tests.test_target_fields', 'tests.test_field_ml',
        'tests.test_field_target_integration',
    ],
    'device-electrical-and-coupled': [
        'tests.test_simulation_setup_state', 'tests.test_electrical_solver',
        'tests.test_electrical_material_library', 'tests.test_electrical_optics',
        'tests.test_electrical_terminal_studies', 'tests.test_electrical_integration',
        'tests.test_electrical_thermal', 'tests.test_thermal_integration',
        'tests.test_research_simulation', 'tests.test_photonic_bands',
        'tests.test_photonic_overlap',
        'tests.test_research_catalog', 'tests.test_benchmark_registry',
        'tests.test_sesame_transport',
        'tests.test_pcsel_research', 'tests.test_pcsel_aperture',
        'tests.test_advanced_transport',
        'tests.test_pcsel_transport_study',
        'tests.test_advanced_optical_tunnelling',
        'tests.test_electrical_temperature',
        'tests.test_custom_electrical_device', 'tests.test_custom_device_project',
        'tests.test_custom_device_optics', 'tests.test_contact_optics',
        'tests.test_optical_unit_cell', 'tests.test_pc_array', 'tests.test_pc_optical_defaults', 'tests.test_pc_library_roundtrip',
    ],
}


def write_report(path, value):
    """Commit a complete checkpoint; interrupted children leave no reusable result."""
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    for attempt in range(10):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt == 9:
                raise
            # Windows sync/antivirus readers can briefly retain a file handle.
            time.sleep(0.05 * (attempt + 1))


def check_source(inventory):
    for relative, expected in inventory['files'].items():
        path = SOURCE / relative
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected['sha256']:
            raise RuntimeError('Staged source changed during verification: ' + relative)


def run_target(target, report, source_tree_sha256):
    """The child owns the checkpoint, even if its parent is subsequently interrupted."""
    import unittest
    started = time.monotonic()
    suite = unittest.defaultTestLoader.loadTestsFromName(target)
    def cases(current):
        for entry in current:
            if isinstance(entry, unittest.TestSuite):
                yield from cases(entry)
            else:
                yield entry
    case_ids = [test.id() for test in cases(suite)]
    if len(case_ids) != len(set(case_ids)):
        raise RuntimeError('Duplicate test IDs prevent reliable checkpoints: ' + target)
    checkpoint_path = Path(report).with_suffix('.cases.json')
    outcomes = {}
    fixture_error = [False]
    if checkpoint_path.is_file():
        try:
            prior = json.loads(checkpoint_path.read_text(encoding='utf-8'))
            if (prior.get('target') == target and prior.get('source_tree_sha256') == source_tree_sha256
                    and prior.get('case_ids') == case_ids and not prior.get('fixture_error')):
                outcomes = {key: value for key, value in prior['outcomes'].items()
                            if key in case_ids and value.get('status') in ('passed', 'skipped', 'expected_failure')}
        except (OSError, ValueError, KeyError):
            outcomes = {}
    retained = len(outcomes)
    def checkpoint():
        write_report(checkpoint_path, dict(
            target=target, source_tree_sha256=source_tree_sha256, case_ids=case_ids,
            outcomes=outcomes, completed_cases=len(outcomes), required_cases=len(case_ids),
            fixture_error=fixture_error[0],
        ))
    def pending(current):
        return unittest.TestSuite(
            pending(entry) if isinstance(entry, unittest.TestSuite) else entry
            for entry in current
            if isinstance(entry, unittest.TestSuite) or entry.id() not in outcomes
        )
    class CheckpointResult(unittest.TextTestResult):
        def startTest(self, test):
            self.current_started = time.monotonic()
            super().startTest(test)
        def addSuccess(self, test):
            super().addSuccess(test)
            outcomes[test.id()] = dict(status='passed')
        def addSkip(self, test, reason):
            super().addSkip(test, reason)
            outcomes[test.id()] = dict(status='skipped', reason=reason)
        def addExpectedFailure(self, test, error):
            super().addExpectedFailure(test, error)
            outcomes[test.id()] = dict(status='expected_failure')
        def addUnexpectedSuccess(self, test):
            super().addUnexpectedSuccess(test)
            outcomes[test.id()] = dict(status='unexpected_success')
        def addFailure(self, test, error):
            super().addFailure(test, error)
            outcomes[test.id()] = dict(status='failed', detail=self._exc_info_to_string(error, test))
        def addError(self, test, error):
            super().addError(test, error)
            outcomes[test.id()] = dict(status='error', detail=self._exc_info_to_string(error, test))
            if not isinstance(test, unittest.TestCase):
                # setUpClass/tearDownClass have no stopTest callback. Persist the
                # invalidation immediately, including if this child is interrupted.
                fixture_error[0] = True
                checkpoint()
        def addSubTest(self, test, subtest, error):
            super().addSubTest(test, subtest, error)
            if error is not None:
                outcomes[test.id()] = dict(
                    status='failed' if issubclass(error[0], test.failureException) else 'error',
                    detail=self._exc_info_to_string(error, subtest))
        def stopTest(self, test):
            outcome = outcomes.setdefault(test.id(), dict(status='error', detail='No final test outcome'))
            outcome['elapsed_seconds'] = time.monotonic() - self.current_started
            checkpoint()
            super().stopTest(test)
    if retained:
        print('Retaining ' + str(retained) + ' completed cases in ' + target, flush=True)
    result = unittest.TextTestRunner(verbosity=2, resultclass=CheckpointResult).run(pending(suite))
    passed = (result.wasSuccessful() and len(outcomes) == len(case_ids)
              and all(value['status'] in ('passed', 'skipped', 'expected_failure') for value in outcomes.values()))
    exit_code = 0 if passed else 1
    skipped = sum(value['status'] == 'skipped' for value in outcomes.values())
    if not passed:
        write_report(checkpoint_path.with_suffix('.failure.json'), dict(
            target=target, source_tree_sha256=source_tree_sha256, case_ids=case_ids,
            outcomes=outcomes, fixture_error=fixture_error[0], failures=len(result.failures),
            errors=len(result.errors), unexpected_successes=len(result.unexpectedSuccesses),
        ))
        outcomes.clear()
        checkpoint()
    write_report(Path(report), dict(
        target=target, targets=[target], source_tree_sha256=source_tree_sha256,
        tests_run=len(case_ids) if passed else retained + result.testsRun,
        failures=len(result.failures), errors=len(result.errors),
        skipped=skipped,
        passed=passed, exit_code=exit_code, retained_cases=retained, executed_cases=result.testsRun,
        case_ids=case_ids, case_checkpoint=str(checkpoint_path),
        elapsed_seconds=time.monotonic() - started, checkpoint_complete=True,
    ))
    return exit_code


def completed_report(report, source_tree_sha256, targets):
    if not report.is_file():
        return None
    try:
        result = json.loads(report.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if (result.get('passed') and result.get('exit_code') == 0
            and result.get('source_tree_sha256') == source_tree_sha256
            and result.get('targets') == targets
            and result.get('tests_run', 0) > 0
            and result.get('failures') == result.get('errors') == 0):
        return result
    return None


def main():
    inventory = json.loads((ROOT / 'stage-manifest.json').read_text(encoding='utf-8'))
    source_tree_sha256 = inventory['source_tree_sha256']
    check_source(inventory)
    output = ROOT / 'source-test-logs'
    output.mkdir(exist_ok=True)
    environment = dict(os.environ)
    environment['PYTHONPATH'] = os.pathsep.join([
        str(SOURCE), str(SOURCE / 'tests'), str(DEPENDENCIES / 'ml_dependencies'),
        str(DEPENDENCIES / 'geometry_dependencies'), str(DEPENDENCIES / 'plot_dependencies'),
    ])
    environment['QT_QPA_PLATFORM'] = 'offscreen'
    environment['MPLBACKEND'] = 'Agg'
    environment['PYTHONIOENCODING'] = 'utf-8'
    for variable in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
        environment[variable] = '1'
    environment['S4_LIBRARY_ROOT'] = str(output / 'isolated-library')
    results = {}
    for name, targets in GROUPS.items():
        report = output / (name + '.json')
        completed = completed_report(report, source_tree_sha256, targets)
        if completed:
            results[name] = completed
            print('Retaining completed staged tests: ' + name, flush=True)
            continue
        if name != 'scientific-rendering':
            checkpoints = output / name
            checkpoints.mkdir(exist_ok=True)
            modules = {}
            for target in targets:
                module_report = checkpoints / (target + '.json')
                module_log = checkpoints / (target + '.log')
                completed = completed_report(module_report, source_tree_sha256, [target])
                if completed:
                    modules[target] = completed
                    print('Retaining completed staged target: ' + target, flush=True)
                    continue
                print('Testing staged target: ' + target, flush=True)
                started = time.monotonic()
                with module_log.open('w', encoding='utf-8') as log:
                    try:
                        process = subprocess.run([
                            sys.executable, str(Path(__file__).resolve()), '--run-target',
                            target, str(module_report), source_tree_sha256,
                        ], cwd=SOURCE, env=environment, stdout=log, stderr=subprocess.STDOUT,
                            timeout=3600)
                    except subprocess.TimeoutExpired:
                        write_report(module_report, dict(
                            target=target, targets=[target], source_tree_sha256=source_tree_sha256,
                            tests_run=0, failures=0, errors=1, skipped=0, passed=False,
                            exit_code=124, elapsed_seconds=time.monotonic() - started,
                            checkpoint_complete=False, error='Target exceeded 3600 seconds',
                        ))
                        process = None
                if not module_report.is_file():
                    raise RuntimeError('Source target did not write a report: ' + target)
                result = json.loads(module_report.read_text(encoding='utf-8'))
                if process is not None and result['exit_code'] != process.returncode:
                    result.update(passed=False, exit_code=process.returncode,
                                  error='Child exit code differs from its checkpoint')
                    write_report(module_report, result)
                modules[target] = result
                print(target + ': ' + json.dumps(result), flush=True)
                if not result['passed']:
                    print(module_log.read_text(encoding='utf-8', errors='replace')[-7000:], flush=True)
            result = dict(
                tests_run=sum(module['tests_run'] for module in modules.values()),
                failures=sum(module['failures'] for module in modules.values()),
                errors=sum(module['errors'] for module in modules.values()),
                skipped=sum(module['skipped'] for module in modules.values()),
                elapsed_seconds=sum(module['elapsed_seconds'] for module in modules.values()),
                passed=len(modules) == len(targets) and all(module['passed'] for module in modules.values()),
                source_tree_sha256=source_tree_sha256, targets=targets, modules=modules,
                checkpointed_targets=True,
            )
            result['exit_code'] = 0 if result['passed'] else 1
            write_report(report, result)
            results[name] = result
            print(name + ': ' + json.dumps({key: value for key, value in result.items()
                                           if key != 'modules'}), flush=True)
            continue
        runner = ('import json,sys,unittest; '
                  'suite=unittest.defaultTestLoader.loadTestsFromNames(sys.argv[2:]); '
                  'result=unittest.TextTestRunner(verbosity=2).run(suite); '
                  "open(sys.argv[1],'w',encoding='utf-8').write(json.dumps(dict("
                  'tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors),'
                  'skipped=len(result.skipped),passed=result.wasSuccessful()),indent=2)); '
                  'sys.exit(0 if result.wasSuccessful() else 1)')
        started = time.monotonic()
        print('Testing staged release: ' + name, flush=True)
        with (output / (name + '.log')).open('w', encoding='utf-8') as log:
            process = subprocess.run([sys.executable, '-c', runner, str(report), *targets],
                                     cwd=SOURCE, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                     timeout=3600)
        if not report.is_file():
            raise RuntimeError('Source test process did not write a report: ' + name)
        result = json.loads(report.read_text(encoding='utf-8'))
        result.update(elapsed_seconds=time.monotonic() - started, exit_code=process.returncode,
                      source_tree_sha256=source_tree_sha256, targets=targets)
        write_report(report, result)
        results[name] = result
        print(name + ': ' + json.dumps(result), flush=True)
        if process.returncode:
            print((output / (name + '.log')).read_text(encoding='utf-8', errors='replace')[-7000:], flush=True)
            break
    check_source(inventory)
    summary = dict(version='1.4.0-alpha.9', source_tree_sha256=source_tree_sha256,
                   tests_run=sum(result['tests_run'] for result in results.values()),
                   failures=sum(result['failures'] for result in results.values()),
                   errors=sum(result['errors'] for result in results.values()),
                   skipped=sum(result['skipped'] for result in results.values()), groups=results,
                   passed=len(results) == len(GROUPS) and all(result['passed'] for result in results.values()))
    write_report(ROOT / 'source-test-report.json', summary)
    print(json.dumps({key: value for key, value in summary.items() if key != 'groups'}), flush=True)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == '--run-target':
        raise SystemExit(run_target(*sys.argv[2:]))
    raise SystemExit(main())
