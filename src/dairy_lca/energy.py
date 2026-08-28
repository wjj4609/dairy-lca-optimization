"""Annual farm-energy inventory for the public Production calculation path."""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import ParameterCatalog
from .results import AppliedParameter, ImpactTotals
from .validation import identifier, number

KG_PER_TONNE = 1000.0
KWH_TO_MJ = 3.6


@dataclass(frozen=True)
class EnergyUseInput:
    """Annual energy activities; all values are supplied at runtime."""

    electricity_kwh_year: float = 0.0
    coal_t_year: float = 0.0
    diesel_l_year: float = 0.0
    natural_gas_m3_year: float = 0.0
    electricity_ghg_parameter_id: str = "energy.electricity_ghg_factor"


@dataclass(frozen=True)
class EnergyUseResult:
    electricity_ghg_kg_co2e_year: float
    coal_ghg_kg_co2e_year: float
    diesel_ghg_kg_co2e_year: float
    diesel_mass_kg_year: float
    electricity_nreu_mj_year: float
    coal_nreu_mj_year: float
    diesel_nreu_mj_year: float
    natural_gas_nreu_mj_year: float
    impacts: ImpactTotals
    applied_parameters: tuple[AppliedParameter, ...]


class EnergyUseCalculator:
    """Calculate direct energy GHG emissions and non-renewable energy use."""

    def __init__(self, catalog: ParameterCatalog):
        self.catalog = catalog

    def calculate(self, activity: EnergyUseInput) -> EnergyUseResult:
        electricity = number(
            "electricity_kwh_year", activity.electricity_kwh_year, nonnegative=True
        )
        coal = number("coal_t_year", activity.coal_t_year, nonnegative=True)
        diesel = number("diesel_l_year", activity.diesel_l_year, nonnegative=True)
        natural_gas = number(
            "natural_gas_m3_year", activity.natural_gas_m3_year, nonnegative=True
        )
        electricity_factor_id = identifier(
            "electricity_ghg_parameter_id", activity.electricity_ghg_parameter_id
        )

        applied: dict[str, AppliedParameter] = {}

        def use(parameter_id: str, expected_unit: str | None = None) -> float:
            value = self.catalog.model_value(
                parameter_id, expected_unit=expected_unit
            )
            applied.setdefault(
                parameter_id, AppliedParameter.from_catalog(self.catalog, parameter_id)
            )
            return value

        electricity_ghg = (
            electricity * use(electricity_factor_id, "kg CO2e/kWh")
            if electricity
            else 0.0
        )
        coal_ghg = (
            coal * KG_PER_TONNE * use("energy.coal_ghg_factor") if coal else 0.0
        )
        if diesel:
            diesel_mass = diesel * use("energy.diesel_density_kg_l")
            diesel_ghg = diesel_mass * use("energy.diesel_ghg_factor")
        else:
            diesel_mass = 0.0
            diesel_ghg = 0.0

        electricity_nreu = electricity * KWH_TO_MJ
        coal_nreu = (
            coal * KG_PER_TONNE * use("energy.coal_lhv_mj_kg") if coal else 0.0
        )
        diesel_nreu = (
            diesel * use("energy.diesel_energy_content_mj_l") if diesel else 0.0
        )
        natural_gas_nreu = (
            natural_gas * use("energy.natural_gas_lhv_mj_m3")
            if natural_gas
            else 0.0
        )
        impacts = ImpactTotals(
            ghg_kg_co2e_year=electricity_ghg + coal_ghg + diesel_ghg,
            nitrogen_g_year=0.0,
            phosphorus_g_year=0.0,
            nreu_mj_year=(
                electricity_nreu + coal_nreu + diesel_nreu + natural_gas_nreu
            ),
            land_m2_year=0.0,
            sulfur_dioxide_kg_year=0.0,
        )
        return EnergyUseResult(
            electricity_ghg_kg_co2e_year=electricity_ghg,
            coal_ghg_kg_co2e_year=coal_ghg,
            diesel_ghg_kg_co2e_year=diesel_ghg,
            diesel_mass_kg_year=diesel_mass,
            electricity_nreu_mj_year=electricity_nreu,
            coal_nreu_mj_year=coal_nreu,
            diesel_nreu_mj_year=diesel_nreu,
            natural_gas_nreu_mj_year=natural_gas_nreu,
            impacts=impacts,
            applied_parameters=tuple(applied.values()),
        )


def calculate_energy_use(
    catalog: ParameterCatalog, activity: EnergyUseInput
) -> EnergyUseResult:
    return EnergyUseCalculator(catalog).calculate(activity)
