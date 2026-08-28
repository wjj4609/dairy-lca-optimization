"""Generic Production-only dairy LCA calculation package."""

from .batch import (
    FarmBatchCalculator,
    FarmBatchInput,
    FarmBatchResult,
    FarmModelCalculator,
    FarmModelInput,
    FarmModelResult,
    calculate_farm_batch,
    calculate_farm_model,
)
from .catalog import Parameter, ParameterCatalog
from .input_schema import (
    LinearCoefficientInput,
    LinearConstraintInput,
    LinearDecisionInput,
    LinearObjectiveInput,
    OptimizationModelInput,
    load_farm_input_csv,
    load_optimization_input_csv,
    validate_farm_input_template,
    validate_optimization_input_template,
)
from .parameter_schema import ParameterSpec, STATIC_PARAMETER_SPECS
from .results import ImpactTotals

__version__ = "0.1.0"

__all__ = [
    "FarmBatchCalculator",
    "FarmBatchInput",
    "FarmBatchResult",
    "FarmModelCalculator",
    "FarmModelInput",
    "FarmModelResult",
    "ImpactTotals",
    "LinearCoefficientInput",
    "LinearConstraintInput",
    "LinearDecisionInput",
    "LinearObjectiveInput",
    "OptimizationModelInput",
    "Parameter",
    "ParameterCatalog",
    "ParameterSpec",
    "STATIC_PARAMETER_SPECS",
    "calculate_farm_batch",
    "calculate_farm_model",
    "load_farm_input_csv",
    "load_optimization_input_csv",
    "validate_farm_input_template",
    "validate_optimization_input_template",
]
