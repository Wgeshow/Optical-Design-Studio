import csv
import json
from pathlib import Path
import tempfile
import unittest

from comsol_results import (SCHEMA_ID, load_comsol_power_results,
                            merge_comsol_power, result_manifest,
                            write_result_manifest)


class ComsolResultBridgeTests(unittest.TestCase):
    def _bundle(self, folder, rows=((0, 0, 0), (20, 4, 30))):
        root = Path(folder)
        with (root / "power.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("drive_current", "emitted_power", "input_power"))
            writer.writerows(rows)
        manifest = result_manifest(
            "power.csv",
            (
                {"name": "drive_current", "quantity": "current", "unit": "mA", "expression": "I0"},
                {"name": "emitted_power", "quantity": "optical_power", "unit": "mW", "expression": "ewfd.Poav"},
                {"name": "input_power", "quantity": "electrical_power", "unit": "mW", "expression": "V0*I0"},
            ),
            model_name="PCSEL", study="std1", dataset="dset1", comsol_version="6.4",
        )
        return write_result_manifest(root / "power.results.json", manifest)

    def test_import_converts_units_and_preserves_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            imported = load_comsol_power_results(self._bundle(folder))
            merged = merge_comsol_power({"threshold_current_ma": 10}, imported)
        self.assertEqual(merged["comsol"]["current_ma"], [0, 20])
        self.assertEqual(merged["comsol"]["output_power_mw"], [0, 4])
        self.assertAlmostEqual(merged["comsol"]["wall_plug_efficiency"][1], 4 / 30)
        self.assertEqual(merged["comsol"]["provenance"]["study"], "std1")

    def test_rejects_path_escape_and_wrong_unit(self):
        with self.assertRaises(ValueError):
            result_manifest("../secret.csv", (), model_name="x", study="s", dataset="d")
        with self.assertRaises(ValueError):
            result_manifest("x.csv", ({"name": "p", "quantity": "optical_power",
                                        "unit": "nm", "expression": "p"},),
                            model_name="x", study="s", dataset="d")

    def test_rejects_nonfinite_and_incomplete_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._bundle(folder, rows=((0, "NaN", 0),))
            with self.assertRaisesRegex(ValueError, "Non-finite"):
                load_comsol_power_results(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["provenance"]["study"] = ""
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "provenance"):
                load_comsol_power_results(path)

    def test_schema_identifier_is_stable(self):
        self.assertEqual(SCHEMA_ID, "optical-design-studio/comsol-power-results/v1")

    def test_mixed_supported_units_merge_to_same_canonical_series(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with (root / "power.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(("current", "optical"))
                writer.writerows(((0, 0), (0.025, 6000)))
            manifest = result_manifest(
                "power.csv",
                (
                    {"name": "current", "quantity": "current", "unit": "A", "expression": "I0"},
                    {"name": "optical", "quantity": "optical_power", "unit": "uW", "expression": "ewfd.Poav"},
                ),
                model_name="PCSEL", study="std1", dataset="dset1",
            )
            path = write_result_manifest(root / "power.results.json", manifest)
            merged = merge_comsol_power({}, load_comsol_power_results(path))

        self.assertEqual(merged["comsol"]["current_ma"], [0, 25])
        self.assertEqual(merged["comsol"]["output_power_mw"], [0, 6])

    def test_merge_does_not_mutate_analytical_result(self):
        with tempfile.TemporaryDirectory() as folder:
            imported = load_comsol_power_results(self._bundle(folder))
            analytical = {"threshold_current_ma": 10, "output_power_mw": [0, 2]}
            merged = merge_comsol_power(analytical, imported)

        self.assertNotIn("comsol", analytical)
        self.assertEqual(merged["threshold_current_ma"], 10)
        self.assertEqual(merged["output_power_mw"], [0, 2])


if __name__ == "__main__":
    unittest.main()
