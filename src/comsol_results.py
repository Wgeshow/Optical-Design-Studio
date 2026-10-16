"""Validated, file-based bridge for COMSOL laser power results.

COMSOL is deliberately not imported here.  A COMSOL model exports a CSV and a
small JSON manifest; Optical Design Studio validates both before using values.
This keeps imported results traceable and makes the importer testable on hosts
without a COMSOL installation.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Iterable, Mapping


SCHEMA_ID = "optical-design-studio/comsol-power-results/v1"

# Canonical quantities accepted by the first laser/PCSEL results bridge.
# The conversion factor converts the declared unit to the canonical unit.
QUANTITIES = {
    "current": {"A": 1.0, "mA": 1e-3},
    "optical_power": {"W": 1.0, "mW": 1e-3, "uW": 1e-6},
    "electrical_power": {"W": 1.0, "mW": 1e-3},
    "vertical_power": {"W": 1.0, "mW": 1e-3, "uW": 1e-6},
    "lateral_power": {"W": 1.0, "mW": 1e-3, "uW": 1e-6},
    "absorbed_power": {"W": 1.0, "mW": 1e-3, "uW": 1e-6},
    "wavelength": {"m": 1.0, "um": 1e-6, "nm": 1e-9},
    "temperature": {"K": 1.0},
}


@dataclass(frozen=True)
class ResultColumn:
    name: str
    quantity: str
    unit: str
    expression: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping):
        if not isinstance(value, Mapping):
            raise ValueError("Each COMSOL result column must be an object.")
        column = cls(*(str(value.get(key, "")).strip()
                       for key in ("name", "quantity", "unit", "expression")))
        if not column.name or not column.expression:
            raise ValueError("Every COMSOL column needs a name and source expression.")
        units = QUANTITIES.get(column.quantity)
        if units is None:
            raise ValueError(f"Unsupported COMSOL result quantity: {column.quantity!r}.")
        if column.unit not in units:
            raise ValueError(
                f"Unit {column.unit!r} is not valid for {column.quantity!r}."
            )
        return column


@dataclass(frozen=True)
class ComsolPowerResults:
    manifest_path: Path
    provenance: Mapping[str, str]
    columns: tuple[ResultColumn, ...]
    rows: tuple[Mapping[str, float], ...]

    def series(self, quantity: str, canonical_unit: bool = True):
        matches = [column for column in self.columns if column.quantity == quantity]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one {quantity!r} column; found {len(matches)}.")
        column = matches[0]
        factor = QUANTITIES[column.quantity][column.unit] if canonical_unit else 1.0
        return [row[column.name] * factor for row in self.rows]


def result_manifest(csv_filename: str, columns: Iterable[Mapping], *,
                    model_name: str, study: str, dataset: str,
                    comsol_version: str = "unknown", model_file: str = ""):
    """Create a serialisable manifest template for a COMSOL table export."""
    safe_csv = _safe_relative_filename(csv_filename)
    parsed = tuple(ResultColumn.from_mapping(column) for column in columns)
    if not model_name.strip() or not study.strip() or not dataset.strip():
        raise ValueError("COMSOL model, study, and dataset provenance are required.")
    return {
        "schema": SCHEMA_ID,
        "csv": safe_csv,
        "provenance": {
            "solver": "COMSOL Multiphysics",
            "comsol_version": str(comsol_version).strip() or "unknown",
            "model_name": model_name.strip(),
            "model_file": str(model_file).strip(),
            "study": study.strip(),
            "dataset": dataset.strip(),
            "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        "columns": [vars(column) for column in parsed],
    }


def write_result_manifest(path, manifest):
    destination = Path(path)
    destination.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return destination


def load_comsol_power_results(manifest_path, *, max_rows=2_000_000):
    """Load and validate a COMSOL CSV result bundle.

    CSV paths must be simple relative filenames adjacent to the manifest.  This
    prevents an imported manifest from reading arbitrary files on the host.
    """
    source = Path(manifest_path)
    try:
        manifest = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read COMSOL result manifest: {exc}") from exc
    if not isinstance(manifest, Mapping) or manifest.get("schema") != SCHEMA_ID:
        raise ValueError("Unsupported or missing COMSOL result schema.")
    provenance = manifest.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError("COMSOL result provenance is required.")
    required = ("solver", "comsol_version", "model_name", "study", "dataset", "exported_at_utc")
    if any(not str(provenance.get(key, "")).strip() for key in required):
        raise ValueError("COMSOL provenance is incomplete.")
    if provenance.get("solver") != "COMSOL Multiphysics":
        raise ValueError("Result manifest does not identify COMSOL Multiphysics.")
    columns = tuple(ResultColumn.from_mapping(item) for item in manifest.get("columns", ()))
    if not columns or len({item.name for item in columns}) != len(columns):
        raise ValueError("COMSOL result columns must be present and uniquely named.")
    csv_path = source.parent / _safe_relative_filename(manifest.get("csv", ""))
    rows = []
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(_data_lines(handle))
            expected = [item.name for item in columns]
            if reader.fieldnames != expected:
                raise ValueError(f"CSV columns {reader.fieldnames!r} do not match {expected!r}.")
            for index, row in enumerate(reader, 1):
                if index > max_rows:
                    raise ValueError(f"COMSOL result exceeds the {max_rows:,}-row safety limit.")
                parsed = {}
                for column in columns:
                    try:
                        number = float(row[column.name])
                    except (KeyError, TypeError, ValueError) as exc:
                        raise ValueError(f"Invalid numeric value in row {index}, column {column.name!r}.") from exc
                    if not math.isfinite(number):
                        raise ValueError(f"Non-finite value in row {index}, column {column.name!r}.")
                    parsed[column.name] = number
                rows.append(parsed)
    except OSError as exc:
        raise ValueError(f"Could not read COMSOL result CSV: {exc}") from exc
    if not rows:
        raise ValueError("COMSOL result CSV contains no data rows.")
    return ComsolPowerResults(source, dict(provenance), columns, tuple(rows))


def merge_comsol_power(laser_result: Mapping, imported: ComsolPowerResults):
    """Return a laser result mapping augmented with canonical COMSOL power data."""
    result = dict(laser_result)
    current_a = imported.series("current")
    optical_w = imported.series("optical_power")
    if len(current_a) != len(optical_w):
        raise ValueError("COMSOL current and optical-power series have different lengths.")
    if any(current_a[i] > current_a[i + 1] for i in range(len(current_a) - 1)):
        raise ValueError("COMSOL current samples must be monotonically increasing.")
    result["comsol"] = {
        "current_ma": [value * 1e3 for value in current_a],
        "output_power_mw": [value * 1e3 for value in optical_w],
        "provenance": dict(imported.provenance),
        "manifest_path": str(imported.manifest_path),
    }
    for quantity, key in (("electrical_power", "electrical_power_mw"),
                          ("vertical_power", "vertical_power_mw"),
                          ("lateral_power", "lateral_power_mw"),
                          ("absorbed_power", "absorbed_power_mw")):
        if sum(column.quantity == quantity for column in imported.columns) == 1:
            result["comsol"][key] = [value * 1e3 for value in imported.series(quantity)]
    electrical = result["comsol"].get("electrical_power_mw")
    if electrical:
        result["comsol"]["wall_plug_efficiency"] = [
            optical / power if power > 0 else 0.0
            for optical, power in zip(result["comsol"]["output_power_mw"], electrical)
        ]
    return result


def _safe_relative_filename(value):
    text = str(value).strip()
    candidate = Path(text)
    if not text or candidate.is_absolute() or len(candidate.parts) != 1 or text in (".", ".."):
        raise ValueError("COMSOL CSV must be a filename adjacent to the manifest.")
    return text


def _data_lines(handle):
    """Ignore COMSOL's optional percent-prefixed metadata lines."""
    for line in handle:
        if line.lstrip().startswith("%") or not line.strip():
            continue
        yield line
