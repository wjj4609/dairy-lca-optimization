"""Minimal command-line entry point for package discovery."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import __version__
from .catalog import ParameterCatalog
from .exceptions import DairyLCAError
from .input_schema import (
    load_farm_input_csv,
    load_optimization_input_csv,
    validate_farm_input_template,
    validate_optimization_input_template,
)
from .parameter_schema import STATIC_PARAMETER_UNITS


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dairy-lca",
        description="Generic Production-only dairy LCA calculation framework.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser(
        "info", help="describe the public package boundary"
    )
    validate = subcommands.add_parser(
        "validate-parameters", help="validate a completed public parameter CSV"
    )
    validate.add_argument("csv_path", help="explicit path to the parameter CSV")
    farm = subcommands.add_parser(
        "validate-farm-input",
        help="validate a farm CSV or the official blank farm template",
    )
    farm.add_argument("csv_path", help="explicit path to the farm input CSV")
    farm.add_argument(
        "--template",
        action="store_true",
        help="validate the unchanged blank template instead of completed input",
    )
    optimization = subcommands.add_parser(
        "validate-optimization-input",
        help="validate a linear-programming CSV or its official blank template",
    )
    optimization.add_argument(
        "csv_path",
        help="explicit path to the optimization input CSV",
    )
    optimization.add_argument(
        "--template",
        action="store_true",
        help="validate the unchanged blank template instead of completed input",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "info":
        print(
            "Production calculation API available. Parameters and activities "
            "must be supplied explicitly by the caller."
        )
        return 0
    if args.command == "validate-parameters":
        try:
            catalog = ParameterCatalog.from_csv(args.csv_path)
            catalog.validate_required()
        except DairyLCAError as exc:
            print(f"parameter validation failed: {exc}", file=sys.stderr)
            return 2
        print(
            f"parameter validation passed: {len(STATIC_PARAMETER_UNITS)} "
            f"static parameters checked; {len(catalog)} total rows loaded"
        )
        return 0
    if args.command == "validate-farm-input":
        try:
            if args.template:
                row_count = validate_farm_input_template(args.csv_path)
                print(f"farm input template validation passed: {row_count} rows")
            else:
                farm_input = load_farm_input_csv(args.csv_path)
                print(
                    "farm input validation passed: "
                    f"farm_id={farm_input.farm_id}; "
                    f"herd_stages={len(farm_input.enteric.stages)}; "
                    f"feeds={len(farm_input.feed_production.feeds)}; "
                    f"transport_sources={len(farm_input.feed_transport.sources)}"
                )
        except DairyLCAError as exc:
            print(f"farm input validation failed: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.command == "validate-optimization-input":
        try:
            if args.template:
                row_count = validate_optimization_input_template(args.csv_path)
                print(
                    "optimization input template validation passed: "
                    f"{row_count} rows"
                )
            else:
                optimization_input = load_optimization_input_csv(args.csv_path)
                print(
                    "optimization input validation passed: "
                    f"decisions={len(optimization_input.decisions)}; "
                    f"constraints={len(optimization_input.constraints)}; "
                    f"coefficients={len(optimization_input.coefficients)}"
                )
        except DairyLCAError as exc:
            print(f"optimization input validation failed: {exc}", file=sys.stderr)
            return 2
        return 0
    parser.print_help()
    return 0
