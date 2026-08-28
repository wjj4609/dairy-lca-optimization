"""Run a seeded Monte Carlo sensitivity analysis with synthetic inputs."""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from math import floor, fsum, isfinite, sqrt
from pathlib import Path
from statistics import fmean, stdev
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from dairy_lca import (  # noqa: E402
    ParameterCatalog,
    __version__,
    calculate_farm_model,
)
from dairy_lca.exceptions import DairyLCAError  # noqa: E402

from run_lca import (  # noqa: E402
    FARM_EXAMPLE,
    PARAMETER_EXAMPLE,
    SYNTHETIC_WARNING,
    _farm_input_from_document,
    _load_farm_document,
    _require_synthetic_warning,
)

SENSITIVITY_EXAMPLE = REPOSITORY_ROOT / "examples" / "synthetic_sensitivity.csv"
DEFAULT_OUTPUT_DIRECTORY = REPOSITORY_ROOT / "outputs" / "synthetic_sensitivity"
DEFAULT_SEED = 20260825
DEFAULT_ITERATIONS = 10_000
SENSITIVITY_COLUMNS = (
    "synthetic",
    "parameter_id",
    "distribution",
    "mean",
    "sd",
    "cv",
    "lower_bound",
    "upper_bound",
    "unit",
    "source_note",
    "warning",
)
METRICS = (
    (
        "gwp_kg_co2e_per_kg_fpcm",
        "kg CO2e/kg FPCM",
        "ghg_kg_co2e",
    ),
    (
        "nitrogen_g_per_kg_fpcm",
        "g N/kg FPCM",
        "nitrogen_g",
    ),
)


class SensitivityConfigurationError(DairyLCAError):
    """Raised when a public sensitivity configuration is invalid."""


@dataclass(frozen=True)
class SensitivityParameter:
    """One uncertain parameter and its user-supplied sampling rule."""

    parameter_id: str
    distribution: str
    unit: str
    source_note: str
    warning: str
    mean: float | None = None
    sd: float | None = None
    cv: float | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None

    @property
    def normal_sd(self) -> float | None:
        if self.distribution != "normal":
            return None
        if self.sd is not None:
            return self.sd
        if self.mean is None or self.cv is None:
            return None
        return abs(self.mean) * self.cv


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the generic seeded Monte Carlo sensitivity workflow."
    )
    parser.add_argument(
        "--example",
        action="store_true",
        help="run the repository's explicitly synthetic demonstration",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
        help=f"simulation count; defaults to {DEFAULT_ITERATIONS}",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"explicit random seed; defaults to {DEFAULT_SEED}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
        help="output directory; defaults to the git-ignored synthetic output folder",
    )
    return parser


def _optional_number(raw: object, label: str) -> float | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError as exc:
        raise SensitivityConfigurationError(f"{label} must be numeric or blank") from exc
    if not isfinite(value):
        raise SensitivityConfigurationError(f"{label} must be finite")
    return value


def _read_sensitivity_configuration(
    path: Path,
    base_catalog: ParameterCatalog,
) -> tuple[SensitivityParameter, ...]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != list(SENSITIVITY_COLUMNS):
                raise SensitivityConfigurationError(
                    f"{path.name} header must be exactly: "
                    + ", ".join(SENSITIVITY_COLUMNS)
                )
            raw_rows = list(reader)
    except OSError as exc:
        raise SensitivityConfigurationError(f"cannot read {path.name}: {exc}") from exc

    specifications: list[SensitivityParameter] = []
    seen: set[str] = set()
    for row_number, row in enumerate(raw_rows, start=2):
        if None in row:
            raise SensitivityConfigurationError(
                f"{path.name} row {row_number} has too many columns"
            )
        if not any(str(value or "").strip() for value in row.values()):
            continue
        row = {key: str(value or "").strip() for key, value in row.items()}
        if row["synthetic"].lower() != "true":
            raise SensitivityConfigurationError(
                f"{path.name} row {row_number} must set synthetic=true"
            )
        _require_synthetic_warning(
            row["warning"], f"{path.name} row {row_number} warning"
        )
        parameter_id = row["parameter_id"]
        if not parameter_id or "<" in parameter_id or ">" in parameter_id:
            raise SensitivityConfigurationError(
                f"{path.name} row {row_number} has an invalid parameter_id"
            )
        if parameter_id in seen:
            raise SensitivityConfigurationError(
                f"{path.name} row {row_number} duplicates {parameter_id!r}"
            )
        seen.add(parameter_id)
        if parameter_id not in base_catalog:
            raise SensitivityConfigurationError(
                f"{path.name} row {row_number} references unknown parameter "
                f"{parameter_id!r}"
            )
        unit = row["unit"]
        expected_unit = base_catalog.parameter(parameter_id).unit
        if unit != expected_unit:
            raise SensitivityConfigurationError(
                f"{path.name} row {row_number} ({parameter_id}) has unit {unit!r}; "
                f"expected {expected_unit!r}"
            )
        source_note = row["source_note"]
        if not source_note:
            raise SensitivityConfigurationError(
                f"{path.name} row {row_number} must include source_note"
            )

        distribution = row["distribution"].lower()
        mean = _optional_number(row["mean"], f"row {row_number} mean")
        sd = _optional_number(row["sd"], f"row {row_number} sd")
        cv = _optional_number(row["cv"], f"row {row_number} cv")
        lower = _optional_number(
            row["lower_bound"], f"row {row_number} lower_bound"
        )
        upper = _optional_number(
            row["upper_bound"], f"row {row_number} upper_bound"
        )
        if lower is not None and upper is not None and lower >= upper:
            raise SensitivityConfigurationError(
                f"{path.name} row {row_number} lower_bound must be below upper_bound"
            )

        if distribution == "normal":
            if mean is None:
                raise SensitivityConfigurationError(
                    f"{path.name} row {row_number} normal distribution requires mean"
                )
            if (sd is None) == (cv is None):
                raise SensitivityConfigurationError(
                    f"{path.name} row {row_number} normal distribution requires "
                    "exactly one of sd or cv"
                )
            if sd is not None and sd <= 0:
                raise SensitivityConfigurationError(
                    f"{path.name} row {row_number} sd must be greater than zero"
                )
            if cv is not None and cv <= 0:
                raise SensitivityConfigurationError(
                    f"{path.name} row {row_number} cv must be greater than zero"
                )
            if cv is not None and mean == 0:
                raise SensitivityConfigurationError(
                    f"{path.name} row {row_number} cannot combine mean=0 with cv"
                )
            if lower is not None and mean < lower:
                raise SensitivityConfigurationError(
                    f"{path.name} row {row_number} mean is below lower_bound"
                )
            if upper is not None and mean > upper:
                raise SensitivityConfigurationError(
                    f"{path.name} row {row_number} mean is above upper_bound"
                )
        elif distribution == "uniform":
            if lower is None or upper is None:
                raise SensitivityConfigurationError(
                    f"{path.name} row {row_number} uniform distribution requires "
                    "both bounds"
                )
            if any(value is not None for value in (mean, sd, cv)):
                raise SensitivityConfigurationError(
                    f"{path.name} row {row_number} uniform distribution leaves "
                    "mean, sd, and cv blank"
                )
        else:
            raise SensitivityConfigurationError(
                f"{path.name} row {row_number} distribution must be normal or uniform"
            )

        specifications.append(
            SensitivityParameter(
                parameter_id=parameter_id,
                distribution=distribution,
                unit=unit,
                source_note=source_note,
                warning=row["warning"],
                mean=mean,
                sd=sd,
                cv=cv,
                lower_bound=lower,
                upper_bound=upper,
            )
        )
    if not specifications:
        raise SensitivityConfigurationError(
            f"{path.name} contains no sensitivity parameter rows"
        )
    return tuple(sorted(specifications, key=lambda item: item.parameter_id))


def _sample_parameter(
    specification: SensitivityParameter,
    generator: random.Random,
) -> float:
    if specification.distribution == "uniform":
        assert specification.lower_bound is not None
        assert specification.upper_bound is not None
        return generator.uniform(
            specification.lower_bound, specification.upper_bound
        )

    assert specification.mean is not None
    standard_deviation = specification.normal_sd
    assert standard_deviation is not None
    for _ in range(10_000):
        value = generator.gauss(specification.mean, standard_deviation)
        if (
            specification.lower_bound is not None
            and value < specification.lower_bound
        ):
            continue
        if (
            specification.upper_bound is not None
            and value > specification.upper_bound
        ):
            continue
        return value
    raise SensitivityConfigurationError(
        f"could not draw {specification.parameter_id!r} within its bounds after "
        "10,000 attempts"
    )


def _percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower_index = floor(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - lower_index
    return ordered[lower_index] + fraction * (
        ordered[upper_index] - ordered[lower_index]
    )


def _average_ranks(values: Sequence[float]) -> list[float]:
    ordered_indices = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(values):
        end = start + 1
        while (
            end < len(values)
            and values[ordered_indices[end]] == values[ordered_indices[start]]
        ):
            end += 1
        average_rank = ((start + 1) + end) / 2.0
        for position in range(start, end):
            ranks[ordered_indices[position]] = average_rank
        start = end
    return ranks


def _pearson_correlation(left: Sequence[float], right: Sequence[float]) -> float:
    left_mean = fmean(left)
    right_mean = fmean(right)
    left_delta = [value - left_mean for value in left]
    right_delta = [value - right_mean for value in right]
    numerator = fsum(
        left_value * right_value
        for left_value, right_value in zip(left_delta, right_delta, strict=True)
    )
    denominator = sqrt(
        fsum(value * value for value in left_delta)
        * fsum(value * value for value in right_delta)
    )
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _spearman_correlation(left: Sequence[float], right: Sequence[float]) -> float:
    return _pearson_correlation(_average_ranks(left), _average_ranks(right))


def _write_csv(
    path: Path,
    fieldnames: Sequence[str],
    rows: Sequence[Mapping[str, object]],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _parameter_payload(specification: SensitivityParameter) -> dict[str, Any]:
    payload = asdict(specification)
    payload["synthetic"] = True
    payload["effective_sd"] = specification.normal_sd
    return payload


def run_synthetic_sensitivity(
    output_directory: Path,
    *,
    iterations: int,
    seed: int,
) -> tuple[str, ...]:
    if iterations < 3:
        raise SensitivityConfigurationError("iterations must be at least 3")

    farm_document = _load_farm_document(FARM_EXAMPLE)
    farm_input = _farm_input_from_document(farm_document, output_directory)
    base_catalog = ParameterCatalog.from_csv(PARAMETER_EXAMPLE)
    base_catalog.validate_required()
    base_parameters = base_catalog.as_dict()
    for parameter_id, parameter in base_parameters.items():
        _require_synthetic_warning(
            parameter.get("citation"), f"parameter {parameter_id}"
        )
    specifications = _read_sensitivity_configuration(
        SENSITIVITY_EXAMPLE, base_catalog
    )

    generator = random.Random(seed)
    draw_series = {item.parameter_id: [] for item in specifications}
    metric_series = {name: [] for name, _, _ in METRICS}
    draw_rows: list[dict[str, object]] = []

    for iteration in range(1, iterations + 1):
        draws = {
            item.parameter_id: _sample_parameter(item, generator)
            for item in specifications
        }
        iteration_parameters = dict(base_parameters)
        for item in specifications:
            original = base_parameters[item.parameter_id]
            iteration_parameters[item.parameter_id] = {
                **original,
                "value": draws[item.parameter_id],
                "citation": SYNTHETIC_WARNING,
            }
            draw_series[item.parameter_id].append(draws[item.parameter_id])

        sampled_catalog = ParameterCatalog(iteration_parameters)
        result = calculate_farm_model(sampled_catalog, farm_input)
        allocated = result.overall.allocated_per_kg_fpcm
        metrics = {
            metric_name: float(getattr(allocated, attribute_name))
            for metric_name, _, attribute_name in METRICS
        }
        if not all(isfinite(value) for value in metrics.values()):
            raise SensitivityConfigurationError(
                f"iteration {iteration} produced a non-finite output metric"
            )
        for metric_name, value in metrics.items():
            metric_series[metric_name].append(value)
        draw_rows.append(
            {
                "iteration": iteration,
                **draws,
                **metrics,
                "synthetic": "true",
                "warning": SYNTHETIC_WARNING,
            }
        )

    summary_rows: list[dict[str, object]] = []
    summary_payload: list[dict[str, object]] = []
    for metric_name, metric_unit, _ in METRICS:
        values = metric_series[metric_name]
        summary = {
            "metric": metric_name,
            "unit": metric_unit,
            "simulation_count": iterations,
            "mean": fmean(values),
            "sd": stdev(values),
            "p2_5": _percentile(values, 0.025),
            "p97_5": _percentile(values, 0.975),
            "seed": seed,
            "synthetic": True,
            "warning": SYNTHETIC_WARNING,
        }
        summary_payload.append(summary)
        summary_rows.append({**summary, "synthetic": "true"})

    influence_rows: list[dict[str, object]] = []
    influence_payload: list[dict[str, object]] = []
    for metric_name, metric_unit, _ in METRICS:
        scored = []
        for item in specifications:
            coefficient = _spearman_correlation(
                draw_series[item.parameter_id], metric_series[metric_name]
            )
            scored.append((item, coefficient))
        scored.sort(key=lambda pair: (-abs(pair[1]), pair[0].parameter_id))
        for rank, (item, coefficient) in enumerate(scored, start=1):
            influence = {
                "metric": metric_name,
                "metric_unit": metric_unit,
                "rank": rank,
                "parameter_id": item.parameter_id,
                "parameter_unit": item.unit,
                "spearman_rho": coefficient,
                "absolute_spearman_rho": abs(coefficient),
                "simulation_count": iterations,
                "seed": seed,
                "synthetic": True,
                "warning": SYNTHETIC_WARNING,
            }
            influence_payload.append(influence)
            influence_rows.append({**influence, "synthetic": "true"})

    output_directory.mkdir(parents=True, exist_ok=True)
    draws_path = output_directory / "synthetic_sensitivity_draws.csv"
    summary_path = output_directory / "synthetic_sensitivity_summary.csv"
    influence_path = output_directory / "synthetic_sensitivity_influence.csv"
    result_path = output_directory / "synthetic_sensitivity_result.json"
    draw_fields = (
        "iteration",
        *(item.parameter_id for item in specifications),
        *(name for name, _, _ in METRICS),
        "synthetic",
        "warning",
    )
    _write_csv(draws_path, draw_fields, draw_rows)
    _write_csv(
        summary_path,
        (
            "metric",
            "unit",
            "simulation_count",
            "mean",
            "sd",
            "p2_5",
            "p97_5",
            "seed",
            "synthetic",
            "warning",
        ),
        summary_rows,
    )
    _write_csv(
        influence_path,
        (
            "metric",
            "metric_unit",
            "rank",
            "parameter_id",
            "parameter_unit",
            "spearman_rho",
            "absolute_spearman_rho",
            "simulation_count",
            "seed",
            "synthetic",
            "warning",
        ),
        influence_rows,
    )

    payload = {
        "schema_version": "1.0",
        "synthetic": True,
        "warning": SYNTHETIC_WARNING,
        "status": "success",
        "run_type": "synthetic_monte_carlo_sensitivity",
        "model_version": __version__,
        "input_files": (
            "examples/synthetic_farm.json",
            "examples/synthetic_parameters.csv",
            "examples/synthetic_sensitivity.csv",
        ),
        "sampling": {
            "random_seed": seed,
            "simulation_count": iterations,
            "lca_engine_call_count": iterations,
            "parameter_order": tuple(item.parameter_id for item in specifications),
            "sampling_rule": "one_draw_per_parameter_per_iteration",
            "reuse_rule": "each draw is reused throughout that iteration's LCA call",
            "normal_bounds_rule": "rejection sampling",
        },
        "interval_method": {
            "summary_statistics": ("mean", "sd", "p2_5", "p97_5"),
            "percentile_interpolation": "linear on position (n - 1) * p",
        },
        "influence_method": {
            "name": "Spearman rank correlation",
            "ranking_key": "absolute_spearman_rho descending",
            "interpretation": "monotonic influence proxy; not causal or variance decomposition",
        },
        "parameter_configuration": tuple(
            _parameter_payload(item) for item in specifications
        ),
        "summary": summary_payload,
        "influence": influence_payload,
        "output_files": (
            draws_path.name,
            summary_path.name,
            influence_path.name,
            result_path.name,
        ),
    }
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return tuple(payload["output_files"])


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.example:
        parser.error("this public workflow currently requires --example")
    try:
        files = run_synthetic_sensitivity(
            args.output_dir,
            iterations=args.iterations,
            seed=args.seed,
        )
    except (DairyLCAError, OSError) as exc:
        print(f"synthetic sensitivity run failed: {exc}", file=sys.stderr)
        return 2
    print("synthetic sensitivity run passed")
    print(f"seed: {args.seed}")
    print(f"simulations: {args.iterations}")
    print("outputs: " + ", ".join(files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
