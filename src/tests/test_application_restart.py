import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import application_restart as restart


class RestartTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.library = Path(self.temporary.name)

    def test_busy_prevents_save_and_plan(self):
        store = SimpleNamespace(busy=True, _autosave=Mock())
        with self.assertRaises(RuntimeError):
            restart.prepare_restart(self.library, store=store)
        store._autosave.assert_not_called()
        self.assertEqual(list(self.library.iterdir()), [])

    def test_plan_keeps_exact_executable_library_and_save(self):
        store = SimpleNamespace(busy=False, _autosave=Mock())
        plan = restart.prepare_restart(self.library, store=store)
        _, data = restart._read(plan)
        store._autosave.assert_called_once()
        self.assertEqual(Path(data['library']), self.library.resolve())
        self.assertEqual(Path(data['executable']), Path(restart.sys.executable).resolve())

    def test_rejects_arbitrary_executable(self):
        plan = restart.prepare_restart(self.library)
        data = json.loads(plan.read_text())
        data['executable'] = str(self.library/'untrusted.exe')
        plan.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            restart._read(plan)

    def test_launch_failure_does_not_exit_parent(self):
        plan = restart.prepare_restart(self.library)
        with patch.object(restart, '_spawn', side_effect=OSError('no helper')):
            with self.assertRaises(OSError):
                restart.launch_restart(plan)

    def test_startup_ack_uses_nonce_and_current_pid(self):
        plan = restart.prepare_restart(self.library)
        with patch.dict(os.environ, ODS_RESTART_PLAN=str(plan)):
            self.assertTrue(restart.acknowledge_restart())
        receipt = json.loads((plan.parent/'started.json').read_text())
        self.assertEqual(receipt['pid'], os.getpid())
        self.assertEqual(receipt['nonce'], plan.parent.name)

    def test_invalid_startup_environment_does_not_crash_gui(self):
        with patch.dict(os.environ, ODS_RESTART_PLAN=str(self.library/'missing.json')):
            self.assertFalse(restart.acknowledge_restart())
            self.assertNotIn('ODS_RESTART_PLAN', os.environ)

    def test_helper_waits_before_launch_and_requires_matching_ack(self):
        plan = restart.prepare_restart(self.library)
        data = json.loads(plan.read_text())
        data['parent_pid'] = os.getpid()+10000
        plan.write_text(json.dumps(data))
        calls = []
        def spawn(command, cwd, env):
            calls.append('launch')
            self.assertEqual(command[-2:], ['--library', str(self.library.resolve())])
            self.assertEqual(env['ODS_RESTART_PLAN'], str(plan))
            restart._write(plan.parent/'started.json', {'nonce': data['nonce'], 'pid': 1234})
            return SimpleNamespace(pid=1234, poll=lambda: None)
        with patch.object(restart, '_wait_parent', side_effect=lambda pid: calls.append('wait')), patch.object(restart, '_spawn', side_effect=spawn):
            self.assertEqual(restart.restart_helper_main(plan), 0)
        self.assertEqual(calls, ['wait', 'launch'])
        self.assertEqual(json.loads((plan.parent/'status.json').read_text())['state'], 'started')


if __name__ == '__main__':
    unittest.main()
