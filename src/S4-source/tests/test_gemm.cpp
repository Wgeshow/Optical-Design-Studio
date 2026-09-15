#include "accelerator.h"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>
#include <vector>
using Z = std::complex<double>;
Z element(const std::vector<Z>& a, int ld, int i, int j, char trans) {
    const Z z = trans == 'N' ? a[i+j*ld] : a[j+i*ld];
    return trans == 'C' ? std::conj(z) : z;
}
int main() {
    int cases = 0;
    double worst = 0;
    for (char ta : {'N','T','C'}) for (char tb : {'N','T','C'}) {
        for (Z beta : {Z(0), Z(0.4, -0.2)}) {
            const int m=7, n=5, k=6, lda=11, ldb=13, ldc=12;
            std::vector<Z> a(lda*7), b(ldb*6), c(ldc*n, Z(99,99));
            for (size_t i=0; i<a.size(); ++i) a[i]=Z(std::sin(i*0.17), std::cos(i*0.13));
            for (size_t i=0; i<b.size(); ++i) b[i]=Z(std::cos(i*0.11), std::sin(i*0.19));
            for (int j=0;j<n;++j) for(int i=0;i<m;++i) c[i+j*ldc] = beta == Z(0) ? Z(std::numeric_limits<double>::quiet_NaN()) : Z(i*0.2,j*0.1);
            const Z alpha(0.7,-0.3);
            std::vector<Z> expected = c;
            for (int j=0;j<n;++j) for(int i=0;i<m;++i) {
                Z sum=0;
                for (int l=0;l<k;++l) sum += element(a,lda,i,l,ta)*element(b,ldb,l,j,tb);
                expected[i+j*ldc] = alpha*sum + (beta == Z(0) ? Z(0) : beta*c[i+j*ldc]);
            }
            if (!S4Accel::Gemm(ta,tb,m,n,k,alpha,a.data(),lda,b.data(),ldb,beta,c.data(),ldc)) return 2;
            for (size_t i=0;i<c.size();++i) {
                const double error=std::abs(c[i]-expected[i]);
                if (!std::isfinite(error) || error > 1e-11) { std::fprintf(stderr,"Mismatch %c %c at %zu\n",ta,tb,i); return 1; }
                worst=std::max(worst,error);
            }
            ++cases;
        }
    }
    std::printf("%d GEMM cases passed; max abs error %.3g; CPU=%llu GPU=%llu failures=%llu; %s\n",cases,worst,S4_accel_cpu_calls(),S4_accel_gpu_calls(),S4_accel_gpu_failures(),S4_accel_status());
}
