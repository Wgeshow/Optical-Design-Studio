"""Generalized P1 tetrahedral Fermi-Dirac transport weak form.

The residual and Jacobian follow the independently audited recovered PCSEL
conformal study. Geometry, material properties, temperature and terminals are
now supplied explicitly. No experiment files or saved solution are read.
"""
import numpy as np
from scipy.sparse import coo_matrix, diags, bmat
from scipy.sparse.linalg import splu
from electrical_fermi_transport import fermi_half_transport, neutral_fermi_potential

Q = 1.602176634e-19
EPS = 8.8541878128e-14  # F/cm


class FiniteElementTransport:
    def __init__(self, cfg, mesh, emit=lambda event: None, cancelled=lambda: False):
        self.cfg, self.emit, self.cancelled = cfg, emit, cancelled
        self.xyz = mesh['points_um']*1e-4
        self.geometry_t = mesh['tetrahedra']
        self.mesh = mesh
        self.vt = 8.617333262145e-5*cfg['temperature_K']
        props = []
        for layer_id, is_void in zip(mesh['layer_index'], mesh['void']):
            layer = cfg['layers'][int(layer_id)]; material = cfg['materials'][layer['material']]
            active = not is_void and material['kind'] == 'semiconductor'
            props.append([float(active), cfg['void_epsilon_r'] if is_void else material['epsilon_r'],
                material['Nc_cm3'], material['Nv_cm3'], material['affinity_eV'], material['bandgap_eV'],
                material['electron_mobility_cm2_Vs'], material['hole_mobility_cm2_Vs'],
                layer['donors_cm3']-layer['acceptors_cm3'] if active else 0.,
                material['B_cm3_s'], material['C_cm6_s'], material['tau_s']])
        props = np.asarray(props)
        self.mobile, self.eps = props[:,0], props[:,1]
        self.nc,self.nv,self.chi,self.eg,self.mun,self.mup,self.dop,self.B,self.C,self.tau = props[:,2:].T
        self.inverse_tau = np.divide(1.,self.tau,out=np.zeros_like(self.tau),where=self.tau>0)
        coordinates = mesh['points_um'].copy()
        tolerance = min(cfg['period_um'])*1e-8
        for axis, length in enumerate(cfg['period_um']):
            coordinates[np.isclose(coordinates[:,axis], length/2, rtol=0, atol=tolerance),axis] = -length/2
        _, representatives, self.dof_map = np.unique(np.round(coordinates/tolerance).astype(np.int64),
            axis=0, return_index=True, return_inverse=True)
        self.coord_dof = self.xyz[representatives]; self.n = len(representatives)
        self.t = self.dof_map[self.geometry_t]
        p = self.xyz[self.geometry_t]
        matrix = np.stack([p[:,1]-p[:,0],p[:,2]-p[:,0],p[:,3]-p[:,0]],axis=2)
        self.vol = abs(np.linalg.det(matrix))/6
        self.gradients = np.zeros((len(self.t),4,3))
        self.gradients[:,1:] = np.linalg.inv(matrix)
        self.gradients[:,0] = -self.gradients[:,1:].sum(axis=1)
        self.K0 = self.vol[:,None,None]*np.einsum('nik,njk->nij',self.gradients,self.gradients)
        self.rr = np.repeat(self.t,4,axis=1).ravel();self.cc = np.tile(self.t,(1,4)).ravel()
        self.Kp = self.assemble(self.K0*(self.eps*EPS)[:,None,None])
        self.w = self.vol[:,None]/4*self.mobile[:,None]
        self.active = self.acc(np.broadcast_to(self.w,self.t.shape))>0
        z = self.coord_dof[:,2]
        self.top = np.isclose(z,0,rtol=0,atol=1e-15)&self.active
        self.bottom = np.isclose(z,z.max(),rtol=0,atol=1e-15)&self.active
        if not self.top.any() or not self.bottom.any():
            raise ValueError('Both full-face ohmic terminals must touch a semiconductor.')
        self.pcontact = self.top if cfg['swept_contact'] == 'top' else self.bottom
        self.ncontact = self.bottom if cfg['swept_contact'] == 'top' else self.top
        self.contacts = self.top|self.bottom
        neutral = neutral_fermi_potential(self.dop,self.nc,self.nv,self.chi,self.eg,self.vt)
        weight = self.acc(np.broadcast_to(self.w,self.t.shape))
        self.neutral = np.divide(self.acc(self.w*neutral[:,None]),weight,
            out=np.full(self.n,-4.7),where=weight>0)
        self.fixed = np.r_[self.contacts,self.contacts|~self.active,self.contacts|~self.active]
        self.free = ~self.fixed
        self.u = np.r_[self.neutral,np.zeros(2*self.n)]

    def arrays(self):
        phi, fn, fp = self.u.reshape(3,self.n)
        _,_,(n,p,recombination) = self.evaluate(self.u,False)
        grad_n = np.einsum('nki,nk->ni', self.gradients, fn[self.t]-fn[self.t][:,:1])
        grad_p = np.einsum('nki,nk->ni', self.gradients, fp[self.t]-fp[self.t][:,:1])
        grad_phi = np.einsum('nki,nk->ni',self.gradients,phi[self.t]-phi[self.t][:,:1])
        return dict(points_um=self.mesh['points_um'],tetrahedra=self.geometry_t,dof_map=self.dof_map,
            layer_index=self.mesh['layer_index'],void=self.mesh['void'],potential_V=phi[self.dof_map],
            electron_quasi_fermi_eV=fn[self.dof_map],hole_quasi_fermi_eV=fp[self.dof_map],
            electrons_element_cm3=n*self.mobile[:,None],holes_element_cm3=p*self.mobile[:,None],
            recombination_element_cm3_s=recombination*self.mobile[:,None],
            electron_current_element_A_cm2=Q*(self.mun*self.mobile*n.mean(axis=1))[:,None]*grad_n,
            hole_current_element_A_cm2=Q*(self.mup*self.mobile*p.mean(axis=1))[:,None]*grad_p,
            electric_field_element_V_cm=-grad_phi,
            tetrahedron_volume_cm3=self.vol)


    def acc(self,v):return np.bincount(self.t.ravel(),weights=np.broadcast_to(v,self.t.shape).ravel(),minlength=self.n)

    def assemble(self,v):return coo_matrix((v.ravel(),(self.rr,self.cc)),shape=(self.n,self.n)).tocsr()

    def boundary(self,u,bias):
     u[:self.n][self.contacts]=self.neutral[self.contacts]+bias*self.pcontact[self.contacts]
     for block in [1,2]:u[block*self.n:(block+1)*self.n][self.contacts]=-bias*self.pcontact[self.contacts]

    def evaluate(self,u,jac=True):
     ph,fn,fp=u.reshape(3,self.n);pt,nt,ht=ph[self.t],fn[self.t],fp[self.t]
     n,dn=fermi_half_transport((pt+self.chi[:,None]+nt)/self.vt);p,dp=fermi_half_transport((-pt-self.chi[:,None]-self.eg[:,None]-ht)/self.vt)
     n*=self.nc[:,None];dn*=self.nc[:,None]/self.vt;p*=self.nv[:,None];dp*=self.nv[:,None]/self.vt
     # Derivatives: dn/dphi=dn/dfn=dn; dp/dphi=dp/dfp=-dp.
     fac=-np.expm1(np.clip(-(nt-ht)/self.vt,-600,600));ef=1-fac
     H=self.B[:,None]+self.C[:,None]*(n+p)+self.inverse_tau[:,None]/(n+p+1)
     hp=self.C[:,None]-self.inverse_tau[:,None]/(n+p+1)**2
     R=n*p*fac*H
     rphi=fac*((dn*p-n*dp)*H+n*p*hp*(dn-dp))
     rfn=dn*p*fac*(H+n*hp)+n*p*H*ef/self.vt
     rfp=-n*dp*fac*(H+p*hp)-n*p*H*ef/self.vt
     cn=self.mun*self.mobile*n.mean(axis=1);cp=self.mup*self.mobile*p.mean(axis=1)
     kn=self.assemble(self.K0*cn[:,None,None]);kp=self.assemble(self.K0*cp[:,None,None])
     # Evaluate gradients using local differences so constant quasi-Fermi values
     # give exactly zero flux rather than cancellation of large matrix terms.
     vn=np.einsum('nij,nj->ni',self.K0,nt-nt[:,:1]);vp=np.einsum('nij,nj->ni',self.K0,ht-ht[:,:1])
     vphi=np.einsum('nij,nj->ni',self.K0,pt-pt[:,:1])
     res=np.r_[self.acc(vphi*(self.eps*EPS)[:,None])-Q*self.acc(self.w*(p-n+self.dop[:,None])),self.acc(cn[:,None]*vn+self.w*R),self.acc(cp[:,None]*vp-self.w*R)]
     if not jac:return res,None,(n,p,R)
     dncoef=self.mun[:,None]*self.mobile[:,None]*dn/4;dpcoef=-self.mup[:,None]*self.mobile[:,None]*dp/4
     dnmat=self.assemble(vn[:,:,None]*dncoef[:,None,:]);dpmat=self.assemble(vp[:,:,None]*dpcoef[:,None,:])
     rp=diags(self.acc(self.w*rphi));rn=diags(self.acc(self.w*rfn));rh=diags(self.acc(self.w*rfp))
     j00=self.Kp+diags(Q*self.acc(self.w*(dp+dn)));j01=diags(Q*self.acc(self.w*dn));j02=diags(Q*self.acc(self.w*dp))
     J=bmat([[j00,j01,j02],[dnmat+rp,kn+dnmat+rn,rh],[dpmat-rp,-rn,kp+dpmat-rh]],format='csr')
     return res,J,(n,p,R)

    def solve(self,bias,eq=False):
     u=self.u.copy();self.boundary(u,bias);free=(~self.contacts) if eq else self.free
     for it in range(self.cfg['maximum_iterations']):
  
      if self.cancelled():raise InterruptedError('Conformal transport cancelled')
      r,J,_=self.evaluate(u)
      if eq:r=r[:self.n];J=J[:self.n,:self.n]
      jf=J[free][:,free];rf=r[free];scale=np.asarray(abs(jf).sum(axis=1)).ravel();scale=np.maximum(scale,1e-100)
      err=float(np.max(abs(rf)/scale))
      self.emit(dict(kind='log',message=f'Conformal Newton bias {bias:g} V, iteration {it}, residual {err:.3g} V'))
      if err<self.cfg['tolerance_V']:
       if eq:break
       re,rh=r[self.n:2*self.n],r[2*self.n:];ip=-Q*(re[self.pcontact]+rh[self.pcontact]).sum();inn=-Q*(re[self.ncontact]+rh[self.ncontact]).sum()
       if abs(ip+inn)<max(1e-18,1e-3*abs(ip)):break
      A=diags(1/scale)@jf;rhs=-rf/scale
      ids=np.flatnonzero(free);perm=np.argsort((ids%self.n)*3+ids//self.n)
      lu=splu(A[perm][:,perm].tocsc(),permc_spec='MMD_AT_PLUS_A',diag_pivot_thresh=.01,options={'Equil':True});du=np.empty(len(rhs));du[perm]=lu.solve(rhs[perm])
      linear_error=np.max(abs(A@du-rhs))/max(np.max(abs(rhs)),1e-300)
      if linear_error>1e-5:raise RuntimeError(f'SuperLU linear residual {linear_error}')
      if not np.isfinite(du).all():raise RuntimeError('Nonfinite Newton step')
      # Componentwise trust bound prevents an ill-conditioned minority node from
      # limiting every well-conditioned majority-carrier unknown to a tiny step.
      rawdu=du.copy();du=np.clip(du,-.12,.12);damping=1.
      # Residual line search at a frozen row scaling is independently meaningful.
      for line in range(18):
       trial=u.copy();sl=trial[:self.n] if eq else trial;sl[free]+=damping*du
       tr=self.evaluate(trial,False)[0];tr=tr[:self.n] if eq else tr
       newerr=float(np.max(abs(tr[free])/scale))
       if newerr<err:break
       damping*=.5
      else:
       # Clipping can destroy the Newton descent direction. Fall back to the
       # exact direction with a conventional residual backtracking line search.
       du=rawdu;damping=1.
       for line in range(24):
        trial=u.copy();sl=trial[:self.n] if eq else trial;sl[free]+=damping*du
        tr=self.evaluate(trial,False)[0];tr=tr[:self.n] if eq else tr
        if np.max(abs(tr[free])/scale)<err:break
        damping*=.5
       else:raise RuntimeError('Both clipped and exact Newton line searches failed')
      u=trial
      if hasattr(self,'iteration_file'):np.savez_compressed(self.iteration_file,u=u,bias_V=bias,iteration=it,error_V=err)
     else:raise RuntimeError('Newton iterations exhausted')
     self.u=u;r,J,(n,p,R)=self.evaluate(u);re,rh=r[self.n:2*self.n],r[2*self.n:]
     phi,fn,fp=u.reshape(3,self.n)
     electron_eta=(phi[self.t]+self.chi[:,None]+fn[self.t])/self.vt
     hole_eta=(-phi[self.t]-self.chi[:,None]-self.eg[:,None]-fp[self.t])/self.vt
     active=self.mobile>0
     if any(not np.isfinite(eta[active]).all() or np.any(eta[active]<-600) or np.any(eta[active]>200) for eta in (electron_eta,hole_eta)):
      raise ValueError('The accepted state leaves the validated parabolic-band Fermi-integral range [-600,200].')
     current={label:float(-Q*(re[c]+rh[c]).sum()) for label,c in [('top',self.top),('bottom',self.bottom)]}
     fn,fp=u[self.n:2*self.n],u[2*self.n:];low=min(-bias,0.);high=max(-bias,0.)
     overshoot=max(float(max(fn[self.active].max(),fp[self.active].max())-high),float(low-min(fn[self.active].min(),fp[self.active].min())),0)
     return dict(voltage_V=bias,current_A=current,current_density_A_cm2=current[self.cfg['swept_contact']]/(self.cfg['period_um'][0]*self.cfg['period_um'][1]*1e-8),current_balance_relative=abs(sum(current.values()))/max(abs(current[self.cfg['swept_contact']]),1e-30),current_balance_absolute_A=abs(sum(current.values())),newton_iterations=it,scaled_residual_V=err,quasi_fermi_contact_range_overshoot_V=overshoot,minimum_density_cm3=float(min(n.min(),p.min())),boundary='Periodic x/y unknown identification verified against matching opposite face coordinates; ideal ohmic top/bottom',method='P1 tetrahedral finite element weak form; lumped charge/recombination; element-average conductivity; exact residual Jacobian')
