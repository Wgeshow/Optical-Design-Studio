"""The optional thermal solver must be present in source and both executables."""
import unittest

import package_release
import stage_release
import verify_release
from test_native_setup_packaging import hidden_modules


class ThermalPackagingTests(unittest.TestCase):
    def test_solver_and_integration_tests_are_required_release_inputs(self):
        import test_release_source
        for modules in (stage_release.REQUIRED_MODULES, package_release.REQUIRED_FROZEN_MODULES,
                        verify_release.GUI_MODULES, verify_release.BACKEND_MODULES, hidden_modules()):
            for module in ('electrical_thermal', 'research_simulation', 'photonic_bands',
                           'thermal_study','research_catalog','research_diagnostics','benchmark_registry',
                           'research_physics_runtime','research_physics_worker','sesame_transport',
                           'input_diagnostics','qt_input_diagnostics','qt_photonic_bands','qt_photonic_band_results','qt_photonic_crystal_3d','qt_photonic_runtime','qt_research_studies','qt_research_results','qt_thermal_setup',
                           'qt_study_flow','qt_simulation_flow','qt_legacy_study_workbench','qt_study_fields','qt_study_library', 'qt_simulation_picker','qt_transport_research_setup','qt_high_field_results','qt_pcsel_research_setup','qt_research_runtime','solver_environment','desktop_environment_probe','qt_solver_environment','simulation_documents','qt_study_transfer',
                           'qt_research_common','qt_sesame_setup','pcsel_research','pcsel_aperture','pcsel_optional','pcsel_physics_worker',
                           'advanced_transport','advanced_transport_graph','electrical_temperature','nonlocal_tunnelling','high_field_optics','bandgap_narrowing',
                           'pcsel_transport_study','pcsel_conformal_mesh','pcsel_conformal_solver','pcsel_transport_worker','pcsel_unitcell_transport'):
                self.assertIn(module, modules)
        group = test_release_source.GROUPS['device-electrical-and-coupled']
        self.assertIn('tests.test_electrical_thermal', group)
        self.assertIn('tests.test_thermal_integration', group)

    def test_versioned_benchmark_data_and_worker_are_required(self):
        from pathlib import Path
        source=Path(stage_release.__file__).resolve().parents[1]/'src'
        result=stage_release.validate_benchmark_resources(source)
        self.assertGreaterEqual(result['cases'],17)
        recipe=Path(stage_release.__file__).with_name('OpticalDesignStudio.spec').read_text()
        self.assertIn("(str(source/'research_physics_worker.py'), '.')",recipe)
        self.assertIn("(str(source/'pcsel_physics_worker.py'), '.')",recipe)
        self.assertIn("(str(source/'pcsel_transport_worker.py'), '.')",recipe)
        self.assertIn("(source/'benchmark_data').rglob('*')",recipe)


if __name__ == '__main__':
    unittest.main()
