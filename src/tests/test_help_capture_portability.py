"""The bundled reproducibility helper resolves this application without a solver run."""
import os
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import patch


class HelpCapturePortabilityTests(unittest.TestCase):
    def test_original_and_bundled_helpers_locate_the_same_application(self):
        source=Path(__file__).resolve().parents[1]
        bundled=source/'help_assets'/'silicon-reference-run'/'run_and_capture.py'
        self.assertTrue(bundled.is_file(), 'The portable Help reproduction helper is required')
        original=source.parent/'ui_redesign_20261008'/'silicon-help-simulation'/'run_and_capture.py'
        helpers=(bundled, original) if original.is_file() else (bundled,)
        for helper in helpers:
            with self.subTest(helper=helper),patch.dict(os.environ),patch.object(sys,'path',list(sys.path)):
                with patch('subprocess.run',side_effect=AssertionError('Source discovery must not run a solver')):
                    resolved=runpy.run_path(str(helper),run_name='source_discovery_test')
                self.assertEqual(resolved['SOURCE'].resolve(),source)
                self.assertEqual(Path(os.environ['S4_LIBRARY_ROOT']),helper.parent/'isolated_library')
                self.assertTrue(callable(resolved['main']))


if __name__=='__main__':unittest.main()
