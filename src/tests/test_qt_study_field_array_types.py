"""Friendly transport arrays keep typed solver values; no solver execution."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from qt_research_studies import StructuredValueEditor
from qt_study_fields import NamedPropertyForm

APP = QApplication.instance() or QApplication([])


class StudyFieldArrayTypeTests(unittest.TestCase):
    def setUp(self):
        self.widgets = []

    def tearDown(self):
        from PyQt6 import sip
        for widget in reversed(self.widgets):
            if not sip.isdeleted(widget):
                if hasattr(widget, "_save_timer"):
                    widget._save_timer.stop()
                sip.delete(widget)
        APP.processEvents()

    def form(self, value, field="values", **kwargs):
        editor = StructuredValueEditor(value, field)
        form = NamedPropertyForm(editor, **kwargs)
        self.widgets.extend([editor, form])
        return editor, form

    @staticmethod
    def type_value(form, key, text):
        control = form._fields[key]
        control.setText(text)
        control.textEdited.emit(text)

    def test_existing_text_array_adds_text_not_number(self):
        editor, form = self.form(["GaAs"])
        form.add_value.click()
        self.type_value(form, "1", "AlGaAs")
        self.assertEqual(editor.value(), ["GaAs", "AlGaAs"])
        self.assertEqual(editor.tree.topLevelItem(0).child(1).data(0, Qt.ItemDataRole.UserRole), "text")

    def test_empty_material_id_list_is_text_and_remains_text_after_remove_all(self):
        editor, form = self.form({"materials": []}, array_types={"materials": "text"})
        form.navigator.setCurrentItem(form._nodes[("materials",)][0])
        form.add_value.click()
        self.type_value(form, "0", "gaas")
        self.assertEqual(editor.value()["materials"], ["gaas"])
        form.remove_value.click()
        form.add_value.click()
        self.type_value(form, "0", "algaas")
        self.assertEqual(editor.value()["materials"], ["algaas"])

    def test_numeric_array_addition_retains_blank_then_unfinished_numeric_draft(self):
        editor, form = self.form([0.45], field="hole_mass_ratios")
        form.add_value.click()
        self.assertEqual(editor.draft()["children"][1]["value"], "")
        self.type_value(form, "1", "1e-")
        self.assertEqual(editor.draft()["children"][1]["value"], "1e-")
        with self.assertRaises(ValueError):
            editor.value()
        self.type_value(form, "1", "0.084")
        self.assertEqual(editor.value(), [0.45, 0.084])

    def test_boolean_array_addition_keeps_boolean_type(self):
        editor, form = self.form([True])
        form.add_value.click()
        self.assertEqual(editor.value(), [True, False])
        form._fields["1"].setCurrentText("true")
        self.assertEqual(editor.value(), [True, True])

    def test_empty_object_array_never_adds_an_invalid_scalar(self):
        editor, form = self.form([], field="samples", root_array_type="object")
        self.assertTrue(form.add_value.isHidden())
        form._add_value()
        self.assertEqual(editor.value(), [])

    def test_nullable_thermal_numbers_assign_clear_and_preserve_unfinished_input(self):
        editor, form = self.form({"temperature_limit_K": None, "void_conductivity_W_mK": None},
            field="thermal", nullable_numbers=("temperature_limit_K", "void_conductivity_W_mK"))
        self.assertTrue(form._fields["temperature_limit_K"].isEnabled())
        self.type_value(form, "temperature_limit_K", "310")
        self.assertEqual(editor.value()["temperature_limit_K"], 310.)
        self.type_value(form, "void_conductivity_W_mK", "0.026")
        self.assertEqual(editor.value()["void_conductivity_W_mK"], .026)
        self.type_value(form, "temperature_limit_K", "")
        self.assertIsNone(editor.value()["temperature_limit_K"])
        self.type_value(form, "temperature_limit_K", "1e-")
        with self.assertRaises(ValueError):
            editor.value()
        self.assertEqual(editor.draft()["children"][0]["value"], "1e-")

    def test_unknown_null_does_not_offer_an_editor_that_silently_ignores_typing(self):
        editor, form = self.form({"unknown_property": None})
        self.assertFalse(form._fields["unknown_property"].isEnabled())
        self.assertIn("Advanced properties", form._fields["unknown_property"].placeholderText())
        self.assertIsNone(editor.value()["unknown_property"])

    def test_deleted_object_diagnostic_does_not_reuse_prior_field(self):
        editor, form = self.form([{"id": "remaining", "field_V_m": 2.}],
                                 field="samples", root_array_type="object")
        with patch("qt_input_diagnostics.reveal_and_focus", return_value=True), patch("qt_study_fields.reveal_and_focus", return_value=True):
            self.assertTrue(form.open_field("samples.0.field_V_m", "remaining"))
            self.assertEqual(editor.tree.currentItem().text(0), "field_V_m")
            self.assertFalse(form.open_field("samples.0.field_V_m", "removed"))
        self.assertIsNone(editor.tree.currentItem())
        self.assertEqual(editor.value(), [{"id": "remaining", "field_V_m": 2.}])

    def test_hidden_raw_tree_does_not_block_valid_friendly_diagnostic(self):
        editor, form = self.form({"contact_a": {"source": "authored"}}, field="contacts")
        with patch("qt_input_diagnostics.reveal_and_focus", return_value=False), patch("qt_study_fields.reveal_and_focus", return_value=True):
            self.assertTrue(form.open_field("contacts.contact_a.source", "contact_a"))
        self.assertEqual(editor.tree.currentItem().text(0), "source")
        self.assertEqual(form._fields["source"].text(), "authored")

    def test_full_transport_interface_template_preserves_material_ids(self):
        from data_library import DataLibrary
        from qt_core import ProjectStore
        from qt_transport_research_setup import TransportResearchWorkspace
        from research_catalog import list_capabilities
        with tempfile.TemporaryDirectory(prefix="transport-array-", dir=os.environ.get("ODS_TEST_TMPDIR")) as folder:
            store = ProjectStore(DataLibrary(Path(folder) / "library"), restore=False)
            store.activate_study("advanced_transport")
            from device_model import default_device
            store.set_device(default_device(store.electrical_materials))
            cap = next(item for item in list_capabilities() if item["engine"] == "advanced_transport")
            page = TransportResearchWorkspace(store, cap, document_id="advanced_transport")
            self.widgets.append(page)
            page.create_model_fields("interfaces")
            form = page.input_forms["interfaces"]
            form.navigator.setCurrentItem(form._nodes[("0", "materials")][0])
            for key, text in [("0", "gaas"), ("1", "algaas")]:
                form.add_value.click()
                self.type_value(form, key, text)
            raw = page.structured["interfaces"].draft()
            materials = next(child for child in raw["children"][0]["children"] if child["name"] == "materials")
            self.assertEqual([child["type"] for child in materials["children"]], ["text", "text"])
            self.assertEqual([child["value"] for child in materials["children"]], ["gaas", "algaas"])
            saved = copy.deepcopy(page.draft())
            page.restore_draft(saved)
            self.assertEqual(page.structured["interfaces"].draft(), raw)
            # Complete the remaining authored inputs and inspect the actual
            # job request, without invoking prepare, a worker or a solver.
            page.fields["swept_contact_id"].setText(store.device["contacts"][0]["id"])
            page.fields["parameter_source"].setText("Explicit interface test")
            page.structured["biases_V"].set_value([0., 0.001])
            interface = page.structured["interfaces"].tree.topLevelItem(0).child(0)
            for index in range(interface.childCount()):
                item = interface.child(index)
                if item.text(0) == "source":
                    item.setText(1, "Authored interface coefficient")
                elif item.text(0).endswith("resistivity_ohm_cm2"):
                    item.setText(1, "2e-6")
            requested = page.options()["settings"]["interfaces"][0]
            self.assertEqual(requested["materials"], ["gaas", "algaas"])
            self.assertEqual(requested["electron_resistivity_ohm_cm2"], 2e-6)
            page.create_model_fields("thermal")
            thermal_root = page.structured["thermal"].tree.topLevelItem(0)
            for index in range(thermal_root.childCount()):
                item = thermal_root.child(index)
                if item.text(0) in ("temperature_limit_K", "void_conductivity_W_mK"):
                    self.assertEqual(item.data(0, Qt.ItemDataRole.UserRole), "null")
            thermal_form = page.input_forms["thermal"]
            thermal_form.navigator.setCurrentItem(thermal_form._nodes[()][0])
            self.type_value(thermal_form, "temperature_limit_K", "310")
            limit = next(thermal_root.child(i) for i in range(thermal_root.childCount()) if thermal_root.child(i).text(0) == "temperature_limit_K")
            self.assertEqual(limit.data(0, Qt.ItemDataRole.UserRole), "number")
            self.assertEqual(limit.text(1), "310")
            page._save_timer.stop()

    def test_high_field_uses_object_add_action_for_empty_states(self):
        from data_library import DataLibrary
        from qt_core import ProjectStore
        from qt_transport_research_setup import HighFieldOpticsWorkspace
        from research_catalog import list_capabilities
        with tempfile.TemporaryDirectory(prefix="highfield-array-", dir=os.environ.get("ODS_TEST_TMPDIR")) as folder:
            store = ProjectStore(DataLibrary(Path(folder) / "library"), restore=False)
            store.activate_study("high_field_optics")
            cap = next(item for item in list_capabilities() if item["engine"] == "high_field_optics")
            page = HighFieldOpticsWorkspace(store, cap, document_id="high_field_optics")
            self.widgets.append(page)
            form = page.input_forms["samples"]
            self.assertTrue(form.add_value.isHidden())
            page.add_sample()
            root = page.structured["samples"].tree.topLevelItem(0)
            self.assertEqual(root.childCount(), 1)
            self.assertEqual(root.child(0).data(0, Qt.ItemDataRole.UserRole), "object")
            self.assertIn("field_V_m", form._fields)
            page._save_timer.stop()


if __name__ == "__main__":
    unittest.main()
