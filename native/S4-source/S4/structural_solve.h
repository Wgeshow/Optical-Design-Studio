#ifndef S4_STRUCTURAL_SOLVE_H
#define S4_STRUCTURAL_SOLVE_H

#include <cmath>
#include <complex>
#include <cstddef>
#include <utility>

namespace S4Structural {

inline bool Finite(const std::complex<double> &z){
	return std::isfinite(z.real()) && std::isfinite(z.imag());
}

// Solve the independent (g, g+n) polarization blocks of a uniform layer.
// The caller must establish uniform scalar permittivity and phi == identity.
// All entries, including both polarization couplings, are retained. There is
// no determinant formula, magnitude cutoff, or sparsity tolerance. Partial
// pivoting uses LAPACK's complex 1-norm comparison.
//
// A and B are never modified. X is scratch and must not alias either input;
// only a true return permits the caller to commit X to B. Thus a singular or
// nonfinite block (even the last one) can fall back to the original dense solve.
inline bool SolveUniformBlocks(
	std::size_t n, std::size_t nrhs,
	const std::complex<double> *a, std::size_t lda,
	const std::complex<double> *b, std::size_t ldb,
	std::complex<double> *x, std::size_t ldx
){
	typedef std::complex<double> Complex;
	const std::size_t n2 = 2*n;
	// A supplied kp must also satisfy the promised structure exactly. This
	// inexpensive scan protects against malformed input and nonfinite entries.
	for(std::size_t j = 0; j < n2; ++j){
		const std::size_t g = j < n ? j : j-n;
		for(std::size_t i = 0; i < n2; ++i){
			if(!Finite(a[i+j*lda]) || (i != g && i != g+n && a[i+j*lda] != Complex(0.))){ return false; }
		}
	}
	for(std::size_t g = 0; g < n; ++g){
		Complex u11 = a[g+g*lda], u12 = a[g+(g+n)*lda];
		Complex l21 = a[g+n+g*lda], u22 = a[g+n+(g+n)*lda];
		const bool pivot = std::abs(l21.real())+std::abs(l21.imag()) >
			std::abs(u11.real())+std::abs(u11.imag());
		if(pivot){ std::swap(u11,l21); std::swap(u12,u22); }
		if(u11 == Complex(0.)){ return false; }
		l21 /= u11;
		u22 -= l21*u12;
		if(!Finite(l21) || !Finite(u22) || u22 == Complex(0.)){ return false; }
		for(std::size_t j = 0; j < nrhs; ++j){
			Complex r1 = b[g+j*ldb], r2 = b[g+n+j*ldb];
			if(!Finite(r1) || !Finite(r2)){ return false; }
			if(pivot){ std::swap(r1,r2); }
			r2 = (r2-l21*r1)/u22;
			r1 = (r1-u12*r2)/u11;
			if(!Finite(r1) || !Finite(r2)){ return false; }
			x[g+j*ldx] = r1;
			x[g+n+j*ldx] = r2;
		}
	}
	return true;
}

} // namespace S4Structural

#endif
