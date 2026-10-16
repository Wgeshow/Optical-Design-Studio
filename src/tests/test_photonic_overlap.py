"""Legume eligibility: positive-area periodic overlap, independent of solver runs."""
import copy
import math
import sys
import unittest

from input_diagnostics import InputValidationError
from photonic_bands import prepare


def circle(identity,center,radius):
    return dict(id=identity,shape='circle',center=center,radius=radius,epsilon=12.)


def block(identity,center,size,axes=((1.,0.),(0.,1.))):
    return dict(id=identity,shape='block',center=center,size=size,axes=[list(row) for row in axes],epsilon=12.)


def settings(objects,lattice=None):
    return dict(dimension=2,lattice_vectors=lattice or [[1.,0.],[0.,1.]],geometry=objects,
        background_epsilon=1.,k_points=[[.1,.1]],solver='legume',gmax=3.,num_bands=4,
        runtime=dict(mode='local',executable=sys.executable))


class PeriodicOverlapTests(unittest.TestCase):
    def rejected(self,cfg,identity,field):
        with self.assertRaises(InputValidationError) as caught:
            prepare({},cfg)
        row=caught.exception.diagnostics[0]
        self.assertEqual(row['code'],'unsupported_periodic_overlap')
        self.assertEqual(row['object_id'],identity)
        self.assertTrue(row['field'].endswith(field))
        self.assertIn('Use MPB or separate the objects',row['message'])

    def test_overlap_targets_second_object_and_mpb_stays_supported(self):
        cfg=settings([circle('first',[0.,0.],.15),circle('second',[.2,0.],.1)])
        original=copy.deepcopy(cfg)
        self.rejected(cfg,'second','center')
        self.assertEqual(cfg,original)
        cfg.update(solver='mpb',runtime=dict(mode='wsl',executable='mpb',distro='Ubuntu'))
        self.assertEqual(len(prepare({},cfg)['geometry']),2)

    def test_periodic_pair_overlap_across_cell_edge(self):
        self.rejected(settings([circle('left',[-.45,0.],.08),circle('right',[.45,0.],.08)]),'right','center')
        self.rejected(settings([circle('left',[7.55,-3.],.08),circle('right',[-6.55,4.],.08)]),'right','center')

    def test_circle_self_overlap_and_exact_tangencies(self):
        self.rejected(settings([circle('wide',[0.,0.],.5001)]),'wide','radius')
        prepare({},settings([circle('touch',[0.,0.],.5)]))
        prepare({},settings([circle('a',[0.,0.],.1),circle('b',[.2,0.],.1)]))
        prepare({},settings([circle('a',[-.4,0.],.1),circle('b',[.4,0.],.1)]))

    def test_skew_cell_nearest_image_is_combination_of_lattice_vectors(self):
        lattice=[[1.,0.],[.9,.2]]
        self.rejected(settings([circle('skew',[0.,0.],.12)],lattice),'skew','radius')
        prepare({},settings([circle('touch',[0.,0.],math.sqrt(.05)/2)],lattice))

    def test_rotated_blocks_overlap_or_share_only_a_face(self):
        root=.5**.5
        axes=[[root,root],[-root,root]]
        first=block('a',[0.,0.],[.2,.1],axes)
        self.rejected(settings([first,block('b',[.19*root,.19*root],[.2,.1],axes)]),'b','center')
        prepare({},settings([first,block('touch',[.2*root,.2*root],[.2,.1],axes)]))
        prepare({},settings([block('a',[0.,-.1],[.8,.02]),block('b',[0.,.1],[.8,.02])]))

    def test_periodic_rotated_block_in_skew_cell(self):
        lattice=[[1.,0.],[.9,.2]]
        axes=[[.1,-.2],[.2,.1]]
        self.rejected(settings([block('wide',[0.,0.],[.24,.05],axes)],lattice),'wide','size')
        prepare({},settings([block('touch',[0.,0.],[math.sqrt(.05),.05],axes)],lattice))

    def test_circle_and_skew_block_intersection_and_tangency(self):
        shape=block('parallelogram',[0.,0.],[.2,.2],[[1.,0.],[.5,math.sqrt(3)/2]])
        self.rejected(settings([shape,circle('inside',[0.,0.],.02)]),'inside','center')
        # The upper horizontal face is y=sqrt(3)*0.05.
        prepare({},settings([shape,circle('touch',[.05,math.sqrt(3)*.05+.04],.04)]))
        self.rejected(settings([shape,circle('cross',[.05,math.sqrt(3)*.05+.039],.04)]),'cross','center')

    def test_extreme_skew_has_explicit_eligibility_limit(self):
        with self.assertRaises(InputValidationError) as caught:
            prepare({},settings([circle('wide',[0.,0.],.1)],[[1.,0.],[1.,1e-8]]))
        self.assertEqual(caught.exception.diagnostics[0]['code'],'periodic_geometry_check_limit')
        self.assertIn('Use MPB',str(caught.exception))


if __name__=='__main__':unittest.main()
