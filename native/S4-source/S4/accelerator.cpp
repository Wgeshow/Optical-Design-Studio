// Optional double-complex GEMM acceleration; GPL-2.0-or-later, like S4.
#include "accelerator.h"
#include <algorithm>
#include <atomic>
#include <climits>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <limits>

extern "C" void zgemm_(const char*, const char*, const int&, const int&,
    const int&, const std::complex<double>&, const std::complex<double>*,
    const int&, const std::complex<double>*, const int&,
    const std::complex<double>&, std::complex<double>*, const int&);

#ifdef S4_USE_CUDA
#include <cublasXt.h>
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#else
#include <dlfcn.h>
#endif
#endif

namespace {
using Z = std::complex<double>;
std::atomic<unsigned long long> cpu_calls(0), gpu_calls(0), gpu_failures(0);
std::atomic<const char*> status("GPU not initialized (CPU is available)");
int env_int(const char* key, int fallback, int lo, int hi) {
    const char* s = std::getenv(key);
    if (!s || !*s) return fallback;
    char* end = NULL;
    const long v = std::strtol(s, &end, 10);
    return (*end || v < lo || v > hi) ? fallback : static_cast<int>(v);
}

#ifdef S4_USE_CUDA
class GPU {
public:
    std::mutex mutex;
    cublasXtHandle_t handle = NULL;
    decltype(&cublasXtCreate) create = NULL;
    decltype(&cublasXtDestroy) destroy = NULL;
    decltype(&cublasXtDeviceSelect) select = NULL;
    decltype(&cublasXtSetBlockDim) block = NULL;
    decltype(&cublasXtZgemm) gemm = NULL;
    bool attempted = false;
    bool failed = false;
#ifdef _WIN32
    HMODULE library = NULL;
    void* symbol(const char* name) { return reinterpret_cast<void*>(GetProcAddress(library, name)); }
#else
    void* library = NULL;
    void* symbol(const char* name) { return dlsym(library, name); }
#endif
    bool init() {
        if (attempted) return handle && !failed;
        attempted = true;
        const char* path = std::getenv("S4_CUBLAS_LIBRARY");
#ifdef _WIN32
        const char* candidates[] = {path, "cublas64_12.dll", "cublas64_11.dll", "cublas64_10.dll"};
        for (const char* candidate : candidates) {
            if (!candidate) continue;
            library = LoadLibraryExA(candidate, NULL, LOAD_LIBRARY_SEARCH_DEFAULT_DIRS |
                ((std::strchr(candidate, '\\') || std::strchr(candidate, '/')) ? LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR : 0));
            if (library) break;
        }
#else
        const char* candidates[] = {path, "libcublas.so.12", "libcublas.so.11", "libcublas.so.10"};
        for (const char* candidate : candidates) {
            if (!candidate) continue;
            library = dlopen(candidate, RTLD_NOW | RTLD_LOCAL);
            if (library) break;
        }
#endif
        if (!library) { status = "cuBLAS library unavailable; using CPU"; ++gpu_failures; return false; }
        create = reinterpret_cast<decltype(create)>(symbol("cublasXtCreate"));
        destroy = reinterpret_cast<decltype(destroy)>(symbol("cublasXtDestroy"));
        select = reinterpret_cast<decltype(select)>(symbol("cublasXtDeviceSelect"));
        block = reinterpret_cast<decltype(block)>(symbol("cublasXtSetBlockDim"));
        gemm = reinterpret_cast<decltype(gemm)>(symbol("cublasXtZgemm"));
        if (!create || !destroy || !select || !block || !gemm) {
            status = "cuBLASXt symbols unavailable; using CPU"; ++gpu_failures; return false;
        }
        int device = env_int("S4_GPU_DEVICE", 0, 0, 1024);
        if (create(&handle) != CUBLAS_STATUS_SUCCESS ||
            select(handle, 1, &device) != CUBLAS_STATUS_SUCCESS ||
            block(handle, env_int("S4_GPU_BLOCK", 256, 64, 1024)) != CUBLAS_STATUS_SUCCESS) {
            failed = true; ++gpu_failures;
            status = "GPU initialization failed; using CPU"; return false;
        }
        status = "cuBLASXt ready; large GEMMs use GPU, LAPACK uses CPU";
        return true;
    }
    // Deliberately keep the CUDA context and loader handle until process exit.
    // Explicit teardown can deadlock during Python DLL finalization (especially
    // with WDDM); the operating system reclaims these per-process resources.
    ~GPU() {}
};
GPU& gpu() { static GPU instance; return instance; }

bool gpu_gemm(char ta, char tb, int m, int n, int k, Z alpha, const Z* a,
    int lda, const Z* b, int ldb, Z beta, Z* c, int ldc) {
    if (!env_int("S4_GPU", 0, 0, 1)) return false;
    const int threshold = env_int("S4_GPU_MIN_N", 1024, 1, INT_MAX);
    if (m < threshold || n < threshold || k < threshold || alpha == Z(0)) return false;
    GPU& g = gpu();
    std::lock_guard<std::mutex> lock(g.mutex);
    if (!g.init()) return false;
    // Xt tiles device memory. A separate, packed host output makes CPU fallback
    // safe even when a failed CUDA call has partially overwritten its output.
    if (size_t(m) > std::numeric_limits<size_t>::max() / sizeof(Z) / size_t(n)) return false;
    Z* result = static_cast<Z*>(std::malloc(sizeof(Z) * size_t(m) * n));
    if (!result) { ++gpu_failures; return false; }
    if (beta != Z(0)) {
        for (int j = 0; j < n; ++j) std::memcpy(result + size_t(j)*m, c + size_t(j)*ldc, sizeof(Z)*m);
    }
    const cublasOperation_t opa = ta == 'N' ? CUBLAS_OP_N : (ta == 'T' ? CUBLAS_OP_T : CUBLAS_OP_C);
    const cublasOperation_t opb = tb == 'N' ? CUBLAS_OP_N : (tb == 'T' ? CUBLAS_OP_T : CUBLAS_OP_C);
    static_assert(sizeof(Z) == sizeof(cuDoubleComplex), "complex ABI mismatch");
    const cublasStatus_t rc = g.gemm(g.handle, opa, opb, m, n, k,
        reinterpret_cast<const cuDoubleComplex*>(&alpha),
        reinterpret_cast<const cuDoubleComplex*>(a), lda,
        reinterpret_cast<const cuDoubleComplex*>(b), ldb,
        reinterpret_cast<const cuDoubleComplex*>(&beta),
        reinterpret_cast<cuDoubleComplex*>(result), m);
    if (rc == CUBLAS_STATUS_SUCCESS) {
        for (int j = 0; j < n; ++j) std::memcpy(c + size_t(j)*ldc, result + size_t(j)*m, sizeof(Z)*m);
        ++gpu_calls;
    } else {
        ++gpu_failures; g.failed = true;
        status = "GPU GEMM failed; GPU disabled for this process, using CPU";
    }
    std::free(result);
    return rc == CUBLAS_STATUS_SUCCESS;
}
#endif
}

bool S4Accel::Gemm(char ta, char tb, size_t m, size_t n, size_t k,
    Z alpha, const Z* a, size_t lda, const Z* b, size_t ldb, Z beta, Z* c, size_t ldc) {
    if (m > INT_MAX || n > INT_MAX || k > INT_MAX || lda > INT_MAX || ldb > INT_MAX || ldc > INT_MAX) return false;
    if (m == 0 || n == 0) return true;
#ifdef S4_USE_CUDA
    if (k && gpu_gemm(ta, tb, int(m), int(n), int(k), alpha, a, int(lda), b, int(ldb), beta, c, int(ldc))) return true;
#else
    status = "CPU BLAS; this build has no CUDA support";
#endif
    ++cpu_calls;
    zgemm_(&ta, &tb, int(m), int(n), int(k), alpha, a, int(lda), b, int(ldb), beta, c, int(ldc));
    return true;
}
extern "C" const char* S4_accel_status() { return status.load(); }
extern "C" unsigned long long S4_accel_cpu_calls() { return cpu_calls.load(); }
extern "C" unsigned long long S4_accel_gpu_calls() { return gpu_calls.load(); }
extern "C" unsigned long long S4_accel_gpu_failures() { return gpu_failures.load(); }
