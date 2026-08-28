"""Public parameter loading and validation with no study defaults."""

from __future__ import annotations

import csv
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from numbers import Real
from pathlib import Path
from types import MappingProxyType
from typing import Any, TextIO

from .exceptions import ParameterSchemaError, UnitMismatchError, UnknownParameterError
from .parameter_schema import STATIC_PARAMETER_UNITS, registered_parameter_unit

CSV_REQUIRED_FIELDS = frozenset({"parameter_id", "value", "unit"})
CSV_ALLOWED_FIELDS = CSV_REQUIRED_FIELDS | frozenset(
    {"citation", "required_by", "description"}
)


@dataclass(frozen=True)
class Parameter:
    parameter_id: str
    value: float
    unit: str = ""
    citation: str | None = None

    @classmethod
    def from_value(cls, parameter_id: str, raw: object) -> "Parameter":
        if isinstance(raw, Mapping):
            unknown = set(raw) - {"value", "unit", "citation"}
            if unknown:
                raise ParameterSchemaError(
                    f"{parameter_id} has unknown field(s): " + ", ".join(sorted(unknown))
                )
            if "value" not in raw:
                raise ParameterSchemaError(f"{parameter_id} is missing value")
            value = raw["value"]
            unit = str(raw.get("unit") or "").strip()
            citation = raw.get("citation")
            if citation is not None:
                citation = str(citation).strip() or None
        else:
            value = raw
            unit = ""
            citation = None
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ParameterSchemaError(f"{parameter_id}.value must be numeric")
        numeric = float(value)
        if not isfinite(numeric):
            raise ParameterSchemaError(f"{parameter_id}.value must be finite")
        return cls(parameter_id, numeric, unit, citation)


class ParameterCatalog:
    """Read-only mapping of user-supplied parameter IDs to numeric values."""

    def __init__(self, parameters: Mapping[str, object]):
        if not isinstance(parameters, Mapping):
            raise ParameterSchemaError("parameters must be a mapping")
        parsed: dict[str, Parameter] = {}
        for raw_id, raw_value in parameters.items():
            parameter_id = str(raw_id).strip()
            if not parameter_id:
                raise ParameterSchemaError("parameter IDs must be non-empty")
            if parameter_id in parsed:
                raise ParameterSchemaError(f"duplicate parameter ID {parameter_id!r}")
            parsed[parameter_id] = Parameter.from_value(parameter_id, raw_value)
        self._parameters = MappingProxyType(parsed)

    @classmethod
    def from_csv(cls, path: str | Path) -> "ParameterCatalog":
        """Load a UTF-8 CSV after strict header, value, unit, and duplicate checks."""

        csv_path = Path(path)
        try:
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                return cls.from_csv_stream(handle)
        except OSError as exc:
            raise ParameterSchemaError(
                f"cannot read parameter CSV {csv_path.name!r}: {exc.strerror or exc}"
            ) from exc

    @classmethod
    def from_csv_stream(cls, handle: TextIO) -> "ParameterCatalog":
        """Load parameter rows from an open text stream; useful for validation tools."""

        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ParameterSchemaError("parameter CSV is missing a header row")
        fieldnames = tuple(name.strip() for name in reader.fieldnames)
        if len(set(fieldnames)) != len(fieldnames):
            raise ParameterSchemaError("parameter CSV has duplicate header fields")
        missing_fields = CSV_REQUIRED_FIELDS - set(fieldnames)
        unknown_fields = set(fieldnames) - CSV_ALLOWED_FIELDS
        if missing_fields:
            raise ParameterSchemaError(
                "parameter CSV is missing field(s): "
                + ", ".join(sorted(missing_fields))
            )
        if unknown_fields:
            raise ParameterSchemaError(
                "parameter CSV has unknown field(s): "
                + ", ".join(sorted(unknown_fields))
            )
        reader.fieldnames = list(fieldnames)

        parameters: dict[str, object] = {}
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise ParameterSchemaError(
                    f"parameter CSV row {row_number} has too many columns"
                )
            if not any(str(value or "").strip() for value in row.values()):
                continue
            parameter_id = str(row.get("parameter_id") or "").strip()
            if not parameter_id:
                raise ParameterSchemaError(
                    f"parameter CSV row {row_number} has a blank parameter_id"
                )
            if "<" in parameter_id or ">" in parameter_id:
                raise ParameterSchemaError(
                    f"parameter CSV row {row_number} ({parameter_id}) contains "
                    "an unresolved placeholder"
                )
            if parameter_id in parameters:
                raise ParameterSchemaError(
                    f"parameter CSV row {row_number} duplicates {parameter_id!r}"
                )
            raw_value = str(row.get("value") or "").strip()
            if not raw_value:
                raise ParameterSchemaError(
                    f"parameter CSV row {row_number} ({parameter_id}) has a blank value"
                )
            try:
                value = float(raw_value)
            except ValueError as exc:
                raise ParameterSchemaError(
                    f"parameter CSV row {row_number} ({parameter_id}) has a non-numeric value"
                ) from exc
            unit = str(row.get("unit") or "").strip()
            if not unit:
                raise ParameterSchemaError(
                    f"parameter CSV row {row_number} ({parameter_id}) has a blank unit"
                )
            citation = str(row.get("citation") or "").strip() or None
            parameters[parameter_id] = {
                "value": value,
                "unit": unit,
                "citation": citation,
            }
        if not parameters:
            raise ParameterSchemaError("parameter CSV contains no parameter rows")
        return cls(parameters)

    def __contains__(self, parameter_id: object) -> bool:
        return parameter_id in self._parameters

    def __len__(self) -> int:
        return len(self._parameters)

    def parameter(self, parameter_id: str, *, expected_unit: str | None = None) -> Parameter:
        try:
            parameter = self._parameters[parameter_id]
        except KeyError as exc:
            raise UnknownParameterError(f"missing required parameter {parameter_id!r}") from exc
        if expected_unit is not None and parameter.unit != expected_unit:
            raise UnitMismatchError(
                f"{parameter_id} has unit {parameter.unit!r}; expected {expected_unit!r}"
            )
        return parameter

    def value(self, parameter_id: str, *, expected_unit: str | None = None) -> float:
        return self.parameter(parameter_id, expected_unit=expected_unit).value

    def model_value(
        self,
        parameter_id: str,
        *,
        expected_unit: str | None = None,
    ) -> float:
        """Read a model parameter and require its registered or explicit unit."""

        unit = expected_unit or registered_parameter_unit(parameter_id)
        if unit is None:
            raise ParameterSchemaError(
                f"no unit rule is registered for parameter {parameter_id!r}"
            )
        return self.value(parameter_id, expected_unit=unit)

    def require(self, parameter_ids: list[str] | tuple[str, ...]) -> None:
        for parameter_id in parameter_ids:
            self.parameter(parameter_id)

    def validate_required(
        self, expected_units: Mapping[str, str] = STATIC_PARAMETER_UNITS
    ) -> None:
        """Require every named parameter and enforce its exact public unit."""

        for parameter_id, expected_unit in expected_units.items():
            self.parameter(parameter_id, expected_unit=expected_unit)

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {
            parameter_id: {
                "value": parameter.value,
                "unit": parameter.unit,
                "citation": parameter.citation,
            }
            for parameter_id, parameter in self._parameters.items()
        }
