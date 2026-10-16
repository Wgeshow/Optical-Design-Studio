"""Independent analytic and Jacobian controls for the generalized FE kernel."""
import copy
import unittest
import numpy as np
from pcsel_transport_study import prepare, example_settings
from pcsel_conformal_solver import FiniteElementTransport
from input_diagnostics import InputValidationError


def rectangular_mesh(cfg):
    # Independent six-tetrahedron cube subdivision, repeated vertically.
    width,depth=cfg['period_um'];height=cfg['layers'][0]['thickness_um']
    xy=np.array([[-width/2,-depth/2],[width/2,-depth/2],[width/2,depth/2],[-width/2,depth/2]])
    points=np.concatenate([np.column_stack([xy,np.full(4,z)]) for z in (0,height/2,height)])
    unit=np.array([[0,1,2,6],[0,2,3,6],[0,3,7,6],[0,7,4,6],[0,4,5,6],[0,5,1,6]])
    tets=np.concatenate([unit,unit+4])
    return dict(points_um=points,tetrahedra=tets,layer_index=np.zeros(len(tets),int),void=np.zeros(len(tets),bool))


class ConformalTransportTests(unittest.TestCase):
    def settings(self):
        value=example_settings();value['inclusions']=[]
        return prepare({},value)

    def test_uniform_conductance_matches_analytic_for_changed_dimensions(self):
        for width,height in [(.3,1.),(.6,2.)]:
            cfg=self.settings();cfg['period_um'][0]=width;cfg['layers'][0]['thickness_um']=height
            solver=FiniteElementTransport(cfg,rectangular_mesh(cfg));solver.solve(0,eq=True)
            row=solver.solve(.01)
            expected=1.602176634e-19*100*1e16*(width*.4*1e-8)/(height*1e-4)*.01
            self.assertAlmostEqual(row['current_A']['top']/expected,1.,places=9)
            self.assertLess(row['current_balance_relative'],1e-9)
            self.assertLess(row['quasi_fermi_contact_range_overshoot_V'],1e-9)

    def test_full_residual_jacobian_matches_finite_difference(self):
        cfg=self.settings();cfg['materials']['demo'].update(B_cm3_s=1e-10,C_cm6_s=1e-30,tau_s=1e-9)
        solver=FiniteElementTransport(cfg,rectangular_mesh(cfg))
        rng=np.random.default_rng(17);value=solver.u+rng.normal(0,.001,solver.u.size)
        residual,jacobian,_=solver.evaluate(value)
        direction=rng.normal(size=len(value));step=1e-7
        numerical=(solver.evaluate(value+step*direction,False)[0]-solver.evaluate(value-step*direction,False)[0])/(2*step)
        expected=jacobian@direction
        # Scale each equation by its Jacobian row norm, independently of the
        # very different Poisson and carrier equation physical magnitudes.
        scales=np.asarray(abs(jacobian).sum(axis=1)).ravel()
        np.testing.assert_allclose(numerical/scales,expected/scales,rtol=2e-7,atol=2e-8)

    def test_geometry_validation_preserves_input_and_targets_bad_inclusion(self):
        value=example_settings();before=copy.deepcopy(value)
        cfg=prepare({},value);self.assertEqual(value,before)
        cfg['inclusions'][0]['radius_um']=1.
        with self.assertRaises(InputValidationError) as error:prepare({},cfg)
        self.assertEqual(error.exception.diagnostics[0]['object_id'],'hole')
        self.assertEqual(error.exception.diagnostics[0]['field'],'inclusions.0')


if __name__=='__main__':unittest.main()
