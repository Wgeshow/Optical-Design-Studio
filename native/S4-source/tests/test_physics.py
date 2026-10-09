"""Numerical regression tests; set PYTHONPATH to the desired build directory."""
import cmath
import gc
import os
import unittest
from s4_runtime import configure
configure(threads=1, gpu=os.environ.get('S4_GPU') == '1',
          gpu_min_n=int(os.environ.get('S4_GPU_MIN_N', '1024')))
import S4

def model(pattern=True, epsilon=12.0):
    s = S4.New(Lattice=((1.0,0.0),(0.0,1.0)), NumBasis=25)
    s.SetMaterial('Air', 1.0)
    s.SetMaterial('Film', epsilon)
    s.AddLayer('Top',0.0,'Air')
    s.AddLayer('Slab',0.5,'Film')
    if pattern:
        s.SetRegionCircle('Slab','Air',(0.0,0.0),0.2)
    s.AddLayer('Bottom',0.0,'Air')
    s.SetExcitationPlanewave((0.0,0.0),1.0,0.0)
    return s

def rt(s, frequency):
    s.SetFrequency(frequency)
    f,b = s.GetPowerFlux('Top')
    t,_ = s.GetPowerFlux('Bottom')
    return -b.real/f.real, t.real/f.real

class PhysicsTests(unittest.TestCase):
    def assert_pair(self, a, b):
        for x,y in zip(a,b):
            self.assertAlmostEqual(x,y,places=9)

    def test_uniform_film_fresnel(self):
        s = model(False, 4.0)
        frequency = 0.31
        r,t = rt(s,frequency)
        phase = cmath.exp(2j * (2*cmath.pi*frequency*2.0*0.5))
        reflection = (-1/3 + (1/3)*phase) / (1-(1/9)*phase)
        self.assertAlmostEqual(r, abs(reflection)**2, places=10)
        self.assertAlmostEqual(r+t,1.0,places=10)

    def test_pattern_energy_and_frequency_cache(self):
        s = model()
        for f in (0.27,0.32,0.39):
            result = rt(s,f)
            self.assertAlmostEqual(sum(result),1.0,places=9)
            self.assert_pair(result,rt(model(),f))

    def test_material_invalidation(self):
        s = model(False,4.0)
        rt(s,0.31)
        s.SetMaterial('Film',9.0)
        # Query immediately, without SetFrequency masking a stale material cache.
        a,b = s.GetPowerFlux('Top')
        t,_ = s.GetPowerFlux('Bottom')
        self.assert_pair((-b.real/a.real,t.real/a.real),rt(model(False,9.0),0.31))

    def test_clone_independence(self):
        s = model()
        expected = rt(s,0.33)
        clone = s.Clone()
        self.assert_pair(rt(clone,0.33),expected)
        clone.SetMaterial('Film',5.0)
        del clone
        gc.collect()
        self.assert_pair(rt(s,0.33),expected)

    def test_legacy_stub_is_not_silent(self):
        with self.assertRaises(NotImplementedError):
            S4.SolveInParallel('Bottom', [])

if __name__ == '__main__':
    unittest.main(exit=False)
    print(S4.AccelerationInfo(), flush=True)
