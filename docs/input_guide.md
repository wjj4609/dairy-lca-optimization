# Input guide

Blank input files are provided under `templates/`. Keep the original templates unchanged and prepare completed copies for calculation. Column names and units must remain as shown in the templates.

## Templates

| Template | Purpose |
|---|---|
| `farm_input_template.csv` | Farm activity data for the LCA modules |
| `parameter_template.csv` | Emission factors, conversion factors, and other model parameters |
| `sensitivity_parameter_template.csv` | Probability distributions used in the Monte Carlo analysis |
| `diet_optimization_feed_template.csv` | Feed properties and feed-level GWP, NFP, and cost coefficients |
| `diet_optimization_constraint_template.csv` | Intake and nutritional bounds by farm group and animal stage |
| `optimization_input_template.csv` | Optional solver-neutral linear-programming schema; it is not used by `optimize_diet.R` |

The `required_by` and `description` columns in `parameter_template.csv` identify where each parameter is used. The `required_when`, `null_rule`, and `description` columns in the long-format templates define how each input field is interpreted.

## General rules

- Replace all placeholder identifiers in completed files.
- Keep field names, units, and metadata columns unchanged.
- In long-format templates, enter data in the `value` column. When adding a repeated record, copy its complete row block and assign a unique `record_id`.
- Related identifiers must match across files, including feed, group, stage, parameter, parent, and method IDs.
- Parameter values must be numeric and use the unit stated in `parameter_template.csv`.
- Lower bounds must not exceed their corresponding upper bounds.

## Diet-optimization units

| Input | Unit |
|---|---|
| Fresh-feed intake decision variable | kg/day |
| Dry matter intake (DMI) bounds | kg/day |
| Dry matter proportion | % |
| Net energy for lactation | MJ/kg DM |
| Crude protein, NDF, calcium, phosphorus, and forage proportion | % DM |
| Feed GWP coefficient | kg CO2e/kg fresh feed |
| Feed NFP coefficient | g N/kg fresh feed |
| Feed cost | currency unit/t fresh feed |

Dry matter proportion and fields reported as `% DM` are entered on the percentage scale and converted within the R workflow. Fields explicitly labelled as fractions in the long-format LCA templates use values from 0 to 1.

## Workflow inputs

The bundled examples use the following files:

| Workflow | Inputs |
|---|---|
| Baseline LCA | `synthetic_farm.json`, `synthetic_parameters.csv`, `synthetic_diet.csv`, and `synthetic_constraints.csv` |
| Sensitivity analysis | Baseline farm and parameter inputs plus `synthetic_sensitivity.csv` |
| Diet optimization | `synthetic_optimization_feed.csv` and `synthetic_optimization_constraints.csv` |
| Scenario evaluation | The S1 and S2 optimization outputs plus `synthetic_scenario_bau.json` and `synthetic_scenario_bau_diet.csv` |

To run the R optimizer with completed input files:

```bash
Rscript workflows/optimize_diet.R \
  --feed path/to/feed.csv \
  --constraints path/to/constraints.csv \
  --output-dir outputs/my_optimization
```

The resulting `optimized_diet.csv` contains both S1 and S2 feed quantities, distinguished by the `scenario` column.
