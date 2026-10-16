// Exact spatial mirror decomposition of the retained Fourier space.
// Geometry eligibility is supplied by S4; numerical tests below only detect
// inconsistent operators and excessive roundoff, never infer geometric symmetry.
#ifndef S4_MIRROR_SYMMETRY_H
#define S4_MIRROR_SYMMETRY_H
#include <algorithm>
#include <cmath>
#include <complex>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <vector>

namespace S4Mirror {
typedef std::complex<double> Z;
inline bool Enabled(){ const char *v=std::getenv("S4_MIRROR_SYMMETRY"); return v && v[0]=='1' && v[1]==0; }
inline void Diagnostic(const char *what){
    const char *v=std::getenv("S4_MIRROR_DIAGNOSTICS");
    if(v && v[0]=='1' && v[1]==0) std::fprintf(stderr,"S4 mirror: %s\n",what);
}
inline bool Finite(Z z){ return std::isfinite(z.real()) && std::isfinite(z.imag()); }
struct Column { size_t count, row[4]; double value[4]; Column():count(0){} };

struct Basis {
    size_t n, dim, start[5];
    std::vector<size_t> mx, my;
    std::vector<Column> col;
    Basis():n(0),dim(0){}
    bool Build(size_t orders, const int *g, const double *kx, const double *ky){
        n=orders; dim=2*n; col.clear(); mx.resize(n); my.resize(n);
        if(!n || !g || !kx || !ky) return false;
        bool origin=false;
        for(size_t i=0;i<n;++i){
            if(!std::isfinite(kx[i]) || !std::isfinite(ky[i])) return false;
            size_t x=n,y=n;
            for(size_t j=0;j<n;++j){
                // Cast before negation so even malformed INT_MIN is harmless.
                if((long long)g[2*j]==-(long long)g[2*i] && g[2*j+1]==g[2*i+1]){ if(x!=n) return false; x=j; }
                if(g[2*j]==g[2*i] && (long long)g[2*j+1]==-(long long)g[2*i+1]){ if(y!=n) return false; y=j; }
            }
            if(x==n || y==n || kx[x]!=-kx[i] || ky[x]!=ky[i] || kx[y]!=kx[i] || ky[y]!=-ky[i]) return false;
            if(g[2*i]==0 && g[2*i+1]==0){ if(kx[i]!=0 || ky[i]!=0) return false; origin=true; }
            mx[i]=x; my[i]=y;
        }
        if(!origin) return false;
        for(size_t i=0;i<n;++i) if(mx[mx[i]]!=i || my[my[i]]!=i || mx[my[i]]!=my[mx[i]]) return false;
        // H is an axial vector: Mx=(+Hx,-Hy), My=(-Hx,+Hy).
        // The transformed electric vector (-Ey,Ex) has these same signs.
        for(size_t sector=0;sector<4;++sector){
            start[sector]=col.size();
            const int px=(sector&1)?-1:1, py=(sector&2)?-1:1;
            for(size_t component=0;component<2;++component){
                std::vector<bool> seen(n,false);
                const int sx=component?-1:1, sy=-sx;
                for(size_t i=0;i<n;++i){
                    if(seen[i]) continue;
                    const size_t orbit[4]={i,mx[i],my[i],mx[my[i]]};
                    const int signs[4]={1,px*sx,py*sy,px*py*sx*sy};
                    Column c;
                    for(size_t k=0;k<4;++k){
                        seen[orbit[k]]=true;
                        size_t t=0; for(;t<c.count;++t) if(c.row[t]==orbit[k]+component*n) break;
                        if(t==c.count){ c.row[t]=orbit[k]+component*n; c.value[t]=0; ++c.count; }
                        c.value[t]+=signs[k];
                    }
                    double norm=0; for(size_t k=0;k<c.count;++k) norm+=c.value[k]*c.value[k];
                    if(norm==0) continue;
                    norm=std::sqrt(norm); for(size_t k=0;k<c.count;++k) c.value[k]/=norm;
                    col.push_back(c);
                }
            }
        }
        start[4]=col.size();
        return col.size()==dim;
    }
    bool Commutes(const Z *a, size_t lda) const {
        double scale=0, error=0;
        for(size_t j=0;j<dim;++j) for(size_t i=0;i<dim;++i){
            const Z z=a[i+j*lda]; if(!Finite(z)) return false;
            scale=std::max(scale,std::abs(z));
            const size_t ci=i/n,cj=j/n, gi=i%n,gj=j%n;
            const double sign=(ci==cj)?1.:-1.;
            error=std::max(error,std::abs(z-sign*a[mx[gi]+ci*n+(mx[gj]+cj*n)*lda]));
            error=std::max(error,std::abs(z-sign*a[my[gi]+ci*n+(my[gj]+cj*n)*lda]));
        }
        return error<=128*std::numeric_limits<double>::epsilon()*dim*scale;
    }
    void Project(size_t sector, const Z *a,size_t lda,std::vector<Z>& b) const {
        const size_t first=start[sector], m=start[sector+1]-first;
        b.assign(m*m,Z(0));
        for(size_t j=0;j<m;++j) for(size_t i=0;i<m;++i){
            const Column &x=col[first+i], &y=col[first+j]; Z sum=0;
            for(size_t v=0;v<y.count;++v) for(size_t u=0;u<x.count;++u)
                sum+=x.value[u]*a[x.row[u]+y.row[v]*lda]*y.value[v];
            b[i+j*m]=sum;
        }
    }
    void ProjectVector(size_t sector,const Z *v,Z *w) const {
        const size_t first=start[sector],m=start[sector+1]-first;
        for(size_t i=0;i<m;++i){ const Column &c=col[first+i]; w[i]=0;
            for(size_t k=0;k<c.count;++k) w[i]+=c.value[k]*v[c.row[k]];
        }
    }
    void LiftVector(size_t sector,const Z *v,Z *w) const {
        const size_t first=start[sector],m=start[sector+1]-first;
        for(size_t i=0;i<m;++i){ const Column &c=col[first+i];
            for(size_t k=0;k<c.count;++k) w[c.row[k]]+=c.value[k]*v[i];
        }
    }
    bool ProjectModes(size_t sector,const Z *phi,std::vector<Z>& a) const {
        const size_t first=start[sector],m=start[sector+1]-first;
        a.resize(m*m); std::vector<Z> reconstructed(dim);
        for(size_t j=0;j<m;++j){
            const Z *v=phi+(first+j)*dim;
            ProjectVector(sector,v,&a[j*m]);
            std::fill(reconstructed.begin(),reconstructed.end(),Z(0));
            LiftVector(sector,&a[j*m],reconstructed.data());
            double norm=0,error=0;
            for(size_t i=0;i<dim;++i){ if(!Finite(v[i])) return false; norm=std::max(norm,std::abs(v[i])); error=std::max(error,std::abs(v[i]-reconstructed[i])); }
            if(norm==0 || error>128*std::numeric_limits<double>::epsilon()*dim*norm) return false;
        }
        return true;
    }
};

// Include after the RNP eigensystem and linear solve headers. Failed trials
// leave the original full operator and output arrays intact for dense fallback.
inline bool Eigensystem(const Basis& basis,const Z *op,Z *q,Z *phi){
    if(!basis.Commutes(op,basis.dim)) return false;
    std::vector<Z> values(basis.dim),vectors(basis.dim*basis.dim,Z(0));
    for(size_t s=0;s<4;++s){
        const size_t first=basis.start[s],m=basis.start[s+1]-first;
        if(!m) continue;
        std::vector<Z> a,v(m*m); basis.Project(s,op,basis.dim,a);
        const int info=RNP::Eigensystem(m,a.data(),m,values.data()+first,NULL,1,v.data(),m,NULL,NULL,0);
        if(info) return false;
        for(size_t j=0;j<m;++j){
            if(!Finite(values[first+j])) return false;
            for(size_t i=0;i<m;++i) if(!Finite(v[i+j*m])) return false;
            basis.LiftVector(s,&v[j*m],&vectors[(first+j)*basis.dim]);
        }
    }
    std::copy(values.begin(),values.end(),q); std::copy(vectors.begin(),vectors.end(),phi);
    return true;
}

// Three-layer boundary matching with bounded exp(i*q*d), retaining both
// propagation directions and every sector. q/phi use the sector ordering above.
// Uniform exterior mode coordinates stay in the original Fourier basis.
inline bool ThreeLayer(const Basis& basis,const double *thickness,const Z **q,
        const Z **kp,const Z **phi,Z *ab){
    const size_t dim=basis.dim;
    if(phi[0] || !phi[1] || phi[2] || !kp[0] || !kp[1] || !kp[2]) return false;
    for(size_t l=0;l<3;++l){
        if(!std::isfinite(thickness[l]) || !basis.Commutes(kp[l],dim)) return false;
        double maxq=0; for(size_t j=0;j<dim;++j){ if(!Finite(q[l][j])) return false; maxq=std::max(maxq,std::abs(q[l][j])); }
        // Preserve the dense path's cutoff convention, including unavailability.
        for(size_t j=0;j<dim;++j) if(std::abs(q[l][j])<=std::numeric_limits<double>::epsilon()*maxq) return false;
    }
    std::vector<Z> result(ab,ab+6*dim);
    std::fill(result.begin()+dim,result.begin()+5*dim,Z(0));
    for(size_t s=0;s<4;++s){
        const size_t first=basis.start[s],m=basis.start[s+1]-first,d=2*m;
        if(!m) continue;
        std::vector<Z> a,k,b0,b2,b(m*m),b0a(m*m),b2a(m*m),matrix(d*d),rhs(d),a0(m),bN(m),f(m),top(m),bottom(m);
        if(!basis.ProjectModes(s,phi[1],a)) return false;
        basis.Project(s,kp[0],dim,b0); basis.Project(s,kp[1],dim,k); basis.Project(s,kp[2],dim,b2);
        basis.ProjectVector(s,ab,a0.data()); basis.ProjectVector(s,ab+5*dim,bN.data());
        for(size_t j=0;j<m;++j){
            const Column &c=basis.col[first+j]; const size_t row=c.row[0];
            for(size_t t=1;t<c.count;++t) if(q[0][c.row[t]]!=q[0][row] || q[2][c.row[t]]!=q[2][row]) return false;
            for(size_t i=0;i<m;++i){ b0[i+j*m]/=q[0][row]; b2[i+j*m]/=q[2][row]; }
            a0[j]*=std::exp(Z(0,thickness[0])*q[0][row]);
            bN[j]*=std::exp(Z(0,thickness[2])*q[2][row]);
            f[j]=std::exp(Z(0,thickness[1])*q[1][first+j]);
            if(!Finite(a0[j]) || !Finite(bN[j]) || !Finite(f[j])) return false;
        }
        RNP::TBLAS::MultMM<'N','N'>(m,m,m,1.,k.data(),m,a.data(),m,0.,b.data(),m);
        RNP::TBLAS::MultMM<'N','N'>(m,m,m,1.,b0.data(),m,a.data(),m,0.,b0a.data(),m);
        RNP::TBLAS::MultMM<'N','N'>(m,m,m,1.,b2.data(),m,a.data(),m,0.,b2a.data(),m);
        for(size_t j=0;j<m;++j) for(size_t i=0;i<m;++i){
            const size_t ij=i+j*m; b[ij]/=q[1][first+j];
            matrix[i+j*d]=b[ij]+b0a[ij];
            matrix[i+(j+m)*d]=(b0a[ij]-b[ij])*f[j];
            matrix[i+m+j*d]=(b2a[ij]-b[ij])*f[j];
            matrix[i+m+(j+m)*d]=b[ij]+b2a[ij];
        }
        for(size_t i=0;i<m;++i) for(size_t j=0;j<m;++j){ rhs[i]+=2.*b0[i+j*m]*a0[j]; rhs[i+m]+=2.*b2[i+j*m]*bN[j]; }
        for(size_t i=0;i<matrix.size();++i) if(!Finite(matrix[i])) return false;
        for(size_t i=0;i<d;++i) if(!Finite(rhs[i])) return false;
        int info=0; RNP::LinearSolve<'N'>(d,1,matrix.data(),d,rhs.data(),d,&info,NULL);
        if(info) return false;
        for(size_t i=0;i<d;++i) if(!Finite(rhs[i])) return false;
        for(size_t i=0;i<m;++i){
            result[2*dim+first+i]=rhs[i]; result[3*dim+first+i]=rhs[i+m];
            top[i]=-a0[i]; bottom[i]=-bN[i];
            for(size_t j=0;j<m;++j){
                top[i]+=a[i+j*m]*(rhs[j]+f[j]*rhs[j+m]);
                bottom[i]+=a[i+j*m]*(f[j]*rhs[j]+rhs[j+m]);
            }
        }
        basis.LiftVector(s,top.data(),result.data()+dim);
        basis.LiftVector(s,bottom.data(),result.data()+4*dim);
    }
    for(size_t i=0;i<result.size();++i) if(!Finite(result[i])) return false;
    std::copy(result.begin(),result.end(),ab); return true;
}
} // namespace S4Mirror
#endif
