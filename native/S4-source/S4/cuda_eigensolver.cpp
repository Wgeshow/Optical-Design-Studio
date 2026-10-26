// Optional cuSOLVER Xgeev backend; GPL-2.0-or-later, like S4.
// Build with S4_USE_CUDA_EIGEN and CUDA >= 12.8 headers. All CUDA symbols are
// loaded at runtime, so an absent GPU/library never prevents CPU-only startup.
#include "cuda_eigensolver.h"
#include <atomic>
#include <climits>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <limits>

#ifdef S4_USE_CUDA_EIGEN
#include <cusolverDn.h>
#include <cuda_runtime_api.h>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <dlfcn.h>
#endif
#endif

namespace {
using Z = std::complex<double>;
std::atomic<unsigned long long> calls(0), fallbacks(0), failures(0), queries(0);
std::atomic<unsigned long long> device_bytes(0), host_bytes(0);
std::atomic<int> last_status(0), last_info(0);
std::atomic<const char*> status("CUDA eigensolver disabled; CPU LAPACK available");
int env_int(const char* name, int fallback, int lo, int hi) {
    const char* s = std::getenv(name);
    if (!s || !*s) return fallback;
    char* end = NULL;
    const long value = std::strtol(s, &end, 10);
    return *end || value < lo || value > hi ? fallback : int(value);
}
#ifdef S4_USE_CUDA_EIGEN
#ifdef _WIN32
using Library = HMODULE;
Library open_library(const char* path) {
    return LoadLibraryExA(path, NULL, LOAD_LIBRARY_SEARCH_DEFAULT_DIRS |
        ((std::strchr(path, '\\') || std::strchr(path, '/')) ? LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR : 0));
}
void* symbol(Library lib, const char* name) { return reinterpret_cast<void*>(GetProcAddress(lib, name)); }
#else
using Library = void*;
Library open_library(const char* path) { return dlopen(path, RTLD_NOW | RTLD_LOCAL); }
void* symbol(Library lib, const char* name) { return dlsym(lib, name); }
#endif
Library load(const char* env, const char* first, const char* second) {
    const char* path = std::getenv(env);
    // An explicit path is authoritative: do not silently test a different SDK.
    if (path && *path) return open_library(path);
    Library lib = open_library(first);
    return lib ? lib : open_library(second);
}

class GPU {
public:
    std::mutex mutex;
    bool attempted = false, failed = false;
    int device = 0;
    Library solver = NULL, runtime = NULL;
    cusolverDnHandle_t handle = NULL;
    cusolverDnParams_t params = NULL;
    cudaStream_t stream = NULL;
#define S4_SYMBOLS(F) \
    F(cusolverDnCreate) F(cusolverDnCreateParams) F(cusolverDnSetStream) \
    F(cusolverDnXgeev_bufferSize) F(cusolverDnXgeev)
#define S4_RUNTIME_SYMBOLS(F) \
    F(cudaGetDevice) F(cudaSetDevice) F(cudaMalloc) F(cudaFree) \
    F(cudaMallocHost) F(cudaFreeHost) F(cudaStreamCreateWithFlags) \
    F(cudaStreamSynchronize) F(cudaMemcpyAsync)
#define DECLARE(name) decltype(&name) p_##name = NULL;
    S4_SYMBOLS(DECLARE)
    S4_RUNTIME_SYMBOLS(DECLARE)
#undef DECLARE
    void* d_a = NULL; void* d_w = NULL; void* d_v = NULL; void* d_info = NULL;
    void* d_work = NULL; void* h_work = NULL; void* h_stage = NULL;
    size_t cached_n = 0, work_device = 0, work_host = 0;
    bool cached_vectors = false;
    bool fail(const char* why, int code = 0) {
        last_status = code;
        status = why;
        failed = true;
        ++failures;
        return false;
    }
    bool init() {
        if (attempted) return !failed;
        attempted = true;
#ifdef _WIN32
        solver = load("S4_CUSOLVER_LIBRARY", "cusolver64_12.dll", "cusolver64_11.dll");
        runtime = load("S4_CUDART_LIBRARY", "cudart64_13.dll", "cudart64_12.dll");
#else
        solver = load("S4_CUSOLVER_LIBRARY", "libcusolver.so.12", "libcusolver.so.11");
        runtime = load("S4_CUDART_LIBRARY", "libcudart.so.13", "libcudart.so.12");
#endif
        if (!solver || !runtime) return fail("CUDA eigensolver libraries unavailable; using CPU");
#define LOAD_SOLVER(name) p_##name = reinterpret_cast<decltype(p_##name)>(symbol(solver, #name)); if (!p_##name) return fail("cuSOLVER Xgeev symbols unavailable; using CPU");
        S4_SYMBOLS(LOAD_SOLVER)
#undef LOAD_SOLVER
#define LOAD_RUNTIME(name) p_##name = reinterpret_cast<decltype(p_##name)>(symbol(runtime, #name)); if (!p_##name) return fail("CUDA runtime symbols unavailable; using CPU");
        S4_RUNTIME_SYMBOLS(LOAD_RUNTIME)
#undef LOAD_RUNTIME
        device = env_int("S4_GPU_DEVICE", 0, 0, 1024);
        int previous = 0;
        cudaError_t ce = p_cudaGetDevice(&previous);
        if (ce != cudaSuccess) return fail("CUDA device unavailable; using CPU", int(ce));
        ce = p_cudaSetDevice(device);
        if (ce != cudaSuccess) return fail("CUDA device selection failed; using CPU", int(ce));
        ce = p_cudaStreamCreateWithFlags(&stream, cudaStreamNonBlocking);
        cusolverStatus_t se = CUSOLVER_STATUS_SUCCESS;
        if (ce == cudaSuccess) se = p_cusolverDnCreate(&handle);
        if (ce == cudaSuccess && se == CUSOLVER_STATUS_SUCCESS) se = p_cusolverDnCreateParams(&params);
        if (ce == cudaSuccess && se == CUSOLVER_STATUS_SUCCESS) se = p_cusolverDnSetStream(handle, stream);
        p_cudaSetDevice(previous);
        if (ce != cudaSuccess || se != CUSOLVER_STATUS_SUCCESS)
            return fail("CUDA eigensolver initialization failed; using CPU", ce != cudaSuccess ? int(ce) : int(se));
        return true;
    }
    void release_buffers() {
        if (d_a) p_cudaFree(d_a); if (d_w) p_cudaFree(d_w);
        if (d_v) p_cudaFree(d_v); if (d_info) p_cudaFree(d_info);
        if (d_work) p_cudaFree(d_work);
        if (h_work) p_cudaFreeHost(h_work); if (h_stage) p_cudaFreeHost(h_stage);
        d_a = d_w = d_v = d_info = d_work = h_work = h_stage = NULL;
        cached_n = work_device = work_host = 0;
        device_bytes = host_bytes = 0;
    }
    bool workspace(size_t n, bool vectors) {
        if (cached_n == n && cached_vectors == vectors) return true;
        release_buffers();
        const size_t matrix = sizeof(Z) * n * n, values = sizeof(Z) * n;
        cudaError_t ce = p_cudaMalloc(&d_a, matrix);
        if (ce == cudaSuccess) ce = p_cudaMalloc(&d_w, values);
        if (ce == cudaSuccess && vectors) ce = p_cudaMalloc(&d_v, matrix);
        if (ce == cudaSuccess) ce = p_cudaMalloc(&d_info, sizeof(int));
        const size_t staging = matrix + values + (vectors ? matrix : 0);
        if (ce == cudaSuccess) ce = p_cudaMallocHost(&h_stage, staging);
        if (ce != cudaSuccess) return fail("CUDA eigensolver buffer allocation failed; using CPU", int(ce));
        const cusolverEigMode_t mode = vectors ? CUSOLVER_EIG_MODE_VECTOR : CUSOLVER_EIG_MODE_NOVECTOR;
        ++queries;
        const cusolverStatus_t se = p_cusolverDnXgeev_bufferSize(handle, params,
            CUSOLVER_EIG_MODE_NOVECTOR, mode, n, CUDA_C_64F, d_a, n,
            CUDA_C_64F, d_w, CUDA_C_64F, NULL, 1, CUDA_C_64F, d_v,
            vectors ? n : 1, CUDA_C_64F, &work_device, &work_host);
        if (se != CUSOLVER_STATUS_SUCCESS) return fail("cuSOLVER Xgeev workspace query failed; using CPU", int(se));
        if (work_device) ce = p_cudaMalloc(&d_work, work_device);
        if (ce == cudaSuccess && work_host) ce = p_cudaMallocHost(&h_work, work_host);
        if (ce != cudaSuccess) return fail("cuSOLVER Xgeev workspace allocation failed; using CPU", int(ce));
        cached_n = n; cached_vectors = vectors;
        device_bytes = matrix + values + (vectors ? matrix : 0) + sizeof(int) + work_device;
        host_bytes = staging + work_host;
        return true;
    }
    // Python can unload extension DLLs during finalization. Avoid CUDA teardown
    // at DLL detach; the OS releases the process-lifetime context and buffers.
};
GPU& gpu() { static GPU* instance = new GPU; return *instance; }
struct DeviceGuard {
    GPU& g; int previous;
    DeviceGuard(GPU& input, int old) : g(input), previous(old) {}
    ~DeviceGuard() { g.p_cudaSetDevice(previous); }
};

bool solve(size_t n, const Z* a, size_t lda, Z* eval, Z* vr, size_t ldvr) {
    GPU& g = gpu();
    std::lock_guard<std::mutex> lock(g.mutex);
    if (!g.init()) return false;
    int previous = 0;
    cudaError_t ce = g.p_cudaGetDevice(&previous);
    if (ce != cudaSuccess) return g.fail("CUDA current device query failed; using CPU", int(ce));
    ce = g.p_cudaSetDevice(g.device);
    if (ce != cudaSuccess) return g.fail("CUDA eigensolver device selection failed; using CPU", int(ce));
    DeviceGuard restore(g, previous);
    if (!g.workspace(n, vr != NULL)) { g.release_buffers(); return false; }
    const size_t matrix = sizeof(Z) * n * n, values = sizeof(Z) * n;
    Z* input = static_cast<Z*>(g.h_stage);
    Z* result_w = input + n*n;
    Z* result_v = result_w + n;
    for (size_t j = 0; j < n; ++j) std::memcpy(input + j*n, a + j*lda, sizeof(Z)*n);
    ce = g.p_cudaMemcpyAsync(g.d_a, input, matrix, cudaMemcpyHostToDevice, g.stream);
    cusolverStatus_t se = CUSOLVER_STATUS_SUCCESS;
    if (ce == cudaSuccess) se = g.p_cusolverDnXgeev(g.handle, g.params,
        CUSOLVER_EIG_MODE_NOVECTOR, vr ? CUSOLVER_EIG_MODE_VECTOR : CUSOLVER_EIG_MODE_NOVECTOR,
        n, CUDA_C_64F, g.d_a, n, CUDA_C_64F, g.d_w, CUDA_C_64F, NULL, 1,
        CUDA_C_64F, g.d_v, vr ? n : 1, CUDA_C_64F,
        g.d_work, g.work_device, g.h_work, g.work_host, static_cast<int*>(g.d_info));
    int info = 0;
    if (ce == cudaSuccess && se == CUSOLVER_STATUS_SUCCESS)
        ce = g.p_cudaMemcpyAsync(&info, g.d_info, sizeof(info), cudaMemcpyDeviceToHost, g.stream);
    if (ce == cudaSuccess && se == CUSOLVER_STATUS_SUCCESS)
        ce = g.p_cudaMemcpyAsync(result_w, g.d_w, values, cudaMemcpyDeviceToHost, g.stream);
    if (ce == cudaSuccess && se == CUSOLVER_STATUS_SUCCESS && vr)
        ce = g.p_cudaMemcpyAsync(result_v, g.d_v, matrix, cudaMemcpyDeviceToHost, g.stream);
    // Always drain this stream before fallback or reuse, including failed calls.
    const cudaError_t sync = g.p_cudaStreamSynchronize(g.stream);
    last_info = info;
    if (ce != cudaSuccess || sync != cudaSuccess || se != CUSOLVER_STATUS_SUCCESS || info != 0)
        return g.fail("cuSOLVER Xgeev failed; disabled for this process, using CPU",
            ce != cudaSuccess ? int(ce) : (sync != cudaSuccess ? int(sync) : int(se)));
    for (size_t i = 0; i < n + (vr ? n*n : 0); ++i)
        if (!std::isfinite(result_w[i].real()) || !std::isfinite(result_w[i].imag()))
            return g.fail("cuSOLVER Xgeev returned nonfinite values; using CPU");
    // Commit only after the entire solve and both downloads have succeeded.
    std::memcpy(eval, result_w, values);
    if (vr) for (size_t j = 0; j < n; ++j) std::memcpy(vr + j*ldvr, result_v + j*n, sizeof(Z)*n);
    ++calls; last_status = 0;
    status = "cuSOLVER Xgeev complex128; cached device and pinned host workspaces";
    return true;
}
#endif
}

bool S4CudaEigen::TryEigensystem(size_t n, const Z* a, size_t lda, Z* eval,
    Z* vl, size_t ldvl, Z* vr, size_t ldvr) {
    (void)ldvl;
    if (!env_int("S4_GPU", 0, 0, 1) || !env_int("S4_GPU_EIGEN", 0, 0, 1)) return false;
#ifdef S4_USE_CUDA_EIGEN
    // Xgeev is a general solver: never substitute a Hermitian eigensolver.
    // The conservative n*n bound also accommodates older CUDA12.8 releases.
    if (vl || !n || !a || !eval || lda < n || (vr && ldvr < n) ||
        n > 46340 || n < size_t(env_int("S4_GPU_EIGEN_MIN_N", 1024, 1, INT_MAX))) {
        ++fallbacks;
        return false;
    }
    if (solve(n, a, lda, eval, vr, ldvr)) return true;
#else
    (void)n; (void)a; (void)lda; (void)eval; (void)vl; (void)vr; (void)ldvr;
    status = "This build has no CUDA eigensolver support; using CPU";
#endif
    ++fallbacks;
    return false;
}

extern "C" const char* S4_cuda_eigen_status() { return status.load(); }
extern "C" unsigned long long S4_cuda_eigen_calls() { return calls.load(); }
extern "C" unsigned long long S4_cuda_eigen_fallbacks() { return fallbacks.load(); }
extern "C" unsigned long long S4_cuda_eigen_failures() { return failures.load(); }
extern "C" unsigned long long S4_cuda_eigen_workspace_queries() { return queries.load(); }
extern "C" unsigned long long S4_cuda_eigen_device_bytes() { return device_bytes.load(); }
extern "C" unsigned long long S4_cuda_eigen_host_bytes() { return host_bytes.load(); }
extern "C" int S4_cuda_eigen_last_status() { return last_status.load(); }
extern "C" int S4_cuda_eigen_last_info() { return last_info.load(); }
