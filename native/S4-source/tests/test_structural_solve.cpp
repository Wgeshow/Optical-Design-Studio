// Link against the same LP64 BLAS/LAPACK runtime as S4. No S4 global state.
#include "structural_solve.h"
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <limits>
#include <vector>

typedef std::complex<double> Z;
extern "C" void zgesv_(const int*, const int*, Z*, const int*, int*, Z*, const int*, int*);

static bool equivalent(const std::vector<Z>& a, const std::vector<Z>& b){
	return a.size()==b.size() && !std::memcmp(a.data(), b.data(), a.size()*sizeof(Z));
}

int main(){
	int cases=0;
	double worst=0, residual=0;
	for(int n : {1,7,121}) for(int mode=0; mode<6; ++mode){
		const int m=2*n, nrhs=mode%2 ? 5 : m, lda=m+3, ldb=m+5;
		std::vector<Z> a(lda*m), b(ldb*nrhs,Z(77,31)), x=b;
		for(int g=0; g<n; ++g){
			const double kx=.23+.071*g, ky=-.17+.031*g;
			Z aa,bb,cc,dd;
			if(mode<3){ // Uniform real/lossy, oblique/skew-wavevector couplings.
				const Z omega(1.13,mode==2 ? .02 : 0), eta=1./Z(2.25,mode ? .11 : 0);
				aa=omega*omega-ky*eta*ky; bb=ky*eta*kx;
				cc=kx*eta*ky; dd=omega*omega-kx*eta*kx;
			}else if(mode==3){ // A zero first diagonal must pivot, not reject.
				aa=0.; bb=Z(.4,.8); cc=Z(2.3,-.2); dd=Z(.7,.1);
			}else if(mode==4){ // Complex LAPACK abs1 pivot differs from abs2.
				aa=Z(1.5,0); bb=Z(.2,-.8); cc=Z(1,1); dd=Z(1.7,.3);
			}else{ // Tiny but nonsingular pivots must not be thresholded away.
				aa=1e-200; bb=0.; cc=0.; dd=2e-200;
			}
			a[g+g*lda]=aa; a[g+(g+n)*lda]=bb;
			a[g+n+g*lda]=cc; a[g+n+(g+n)*lda]=dd;
			for(int j=0;j<nrhs;++j){
				Z s(std::sin(.13*(g+j+1)),std::cos(.19*(g+2*j))), t(.3+.002*g,-.2+.01*j);
				b[g+j*ldb]=aa*s+bb*t; b[g+n+j*ldb]=cc*s+dd*t;
			}
		}
		const auto original_a=a, original_b=b;
		if(!S4Structural::SolveUniformBlocks(n,nrhs,a.data(),lda,b.data(),ldb,x.data(),ldb)) return 1;
		if(!equivalent(a,original_a) || !equivalent(b,original_b)) return 2;
		std::vector<int> piv(m);
		int info=0;
		zgesv_(&m,&nrhs,a.data(),&lda,piv.data(),b.data(),&ldb,&info);
		if(info) return 3;
		for(int j=0;j<nrhs;++j) for(int i=0;i<m;++i){
			const double err=std::abs(x[i+j*ldb]-b[i+j*ldb])/std::max(1.,std::abs(b[i+j*ldb]));
			worst=std::max(worst,err);
			if(!std::isfinite(err) || err>2e-12){ std::printf("Parity failure n=%d mode=%d err=%g\n",n,mode,err); return 4; }
			const int g=i%n;
			const Z r=original_a[i+g*lda]*x[g+j*ldb]+original_a[i+(g+n)*lda]*x[g+n+j*ldb]-original_b[i+j*ldb];
			residual=std::max(residual,std::abs(r)/std::max(1.,std::abs(original_b[i+j*ldb])));
		}
		for(int j=0;j<nrhs;++j) for(int i=m;i<ldb;++i) if(x[i+j*ldb]!=Z(77,31)) return 5;
		++cases;
	}
	// Failure late in the solve must leave the original dense inputs untouched.
	for(int mode=0; mode<6; ++mode){
		const int n=3,m=6;
		std::vector<Z>a(m*m),b(m*m,Z(.3,.7)),x(m*m);
		for(int i=0;i<m;++i) a[i+i*m]=1.;
		if(mode==0) a[5+5*m]=0.; // exact singularity, last block
		if(mode==1) a[5+5*m]=std::numeric_limits<double>::infinity();
		if(mode==2) b[5+5*m]=std::numeric_limits<double>::quiet_NaN();
		if(mode==3) a[1]=1e-250; // nonzero inter-order coupling, however small
		if(mode==4){ a[5+5*m]=1e-300; b[5+5*m]=1e300; } // output overflow
		if(mode==5){ a[2+2*m]=1.; a[2+5*m]=2.; a[5+2*m]=2.; a[5+5*m]=4.; }
		const auto aa=a,bb=b;
		if(S4Structural::SolveUniformBlocks(n,m,a.data(),m,b.data(),m,x.data(),m)) return 6;
		if(!equivalent(a,aa) || !equivalent(b,bb)) return 7;
		++cases;
	}
	std::printf("%d structural solve cases passed; max scaled LAPACK difference %.3g; max scaled residual %.3g\n", cases,worst,residual);
	return residual>2e-12 ? 8 : 0;
}
