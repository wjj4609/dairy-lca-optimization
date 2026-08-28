from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
WORKFLOW_ROOT = REPOSITORY_ROOT / "workflows"
TEST_TEMP_ROOT = REPOSITORY_ROOT / "outputs" / "test-temp"
for path in (SOURCE_ROOT, WORKFLOW_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import evaluate_scenarios  # noqa: E402


def _find_rscript() -> str | None:
    configured = os.environ.get("DAIRY_LCA_RSCRIPT")
    if configured and Path(configured).is_file():
        return configured
    executable = shutil.which("Rscript")
    if executable is not None or os.name != "nt":
        return executable
    program_files_value = os.environ.get("ProgramFiles")
    if not program_files_value:
        return None
    program_files = Path(program_files_value)
    candidates = sorted(
        (program_files / "R").glob("R-*/bin/Rscript.exe"), reverse=True
    )
    return str(candidates[0]) if candidates else None


def _writable_test_directory() -> Path:
    TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = TEST_TEMP_ROOT / f"integration-{uuid.uuid4().hex}"
    path.mkdir()
    return path


class OptimizationScenarioIntegrationTests(unittest.TestCase):
    def test_r_glpk_and_python_scenario_integration(self) -> None:
        rscript = _find_rscript()
        if rscript is None:
            self.fail(
                "Rscript is required on PATH or in DAIRY_LCA_RSCRIPT; "
                "see docs/r_dependencies.md"
            )

        root = _writable_test_directory()
        try:
            optimization_output = root / "optimization"
            scenario_output = root / "scenarios"
            completed = subprocess.run(
                [
                    rscript,
                    "workflows/optimize_diet.R",
                    "--example",
                    "--output-dir",
                    optimization_output.relative_to(REPOSITORY_ROOT).as_posix(),
                ],
                cwd=REPOSITORY_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                completed.stdout + "\n" + completed.stderr,
            )
            self.assertIn("synthetic optimization run passed", completed.stdout)

            optimized_diet = optimization_output / "optimized_diet.csv"
            optimization_summary = optimization_output / "optimization_summary.csv"
            for file_name in (
                "optimized_diet.csv",
                "optimization_payoff_matrix.csv",
                "optimization_summary.csv",
                "optimization_solver_status.csv",
            ):
                self.assertTrue((optimization_output / file_name).is_file(), file_name)

            with optimized_diet.open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                optimized_rows = list(csv.DictReader(handle))
            self.assertEqual(
                {row["scenario"] for row in optimized_rows},
                {evaluate_scenarios.S1, evaluate_scenarios.S2},
            )

            with (
                patch.object(
                    evaluate_scenarios,
                    "OPTIMIZED_DIET_EXAMPLE",
                    optimized_diet,
                ),
                patch.object(
                    evaluate_scenarios,
                    "OPTIMIZATION_SUMMARY_EXAMPLE",
                    optimization_summary,
                ),
            ):
                files = evaluate_scenarios.run_synthetic_example(scenario_output)

            self.assertIn("synthetic_scenario_results.csv", files)
            with (scenario_output / "synthetic_scenario_results.csv").open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                scenario_rows = list(csv.DictReader(handle))
            self.assertEqual(
                [row["scenario"] for row in scenario_rows],
                list(evaluate_scenarios.SCENARIO_ORDER),
            )
            self.assertEqual(len(scenario_rows), 3)

            unreported_terms = (
                "phosphorus",
                "eutrophication",
                "acidification",
                "nreu",
                "po4e",
                "so2e",
            )
            for file_name in files:
                text = (scenario_output / file_name).read_text(
                    encoding="utf-8-sig"
                ).lower()
                for term in unreported_terms:
                    self.assertNotIn(term, text, f"{term} found in {file_name}")
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
