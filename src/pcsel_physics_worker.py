"""Fixed standalone optional-engine worker for editable Legume slab modes."""
import csv
import json
from pathlib import Path
import sys


def main():
    source=Path(sys.argv[1]);cfg=json.loads(source.read_text(encoding='utf-8'));directory=source.parent
    sys.path[:0]=cfg.get('runtime',{}).get('module_paths',[])
    import numpy as np
    import legume
    crystal=legume.PhotCryst(legume.Lattice('square'),eps_l=cfg['bottom_index']**2,eps_u=cfg['top_index']**2)
    for row in reversed(cfg['layers']):
        crystal.add_layer(d=row['thickness_nm']/cfg['lattice_nm'],eps_b=row['index']**2)
        if row['patterned']:
            for shape in cfg['shapes']:
                if shape['shape']=='circle':
                    primitive=legume.Circle(eps=cfg['inclusion_index']**2,x_cent=shape['center'][0],y_cent=shape['center'][1],r=shape['radius'])
                else:
                    points=np.array(shape['vertices']);primitive=legume.Poly(eps=cfg['inclusion_index']**2,x_edges=points[:,0],y_edges=points[:,1])
                crystal.add_shape(primitive)
    solver=legume.GuidedModeExp(crystal,gmax=cfg['gmax'],truncate_g='abs')
    kpoints=2*np.pi*np.asarray(cfg.get('kpoints',[[0.,0.]])).T
    solver.run(kpoints=kpoints,gmode_inds=cfg['guided_modes'],numeig=cfg['num_modes'],compute_im=True,
        verbose=False,gmode_step=.001,gmode_tol=1e-10)
    records=[]
    for ki,point in enumerate(kpoints.T):
        for band,(freq,imag) in enumerate(zip(solver.freqs[ki],solver.freqs_im[ki])):
            records.append(dict(k_index=ki,kx=float(point[0]/(2*np.pi)),ky=float(point[1]/(2*np.pi)),band=band,
                frequency=float(freq),frequency_imag=float(imag),wavelength_nm=float(cfg['lattice_nm']/freq),
                Q=float(freq/(2*abs(imag))) if imag else None))
    with (directory/'gme_modes.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    result=dict(status='complete',engine='pcsel',model='gme',modes=records,artifacts=['gme_modes.csv'],
        engine_version=getattr(legume,'__version__','unknown'),convergence_established=False,
        approximation='Guided-mode expansion of an explicit lossless patterned slab; radiation loss is perturbative.')
    (directory/'engine_result.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    print('ODS_EVENT '+json.dumps(dict(kind='log',message='Legume slab modes and radiation losses calculated.')),flush=True)


if __name__=='__main__':main()
