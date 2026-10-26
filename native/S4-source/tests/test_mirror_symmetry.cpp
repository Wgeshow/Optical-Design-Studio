// Standalone LP64 BLAS/LAPACK checks of the complete mirror basis and fields.
#define F77_FUNC(lower,upper) lower ## _
#include <TBLAS.h>
#include <TBLAS_ext.h>
#include <LinearSolve.h>
#include <LinearSolve_lapack.h>
#include <Eigensystems_lapack.h>
#include "mirror_symmetry.h"
#include <cstring>

using S4Mirror::Z;
static void require(bool ok,const char *what){ if(!ok){ std::fprintf(stderr,"FAIL: %s\n",what); std::exit(1); } }
static double error(const std::vector<Z>& a,const std::vector<Z>& b){ double e=0; for(size_t i=0;i<a.size();++i)e=std::max(e,std::abs(a[i]-b[i])/std::max(1.,std::abs(b[i]))); return e; }
static S4Mirror::Basis basis(int radius2,std::vector<int>& g,std::vector<double>& kx,std::vector<double>& ky){
    g.clear(); kx.clear(); ky.clear();
    for(int x=-6;x<=6;++x)for(int y=-6;y<=6;++y)if(x*x+y*y<=radius2){ g.push_back(x);g.push_back(y);kx.push_back(x*.7);ky.push_back(y*.7); }
    S4Mirror::Basis b;require(b.Build(kx.size(),g.data(),kx.data(),ky.data()),"build closed basis");return b;
}
static std::vector<Z> make_operator(const S4Mirror::Basis& basis,double shift){
    const size_t dim=basis.dim; std::vector<Z> a(dim*dim);
    for(size_t s=0;s<4;++s){const size_t first=basis.start[s],m=basis.start[s+1]-first;
        for(size_t j=0;j<m;++j)for(size_t i=0;i<m;++i){
            const Z z=(i==j?Z(shift+.1*i,.11+.001*j):Z(.012*std::sin(i+2*j+1),.01*std::cos(3*i+j)));
            const S4Mirror::Column &x=basis.col[first+i],&y=basis.col[first+j];
            for(size_t v=0;v<y.count;++v)for(size_t u=0;u<x.count;++u)a[x.row[u]+y.row[v]*dim]+=x.value[u]*z*y.value[v];
        }
    }return a;
}
static std::vector<Z> uniform_kp(const std::vector<double>& kx,const std::vector<double>& ky,Z eps,Z omega){
    const size_t n=kx.size(),dim=2*n;std::vector<Z> a(dim*dim);
    for(size_t g=0;g<n;++g){a[g+g*dim]=omega*omega-ky[g]*ky[g]/eps;a[g+n+(g+n)*dim]=omega*omega-kx[g]*kx[g]/eps;a[g+n+g*dim]=a[g+(g+n)*dim]=kx[g]*ky[g]/eps;}return a;
}
// Independent reference: solve the four continuity equations directly for
// [b_top,a_film,b_film,a_bottom], in original Fourier coordinates.
static std::vector<Z> dense_boundary(size_t dim,const double *h,const Z **q,const Z **kp,const Z **phi,const std::vector<Z>& input){
    const size_t d=4*dim;std::vector<Z>a(d*d),rhs(d),B(dim*dim),B0(dim*dim),B2(dim*dim),f(dim),inc(dim),back(dim);
    RNP::TBLAS::MultMM<'N','N'>(dim,dim,dim,1.,kp[1],dim,phi[1],dim,0.,B.data(),dim);
    for(size_t j=0;j<dim;++j){f[j]=std::exp(Z(0,h[1])*q[1][j]);inc[j]=input[j]*std::exp(Z(0,h[0])*q[0][j]);back[j]=input[5*dim+j]*std::exp(Z(0,h[2])*q[2][j]);
        for(size_t i=0;i<dim;++i){B[i+j*dim]/=q[1][j];B0[i+j*dim]=kp[0][i+j*dim]/q[0][j];B2[i+j*dim]=kp[2][i+j*dim]/q[2][j];}
    }
    for(size_t i=0;i<dim;++i){rhs[i]=-inc[i];rhs[2*dim+i]=back[i];
        for(size_t j=0;j<dim;++j){const size_t ij=i+j*dim;const Z A=phi[1][ij];
            a[i+j*d]=(i==j?1.:0.);a[i+(j+dim)*d]=-A;a[i+(j+2*dim)*d]=-A*f[j];
            a[i+dim+j*d]=-B0[ij];a[i+dim+(j+dim)*d]=-B[ij];a[i+dim+(j+2*dim)*d]=B[ij]*f[j];
            a[i+2*dim+(j+dim)*d]=A*f[j];a[i+2*dim+(j+2*dim)*d]=A;a[i+2*dim+(j+3*dim)*d]=(i==j?-1.:0.);
            a[i+3*dim+(j+dim)*d]=B[ij]*f[j];a[i+3*dim+(j+2*dim)*d]=-B[ij];a[i+3*dim+(j+3*dim)*d]=-B2[ij];
            rhs[i+dim]-=B0[ij]*inc[j];rhs[i+3*dim]-=B2[ij]*back[j];
        }
    }
    int info=0;RNP::LinearSolve<'N'>(d,1,a.data(),d,rhs.data(),d,&info,NULL);require(!info,"dense boundary reference");
    std::vector<Z> output=input;std::copy(rhs.begin(),rhs.end(),output.begin()+dim);return output;
}
int main(){
    double worst_eigen=0,worst_boundary=0;int cases=0;
    for(int radius2 : {0,2,37}){
        std::vector<int>g;std::vector<double>kx,ky;S4Mirror::Basis b=basis(radius2,g,kx,ky);const size_t dim=b.dim;
        if(radius2==37){require(b.n==121,"121 orders");require(b.start[1]==60&&b.start[2]==121&&b.start[3]==182&&b.start[4]==242,"60/61/61/60 sectors");}
        std::vector<Z>eye(dim*dim);for(size_t s=0;s<4;++s)for(size_t j=b.start[s];j<b.start[s+1];++j){std::vector<Z>v(b.start[s+1]-b.start[s]);v[j-b.start[s]]=1; b.LiftVector(s,v.data(),eye.data()+j*dim);}
        for(size_t j=0;j<dim;++j)for(size_t i=0;i<dim;++i){Z dot=0;for(size_t k=0;k<dim;++k)dot+=eye[k+i*dim]*eye[k+j*dim];require(std::abs(dot-Z(i==j?1:0))<1e-14,"complete orthonormal transform");}
        std::vector<Z>op=make_operator(b,2),q(dim),phi(dim*dim);
        require(S4Mirror::Eigensystem(b,op.data(),q.data(),phi.data()),"sector general complex eigensystem");
        for(size_t j=0;j<dim;++j)for(size_t i=0;i<dim;++i){Z sum=0;for(size_t k=0;k<dim;++k)sum+=op[i+k*dim]*phi[k+j*dim];worst_eigen=std::max(worst_eigen,std::abs(sum-q[j]*phi[i+j*dim]));}
        require(worst_eigen<2e-12,"full eigenoperator residual");++cases;
        if(radius2==0)continue;
        std::vector<Z>bad=op,oldphi=phi,oldq=q;bad[0]+=Z(.013,.004);
        require(!S4Mirror::Eigensystem(b,bad.data(),q.data(),phi.data()),"asymmetric operator fallback");require(phi==oldphi&&q==oldq,"eigen fallback is transactional");
        bad=op;bad[0]=std::numeric_limits<double>::quiet_NaN();require(!S4Mirror::Eigensystem(b,bad.data(),q.data(),phi.data()),"nonfinite eigen fallback");
        auto badg=g;badg[0]=39;S4Mirror::Basis reject;require(!reject.Build(b.n,badg.data(),kx.data(),ky.data()),"nonclosed G fallback");
        auto badkx=kx;for(auto&v:badkx)v+=1e-13;require(!reject.Build(b.n,g.data(),badkx.data(),ky.data()),"tiny oblique incidence fallback");
        ++cases;
        // Use moderate dimension for dense 4*dim validation, not a benchmark.
        if(radius2==37)continue;
        const Z omega(2.7,0),eps0(1.2,.02),eps2(2.3,.09);std::vector<Z>k0=uniform_kp(kx,ky,eps0,omega),k2=uniform_kp(kx,ky,eps2,omega),k1=make_operator(b,7),q0(dim),q2(dim);
        for(size_t j=0;j<b.n;++j){q0[j+b.n]=q0[j]=std::sqrt(eps0*omega*omega-kx[j]*kx[j]-ky[j]*ky[j]);q2[j+b.n]=q2[j]=std::sqrt(eps2*omega*omega-kx[j]*kx[j]-ky[j]*ky[j]);}
        for(size_t j=0;j<dim;++j)q[j]=std::sqrt(q[j]);
        const Z *qs[3]={q0.data(),q.data(),q2.data()},*ks[3]={k0.data(),k1.data(),k2.data()},*ps[3]={NULL,phi.data(),NULL};
        for(int mode=0;mode<4;++mode){
            const double h[3]={mode==3?.19:0.,mode==2?35.:.25,mode==3?.31:0.};std::vector<Z>input(6*dim);
            for(size_t j=0;j<dim;++j){if(mode!=1)input[j]=Z(std::sin(j+.1),.2*std::cos(j));if(mode!=0)input[5*dim+j]=Z(.3*std::cos(j),std::sin(j+.2));}
            auto expected=dense_boundary(dim,h,qs,ks,ps,input),output=input;
            require(S4Mirror::ThreeLayer(b,h,qs,ks,ps,output.data()),"all-sector top/bottom boundary solve");
            worst_boundary=std::max(worst_boundary,error(output,expected));require(worst_boundary<2e-12,"all amplitudes match dense continuity solve");++cases;
        }
        const double h[3]={0,.25,0};std::vector<Z>input(6*dim,Z(.1,.2)),output=input;
        q0[0]=0;require(!S4Mirror::ThreeLayer(b,h,qs,ks,ps,output.data()),"cutoff fallback");require(output==input,"boundary fallback transactional");++cases;
    }
    std::printf("mirror symmetry: %d cases passed; full eigen residual %.17g; boundary amplitude error %.17g\n",cases,worst_eigen,worst_boundary);
    return 0;
}
