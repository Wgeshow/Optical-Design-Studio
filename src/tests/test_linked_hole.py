import copy
import unittest
from model import prepare
from peak_optimizer import parse_search, designs
from ml_optimizer import model_for
from target_optimizer import values_for, family
from target_ui import target_project, HOLE_COLS
from test_backend import MATERIALS, LAYERS, PATTERNS, SETTINGS

class LinkedHoleTests(unittest.TestCase):
    def compile(self, shape='circle'):
        project=copy.deepcopy(dict(materials=MATERIALS,layers=LAYERS,patterns=PATTERNS,settings=SETTINGS))
        layer=copy.deepcopy(project['layers'][1]); layer['Name']='Second'
        project['layers'].insert(2,layer)
        holes=[dict(zip(HOLE_COLS,[name,shape,.1,.2,.05,.1])) for name in ['Device','Second']]
        result,bounds=target_project(project,holes,[],1550,5,1000,20,.2,3,linked_hole=True)
        base=prepare(result['materials'],result['layers'],result['patterns'],{},result['settings'])
        cfg=parse_search(base,bounds,{})
        return base,cfg,project

    def test_circle_is_one_dimension_and_keeps_alignment(self):
        base,cfg,original=self.compile()
        self.assertEqual(cfg['design_count'],3)
        for candidate in designs(base,cfg):
            a,b=candidate['patterns']
            for key in ('shape','sx','sy','cx','cy','angle'):
                self.assertEqual(a[key],b[key])
            self.assertEqual(values_for(candidate,cfg),[a['sx']])
            self.assertEqual(family(candidate,cfg),family(base,cfg))
        self.assertEqual(len(original['patterns']),1)

    def test_ellipse_has_two_shared_dimensions_in_ml_candidates(self):
        base,cfg,_=self.compile('ellipse')
        self.assertEqual(cfg['design_count'],9)
        candidate=model_for(base,cfg,[.12,.07])
        for pattern in candidate['patterns']:
            self.assertEqual((pattern['sx'],pattern['sy']),(.12,.07))
        candidate['patterns'][1]['sx']=.13
        with self.assertRaisesRegex(ValueError,'linked hole'):
            values_for(candidate,cfg)

    def test_conflicting_linked_bound_is_rejected(self):
        base,cfg,_=self.compile()
        bound=dict(Parameter='radius',Target='1',Min=.1,Max=.2,Step=.1,linked_targets=[2])
        other=dict(Parameter='radius',Target='2',Min=.1,Max=.2,Step=.1)
        with self.assertRaisesRegex(ValueError,'conflicting'):
            parse_search(base,[bound,other],{})

if __name__=='__main__': unittest.main()
