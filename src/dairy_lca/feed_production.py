"""Feed demand, crop area, upstream inputs, and production-energy inventory."""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import ParameterCatalog
from .exceptions import InvalidModelInputError
from .results import AppliedParameter, ImpactTotals, sum_impacts
from .validation import fraction, identifier, number

KG_PER_TONNE = 1000.0
M2_PER_HA = 10000.0
KWH_TO_MJ = 3.6
N_IN_N2O_FRACTION = 28.0 / 44.0
N_IN_NH3_FRACTION = 14.0 / 17.0


@dataclass(frozen=True)
class AgriculturalInput:
    """One crop input rate and its externally configured upstream factors."""

    input_id: str
    rate_kg_ha: float
    ghg_factor_parameter_id: str
    n2o_factor_parameter_id: str
    nh3_factor_parameter_id: str
    phosphorus_factor_parameter_id: str


@dataclass(frozen=True)
class FeedProductionItemInput:
    feed_id: str
    annual_feed_use_t_year: float
    crop_requirement_factor: float
    cultivation_mass_fraction: float
    yield_kg_ha: float
    allocation_fraction: float = 1.0
    agricultural_inputs: tuple[AgriculturalInput, ...] = ()
    diesel_use_kg_ha: float = 0.0
    electricity_use_kwh_ha: float = 0.0


@dataclass(frozen=True)
class FeedProductionInput:
    feeds: tuple[FeedProductionItemInput, ...]


@dataclass(frozen=True)
class AgriculturalInputResult:
    input_id: str
    annual_amount_kg_year: float
    impacts: ImpactTotals


@dataclass(frozen=True)
class FeedProductionItemResult:
    feed_id: str
    crop_reference_t_year: float
    cultivated_crop_t_year: float
    cultivated_area_ha: float
    allocated_land_ha: float
    agricultural_inputs: tuple[AgriculturalInputResult, ...]
    crop_energy_mj_year: float
    upstream_impacts: ImpactTotals
    impacts: ImpactTotals


@dataclass(frozen=True)
class FeedProductionResult:
    feeds: tuple[FeedProductionItemResult, ...]
    upstream_impacts: ImpactTotals
    impacts: ImpactTotals
    applied_parameters: tuple[AppliedParameter, ...]


class FeedProductionCalculator:
    """Calculate Production crop activities without crop-specific defaults."""

    def __init__(self, catalog: ParameterCatalog):
        self.catalog = catalog

    def calculate(self, activity: FeedProductionInput) -> FeedProductionResult:
        if not activity.feeds:
            raise InvalidModelInputError("at least one feed production row is required")
        applied: dict[str, AppliedParameter] = {}

        def use(parameter_id: str, expected_unit: str | None = None) -> float:
            normalized = identifier("factor parameter ID", parameter_id)
            value = self.catalog.model_value(
                normalized, expected_unit=expected_unit
            )
            applied.setdefault(
                normalized, AppliedParameter.from_catalog(self.catalog, normalized)
            )
            return value

        results: list[FeedProductionItemResult] = []
        seen: set[str] = set()
        for row in activity.feeds:
            feed_id = identifier("feed_id", row.feed_id)
            if feed_id in seen:
                raise InvalidModelInputError(f"duplicate feed production row {feed_id!r}")
            seen.add(feed_id)
            feed_mass = number(
                f"{feed_id}.annual_feed_use_t_year",
                row.annual_feed_use_t_year,
                nonnegative=True,
            )
            requirement = number(
                f"{feed_id}.crop_requirement_factor",
                row.crop_requirement_factor,
                positive=True,
            )
            cultivation = fraction(
                f"{feed_id}.cultivation_mass_fraction",
                row.cultivation_mass_fraction,
            )
            yield_kg_ha = number(
                f"{feed_id}.yield_kg_ha", row.yield_kg_ha, positive=True
            )
            allocation = fraction(
                f"{feed_id}.allocation_fraction", row.allocation_fraction
            )
            crop_reference = feed_mass * requirement
            cultivated_crop = crop_reference * cultivation
            area = cultivated_crop * KG_PER_TONNE / yield_kg_ha

            input_results: list[AgriculturalInputResult] = []
            input_ids: set[str] = set()
            for item in row.agricultural_inputs:
                input_id = identifier("input_id", item.input_id)
                if input_id in input_ids:
                    raise InvalidModelInputError(
                        f"{feed_id} has duplicate agricultural input {input_id!r}"
                    )
                input_ids.add(input_id)
                annual_amount = number(
                    f"{feed_id}.{input_id}.rate_kg_ha",
                    item.rate_kg_ha,
                    nonnegative=True,
                ) * area
                ghg = (
                    annual_amount
                    * use(item.ghg_factor_parameter_id, "kg CO2e/kg input")
                    * allocation
                )
                n2o_g = (
                    annual_amount
                    * use(item.n2o_factor_parameter_id, "g N2O/kg input")
                    * allocation
                )
                nh3_g = (
                    annual_amount
                    * use(item.nh3_factor_parameter_id, "g NH3/kg input")
                    * allocation
                )
                phosphorus_g = (
                    annual_amount
                    * use(item.phosphorus_factor_parameter_id, "g P/kg input")
                    * allocation
                )
                nitrogen_g = (
                    n2o_g * N_IN_N2O_FRACTION + nh3_g * N_IN_NH3_FRACTION
                )
                input_results.append(
                    AgriculturalInputResult(
                        input_id=input_id,
                        annual_amount_kg_year=annual_amount,
                        impacts=ImpactTotals(
                            ghg, nitrogen_g, phosphorus_g, 0.0, 0.0, 0.0
                        ),
                    )
                )

            diesel_kg = number(
                f"{feed_id}.diesel_use_kg_ha",
                row.diesel_use_kg_ha,
                nonnegative=True,
            ) * area
            electricity_kwh = number(
                f"{feed_id}.electricity_use_kwh_ha",
                row.electricity_use_kwh_ha,
                nonnegative=True,
            ) * area
            if diesel_kg:
                density = use("energy.diesel_density_kg_l")
                if density <= 0:
                    raise InvalidModelInputError(
                        "energy.diesel_density_kg_l must be > 0"
                    )
                diesel_energy = (
                    diesel_kg
                    / density
                    * use("energy.diesel_energy_content_mj_l")
                    * allocation
                )
            else:
                diesel_energy = 0.0
            crop_energy = electricity_kwh * KWH_TO_MJ * allocation + diesel_energy
            upstream = sum_impacts(item.impacts for item in input_results)
            land_m2 = area * allocation * M2_PER_HA
            impacts = upstream + ImpactTotals(
                0.0, 0.0, 0.0, crop_energy, land_m2, 0.0
            )
            results.append(
                FeedProductionItemResult(
                    feed_id=feed_id,
                    crop_reference_t_year=crop_reference,
                    cultivated_crop_t_year=cultivated_crop,
                    cultivated_area_ha=area,
                    allocated_land_ha=area * allocation,
                    agricultural_inputs=tuple(input_results),
                    crop_energy_mj_year=crop_energy,
                    upstream_impacts=upstream,
                    impacts=impacts,
                )
            )

        return FeedProductionResult(
            feeds=tuple(results),
            upstream_impacts=sum_impacts(row.upstream_impacts for row in results),
            impacts=sum_impacts(row.impacts for row in results),
            applied_parameters=tuple(applied.values()),
        )


def calculate_feed_production(
    catalog: ParameterCatalog, activity: FeedProductionInput
) -> FeedProductionResult:
    return FeedProductionCalculator(catalog).calculate(activity)
