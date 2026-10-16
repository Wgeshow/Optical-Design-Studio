"""Installation checks use isolated arguments and reject stale process results."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QProcess
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from qt_research_runtime import (ResearchRuntimeCheck, load_saved_runtime,
                                 probe_command, remember_runtime, runtime_key)

APP = QApplication.instance() or QApplication([])


class ResearchRuntimeTests(unittest.TestCase):
    def widget(self, request=None):
        widget = ResearchRuntimeCheck(lambda: request or dict(engine='sesame_transport', runtime=dict(executable=sys.executable)))
        def cleanup():
            widget.cancel()
            if widget.process.state() != QProcess.ProcessState.NotRunning:
                widget.process.waitForFinished(3000)
            widget.deleteLater()
        self.addCleanup(cleanup)
        return widget

    def wait(self, widget):
        for _ in range(250):
            QTest.qWait(20)
            if not widget._running and widget.process.state() == QProcess.ProcessState.NotRunning:
                return
        self.fail('Runtime check did not finish.')

    def test_explicit_interpreter_required_and_packaged_application_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Python executable'):
            probe_command(dict(engine='sesame_transport', runtime={}))
        with patch.object(sys, 'frozen', True, create=True):
            with self.assertRaisesRegex(ValueError, 'not a Python interpreter'):
                probe_command(dict(engine='sesame_transport', runtime=dict(executable=sys.executable)))

    def test_wsl_paths_are_arguments_and_engine_code_is_fixed(self):
        runtime = dict(mode='wsl', distro='Physics Test', executable='/opt/my env/python',
            module_paths=["/opt/a 'quoted' folder;$(cmd)"], library_paths=['/opt/native libs'])
        command, validated, label, marker = probe_command(dict(engine='pcsel', settings=dict(model='gme', runtime=runtime)))
        self.assertEqual(command[:6], ['wsl.exe', '--distribution', 'Physics Test', '--exec', 'env', 'LD_LIBRARY_PATH=/opt/native libs'])
        self.assertEqual(command[6:8], ['/opt/my env/python', '-c'])
        self.assertNotIn(runtime['module_paths'][0], command[-2])
        self.assertEqual(json.loads(command[-1]), validated)
        self.assertIn('GuidedModeExp', command[-2])
        self.assertEqual((label, marker), ('Legume', 'ODS_RESEARCH_READY_LEGUME'))
        compile(command[-2], '<fixed probe>', 'exec')

    def test_actual_child_imports_required_api_and_publishes_readiness(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            Path(directory, 'sesame.py').write_text("Builder = solve = IVcurve = Analyzer = object\n__version__='test API'\n", encoding='utf-8')
            request = dict(engine='sesame_transport', runtime=dict(executable=sys.executable, module_paths=[directory]))
            widget = self.widget(request)
            changes = []
            widget.readinessChanged.connect(changes.append)
            widget.check()
            self.wait(widget)
            self.assertTrue(widget.ready, widget.details.toPlainText())
            self.assertEqual(widget.status.text(), 'Sesame is available.')
            self.assertIn('test API', widget.details.toPlainText())
            widget.invalidate()
            self.assertFalse(widget.ready)
            self.assertEqual(changes, [True, False])

    def test_importable_wrong_package_is_not_available(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            Path(directory, 'legume.py').write_text('__version__="wrong package"\n', encoding='utf-8')
            widget = self.widget(dict(engine='pcsel', model='gme', runtime=dict(executable=sys.executable, module_paths=[directory])))
            widget.check()
            self.wait(widget)
            self.assertFalse(widget.ready)
            self.assertIn('Could not verify Legume', widget.status.text())
            self.assertIn('ImportError', widget.details.toPlainText())

    def test_gmsh_probe_initializes_native_library(self):
        command, _, label, _ = probe_command(dict(engine='pcsel_transport', runtime=dict(executable=sys.executable)))
        self.assertEqual(label, 'Gmsh')
        self.assertIn('gmsh.initialize()', command[-2])
        self.assertIn('gmsh.finalize()', command[-2])
        compile(command[-2], '<gmsh probe>', 'exec')

    def test_cancelled_process_cannot_publish_or_be_reused_early(self):
        widget = self.widget()
        probe = ([sys.executable, '-c', 'import time; time.sleep(10); print("ODS_RESEARCH_READY_SESAME old")'],
                 {'mode': 'local', 'executable': sys.executable}, 'Sesame', 'ODS_RESEARCH_READY_SESAME')
        with patch('qt_research_runtime.probe_command', return_value=probe) as mocked:
            widget.check()
            self.assertTrue(widget.process.waitForStarted(2000))
            widget.invalidate()
            widget.check()
            self.assertEqual(mocked.call_count, 1)
            self.assertFalse(widget.check_button.isEnabled())
            self.wait(widget)
        self.assertFalse(widget.ready)
        self.assertIn('changed', widget.status.text())
        probe[0][-1] = 'print("ODS_RESEARCH_READY_SESAME new")'
        with patch('qt_research_runtime.probe_command', return_value=probe):
            widget.check()
            self.wait(widget)
        self.assertTrue(widget.ready)
        self.assertIn('new', widget.details.toPlainText())

    def test_timeout_and_failed_start_remain_actionable_not_ready(self):
        widget = self.widget()
        probe = ([sys.executable, '-c', 'import time; time.sleep(10)'],
                 {'mode': 'local', 'executable': sys.executable}, 'Sesame', 'ODS_RESEARCH_READY_SESAME')
        with patch('qt_research_runtime.probe_command', return_value=probe):
            widget.timer.setInterval(50)
            widget.check()
            self.wait(widget)
        self.assertFalse(widget.ready)
        self.assertIn('timed out', widget.status.text())
        widget.get_settings = lambda: dict(engine='pcsel_transport', runtime=dict(executable='C:/missing-ods-qa-interpreter/python.exe'))
        widget.check()
        self.wait(widget)
        self.assertFalse(widget.ready)
        self.assertIn('could not start', widget.status.text())

    def test_native_engine_identity_does_not_claim_external_readiness(self):
        widget = self.widget(dict(engine='pcsel', model='rcwa_poles'))
        widget.check()
        self.assertIn('S4 resonance', widget.status.text())
        self.assertIn('included engine', widget.status.text())
        self.assertFalse(widget.ready)
        self.assertEqual(widget.process.state(), QProcess.ProcessState.NotRunning)

    def test_saved_runtime_is_explicit_namespaced_and_not_readiness(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory, patch.dict(os.environ, S4_LIBRARY_ROOT=directory):
            self.assertEqual(load_saved_runtime('sesame_transport'), {})
            runtime = dict(executable=sys.executable, module_paths=["C:/solver's modules"])
            expected = remember_runtime('pcsel', runtime, model='gme')
            self.assertEqual(load_saved_runtime('legume'), expected)
            self.assertEqual(runtime_key('pcsel_transport'), 'gmsh')
            self.assertEqual(load_saved_runtime('sesame_transport'), {})
            from qt_common import preferences
            settings = preferences()
            settings.setValue('research_runtime/sesame', '[]')
            settings.sync()
            self.assertEqual(load_saved_runtime('sesame_transport'), {})
            with self.assertRaises(ValueError):
                remember_runtime('pcsel_transport', {})


if __name__ == '__main__':
    unittest.main()
