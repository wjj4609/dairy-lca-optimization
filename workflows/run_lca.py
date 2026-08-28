"""Run the public baseline LCA with the repository's synthetic example."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Mapping, Sequence
from math import isclose, isfinite
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from dairy_lca import (  # noqa: E402
    ParameterCatalog,
    __version__,
    calculate_farm_model,
    load_farm_input_csv,
)
from dairy_lca.exceptions import DairyLCAError, InputSchemaError  # noqa: E402
from dairy_lca.export import (  # noqa: E402
    export_result,
    filter_lca_result_for_reporting,
)
from dairy_lca.input_schema import (  # noqa: E402
    FARM_INPUT_COLUMNS,
    FARM_INPUT_FIELD_SPECS,
)

SYNTHETIC_WARNING = (
    "SYNTHETIC DEMONSTRATION ONLY — NOT FOR RESEARCH USE OR "
    "SCIENTIFIC INTERPRETATION."
)
EXAMPLE_DIRECTORY = REPOSITORY_ROOT / "examples"
FARM_EXAMPLE = EXAMPLE_DIRECTORY / "synthetic_farm.json"
PARAMETER_EXAMPLE = EXAMPLE_DIRECTORY / "synthetic_parameters.csv"
DIET_EXAMPLE = EXAMPLE_DIRECTORY / "synthetic_diet.csv"
CONSTRAINT_EXAMPLE = EXAMPLE_DIRECTORY / "synthetic_constraints.csv"

DIET_COLUMNS = (
    "synthetic",
    "ingredient_id",
    "ingredient_label",
    "annual_amount_t_year",
    "dry_matter_fraction",
    "crude_protein_fraction",
    "neutral_detergent_fiber_fraction",
    "objective_cost_unit_per_t",
    "warning",
)
CONSTRAINT_COLUMNS = (
    "synthetic",
    "constraint_id",
    "metric",
    "lower_bound",
    "upper_bound",
    "unit",
    "warning",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the generic dairy LCA baseline workflow."
    )
    parser.add_argument(
        "--example",
        action="store_true",
        help="run the repository's explicitly synthetic demonstration",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPOSITORY_ROOT / "outputs" / "synthetic_example",
        help="output directory; defaults to the git-ignored synthetic output folder",
    )
    return parser


def _require_synthetic_warning(value: object, label: str) -> str:
    if not isinstance(value, str) or "SYNTHETIC" not in value.upper():
        raise InputSchemaError(f"{label} must contain an explicit SYNTHETIC warning")
    if "NOT FOR RESEARCH" not in value.upper():
        raise InputSchemaError(f"{label} must state NOT FOR RESEARCH")
    return value


def _load_farm_document(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputSchemaError(f"cannot read synthetic farm JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise InputSchemaError("synthetic farm JSON must contain an object")
    if payload.get("schema_version") != "1.0":
        raise InputSchemaError("synthetic farm schema_version must be '1.0'")
    if payload.get("synthetic") is not True:
        raise InputSchemaError("synthetic farm JSON must set synthetic=true")
    _require_synthetic_warning(payload.get("warning"), "synthetic farm warning")
    return payload


def _farm_input_from_document(
    payload: Mapping[str, Any], temporary_parent: Path
):
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise InputSchemaError("synthetic farm records must be a non-empty list")
    specs_by_type: dict[str, list[Any]] = {}
    for spec in FARM_INPUT_FIELD_SPECS:
        specs_by_type.setdefault(spec.record_type, []).append(spec)

    csv_rows: list[dict[str, object]] = []
    for index, raw_record in enumerate(records):
        if not isinstance(raw_record, Mapping):
            raise InputSchemaError(f"synthetic farm record {index} must be an object")
        record_type = str(raw_record.get("record_type") or "").strip()
        record_id = str(raw_record.get("record_id") or "").strip()
        parent_record_id = str(raw_record.get("parent_record_id") or "").strip()
        values = raw_record.get("values")
        if record_type not in specs_by_type:
            raise InputSchemaError(
                f"synthetic farm record {index} has unknown record_type {record_type!r}"
            )
        if not record_id:
            raise InputSchemaError(f"synthetic farm record {index} has blank record_id")
        if not isinstance(values, Mapping):
            raise InputSchemaError(
                f"synthetic farm record {index} values must be an object"
            )
        known_fields = {spec.field_name for spec in specs_by_type[record_type]}
        unknown_fields = set(values) - known_fields
        if unknown_fields:
            raise InputSchemaError(
                f"synthetic farm record {index} has unknown field(s): "
                + ", ".join(sorted(str(field) for field in unknown_fields))
            )
        for spec in specs_by_type[record_type]:
            value = values.get(spec.field_name, "")
            csv_rows.append(
                {
                    "record_type": record_type,
                    "record_id": record_id,
                    "parent_record_id": parent_record_id,
                    "field_name": spec.field_name,
                    "value": value,
                    "unit": spec.unit,
                    "required_when": spec.required_when,
                    "null_rule": spec.null_rule,
                    "description": spec.description,
                }
            )

    temporary_parent.mkdir(parents=True, exist_ok=True)
    csv_path = temporary_parent / ".synthetic_farm_input.csv"
    try:
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FARM_INPUT_COLUMNS)
            writer.writeheader()
            writer.writerows(csv_rows)
        farm_input = load_farm_input_csv(csv_path)
    finally:
        csv_path.unlink(missing_ok=True)
    if not farm_input.farm_id.startswith("synthetic_"):
        raise InputSchemaError("example farm_id must start with 'synthetic_'")
    if not farm_input.dataset_label or "synthetic" not in farm_input.dataset_label:
        raise InputSchemaError("example dataset_label must contain 'synthetic'")
    return farm_input


def _number(label: str, raw: object, *, fraction: bool = False) -> float:
    try:
        value = float(str(raw).strip())
    except ValueError as exc:
        raise InputSchemaError(f"{label} must be numeric") from exc
    if not isfinite(value):
        raise InputSchemaError(f"{label} must be finite")
    if fraction and not 0 <= value <= 1:
        raise InputSchemaError(f"{label} must be in [0, 1]")
    return value


def _read_csv(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != list(columns):
                raise InputSchemaError(
                    f"{path.name} header must be exactly: {', '.join(columns)}"
                )
            rows = [
                {key: str(value or "").strip() for key, value in row.items()}
                for row in reader
                if any(str(value or "").strip() for value in row.values())
            ]
    except OSError as exc:
        raise InputSchemaError(f"cannot read {path.name}: {exc}") from exc
    if not rows:
        raise InputSchemaError(f"{path.name} contains no rows")
    for index, row in enumerate(rows, start=2):
        if row["synthetic"].lower() != "true":
            raise InputSchemaError(f"{path.name} row {index} must set synthetic=true")
        _require_synthetic_warning(row["warning"], f"{path.name} row {index}")
    return rows


def _validate_diet(path: Path) -> tuple[list[dict[str, str]], float]:
    rows = _read_csv(path, DIET_COLUMNS)
    seen: set[str] = set()
    total = 0.0
    for index, row in enumerate(rows, start=2):
        ingredient_id = row["ingredient_id"]
        if not ingredient_id.startswith("synthetic_"):
            raise InputSchemaError(
                f"synthetic_diet.csv row {index} ingredient_id must start with synthetic_"
            )
        if ingredient_id in seen:
            raise InputSchemaError(f"duplicate ingredient_id {ingredient_id!r}")
        seen.add(ingredient_id)
        amount = _number(
            f"synthetic_diet.csv row {index} annual_amount_t_year",
            row["annual_amount_t_year"],
        )
        if amount < 0:
            raise InputSchemaError("synthetic diet amounts must be nonnegative")
        total += amount
        for field in (
            "dry_matter_fraction",
            "crude_protein_fraction",
            "neutral_detergent_fiber_fraction",
        ):
            _number(
                f"synthetic_diet.csv row {index} {field}",
                row[field],
                fraction=True,
            )
        _number(
            f"synthetic_diet.csv row {index} objective_cost_unit_per_t",
            row["objective_cost_unit_per_t"],
        )
    return rows, total


def _validate_constraints(path: Path) -> list[dict[str, str]]:
    rows = _read_csv(path, CONSTRAINT_COLUMNS)
    seen: set[str] = set()
    for index, row in enumerate(rows, start=2):
        constraint_id = row["constraint_id"]
        if not constraint_id.startswith("synthetic_"):
            raise InputSchemaError(
                f"synthetic_constraints.csv row {index} constraint_id must start "
                "with synthetic_"
            )
        if constraint_id in seen:
            raise InputSchemaError(f"duplicate constraint_id {constraint_id!r}")
        seen.add(constraint_id)
        lower = _number(
            f"synthetic_constraints.csv row {index} lower_bound",
            row["lower_bound"],
        )
        upper = _number(
            f"synthetic_constraints.csv row {index} upper_bound",
            row["upper_bound"],
        )
        if lower > upper:
            raise InputSchemaError(
                f"synthetic_constraints.csv row {index} lower_bound exceeds upper_bound"
            )
    return rows


def run_synthetic_example(output_directory: Path) -> tuple[str, ...]:
    farm_document = _load_farm_document(FARM_EXAMPLE)
    farm_input = _farm_input_from_document(farm_document, output_directory)
    catalog = ParameterCatalog.from_csv(PARAMETER_EXAMPLE)
    catalog.validate_required()
    for parameter_id, parameter in catalog.as_dict().items():
        citation = str(parameter.get("citation") or "")
        _require_synthetic_warning(citation, f"parameter {parameter_id}")

    diet_rows, diet_total = _validate_diet(DIET_EXAMPLE)
    constraint_rows = _validate_constraints(CONSTRAINT_EXAMPLE)
    farm_feed_total = sum(
        item.annual_feed_use_t_year for item in farm_input.feed_production.feeds
    )
    if not isclose(diet_total, farm_feed_total, rel_tol=0.0, abs_tol=1e-9):
        raise InputSchemaError(
            "synthetic diet total must equal the farm feed-production total"
        )
    diet_ids = {row["ingredient_id"] for row in diet_rows}
    farm_feed_ids = {item.feed_id for item in farm_input.feed_production.feeds}
    if diet_ids != farm_feed_ids:
        raise InputSchemaError(
            "synthetic diet ingredient IDs must match farm feed-production IDs"
        )

    result = calculate_farm_model(catalog, farm_input)
    payload = {
        "schema_version": "1.0",
        "synthetic": True,
        "warning": SYNTHETIC_WARNING,
        "status": "success",
        "run_type": "synthetic_baseline_lca",
        "model_version": __version__,
        "input_files": (
            "examples/synthetic_farm.json",
            "examples/synthetic_parameters.csv",
            "examples/synthetic_diet.csv",
            "examples/synthetic_constraints.csv",
        ),
        "input_summary": {
            "farm_count": 1,
            "diet_row_count": len(diet_rows),
            "constraint_row_count": len(constraint_rows),
            "all_values_are_synthetic": True,
        },
        "result": filter_lca_result_for_reporting(result),
    }
    manifest = export_result(
        payload,
        output_directory,
        stem="synthetic_baseline_result",
    )
    return manifest.files


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.example:
        parser.error("this public workflow currently requires --example")
    try:
        files = run_synthetic_example(args.output_dir)
    except DairyLCAError as exc:
        print(f"synthetic example run failed: {exc}", file=sys.stderr)
        return 2
    print("synthetic example run passed")
    print("outputs: " + ", ".join(files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
