import time
import unittest
from unittest.mock import patch
import backend
from model import DEFAULT_PERFORMANCE, performance
from tests.test_backend import sample


class UnlimitedSimulationTests(unittest.TestCase):
    def test_saved_positive_limit_migrates_to_unlimited(self):
        self.assertEqual(performance(dict(timeout_seconds=1), 1, 8)['timeout_seconds'], 0)
        self.assertEqual(DEFAULT_PERFORMANCE['timeout_seconds'], 0)

    def test_native_run_finishes_after_saved_limit(self):
        original_wait = backend.wait
        delayed = False
        def wait(connections, timeout):
            nonlocal delayed
            if not delayed:
                delayed = True
                time.sleep(1.2)
                return []
            return original_wait(connections, timeout=timeout)
        model = sample(NumG=9, wl_start_nm=1500, wl_stop_nm=1500)
        with patch.object(backend, 'wait', wait):
            rows, _ = backend.execute(model, dict(DEFAULT_PERFORMANCE, workers=1, timeout_seconds=1))
        self.assertTrue(delayed)
        self.assertEqual(len(rows), len(model['points']))


if __name__ == '__main__':
    unittest.main()
