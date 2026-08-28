"""Shared result containers without private-source or local-path provenance."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .catalog import ParameterCatalog


@dataclass(frozen=True)
class AppliedParameter:
    parameter_id: str
    value: float
    unit: str
    citation: str | None = None

    @classmethod
    def from_catalog(cls, catalog: ParameterCatalog, parameter_id: str) -> "AppliedParameter":
        parameter = catalog.parameter(parameter_id)
        return cls(
            parameter_id=parameter.parameter_id,
            value=parameter.value,
            unit=parameter.unit,
            citation=parameter.citation,
        )


@dataclass(frozen=True)
class ImpactTotals:
    ghg_kg_co2e_year: float
    nitrogen_g_year: float
    phosphorus_g_year: float
    nreu_mj_year: float
    land_m2_year: float
    sulfur_dioxide_kg_year: float

    @classmethod
    def zero(cls) -> "ImpactTotals":
        return cls(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    def __add__(self, other: "ImpactTotals") -> "ImpactTotals":
        return ImpactTotals(
            self.ghg_kg_co2e_year + other.ghg_kg_co2e_year,
            self.nitrogen_g_year + other.nitrogen_g_year,
            self.phosphorus_g_year + other.phosphorus_g_year,
            self.nreu_mj_year + other.nreu_mj_year,
            self.land_m2_year + other.land_m2_year,
            self.sulfur_dioxide_kg_year + other.sulfur_dioxide_kg_year,
        )

    def scaled(self, factor: float) -> "ImpactTotals":
        return ImpactTotals(
            self.ghg_kg_co2e_year * factor,
            self.nitrogen_g_year * factor,
            self.phosphorus_g_year * factor,
            self.nreu_mj_year * factor,
            self.land_m2_year * factor,
            self.sulfur_dioxide_kg_year * factor,
        )

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def sum_impacts(values: Iterable[ImpactTotals]) -> ImpactTotals:
    total = ImpactTotals.zero()
    for value in values:
        total = total + value
    return total


def dataclass_dict(value: object) -> dict[str, Any]:
    return asdict(value)
