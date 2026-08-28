"""Field nitrogen, phosphorus, energy, and soil-emission calculations."""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import ParameterCatalog
from .exceptions import InvalidModelInputError
from .results import AppliedParameter, ImpactTotals, sum_impacts
from .validation import fraction, identifier, number

MJ_PER_TJ = 1_000_000.0
N2O_FROM_N = 44.0 / 28.0
N_IN_N2O = 28.0 / 44.0
GRAMS_PER_KG = 1000.0


@dataclass(frozen=True)
class FeedFieldItemInput:
    """Annual nutrient and energy inventory for one cultivated feed item."""

    feed_id: str
    fertilizer_application_method_id: str
    allocation_fraction: float = 1.0
    seed_n_kg_year: float = 0.0
    biological_fixation_n_kg_year: float = 0.0
    atmospheric_n_kg_year: float = 0.0
    mineral_fertilizer_n_kg_year: float = 0.0
    manure_n_kg_year: float = 0.0
    irrigation_n_kg_year: float = 0.0
    straw_return_n_kg_year: float = 0.0
    seed_p_kg_year: float = 0.0
    atmospheric_p_kg_year: float = 0.0
    mineral_fertilizer_p_kg_year: float = 0.0
    manure_p_kg_year: float = 0.0
    irrigation_p_kg_year: float = 0.0
    straw_return_p_kg_year: float = 0.0
    main_product_n_kg_year: float = 0.0
    straw_n_kg_year: float = 0.0
    main_product_p_kg_year: float = 0.0
    straw_p_kg_year: float = 0.0
    urea_equivalent_kg_year: float = 0.0
    diesel_kg_year: float = 0.0
    electricity_kwh_year: float = 0.0
    electricity_ghg_parameter_id: str = "energy.electricity_ghg_factor"


@dataclass(frozen=True)
class FeedFieldInput:
    feeds: tuple[FeedFieldItemInput, ...]


@dataclass(frozen=True)
class FieldNBalance:
    total_input_kg_year: float
    nh3_n_kg_year: float
    n2o_n_kg_year: float
    nox_n_kg_year: float
    runoff_n_kg_year: float
    leaching_balance_raw_kg_year: float
    leaching_n_kg_year: float
    energy_n2o_n_kg_year: float
    allocated_reactive_n_kg_year: float


@dataclass(frozen=True)
class FieldPBalance:
    total_input_kg_year: float
    runoff_p_kg_year: float
    leaching_balance_raw_kg_year: float
    leaching_p_kg_year: float
    allocated_p_kg_year: float


@dataclass(frozen=True)
class FieldGHG:
    urea_co2_kg_year: float
    direct_n2o_kg_year: float
    indirect_n2o_kg_year: float
    soil_ghg_kg_co2e_year: float
    energy_ghg_kg_co2e_year: float
    total_ghg_kg_co2e_year: float


@dataclass(frozen=True)
class FeedFieldItemResult:
    feed_id: str
    nitrogen: FieldNBalance
    phosphorus: FieldPBalance
    ghg: FieldGHG
    impacts: ImpactTotals


@dataclass(frozen=True)
class FeedFieldResult:
    feeds: tuple[FeedFieldItemResult, ...]
    impacts: ImpactTotals
    applied_parameters: tuple[AppliedParameter, ...]


class FeedFieldCalculator:
    """Apply explicit annual field balances with no crop or region lookup."""

    def __init__(self, catalog: ParameterCatalog):
        self.catalog = catalog

    def calculate(self, activity: FeedFieldInput) -> FeedFieldResult:
        if not activity.feeds:
            raise InvalidModelInputError("at least one feed field row is required")
        applied: dict[str, AppliedParameter] = {}

        def use(parameter_id: str, expected_unit: str | None = None) -> float:
            value = self.catalog.model_value(
                parameter_id, expected_unit=expected_unit
            )
            applied.setdefault(
                parameter_id, AppliedParameter.from_catalog(self.catalog, parameter_id)
            )
            return value

        results: list[FeedFieldItemResult] = []
        seen: set[str] = set()
        for row in activity.feeds:
            feed_id = identifier("feed_id", row.feed_id)
            if feed_id in seen:
                raise InvalidModelInputError(f"duplicate feed field row {feed_id!r}")
            seen.add(feed_id)
            method = identifier(
                f"{feed_id}.fertilizer_application_method_id",
                row.fertilizer_application_method_id,
            )
            allocation = fraction(
                f"{feed_id}.allocation_fraction", row.allocation_fraction
            )

            def annual(field_name: str) -> float:
                return number(
                    f"{feed_id}.{field_name}",
                    getattr(row, field_name),
                    nonnegative=True,
                )

            mineral_n = annual("mineral_fertilizer_n_kg_year")
            total_n = sum(
                annual(name)
                for name in (
                    "seed_n_kg_year",
                    "biological_fixation_n_kg_year",
                    "atmospheric_n_kg_year",
                    "mineral_fertilizer_n_kg_year",
                    "manure_n_kg_year",
                    "irrigation_n_kg_year",
                    "straw_return_n_kg_year",
                )
            )
            total_p = sum(
                annual(name)
                for name in (
                    "seed_p_kg_year",
                    "atmospheric_p_kg_year",
                    "mineral_fertilizer_p_kg_year",
                    "manure_p_kg_year",
                    "irrigation_p_kg_year",
                    "straw_return_p_kg_year",
                )
            )
            main_n = annual("main_product_n_kg_year")
            straw_n = annual("straw_n_kg_year")
            main_p = annual("main_product_p_kg_year")
            straw_p = annual("straw_p_kg_year")

            method_prefix = f"field.application.{method}"
            nh3_n = mineral_n * use(
                f"{method_prefix}.nh3_fraction", "fraction"
            )
            n2o_n = mineral_n * use(
                f"{method_prefix}.n2o_fraction", "fraction"
            )
            nox_n = n2o_n * use("field.nox_from_n2o_n_factor")
            runoff_n = total_n * use("field.n_runoff_fraction")
            leaching_n_raw = (
                total_n - main_n - straw_n - nh3_n - n2o_n - nox_n - runoff_n
            ) * use("field.n_leaching_fraction")
            leaching_n = max(leaching_n_raw, 0.0)

            runoff_p = total_p * use("field.p_runoff_fraction")
            leaching_p_raw = (
                total_p - main_p - straw_p - runoff_p
            ) * use("field.p_leaching_fraction")
            leaching_p = max(leaching_p_raw, 0.0)

            diesel_kg = annual("diesel_kg_year")
            electricity_kwh = annual("electricity_kwh_year")
            if diesel_kg:
                density = use("energy.diesel_density_kg_l")
                if density <= 0:
                    raise InvalidModelInputError(
                        "energy.diesel_density_kg_l must be > 0"
                    )
                diesel_mj = (
                    diesel_kg
                    / density
                    * use("energy.diesel_energy_content_mj_l")
                )
                energy_n = (
                    diesel_mj
                    / MJ_PER_TJ
                    * use("transport.diesel_n2o_kg_per_tj")
                    * N_IN_N2O
                )
                diesel_ghg = diesel_kg * use("energy.diesel_ghg_factor")
            else:
                energy_n = 0.0
                diesel_ghg = 0.0

            reactive_n = (
                nh3_n + n2o_n + nox_n + runoff_n + leaching_n + energy_n
            ) * allocation
            p_footprint = (runoff_p + leaching_p) * allocation

            urea_co2 = annual("urea_equivalent_kg_year") * use(
                "field.urea_co2_factor"
            )
            direct_n2o = n2o_n * N2O_FROM_N
            indirect_n2o = (nh3_n + nox_n + runoff_n + leaching_n) * N2O_FROM_N
            soil_ghg = (
                urea_co2
                + (direct_n2o + indirect_n2o)
                * use("characterization.gwp_n2o_100yr")
            ) * allocation
            electricity_factor_id = identifier(
                f"{feed_id}.electricity_ghg_parameter_id",
                row.electricity_ghg_parameter_id,
            )
            electricity_ghg = (
                electricity_kwh * use(electricity_factor_id, "kg CO2e/kWh")
                if electricity_kwh
                else 0.0
            )
            energy_ghg = (diesel_ghg + electricity_ghg) * allocation
            total_ghg = soil_ghg + energy_ghg
            impacts = ImpactTotals(
                ghg_kg_co2e_year=total_ghg,
                nitrogen_g_year=reactive_n * GRAMS_PER_KG,
                phosphorus_g_year=p_footprint * GRAMS_PER_KG,
                nreu_mj_year=0.0,
                land_m2_year=0.0,
                sulfur_dioxide_kg_year=0.0,
            )
            results.append(
                FeedFieldItemResult(
                    feed_id=feed_id,
                    nitrogen=FieldNBalance(
                        total_input_kg_year=total_n,
                        nh3_n_kg_year=nh3_n,
                        n2o_n_kg_year=n2o_n,
                        nox_n_kg_year=nox_n,
                        runoff_n_kg_year=runoff_n,
                        leaching_balance_raw_kg_year=leaching_n_raw,
                        leaching_n_kg_year=leaching_n,
                        energy_n2o_n_kg_year=energy_n,
                        allocated_reactive_n_kg_year=reactive_n,
                    ),
                    phosphorus=FieldPBalance(
                        total_input_kg_year=total_p,
                        runoff_p_kg_year=runoff_p,
                        leaching_balance_raw_kg_year=leaching_p_raw,
                        leaching_p_kg_year=leaching_p,
                        allocated_p_kg_year=p_footprint,
                    ),
                    ghg=FieldGHG(
                        urea_co2_kg_year=urea_co2,
                        direct_n2o_kg_year=direct_n2o,
                        indirect_n2o_kg_year=indirect_n2o,
                        soil_ghg_kg_co2e_year=soil_ghg,
                        energy_ghg_kg_co2e_year=energy_ghg,
                        total_ghg_kg_co2e_year=total_ghg,
                    ),
                    impacts=impacts,
                )
            )

        return FeedFieldResult(
            feeds=tuple(results),
            impacts=sum_impacts(row.impacts for row in results),
            applied_parameters=tuple(applied.values()),
        )


def calculate_feed_field(
    catalog: ParameterCatalog, activity: FeedFieldInput
) -> FeedFieldResult:
    return FeedFieldCalculator(catalog).calculate(activity)
