"""Public CSV templates, validation, and conversion to runtime input objects."""

from __future__ import annotations

import csv
import re
from collections import OrderedDict
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any

from .batch import FarmModelInput
from .energy import EnergyUseInput
from .enteric import EntericFarmInput, EntericStageInput
from .exceptions import InputSchemaError
from .feed_field import FeedFieldInput, FeedFieldItemInput
from .feed_production import (
    AgriculturalInput,
    FeedProductionInput,
    FeedProductionItemInput,
)
from .feed_transport import (
    FeedTransportInput,
    FeedTransportSourceInput,
    SeaTransportInput,
)
from .manure import (
    ManureManagementInput,
    ManurePathwayInput,
    ManureStageInput,
    PATHWAY_STAGES,
)

KG_PER_TONNE = 1000.0
DEFAULT_ELECTRICITY_GHG_PARAMETER_ID = "energy.electricity_ghg_factor"

FARM_INPUT_COLUMNS = (
    "record_type",
    "record_id",
    "parent_record_id",
    "field_name",
    "value",
    "unit",
    "required_when",
    "null_rule",
    "description",
)

OPTIMIZATION_INPUT_COLUMNS = (
    "record_type",
    "record_id",
    "related_record_id",
    "field_name",
    "value",
    "unit",
    "required_when",
    "null_rule",
    "description",
)


@dataclass(frozen=True)
class InputFieldSpec:
    record_type: str
    field_name: str
    unit: str
    required_when: str
    null_rule: str
    description: str


def _field(
    record_type: str,
    field_name: str,
    unit: str,
    required_when: str,
    null_rule: str,
    description: str,
) -> InputFieldSpec:
    return InputFieldSpec(
        record_type,
        field_name,
        unit,
        required_when,
        null_rule,
        description,
    )


FARM_INPUT_FIELD_SPECS = (
    _field("farm", "farm_id", "id", "always", "blank rejected", "Public farm identifier."),
    _field("farm", "dataset_label", "id", "optional", "blank becomes null", "Optional public dataset label."),
    _field("farm", "annual_raw_milk_t_year", "t/year", "always", "blank rejected", "Annual delivered raw milk; must be greater than zero."),
    _field("farm", "milk_fat_fraction", "fraction", "always", "blank rejected", "Milk fat as a decimal fraction in the range [0, 1]."),
    _field("farm", "milk_protein_fraction", "fraction", "always", "blank rejected", "Milk protein as a decimal fraction in the range [0, 1]."),
    _field("farm", "average_milk_price_currency_kg", "currency/kg raw milk", "always", "blank rejected", "Average milk price in the same currency used for cattle sales; must be greater than zero."),
    _field("cattle_sale", "pricing_basis", "id", "when cattle_sale record is used", "all-blank exemplar is ignored", "Use per_head or per_kg_live_weight."),
    _field("cattle_sale", "annual_quantity_head", "head/year", "per_head, or per_kg_live_weight when total live weight is blank", "blank allowed only when the conditional requirement does not apply", "Annual number of cattle sold."),
    _field("cattle_sale", "unit_price_currency_head", "currency/head", "pricing_basis=per_head", "blank otherwise", "Sale price per head."),
    _field("cattle_sale", "unit_price_currency_kg", "currency/kg live weight", "pricing_basis=per_kg_live_weight", "blank otherwise", "Sale price per kilogram live weight."),
    _field("cattle_sale", "average_live_weight_kg_head", "kg/head", "per_kg_live_weight when total live weight is blank", "blank allowed when annual total live weight is filled", "Average sale live weight used to derive annual total live weight."),
    _field("cattle_sale", "annual_total_live_weight_kg_year", "kg/year", "optional for per_kg_live_weight", "blank derives quantity multiplied by average live weight", "Annual total live weight; takes precedence when filled."),
    _field("energy", "electricity_kwh_year", "kWh/year", "optional activity", "blank becomes 0", "Annual purchased or metered electricity use."),
    _field("energy", "coal_t_year", "t/year", "optional activity", "blank becomes 0", "Annual coal use."),
    _field("energy", "diesel_l_year", "L/year", "optional activity", "blank becomes 0", "Annual diesel use."),
    _field("energy", "natural_gas_m3_year", "m3/year", "optional activity", "blank becomes 0", "Annual natural-gas use."),
    _field("energy", "electricity_ghg_parameter_id", "parameter id", "when electricity is greater than 0", "blank uses energy.electricity_ghg_factor", "Parameter ID for the electricity greenhouse-gas factor."),
    _field("herd_stage", "count_head", "head", "each herd_stage record", "blank rejected", "Number of animals in the stage; whole number greater than or equal to zero."),
    _field("herd_stage", "dry_matter_intake_kg_head_day", "kg DM/head/day", "each herd_stage record", "blank rejected", "Daily dry-matter intake per head."),
    _field("herd_stage", "neutral_detergent_fiber_fraction", "fraction of DM", "each herd_stage record", "blank rejected", "Neutral detergent fibre fraction of diet dry matter."),
    _field("herd_stage", "starch_fraction", "fraction of DM", "each herd_stage record", "blank rejected", "Starch fraction of diet dry matter."),
    _field("herd_stage", "fatty_acid_fraction", "fraction of DM", "each herd_stage record", "blank rejected", "Fatty-acid fraction of diet dry matter."),
    _field("herd_stage", "crude_protein_fraction", "fraction of DM", "each herd_stage record", "blank rejected", "Crude-protein fraction of diet dry matter."),
    _field("herd_stage", "non_protein_nitrogen_fraction", "fraction of DM", "each herd_stage record", "blank rejected", "Non-protein nitrogen fraction; cannot exceed crude protein."),
    _field("herd_stage", "ash_fraction", "fraction of DM", "each herd_stage record", "blank rejected", "Ash fraction of diet dry matter."),
    _field("herd_stage", "body_weight_kg", "kg/head", "each herd_stage record", "blank rejected", "Average body weight for the stage; must be greater than zero."),
    _field("manure", "annual_slurry_t_year", "t/year", "always", "blank rejected", "Annual slurry fresh mass."),
    _field("manure", "recovered_electricity_kwh_year", "kWh/year", "optional recovery", "blank becomes 0", "Annual recovered electricity credited by the model."),
    _field("manure", "recovered_heat_mj_year", "MJ/year", "optional recovery", "blank becomes 0", "Annual recovered heat credited by the model."),
    _field("manure", "electricity_credit_parameter_id", "parameter id", "when recovered electricity is greater than 0", "blank uses energy.electricity_ghg_factor", "Parameter ID for recovered-electricity credit."),
    _field("manure_pathway", "method_id", "method id", "for housing, storage_treatment, and land_application", "blank rejected", "Public parameter method ID for this manure pathway stage."),
    _field("feed_production", "annual_feed_use_t_year", "t/year", "each feed_production record", "blank rejected", "Annual feed product mass used."),
    _field("feed_production", "crop_requirement_factor", "t crop reference/t feed", "each feed_production record", "blank rejected", "Positive crop-reference requirement per unit feed product."),
    _field("feed_production", "cultivation_mass_fraction", "fraction", "each feed_production record", "blank rejected", "Fraction of the crop reference mass cultivated."),
    _field("feed_production", "yield_kg_ha", "kg/ha", "each feed_production record", "blank rejected", "Crop yield; must be greater than zero."),
    _field("feed_production", "allocation_fraction", "fraction", "optional", "blank becomes 1", "Fraction of production impacts allocated to the feed product."),
    _field("feed_production", "diesel_use_kg_ha", "kg/ha", "optional activity", "blank becomes 0", "Cultivation diesel use per hectare."),
    _field("feed_production", "electricity_use_kwh_ha", "kWh/ha", "optional activity", "blank becomes 0", "Cultivation electricity use per hectare."),
    _field("agricultural_input", "rate_kg_ha", "kg/ha", "when agricultural_input record is used", "all-blank exemplar is ignored", "Agricultural input application rate."),
    _field("agricultural_input", "ghg_factor_parameter_id", "parameter id", "when agricultural_input record is used", "blank rejected", "Upstream GHG factor parameter ID."),
    _field("agricultural_input", "n2o_factor_parameter_id", "parameter id", "when agricultural_input record is used", "blank rejected", "Upstream N2O factor parameter ID."),
    _field("agricultural_input", "nh3_factor_parameter_id", "parameter id", "when agricultural_input record is used", "blank rejected", "Upstream NH3 factor parameter ID."),
    _field("agricultural_input", "phosphorus_factor_parameter_id", "parameter id", "when agricultural_input record is used", "blank rejected", "Upstream phosphorus factor parameter ID."),
    _field("feed_field", "fertilizer_application_method_id", "method id", "each feed_field record", "blank rejected", "Public fertilizer-application method ID."),
    _field("feed_field", "allocation_fraction", "fraction", "optional", "blank becomes 1", "Fraction of field impacts allocated to the feed product."),
    _field("feed_field", "seed_n_kg_year", "kg N/year", "optional activity", "blank becomes 0", "Annual seed nitrogen input."),
    _field("feed_field", "biological_fixation_n_kg_year", "kg N/year", "optional activity", "blank becomes 0", "Annual biological nitrogen fixation."),
    _field("feed_field", "atmospheric_n_kg_year", "kg N/year", "optional activity", "blank becomes 0", "Annual atmospheric nitrogen deposition."),
    _field("feed_field", "mineral_fertilizer_n_kg_year", "kg N/year", "optional activity", "blank becomes 0", "Annual mineral-fertilizer nitrogen input."),
    _field("feed_field", "manure_n_kg_year", "kg N/year", "optional activity", "blank becomes 0", "Annual manure nitrogen input."),
    _field("feed_field", "irrigation_n_kg_year", "kg N/year", "optional activity", "blank becomes 0", "Annual irrigation nitrogen input."),
    _field("feed_field", "straw_return_n_kg_year", "kg N/year", "optional activity", "blank becomes 0", "Annual returned-straw nitrogen input."),
    _field("feed_field", "seed_p_kg_year", "kg P/year", "optional activity", "blank becomes 0", "Annual seed phosphorus input."),
    _field("feed_field", "atmospheric_p_kg_year", "kg P/year", "optional activity", "blank becomes 0", "Annual atmospheric phosphorus deposition."),
    _field("feed_field", "mineral_fertilizer_p_kg_year", "kg P/year", "optional activity", "blank becomes 0", "Annual mineral-fertilizer phosphorus input."),
    _field("feed_field", "manure_p_kg_year", "kg P/year", "optional activity", "blank becomes 0", "Annual manure phosphorus input."),
    _field("feed_field", "irrigation_p_kg_year", "kg P/year", "optional activity", "blank becomes 0", "Annual irrigation phosphorus input."),
    _field("feed_field", "straw_return_p_kg_year", "kg P/year", "optional activity", "blank becomes 0", "Annual returned-straw phosphorus input."),
    _field("feed_field", "main_product_n_kg_year", "kg N/year", "optional activity", "blank becomes 0", "Annual nitrogen removed in the main product."),
    _field("feed_field", "straw_n_kg_year", "kg N/year", "optional activity", "blank becomes 0", "Annual nitrogen removed in straw."),
    _field("feed_field", "main_product_p_kg_year", "kg P/year", "optional activity", "blank becomes 0", "Annual phosphorus removed in the main product."),
    _field("feed_field", "straw_p_kg_year", "kg P/year", "optional activity", "blank becomes 0", "Annual phosphorus removed in straw."),
    _field("feed_field", "urea_equivalent_kg_year", "kg/year", "optional activity", "blank becomes 0", "Annual urea-equivalent amount used for soil CO2."),
    _field("feed_field", "diesel_kg_year", "kg/year", "optional activity", "blank becomes 0", "Annual field diesel use."),
    _field("feed_field", "electricity_kwh_year", "kWh/year", "optional activity", "blank becomes 0", "Annual field electricity use."),
    _field("feed_field", "electricity_ghg_parameter_id", "parameter id", "when electricity is greater than 0", "blank uses energy.electricity_ghg_factor", "Parameter ID for field electricity GHG."),
    _field("transport_source", "feed_id", "id", "each transport_source record", "blank rejected", "Feed ID linked to a feed_production record."),
    _field("transport_source", "feed_mass_t_year", "t/year", "each transport_source record", "blank rejected", "Annual feed mass transported from this source."),
    _field("transport_source", "road_distance_km", "km one way", "each transport_source record", "blank rejected", "Loaded one-way road distance."),
    _field("transport_source", "sea_distance_nmi", "nautical mile one way", "when a sea leg is used", "all sea fields blank means no sea leg", "One-way sea distance."),
    _field("transport_source", "sea_cargo_mass_t_year", "t/year", "when a sea leg is used", "all sea fields blank means no sea leg", "Annual cargo mass used to determine voyages."),
    _field("transport_source", "sea_emission_allocation_fraction", "fraction", "optional when a sea leg is used", "blank becomes 1 for a sea leg", "Fraction of sea emissions allocated to this feed source."),
)


OPTIMIZATION_INPUT_FIELD_SPECS = (
    _field("model", "objective_direction", "id", "always", "blank rejected", "Use minimize or maximize."),
    _field("model", "objective_unit", "unit text", "always", "blank rejected", "Unit of the linear objective value."),
    _field("decision", "lower_bound", "decision unit", "optional", "blank means no lower bound", "Lower bound for the decision variable."),
    _field("decision", "upper_bound", "decision unit", "optional", "blank means no upper bound", "Upper bound for the decision variable."),
    _field("decision", "objective_coefficient", "objective unit/decision unit", "each decision record", "blank rejected", "Linear objective coefficient."),
    _field("decision", "decision_unit", "unit text", "each decision record", "blank rejected", "Unit of this decision variable."),
    _field("constraint", "lower_bound", "constraint unit", "at least one constraint bound", "blank means no lower bound", "Lower bound for the constraint expression."),
    _field("constraint", "upper_bound", "constraint unit", "at least one constraint bound", "blank means no upper bound", "Upper bound for the constraint expression."),
    _field("constraint", "constraint_unit", "unit text", "each constraint record", "blank rejected", "Unit of the constraint expression."),
    _field("coefficient", "coefficient", "constraint unit/decision unit", "each coefficient record", "blank rejected", "Sparse constraint-matrix coefficient; omitted pairs are zero."),
)


FARM_TEMPLATE_LAYOUT = (
    ("farm", "farm", ""),
    ("cattle_sale", "<sale_id>", ""),
    ("energy", "energy", ""),
    ("herd_stage", "<stage_id>", ""),
    ("manure", "manure", ""),
    ("manure_pathway", "housing", ""),
    ("manure_pathway", "storage_treatment", ""),
    ("manure_pathway", "land_application", ""),
    ("feed_production", "<feed_id>", ""),
    ("agricultural_input", "<input_id>", "<feed_id>"),
    ("feed_field", "<feed_id>", ""),
    ("transport_source", "<source_id>", ""),
)

OPTIMIZATION_TEMPLATE_LAYOUT = (
    ("model", "model", ""),
    ("decision", "<decision_id>", ""),
    ("constraint", "<constraint_id>", ""),
    ("coefficient", "<constraint_id>", "<decision_id>"),
)


def _specs_by_record_type(
    specs: tuple[InputFieldSpec, ...],
) -> dict[str, tuple[InputFieldSpec, ...]]:
    result: dict[str, list[InputFieldSpec]] = {}
    for spec in specs:
        result.setdefault(spec.record_type, []).append(spec)
    return {key: tuple(value) for key, value in result.items()}


def _template_rows(
    specs: tuple[InputFieldSpec, ...],
    layout: tuple[tuple[str, str, str], ...],
    relation_column: str,
) -> tuple[dict[str, str], ...]:
    by_type = _specs_by_record_type(specs)
    rows: list[dict[str, str]] = []
    for record_type, record_id, relation_id in layout:
        for spec in by_type[record_type]:
            rows.append(
                {
                    "record_type": record_type,
                    "record_id": record_id,
                    relation_column: relation_id,
                    "field_name": spec.field_name,
                    "value": "",
                    "unit": spec.unit,
                    "required_when": spec.required_when,
                    "null_rule": spec.null_rule,
                    "description": spec.description,
                }
            )
    return tuple(rows)


def farm_template_rows() -> tuple[dict[str, str], ...]:
    """Return the authoritative blank farm-template rows."""

    return _template_rows(
        FARM_INPUT_FIELD_SPECS,
        FARM_TEMPLATE_LAYOUT,
        "parent_record_id",
    )


def optimization_template_rows() -> tuple[dict[str, str], ...]:
    """Return the authoritative blank optimization-template rows."""

    return _template_rows(
        OPTIMIZATION_INPUT_FIELD_SPECS,
        OPTIMIZATION_TEMPLATE_LAYOUT,
        "related_record_id",
    )


@dataclass(frozen=True)
class LinearObjectiveInput:
    direction: str
    unit: str


@dataclass(frozen=True)
class LinearDecisionInput:
    decision_id: str
    lower_bound: float | None
    upper_bound: float | None
    objective_coefficient: float
    unit: str


@dataclass(frozen=True)
class LinearConstraintInput:
    constraint_id: str
    lower_bound: float | None
    upper_bound: float | None
    unit: str


@dataclass(frozen=True)
class LinearCoefficientInput:
    constraint_id: str
    decision_id: str
    coefficient: float


@dataclass(frozen=True)
class OptimizationModelInput:
    objective: LinearObjectiveInput
    decisions: tuple[LinearDecisionInput, ...]
    constraints: tuple[LinearConstraintInput, ...]
    coefficients: tuple[LinearCoefficientInput, ...]


@dataclass(frozen=True)
class _Record:
    record_type: str
    record_id: str
    relation_id: str
    values: dict[str, str]

    @property
    def label(self) -> str:
        if self.relation_id:
            return f"{self.record_type}[{self.record_id}->{self.relation_id}]"
        return f"{self.record_type}[{self.record_id}]"


_PLACEHOLDER = re.compile(r"^<[^<>]+>$")
_NO_DEFAULT = object()


def _read_rows(
    csv_path: str | Path,
    columns: tuple[str, ...],
) -> tuple[dict[str, str], ...]:
    path = Path(csv_path)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != list(columns):
                raise InputSchemaError(
                    f"{path.name} header must be exactly: {', '.join(columns)}"
                )
            rows: list[dict[str, str]] = []
            for line_number, raw in enumerate(reader, start=2):
                if None in raw:
                    raise InputSchemaError(
                        f"{path.name} line {line_number} has extra columns"
                    )
                row = {
                    column: (raw.get(column) or "").strip()
                    for column in columns
                }
                if any(row.values()):
                    rows.append(row)
    except InputSchemaError:
        raise
    except (OSError, csv.Error) as exc:
        raise InputSchemaError(f"cannot read input CSV {path}: {exc}") from exc
    if not rows:
        raise InputSchemaError(f"{path.name} contains no input rows")
    return tuple(rows)


def _spec_index(
    specs: tuple[InputFieldSpec, ...],
) -> dict[tuple[str, str], InputFieldSpec]:
    return {(spec.record_type, spec.field_name): spec for spec in specs}


def _validate_metadata(
    rows: tuple[dict[str, str], ...],
    specs: tuple[InputFieldSpec, ...],
) -> None:
    index = _spec_index(specs)
    for position, row in enumerate(rows, start=2):
        key = (row["record_type"], row["field_name"])
        spec = index.get(key)
        if spec is None:
            raise InputSchemaError(
                f"line {position} has unknown input field {key[0]}.{key[1]}"
            )
        for column in ("unit", "required_when", "null_rule", "description"):
            if row[column] != getattr(spec, column):
                raise InputSchemaError(
                    f"line {position} changes protected metadata column {column!r} "
                    f"for {key[0]}.{key[1]}"
                )


def _group_records(
    rows: tuple[dict[str, str], ...],
    specs: tuple[InputFieldSpec, ...],
    relation_column: str,
    relation_record_type: str,
) -> tuple[_Record, ...]:
    _validate_metadata(rows, specs)
    expected = {
        record_type: {spec.field_name for spec in record_specs}
        for record_type, record_specs in _specs_by_record_type(specs).items()
    }
    grouped: OrderedDict[tuple[str, str, str], dict[str, str]] = OrderedDict()
    for position, row in enumerate(rows, start=2):
        record_type = row["record_type"]
        record_id = row["record_id"]
        relation_id = row[relation_column]
        if not record_id:
            raise InputSchemaError(f"line {position} has a blank record_id")
        if record_type == relation_record_type:
            if not relation_id:
                raise InputSchemaError(
                    f"line {position} requires {relation_column} for {record_type}"
                )
        elif relation_id:
            raise InputSchemaError(
                f"line {position} must leave {relation_column} blank for {record_type}"
            )
        key = (record_type, record_id, relation_id)
        values = grouped.setdefault(key, {})
        field_name = row["field_name"]
        if field_name in values:
            raise InputSchemaError(
                f"duplicate field {field_name!r} in {record_type}[{record_id}]"
            )
        values[field_name] = row["value"]

    records: list[_Record] = []
    for (record_type, record_id, relation_id), values in grouped.items():
        missing = expected[record_type] - set(values)
        extra = set(values) - expected[record_type]
        if missing or extra:
            details = []
            if missing:
                details.append("missing " + ", ".join(sorted(missing)))
            if extra:
                details.append("extra " + ", ".join(sorted(extra)))
            raise InputSchemaError(
                f"incomplete {record_type}[{record_id}] record: "
                + "; ".join(details)
            )
        records.append(_Record(record_type, record_id, relation_id, values))
    return tuple(records)


def _validate_exact_template(
    csv_path: str | Path,
    columns: tuple[str, ...],
    expected_rows: tuple[dict[str, str], ...],
) -> int:
    rows = _read_rows(csv_path, columns)
    if rows != expected_rows:
        raise InputSchemaError(
            f"{Path(csv_path).name} does not match the authoritative blank template"
        )
    return len(rows)


def validate_farm_input_template(csv_path: str | Path) -> int:
    """Validate the official blank farm-input template and return its row count."""

    return _validate_exact_template(
        csv_path,
        FARM_INPUT_COLUMNS,
        farm_template_rows(),
    )


def validate_optimization_input_template(csv_path: str | Path) -> int:
    """Validate the official blank optimization template and return its row count."""

    return _validate_exact_template(
        csv_path,
        OPTIMIZATION_INPUT_COLUMNS,
        optimization_template_rows(),
    )


def _is_blank_record(record: _Record) -> bool:
    return not any(record.values.values())


def _active_records(
    records: tuple[_Record, ...],
    optional_blank_types: set[str],
) -> tuple[_Record, ...]:
    return tuple(
        record
        for record in records
        if not (
            record.record_type in optional_blank_types
            and _is_blank_record(record)
        )
    )


def _by_type(records: tuple[_Record, ...]) -> dict[str, tuple[_Record, ...]]:
    result: dict[str, list[_Record]] = {}
    for record in records:
        result.setdefault(record.record_type, []).append(record)
    return {key: tuple(value) for key, value in result.items()}


def _single(
    records_by_type: dict[str, tuple[_Record, ...]],
    record_type: str,
    expected_record_id: str,
) -> _Record:
    records = records_by_type.get(record_type, ())
    if len(records) != 1:
        raise InputSchemaError(
            f"completed input requires exactly one {record_type} record"
        )
    record = records[0]
    if record.record_id != expected_record_id:
        raise InputSchemaError(
            f"{record_type} record_id must be {expected_record_id!r}"
        )
    return record


def _required_records(
    records_by_type: dict[str, tuple[_Record, ...]],
    record_type: str,
) -> tuple[_Record, ...]:
    records = records_by_type.get(record_type, ())
    if not records:
        raise InputSchemaError(
            f"completed input requires at least one {record_type} record"
        )
    return records


def _identifier(label: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise InputSchemaError(f"{label} cannot be blank")
    if _PLACEHOLDER.fullmatch(normalized):
        raise InputSchemaError(f"{label} still contains placeholder {normalized!r}")
    return normalized


def _record_id(record: _Record) -> str:
    return _identifier(f"{record.label}.record_id", record.record_id)


def _text(
    record: _Record,
    field_name: str,
    *,
    default: Any = _NO_DEFAULT,
) -> str | None:
    value = record.values[field_name].strip()
    if not value:
        if default is _NO_DEFAULT:
            raise InputSchemaError(f"{record.label}.{field_name} cannot be blank")
        return default
    return _identifier(f"{record.label}.{field_name}", value)


def _float(
    record: _Record,
    field_name: str,
    *,
    default: Any = _NO_DEFAULT,
    nonnegative: bool = False,
    positive: bool = False,
) -> float | None:
    raw = record.values[field_name].strip()
    if not raw:
        if default is _NO_DEFAULT:
            raise InputSchemaError(f"{record.label}.{field_name} cannot be blank")
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise InputSchemaError(
            f"{record.label}.{field_name} must be numeric"
        ) from exc
    if not isfinite(value):
        raise InputSchemaError(f"{record.label}.{field_name} must be finite")
    if positive and value <= 0:
        raise InputSchemaError(f"{record.label}.{field_name} must be > 0")
    if nonnegative and value < 0:
        raise InputSchemaError(f"{record.label}.{field_name} must be >= 0")
    return value


def _whole(
    record: _Record,
    field_name: str,
    *,
    positive: bool = False,
) -> int:
    value = _float(
        record,
        field_name,
        nonnegative=True,
        positive=positive,
    )
    assert value is not None
    if not value.is_integer():
        raise InputSchemaError(
            f"{record.label}.{field_name} must be a whole number"
        )
    return int(value)


def _fraction(
    record: _Record,
    field_name: str,
    *,
    default: Any = _NO_DEFAULT,
) -> float:
    value = _float(
        record,
        field_name,
        default=default,
        nonnegative=True,
    )
    assert value is not None
    if value > 1:
        raise InputSchemaError(f"{record.label}.{field_name} must be in [0, 1]")
    return value


def _require_blank(record: _Record, *field_names: str) -> None:
    for field_name in field_names:
        if record.values[field_name].strip():
            raise InputSchemaError(
                f"{record.label}.{field_name} must be blank for the selected mode"
            )


def _string(
    record: _Record,
    field_name: str,
    *,
    default: Any = _NO_DEFAULT,
) -> str:
    value = _text(record, field_name, default=default)
    assert isinstance(value, str)
    return value


def _number(
    record: _Record,
    field_name: str,
    *,
    default: Any = _NO_DEFAULT,
    nonnegative: bool = False,
    positive: bool = False,
) -> float:
    value = _float(
        record,
        field_name,
        default=default,
        nonnegative=nonnegative,
        positive=positive,
    )
    assert isinstance(value, float)
    return value


def load_farm_input_csv(csv_path: str | Path) -> FarmModelInput:
    """Read a completed public farm CSV and build ``FarmModelInput``."""

    rows = _read_rows(csv_path, FARM_INPUT_COLUMNS)
    grouped = _group_records(
        rows,
        FARM_INPUT_FIELD_SPECS,
        "parent_record_id",
        "agricultural_input",
    )
    records = _active_records(grouped, {"cattle_sale", "agricultural_input"})
    records_by_type = _by_type(records)

    farm = _single(records_by_type, "farm", "farm")
    energy_record = _single(records_by_type, "energy", "energy")
    manure_record = _single(records_by_type, "manure", "manure")

    farm_id = _string(farm, "farm_id")
    dataset_label_value = _text(farm, "dataset_label", default=None)
    assert dataset_label_value is None or isinstance(dataset_label_value, str)
    annual_raw_milk = _number(
        farm,
        "annual_raw_milk_t_year",
        positive=True,
    )
    milk_fat = _fraction(farm, "milk_fat_fraction")
    milk_protein = _fraction(farm, "milk_protein_fraction")
    milk_price = _number(
        farm,
        "average_milk_price_currency_kg",
        positive=True,
    )
    milk_revenue = annual_raw_milk * KG_PER_TONNE * milk_price

    cattle_revenue = 0.0
    for sale in records_by_type.get("cattle_sale", ()):
        _record_id(sale)
        pricing_basis = _string(sale, "pricing_basis").lower()
        if pricing_basis == "per_head":
            quantity = _whole(sale, "annual_quantity_head", positive=True)
            unit_price = _number(
                sale,
                "unit_price_currency_head",
                positive=True,
            )
            _require_blank(
                sale,
                "unit_price_currency_kg",
                "average_live_weight_kg_head",
                "annual_total_live_weight_kg_year",
            )
            cattle_revenue += quantity * unit_price
        elif pricing_basis == "per_kg_live_weight":
            _require_blank(sale, "unit_price_currency_head")
            unit_price = _number(
                sale,
                "unit_price_currency_kg",
                positive=True,
            )
            annual_live_weight = _float(
                sale,
                "annual_total_live_weight_kg_year",
                default=None,
                positive=True,
            )
            if annual_live_weight is None:
                quantity = _whole(sale, "annual_quantity_head", positive=True)
                average_weight = _number(
                    sale,
                    "average_live_weight_kg_head",
                    positive=True,
                )
                annual_live_weight = quantity * average_weight
            else:
                quantity_raw = sale.values["annual_quantity_head"].strip()
                weight_raw = sale.values["average_live_weight_kg_head"].strip()
                if bool(quantity_raw) != bool(weight_raw):
                    raise InputSchemaError(
                        f"{sale.label} must fill both quantity and average live "
                        "weight, or leave both blank, when annual total live weight "
                        "is supplied"
                    )
                if quantity_raw:
                    _whole(sale, "annual_quantity_head", positive=True)
                    _number(
                        sale,
                        "average_live_weight_kg_head",
                        positive=True,
                    )
            cattle_revenue += annual_live_weight * unit_price
        else:
            raise InputSchemaError(
                f"{sale.label}.pricing_basis must be per_head or "
                "per_kg_live_weight"
            )

    energy = EnergyUseInput(
        electricity_kwh_year=_number(
            energy_record,
            "electricity_kwh_year",
            default=0.0,
            nonnegative=True,
        ),
        coal_t_year=_number(
            energy_record,
            "coal_t_year",
            default=0.0,
            nonnegative=True,
        ),
        diesel_l_year=_number(
            energy_record,
            "diesel_l_year",
            default=0.0,
            nonnegative=True,
        ),
        natural_gas_m3_year=_number(
            energy_record,
            "natural_gas_m3_year",
            default=0.0,
            nonnegative=True,
        ),
        electricity_ghg_parameter_id=_string(
            energy_record,
            "electricity_ghg_parameter_id",
            default=DEFAULT_ELECTRICITY_GHG_PARAMETER_ID,
        ),
    )

    enteric_stages: list[EntericStageInput] = []
    manure_stages: list[ManureStageInput] = []
    for stage in _required_records(records_by_type, "herd_stage"):
        stage_id = _record_id(stage)
        count = _whole(stage, "count_head")
        dry_matter_intake = _number(
            stage,
            "dry_matter_intake_kg_head_day",
            nonnegative=True,
        )
        ndf = _fraction(stage, "neutral_detergent_fiber_fraction")
        starch = _fraction(stage, "starch_fraction")
        fatty_acid = _fraction(stage, "fatty_acid_fraction")
        crude_protein = _fraction(stage, "crude_protein_fraction")
        non_protein_nitrogen = _fraction(
            stage,
            "non_protein_nitrogen_fraction",
        )
        ash = _fraction(stage, "ash_fraction")
        if non_protein_nitrogen > crude_protein:
            raise InputSchemaError(
                f"{stage.label}.non_protein_nitrogen_fraction cannot exceed "
                "crude_protein_fraction"
            )
        body_weight = _number(stage, "body_weight_kg", positive=True)
        enteric_stages.append(
            EntericStageInput(
                stage_id=stage_id,
                count_head=count,
                dry_matter_intake_kg_head_day=dry_matter_intake,
                neutral_detergent_fiber_fraction=ndf,
                starch_fraction=starch,
                fatty_acid_fraction=fatty_acid,
                crude_protein_fraction=crude_protein,
                non_protein_nitrogen_fraction=non_protein_nitrogen,
                ash_fraction=ash,
            )
        )
        manure_stages.append(
            ManureStageInput(
                stage_id=stage_id,
                count_head=count,
                dry_matter_intake_kg_head_day=dry_matter_intake,
                crude_protein_fraction=crude_protein,
                body_weight_kg=body_weight,
            )
        )

    pathway_records = records_by_type.get("manure_pathway", ())
    pathway_by_stage: dict[str, _Record] = {}
    for pathway in pathway_records:
        stage_id = _record_id(pathway)
        if stage_id not in PATHWAY_STAGES:
            raise InputSchemaError(
                f"unknown manure pathway stage {stage_id!r}"
            )
        if stage_id in pathway_by_stage:
            raise InputSchemaError(
                f"duplicate manure pathway stage {stage_id!r}"
            )
        pathway_by_stage[stage_id] = pathway
    missing_pathways = [
        stage for stage in PATHWAY_STAGES if stage not in pathway_by_stage
    ]
    if missing_pathways or len(pathway_by_stage) != len(PATHWAY_STAGES):
        raise InputSchemaError(
            "completed input requires exactly the manure pathway stages: "
            + ", ".join(PATHWAY_STAGES)
        )
    pathways = tuple(
        ManurePathwayInput(
            pathway_stage=stage,
            method_id=_string(pathway_by_stage[stage], "method_id"),
        )
        for stage in PATHWAY_STAGES
    )
    manure = ManureManagementInput(
        stages=tuple(manure_stages),
        pathways=pathways,
        annual_slurry_t_year=_number(
            manure_record,
            "annual_slurry_t_year",
            nonnegative=True,
        ),
        recovered_electricity_kwh_year=_number(
            manure_record,
            "recovered_electricity_kwh_year",
            default=0.0,
            nonnegative=True,
        ),
        recovered_heat_mj_year=_number(
            manure_record,
            "recovered_heat_mj_year",
            default=0.0,
            nonnegative=True,
        ),
        electricity_credit_parameter_id=_string(
            manure_record,
            "electricity_credit_parameter_id",
            default=DEFAULT_ELECTRICITY_GHG_PARAMETER_ID,
        ),
    )

    production_records = _required_records(records_by_type, "feed_production")
    production_ids = {_record_id(record) for record in production_records}
    agricultural_by_feed: dict[str, list[AgriculturalInput]] = {}
    for item in records_by_type.get("agricultural_input", ()):
        input_id = _record_id(item)
        parent_id = _identifier(
            f"{item.label}.parent_record_id",
            item.relation_id,
        )
        if parent_id not in production_ids:
            raise InputSchemaError(
                f"{item.label} references unknown feed_production {parent_id!r}"
            )
        agricultural_by_feed.setdefault(parent_id, []).append(
            AgriculturalInput(
                input_id=input_id,
                rate_kg_ha=_number(
                    item,
                    "rate_kg_ha",
                    nonnegative=True,
                ),
                ghg_factor_parameter_id=_string(
                    item,
                    "ghg_factor_parameter_id",
                ),
                n2o_factor_parameter_id=_string(
                    item,
                    "n2o_factor_parameter_id",
                ),
                nh3_factor_parameter_id=_string(
                    item,
                    "nh3_factor_parameter_id",
                ),
                phosphorus_factor_parameter_id=_string(
                    item,
                    "phosphorus_factor_parameter_id",
                ),
            )
        )

    production_items: list[FeedProductionItemInput] = []
    for feed in production_records:
        feed_id = _record_id(feed)
        production_items.append(
            FeedProductionItemInput(
                feed_id=feed_id,
                annual_feed_use_t_year=_number(
                    feed,
                    "annual_feed_use_t_year",
                    nonnegative=True,
                ),
                crop_requirement_factor=_number(
                    feed,
                    "crop_requirement_factor",
                    positive=True,
                ),
                cultivation_mass_fraction=_fraction(
                    feed,
                    "cultivation_mass_fraction",
                ),
                yield_kg_ha=_number(feed, "yield_kg_ha", positive=True),
                allocation_fraction=_fraction(
                    feed,
                    "allocation_fraction",
                    default=1.0,
                ),
                agricultural_inputs=tuple(
                    agricultural_by_feed.get(feed_id, ())
                ),
                diesel_use_kg_ha=_number(
                    feed,
                    "diesel_use_kg_ha",
                    default=0.0,
                    nonnegative=True,
                ),
                electricity_use_kwh_ha=_number(
                    feed,
                    "electricity_use_kwh_ha",
                    default=0.0,
                    nonnegative=True,
                ),
            )
        )

    field_numeric_names = (
        "seed_n_kg_year",
        "biological_fixation_n_kg_year",
        "atmospheric_n_kg_year",
        "mineral_fertilizer_n_kg_year",
        "manure_n_kg_year",
        "irrigation_n_kg_year",
        "straw_return_n_kg_year",
        "seed_p_kg_year",
        "atmospheric_p_kg_year",
        "mineral_fertilizer_p_kg_year",
        "manure_p_kg_year",
        "irrigation_p_kg_year",
        "straw_return_p_kg_year",
        "main_product_n_kg_year",
        "straw_n_kg_year",
        "main_product_p_kg_year",
        "straw_p_kg_year",
        "urea_equivalent_kg_year",
        "diesel_kg_year",
        "electricity_kwh_year",
    )
    field_items: list[FeedFieldItemInput] = []
    for field_record in _required_records(records_by_type, "feed_field"):
        feed_id = _record_id(field_record)
        if feed_id not in production_ids:
            raise InputSchemaError(
                f"{field_record.label} has no matching feed_production record"
            )
        numeric_values = {
            name: _number(
                field_record,
                name,
                default=0.0,
                nonnegative=True,
            )
            for name in field_numeric_names
        }
        field_items.append(
            FeedFieldItemInput(
                feed_id=feed_id,
                fertilizer_application_method_id=_string(
                    field_record,
                    "fertilizer_application_method_id",
                ),
                allocation_fraction=_fraction(
                    field_record,
                    "allocation_fraction",
                    default=1.0,
                ),
                electricity_ghg_parameter_id=_string(
                    field_record,
                    "electricity_ghg_parameter_id",
                    default=DEFAULT_ELECTRICITY_GHG_PARAMETER_ID,
                ),
                **numeric_values,
            )
        )

    transport_sources: list[FeedTransportSourceInput] = []
    for source in _required_records(records_by_type, "transport_source"):
        source_id = _record_id(source)
        feed_id = _string(source, "feed_id")
        if feed_id not in production_ids:
            raise InputSchemaError(
                f"{source.label}.feed_id references unknown feed_production "
                f"{feed_id!r}"
            )
        sea_fields = (
            "sea_distance_nmi",
            "sea_cargo_mass_t_year",
            "sea_emission_allocation_fraction",
        )
        has_sea = any(source.values[name].strip() for name in sea_fields)
        sea: SeaTransportInput | None = None
        if has_sea:
            sea = SeaTransportInput(
                distance_nmi=_number(
                    source,
                    "sea_distance_nmi",
                    nonnegative=True,
                ),
                cargo_mass_t_year=_number(
                    source,
                    "sea_cargo_mass_t_year",
                    nonnegative=True,
                ),
                emission_allocation_fraction=_fraction(
                    source,
                    "sea_emission_allocation_fraction",
                    default=1.0,
                ),
            )
        transport_sources.append(
            FeedTransportSourceInput(
                source_id=source_id,
                feed_id=feed_id,
                feed_mass_t_year=_number(
                    source,
                    "feed_mass_t_year",
                    nonnegative=True,
                ),
                road_distance_km=_number(
                    source,
                    "road_distance_km",
                    nonnegative=True,
                ),
                sea=sea,
            )
        )

    return FarmModelInput(
        farm_id=farm_id,
        dataset_label=dataset_label_value,
        energy=energy,
        enteric=EntericFarmInput(tuple(enteric_stages)),
        manure=manure,
        feed_production=FeedProductionInput(tuple(production_items)),
        feed_field=FeedFieldInput(tuple(field_items)),
        feed_transport=FeedTransportInput(tuple(transport_sources)),
        annual_raw_milk_t_year=annual_raw_milk,
        milk_fat_fraction=milk_fat,
        milk_protein_fraction=milk_protein,
        milk_revenue_year=milk_revenue,
        cattle_revenue_year=cattle_revenue,
    )


def load_optimization_input_csv(
    csv_path: str | Path,
) -> OptimizationModelInput:
    """Read a completed solver-neutral linear-programming input CSV."""

    rows = _read_rows(csv_path, OPTIMIZATION_INPUT_COLUMNS)
    records = _group_records(
        rows,
        OPTIMIZATION_INPUT_FIELD_SPECS,
        "related_record_id",
        "coefficient",
    )
    records_by_type = _by_type(records)
    model = _single(records_by_type, "model", "model")
    direction = _string(model, "objective_direction").lower()
    if direction not in {"minimize", "maximize"}:
        raise InputSchemaError(
            "model[model].objective_direction must be minimize or maximize"
        )
    objective = LinearObjectiveInput(
        direction=direction,
        unit=_string(model, "objective_unit"),
    )

    decisions: list[LinearDecisionInput] = []
    decision_ids: set[str] = set()
    for record in _required_records(records_by_type, "decision"):
        decision_id = _record_id(record)
        if decision_id in decision_ids:
            raise InputSchemaError(f"duplicate decision_id {decision_id!r}")
        decision_ids.add(decision_id)
        lower = _float(record, "lower_bound", default=None)
        upper = _float(record, "upper_bound", default=None)
        if lower is not None and upper is not None and lower > upper:
            raise InputSchemaError(
                f"{record.label}.lower_bound cannot exceed upper_bound"
            )
        decisions.append(
            LinearDecisionInput(
                decision_id=decision_id,
                lower_bound=lower,
                upper_bound=upper,
                objective_coefficient=_number(
                    record,
                    "objective_coefficient",
                ),
                unit=_string(record, "decision_unit"),
            )
        )

    constraints: list[LinearConstraintInput] = []
    constraint_ids: set[str] = set()
    for record in _required_records(records_by_type, "constraint"):
        constraint_id = _record_id(record)
        if constraint_id in constraint_ids:
            raise InputSchemaError(f"duplicate constraint_id {constraint_id!r}")
        constraint_ids.add(constraint_id)
        lower = _float(record, "lower_bound", default=None)
        upper = _float(record, "upper_bound", default=None)
        if lower is None and upper is None:
            raise InputSchemaError(
                f"{record.label} requires at least one bound"
            )
        if lower is not None and upper is not None and lower > upper:
            raise InputSchemaError(
                f"{record.label}.lower_bound cannot exceed upper_bound"
            )
        constraints.append(
            LinearConstraintInput(
                constraint_id=constraint_id,
                lower_bound=lower,
                upper_bound=upper,
                unit=_string(record, "constraint_unit"),
            )
        )

    coefficients: list[LinearCoefficientInput] = []
    coefficient_pairs: set[tuple[str, str]] = set()
    referenced_decisions: set[str] = set()
    referenced_constraints: set[str] = set()
    for record in _required_records(records_by_type, "coefficient"):
        constraint_id = _record_id(record)
        decision_id = _identifier(
            f"{record.label}.related_record_id",
            record.relation_id,
        )
        if constraint_id not in constraint_ids:
            raise InputSchemaError(
                f"{record.label} references unknown constraint {constraint_id!r}"
            )
        if decision_id not in decision_ids:
            raise InputSchemaError(
                f"{record.label} references unknown decision {decision_id!r}"
            )
        pair = (constraint_id, decision_id)
        if pair in coefficient_pairs:
            raise InputSchemaError(
                f"duplicate coefficient for {constraint_id!r}/{decision_id!r}"
            )
        coefficient_pairs.add(pair)
        referenced_constraints.add(constraint_id)
        referenced_decisions.add(decision_id)
        coefficients.append(
            LinearCoefficientInput(
                constraint_id=constraint_id,
                decision_id=decision_id,
                coefficient=_number(record, "coefficient"),
            )
        )

    unused_decisions = decision_ids - referenced_decisions
    unused_constraints = constraint_ids - referenced_constraints
    if unused_decisions:
        raise InputSchemaError(
            "decision(s) without any constraint coefficient: "
            + ", ".join(sorted(unused_decisions))
        )
    if unused_constraints:
        raise InputSchemaError(
            "constraint(s) without any coefficient: "
            + ", ".join(sorted(unused_constraints))
        )

    return OptimizationModelInput(
        objective=objective,
        decisions=tuple(decisions),
        constraints=tuple(constraints),
        coefficients=tuple(coefficients),
    )
