"""Sesame physical imports preserve editable installation state; no workers."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_sesame_setup import SesameSetupWorkspace

APP = QApplication.instance() or QApplication([])


class SesameRuntimeImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sesame-import-", dir=os.environ.get("ODS_TEST_TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        self.pages = []
        self.page = self.new_page("first")
        self.settings = json.loads((Path(__file__).resolve().parents[1] /
            "benchmark_data/sesame_1d_heterojunction/case.json").read_text(encoding="utf-8"))["options"]["settings"]
        self.runtime = dict(mode="wsl", executable="/opt/ods/bin/python", distro="Test-Distribution",
                            module_paths=["/opt/ods/packages", "/home/test/extra"],
                            library_paths=["/opt/ods/lib", "/home/test/native"], timeout_s=4321.)
        self.apply_runtime(self.page, self.runtime)

    def new_page(self, suffix):
        store = ProjectStore(DataLibrary(Path(self.temp.name) / suffix), restore=False)
        store.activate_study("sesame_transport")
        page = SesameSetupWorkspace(store, document_id="sesame_transport")
        self.pages.append(page)
        return page

    def tearDown(self):
        from PyQt6 import sip
        for page in self.pages:
            page._save_timer.stop()
            sip.delete(page)
        APP.processEvents()

    @staticmethod
    def apply_runtime(page, runtime):
        from PyQt6.QtWidgets import QComboBox
        for key, value in runtime.items():
            control = page.fields["runtime." + key]
            if isinstance(control, QComboBox):
                control.setCurrentIndex(control.findData(value))
            else:
                control.setText("; ".join(value) if isinstance(value, list) else str(value))

    def test_physical_only_import_preserves_complete_current_runtime(self):
        original = copy.deepcopy(self.settings)
        self.page.load_settings(self.settings)
        self.assertEqual(self.page.runtime_settings(), self.runtime)
        self.assertEqual(self.page.options()["settings"]["runtime"], self.runtime)
        self.assertEqual(self.settings, original)

    def test_explicit_imported_runtime_wins_and_roundtrips_library_paths(self):
        incoming = dict(self.settings, runtime=dict(mode="local", executable="C:/managed/python.exe",
            distro="Ubuntu", module_paths=["C:/managed/site"], library_paths=["C:/managed/dll"], timeout_s=123.))
        self.page.load_settings(incoming)
        self.assertEqual(self.page.runtime_settings(), incoming["runtime"])
        draft = copy.deepcopy(self.page.draft())
        self.page.library_paths.setText("changed")
        self.page.restore_draft(draft)
        self.assertEqual(self.page.options()["settings"]["runtime"], incoming["runtime"])

    def test_partial_explicit_runtime_uses_fresh_defaults_for_unspecified_fields(self):
        self.page.load_settings(dict(self.settings, runtime=dict(executable="C:/specified/python.exe")))
        runtime = self.page.runtime_settings()
        self.assertEqual(runtime["mode"], "local")
        self.assertEqual(runtime["executable"], "C:/specified/python.exe")
        self.assertEqual(runtime["module_paths"], [])
        self.assertEqual(runtime["library_paths"], [])
        self.assertEqual(runtime["timeout_s"], 86400.)

    def test_fresh_page_does_not_inherit_another_pages_runtime(self):
        fresh = self.new_page("fresh")
        fresh.load_settings(self.settings)
        runtime = fresh.runtime_settings()
        self.assertEqual(runtime["mode"], "local")
        self.assertEqual(runtime["executable"], sys.executable)
        self.assertEqual(runtime["module_paths"], [])
        self.assertEqual(runtime["library_paths"], [])

    def test_physical_only_import_preserves_unfinished_raw_runtime_fields(self):
        self.page.timeout.setText("1e-")
        self.page.library_paths.setText(" /opt/lib ; /home/native ")
        before = {key: value for key, value in self.page.draft()["fields"].items() if key.startswith("runtime.")}
        self.page.load_settings(self.settings)
        after = {key: value for key, value in self.page.draft()["fields"].items() if key.startswith("runtime.")}
        self.assertEqual(after, before)
        with self.assertRaises(ValueError):
            self.page.options()

    def test_automatic_setup_applies_native_library_paths_without_starting_probe(self):
        with patch.object(self.page, "remember_runtime") as remember, patch.object(self.page.runtime_check, "check") as check:
            self.page._apply_automatic_runtime(self.runtime)
        self.assertEqual(self.page.runtime_settings(), self.runtime)
        remember.assert_called_once()
        check.assert_called_once()
        self.assertIn("Shared-library", self.page.library_paths.accessibleName())

    def test_nonobject_import_reports_error_without_mutating_current_draft(self):
        before = copy.deepcopy(self.page.draft())
        path = Path(self.temp.name) / "bad.json"
        path.write_text("[]", encoding="utf-8")
        with patch("qt_sesame_setup.QFileDialog.getOpenFileName", return_value=(str(path), "JSON")):
            self.page.import_settings()
        self.assertIn("JSON object", self.page.status.text())
        self.assertEqual(self.page.draft(), before)

    def test_invalid_explicit_runtime_is_rejected_before_replacing_physics(self):
        self.page.load_settings(self.settings)
        before = copy.deepcopy(self.page.draft())
        with self.assertRaises(ValueError):
            self.page.load_settings(dict(self.settings, runtime=dict(mode="wsl", executable="relative/python")))
        self.assertEqual(self.page.draft(), before)


if __name__ == "__main__":
    unittest.main()
