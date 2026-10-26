"""Fine-mesh allocation, accuracy and cancellation regressions."""
import unittest
from unittest.mock import patch

import numpy as np
from scipy.sparse import diags

from device_model import default_device, validate_device
from electrical_mesh import check_mesh_resources, mesh_resource_estimate, solve_linear_system
from custom_electrical_solver import build_mesh
from electrical_material_library import builtin_materials


class FineMeshTests(unittest.TestCase):
    def test_more_than_old_axis_and_million_cell_limits_survive_validation(self):
        device = default_device()
        device['mesh'].update(nx=512, ny=512, nz_per_layer=8, max_nodes=0)
        checked = validate_device(device)
        self.assertEqual(checked['mesh']['nx'], 512)
        self.assertEqual(mesh_resource_estimate(checked)['cells'], 12_582_912)
        self.assertEqual(mesh_resource_estimate(checked)['linear_solver'], 'Jacobi-scaled CG')

    def test_explicit_user_cell_budget_is_preserved(self):
        device = default_device()
        device['mesh'].update(nx=512, ny=512, max_nodes=120_000)
        with self.assertRaisesRegex(ValueError, 'your cell budget'):
            validate_device(device)
        device['mesh']['max_nodes'] = 0
        self.assertEqual(validate_device(device)['mesh']['max_nodes'], 0)

    def test_ram_guard_happens_before_mesh_array_allocation(self):
        with patch('electrical_mesh.available_memory_bytes', return_value=1024**2), \
             patch('custom_electrical_solver.np.linspace') as allocate:
            with self.assertRaisesRegex(ValueError, 'resolution has not been reduced'):
                build_mesh(default_device(), builtin_materials())
            allocate.assert_not_called()

    def test_resource_shape_counts_only_active_layers(self):
        device = default_device()
        device['layers'][0]['enabled'] = False
        estimate = check_mesh_resources(device, available_bytes=64*1024**3)
        self.assertEqual(estimate['shape'], [16, 16, 40])
        self.assertEqual(estimate['cells'], 10_240)

    def test_scaled_cg_matches_independent_known_discrete_solution(self):
        size = 1001
        matrix = diags([-np.ones(size-1), np.full(size, 2.), -np.ones(size-1)], [-1, 0, 1], format='csr')
        exact = np.sin(np.pi*np.arange(1, size+1)/(size+1))
        values, checks = solve_linear_system(matrix, matrix@exact, force_iterative=True)
        np.testing.assert_allclose(values, exact, rtol=1e-9, atol=1e-10)
        self.assertEqual(checks['method'], 'Jacobi-scaled CG')
        self.assertGreater(checks['iterations'], 0)

    def test_scaled_cg_handles_many_decades_of_diagonal_contrast(self):
        diagonal = np.geomspace(1e-18, 1e3, 1001)
        exact = np.linspace(-1., 2., len(diagonal))
        values, _ = solve_linear_system(diags(diagonal), diagonal*exact, force_iterative=True)
        np.testing.assert_allclose(values, exact, atol=2e-15)

    def test_cg_checks_cancellation_during_iterations(self):
        matrix = diags([-np.ones(99), np.full(100, 2.), -np.ones(99)], [-1,0,1], format='csr')
        calls = [0]
        def cancelled():
            calls[0] += 1
            return calls[0] >= 3
        with self.assertRaises(InterruptedError):
            solve_linear_system(matrix, np.ones(100), cancelled=cancelled, force_iterative=True)


if __name__ == '__main__':
    unittest.main()
