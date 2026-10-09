"""Spawn-safe, bounded process sweeps. Pass plain parameters, never S4 objects.

Define the simulation function at module scope and import S4 inside it.
Call parallel_map only under `if __name__ == '__main__':` (also on Linux).
"""
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import multiprocessing as mp
import os
from s4_runtime import configure

def _initialize(threads, gpu, device, minimum):
    configure(threads, gpu, device, minimum)

def parallel_map(function, parameters, *, workers=None, threads_per_worker=1,
                 gpu=False, gpu_device=0, gpu_min_n=1024, max_pending=None):
    """Return input-ordered results; propagate worker errors to the caller.

    gpu=True uses ONE GPU-designated process plus workers-1 CPU-only processes.
    Each lane takes another job when ready, so slower GPU work is self-limiting.
    `workers * threads_per_worker` must fit the logical CPU budget. GPU mode
    uses the CPU for eigenproblems; it does not move the entire solver to CUDA.
    """
    cores = os.cpu_count() or 1
    if isinstance(threads_per_worker, bool) or not isinstance(threads_per_worker, int) or threads_per_worker < 1:
        raise ValueError('threads_per_worker must be a positive integer')
    if workers is None:
        workers = max(1, cores // threads_per_worker)
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError('workers must be a positive integer')
    if workers * threads_per_worker > cores:
        raise ValueError('workers * threads_per_worker exceeds available logical CPUs')
    if max_pending is None:
        max_pending = 2 * workers
    if isinstance(max_pending, bool) or not isinstance(max_pending, int) or max_pending < workers:
        raise ValueError('max_pending must be an integer >= workers')
    if isinstance(gpu_device, bool) or not isinstance(gpu_device, int) or gpu_device < 0:
        raise ValueError('gpu_device must be a nonnegative integer')
    if isinstance(gpu_min_n, bool) or not isinstance(gpu_min_n, int) or gpu_min_n < 1:
        raise ValueError('gpu_min_n must be a positive integer')
    context = mp.get_context('spawn')
    iterator = iter(enumerate(parameters))
    results = []
    pending = {}
    pools = []
    exhausted = False
    try:
        if gpu:
            pools.append((ProcessPoolExecutor(1, mp_context=context, initializer=_initialize,
                initargs=(threads_per_worker, True, gpu_device, gpu_min_n)), 1))
        cpu_workers = workers - int(bool(gpu))
        if cpu_workers:
            pools.append((ProcessPoolExecutor(cpu_workers, mp_context=context, initializer=_initialize,
                initargs=(threads_per_worker, False, gpu_device, gpu_min_n)), cpu_workers))
        # One in-flight job per GPU process; CPU queue may prefetch remaining capacity.
        slots = []
        for pool, count in pools:
            slots.extend([pool] * count)
        if cpu_workers:
            slots.extend([pools[-1][0]] * (max_pending - workers))
        def submit(pool):
            nonlocal exhausted
            if exhausted:
                return
            try:
                index, value = next(iterator)
            except StopIteration:
                exhausted = True
                return
            results.append(None)
            pending[pool.submit(function, value)] = (pool, index)
        for pool in slots:
            submit(pool)
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                pool, index = pending.pop(future)
                results[index] = future.result()
                submit(pool)
        return results
    finally:
        for future in pending:
            future.cancel()
        for pool, _ in pools:
            pool.shutdown(wait=True, cancel_futures=True)
