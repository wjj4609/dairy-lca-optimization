"""Parameter names and units only; this module deliberately contains no values."""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class ParameterSpec:
    parameter_id: str
    unit: str
    required_by: str
    description: str


STATIC_PARAMETER_SPECS = (
    ParameterSpec("energy.electricity_ghg_factor", "kg CO2e/kWh", "energy; field; manure", "Electricity greenhouse-gas factor selected by the caller."),
    ParameterSpec("energy.coal_ghg_factor", "kg CO2e/kg coal", "energy", "Coal greenhouse-gas factor."),
    ParameterSpec("energy.diesel_density_kg_l", "kg/L", "energy; feed production; field; transport", "Diesel density."),
    ParameterSpec("energy.diesel_ghg_factor", "kg CO2e/kg diesel", "energy; field; transport", "Diesel greenhouse-gas factor."),
    ParameterSpec("energy.coal_lhv_mj_kg", "MJ/kg", "energy", "Coal lower heating value."),
    ParameterSpec("energy.diesel_energy_content_mj_l", "MJ/L", "energy; feed production; field; transport", "Diesel energy content."),
    ParameterSpec("energy.natural_gas_lhv_mj_m3", "MJ/m3", "energy", "Natural-gas lower heating value."),
    ParameterSpec("enteric.rom_npn_correction_factor", "factor", "enteric", "Correction applied to non-protein nitrogen in residual organic matter."),
    ParameterSpec("enteric.diet_energy_ndf_factor_mcal_kg", "Mcal/kg DM", "enteric", "Diet-energy factor for neutral detergent fibre."),
    ParameterSpec("enteric.diet_energy_starch_factor_mcal_kg", "Mcal/kg DM", "enteric", "Diet-energy factor for starch."),
    ParameterSpec("enteric.diet_energy_rom_factor_mcal_kg", "Mcal/kg DM", "enteric", "Diet-energy factor for residual organic matter."),
    ParameterSpec("enteric.diet_energy_fatty_acid_factor_mcal_kg", "Mcal/kg DM", "enteric", "Diet-energy factor for fatty acids."),
    ParameterSpec("enteric.diet_energy_true_protein_factor_mcal_kg", "Mcal/kg DM", "enteric", "Diet-energy factor for true protein."),
    ParameterSpec("enteric.diet_energy_npn_factor_mcal_kg", "Mcal/kg DM", "enteric", "Diet-energy factor for non-protein nitrogen."),
    ParameterSpec("enteric.methane_energy_content_mj_kg", "MJ/kg CH4", "enteric", "Energy content of methane."),
    ParameterSpec("enteric.methane_conversion_factor_pct", "percent", "enteric", "Share of gross energy converted to methane."),
    ParameterSpec("characterization.gwp_ch4_100yr", "kg CO2e/kg CH4", "enteric; manure", "Biogenic methane 100-year global warming potential."),
    ParameterSpec("nutrition.protein_to_nitrogen_factor", "kg CP/kg N", "enteric; manure", "Crude-protein to nitrogen conversion factor."),
    ParameterSpec("field.nox_from_n2o_n_factor", "factor", "field", "NOx-N derived per unit N2O-N."),
    ParameterSpec("field.n_runoff_fraction", "fraction", "field", "Nitrogen runoff fraction."),
    ParameterSpec("field.n_leaching_fraction", "fraction", "field", "Nitrogen leaching fraction applied to the residual balance."),
    ParameterSpec("field.p_runoff_fraction", "fraction", "field", "Phosphorus runoff fraction."),
    ParameterSpec("field.p_leaching_fraction", "fraction", "field", "Phosphorus leaching fraction applied to the residual balance."),
    ParameterSpec("field.urea_co2_factor", "kg CO2/kg urea", "field", "Carbon-dioxide emission factor for urea application."),
    ParameterSpec("characterization.gwp_n2o_100yr", "kg CO2e/kg N2O", "field; transport; manure", "Nitrous-oxide 100-year global warming potential."),
    ParameterSpec("transport.diesel_n2o_kg_per_tj", "kg N2O/TJ", "field; transport", "Diesel-combustion nitrous-oxide factor."),
    ParameterSpec("transport.road_payload_t", "t", "transport", "Loaded road-vehicle payload."),
    ParameterSpec("transport.road_loaded_fuel_l_100km", "L/100 km", "transport", "Loaded road-vehicle fuel consumption."),
    ParameterSpec("transport.sea_effective_capacity_t", "t cargo", "transport", "Effective vessel cargo capacity."),
    ParameterSpec("transport.sea_speed_kn", "kn", "transport", "Vessel speed in nautical miles per hour."),
    ParameterSpec("transport.sea_load_factor", "fraction", "transport", "Main-engine load factor."),
    ParameterSpec("transport.sea_engine_power_kw", "kW", "transport", "Main-engine rated power."),
    ParameterSpec("transport.sea_load_power_correction_factor", "factor", "transport", "Externally supplied vessel load-power correction."),
    ParameterSpec("transport.hfo_specific_fuel_g_kwh", "g/kWh", "transport", "Heavy-fuel-oil specific consumption."),
    ParameterSpec("transport.hfo_co2_kg_t", "kg CO2/t HFO", "transport", "HFO carbon-dioxide factor."),
    ParameterSpec("transport.hfo_ch4_kg_t", "kg CH4/t HFO", "transport", "HFO methane factor."),
    ParameterSpec("transport.hfo_n2o_kg_t", "kg N2O/t HFO", "transport", "HFO nitrous-oxide factor."),
    ParameterSpec("transport.hfo_nox_kg_t", "kg NOx/t HFO", "transport", "HFO nitrogen-oxides factor."),
    ParameterSpec("transport.hfo_co_kg_t", "kg CO/t HFO", "transport", "HFO carbon-monoxide factor."),
    ParameterSpec("transport.hfo_sox_kg_t", "kg SOx/t HFO", "transport", "HFO sulfur-oxides factor used in acidification characterization."),
    ParameterSpec("characterization.gwp_ch4_fossil_100yr", "kg CO2e/kg CH4", "transport", "Fossil methane 100-year global warming potential."),
    ParameterSpec("manure.volatile_solids_kg_per_1000kg_bw_day", "kg VS/(1000 kg BW day)", "manure", "Volatile-solids excretion factor."),
    ParameterSpec("manure.nitrogen_retention_fraction", "fraction", "manure", "Animal nitrogen-retention fraction."),
    ParameterSpec("manure.feces_dry_matter_fraction", "fraction", "manure", "Manure faecal dry-matter fraction."),
    ParameterSpec("manure.feces_phosphorus_dm_fraction", "fraction", "manure", "Phosphorus fraction of faecal dry matter."),
    ParameterSpec("manure.total_carbon_vs_ratio", "kg C/kg VS", "manure", "Total-carbon to volatile-solids ratio."),
    ParameterSpec("manure.heat_generation_ghg_factor", "kg CO2e/MJ", "manure", "Displaced heat-generation greenhouse-gas factor."),
    ParameterSpec("overall.fpcm_base_factor", "kg FPCM/kg milk", "overall", "Base term in the FPCM equation."),
    ParameterSpec("overall.fpcm_fat_factor", "kg FPCM/kg milk per fat fraction", "overall", "Milk-fat term in the FPCM equation."),
    ParameterSpec("overall.fpcm_protein_factor", "kg FPCM/kg milk per protein fraction", "overall", "Milk-protein term in the FPCM equation."),
    ParameterSpec("characterization.ep_n_factor", "g PO4e/g N", "overall", "Eutrophication factor for nitrogen."),
    ParameterSpec("characterization.ep_p_factor", "g PO4e/g P", "overall", "Eutrophication factor for phosphorus."),
    ParameterSpec("characterization.ap_n_factor", "g SO2e/g N", "overall", "Acidification factor for nitrogen."),
    ParameterSpec("characterization.ap_so2_factor", "g SO2e/g SO2", "overall", "Acidification factor for sulfur dioxide equivalent mass."),
)

STATIC_PARAMETER_UNITS = MappingProxyType(
    {spec.parameter_id: spec.unit for spec in STATIC_PARAMETER_SPECS}
)

_FIELD_METHOD = re.compile(
    r"^field\.application\.[^.]+\.(?:nh3|n2o)_fraction$"
)
_MANURE_METHOD = re.compile(
    r"^manure\.(?:housing|storage_treatment|land_application)\.[^.]+\."
    r"(?:ammonia_volatilization|nitrous_oxide_emission|nitrogen_oxide_emission|"
    r"nitrogen_leaching|nitrogen_runoff|methane_emission|"
    r"carbon_dioxide_emission|phosphorus_leaching|phosphorus_runoff)_fraction$"
)


def registered_parameter_unit(parameter_id: str) -> str | None:
    """Return the required unit for a static or method-specific model parameter."""

    unit = STATIC_PARAMETER_UNITS.get(parameter_id)
    if unit is not None:
        return unit
    if _FIELD_METHOD.fullmatch(parameter_id) or _MANURE_METHOD.fullmatch(parameter_id):
        return "fraction"
    return None
