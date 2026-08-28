"""Farm aggregation, FPCM normalization, and revenue-based allocation."""

from __future__ import annotations

from dataclasses import dataclass, fields
from math import isfinite

from .catalog import ParameterCatalog
from .exceptions import InvalidModelInputError
from .results import AppliedParameter, ImpactTotals, sum_impacts
from .validation import fraction, identifier, number

KG_PER_TONNE = 1000.0


@dataclass(frozen=True)
class ProcessImpact:
    process_id: str
    impacts: ImpactTotals


@dataclass(frozen=True)
class OverallResultsInput:
    annual_raw_milk_t_year: float
    milk_fat_fraction: float
    milk_protein_fraction: float
    milk_revenue_year: float
    cattle_revenue_year: float
    processes: tuple[ProcessImpact, ...]


@dataclass(frozen=True)
class CharacterizedImpacts:
    eutrophication_g_po4e_year: float
    acidification_g_so2e_year: float


@dataclass(frozen=True)
class AllocatedImpactPerKgFPCM:
    ghg_kg_co2e: float
    nitrogen_g: float
    phosphorus_g: float
    eutrophication_g_po4e: float
    acidification_g_so2e: float
    nreu_mj: float
    land_m2: float


@dataclass(frozen=True)
class OverallResultsResult:
    processes: tuple[ProcessImpact, ...]
    annual_totals: ImpactTotals
    annual_characterized: CharacterizedImpacts
    annual_fpcm_t_year: float
    milk_economic_allocation_fraction: float
    allocated_per_kg_fpcm: AllocatedImpactPerKgFPCM
    applied_parameters: tuple[AppliedParameter, ...]


class OverallResultsCalculator:
    """Aggregate annual process inventories and allocate them to milk."""

    def __init__(self, catalog: ParameterCatalog):
        self.catalog = catalog

    def calculate(self, activity: OverallResultsInput) -> OverallResultsResult:
        if not activity.processes:
            raise InvalidModelInputError("at least one process impact is required")
        applied: dict[str, AppliedParameter] = {}

        def use(parameter_id: str) -> float:
            value = self.catalog.model_value(parameter_id)
            applied.setdefault(
                parameter_id, AppliedParameter.from_catalog(self.catalog, parameter_id)
            )
            return value

        process_ids: set[str] = set()
        for row in activity.processes:
            process_id = identifier("process_id", row.process_id)
            if process_id in process_ids:
                raise InvalidModelInputError(f"duplicate process impact {process_id!r}")
            process_ids.add(process_id)
            for field in fields(ImpactTotals):
                value = getattr(row.impacts, field.name)
                if not isinstance(value, (int, float)) or not isfinite(float(value)):
                    raise InvalidModelInputError(
                        f"{process_id}.{field.name} must be a finite number"
                    )

        raw_milk = number(
            "annual_raw_milk_t_year", activity.annual_raw_milk_t_year, positive=True
        )
        fat = fraction("milk_fat_fraction", activity.milk_fat_fraction)
        protein = fraction("milk_protein_fraction", activity.milk_protein_fraction)
        fpcm_factor = (
            use("overall.fpcm_base_factor")
            + use("overall.fpcm_fat_factor") * fat
            + use("overall.fpcm_protein_factor") * protein
        )
        annual_fpcm = raw_milk * fpcm_factor
        if annual_fpcm <= 0:
            raise InvalidModelInputError("calculated annual FPCM must be > 0")

        milk_revenue = number(
            "milk_revenue_year", activity.milk_revenue_year, nonnegative=True
        )
        cattle_revenue = number(
            "cattle_revenue_year", activity.cattle_revenue_year, nonnegative=True
        )
        total_revenue = milk_revenue + cattle_revenue
        if total_revenue <= 0:
            raise InvalidModelInputError("milk and cattle revenue must sum to > 0")
        allocation = milk_revenue / total_revenue

        totals = sum_impacts(row.impacts for row in activity.processes)
        ep = (
            totals.nitrogen_g_year * use("characterization.ep_n_factor")
            + totals.phosphorus_g_year * use("characterization.ep_p_factor")
        )
        ap = (
            totals.nitrogen_g_year * use("characterization.ap_n_factor")
            + totals.sulfur_dioxide_kg_year
            * KG_PER_TONNE
            * use("characterization.ap_so2_factor")
        )
        denominator = annual_fpcm * KG_PER_TONNE

        def allocated(value: float) -> float:
            return value * allocation / denominator

        return OverallResultsResult(
            processes=activity.processes,
            annual_totals=totals,
            annual_characterized=CharacterizedImpacts(ep, ap),
            annual_fpcm_t_year=annual_fpcm,
            milk_economic_allocation_fraction=allocation,
            allocated_per_kg_fpcm=AllocatedImpactPerKgFPCM(
                ghg_kg_co2e=allocated(totals.ghg_kg_co2e_year),
                nitrogen_g=allocated(totals.nitrogen_g_year),
                phosphorus_g=allocated(totals.phosphorus_g_year),
                eutrophication_g_po4e=allocated(ep),
                acidification_g_so2e=allocated(ap),
                nreu_mj=allocated(totals.nreu_mj_year),
                land_m2=allocated(totals.land_m2_year),
            ),
            applied_parameters=tuple(applied.values()),
        )


def calculate_overall_results(
    catalog: ParameterCatalog, activity: OverallResultsInput
) -> OverallResultsResult:
    return OverallResultsCalculator(catalog).calculate(activity)
