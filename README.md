# Dairy LCA Optimization

This repository provides workflows for dairy-farm life-cycle assessment (LCA), Monte Carlo uncertainty and sensitivity analysis, linear-programming ration optimization, and LCA re-evaluation of optimization scenarios.

## Workflows

1. **Baseline LCA** calculates greenhouse gas, nitrogen-footprint, land-use, production, and allocation results with the Python LCA model.
2. **Sensitivity analysis** propagates parameter uncertainty through the same LCA model using seeded Monte Carlo simulation. The default example runs 10,000 iterations and summarizes the 2.5th and 97.5th percentiles.
3. **Diet optimization** uses R and GLPK to reformulate rations subject to intake and nutritional constraints.
4. **Scenario evaluation** passes the optimized feed quantities and diet properties back into the LCA model and recalculates the results.

### Scenarios

| Scenario | Definition |
|---|---|
| S1: GWP optimization | Reformulates rations to minimize GWP intensity. |
| S2: Multi-objective optimization | Uses equal weights for normalized GWP intensity, nitrogen footprint, and ration cost. |
| S3: Efficiency optimization | Retains the BAU ration composition and assumes a 5% improvement in feed conversion efficiency, represented by a 5% reduction in feed intake at unchanged modeled milk output. |

## Requirements

- Python 3.11 or newer; the Python workflows use only the standard library.
- R 4.1 or newer.
- R packages `ompr`, `ompr.roi`, `ROI`, and `ROI.plugin.glpk`, with a working GLPK backend.

Install the R packages with:

```r
install.packages(c("ompr", "ompr.roi", "ROI", "ROI.plugin.glpk"))
```

## Repository structure

| Path | Contents |
|---|---|
| `src/dairy_lca/` | Python LCA calculation modules |
| `workflows/` | Baseline, sensitivity, optimization, and scenario scripts |
| `templates/` | Blank input templates |
| `examples/` | Synthetic inputs for running the workflows |
| `docs/input_guide.md` | Input files and unit conventions |
| `tests/` | Workflow and integration tests |

## Run the examples

Run the following commands from the repository root. The R optimization must finish before the scenario evaluation.

```bash
python workflows/run_lca.py --example
python workflows/run_sensitivity.py --example
Rscript workflows/optimize_diet.R --example
python workflows/evaluate_scenarios.py --example
```

The main outputs are:

| Workflow | Output |
|---|---|
| Baseline LCA | `outputs/synthetic_example/` |
| Sensitivity analysis | `outputs/synthetic_sensitivity/` |
| Diet optimization | `outputs/synthetic_optimization/optimized_diet.csv` |
| Scenario evaluation | `outputs/synthetic_scenarios/synthetic_scenario_results.csv` |

The files under `examples/` are synthetic inputs provided to demonstrate execution. See [`docs/input_guide.md`](docs/input_guide.md) for the blank templates and key unit conventions.

## Tests

```bash
python -m unittest discover -s tests -v
```

## License

Copyright (c) 2026 Jingjun Wang.

This project is licensed under the GNU General Public License version 3 only (`GPL-3.0-only`). See [`LICENSE`](LICENSE).
