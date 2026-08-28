"""Production-only enteric methane calculation from herd and diet activities."""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import ParameterCatalog
from .exceptions import InvalidModelInputError
from .results import AppliedParameter, ImpactTotals
from .validation import fraction, identifier, number, whole_number

DAYS_PER_YEAR = 365.0
MCAL_TO_MJ = 4.184


@dataclass(frozen=True)
class EntericStageInput:
    stage_id: str
    count_head: int
    dry_matter_intake_kg_head_day: float
    neutral_detergent_fiber_fraction: float
    starch_fraction: float
    fatty_acid_fraction: float
    crude_protein_fraction: float
    non_protein_nitrogen_fraction: float
    ash_fraction: float
    diet_energy_mcal_kg_dm_override: float | None = None


@dataclass(frozen=True)
class EntericFarmInput:
    stages: tuple[EntericStageInput, ...]


@dataclass(frozen=True)
class EntericStageResult:
    stage_id: str
    count_head: int
    rom_fraction: float
    true_protein_fraction: float
    diet_energy_mcal_kg_dm: float
    gross_energy_mj_head_day: float
    dry_matter_intake_kg_year: float
    methane_kg_head_year: float
    methane_kg_year: float
    ghg_kg_co2e_year: float
    nitrogen_intake_kg_year: float


@dataclass(frozen=True)
class EntericFarmResult:
    stages: tuple[EntericStageResult, ...]
    methane_kg_year: float
    nitrogen_intake_kg_year: float
    impacts: ImpactTotals
    applied_parameters: tuple[AppliedParameter, ...]


class EntericFermentationCalculator:
    """Apply the public diet-energy and methane-conversion equations."""

    def __init__(self, catalog: ParameterCatalog):
        self.catalog = catalog

    def calculate(self, activity: EntericFarmInput) -> EntericFarmResult:
        if not activity.stages:
            raise InvalidModelInputError("at least one enteric stage is required")
        applied: dict[str, AppliedParameter] = {}

        def use(parameter_id: str) -> float:
            value = self.catalog.model_value(parameter_id)
            applied.setdefault(
                parameter_id, AppliedParameter.from_catalog(self.catalog, parameter_id)
            )
            return value

        stage_results: list[EntericStageResult] = []
        seen: set[str] = set()
        for raw in activity.stages:
            stage_id = identifier("stage_id", raw.stage_id)
            if stage_id in seen:
                raise InvalidModelInputError(f"duplicate enteric stage {stage_id!r}")
            seen.add(stage_id)
            count = whole_number(f"{stage_id}.count_head", raw.count_head)
            dmi = number(
                f"{stage_id}.dry_matter_intake_kg_head_day",
                raw.dry_matter_intake_kg_head_day,
                nonnegative=True,
            )
            ndf = fraction(
                f"{stage_id}.neutral_detergent_fiber_fraction",
                raw.neutral_detergent_fiber_fraction,
            )
            starch = fraction(f"{stage_id}.starch_fraction", raw.starch_fraction)
            fatty_acid = fraction(
                f"{stage_id}.fatty_acid_fraction", raw.fatty_acid_fraction
            )
            crude_protein = fraction(
                f"{stage_id}.crude_protein_fraction", raw.crude_protein_fraction
            )
            npn = fraction(
                f"{stage_id}.non_protein_nitrogen_fraction",
                raw.non_protein_nitrogen_fraction,
            )
            ash = fraction(f"{stage_id}.ash_fraction", raw.ash_fraction)
            if npn > crude_protein:
                raise InvalidModelInputError(
                    f"{stage_id}.non_protein_nitrogen_fraction cannot exceed "
                    "crude_protein_fraction"
                )

            true_protein = crude_protein - npn
            rom = (
                1.0
                - ash
                - ndf
                - starch
                - fatty_acid
                - (
                    crude_protein
                    - use("enteric.rom_npn_correction_factor") * npn
                )
            )
            if not 0.0 <= rom <= 1.0:
                raise InvalidModelInputError(
                    f"{stage_id} diet composition gives ROM={rom:.12g}; expected [0, 1]"
                )
            calculated_diet_energy = (
                use("enteric.diet_energy_ndf_factor_mcal_kg") * ndf
                + use("enteric.diet_energy_starch_factor_mcal_kg") * starch
                + use("enteric.diet_energy_rom_factor_mcal_kg") * rom
                + use("enteric.diet_energy_fatty_acid_factor_mcal_kg")
                * fatty_acid
                + use("enteric.diet_energy_true_protein_factor_mcal_kg")
                * true_protein
                + use("enteric.diet_energy_npn_factor_mcal_kg") * npn
            )
            diet_energy = (
                calculated_diet_energy
                if raw.diet_energy_mcal_kg_dm_override is None
                else number(
                    f"{stage_id}.diet_energy_mcal_kg_dm_override",
                    raw.diet_energy_mcal_kg_dm_override,
                    positive=True,
                )
            )
            gross_energy = dmi * diet_energy * MCAL_TO_MJ
            methane_energy = use("enteric.methane_energy_content_mj_kg")
            if methane_energy <= 0:
                raise InvalidModelInputError(
                    "enteric.methane_energy_content_mj_kg must be > 0"
                )
            methane_head = (
                gross_energy
                * use("enteric.methane_conversion_factor_pct")
                / 100.0
                / methane_energy
                * DAYS_PER_YEAR
            )
            methane = methane_head * count
            ghg = methane * use("characterization.gwp_ch4_100yr")
            protein_to_n = use("nutrition.protein_to_nitrogen_factor")
            if protein_to_n <= 0:
                raise InvalidModelInputError(
                    "nutrition.protein_to_nitrogen_factor must be > 0"
                )
            nitrogen = count * dmi * crude_protein / protein_to_n * DAYS_PER_YEAR
            stage_results.append(
                EntericStageResult(
                    stage_id=stage_id,
                    count_head=count,
                    rom_fraction=rom,
                    true_protein_fraction=true_protein,
                    diet_energy_mcal_kg_dm=diet_energy,
                    gross_energy_mj_head_day=gross_energy,
                    dry_matter_intake_kg_year=count * dmi * DAYS_PER_YEAR,
                    methane_kg_head_year=methane_head,
                    methane_kg_year=methane,
                    ghg_kg_co2e_year=ghg,
                    nitrogen_intake_kg_year=nitrogen,
                )
            )

        total_methane = sum(row.methane_kg_year for row in stage_results)
        total_nitrogen = sum(row.nitrogen_intake_kg_year for row in stage_results)
        total_ghg = sum(row.ghg_kg_co2e_year for row in stage_results)
        return EntericFarmResult(
            stages=tuple(stage_results),
            methane_kg_year=total_methane,
            nitrogen_intake_kg_year=total_nitrogen,
            impacts=ImpactTotals(total_ghg, 0.0, 0.0, 0.0, 0.0, 0.0),
            applied_parameters=tuple(applied.values()),
        )


def calculate_enteric_fermentation(
    catalog: ParameterCatalog, activity: EntericFarmInput
) -> EntericFarmResult:
    return EntericFermentationCalculator(catalog).calculate(activity)
