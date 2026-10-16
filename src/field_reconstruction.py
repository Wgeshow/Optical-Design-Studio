"""Separable complex128 Fourier synthesis with optional resident cuBLAS buffers.

Every retained order contributes. The CPU contracts the small harmonic tensor;
the GPU can perform the large final product for several depths together. No
reduced precision, interpolation, padding or resampling is used.
"""
import ctypes
import os
from pathlib import Path
import sys

import numpy as np
from threadpoolctl import threadpool_limits


def harmonic_plan(g, xs, ys, ax, ay, kx, ky):
    gx, ix = np.unique(g[:, 0], return_inverse=True)
    gy, iy = np.unique(g[:, 1], return_inverse=True)
    px = np.exp(1j * np.asarray(xs)[:, None] * (gx * (2 * np.pi / ax) + kx))
    py = np.exp(1j * np.asarray(ys)[:, None] * (gy * (2 * np.pi / ay) + ky))
    return px, py, ix, iy


def contract_y(plan, coefficients, separate=False):
    """[depth, harmonic, component] -> [depth, gx, y * component]."""
    px, py, ix, iy = plan
    batch = len(coefficients)
    grid = np.zeros((py.shape[1], px.shape[1], batch, 6), np.complex128)
    np.add.at(grid, (iy, ix), np.asarray(coefficients).transpose(1, 0, 2))
    middle = py @ grid.reshape(py.shape[1], -1)
    if separate:
        # E and H are distinct GEMM batch entries. Their returned planes are
        # contiguous Nx x Ny x 3 arrays, so storage needs no deinterleaving copy.
        return np.ascontiguousarray(middle.reshape(len(py), px.shape[1], batch, 2, 3)
            .transpose(2, 3, 1, 0, 4)).reshape(batch*2, px.shape[1], len(py)*3)
    return np.ascontiguousarray(middle.reshape(len(py), px.shape[1], batch, 6)
        .transpose(2, 1, 0, 3)).reshape(batch, px.shape[1], len(py) * 6)


def synthesize_cpu(plan, coefficients, threads=1):
    with threadpool_limits(limits=threads, user_api='blas'):
        middle = contract_y(plan, coefficients)
        values = np.matmul(plan[0], middle)
    return values.reshape(len(coefficients), len(plan[0]), len(plan[1]), 6)


def _library(names, override=None):
    candidates = [override] if override else []
    directories = [Path(getattr(sys, '_MEIPASS', Path(__file__).parent))]
    directories += [Path(p) for p in os.environ.get('S4_DLL_DIRS', '').split(os.pathsep) if p]
    for directory in directories:
        candidates += [str(directory / name) for name in names]
    candidates += list(names)
    failures = []
    for candidate in candidates:
        try:
            return ctypes.CDLL(candidate)
        except OSError as exc:
            failures.append(str(exc))
    raise RuntimeError('CUDA field reconstruction libraries unavailable: ' + failures[-1])


class CudaSynthesis:
    """A worker-local cuBLAS handle and bounded reusable device workspace."""
    def __init__(self, px, device=0):
        self.buffers = {}
        self.handle = ctypes.c_void_p()
        self.device = int(device)
        self.closed = False
        self.calls = 0
        self.copy_bytes = 0
        self.peak_device_bytes = 0
        if os.name == 'nt':
            runtime_names = ('cudart64_12.dll', 'cudart64_110.dll')
            blas_names = ('cublas64_12.dll', 'cublas64_11.dll')
        else:
            runtime_names = ('libcudart.so.12', 'libcudart.so.11.0', 'libcudart.so')
            blas_names = ('libcublas.so.12', 'libcublas.so.11', 'libcublas.so')
        self.runtime = _library(runtime_names)
        self.blas = _library(blas_names, os.environ.get('S4_CUBLAS_LIBRARY'))
        pointer = ctypes.c_void_p
        integer = ctypes.c_int
        size = ctypes.c_size_t
        signatures = {
            'cudaSetDevice': [integer], 'cudaMalloc': [ctypes.POINTER(pointer), size],
            'cudaFree': [pointer], 'cudaMemcpy': [pointer, pointer, size, integer],
            'cudaDeviceSynchronize': [],
        }
        for name, arguments in signatures.items():
            function = getattr(self.runtime, name)
            function.argtypes, function.restype = arguments, integer
        for name, arguments in {
            'cublasCreate_v2': [ctypes.POINTER(pointer)], 'cublasDestroy_v2': [pointer],
            'cublasSetMathMode': [pointer, integer], 'cublasSetAtomicsMode': [pointer, integer],
            'cublasZgemmStridedBatched': [pointer, integer, integer, integer, integer, integer,
                pointer, pointer, integer, ctypes.c_longlong, pointer, integer, ctypes.c_longlong,
                pointer, pointer, integer, ctypes.c_longlong, integer],
        }.items():
            function = getattr(self.blas, name)
            function.argtypes, function.restype = arguments, integer
        self.px = np.ascontiguousarray(px, np.complex128)
        try:
            self._check(self.runtime.cudaSetDevice(self.device), 'cudaSetDevice')
            self._check(self.blas.cublasCreate_v2(ctypes.byref(self.handle)), 'cublasCreate')
            self._check(self.blas.cublasSetMathMode(self.handle, 0), 'cublasSetMathMode')
            self._check(self.blas.cublasSetAtomicsMode(self.handle, 0), 'cublasSetAtomicsMode')
            self._upload('px', self.px)
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _check(code, operation):
        if code:
            raise RuntimeError(f'{operation} failed (CUDA/cuBLAS status {code})')

    def _buffer(self, name, size):
        previous = self.buffers.get(name)
        if previous and previous[1] >= size:
            return previous[0]
        if previous:
            self._check(self.runtime.cudaFree(previous[0]), 'cudaFree')
            del self.buffers[name]
        pointer = ctypes.c_void_p()
        self._check(self.runtime.cudaMalloc(ctypes.byref(pointer), size), 'cudaMalloc')
        self.buffers[name] = (pointer, size)
        self.peak_device_bytes = max(self.peak_device_bytes, sum(v[1] for v in self.buffers.values()))
        return pointer

    def _upload(self, name, values):
        pointer = self._buffer(name, values.nbytes)
        self._check(self.runtime.cudaMemcpy(pointer, values.ctypes.data, values.nbytes, 1), 'cudaMemcpy H2D')
        self.copy_bytes += values.nbytes
        return pointer

    def multiply(self, middle):
        if self.closed:
            raise RuntimeError('CUDA synthesis is closed')
        self._check(self.runtime.cudaSetDevice(self.device), 'cudaSetDevice')
        middle = np.ascontiguousarray(middle, np.complex128)
        batch, k, m = middle.shape
        n = len(self.px)
        output = np.empty((batch, n, m), np.complex128)
        a = self._upload('middle', middle)
        b = self.buffers['px'][0]
        c = self._buffer('output', output.nbytes)
        alpha, beta = np.asarray(1+0j, np.complex128), np.asarray(0+0j, np.complex128)
        # Row-major C = Px @ middle becomes column-major C.T = middle.T @ Px.T.
        # Px is broadcast across depths with stride 0. All operations are Zgemm.
        self._check(self.blas.cublasZgemmStridedBatched(self.handle, 0, 0, m, n, k,
            alpha.ctypes.data, a, m, k*m, b, k, 0, beta.ctypes.data, c, m, n*m, batch),
            'cublasZgemmStridedBatched')
        self._check(self.runtime.cudaMemcpy(output.ctypes.data, c, output.nbytes, 2), 'cudaMemcpy D2H')
        self.calls += 1
        self.copy_bytes += output.nbytes
        return output

    def close(self):
        if self.closed:
            return
        self.closed = True
        if hasattr(self, 'runtime'):
            self.runtime.cudaSetDevice(self.device)
            for pointer, _ in self.buffers.values():
                self.runtime.cudaFree(pointer)
            self.buffers.clear()
        if self.handle.value and hasattr(self, 'blas'):
            self.blas.cublasDestroy_v2(self.handle)
            self.handle = ctypes.c_void_p()

    def __del__(self):
        self.close()
