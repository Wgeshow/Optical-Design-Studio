"""The native Qt build must start without the legacy Gradio dependency."""
from pathlib import Path
import subprocess
import sys
import unittest


class OptionalGradioTests(unittest.TestCase):
    def test_shared_app_core_imports_when_gradio_is_absent(self):
        root = Path(__file__).resolve().parents[1]
        code = (
            "import sys; sys.modules['gradio'] = None; import qt_app, app; "
            "assert app.gr.Request.__name__ == '_Request'"
        )
        result = subprocess.run(
            [sys.executable, '-c', code], cwd=root, text=True,
            capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
