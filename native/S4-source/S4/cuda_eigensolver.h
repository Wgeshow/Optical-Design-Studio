#ifndef S4_CUDA_EIGENSOLVER_H
#define S4_CUDA_EIGENSOLVER_H

#ifdef __cplusplus
#include <complex>
#include <cstddef>
namespace S4CudaEigen {
// Opt in with S4_GPU=1 and S4_GPU_EIGEN=1 (both required, so CPU workers remain
// CPU-only). S4_GPU_EIGEN_MIN_N defaults to 1024; this is a
// conservative eligibility gate, not a measured crossover. The caller should
// benchmark its matrix sizes before enabling. S4_GPU_DEVICE selects the GPU.
// S4_CUSOLVER_LIBRARY / S4_CUDART_LIBRARY optionally specify exact library paths.
// Optional general complex128 eigensolver. False means the caller must use its
// CPU LAPACK path; all caller buffers remain unchanged in that case. No left
// eigenvectors are supported by cuSOLVER Xgeev. Input A is preserved even on
// success. Never use this entry point for a LAPACK workspace query.
bool TryEigensystem(size_t n, const std::complex<double>* a, size_t lda,
    std::complex<double>* eval, std::complex<double>* vl, size_t ldvl,
    std::complex<double>* vr, size_t ldvr);
}
extern "C" {
#endif
#ifdef _WIN32
#define S4_CUDA_EIGEN_EXPORT __declspec(dllexport)
#else
#define S4_CUDA_EIGEN_EXPORT
#endif
S4_CUDA_EIGEN_EXPORT const char* S4_cuda_eigen_status(void);
S4_CUDA_EIGEN_EXPORT unsigned long long S4_cuda_eigen_calls(void);
S4_CUDA_EIGEN_EXPORT unsigned long long S4_cuda_eigen_fallbacks(void);
S4_CUDA_EIGEN_EXPORT unsigned long long S4_cuda_eigen_failures(void);
S4_CUDA_EIGEN_EXPORT unsigned long long S4_cuda_eigen_workspace_queries(void);
S4_CUDA_EIGEN_EXPORT unsigned long long S4_cuda_eigen_device_bytes(void);
S4_CUDA_EIGEN_EXPORT unsigned long long S4_cuda_eigen_host_bytes(void);
S4_CUDA_EIGEN_EXPORT int S4_cuda_eigen_last_status(void);
S4_CUDA_EIGEN_EXPORT int S4_cuda_eigen_last_info(void);
#undef S4_CUDA_EIGEN_EXPORT
#ifdef __cplusplus
}
#endif
#endif
