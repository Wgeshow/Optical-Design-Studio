"""Editable reduced sheet/current, QW rate and lattice-temperature model.

Generalized from the recovered aperture study. The vertical load is a supplied
log-linear J(V) calibration, not a self-consistent semiconductor transport solve.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
import numpy as np
from scipy.sparse import coo_matrix,diags,eye,kron
from scipy.sparse.linalg import spsolve
from scipy.optimize import brentq

Q=1.602176634e-19
HC=1.986445857e-25
KB=8.617333262e-5


def calibration_domain(cfg):
    return dict(lattice_nm=cfg['lattice_nm'],inclusion_index=cfg['inclusion_index'],
        layers=[{k:v for k,v in r.items() if k not in ('id','name')} for r in cfg['layers']],
        shapes=[{k:v for k,v in r.items() if k not in ('id','name','_bounds')} for r in cfg['shapes']])


def prepare_parameters(value,aperture_um,cfg=None):
    from pcsel_research import _error,_number
    if not isinstance(value,dict):_error('aperture','Enter the reduced aperture model parameters.')
    p=copy.deepcopy(value)
    required=['sheet_ohm_square','sheet_temperature_exponent','reference_temperature_K','sink_K',
        'substrate_um','substrate_k_W_mK','thermal_k_exponent','interface_R_m2K_W','epitaxial_R_m2K_W',
        'well_total_nm','capture_ps','escape_ps','barrier_lifetime_ps','escape_activation_eV',
        'A_s1','B_cm3_s','C_cm6_s','g0_cm1','Ntr_cm3','gain_temperature_K',
        'group_index','Gamma_QW','alpha_rad_cm1','alpha_edge_cm1','alpha_internal_cm1',
        'port_fraction','port_transmission','wavelength_nm','load_reference_V','max_temperature_K']
    nonnegative={'sheet_temperature_exponent','thermal_k_exponent','interface_R_m2K_W','epitaxial_R_m2K_W',
        'escape_activation_eV','A_s1','B_cm3_s','C_cm6_s','alpha_edge_cm1','alpha_internal_cm1'}
    allowed=set(required)|{'grid_n','currents_A','contacts','load_anchors','load_source','load_domain',
        'mode_weight','heated','maximum_iterations','voltage_bracket_V','temperature_tolerance_K'}
    if set(p)-allowed:_error('aperture','Unsupported aperture parameters: '+', '.join(sorted(set(p)-allowed)))
    for key in required:
        if key not in p:_error('aperture.'+key,'Supply '+key.replace('_',' ')+' with a source.')
        p[key]=_number(p[key],'aperture.'+key,0 if key in nonnegative else 1e-30)
    for key in ('Gamma_QW','port_fraction','port_transmission'):
        if p[key]>1:_error('aperture.'+key,'This fraction must be between zero and one.')
    if p['sink_K']>=p['max_temperature_K']:_error('aperture.max_temperature_K','The validity limit must exceed the heat-sink temperature.')
    p['grid_n']=_number(p.get('grid_n',20),'aperture.grid_n',4,True)
    if p['grid_n']>200:_error('aperture.grid_n','Use at most 200 cells per direction with this direct sparse solver.')
    p['maximum_iterations']=_number(p.get('maximum_iterations',120),'aperture.maximum_iterations',1,True)
    p['temperature_tolerance_K']=_number(p.get('temperature_tolerance_K',.002),'aperture.temperature_tolerance_K',1e-12)
    p.setdefault('heated',True)
    if not isinstance(p['heated'],bool):_error('aperture.heated','Choose whether to solve lattice heating.')
    for key in ('currents_A','voltage_bracket_V'):
        if not isinstance(p.get(key),list) or not p[key]:_error('aperture.'+key,'Supply '+key.replace('_',' ')+'.')
        p[key]=[_number(v,'aperture.'+key,1e-30) for v in p[key]]
    if len(p['voltage_bracket_V'])!=2 or p['voltage_bracket_V'][1]<=p['voltage_bracket_V'][0]:_error('aperture.voltage_bracket_V','Supply increasing lower and upper voltage bounds.')
    anchors=p.get('load_anchors')
    if not isinstance(anchors,list) or len(anchors)<2:_error('aperture.load_anchors','Supply at least two source-bound current-density anchors.')
    for row in anchors:
        if not isinstance(row,dict):_error('aperture.load_anchors','Each load anchor needs voltage_V and current_density_A_cm2.')
        row['voltage_V']=_number(row.get('voltage_V'),'aperture.load_anchors')
        row['current_density_A_cm2']=_number(row.get('current_density_A_cm2'),'aperture.load_anchors',1e-30)
        if row.get('accepted_solver_checks') is not True:_error('aperture.load_anchors','Every anchor must retain explicit accepted solver checks from its source.')
    if any(b['voltage_V']<=a['voltage_V'] or b['current_density_A_cm2']<=a['current_density_A_cm2'] for a,b in zip(anchors,anchors[1:])):
        _error('aperture.load_anchors','Anchors must increase in both voltage and positive current density.')
    if not isinstance(p.get('load_source'),str) or not p['load_source'].strip():_error('aperture.load_source','Identify the load calibration source.')
    if cfg is not None and p.get('load_domain')!=calibration_domain(cfg):
        _error('aperture.load_domain','The load calibration is missing or belongs to a different stack/pattern. Import matching calibration inputs.')
    contacts=p.get('contacts')
    if not isinstance(contacts,list) or not contacts:_error('aperture.contacts','Add an editable contact rectangle or ring.')
    for row in contacts:
        if not isinstance(row,dict) or row.get('shape') not in ('rectangle','ring'):_error('aperture.contacts','Contacts support rectangle or rectangular ring.')
        for key in ('cx_um','cy_um'):row[key]=_number(row.get(key,0),'aperture.contacts')
        for key in ('width_um','height_um'):row[key]=_number(row.get(key),'aperture.contacts',1e-12)
        if row['shape']=='ring':
            for inner,outer in [('inner_width_um','width_um'),('inner_height_um','height_um')]:
                row[inner]=_number(row.get(inner),'aperture.contacts',1e-12)
                if row[inner]>=row[outer]:_error('aperture.contacts','Ring inner dimensions must be smaller than outer dimensions.')
    weights=np.asarray(p.get('mode_weight',[]),dtype=float)
    if weights.size and (weights.shape!=(p['grid_n'],p['grid_n']) or not np.isfinite(weights).all() or np.any(weights<0) or weights.sum()<=0):
        _error('aperture.mode_weight','Use a finite nonnegative optical weight on the same grid, or an empty array for an explicit uniform mode.')
    p['mode_weight']=weights.tolist()
    return p


def load_value(voltage,temperature,p):
    av=np.array([r['voltage_V'] for r in p['load_anchors']]);aj=np.array([r['current_density_A_cm2']*1e4 for r in p['load_anchors']])
    effective=p['load_reference_V']+(voltage-p['load_reference_V'])*p['reference_temperature_K']/temperature
    logs=np.log(aj);index=np.clip(np.searchsorted(av,effective,side='right')-1,0,len(av)-2)
    slopes=np.diff(logs)/np.diff(av);logj=logs[index]+slopes[index]*(effective-av[index])
    # Guard root-bracketing trials; clipping is independently reported below.
    clipped=np.clip(logj,-230,140);j=np.exp(clipped)
    return j,j*slopes[index]*p['reference_temperature_K']/temperature*((logj>-230)&(logj<140)),effective


class ApertureDevice:
    def __init__(self,cfg,cancelled=lambda:False):
        from pcsel_research import _error
        self.p=cfg['aperture'];p=self.p;self.cancelled=cancelled;n=p['grid_n'];self.n=n
        width,height=np.array(cfg['aperture_um'])*1e-6;self.dx=width/n;self.dy=height/n;self.area=self.dx*self.dy;self.acm=self.area*1e4
        self.x=(np.arange(n)+.5)*width*1e6/n-width*5e5;self.y=(np.arange(n)+.5)*height*1e6/n-height*5e5
        xx,yy=np.meshgrid(self.x,self.y);mask=np.zeros((n,n),bool)
        for row in p['contacts']:
            cx,cy=abs(xx-row['cx_um']),abs(yy-row['cy_um'])
            region=(cx<=row['width_um']/2)&(cy<=row['height_um']/2)
            if row['shape']=='ring':region&=(cx>=row['inner_width_um']/2)|(cy>=row['inner_height_um']/2)
            mask|=region
        self.contact=mask.ravel();self.free=~self.contact
        if not self.contact.any() or not self.free.any():_error('aperture.contacts','Resolve both contact and uncontacted cells on the lateral mesh.')
        one=diags([-np.ones(n-1),np.r_[1,np.full(n-2,2),1],-np.ones(n-1)],[-1,0,1],format='csr')
        self.L=(kron(eye(n),one)*self.dy/self.dx+kron(one,eye(n))*self.dx/self.dy).tocsr();self.Le=self.L.copy();self.links=[]
        ids=np.arange(n*n).reshape(n,n)
        for axis,metric in [(0,self.dx/self.dy),(1,self.dy/self.dx)]:
            i=(ids[:-1,:] if axis==0 else ids[:,:-1]).ravel();k=(ids[1:,:] if axis==0 else ids[:,1:]).ravel()
            boundary=self.contact[i]^self.contact[k];weight=metric*np.where(boundary,2.,1.)
            self.links.append((i,k,weight,boundary))
            a,b=i[boundary],k[boundary];v=np.full(len(a),metric)
            self.Le+=coo_matrix((np.r_[v,-v,-v,v],(np.r_[a,a,b,b],np.r_[a,b,a,b])),shape=self.L.shape).tocsr()
        self.Lf=self.Le[self.free][:,self.free];self.Lc=np.asarray(self.Le[self.free][:,self.contact].sum(axis=1)).ravel()
        self.weight=np.asarray(p['mode_weight']).ravel() if p['mode_weight'] else np.ones(n*n)
        self.weight=self.weight/self.weight.sum();self.vg=2.99792458e10/p['group_index'];self.eph=HC/(p['wavelength_nm']*1e-9)
        self.alpha=p['alpha_rad_cm1']+p['alpha_edge_cm1']+p['alpha_internal_cm1']
        self.etaout=p['port_fraction']*p['port_transmission']*p['alpha_rad_cm1']/self.alpha
        self.etaescape=(p['alpha_rad_cm1']+p['alpha_edge_cm1'])/self.alpha

    def check_cancel(self):
        if self.cancelled():raise InterruptedError('Aperture study cancelled')

    def spreading(self,current,T):
        p=self.p;G=1/(p['sheet_ohm_square']*(T.mean()/p['reference_temperature_K'])**p['sheet_temperature_exponent'])
        def at(vc):
            self.check_cancel();v=np.full(self.n**2,vc);v[self.free]=vc-.1
            for _ in range(100):
                j,dj,_=load_value(v,T,p);residual=G*(self.Lf@v[self.free]+self.Lc*vc)+j[self.free]*self.area
                delta=spsolve(G*self.Lf+diags(dj[self.free]*self.area),-residual);v[self.free]+=np.clip(delta,-.1,.1)
                if np.max(abs(delta))<1e-10:break
            else:raise ValueError('Reduced sheet Newton iteration did not converge.')
            j,_,_=load_value(v,T,p)
            return float(j.sum()*self.area-current),v,j
        vc=brentq(lambda voltage:at(voltage)[0],*p['voltage_bracket_V'],xtol=2e-10)
        _,v,j=at(vc);heat=np.zeros(self.n**2)
        for i,k,weight,boundary in self.links:
            power=G*weight*(v[i]-v[k])**2;fraction=np.where(boundary,self.free[i].astype(float),.5)
            np.add.at(heat,i,fraction*power);np.add.at(heat,k,(1-fraction)*power)
        residual=(G*(self.Le@v)+j*self.area)[self.free]
        return v,j,vc,heat,float(np.max(abs(residual))/current)

    def carriers(self,j,T,S):
        p=self.p;eta=p['barrier_lifetime_ps']/(p['barrier_lifetime_ps']+p['capture_ps'])
        te=p['escape_ps']*1e-12*np.exp(p['escape_activation_eV']/KB*(1/T-1/p['reference_temperature_K']))
        esc=(1-eta)/te;ntr=p['Ntr_cm3']*np.exp((T-p['reference_temperature_K'])/p['gain_temperature_K'])
        g0=p['g0_cm1']*p['reference_temperature_K']/T;source=eta*j/1e4/Q
        coef=self.vg*p['Gamma_QW']*S*self.weight/self.acm;d=p['well_total_nm']*1e-7
        lo=np.full(len(T),1e8);hi=np.full(len(T),1e22)
        for _ in range(75):
            N=np.sqrt(lo*hi);gain=g0*np.log(N/ntr)
            residual=d*((p['A_s1']+esc)*N+p['B_cm3_s']*N*N+p['C_cm6_s']*N**3)+coef*gain-source
            hi=np.where(residual>0,N,hi);lo=np.where(residual<=0,N,lo)
        N=np.sqrt(lo*hi);gain=g0*np.log(N/ntr);stim=coef*gain
        residual=d*((p['A_s1']+esc)*N+p['B_cm3_s']*N*N+p['C_cm6_s']*N**3)+stim-source
        barrier=p['capture_ps']*1e-12*(d*N/te+d*(p['A_s1']*N+p['B_cm3_s']*N*N+p['C_cm6_s']*N**3)+stim)
        return N,gain,stim,barrier,float(np.max(abs(residual))/max(source.max(),1))

    def photons(self,j,T):
        def residual(S):return self.p['Gamma_QW']*np.dot(self.weight,self.carriers(j,T,S)[1])-self.alpha
        margin=residual(0);S=0.
        if margin>0:
            upper=max(j.sum()*self.area/Q/(self.vg*self.alpha)*2,1.)
            for _ in range(60):
                if residual(upper)<=0:break
                upper*=4
            else:raise ValueError('The photon-number root could not be bracketed.')
            S=brentq(residual,0,upper,xtol=1e-4,rtol=1e-10)
        N,gain,stim,barrier,error=self.carriers(j,T,S)
        return S,N,gain,stim,barrier,S*self.vg*self.alpha*self.eph*self.etaout,margin,error

    def run(self,current):
        p=self.p;T=np.full(self.n**2,p['sink_K']);old_power=0.
        for iteration in range(p['maximum_iterations']):
            self.check_cancel();v,j,vc,sheet,er=self.spreading(current,T)
            S,N,gain,stim,barrier,power,margin,cr=self.photons(j,T)
            heat=v*j*self.area+sheet-self.eph*stim*self.acm*self.etaescape
            thick=p['substrate_um']*1e-6;k=p['substrate_k_W_mK']*(p['reference_temperature_K']/T.mean())**p['thermal_k_exponent']
            gb=1/(thick/k+p['interface_R_m2K_W'])
            target=p['sink_K']+spsolve(k*thick*self.L+diags(np.full(len(T),gb*self.area)),heat)
            target+=heat/self.area*p['epitaxial_R_m2K_W']
            if not p['heated']:target[:]=p['sink_K']
            error=float(np.max(abs(target-T)))
            if error<p['temperature_tolerance_K'] and abs(power-old_power)<1e-6:break
            T=.6*T+.4*target;old_power=power
            if T.max()>p['max_temperature_K']:raise ValueError('Temperature exceeded the explicit model validity limit.')
        else:raise ValueError('Reduced electrothermal fixed point did not converge.')
        total_input=vc*current;escaped=S*self.vg*self.alpha*self.eph*self.etaescape
        electrical_error=abs(np.sum(v*j*self.area+sheet)-total_input)/total_input
        energy_error=abs(heat.sum()+escaped-total_input)/total_input
        photon_error=abs(p['Gamma_QW']*np.dot(self.weight,gain)-self.alpha)/self.alpha if S else 0.
        _,_,effective=load_value(v,T,p);low,high=p['load_anchors'][0]['voltage_V'],p['load_anchors'][-1]['voltage_V'];outside=(effective<low)|(effective>high)
        row=dict(current_A=current,voltage_V=vc,beam_W=float(power),temperature_max_K=float(T.max()),
            temperature_mean_K=float(T.mean()),J_max_A_cm2=float(j.max()/1e4),J_min_A_cm2=float(j.min()/1e4),
            photon_number=float(S),small_signal_gain_margin_cm1=float(margin),iterations=iteration+1,
            thermal_fixed_point_error_K=error,sheet_residual_relative=er,carrier_residual_relative=cr,
            electrical_energy_error=float(electrical_error),total_energy_error=float(energy_error),
            photon_balance_relative=float(photon_error),area_fraction_outside_vertical_fit=float(outside.mean()),
            current_fraction_outside_vertical_fit=float(j[outside].sum()/j.sum()))
        row['accepted_solver_checks']=bool(max(er,cr,electrical_error,energy_error,photon_error)<1e-4 and error<p['temperature_tolerance_K'])
        fields=dict(x_um=self.x,y_um=self.y,current_A_cm2=j.reshape(self.n,self.n)/1e4,temperature_K=T.reshape(self.n,self.n),
            sheet_voltage_V=v.reshape(self.n,self.n),well_density_cm3=N.reshape(self.n,self.n),gain_cm1=gain.reshape(self.n,self.n),
            barrier_areal_cm2=barrier.reshape(self.n,self.n),mode_weight=self.weight.reshape(self.n,self.n),heat_W=heat.reshape(self.n,self.n))
        return row,fields


def execute_aperture(cfg,directory,emit,cancelled):
    from pcsel_research import _csv
    directory=Path(directory);device=ApertureDevice(cfg,cancelled);rows=[];failures=[];artifacts=[]
    for index,current in enumerate(cfg['aperture']['currents_A']):
        device.check_cancel()
        try:
            row,fields=device.run(current);rows.append(row);name=f'aperture_fields_{index:04d}.npz'
            axes=[dict(name='y',coordinate='y_um',unit='µm'),dict(name='x',coordinate='x_um',unit='µm')]
            units=dict(current_A_cm2='A/cm²',temperature_K='K',sheet_voltage_V='V',well_density_cm3='cm^-3',
                gain_cm1='cm^-1',barrier_areal_cm2='cm^-2',mode_weight='normalized fraction',heat_W='W per cell')
            metadata={key:dict(axes=axes,unit=unit) for key,unit in units.items()}
            np.savez_compressed(directory/name,**fields,array_axes=json.dumps(metadata));artifacts.append(name)
        except (ValueError,RuntimeError) as exc:failures.append(dict(current_A=current,message=str(exc)))
        _csv(directory/'aperture_sweep.csv',rows)
        (directory/'aperture_progress.json').write_text(json.dumps(dict(rows=rows,failures=failures),indent=2,allow_nan=False),encoding='utf-8')
        emit(dict(kind='log',message=f'Aperture point {index+1}/{len(cfg["aperture"]["currents_A"])}'))
    status='partial' if failures else 'unconverged' if any(not row['accepted_solver_checks'] for row in rows) else 'complete'
    return dict(status=status,rows=rows,failures=failures,artifacts=artifacts+['aperture_sweep.csv','aperture_progress.json'],
        approximation='Reduced sheet and calibrated vertical load + local QW rates + substrate sheet heat conduction',
        load_source=cfg['aperture']['load_source'],temperature_load_law_calibrated=False,
        load_domain=cfg['aperture']['load_domain'],convergence_established=False)
