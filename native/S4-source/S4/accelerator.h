#ifndef S4_ACCELERATOR_H
#define S4_ACCELERATOR_H

#ifdef __cplusplus
#include <complex>
#include <cstddef>
namespace S4Accel {
bool Gemm(char ta, char tb, size_t m, size_t n, size_t k,
    std::complex<double> alpha, const std::complex<double>* a, size_t lda,
    const std::complex<double>* b, size_t ldb, std::complex<double> beta,
    std::complex<double>* c, size_t ldc);
template<class A, class B, class T>
inline bool TryGemm(char, char, size_t, size_t, size_t, const A&, const T*,
    size_t, const T*, size_t, const B&, T*, size_t) { return false; }
template<class A, class B>
inline bool TryGemm(char ta, char tb, size_t m, size_t n, size_t k,
    const A& alpha, const std::complex<double>* a, size_t lda,
    const std::complex<double>* b, size_t ldb, const B& beta,
    std::complex<double>* c, size_t ldc) {
    return Gemm(ta, tb, m, n, k, std::complex<double>(alpha), a, lda,
        b, ldb, std::complex<double>(beta), c, ldc);
}
}
extern "C" {
#endif
const char* S4_accel_status(void);
unsigned long long S4_accel_cpu_calls(void);
unsigned long long S4_accel_gpu_calls(void);
unsigned long long S4_accel_gpu_failures(void);
#ifdef __cplusplus
}
#endif
#endif
