"""Fixed optional-runtime worker for the editable periodic tetrahedral solver."""
import csv
import json
from pathlib import Path
import sys


def main():
    inputs=Path(sys.argv[1]);cfg=json.loads(inputs.read_text(encoding='utf-8'));directory=inputs.parent
    sys.path[1:1]=cfg['runtime'].get('module_paths',[])
    import numpy as np
    from pcsel_conformal_mesh import build
    from pcsel_conformal_solver import FiniteElementTransport
    cancelled=lambda:(directory/'cancel.flag').exists()
    def emit(event):print('ODS_EVENT '+json.dumps(event),flush=True)
    def save(value,path):path.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')
    mesh=build(cfg)
    np.savez_compressed(directory/'transport_mesh.npz',**{k:v for k,v in mesh.items() if isinstance(v,np.ndarray)})
    save(mesh['checks'],directory/'transport_mesh_checks.json')
    model=FiniteElementTransport(cfg,mesh,emit,cancelled)
    summary=dict(status='partial',engine='pcsel_transport',study='conformal',results=[],mesh=mesh['checks'],
        convergence_established=False,method='P1 tetrahedral Fermi-Dirac weak form, lumped charge/recombination, element-average conductivity',
        current_density_reference_area_um2=cfg['period_um'][0]*cfg['period_um'][1],
        limitations=['Ideal full-face ohmic contacts and periodic lateral cell, not a finite aperture.',
            'No monotonicity guarantee on a coarse P1 mesh. Inspect quasi-Fermi overshoot and refine.',
            'B/C/lifetime recombination uses a phenomenological detailed-balance proxy. No quantum confinement or laser gain.'])
    try:
        model.solve(0.,eq=True)
        previous=0.
        for index,bias in enumerate(cfg['biases_V']):
            count=max(1,int(np.ceil(abs(bias-previous)/cfg['max_bias_step_V'])))
            for voltage in np.linspace(previous,bias,count+1)[1:]:
                result=model.solve(float(voltage))
            previous=bias
            filename='conformal_state_'+str(index).zfill(4)+'.npz'
            np.savez_compressed(directory/filename,**model.arrays(),bias_V=bias)
            result['volume_npz']=filename;summary['results'].append(result)
            save(summary,directory/'conformal_transport_summary.json')
        summary['status']='complete'
        if any(row['quasi_fermi_contact_range_overshoot_V']>max(1e-6,10*cfg['tolerance_V']) for row in summary['results']):
            summary['status']='validity_limit'
            summary['status_reason']='Resolved quasi-Fermi overshoot exceeds the explicit bound; refine the mesh before accepting this P1 result.'
    except (RuntimeError,ValueError) as exc:
        summary.update(status='partial',error=str(exc))
        if not summary['results']:raise
    finally:
        save(summary,directory/'conformal_transport_summary.json')
    rows=[dict(voltage_V=row['voltage_V'],top_current_A=row['current_A']['top'],bottom_current_A=row['current_A']['bottom'],
        current_density_A_cm2=row['current_density_A_cm2'],current_balance_relative=row['current_balance_relative'],
        scaled_residual_V=row['scaled_residual_V'],quasi_fermi_overshoot_V=row['quasi_fermi_contact_range_overshoot_V']) for row in summary['results']]
    if rows:
        with (directory/'conformal_iv.csv').open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    summary['artifacts']=['transport_mesh.npz','transport_mesh_checks.json','conformal_transport_summary.json','conformal_iv.csv']+[r['volume_npz'] for r in summary['results']]
    save(summary,directory/'conformal_transport_summary.json');save(summary,directory/'engine_result.json')


if __name__=='__main__':main()
