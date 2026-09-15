import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from s4_parallel import parallel_map
from s4_runtime import configure

def square(x):
    return x * x

def environment(x):
    return int(os.environ['S4_GPU']), os.environ['MKL_NUM_THREADS'], x

def raises(x):
    raise RuntimeError('worker failure')

class ParallelTests(unittest.TestCase):
    def test_order_and_generator(self):
        self.assertEqual(parallel_map(square, (i for i in range(15)), workers=2), [i*i for i in range(15)])

    def test_empty(self):
        self.assertEqual(parallel_map(square, [], workers=1), [])

    def test_hybrid_lanes(self):
        if (os.cpu_count() or 1) < 2:
            self.skipTest('requires two CPUs')
        result = parallel_map(environment, range(8), workers=2, gpu=True, max_pending=2)
        self.assertEqual({x[0] for x in result}, {0, 1})
        self.assertTrue(all(x[1] == '1' for x in result))
        self.assertEqual([x[2] for x in result], list(range(8)))

    def test_errors(self):
        with self.assertRaisesRegex(RuntimeError, 'worker failure'):
            parallel_map(raises, [0], workers=1)

    def test_limits(self):
        with self.assertRaises(ValueError):
            parallel_map(square, [1], workers=(os.cpu_count() or 1) + 1)
        with self.assertRaises(ValueError):
            parallel_map(square, [1], workers=1, max_pending=0)
        with self.assertRaises(ValueError):
            configure(threads=0)

if __name__ == '__main__':
    unittest.main()
