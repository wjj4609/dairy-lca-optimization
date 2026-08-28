"""Production-only manure excretion, pathway loss, and recovery calculations."""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import ParameterCatalog
from .exceptions import InvalidModelInputError
from .results import AppliedParameter, ImpactTotals, sum_impacts
from .validation import fraction, identifier, number, whole_number

DAYS_PER_YEAR = 365.0
KG_PER_TONNE = 1000.0
GRAMS_PER_TONNE = 1_000_000.0
N2O_FROM_N = 44.0 / 28.0
CH4_FROM_C = 16.0 / 12.0
CO2_FROM_C = 44.0 / 12.0

PATHWAY_STAGES = ("housing", "storage_treatment", "land_application")
LOSS_NAMES = (
    "ammonia_volatilization",
    "nitrous_oxide_emission",
    "nitrogen_oxide_emission",
    "nitrogen_leaching",
    "nitrogen_runoff",
    "methane_emission",
    "carbon_dioxide_emission",
    "phosphorus_leaching",
    "phosphorus_runoff",
)


@dataclass(frozen=True)
class ManureStageInput:
    stage_id: str
    count_head: int
    dry_matter_intake_kg_head_day: float
    crude_protein_fraction: float
    body_weight_kg: float


@dataclass(frozen=True)
class ManurePathwayInput:
    pathway_stage: str
    method_id: str


@dataclass(frozen=True)
class ManureManagementInput:
    stages: tuple[ManureStageInput, ...]
    pathways: tuple[ManurePathwayInput, ...]
    annual_slurry_t_year: float
    recovered_electricity_kwh_year: float = 0.0
    recovered_heat_mj_year: float = 0.0
    electricity_credit_parameter_id: str = "energy.electricity_ghg_factor"


@dataclass(frozen=True)
class ManureStageResult:
    stage_id: str
    nitrogen_intake_t_year: float
    volatile_solids_t_year: float


@dataclass(frozen=True)
class ManureLosses:
    nh3_n_t_year: float
    n2o_n_t_year: float
    nox_n_t_year: float
    n_leaching_t_year: float
    n_runoff_t_year: float
    ch4_t_year: float
    co2_t_year: float
    p_leaching_t_year: float
    p_runoff_t_year: float

    @property
    def nitrogen_t_year(self) -> float:
        return (
            self.nh3_n_t_year
            + self.n2o_n_t_year
            + self.nox_n_t_year
            + self.n_leaching_t_year
            + self.n_runoff_t_year
        )

    @property
    def phosphorus_t_year(self) -> float:
        return self.p_leaching_t_year + self.p_runoff_t_year


@dataclass(frozen=True)
class ManurePathwayResult:
    pathway_stage: str
    method_id: str
    input_n_t_year: float
    input_p_t_year: float
    input_vs_t_year: float
    losses: ManureLosses
    remaining_n_t_year: float
    remaining_p_t_year: float
    remaining_vs_t_year: float
    impacts: ImpactTotals


@dataclass(frozen=True)
class ManureManagementResult:
    stages: tuple[ManureStageResult, ...]
    pathways: tuple[ManurePathwayResult, ...]
    manure_n_t_year: float
    manure_p_t_year: float
    volatile_solids_t_year: float
    direct_impacts: ImpactTotals
    recovery_credit_kg_co2e_year: float
    impacts: ImpactTotals
    applied_parameters: tuple[AppliedParameter, ...]


class ManureManagementCalculator:
    """Apply an explicit housing-storage-land chain without method defaults."""

    def __init__(self, catalog: ParameterCatalog):
        self.catalog = catalog

    def calculate(self, activity: ManureManagementInput) -> ManureManagementResult:
        if not activity.stages:
            raise InvalidModelInputError("at least one manure herd stage is required")
        applied: dict[str, AppliedParameter] = {}

        def use(parameter_id: str, expected_unit: str | None = None) -> float:
            value = self.catalog.model_value(
                parameter_id, expected_unit=expected_unit
            )
            applied.setdefault(
                parameter_id, AppliedParameter.from_catalog(self.catalog, parameter_id)
            )
            return value

        protein_to_n = use("nutrition.protein_to_nitrogen_factor")
        if protein_to_n <= 0:
            raise InvalidModelInputError(
                "nutrition.protein_to_nitrogen_factor must be > 0"
            )
        vs_factor = use("manure.volatile_solids_kg_per_1000kg_bw_day")
        stage_results: list[ManureStageResult] = []
        seen_stages: set[str] = set()
        for row in activity.stages:
            stage_id = identifier("stage_id", row.stage_id)
            if stage_id in seen_stages:
                raise InvalidModelInputError(f"duplicate manure stage {stage_id!r}")
            seen_stages.add(stage_id)
            count = whole_number(f"{stage_id}.count_head", row.count_head)
            dmi = number(
                f"{stage_id}.dry_matter_intake_kg_head_day",
                row.dry_matter_intake_kg_head_day,
                nonnegative=True,
            )
            crude_protein = fraction(
                f"{stage_id}.crude_protein_fraction", row.crude_protein_fraction
            )
            weight = number(
                f"{stage_id}.body_weight_kg", row.body_weight_kg, positive=True
            )
            nitrogen_t = (
                count
                * dmi
                * crude_protein
                / protein_to_n
                * DAYS_PER_YEAR
                / KG_PER_TONNE
            )
            volatile_solids_t = (
                count
                * weight
                / KG_PER_TONNE
                * vs_factor
                * DAYS_PER_YEAR
                / KG_PER_TONNE
            )
            stage_results.append(
                ManureStageResult(stage_id, nitrogen_t, volatile_solids_t)
            )

        intake_n = sum(row.nitrogen_intake_t_year for row in stage_results)
        volatile_solids = sum(row.volatile_solids_t_year for row in stage_results)
        retention = fraction(
            "manure.nitrogen_retention_fraction",
            use("manure.nitrogen_retention_fraction"),
        )
        manure_n = intake_n * (1.0 - retention)
        slurry = number(
            "annual_slurry_t_year", activity.annual_slurry_t_year, nonnegative=True
        )
        dry_matter_fraction = fraction(
            "manure.feces_dry_matter_fraction",
            use("manure.feces_dry_matter_fraction"),
        )
        phosphorus_fraction = fraction(
            "manure.feces_phosphorus_dm_fraction",
            use("manure.feces_phosphorus_dm_fraction"),
        )
        manure_p = slurry * dry_matter_fraction * phosphorus_fraction
        carbon_vs_ratio = number(
            "manure.total_carbon_vs_ratio",
            use("manure.total_carbon_vs_ratio"),
            nonnegative=True,
        )

        path_index: dict[str, str] = {}
        for row in activity.pathways:
            stage = identifier("pathway_stage", row.pathway_stage)
            method = identifier(f"{stage}.method_id", row.method_id)
            if stage not in PATHWAY_STAGES:
                raise InvalidModelInputError(f"unknown manure pathway stage {stage!r}")
            if stage in path_index:
                raise InvalidModelInputError(f"duplicate manure pathway stage {stage!r}")
            path_index[stage] = method
        missing = [stage for stage in PATHWAY_STAGES if stage not in path_index]
        if missing:
            raise InvalidModelInputError(
                "missing manure pathway stage(s): " + ", ".join(missing)
            )

        gwp_ch4 = use("characterization.gwp_ch4_100yr")
        gwp_n2o = use("characterization.gwp_n2o_100yr")
        current_n = manure_n
        current_p = manure_p
        current_vs = volatile_solids
        pathway_results: list[ManurePathwayResult] = []
        for stage in PATHWAY_STAGES:
            method = path_index[stage]
            prefix = f"manure.{stage}.{method}"
            factors = {
                name: fraction(
                    f"{prefix}.{name}_fraction",
                    use(f"{prefix}.{name}_fraction", "fraction"),
                )
                for name in LOSS_NAMES
            }
            total_n_fraction = sum(
                factors[name]
                for name in (
                    "ammonia_volatilization",
                    "nitrous_oxide_emission",
                    "nitrogen_oxide_emission",
                    "nitrogen_leaching",
                    "nitrogen_runoff",
                )
            )
            total_p_fraction = (
                factors["phosphorus_leaching"] + factors["phosphorus_runoff"]
            )
            total_carbon_fraction = (
                factors["methane_emission"] + factors["carbon_dioxide_emission"]
            )
            if total_n_fraction > 1 or total_p_fraction > 1 or total_carbon_fraction > 1:
                raise InvalidModelInputError(
                    f"loss fractions for manure pathway {stage}/{method} exceed 1"
                )
            carbon = current_vs * carbon_vs_ratio
            losses = ManureLosses(
                nh3_n_t_year=current_n * factors["ammonia_volatilization"],
                n2o_n_t_year=current_n * factors["nitrous_oxide_emission"],
                nox_n_t_year=current_n * factors["nitrogen_oxide_emission"],
                n_leaching_t_year=current_n * factors["nitrogen_leaching"],
                n_runoff_t_year=current_n * factors["nitrogen_runoff"],
                ch4_t_year=carbon * factors["methane_emission"] * CH4_FROM_C,
                co2_t_year=carbon * factors["carbon_dioxide_emission"] * CO2_FROM_C,
                p_leaching_t_year=current_p * factors["phosphorus_leaching"],
                p_runoff_t_year=current_p * factors["phosphorus_runoff"],
            )
            ghg_kg = (
                losses.ch4_t_year * gwp_ch4
                + losses.co2_t_year
                + losses.n2o_n_t_year * N2O_FROM_N * gwp_n2o
            ) * KG_PER_TONNE
            impacts = ImpactTotals(
                ghg_kg,
                losses.nitrogen_t_year * GRAMS_PER_TONNE,
                losses.phosphorus_t_year * GRAMS_PER_TONNE,
                0.0,
                0.0,
                0.0,
            )
            remaining_n = current_n - losses.nitrogen_t_year
            remaining_p = current_p - losses.phosphorus_t_year
            remaining_vs = current_vs * (1.0 - total_carbon_fraction)
            pathway_results.append(
                ManurePathwayResult(
                    pathway_stage=stage,
                    method_id=method,
                    input_n_t_year=current_n,
                    input_p_t_year=current_p,
                    input_vs_t_year=current_vs,
                    losses=losses,
                    remaining_n_t_year=remaining_n,
                    remaining_p_t_year=remaining_p,
                    remaining_vs_t_year=remaining_vs,
                    impacts=impacts,
                )
            )
            current_n, current_p, current_vs = remaining_n, remaining_p, remaining_vs

        direct = sum_impacts(row.impacts for row in pathway_results)
        recovered_electricity = number(
            "recovered_electricity_kwh_year",
            activity.recovered_electricity_kwh_year,
            nonnegative=True,
        )
        recovered_heat = number(
            "recovered_heat_mj_year", activity.recovered_heat_mj_year, nonnegative=True
        )
        credit = 0.0
        if recovered_electricity:
            factor_id = identifier(
                "electricity_credit_parameter_id",
                activity.electricity_credit_parameter_id,
            )
            credit += recovered_electricity * use(factor_id, "kg CO2e/kWh")
        if recovered_heat:
            credit += recovered_heat * use("manure.heat_generation_ghg_factor")
        net = direct + ImpactTotals(-credit, 0.0, 0.0, 0.0, 0.0, 0.0)
        return ManureManagementResult(
            stages=tuple(stage_results),
            pathways=tuple(pathway_results),
            manure_n_t_year=manure_n,
            manure_p_t_year=manure_p,
            volatile_solids_t_year=volatile_solids,
            direct_impacts=direct,
            recovery_credit_kg_co2e_year=credit,
            impacts=net,
            applied_parameters=tuple(applied.values()),
        )


def calculate_manure_management(
    catalog: ParameterCatalog, activity: ManureManagementInput
) -> ManureManagementResult:
    return ManureManagementCalculator(catalog).calculate(activity)
