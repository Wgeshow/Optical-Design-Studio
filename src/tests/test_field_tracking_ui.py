import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data_library import DataLibrary, write_json
from field_tracking_ui import (saved_datasets, _safe_directory, plot_comparison,
                               condition_table, compare_saved, save_comparison)


def sample(directory, wavelength=1550, mode='fixed_target', thickness=1., scale=1., maps=False):
    directory.mkdir(parents=True)
    model = dict(ax=1., ay=1., basis=9, polarization='s', phi=0, points=[[0,wavelength,0]],
        materials=[dict(name='Air', model='constant_nk', a=1., b=0),
                   dict(name='Film', model='constant_nk', a=2., b=.01)],
        layers=[dict(name='Top', material='Air', thickness=0.),
                dict(name='PCS', material='Film', thickness=thickness),
                dict(name='Bottom', material='Air', thickness=0.)],
        patterns=[dict(layer='PCS',material='Air',shape='circle',cx=0.,cy=0.,sx=.2,sy=0.,angle=0.)])
    write_json(directory/'field_model.json', dict(model=model,wavelength_nm=wavelength,settings=dict(sampling_mode=mode)))
    write_json(directory/'field_features.json',dict(wavelength_nm=wavelength))
    headers=['plane','layer','x_um','y_um','z_um','Ex_real','Ex_imag','Ey_real','Ey_imag','Ez_real','Ez_imag','E2','material']
    with (directory/'electric_fields.csv').open('w',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(headers)
        for z in (1/6,.5,5/6):
            for x in (-1/3,0.,1/3):
                for y in (-1/3,0.,1/3):
                    e2=scale*(1+x*x+y*y)
                    writer.writerow(['volume_samples','PCS',x,y,z*thickness,np.sqrt(e2),0,0,0,0,0,e2,'Air' if abs(x)+abs(y)<.2 else 'Film'])
        if maps:
            for x in (-1/3,0.,1/3):
                for y in (-1/3,0.,1/3):
                    writer.writerow(['xy','PCS',x,y,.5*thickness,1,0,0,0,0,0,scale,'Film'])
                for z in (.1,.5,.9):
                    writer.writerow(['xz','PCS',x,0,z*thickness,1,0,0,0,0,0,scale,'Film'])
    return model


class FieldTrackingUITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.library=DataLibrary(self.root)
        self.reference=self.library.runs/'run01'/'design01'/'fields'
        self.current=self.library.runs/'run01'/'design02'/'fields'
        sample(self.reference)
        sample(self.current,thickness=2.,scale=4.)

    def tearDown(self):
        plt.close('all')
        self.temp.cleanup()

    def test_discovery_retains_lineage_and_filters_wavelength_and_mode(self):
        sample(self.library.runs/'run02'/'resonance_fields',wavelength=1551,mode='selected_resonance')
        choices=saved_datasets(self.library,'Fixed target wavelength','run01',1550)
        self.assertEqual([value for _,value in choices],['run01/design01/fields','run01/design02/fields'])
        self.assertEqual(len(saved_datasets(self.library,'Selected resonance')),1)
        self.assertEqual(len(saved_datasets(self.library,wavelength_nm=1552)),0)
        (self.reference/'field_features.json').unlink()
        self.assertEqual(len(saved_datasets(self.library,'Fixed target wavelength')),1)

    def test_arbitrary_paths_cannot_select_files_outside_library(self):
        with self.assertRaises(ValueError):
            _safe_directory(self.library,'../../outside')
        with self.assertRaises(ValueError):
            _safe_directory(self.library,'')

    def test_shared_scale_and_physical_depth_preserved_for_coarse_maps(self):
        figure=plot_comparison(self.reference,self.current)
        plots=figure.axes[:4]
        norms=[axis.collections[0].norm for axis in plots]
        self.assertTrue(all(norm is norms[0] for norm in norms))
        self.assertGreater(norms[0].vmax,4.)
        self.assertEqual(plots[1].get_ylim(),(0.,2.))
        self.assertEqual(plots[3].get_ylim(),(0.,2.))
        self.assertIn('3 depths/layer',plots[1].get_title())
        self.assertIn('training grid',plots[0].get_title())
        output=self.root/'coarse.png'
        figure.savefig(output)
        self.assertGreater(output.stat().st_size,1000)

    def test_layer_relative_depth_compares_different_thicknesses(self):
        figure=plot_comparison(self.reference,self.current,alignment='Layer-relative coordinates')
        self.assertEqual(figure.axes[1].get_ylim(),(0.,1.))
        self.assertEqual(figure.axes[3].get_ylim(),(0.,1.))
        self.assertEqual(figure.axes[0].get_xlim(),(-.5,.5))

    def test_explicit_maps_preferred_and_invalid_layer_rejected(self):
        mapped=self.library.runs/'run03'/'fields'
        sample(mapped,maps=True)
        figure=plot_comparison(mapped,self.current)
        self.assertNotIn('training grid',figure.axes[0].get_title())
        self.assertIn('y = 0',figure.axes[1].get_title())
        with self.assertRaisesRegex(ValueError,'XY layer'):
            plot_comparison(mapped,self.current,layer='Missing')

    def test_conditions_report_changed_thickness_and_evaluated_nk(self):
        table=condition_table(self.reference,self.current).set_index('Condition')
        self.assertTrue(table.loc['layer/PCS/thickness_um','Changed'])
        self.assertAlmostEqual(float(table.loc['material/Film/n_at_sample_wavelength','Current']),2.)
        self.assertAlmostEqual(float(table.loc['material/Film/k_at_sample_wavelength','Current']),.01)
        self.assertEqual(table.loc['pattern/1/shape','Current'],'circle')

    def test_comparison_saves_portable_raw_inputs_and_metrics(self):
        with patch.object(self.library,'export',side_effect=lambda identifier:str(self.library.runs/identifier)):
            bundle,message=save_comparison(self.library,'run01/design01/fields','run01/design02/fields')
        directory=Path(bundle)
        for name in ('field_comparison.json','field_comparison_metrics.csv','design_conditions.csv','field_comparison.png','reference_electric_fields.csv','current_electric_fields.csv','reference_field_model.json','current_field_model.json','library_record.json'):
            self.assertTrue((directory/name).is_file(),name)
        payload=json.loads((directory/'field_comparison.json').read_text())
        self.assertEqual(payload['reference'],'run01/design01/fields')
        self.assertAlmostEqual(payload['comparison']['field_overlap'],1.)
        self.assertEqual(payload['current_descriptor']['schema_version'],2)
        self.assertEqual(len(saved_datasets(self.library)),2) # exports do not duplicate training snapshots

    def test_incompatible_overlap_is_explicit_but_maps_still_render(self):
        path=self.current/'field_model.json'
        snapshot=json.loads(path.read_text())
        snapshot['model']['polarization']='p'
        write_json(path,snapshot)
        result=compare_saved(self.library,'run01/design01/fields','run01/design02/fields')
        self.assertIn('Overlap unavailable',result[3])
        self.assertIn('illumination',result[3])

    def test_energy_flow_arrows_require_h_and_are_visible_with_saved_h(self):
        figure=plot_comparison(self.reference,self.current,arrows=True)
        self.assertTrue(any('H not saved' in t.get_text() for t in figure.axes[0].texts))
        for path in (self.reference,self.current):
            data=pd.read_csv(path/'electric_fields.csv')
            for component in ('Hx','Hy','Hz'):
                data[component+'_real']=1. if component=='Hy' else 0.
                data[component+'_imag']=0.
            data.to_csv(path/'electric_fields.csv',index=False)
        figure=plot_comparison(self.reference,self.current,arrows=True)
        self.assertTrue(any(artist.__class__.__name__=='Quiver' for artist in figure.axes[1].collections))
        self.assertIn('magnitude not encoded',figure._suptitle.get_text())


if __name__=='__main__':
    unittest.main()
