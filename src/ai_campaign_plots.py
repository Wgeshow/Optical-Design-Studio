"""Saved-data plots for AI Search. No solver work occurs while inspecting results."""
from pathlib import Path
import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Circle
from data_library import read_json
from field_storage import load_field_frame


def amplitude_map(frame,component):
    values=np.column_stack([np.abs(frame[c+'_real'].to_numpy()+1j*frame[c+'_imag'].to_numpy()) for c in ('Ex','Ey','Ez')])
    return np.linalg.norm(values,axis=1) if component=='total' else values[:,('Ex','Ey','Ez').index(component)]


def field_figure(record,component='total',layer=None,threshold=0.,moving=False,step=.1):
    path=Path(record['field_directory']);frame=load_field_frame(path);model=read_json(path/'field_model.json')['model']
    names=[l['name'] for l in model['layers'][1:-1] if l['thickness']>0];layer=layer if layer in names else names[0]
    xy=frame[(frame.plane=='volume_samples')&(frame.layer==layer)].copy();depths=sorted(xy.z_um.unique());mid=depths[len(depths)//2];xy=xy[np.isclose(xy.z_um,mid)].copy()
    xy['amplitude']=amplitude_map(xy,component);xz=frame[frame.plane=='xz'].copy();xz['amplitude']=amplitude_map(xz,component)
    fig=Figure(figsize=(10,5),layout='constrained');axes=fig.subplots(1,2)
    maxvalue=max(float(xy.amplitude.max()),float(xz.amplitude.max()) if len(xz) else 0.)
    if maxvalue<1e-8:
        for ax in axes:ax.text(.5,.5,'Component below numerical floor',ha='center',va='center',transform=ax.transAxes)
        return fig
    vmin=threshold if moving else 0.;vmax=max(vmin+5*step,1e-8) if moving else maxvalue
    xs=sorted(xy.x_um.unique());ys=sorted(xy.y_um.unique());a=xy.pivot(index='y_um',columns='x_um',values='amplitude').to_numpy()
    if moving:a=np.ma.masked_less(a,threshold)
    image=axes[0].imshow(a,origin='lower',extent=[-model['ax']*500,model['ax']*500,-model['ay']*500,model['ay']*500],cmap='viridis',vmin=vmin,vmax=vmax,interpolation='nearest',aspect='equal')
    if float(np.min(a))<threshold<float(np.max(a)):
        axes[0].contour(np.array(xs)*1000,np.array(ys)*1000,a,levels=[threshold],colors='orange',linewidths=.8)
    for p in model['patterns']:
        if p['layer']==layer and p['shape']=='circle':axes[0].add_patch(Circle((p['cx']*1000,p['cy']*1000),p['sx']*1000,fill=False,linestyle='--',edgecolor='white',linewidth=.8))
    axes[0].set(xlabel='x (nm)',ylabel='y (nm)',title=f'XY · {layer} · z={mid*1000:.1f} nm')
    zstart=0.
    for l in model['layers'][1:-1]:
        t=l['thickness'];section=xz[xz.layer==l['name']]
        if len(section):
            a=section.pivot(index='z_um',columns='x_um',values='amplitude').to_numpy()
            if moving:a=np.ma.masked_less(a,threshold)
            xedges=np.linspace(-model['ax']/2,model['ax']/2,a.shape[1]+1)*1000;zedges=np.linspace(zstart,zstart+t,a.shape[0]+1)*1000
            axes[1].pcolormesh(xedges,zedges,a,cmap='viridis',vmin=vmin,vmax=vmax,shading='flat')
            p=next((p for p in model['patterns'] if p['layer']==l['name']),None)
            if p:
                for sign in [-1,1]:axes[1].plot([1000*(p['cx']+sign*p['sx'])]*2,[zstart*1000,(zstart+t)*1000],color='white',ls='--',lw=.8)
            axes[1].axhline((zstart+t)*1000,color='gray',lw=.5)
        zstart+=t
    axes[1].set(xlabel='x (nm)',ylabel='Depth z (nm)',title='XZ · complete finite stack');axes[1].invert_yaxis()
    fig.colorbar(image,ax=axes,label='Amplitude / incident amplitude',shrink=.8)
    fig.suptitle('|E|' if component=='total' else '|'+component+'|')
    return fig


def line_figure(record):
    points=record['fields']['depth_profile'];fig=Figure(figsize=(9,4),layout='constrained');ax=fig.subplots();z=np.array([p['z_um']*1000 for p in points])
    for i,c in enumerate(('Ex','Ey','Ez')):ax.plot(z,[p['abs_E'][i] for p in points],label='|'+c+'|')
    ax.plot(z,[p['total_abs'] for p in points],label='|E|',ls='--');ax.set(xlabel='Depth z (nm)',ylabel='Amplitude / incident amplitude',title='Depth line outside the air-hole wall · all finite layers');ax.legend()
    for layer in dict.fromkeys(p['layer'] for p in points):
        pos=[p['z_um']*1000 for p in points if p['layer']==layer];ax.axvline(max(pos),color='gray',lw=.5)
    return fig


def rta_figure(record):
    fig=Figure(figsize=(9,4),layout='constrained');ax=fig.subplots();rows=record['rta']
    for key in ('R','T','A'):ax.plot([r['wavelength_nm'] for r in rows],[r[key] for r in rows],label=key)
    from matplotlib.ticker import PercentFormatter
    ax.set(xlabel='Wavelength (nm)',ylabel='Incident power (%)',ylim=(0,1),title='Visible RTA sweep · narrow peaks can require a finer verification scan')
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1));ax.legend();return fig


def validation_figure(report):
    fig=Figure(figsize=(9,4),layout='constrained');axes=fig.subplots(1,2)
    for ax,index,title in zip(axes,(1,2),('Volume contrast','XZ contrast')):
        if len(report.get('measurements',[]))<=index:
            ax.text(.5,.5,'No independent test results yet',ha='center',va='center',transform=ax.transAxes);ax.set_axis_off();continue
        m=report['measurements'][index];a=np.array(m['measured']);p=np.array(m['predictions']);s=np.array(m['std']);ax.errorbar(a,p,yerr=1.96*s,fmt='o',capsize=3)
        lo=min(a.min(),(p-1.96*s).min());hi=max(a.max(),(p+1.96*s).max());ax.plot([lo,hi],[lo,hi],ls='--',color='gray');ax.set(xlabel='S4 measured log contrast',ylabel='Predicted log contrast',title=title+' · 95% intervals')
    return fig
