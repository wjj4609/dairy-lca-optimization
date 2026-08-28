"""In-memory orchestration for one or more generic farm calculations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .catalog import ParameterCatalog
from .energy import EnergyUseCalculator, EnergyUseInput, EnergyUseResult
from .enteric import (
    EntericFarmInput,
    EntericFarmResult,
    EntericFermentationCalculator,
)
from .exceptions import InvalidModelInputError
from .feed_field import FeedFieldCalculator, FeedFieldInput, FeedFieldResult
from .feed_production import (
    FeedProductionCalculator,
    FeedProductionInput,
    FeedProductionResult,
)
from .feed_transport import (
    FeedTransportCalculator,
    FeedTransportInput,
    FeedTransportResult,
)
from .manure import (
    ManureManagementCalculator,
    ManureManagementInput,
    ManureManagementResult,
)
from .overall import (
    OverallResultsCalculator,
    OverallResultsInput,
    OverallResultsResult,
    ProcessImpact,
)
from .validation import identifier


@dataclass(frozen=True)
class FarmModelInput:
    farm_id: str
    energy: EnergyUseInput
    enteric: EntericFarmInput
    manure: ManureManagementInput
    feed_production: FeedProductionInput
    feed_field: FeedFieldInput
    feed_transport: FeedTransportInput
    annual_raw_milk_t_year: float
    milk_fat_fraction: float
    milk_protein_fraction: float
    milk_revenue_year: float
    cattle_revenue_year: float
    dataset_label: str | None = None


@dataclass(frozen=True)
class FarmModelResult:
    farm_id: str
    dataset_label: str | None
    energy: EnergyUseResult
    enteric: EntericFarmResult
    manure: ManureManagementResult
    feed_production: FeedProductionResult
    feed_field: FeedFieldResult
    feed_transport: FeedTransportResult
    overall: OverallResultsResult

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FarmBatchInput:
    farms: tuple[FarmModelInput, ...]


@dataclass(frozen=True)
class FarmBatchResult:
    farms: tuple[FarmModelResult, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class FarmModelCalculator:
    """Connect the six inventory modules to the overall calculation."""

    def __init__(self, catalog: ParameterCatalog):
        self.catalog = catalog

    def calculate(self, activity: FarmModelInput) -> FarmModelResult:
        farm_id = identifier("farm_id", activity.farm_id)
        dataset_label = activity.dataset_label
        if dataset_label is not None:
            dataset_label = identifier("dataset_label", dataset_label)

        energy = EnergyUseCalculator(self.catalog).calculate(activity.energy)
        enteric = EntericFermentationCalculator(self.catalog).calculate(
            activity.enteric
        )
        manure = ManureManagementCalculator(self.catalog).calculate(activity.manure)
        feed_production = FeedProductionCalculator(self.catalog).calculate(
            activity.feed_production
        )
        feed_field = FeedFieldCalculator(self.catalog).calculate(activity.feed_field)
        feed_transport = FeedTransportCalculator(self.catalog).calculate(
            activity.feed_transport
        )
        overall = OverallResultsCalculator(self.catalog).calculate(
            OverallResultsInput(
                annual_raw_milk_t_year=activity.annual_raw_milk_t_year,
                milk_fat_fraction=activity.milk_fat_fraction,
                milk_protein_fraction=activity.milk_protein_fraction,
                milk_revenue_year=activity.milk_revenue_year,
                cattle_revenue_year=activity.cattle_revenue_year,
                processes=(
                    ProcessImpact("feed_production", feed_production.impacts),
                    ProcessImpact("feed_field", feed_field.impacts),
                    ProcessImpact("feed_transport", feed_transport.impacts),
                    ProcessImpact("enteric_fermentation", enteric.impacts),
                    ProcessImpact("manure_management", manure.impacts),
                    ProcessImpact("farm_energy", energy.impacts),
                ),
            )
        )
        return FarmModelResult(
            farm_id=farm_id,
            dataset_label=dataset_label,
            energy=energy,
            enteric=enteric,
            manure=manure,
            feed_production=feed_production,
            feed_field=feed_field,
            feed_transport=feed_transport,
            overall=overall,
        )


class FarmBatchCalculator:
    def __init__(self, catalog: ParameterCatalog):
        self.catalog = catalog

    def calculate(self, activity: FarmBatchInput) -> FarmBatchResult:
        if not activity.farms:
            raise InvalidModelInputError("at least one farm model input is required")
        results: list[FarmModelResult] = []
        seen: set[str] = set()
        calculator = FarmModelCalculator(self.catalog)
        for farm in activity.farms:
            farm_id = identifier("farm_id", farm.farm_id)
            if farm_id in seen:
                raise InvalidModelInputError(f"duplicate farm_id {farm_id!r}")
            seen.add(farm_id)
            results.append(calculator.calculate(farm))
        return FarmBatchResult(tuple(results))


def calculate_farm_model(
    catalog: ParameterCatalog, activity: FarmModelInput
) -> FarmModelResult:
    return FarmModelCalculator(catalog).calculate(activity)


def calculate_farm_batch(
    catalog: ParameterCatalog, activity: FarmBatchInput
) -> FarmBatchResult:
    return FarmBatchCalculator(catalog).calculate(activity)
