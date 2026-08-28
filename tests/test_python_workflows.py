from __future__ import annotations

import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
WORKFLOW_ROOT = REPOSITORY_ROOT / "workflows"
TEST_TEMP_ROOT = REPOSITORY_ROOT / "outputs" / "test-temp"
for path in (SOURCE_ROOT, WORKFLOW_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_lca  # noqa: E402
import run_sensitivity  # noqa: E402
from dairy_lca.exceptions import InputSchemaError  # noqa: E402
from dairy_lca.export import filter_lca_result_for_reporting  # noqa: E402


def _writable_test_directory() -> Path:
    TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = TEST_TEMP_ROOT / f"python-{uuid.uuid4().hex}"
    path.mkdir()
    return path


class BaselineAndReportingTests(unittest.TestCase):
    def test_input_validation_and_baseline_calculation(self) -> None:
        root = _writable_test_directory()
        try:
            output = root / "baseline"
            files = run_lca.run_synthetic_example(output)

            self.assertEqual(
                set(files),
                {
                    "synthetic_baseline_result.json",
                    "synthetic_baseline_result_summary.csv",
                },
            )
            payload = json.loads(
                (output / "synthetic_baseline_result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(payload["synthetic"])
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["run_type"], "synthetic_baseline_lca")
            self.assertGreater(
                payload["result"]["overall"]["annual_fpcm_t_year"], 0.0
            )

            invalid_payload = json.loads(
                run_lca.FARM_EXAMPLE.read_text(encoding="utf-8")
            )
            invalid_payload["synthetic"] = False
            invalid_path = root / "not_synthetic.json"
            invalid_path.write_text(
                json.dumps(invalid_payload), encoding="utf-8"
            )
            with self.assertRaisesRegex(InputSchemaError, "synthetic=true"):
                run_lca._load_farm_document(invalid_path)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_p_ep_ap_and_nreu_are_filtered_from_reports(self) -> None:
        source = {
            "ghg_kg_co2e": 1.0,
            "p_kg": 2.0,
            "phosphorus_kg": 3.0,
            "nested": {
                "ep_kg_po4e": 4.0,
                "ap_kg_so2e": 5.0,
                "nreu_mj": 6.0,
                "nitrogen_g": 7.0,
            },
            "parameter_records": [
                {"parameter_id": "field_ep_factor", "value": 8.0},
                {"parameter_id": "retained_factor", "value": 9.0},
            ],
        }

        filtered = filter_lca_result_for_reporting(source)

        self.assertEqual(filtered["ghg_kg_co2e"], 1.0)
        self.assertEqual(filtered["nested"], {"nitrogen_g": 7.0})
        self.assertNotIn("p_kg", filtered)
        self.assertNotIn("phosphorus_kg", filtered)
        self.assertEqual(
            filtered["parameter_records"],
            [{"parameter_id": "retained_factor", "value": 9.0}],
        )


class SensitivityReproducibilityTests(unittest.TestCase):
    def test_fixed_seed_outputs_are_byte_identical(self) -> None:
        root = _writable_test_directory()
        try:
            first = root / "first"
            second = root / "second"
            files = run_sensitivity.run_synthetic_sensitivity(
                first, iterations=30, seed=20260827
            )
            repeated_files = run_sensitivity.run_synthetic_sensitivity(
                second, iterations=30, seed=20260827
            )

            self.assertEqual(files, repeated_files)
            for file_name in files:
                self.assertEqual(
                    (first / file_name).read_bytes(),
                    (second / file_name).read_bytes(),
                    file_name,
                )

            payload = json.loads(
                (first / "synthetic_sensitivity_result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(payload["sampling"]["random_seed"], 20260827)
            self.assertEqual(payload["sampling"]["simulation_count"], 30)
            self.assertEqual(payload["sampling"]["lca_engine_call_count"], 30)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
