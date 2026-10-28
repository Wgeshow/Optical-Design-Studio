"""Thermal draft persistence; hidden Qt widgets, no solver or native UI run."""
import copy
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from device_model import default_device
from qt_core import ProjectStore
from qt_thermal_setup import ThermalSetupWorkspace

APP = QApplication.instance() or QApplication([])


class ThermalAssignmentPreservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ods-thermal-drafts-", dir=os.environ.get("ODS_TEST_TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(DataLibrary(Path(self.temp.name) / "library"), restore=False)
        self.store.activate_study("thermal")
        device = default_device(self.store.electrical_materials)
        device["layers"] = [device["layers"][0], device["layers"][-1]]
        device.update(contacts=[], shapes=[], doping_regions=[])
        self.store.set_device(device)
        self.original = copy.deepcopy(self.store.device)
        self.layer = self.original["layers"][-1]["id"]
        self.material = self.original["layers"][-1]["material_id"]
        self.pages = []
        self.page = self.new_page(self.store)
        self.set_values("0.00017", "45.25", "Authored thermal source")

    def new_page(self, store):
        page = ThermalSetupWorkspace(store, document_id="thermal")
        self.pages.append(page)
        return page

    def tearDown(self):
        from PyQt6 import sip
        for page in self.pages:
            page._save_timer.stop()
            sip.delete(page)
        APP.processEvents()

    def set_values(self, power, conductivity, source, page=None):
        page = page or self.page
        page.powers.item(page._layer_ids.index(self.layer), 1).setText(power)
        row = page._material_ids.index(self.material)
        page.conductivities.item(row, 1).setText(conductivity)
        page.conductivities.item(row, 2).setText(source)

    def values(self, page=None):
        page = page or self.page
        row = page._material_ids.index(self.material)
        return (page.powers.item(page._layer_ids.index(self.layer), 1).text(),
                page.conductivities.item(row, 1).text(),
                page.conductivities.item(row, 2).text())

    def enabled(self, enabled):
        device = copy.deepcopy(self.store.device)
        next(row for row in device["layers"] if row["id"] == self.layer)["enabled"] = enabled
        self.store.set_device(device)

    def test_disable_reenable_retains_power_conductivity_and_source(self):
        expected = self.values()
        self.enabled(False)
        self.assertNotIn(self.layer, self.page._layer_ids)
        self.assertNotIn(self.material, self.page._material_ids)
        self.enabled(True)
        self.assertEqual(self.values(), expected)

    def test_disabled_unfinished_inputs_survive_project_save_reopen(self):
        self.set_values("1e-", "4.", "unfinished source text")
        self.enabled(False)
        self.page.flush_draft()
        saved = self.store.portable_project()
        other = ProjectStore(DataLibrary(Path(self.temp.name) / "reopened"), restore=False)
        other.load_project(saved)
        reopened = self.new_page(other)
        device = copy.deepcopy(other.device)
        next(row for row in device["layers"] if row["id"] == self.layer)["enabled"] = True
        other.set_device(device)
        self.assertEqual(self.values(reopened), ("1e-", "4.", "unfinished source text"))

    def test_inactive_thermal_editor_ignores_other_study_geometry(self):
        self.page.flush_draft()
        original = copy.deepcopy(self.page.draft())
        self.store.activate_study("electrical")
        device = default_device(self.store.electrical_materials)
        device["layers"][0]["name"] = "Other study layer"
        self.store.set_device(device)
        self.assertEqual(self.page.draft(), original)
        self.store.activate_study("thermal")
        self.assertEqual(self.values(), ("0.00017", "45.25", "Authored thermal source"))

    def test_disabled_invalid_assignments_are_saved_but_not_dispatched(self):
        self.set_values("1e-", "unfinished", "draft source")
        self.enabled(False)
        for row in range(self.page.conductivities.rowCount()):
            self.page.conductivities.item(row, 1).setText("50")
            self.page.conductivities.item(row, 2).setText("Active material source")
        settings = self.page.options()["settings"]
        self.assertNotIn(self.layer, settings["power_by_layer_W"])
        self.assertNotIn(self.material, settings["conductivity"])
        self.assertEqual(self.page.draft()["power_drafts"][self.layer], "1e-")
        self.assertEqual(self.page.draft()["conductivity_drafts"][self.material],
                         ["unfinished", "draft source"])

    def test_old_draft_without_assignment_caches_is_migrated_from_rows(self):
        saved = copy.deepcopy(self.page.draft())
        saved.pop("power_drafts")
        saved.pop("conductivity_drafts")
        self.set_values("99", "99", "changed")
        self.page.restore_draft(saved)
        self.enabled(False)
        self.enabled(True)
        self.assertEqual(self.values(), ("0.00017", "45.25", "Authored thermal source"))

    def test_document_replacement_resets_hidden_assignment_caches(self):
        self.enabled(False)
        self.page.restore_draft(self.page._restored_document({}))
        self.page.sync_device()
        self.enabled(True)
        self.assertEqual(self.values(), ("0", "", ""))

    def test_geometry_remove_restore_retains_ids_but_new_id_gets_new_power(self):
        device = copy.deepcopy(self.store.device)
        removed = device["layers"].pop()
        self.store.set_device(device)
        device["layers"].append(removed)
        self.store.set_device(device)
        self.assertEqual(self.values(), ("0.00017", "45.25", "Authored thermal source"))
        device["layers"][-1]["id"] = "new_thermal_layer"
        self.store.set_device(device)
        row = self.page._layer_ids.index("new_thermal_layer")
        self.assertEqual(self.page.powers.item(row, 1).text(), "0")


if __name__ == "__main__":
    unittest.main()
