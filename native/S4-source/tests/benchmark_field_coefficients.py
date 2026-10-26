"""Native microbenchmarks / original-binary snapshots.

Select the extension through PYTHONPATH and S4_TEST_DLL_DIR before invoking.
Runs short representative workloads, never the full 30,001-volume scan.
"""
import argparse
import json
from pathlib import Path
import statistics
import time
import os
import numpy as np

from test_field_coefficients import simulation, coefficients, reconstructed, S4


def snapshot(output):
    saved = {}
    errors = []
    depths = [-.09, .11, .27, .41]
    xy = [(-.31, .27), (.09, -.13), (.51, .33)]
    for basis in (32, 64, 128):
        for case, kwargs in enumerate(({}, {"tensor": True}, {"pattern": False}, {"skew": False, "loss": False})):
            sim = simulation(basis, **kwargs)
            for frequency in (1000/900, 1000/1050, 1000/1200):
                sim.SetFrequency(frequency)
                key = f"b{basis}_case{case}_f{frequency:.9f}"
                field = np.array([[np.concatenate(sim.GetFields(x, y, z)) for x, y in xy] for z in depths])
                saved[key+"_fields"] = field
                saved[key+"_flux"] = np.array([sim.GetPowerFlux("top", 0.), sim.GetPowerFlux("bottom", 0.)])
                if hasattr(sim, "GetFieldCoefficientsMany"):
                    actual = reconstructed(sim, depths, xy, frequency=frequency)
                    errors.append(float(np.max(np.abs(actual-field))))
                    np.testing.assert_allclose(actual, field, rtol=2e-11, atol=2e-12)
    np.savez(output, **saved)
    print(json.dumps({"module": S4.__file__, "snapshots": len(saved),
                      "coefficient_vs_scalar_max_abs": max(errors, default=None), "output": str(output)}))


def compare(first, second):
    a, b = np.load(first), np.load(second)
    assert set(a.files) == set(b.files)
    maximum = 0.
    normalized = 0.
    for key in a.files:
        error = float(np.max(np.abs(a[key]-b[key])))
        maximum = max(maximum, error)
        normalized = max(normalized, error/max(1., float(np.max(np.abs(a[key])))))
        np.testing.assert_allclose(a[key], b[key], rtol=5e-10, atol=5e-11)
    print(json.dumps({"snapshots": len(a.files), "max_abs_error": maximum,
                      "max_scaled_error": normalized, "status": "passed"}))


def benchmark(output):
    results = []
    for basis in (32, 64, 128):
        for disabled in (False, True):
            os.environ["S4_DISABLE_EPSILON_CACHE"] = "1" if disabled else "0"
            sim = simulation(basis, skew=False, loss=False)
            sim.GetPowerFlux("bottom", 0.)
            solve_times = []
            for frequency in np.linspace(1000/1050, 1000/1049.8, 21)[1:]:
                start = time.perf_counter()
                sim.SetFrequency(float(frequency))
                sim.GetPowerFlux("bottom", 0.)
                solve_times.append(time.perf_counter()-start)
            result = {"basis": basis, "retained_basis": len(sim.GetBasisSet()),
                      "epsilon_cache_disabled": disabled,
                      "solve_median_seconds": statistics.median(solve_times)}
            depths = np.linspace(.001, .349, 32).tolist()
            legacy = []
            native = []
            for iteration in range(8):
                start = time.perf_counter()
                for z in depths:
                    sim.GetFieldsOnGrid(z, (16, 16), "Array")
                legacy.append(time.perf_counter()-start)
                if hasattr(sim, "GetFieldCoefficientsMany"):
                    start = time.perf_counter()
                    coefficients(sim, depths)
                    native.append(time.perf_counter()-start)
            result["legacy_grid_32_planes_median_seconds"] = statistics.median(legacy)
            if native:
                result["native_coefficients_32_planes_median_seconds"] = statistics.median(native)
                result["cache_stats"] = sim.GetEpsilonCacheStats()
            results.append(result)
    Path(output).write_text(json.dumps({"module": S4.__file__, "results": results}, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["snapshot", "compare", "benchmark"])
    parser.add_argument("output")
    parser.add_argument("other", nargs="?")
    args = parser.parse_args()
    if args.mode == "snapshot":
        snapshot(args.output)
    elif args.mode == "compare":
        compare(args.output, args.other)
    else:
        benchmark(args.output)
