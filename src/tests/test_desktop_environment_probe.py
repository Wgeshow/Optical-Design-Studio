"""The desktop probe must never read or modify the real user profile."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import desktop_environment_probe as probe


class ProbeIsolationTests(unittest.TestCase):
    def exercise(self, *, fail, existing):
        with tempfile.TemporaryDirectory(prefix='desktop-probe-test-', dir=Path.cwd()) as root:
            observed = {}
            expected = dict(LOCALAPPDATA=str(Path(root)/'real-profile'),
                            S4_LIBRARY_ROOT=str(Path(root)/'real-library'),
                            QT_QPA_PLATFORM='windows') if existing else {}
            def inspect():
                observed.update({name: os.environ[name] for name in
                                 ('LOCALAPPDATA', 'S4_LIBRARY_ROOT', 'QT_QPA_PLATFORM')})
                library = Path(observed['S4_LIBRARY_ROOT'])
                profile = Path(observed['LOCALAPPDATA'])
                self.assertEqual(library.parent, Path(root)/'.startup-checks')
                self.assertTrue(library.is_dir())
                self.assertTrue(profile.is_dir())
                self.assertTrue(profile.is_relative_to(library))
                self.assertEqual(observed['QT_QPA_PLATFORM'], 'offscreen')
                self.assertNotEqual(str(library), expected.get('S4_LIBRARY_ROOT'))
                self.assertNotEqual(str(profile), expected.get('LOCALAPPDATA'))
                # Represent writes by module initialization. They must remain
                # inside the disposable profile even when initialization fails.
                (profile/'probe-only.txt').write_text('isolated', encoding='utf-8')
                if fail:
                    raise RuntimeError('initialization failed')
                return {'desktop_constructed': True}
            with patch.dict(os.environ, expected, clear=True), \
                    patch.object(probe.sys, 'prefix', root), \
                    patch.object(probe, '_check', side_effect=inspect) as inner:
                if fail:
                    with self.assertRaisesRegex(RuntimeError, 'initialization failed'):
                        probe.check()
                else:
                    self.assertEqual(probe.check(), {'desktop_constructed': True})
                inner.assert_called_once_with()
                self.assertEqual(dict(os.environ), expected)
                self.assertFalse(Path(observed['S4_LIBRARY_ROOT']).exists())

    def test_profile_is_overridden_before_probe_and_restored_after_success(self):
        self.exercise(fail=False, existing=True)

    def test_profile_is_restored_and_scratch_removed_after_failure(self):
        self.exercise(fail=True, existing=True)

    def test_absent_environment_values_remain_absent_after_probe(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                self.exercise(fail=fail, existing=False)


if __name__ == '__main__':
    unittest.main()
