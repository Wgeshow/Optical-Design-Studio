"""Run: python -m unittest discover -s tests -v. Set S4_TEST_GPU=1 for GPU tests."""
import copy
import math
import multiprocessing as mp
import os
from pathlib import Path
import tempfile
import time
import unittest

from backend import Cancelled, build_simulation, execute
from model import DEFAULT_PERFORMANCE, MAT_COLS, LAYER_COLS, PAT_COLS, epsilon, numeric_rows, performance, prepare, sweep

MATERIALS = [
    dict(zip(MAT_COLS, ["Air", "constant_nk", 1, 0, "", "nm"])),
    dict(zip(MAT_COLS, ["Film", "constant_nk", 3.4, 0.015, "", "nm"])),
    dict(zip(MAT_COLS, ["Glass", "constant_nk", 1.5, 0, "", "nm"])),
]
LAYERS = [dict(zip(LAYER_COLS, r)) for r in [["Top", 0, "Air"], ["Device", .25, "Film"], ["Bottom", 0, "Glass"]]]
PATTERNS = [dict(zip(PAT_COLS, ["circle", "Device", "Air", 0, 0, .1, 0, 0]))]
SETTINGS = dict(ax_um=.77, ay_um=.77, NumG=17, mode="Wavelength sweep", wl_start_nm=1300,
                wl_stop_nm=1600, wl_step_nm=50, fixed_wl_nm=1550, theta_deg=0,
                phi_deg=0, angle_start=0, angle_stop=60, angle_step=10, polarization="p")


def sample(**settings):
    return prepare(MATERIALS, LAYERS, PATTERNS, [], dict(SETTINGS, **settings))


def run(model, **options):
    return execute(model, dict(DEFAULT_PERFORMANCE, workers=1, timeout_seconds=60, **options))


class InputTests(unittest.TestCase):
    def test_sweep_no_overshoot(self):
        self.assertEqual(sweep(0, 1, .3, "test"), [0, .3, .6, .8999999999999999])
        self.assertEqual(len(sweep(1515, 1555, .1, "test")), 401)
        for args in [(2, 1, 1), (0, 1, 0), (0, math.inf, 1)]:
            with self.assertRaises(ValueError):
                sweep(*args, "test")

    def test_budget(self):
        p = performance({"workers": 0, "threads": 2}, 100, 8)
        self.assertEqual(p["effective_workers"], 4)
        self.assertEqual(performance({"workers": 0}, 2, 8)["effective_workers"], 2)
        for values in ({"workers": 8, "threads": 2}, {"threads": 0}, {"gpu_block": 65},
                       {"gpu_device": -1}, {"gpu_min_n": 0}, {"require_gpu": True}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                performance(values, 10, 8)
        p = performance({"mode": "GPU-assisted (one worker)", "workers": 8}, 100, 8)
        self.assertEqual(p["effective_workers"], 1)

    def test_table_units_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            nm, um = Path(directory)/"nm.csv", Path(directory)/"um.csv"
            nm.write_text("wavelength,n,k\n1000,2,0.1\n1500,3,0.2\n", encoding="utf-8")
            um.write_text("wavelength,n,k\n1,2,0.1\n1.5,3,0.2\n", encoding="utf-8")
            table = numeric_rows(nm, "nm")
            self.assertEqual(table, numeric_rows(um, "um"))
            material = dict(model="table_nk", a=1, b=0, table=table, grid=[r[0] for r in table])
            self.assertAlmostEqual(epsilon(material, 1250), complex(2.5, .15)**2)
            for data in ("1000,2,0\n1000,3,0", "1000,2,0\n1500,3", "1000,2,0\n1500,nan,0"):
                nm.write_text(data, encoding="utf-8")
                with self.assertRaises(ValueError):
                    numeric_rows(nm, "nm")

    def test_shape_units(self):
        class Fake:
            def __init__(self):
                self.regions = []
            def New(self, **kw):
                return self
            def SetMaterial(self, **kw):
                pass
            def AddLayer(self, **kw):
                pass
            def SetRegionRectangle(self, **kw):
                self.regions.append(kw)
            SetRegionEllipse = SetRegionRectangle
            SetRegionCircle = SetRegionRectangle
        model = sample()
        circle = model["patterns"][0]
        model["patterns"] = [circle, dict(circle, shape="rectangle", sx=.2, sy=.4, angle=30),
                            dict(circle, shape="ellipse", sx=.1, sy=.2, angle=45)]
        fake = Fake()
        build_simulation(fake, model, 1500)
        self.assertEqual(fake.regions[0]["Radius"], .1)
        self.assertEqual(fake.regions[1]["Halfwidths"], (.1, .2))
        self.assertEqual(fake.regions[1]["Angle"], 30)
        self.assertEqual(fake.regions[2]["Halfwidths"], (.1, .2))

    def test_missing_upload_rejected(self):
        materials = copy.deepcopy(MATERIALS)
        materials[1].update(Model="table_nk", DataFile="missing.csv")
        with self.assertRaisesRegex(ValueError, "upload"):
            prepare(materials, LAYERS, PATTERNS, [], SETTINGS)


class NativeTests(unittest.TestCase):
    def assert_rows_close(self, actual, expected, tolerance=1e-9):
        self.assertEqual(len(actual), len(expected))
        for a, b in zip(actual, expected):
            self.assertEqual(a[:3], b[:3])
            for x, y in zip(a[3:], b[3:]):
                self.assertAlmostEqual(x, y, delta=tolerance)

    def tearDown(self):
        self.assertEqual(mp.active_children(), [], "worker processes leaked")

    def test_fresnel_and_brewster(self):
        model = sample()
        model["patterns"] = []
        model["layers"][1]["material"] = "Glass"
        rows, _ = run(model)
        for row in rows:
            self.assertAlmostEqual(row[3], .04, delta=1e-12)
            self.assertAlmostEqual(row[4], .96, delta=1e-12)
        model["points"] = [[0, 1550, math.degrees(math.atan(1.5))]]
        rows, _ = run(model)
        self.assertLess(rows[0][3], 1e-12)
        self.assertAlmostEqual(rows[0][4], 1, delta=1e-12)

    def test_serial_parallel_and_threads(self):
        model = sample()
        baseline, _ = run(model)
        parallel, info = execute(model, dict(DEFAULT_PERFORMANCE, workers=min(4, os.cpu_count()), chunk_size=1))
        self.assert_rows_close(parallel, baseline)
        self.assertEqual(len(info["workers"]), min(4, os.cpu_count()))
        threaded, _ = run(model, threads=min(2, os.cpu_count()))
        self.assert_rows_close(threaded, baseline)
        self.assertGreater(max(row[3] for row in baseline)-min(row[3] for row in baseline), .01)

    def test_angle_parallel(self):
        model = sample(mode="Angle sweep")
        baseline, _ = run(model)
        parallel, _ = execute(model, dict(DEFAULT_PERFORMANCE, workers=min(3, os.cpu_count()), chunk_size=1))
        self.assert_rows_close(parallel, baseline)

    def test_dispersive_incident_medium_reused_vs_fresh(self):
        model = sample(theta_deg=23, wl_step_nm=150)
        model["materials"][0].update(model="table_nk", table=[[1300, 1, 0], [1600, 1.2, 0]], grid=[1300, 1600])
        reused, _ = run(model)
        fresh = []
        for point in model["points"]:
            rows, _ = run(dict(model, points=[point]))
            fresh.extend(rows)
        self.assert_rows_close(reused, fresh)

    def test_reused_vs_fresh_dispersive_shapes(self):
        for shape in ("circle", "ellipse", "rectangle"):
            model = sample(wl_start_nm=1300, wl_stop_nm=1600, wl_step_nm=150)
            model["patterns"][0].update(shape=shape, sy=.07, angle=27)
            mat = model["materials"][1]
            mat.update(model="table_nk", table=[[1300, 2.9, .02], [1600, 3.6, .04]], grid=[1300, 1600])
            reused, _ = run(model, chunk_size=3)
            fresh = []
            for point in model["points"]:
                single = dict(model, points=[point])
                rows, _ = run(single)
                fresh.extend(rows)
            self.assert_rows_close(reused, fresh)
            self.assertTrue(all(row[5] > 0 for row in reused))

    def test_cancel_and_timeout_cleanup(self):
        model = sample(NumG=101, wl_start_nm=1200, wl_stop_nm=1600, wl_step_nm=1)
        started = time.monotonic()
        with self.assertRaises(Cancelled):
            execute(model, dict(DEFAULT_PERFORMANCE, workers=2), cancelled=lambda: time.monotonic()-started > .5)
        self.assertLess(time.monotonic()-started, 8)
        with self.assertRaises(TimeoutError):
            execute(model, dict(DEFAULT_PERFORMANCE, workers=2, timeout_seconds=1))

    def test_native_error_cleanup(self):
        model = sample()
        model["layers"][1]["material"] = "NoSuchMaterial"
        with self.assertRaises(RuntimeError):
            run(model)

    @unittest.skipUnless(os.environ.get("S4_TEST_GPU") == "1", "opt-in GPU test")
    def test_hybrid_matches_cpu_and_offloads(self):
        model = sample(NumG=33)
        cpu, _ = run(model)
        gpu, info = execute(model, dict(DEFAULT_PERFORMANCE, mode="CPU + GPU", workers=min(3, os.cpu_count()),
                                       chunk_size=1, gpu_min_n=1, require_gpu=True))
        self.assert_rows_close(gpu, cpu, tolerance=1e-8)
        self.assertGreater(info["gpu_gemm_calls"], 0)
        self.assertEqual(info["gpu_failures"], 0)
        self.assertEqual(sum(worker["gpu"] for worker in info["workers"]), 1)
        print("GPU verification:", info["gpu_gemm_calls"], "products;", info["statuses"], flush=True)


if __name__ == "__main__":
    mp.freeze_support()
    unittest.main()
