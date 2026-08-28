"""Re-evaluate synthetic S1, S2, and S3 inputs with the public LCA engine."""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from math import isclose, isfinite
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
WORKFLOW_ROOT = Path(__file__).resolve().parent
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
if str(WORKFLOW_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_ROOT))

from dairy_lca import (  # noqa: E402
    ParameterCatalog,
    __version__,
    calculate_farm_model,
)
from dairy_lca.batch import FarmModelInput, FarmModelResult  # noqa: E402
from dairy_lca.enteric import EntericFarmInput  # noqa: E402
from dairy_lca.exceptions import DairyLCAError, InputSchemaError  # noqa: E402
from dairy_lca.export import (  # noqa: E402
    export_result,
    filter_lca_result_for_reporting,
)
from dairy_lca.feed_field import FeedFieldInput  # noqa: E402
from dairy_lca.feed_production import FeedProductionInput  # noqa: E402
from dairy_lca.feed_transport import FeedTransportInput  # noqa: E402
from dairy_lca.manure import ManureManagementInput  # noqa: E402
from run_lca import (  # noqa: E402
    _farm_input_from_document,
    _load_farm_document,
    _require_synthetic_warning,
)

SYNTHETIC_WARNING = (
    "SYNTHETIC DEMONSTRATION ONLY — NOT FOR RESEARCH USE OR "
    "SCIENTIFIC INTERPRETATION."
)
DAYS_PER_YEAR = 365.0
KG_PER_TONNE = 1000.0
MJ_PER_MCAL = 4.184
S3_FEED_FRACTION = 0.95

S1 = "S1_GHG_min"
S2 = "S2_equal_weight_weighted_sum"
S3 = "S3_feed_efficiency_95pct"
SCENARIO_ORDER = (S1, S2, S3)
SUMMARY_SCENARIO = {S1: "GHG_min", S2: S2}
SCENARIO_STEMS = {
    S1: "synthetic_s1_ghg_min_result",
    S2: "synthetic_s2_equal_weight_result",
    S3: "synthetic_s3_feed_efficiency_result",
}
STAGE_ENERGY_DIVISORS = {
    "growing_cattle": 1.48,
    "young_cattle": 1.38,
    "lactating_cow": 1.74,
    "dry_cow": 1.39,
}

EXAMPLE_DIRECTORY = REPOSITORY_ROOT / "examples"
OPTIMIZATION_OUTPUT_DIRECTORY = REPOSITORY_ROOT / "outputs" / "synthetic_optimization"
FARM_EXAMPLE = EXAMPLE_DIRECTORY / "synthetic_scenario_bau.json"
PARAMETER_EXAMPLE = EXAMPLE_DIRECTORY / "synthetic_parameters.csv"
BAU_DIET_EXAMPLE = EXAMPLE_DIRECTORY / "synthetic_scenario_bau_diet.csv"
FEED_EXAMPLE = EXAMPLE_DIRECTORY / "synthetic_optimization_feed.csv"
OPTIMIZED_DIET_EXAMPLE = OPTIMIZATION_OUTPUT_DIRECTORY / "optimized_diet.csv"
OPTIMIZATION_SUMMARY_EXAMPLE = (
    OPTIMIZATION_OUTPUT_DIRECTORY / "optimization_summary.csv"
)

BAU_DIET_COLUMNS = (
    "synthetic",
    "group_id",
    "stage_id",
    "stage_category",
    "feed_id",
    "fresh_feed_kg_head_day",
    "warning",
)
FEED_COLUMNS = (
    "synthetic",
    "feed_id",
    "feed_label",
    "dry_matter_proportion_pct",
    "net_energy_lactation_mj_per_kg_dm",
    "crude_protein_pct_dm",
    "ndf_pct_dm",
    "calcium_pct_dm",
    "phosphorus_pct_dm",
    "forage_indicator",
    "ghg_kg_co2e_per_kg_fresh_feed",
    "nfp_g_n_per_kg_fresh_feed",
    "cost_unit_per_t_fresh_feed",
    "warning",
)
OPTIMIZED_DIET_COLUMNS = (
    "synthetic",
    "group_id",
    "stage_id",
    "scenario",
    "feed_id",
    "feed_label",
    "fresh_feed_kg_day",
    "dry_matter_kg_day",
    "solver_status",
    "warning",
)
OPTIMIZATION_SUMMARY_COLUMNS = (
    "synthetic",
    "group_id",
    "stage_id",
    "scenario",
    "solver_status",
    "dmi_kg_day",
    "nel_mj_per_kg_dm",
    "crude_protein_pct_dm",
    "ndf_pct_dm",
    "calcium_pct_dm",
    "phosphorus_pct_dm",
    "forage_pct_dm",
    "ghg_kg_co2e_day",
    "nfp_g_n_day",
    "cost_unit_day",
    "fresh_feed_kg_day",
    "normalized_deviation_ghg",
    "normalized_deviation_nfp",
    "normalized_deviation_cost",
    "equal_weight_ghg",
    "equal_weight_nfp",
    "equal_weight_cost",
    "combined_normalized_score",
    "warning",
)
SCENARIO_FEED_COLUMNS = (
    "synthetic",
    "scenario",
    "group_id",
    "stage_id",
    "feed_id",
    "feed_label",
    "fresh_feed_kg_head_day",
    "dry_matter_kg_head_day",
    "stage_annual_feed_use_t_year",
    "farm_annual_feed_use_t_year",
    "annual_feed_cost_currency_year",
    "warning",
)
SCENARIO_STAGE_COLUMNS = (
    "synthetic",
    "scenario",
    "group_id",
    "stage_id",
    "stage_category",
    "count_head",
    "dmi_kg_head_day",
    "crude_protein_pct_dm",
    "ndf_pct_dm",
    "diet_energy_mcal_kg_dm",
    "feed_cost_currency_head_day",
    "annual_slurry_t_year",
    "solver_status",
    "warning",
)
SCENARIO_RESULT_COLUMNS = (
    "synthetic",
    "scenario",
    "solver_status",
    "annual_feed_use_t_year",
    "annual_slurry_t_year",
    "feed_cost_currency_farm_day",
    "feed_cost_currency_year",
    "annual_ghg_kg_co2e_year",
    "annual_nitrogen_g_year",
    "annual_land_m2_year",
    "annual_fpcm_t_year",
    "milk_economic_allocation_fraction",
    "ghg_kg_co2e_per_kg_fpcm",
    "nitrogen_g_per_kg_fpcm",
    "land_m2_per_kg_fpcm",
    "warning",
)
FIELD_ANNUAL_FIELDS = (
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


@dataclass(frozen=True)
class FeedProfile:
    feed_id: str
    feed_label: str
    dry_matter_fraction: float
    nel_mj_kg_dm: float
    crude_protein_fraction: float
    ndf_fraction: float
    calcium_fraction: float
    phosphorus_fraction: float
    forage_indicator: int
    ghg_kg_co2e_kg_fresh: float
    nfp_g_n_kg_fresh: float
    cost_currency_t_fresh: float


@dataclass(frozen=True)
class DietFeed:
    group_id: str
    stage_id: str
    stage_category: str
    feed_id: str
    fresh_feed_kg_head_day: float
    dry_matter_kg_head_day: float


@dataclass(frozen=True)
class DietMetrics:
    dmi_kg_head_day: float
    nel_mj_kg_dm: float
    crude_protein_fraction: float
    ndf_fraction: float
    fresh_feed_kg_head_day: float
    ghg_kg_co2e_head_day: float
    nfp_g_n_head_day: float
    cost_currency_head_day: float


@dataclass(frozen=True)
class ScenarioStage:
    scenario: str
    group_id: str
    stage_id: str
    stage_category: str
    solver_status: str
    feeds: tuple[DietFeed, ...]
    metrics: DietMetrics


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Re-evaluate synthetic S1, S2, and S3 with the public LCA engine."
    )
    parser.add_argument(
        "--example",
        action="store_true",
        help="run the repository's explicitly synthetic scenario demonstration",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPOSITORY_ROOT / "outputs" / "synthetic_scenarios",
        help="output directory for the synthetic scenario results",
    )
    return parser


def _read_csv(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != list(columns):
                raise InputSchemaError(
                    f"{path.name} header must be exactly: {', '.join(columns)}"
                )
            rows = [
                {key: str(value or "").strip() for key, value in row.items()}
                for row in reader
                if any(str(value or "").strip() for value in row.values())
            ]
    except OSError as exc:
        raise InputSchemaError(f"cannot read {path.name}: {exc}") from exc
    if not rows:
        raise InputSchemaError(f"{path.name} contains no rows")
    return rows


def _synthetic_row(row: Mapping[str, str], label: str) -> None:
    if row.get("synthetic", "").lower() != "true":
        raise InputSchemaError(f"{label} must set synthetic=true")
    _require_synthetic_warning(row.get("warning"), f"{label} warning")


def _number(
    label: str,
    raw: object,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        value = float(str(raw).strip())
    except ValueError as exc:
        raise InputSchemaError(f"{label} must be numeric") from exc
    if not isfinite(value):
        raise InputSchemaError(f"{label} must be finite")
    if minimum is not None and value < minimum:
        raise InputSchemaError(f"{label} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise InputSchemaError(f"{label} must be <= {maximum}")
    return value


def _assert_close(label: str, actual: float, expected: float) -> None:
    if not isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-8):
        raise InputSchemaError(
            f"{label} mismatch: calculated {actual:.12g}, expected {expected:.12g}"
        )


def _load_feed_profiles(path: Path) -> dict[str, FeedProfile]:
    rows = _read_csv(path, FEED_COLUMNS)
    profiles: dict[str, FeedProfile] = {}
    for index, row in enumerate(rows, start=2):
        label = f"{path.name} row {index}"
        _synthetic_row(row, label)
        feed_id = row["feed_id"]
        if not feed_id.startswith("synthetic_"):
            raise InputSchemaError(f"{label} feed_id must start with synthetic_")
        if feed_id in profiles:
            raise InputSchemaError(f"duplicate feed_id {feed_id!r}")
        forage = _number(
            f"{label} forage_indicator", row["forage_indicator"], minimum=0, maximum=1
        )
        if forage not in (0.0, 1.0):
            raise InputSchemaError(f"{label} forage_indicator must be 0 or 1")
        profiles[feed_id] = FeedProfile(
            feed_id=feed_id,
            feed_label=row["feed_label"],
            dry_matter_fraction=_number(
                f"{label} dry_matter_proportion_pct",
                row["dry_matter_proportion_pct"],
                minimum=0.000001,
                maximum=100,
            )
            / 100.0,
            nel_mj_kg_dm=_number(
                f"{label} net_energy_lactation_mj_per_kg_dm",
                row["net_energy_lactation_mj_per_kg_dm"],
                minimum=0,
            ),
            crude_protein_fraction=_number(
                f"{label} crude_protein_pct_dm",
                row["crude_protein_pct_dm"],
                minimum=0,
                maximum=100,
            )
            / 100.0,
            ndf_fraction=_number(
                f"{label} ndf_pct_dm",
                row["ndf_pct_dm"],
                minimum=0,
                maximum=100,
            )
            / 100.0,
            calcium_fraction=_number(
                f"{label} calcium_pct_dm",
                row["calcium_pct_dm"],
                minimum=0,
                maximum=100,
            )
            / 100.0,
            phosphorus_fraction=_number(
                f"{label} phosphorus_pct_dm",
                row["phosphorus_pct_dm"],
                minimum=0,
                maximum=100,
            )
            / 100.0,
            forage_indicator=int(forage),
            ghg_kg_co2e_kg_fresh=_number(
                f"{label} ghg_kg_co2e_per_kg_fresh_feed",
                row["ghg_kg_co2e_per_kg_fresh_feed"],
                minimum=0,
            ),
            nfp_g_n_kg_fresh=_number(
                f"{label} nfp_g_n_per_kg_fresh_feed",
                row["nfp_g_n_per_kg_fresh_feed"],
                minimum=0,
            ),
            cost_currency_t_fresh=_number(
                f"{label} cost_unit_per_t_fresh_feed",
                row["cost_unit_per_t_fresh_feed"],
                minimum=0,
            ),
        )
    return profiles


def _load_bau_diet(
    path: Path, profiles: Mapping[str, FeedProfile]
) -> tuple[DietFeed, ...]:
    rows = _read_csv(path, BAU_DIET_COLUMNS)
    result: list[DietFeed] = []
    seen: set[tuple[str, str, str]] = set()
    categories: dict[tuple[str, str], str] = {}
    for index, row in enumerate(rows, start=2):
        label = f"{path.name} row {index}"
        _synthetic_row(row, label)
        group_id = row["group_id"]
        stage_id = row["stage_id"]
        feed_id = row["feed_id"]
        category = row["stage_category"]
        if category not in STAGE_ENERGY_DIVISORS:
            raise InputSchemaError(f"{label} has unknown stage_category {category!r}")
        if feed_id not in profiles:
            raise InputSchemaError(f"{label} references unknown feed_id {feed_id!r}")
        key = (group_id, stage_id, feed_id)
        if key in seen:
            raise InputSchemaError(f"{label} duplicates {key!r}")
        seen.add(key)
        stage_key = (group_id, stage_id)
        if stage_key in categories and categories[stage_key] != category:
            raise InputSchemaError(f"{label} changes stage_category within one stage")
        categories[stage_key] = category
        fresh = _number(
            f"{label} fresh_feed_kg_head_day",
            row["fresh_feed_kg_head_day"],
            minimum=0,
        )
        result.append(
            DietFeed(
                group_id=group_id,
                stage_id=stage_id,
                stage_category=category,
                feed_id=feed_id,
                fresh_feed_kg_head_day=fresh,
                dry_matter_kg_head_day=fresh
                * profiles[feed_id].dry_matter_fraction,
            )
        )
    return tuple(result)


def _load_optimized_diets(
    path: Path,
    profiles: Mapping[str, FeedProfile],
    bau_diet: Sequence[DietFeed],
) -> dict[str, tuple[DietFeed, ...]]:
    rows = _read_csv(path, OPTIMIZED_DIET_COLUMNS)
    categories = {
        (row.group_id, row.stage_id): row.stage_category for row in bau_diet
    }
    expected_keys = {
        (row.group_id, row.stage_id, row.feed_id) for row in bau_diet
    }
    grouped: dict[str, list[DietFeed]] = defaultdict(list)
    scenario_keys: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    for index, row in enumerate(rows, start=2):
        label = f"{path.name} row {index}"
        _synthetic_row(row, label)
        scenario = row["scenario"]
        if scenario not in (S1, S2):
            raise InputSchemaError(f"{label} has unsupported scenario {scenario!r}")
        if row["solver_status"] != "success":
            raise InputSchemaError(f"{label} solver_status must be success")
        feed_id = row["feed_id"]
        if feed_id not in profiles:
            raise InputSchemaError(f"{label} references unknown feed_id {feed_id!r}")
        group_id = row["group_id"]
        stage_id = row["stage_id"]
        stage_key = (group_id, stage_id)
        if stage_key not in categories:
            raise InputSchemaError(
                f"{label} has no BAU mapping for group/stage {stage_key!r}"
            )
        key = (group_id, stage_id, feed_id)
        if key in scenario_keys[scenario]:
            raise InputSchemaError(f"{label} duplicates {key!r}")
        scenario_keys[scenario].add(key)
        fresh = _number(
            f"{label} fresh_feed_kg_day", row["fresh_feed_kg_day"], minimum=0
        )
        dry_matter = _number(
            f"{label} dry_matter_kg_day", row["dry_matter_kg_day"], minimum=0
        )
        _assert_close(
            f"{label} dry matter",
            dry_matter,
            fresh * profiles[feed_id].dry_matter_fraction,
        )
        grouped[scenario].append(
            DietFeed(
                group_id=group_id,
                stage_id=stage_id,
                stage_category=categories[stage_key],
                feed_id=feed_id,
                fresh_feed_kg_head_day=fresh,
                dry_matter_kg_head_day=dry_matter,
            )
        )
    if set(grouped) != {S1, S2}:
        raise InputSchemaError("optimized_diet.csv must contain exactly S1 and S2")
    for scenario in (S1, S2):
        if scenario_keys[scenario] != expected_keys:
            raise InputSchemaError(
                f"{scenario} feed/group/stage keys do not match the BAU mapping"
            )
    return {key: tuple(value) for key, value in grouped.items()}


def _load_optimization_summary(path: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    rows = _read_csv(path, OPTIMIZATION_SUMMARY_COLUMNS)
    result: dict[tuple[str, str, str], dict[str, str]] = {}
    required_names = set(SUMMARY_SCENARIO.values())
    for index, row in enumerate(rows, start=2):
        label = f"{path.name} row {index}"
        _synthetic_row(row, label)
        if row["scenario"] not in required_names:
            continue
        if row["solver_status"] != "success":
            raise InputSchemaError(f"{label} solver_status must be success")
        key = (row["group_id"], row["stage_id"], row["scenario"])
        if key in result:
            raise InputSchemaError(f"{label} duplicates summary key {key!r}")
        result[key] = row
    return result


def _diet_metrics(
    rows: Sequence[DietFeed], profiles: Mapping[str, FeedProfile]
) -> DietMetrics:
    dmi = sum(row.dry_matter_kg_head_day for row in rows)
    if dmi <= 0:
        raise InputSchemaError("scenario stage dry-matter intake must be > 0")
    return DietMetrics(
        dmi_kg_head_day=dmi,
        nel_mj_kg_dm=sum(
            row.dry_matter_kg_head_day * profiles[row.feed_id].nel_mj_kg_dm
            for row in rows
        )
        / dmi,
        crude_protein_fraction=sum(
            row.dry_matter_kg_head_day
            * profiles[row.feed_id].crude_protein_fraction
            for row in rows
        )
        / dmi,
        ndf_fraction=sum(
            row.dry_matter_kg_head_day * profiles[row.feed_id].ndf_fraction
            for row in rows
        )
        / dmi,
        fresh_feed_kg_head_day=sum(row.fresh_feed_kg_head_day for row in rows),
        ghg_kg_co2e_head_day=sum(
            row.fresh_feed_kg_head_day
            * profiles[row.feed_id].ghg_kg_co2e_kg_fresh
            for row in rows
        ),
        nfp_g_n_head_day=sum(
            row.fresh_feed_kg_head_day * profiles[row.feed_id].nfp_g_n_kg_fresh
            for row in rows
        ),
        cost_currency_head_day=sum(
            row.fresh_feed_kg_head_day
            * profiles[row.feed_id].cost_currency_t_fresh
            / KG_PER_TONNE
            for row in rows
        ),
    )


def _scenario_stages(
    bau_diet: Sequence[DietFeed],
    optimized: Mapping[str, Sequence[DietFeed]],
    summaries: Mapping[tuple[str, str, str], Mapping[str, str]],
    profiles: Mapping[str, FeedProfile],
) -> dict[str, tuple[ScenarioStage, ...]]:
    result: dict[str, tuple[ScenarioStage, ...]] = {}
    for scenario in (S1, S2):
        stage_rows: dict[tuple[str, str], list[DietFeed]] = defaultdict(list)
        for row in optimized[scenario]:
            stage_rows[(row.group_id, row.stage_id)].append(row)
        scenario_stages: list[ScenarioStage] = []
        for (group_id, stage_id), rows in sorted(stage_rows.items()):
            metrics = _diet_metrics(rows, profiles)
            summary_name = SUMMARY_SCENARIO[scenario]
            summary_key = (group_id, stage_id, summary_name)
            if summary_key not in summaries:
                raise InputSchemaError(f"missing optimization summary {summary_key!r}")
            summary = summaries[summary_key]
            checks = {
                "dmi_kg_day": metrics.dmi_kg_head_day,
                "nel_mj_per_kg_dm": metrics.nel_mj_kg_dm,
                "crude_protein_pct_dm": metrics.crude_protein_fraction * 100.0,
                "ndf_pct_dm": metrics.ndf_fraction * 100.0,
                "ghg_kg_co2e_day": metrics.ghg_kg_co2e_head_day,
                "nfp_g_n_day": metrics.nfp_g_n_head_day,
                "cost_unit_day": metrics.cost_currency_head_day,
                "fresh_feed_kg_day": metrics.fresh_feed_kg_head_day,
            }
            for field_name, calculated in checks.items():
                _assert_close(
                    f"{scenario}/{group_id}/{stage_id}/{field_name}",
                    calculated,
                    _number(
                        f"{summary_name} {field_name}", summary[field_name]
                    ),
                )
            scenario_stages.append(
                ScenarioStage(
                    scenario=scenario,
                    group_id=group_id,
                    stage_id=stage_id,
                    stage_category=rows[0].stage_category,
                    solver_status="success",
                    feeds=tuple(sorted(rows, key=lambda item: item.feed_id)),
                    metrics=metrics,
                )
            )
        result[scenario] = tuple(scenario_stages)

    bau_stage_rows: dict[tuple[str, str], list[DietFeed]] = defaultdict(list)
    for row in bau_diet:
        bau_stage_rows[(row.group_id, row.stage_id)].append(row)
    s3_stages: list[ScenarioStage] = []
    for (group_id, stage_id), rows in sorted(bau_stage_rows.items()):
        scaled = tuple(
            replace(
                row,
                fresh_feed_kg_head_day=row.fresh_feed_kg_head_day
                * S3_FEED_FRACTION,
                dry_matter_kg_head_day=row.dry_matter_kg_head_day
                * S3_FEED_FRACTION,
            )
            for row in sorted(rows, key=lambda item: item.feed_id)
        )
        s3_stages.append(
            ScenarioStage(
                scenario=S3,
                group_id=group_id,
                stage_id=stage_id,
                stage_category=rows[0].stage_category,
                solver_status="not_applicable",
                feeds=scaled,
                metrics=_diet_metrics(scaled, profiles),
            )
        )
    result[S3] = tuple(s3_stages)
    return result


def _load_bau_farm() -> FarmModelInput:
    document = _load_farm_document(FARM_EXAMPLE)
    temporary_root = REPOSITORY_ROOT / "outputs"
    temporary_root.mkdir(parents=True, exist_ok=True)
    return _farm_input_from_document(document, temporary_root)


def _validate_bau_alignment(
    farm: FarmModelInput,
    bau_diet: Sequence[DietFeed],
    profiles: Mapping[str, FeedProfile],
) -> None:
    stage_rows: dict[str, list[DietFeed]] = defaultdict(list)
    stage_groups: dict[str, str] = {}
    for row in bau_diet:
        if row.stage_id in stage_groups and stage_groups[row.stage_id] != row.group_id:
            raise InputSchemaError(
                f"stage_id {row.stage_id!r} is assigned to more than one group"
            )
        stage_groups[row.stage_id] = row.group_id
        stage_rows[row.stage_id].append(row)
    enteric_by_stage = {row.stage_id: row for row in farm.enteric.stages}
    if set(stage_rows) != set(enteric_by_stage):
        raise InputSchemaError("BAU diet stage IDs must match the farm herd stages")
    for stage_id, rows in stage_rows.items():
        metrics = _diet_metrics(rows, profiles)
        farm_stage = enteric_by_stage[stage_id]
        _assert_close(
            f"{stage_id} BAU DMI",
            metrics.dmi_kg_head_day,
            farm_stage.dry_matter_intake_kg_head_day,
        )
        _assert_close(
            f"{stage_id} BAU crude protein",
            metrics.crude_protein_fraction,
            farm_stage.crude_protein_fraction,
        )
        _assert_close(
            f"{stage_id} BAU NDF",
            metrics.ndf_fraction,
            farm_stage.neutral_detergent_fiber_fraction,
        )

    counts = {row.stage_id: row.count_head for row in farm.enteric.stages}
    diet_masses: dict[str, float] = defaultdict(float)
    for row in bau_diet:
        diet_masses[row.feed_id] += (
            row.fresh_feed_kg_head_day
            * counts[row.stage_id]
            * DAYS_PER_YEAR
            / KG_PER_TONNE
        )
    production_masses = {
        row.feed_id: row.annual_feed_use_t_year
        for row in farm.feed_production.feeds
    }
    expected_feeds = set(profiles)
    if set(diet_masses) != expected_feeds or set(production_masses) != expected_feeds:
        raise InputSchemaError(
            "BAU diet, optimization feed, and feed-production IDs must match"
        )
    for feed_id in expected_feeds:
        _assert_close(
            f"{feed_id} BAU annual feed mass",
            diet_masses[feed_id],
            production_masses[feed_id],
        )
        if production_masses[feed_id] <= 0:
            raise InputSchemaError(f"{feed_id} BAU feed mass must be > 0")

    field_ids = {row.feed_id for row in farm.feed_field.feeds}
    if field_ids != expected_feeds:
        raise InputSchemaError("BAU feed-field IDs must match feed-production IDs")
    transport_masses: dict[str, float] = defaultdict(float)
    for source in farm.feed_transport.sources:
        transport_masses[source.feed_id] += source.feed_mass_t_year
    if set(transport_masses) != expected_feeds:
        raise InputSchemaError("BAU transport feed IDs must match feed-production IDs")
    for feed_id in expected_feeds:
        _assert_close(
            f"{feed_id} BAU transport mass",
            transport_masses[feed_id],
            production_masses[feed_id],
        )


def _aggregate_feed_masses(
    stages: Sequence[ScenarioStage], counts: Mapping[str, int]
) -> dict[str, float]:
    masses: dict[str, float] = defaultdict(float)
    for stage in stages:
        for row in stage.feeds:
            masses[row.feed_id] += (
                row.fresh_feed_kg_head_day
                * counts[stage.stage_id]
                * DAYS_PER_YEAR
                / KG_PER_TONNE
            )
    return dict(masses)


def _build_scenario_farm(
    bau_farm: FarmModelInput,
    bau_result: FarmModelResult,
    stages: Sequence[ScenarioStage],
) -> tuple[FarmModelInput, dict[str, float]]:
    stage_specs = {row.stage_id: row for row in stages}
    if len(stage_specs) != len(stages):
        raise InputSchemaError("each LCA stage_id must map to exactly one group")
    counts = {row.stage_id: row.count_head for row in bau_farm.enteric.stages}
    feed_masses = _aggregate_feed_masses(stages, counts)
    base_feed_masses = {
        row.feed_id: row.annual_feed_use_t_year
        for row in bau_farm.feed_production.feeds
    }
    if set(feed_masses) != set(base_feed_masses):
        raise InputSchemaError("scenario feed IDs must match BAU feed-production IDs")

    bau_energy = {
        row.stage_id: row.diet_energy_mcal_kg_dm
        for row in bau_result.enteric.stages
    }
    enteric_stages = []
    for row in bau_farm.enteric.stages:
        if row.stage_id not in stage_specs:
            raise InputSchemaError(f"missing scenario diet for stage {row.stage_id!r}")
        stage = stage_specs[row.stage_id]
        energy_override = None
        if stage.scenario in (S1, S2):
            energy_override = (
                stage.metrics.nel_mj_kg_dm
                / MJ_PER_MCAL
                / STAGE_ENERGY_DIVISORS[stage.stage_category]
                * bau_energy[row.stage_id]
            )
        enteric_stages.append(
            replace(
                row,
                dry_matter_intake_kg_head_day=stage.metrics.dmi_kg_head_day,
                neutral_detergent_fiber_fraction=stage.metrics.ndf_fraction,
                crude_protein_fraction=stage.metrics.crude_protein_fraction,
                diet_energy_mcal_kg_dm_override=energy_override,
            )
        )

    manure_stages = []
    for row in bau_farm.manure.stages:
        if row.stage_id not in stage_specs:
            raise InputSchemaError(
                f"missing scenario manure inputs for stage {row.stage_id!r}"
            )
        stage = stage_specs[row.stage_id]
        manure_stages.append(
            replace(
                row,
                dry_matter_intake_kg_head_day=stage.metrics.dmi_kg_head_day,
                crude_protein_fraction=stage.metrics.crude_protein_fraction,
            )
        )

    production = FeedProductionInput(
        tuple(
            replace(
                row,
                annual_feed_use_t_year=feed_masses[row.feed_id],
            )
            for row in bau_farm.feed_production.feeds
        )
    )
    field_rows = []
    for row in bau_farm.feed_field.feeds:
        base_mass = base_feed_masses[row.feed_id]
        scenario_mass = feed_masses[row.feed_id]
        updates = {
            field_name: getattr(row, field_name) / base_mass * scenario_mass
            for field_name in FIELD_ANNUAL_FIELDS
        }
        field_rows.append(replace(row, **updates))
    feed_field = FeedFieldInput(tuple(field_rows))

    base_transport_masses: dict[str, float] = defaultdict(float)
    for source in bau_farm.feed_transport.sources:
        base_transport_masses[source.feed_id] += source.feed_mass_t_year
    transport_rows = []
    for source in bau_farm.feed_transport.sources:
        feed_total = base_transport_masses[source.feed_id]
        source_mass = (
            feed_masses[source.feed_id] * source.feed_mass_t_year / feed_total
        )
        sea = source.sea
        if sea is not None:
            sea = replace(
                sea,
                cargo_mass_t_year=(
                    sea.cargo_mass_t_year
                    * source_mass
                    / source.feed_mass_t_year
                    if source.feed_mass_t_year
                    else 0.0
                ),
            )
        transport_rows.append(
            replace(source, feed_mass_t_year=source_mass, sea=sea)
        )
    transport = FeedTransportInput(tuple(transport_rows))

    scenario = stages[0].scenario
    slurry = bau_farm.manure.annual_slurry_t_year
    if scenario == S3:
        slurry *= S3_FEED_FRACTION
    manure = replace(
        bau_farm.manure,
        stages=tuple(manure_stages),
        annual_slurry_t_year=slurry,
    )
    return (
        replace(
            bau_farm,
            dataset_label=f"synthetic_{scenario.lower()}",
            enteric=EntericFarmInput(tuple(enteric_stages)),
            manure=manure,
            feed_production=production,
            feed_field=feed_field,
            feed_transport=transport,
        ),
        feed_masses,
    )


def _write_csv(
    path: Path, columns: tuple[str, ...], rows: Sequence[Mapping[str, Any]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _scenario_status(stages: Sequence[ScenarioStage]) -> str:
    statuses = {row.solver_status for row in stages}
    if len(statuses) != 1:
        raise InputSchemaError("scenario stages must share one solver status")
    return next(iter(statuses))


def run_synthetic_example(output_directory: Path) -> tuple[str, ...]:
    required_files = (
        FARM_EXAMPLE,
        PARAMETER_EXAMPLE,
        BAU_DIET_EXAMPLE,
        FEED_EXAMPLE,
        OPTIMIZED_DIET_EXAMPLE,
        OPTIMIZATION_SUMMARY_EXAMPLE,
    )
    missing = [path.name for path in required_files if not path.is_file()]
    if missing:
        raise InputSchemaError(
            "missing required scenario input(s): "
            + ", ".join(missing)
            + "; run the R optimization example first"
        )

    profiles = _load_feed_profiles(FEED_EXAMPLE)
    bau_diet = _load_bau_diet(BAU_DIET_EXAMPLE, profiles)
    optimized = _load_optimized_diets(
        OPTIMIZED_DIET_EXAMPLE, profiles, bau_diet
    )
    summaries = _load_optimization_summary(OPTIMIZATION_SUMMARY_EXAMPLE)
    stages_by_scenario = _scenario_stages(
        bau_diet, optimized, summaries, profiles
    )

    catalog = ParameterCatalog.from_csv(PARAMETER_EXAMPLE)
    catalog.validate_required()
    for parameter_id, parameter in catalog.as_dict().items():
        _require_synthetic_warning(
            str(parameter.get("citation") or ""), f"parameter {parameter_id}"
        )
    bau_farm = _load_bau_farm()
    _validate_bau_alignment(bau_farm, bau_diet, profiles)
    bau_result = calculate_farm_model(catalog, bau_farm)

    output_directory.mkdir(parents=True, exist_ok=True)
    feed_rows: list[dict[str, Any]] = []
    stage_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    files: list[str] = []
    counts = {row.stage_id: row.count_head for row in bau_farm.enteric.stages}

    for scenario in SCENARIO_ORDER:
        stages = stages_by_scenario[scenario]
        scenario_farm, feed_masses = _build_scenario_farm(
            bau_farm, bau_result, stages
        )
        result = calculate_farm_model(catalog, scenario_farm)
        enteric_results = {row.stage_id: row for row in result.enteric.stages}
        feed_cost_day = sum(
            stage.metrics.cost_currency_head_day * counts[stage.stage_id]
            for stage in stages
        )
        feed_cost_year = feed_cost_day * DAYS_PER_YEAR
        solver_status = _scenario_status(stages)

        for stage in stages:
            stage_rows.append(
                {
                    "synthetic": True,
                    "scenario": scenario,
                    "group_id": stage.group_id,
                    "stage_id": stage.stage_id,
                    "stage_category": stage.stage_category,
                    "count_head": counts[stage.stage_id],
                    "dmi_kg_head_day": stage.metrics.dmi_kg_head_day,
                    "crude_protein_pct_dm": stage.metrics.crude_protein_fraction
                    * 100.0,
                    "ndf_pct_dm": stage.metrics.ndf_fraction * 100.0,
                    "diet_energy_mcal_kg_dm": enteric_results[
                        stage.stage_id
                    ].diet_energy_mcal_kg_dm,
                    "feed_cost_currency_head_day": (
                        stage.metrics.cost_currency_head_day
                    ),
                    "annual_slurry_t_year": (
                        scenario_farm.manure.annual_slurry_t_year
                    ),
                    "solver_status": stage.solver_status,
                    "warning": SYNTHETIC_WARNING,
                }
            )
            for row in stage.feeds:
                stage_annual = (
                    row.fresh_feed_kg_head_day
                    * counts[stage.stage_id]
                    * DAYS_PER_YEAR
                    / KG_PER_TONNE
                )
                feed_rows.append(
                    {
                        "synthetic": True,
                        "scenario": scenario,
                        "group_id": stage.group_id,
                        "stage_id": stage.stage_id,
                        "feed_id": row.feed_id,
                        "feed_label": profiles[row.feed_id].feed_label,
                        "fresh_feed_kg_head_day": (
                            row.fresh_feed_kg_head_day
                        ),
                        "dry_matter_kg_head_day": (
                            row.dry_matter_kg_head_day
                        ),
                        "stage_annual_feed_use_t_year": stage_annual,
                        "farm_annual_feed_use_t_year": feed_masses[
                            row.feed_id
                        ],
                        "annual_feed_cost_currency_year": (
                            stage_annual
                            * profiles[row.feed_id].cost_currency_t_fresh
                        ),
                        "warning": SYNTHETIC_WARNING,
                    }
                )

        payload = {
            "schema_version": "1.0",
            "synthetic": True,
            "warning": SYNTHETIC_WARNING,
            "status": "success",
            "run_type": "synthetic_scenario_lca",
            "scenario": scenario,
            "solver_status": solver_status,
            "model_version": __version__,
            "input_files": (
                "examples/synthetic_scenario_bau.json",
                "examples/synthetic_scenario_bau_diet.csv",
                "examples/synthetic_parameters.csv",
                "examples/synthetic_optimization_feed.csv",
                "outputs/synthetic_optimization/optimized_diet.csv",
                "outputs/synthetic_optimization/optimization_summary.csv",
            ),
            "input_summary": {
                "group_stage_count": len(stages),
                "feed_count": len(feed_masses),
                "annual_feed_use_t_year": sum(feed_masses.values()),
                "annual_slurry_t_year": scenario_farm.manure.annual_slurry_t_year,
                "feed_cost_currency_farm_day": feed_cost_day,
                "feed_cost_currency_year": feed_cost_year,
                "all_values_are_synthetic": True,
            },
            "result": filter_lca_result_for_reporting(result),
        }
        manifest = export_result(
            payload, output_directory, stem=SCENARIO_STEMS[scenario]
        )
        files.extend(manifest.files)

        totals = result.overall.annual_totals
        allocated = result.overall.allocated_per_kg_fpcm
        result_rows.append(
            {
                "synthetic": True,
                "scenario": scenario,
                "solver_status": solver_status,
                "annual_feed_use_t_year": sum(feed_masses.values()),
                "annual_slurry_t_year": scenario_farm.manure.annual_slurry_t_year,
                "feed_cost_currency_farm_day": feed_cost_day,
                "feed_cost_currency_year": feed_cost_year,
                "annual_ghg_kg_co2e_year": totals.ghg_kg_co2e_year,
                "annual_nitrogen_g_year": totals.nitrogen_g_year,
                "annual_land_m2_year": totals.land_m2_year,
                "annual_fpcm_t_year": result.overall.annual_fpcm_t_year,
                "milk_economic_allocation_fraction": (
                    result.overall.milk_economic_allocation_fraction
                ),
                "ghg_kg_co2e_per_kg_fpcm": allocated.ghg_kg_co2e,
                "nitrogen_g_per_kg_fpcm": allocated.nitrogen_g,
                "land_m2_per_kg_fpcm": allocated.land_m2,
                "warning": SYNTHETIC_WARNING,
            }
        )

    csv_outputs = (
        (
            "synthetic_scenario_feed_inputs.csv",
            SCENARIO_FEED_COLUMNS,
            feed_rows,
        ),
        (
            "synthetic_scenario_stage_inputs.csv",
            SCENARIO_STAGE_COLUMNS,
            stage_rows,
        ),
        (
            "synthetic_scenario_results.csv",
            SCENARIO_RESULT_COLUMNS,
            result_rows,
        ),
    )
    for file_name, columns, rows in csv_outputs:
        _write_csv(output_directory / file_name, columns, rows)
        files.append(file_name)
    return tuple(files)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.example:
        parser.error("this public workflow currently requires --example")
    try:
        files = run_synthetic_example(args.output_dir)
    except (DairyLCAError, OSError, ValueError) as exc:
        print(f"synthetic scenario evaluation failed: {exc}", file=sys.stderr)
        return 2
    print("synthetic S1/S2/S3 scenario evaluation passed")
    print("outputs: " + ", ".join(files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
