"""Road and sea transport equations for annual feed procurement."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from .catalog import ParameterCatalog
from .exceptions import InvalidModelInputError
from .results import AppliedParameter, ImpactTotals, sum_impacts
from .validation import fraction, identifier, number

KG_PER_TONNE = 1000.0
GRAMS_PER_TONNE = 1_000_000.0
MJ_PER_TJ = 1_000_000.0
KWH_TO_MJ = 3.6
N_IN_N2O = 28.0 / 44.0


@dataclass(frozen=True)
class SeaTransportInput:
    distance_nmi: float
    cargo_mass_t_year: float
    emission_allocation_fraction: float = 1.0


@dataclass(frozen=True)
class FeedTransportSourceInput:
    source_id: str
    feed_id: str
    feed_mass_t_year: float
    road_distance_km: float
    sea: SeaTransportInput | None = None


@dataclass(frozen=True)
class FeedTransportInput:
    sources: tuple[FeedTransportSourceInput, ...]


@dataclass(frozen=True)
class RoadTransportResult:
    trip_count: float
    diesel_l_year: float
    diesel_kg_year: float
    n2o_kg_year: float
    impacts: ImpactTotals


@dataclass(frozen=True)
class SeaTransportResult:
    voyage_count: int
    engine_kwh_per_voyage: float
    gross_hfo_t_year: float
    allocated_hfo_t_year: float
    co2_kg_year: float
    ch4_kg_year: float
    n2o_kg_year: float
    nox_kg_year: float
    carbon_monoxide_kg_year: float
    sox_kg_year: float
    impacts: ImpactTotals


@dataclass(frozen=True)
class FeedTransportSourceResult:
    source_id: str
    feed_id: str
    feed_mass_t_year: float
    road: RoadTransportResult
    sea: SeaTransportResult | None
    impacts: ImpactTotals


@dataclass(frozen=True)
class FeedTransportResult:
    sources: tuple[FeedTransportSourceResult, ...]
    impacts: ImpactTotals
    applied_parameters: tuple[AppliedParameter, ...]


class FeedTransportCalculator:
    """Apply Production freight equations using external vehicle parameters."""

    def __init__(self, catalog: ParameterCatalog):
        self.catalog = catalog

    def calculate(self, activity: FeedTransportInput) -> FeedTransportResult:
        if not activity.sources:
            raise InvalidModelInputError("at least one feed transport source is required")
        applied: dict[str, AppliedParameter] = {}

        def use(parameter_id: str) -> float:
            value = self.catalog.model_value(parameter_id)
            applied.setdefault(
                parameter_id, AppliedParameter.from_catalog(self.catalog, parameter_id)
            )
            return value

        payload = use("transport.road_payload_t")
        if payload <= 0:
            raise InvalidModelInputError("transport.road_payload_t must be > 0")
        results: list[FeedTransportSourceResult] = []
        seen: set[str] = set()
        for row in activity.sources:
            source_id = identifier("source_id", row.source_id)
            feed_id = identifier("feed_id", row.feed_id)
            if source_id in seen:
                raise InvalidModelInputError(
                    f"duplicate transport source {source_id!r}"
                )
            seen.add(source_id)
            mass = number(
                f"{source_id}.feed_mass_t_year", row.feed_mass_t_year, nonnegative=True
            )
            road_distance = number(
                f"{source_id}.road_distance_km",
                row.road_distance_km,
                nonnegative=True,
            )
            trips = mass / payload
            diesel_l = (
                trips
                * road_distance
                * use("transport.road_loaded_fuel_l_100km")
                / 100.0
            )
            diesel_kg = diesel_l * use("energy.diesel_density_kg_l")
            road_energy = diesel_l * use("energy.diesel_energy_content_mj_l")
            road_n2o = (
                road_energy
                / MJ_PER_TJ
                * use("transport.diesel_n2o_kg_per_tj")
            )
            road_ghg = (
                diesel_kg * use("energy.diesel_ghg_factor")
                + road_n2o * use("characterization.gwp_n2o_100yr")
            )
            road_impacts = ImpactTotals(
                road_ghg,
                road_n2o * N_IN_N2O * KG_PER_TONNE,
                0.0,
                road_energy,
                0.0,
                0.0,
            )
            road_result = RoadTransportResult(
                trip_count=trips,
                diesel_l_year=diesel_l,
                diesel_kg_year=diesel_kg,
                n2o_kg_year=road_n2o,
                impacts=road_impacts,
            )

            sea_result: SeaTransportResult | None = None
            sea_impacts = ImpactTotals.zero()
            if row.sea is not None:
                sea_capacity = use("transport.sea_effective_capacity_t")
                sea_speed = use("transport.sea_speed_kn")
                if sea_capacity <= 0 or sea_speed <= 0:
                    raise InvalidModelInputError(
                        "sea capacity and sea speed must be > 0"
                    )
                distance = number(
                    f"{source_id}.sea.distance_nmi",
                    row.sea.distance_nmi,
                    nonnegative=True,
                )
                cargo = number(
                    f"{source_id}.sea.cargo_mass_t_year",
                    row.sea.cargo_mass_t_year,
                    nonnegative=True,
                )
                allocation = fraction(
                    f"{source_id}.sea.emission_allocation_fraction",
                    row.sea.emission_allocation_fraction,
                )
                voyages = ceil(cargo / sea_capacity) if cargo else 0
                engine_kwh = (
                    use("transport.sea_load_factor")
                    * use("transport.sea_engine_power_kw")
                    * use("transport.sea_load_power_correction_factor")
                    * distance
                    / sea_speed
                )
                hfo_per_voyage = (
                    engine_kwh
                    * use("transport.hfo_specific_fuel_g_kwh")
                    / GRAMS_PER_TONNE
                )
                gross_hfo = hfo_per_voyage * voyages
                allocated_hfo = gross_hfo * allocation
                co2 = allocated_hfo * use("transport.hfo_co2_kg_t")
                ch4 = allocated_hfo * use("transport.hfo_ch4_kg_t")
                n2o = allocated_hfo * use("transport.hfo_n2o_kg_t")
                nox = allocated_hfo * use("transport.hfo_nox_kg_t")
                carbon_monoxide = allocated_hfo * use("transport.hfo_co_kg_t")
                sox = allocated_hfo * use("transport.hfo_sox_kg_t")
                sea_ghg = (
                    co2
                    + ch4 * use("characterization.gwp_ch4_fossil_100yr")
                    + n2o * use("characterization.gwp_n2o_100yr")
                )
                sea_energy = engine_kwh * voyages * allocation * KWH_TO_MJ
                sea_impacts = ImpactTotals(
                    sea_ghg,
                    n2o * N_IN_N2O * KG_PER_TONNE,
                    0.0,
                    sea_energy,
                    0.0,
                    sox,
                )
                sea_result = SeaTransportResult(
                    voyage_count=voyages,
                    engine_kwh_per_voyage=engine_kwh,
                    gross_hfo_t_year=gross_hfo,
                    allocated_hfo_t_year=allocated_hfo,
                    co2_kg_year=co2,
                    ch4_kg_year=ch4,
                    n2o_kg_year=n2o,
                    nox_kg_year=nox,
                    carbon_monoxide_kg_year=carbon_monoxide,
                    sox_kg_year=sox,
                    impacts=sea_impacts,
                )

            total = road_impacts + sea_impacts
            results.append(
                FeedTransportSourceResult(
                    source_id=source_id,
                    feed_id=feed_id,
                    feed_mass_t_year=mass,
                    road=road_result,
                    sea=sea_result,
                    impacts=total,
                )
            )

        return FeedTransportResult(
            sources=tuple(results),
            impacts=sum_impacts(row.impacts for row in results),
            applied_parameters=tuple(applied.values()),
        )


def calculate_feed_transport(
    catalog: ParameterCatalog, activity: FeedTransportInput
) -> FeedTransportResult:
    return FeedTransportCalculator(catalog).calculate(activity)
