"""Small JSON and CSV exporters that retain no local-path provenance."""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

from .exceptions import InvalidModelInputError

_SAFE_STEM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_OMIT = object()
_UNREPORTED_LCA_KEY_TERMS = (
    "phosphorus",
    "eutrophication",
    "acidification",
    "nreu",
    "po4e",
    "so2e",
    "sulfur_dioxide",
    "sox",
)


@dataclass(frozen=True)
class ExportManifest:
    """Only relative file names are returned to avoid leaking machine paths."""

    files: tuple[str, ...]


def _payload(result: object) -> object:
    if hasattr(result, "as_dict"):
        return result.as_dict()  # type: ignore[no-any-return, attr-defined]
    if is_dataclass(result) and not isinstance(result, type):
        return asdict(result)
    if isinstance(result, Mapping):
        return dict(result)
    raise InvalidModelInputError("export result must be a dataclass or mapping")


def _is_unreported_lca_key(key: object) -> bool:
    normalized = str(key).lower()
    if any(term in normalized for term in _UNREPORTED_LCA_KEY_TERMS):
        return True
    tokens = set(re.split(r"[^a-z0-9]+", normalized))
    return bool(tokens.intersection({"p", "ep", "ap"}))


def _is_unreported_parameter_record(value: Mapping[object, object]) -> bool:
    parameter_id = value.get("parameter_id")
    return parameter_id is not None and _is_unreported_lca_key(parameter_id)


def _filter_lca_reporting_value(value: object) -> object:
    if isinstance(value, Mapping):
        if _is_unreported_parameter_record(value):
            return _OMIT
        filtered: dict[object, object] = {}
        for key, item in value.items():
            if _is_unreported_lca_key(key):
                continue
            child = _filter_lca_reporting_value(item)
            if child is not _OMIT:
                filtered[key] = child
        return filtered if filtered else _OMIT
    if isinstance(value, (list, tuple)):
        filtered_items = [
            child
            for item in value
            if (child := _filter_lca_reporting_value(item)) is not _OMIT
        ]
        if not filtered_items:
            return _OMIT
        return tuple(filtered_items) if isinstance(value, tuple) else filtered_items
    return value


def filter_lca_result_for_reporting(result: object) -> dict[object, object]:
    """Remove P, EP, AP, and NREU fields from an already calculated result."""

    payload = _payload(result)
    filtered = _filter_lca_reporting_value(payload)
    if filtered is _OMIT or not isinstance(filtered, dict):
        raise InvalidModelInputError("filtered LCA result must remain a mapping")
    return filtered


def _flatten(value: object, prefix: str = "") -> list[tuple[str, object]]:
    if isinstance(value, Mapping):
        rows: list[tuple[str, object]] = []
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten(item, child))
        return rows
    if isinstance(value, (list, tuple)):
        rows = []
        for index, item in enumerate(value):
            child = f"{prefix}[{index}]"
            rows.extend(_flatten(item, child))
        return rows
    return [(prefix, value)]


def export_result(
    result: object,
    output_directory: str | Path,
    *,
    stem: str = "model_result",
) -> ExportManifest:
    """Write a structured JSON result plus a two-column flattened CSV."""

    if not _SAFE_STEM.fullmatch(stem):
        raise InvalidModelInputError(
            "export stem may contain only letters, numbers, underscores, and hyphens"
        )
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    payload = _payload(result)
    json_name = f"{stem}.json"
    csv_name = f"{stem}_summary.csv"
    with (output / json_name).open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    with (output / csv_name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("field", "value"))
        for key, value in _flatten(payload):
            writer.writerow((key, value))
    return ExportManifest((json_name, csv_name))
