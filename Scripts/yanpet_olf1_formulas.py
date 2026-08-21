# -*- coding: utf-8 -*-
"""
Plant physics plug-in : YANPET Olefin-1 (YP-OLF1)
====================================================================
This is the ONLY file that should contain YANPET-specific equipment
physics (furnace COT correlation, PRC turbine/compressor thermodynamics).
Everything generic (Kalman prediction sequencing, constraint handling,
user overrides) now lives in whatif_runner.py's plant-agnostic engine.

To reuse the what-if platform for a different plant:
  1. Copy this file to plants/<your_plant_name>_formulas.py
     (name must match the plant folder name, lower-cased).
  2. Replace the two hook functions below with that plant's own
     physics (or delete them and keep HOOKS = {} if the plant is
     fully Kalman-driven with no bespoke physics).
  3. Update OWNED_PARAMETERS / SKIP_PARAMETERS to match which
     "Predicted parameter" rows in that plant's Model details sheet
     are computed by physics instead of / never run through Kalman.

The engine in whatif_runner.py auto-discovers this file by plant name;
nothing else needs to change.
====================================================================
"""
import numpy as np
from CoolProp.CoolProp import PropsSI
from scipy.optimize import minimize_scalar

# ---------------------------------------------------------------------
# Predicted parameters (per the "Model details" sheet) that this plugin
# fully owns -> the generic engine will NOT run a Kalman prediction for
# them, but will still run hooks / user-override / constraints on them.
# ---------------------------------------------------------------------
OWNED_PARAMETERS = {"PRC_Total_estimated_power_MW"}

# Predicted parameters whose OWN slot in the execution order does
# nothing -- the engine just `continue`s past them -- because their
# value is set as a side effect of something else instead:
#   "Overall_COT": set inside furnace_cot_hook (as an alias of the real
#   'Coil_Avg_COT' historian tag / its bias-corrected estimate) and, for
#   bulk historical rows, via BULK_SIMULATION below. Nothing extra is
#   needed from its own execution-order slot.
SKIP_PARAMETERS = {"Overall_COT"}

# ---------------------------------------------------------------------
# Calculated variables this plant wants shown as executive KPI tiles in
# the What-if Dashboard, IN ADDITION to the config-driven ones (every
# "Predicted parameter" from the Model details sheet and every
# "Parameter" from the Constraints sheet). These are derived plant-level
# totals computed by totals_hook below -- they exist in the results
# table but appear in neither config sheet, so without this list the
# dashboard would have no plant-agnostic way to know they matter.
# ---------------------------------------------------------------------
KPI_PARAMETERS = [
    "Total_Power_(KW)",
    "Total_required_steam_flow_(TPH)",
]

# ---------------------------------------------------------------------
# KPI tile substitutions: {tag as it appears in the config sheets ->
# tag to actually show as the KPI}. The config's Model details /
# Constraints sheets reference the RAW historian tag
# 'PRC_turbine_steam_flow' (that's what gets constrained/overridden),
# but the executive KPI worth watching is the simulated steam flow
# matched to the estimated compressor power --
# 'PRC_turbine_Calculated_Steam_flow_TPH', computed by prc_turbine_hook
# above -- so the dashboard swaps the tile accordingly. The raw tag
# still appears, unchanged, in the full Actual-vs-estimated table.
# ---------------------------------------------------------------------
KPI_REPLACEMENTS = {
    "PRC_turbine_steam_flow": "PRC_turbine_Calculated_Steam_flow_TPH",
}


# =====================================================================
# Furnace COT (Coil Outlet Temperature) correlation
# =====================================================================
def _COT_calculation(df_furnace):
    df_furnace['Plant_average_feed_rate_Coil'] = df_furnace["DMCTF_feed"] / (df_furnace["Number_Of_Furnaces_Online"] * 4)

    df_furnace['Coil_CIP_Calculated'] = (-131.3081 +
            (0.0755 * df_furnace['Plant_average_feed_rate_Coil']) +
            (0.1463 * df_furnace['Ethane_Feed_Preheater_Ethane_Feed_Outlet_Pressure']) +
            (0.6819 * df_furnace['Furnace_Ethane_Feed_Preheater_Ethane_Feed_Outlet_Temperature']) +
            (0.4853 * df_furnace['Coil_Weighted_Avg_Feed_CV_opening']) +
            (0.8766 * df_furnace['Coil_Weighted_Avg_Steam_CV_opening']))

    df_furnace['Coil_Steam_Flow'] = (df_furnace['Coil_Avg_SHC_Ratio'] * df_furnace['Plant_average_feed_rate_Coil'])

    df_furnace['Coil_Mixed_Feed_flow'] = df_furnace['Coil_Steam_Flow'] + df_furnace['Plant_average_feed_rate_Coil']

    df_furnace['Coil_Mixed_Feed_Cp'] = (
        (df_furnace['Coil_Steam_Flow'] * 2.067) +
        (df_furnace['Plant_average_feed_rate_Coil'] * 1.909)
    ) / (df_furnace['Coil_Steam_Flow'] + df_furnace['Plant_average_feed_rate_Coil'])

    df_furnace['Coil_Mixed_Feed_Mol_wt'] = (
        df_furnace['Coil_Mixed_Feed_flow'] /
        (
            (df_furnace['Plant_average_feed_rate_Coil'] / df_furnace["Furnace_Feed_Average_Molecular_Wt"]) +
            (df_furnace['Coil_Steam_Flow'] / 18.0)
        )
    )

    df_furnace['Coil_Volumetric_Flow'] = (
        df_furnace['Coil_Mixed_Feed_flow']
    ) / (
        ((df_furnace['Coil_CIP_Calculated'] + 101.325) *
          0.00982963 * df_furnace['Coil_Mixed_Feed_Mol_wt']) /
        (0.08206 * (df_furnace['Coil_Weighted_Avg_Coil_Mixed_Feed_Inlet_Temperature'] + 273.15))
    )

    df_furnace['Coil_CIP_Corrected_atma'] = np.where(
        (df_furnace['Coil_CIP_Calculated'] / 101.325 + 1) < 5,
        (df_furnace['Coil_CIP_Calculated'] / 101.325 + 1) -
        (df_furnace['Coil_Volumetric_Flow'] * 144 / 1309.83) * 0.00986923,
        (df_furnace['Coil_CIP_Calculated'] / 101.325 + 1) -
        (df_furnace['Coil_Volumetric_Flow'] * 131 / 1209.52) * 0.00986923
    )
    return df_furnace


def furnace_cot_hook(selected_row, selected_row_updated):
    """Registered as HOOKS['after:CGC_STAGE_1_SUCTION_PRESSURE'].
    Recomputes actual & estimated Coil Avg COT and applies a bias
    correction so the estimate tracks the plant's historical COT."""
    selected_row = _COT_calculation(selected_row)

    Delta_CGC_Suction_Pressure_old = 0
    selected_row['Corrected_COP_Furnace'] = selected_row['Coil_Weighted_Avg_COP'] + Delta_CGC_Suction_Pressure_old
    selected_row['Furnace_Effluent_C2H6'] = (selected_row['DMCTF_feed'] / 1000) * (selected_row['Furnace_Normalised_Feed_C2H6_Wt'] / 100) * (1 - selected_row['Furnace_conversion'])
    selected_row['Furnace_Effluent_C2H6_wt%'] = (selected_row['Furnace_Effluent_C2H6'] / (selected_row['DMCTF_feed'] / 1000)) * 100
    selected_row['Coil_Avg_COT_actual'] = ((
        0.937913371 * (selected_row['Coil_CIP_Corrected_atma'] - 0.3) -
        2.413045433 * (selected_row['Corrected_COP_Furnace'] / 101.325 + 1 - 0.2) +
        2.774285758 * selected_row['Coil_Avg_SHC_Ratio'] +
        0.002253435 * selected_row['Plant_average_feed_rate_Coil'] -
        0.463411867 * selected_row['Furnace_Normalised_Feed_C3H8_Wt'] +
        0.674941411 * selected_row['Furnace_Normalised_Feed_C2H6_Wt'] +
        337.8851416 - selected_row['Furnace_Effluent_C2H6_wt%']
        )) / 0.451606991

    selected_row_updated = _COT_calculation(selected_row_updated)

    Delta_CGC_Suction_Pressure = selected_row_updated["CGC_STAGE_1_SUCTION_PRESSURE"] - selected_row["CGC_STAGE_1_SUCTION_PRESSURE"]
    selected_row_updated['Corrected_COP_Furnace'] = selected_row_updated['Coil_Weighted_Avg_COP'] + Delta_CGC_Suction_Pressure

    if ((selected_row_updated['DMCTF_feed'].iloc[0] / 1000) - selected_row_updated['Fresh_ethane_feed'].iloc[0]) > 70:
        selected_row_updated['Fresh_ethane_feed'] = (selected_row_updated['DMCTF_feed'] / 1000) - 70

    selected_row_updated['Furnace_conversion'] = ((selected_row_updated['DMCTF_feed'] / 1000) * (selected_row_updated['Furnace_Normalised_Feed_C2H6_Wt'] / 100) -
                                (selected_row_updated['DMCTF_feed'] / 1000 - selected_row_updated['Fresh_ethane_feed'])) / ((selected_row_updated['DMCTF_feed'] / 1000) * selected_row_updated['Furnace_Normalised_Feed_C2H6_Wt'] / 100)

    selected_row_updated['Furnace_Effluent_C2H6'] = (selected_row_updated['DMCTF_feed'] / 1000) * (selected_row_updated['Furnace_Normalised_Feed_C2H6_Wt'] / 100) * (1 - selected_row_updated['Furnace_conversion'])
    selected_row_updated['Furnace_Effluent_C2H6_wt%'] = (selected_row_updated['Furnace_Effluent_C2H6'] / (selected_row_updated['DMCTF_feed'] / 1000)) * 100

    selected_row_updated['Coil_Avg_COT'] = ((
        0.937913371 * (selected_row_updated['Coil_CIP_Corrected_atma'] - 0.3) -
        2.413045433 * (selected_row_updated['Corrected_COP_Furnace'] / 101.325 + 1 - 0.2) +
        2.774285758 * selected_row_updated['Coil_Avg_SHC_Ratio'] +
        0.002253435 * selected_row_updated['Plant_average_feed_rate_Coil'] -
        0.463411867 * selected_row_updated['Furnace_Normalised_Feed_C3H8_Wt'] +
        0.674941411 * selected_row_updated['Furnace_Normalised_Feed_C2H6_Wt'] +
        337.8851416 - selected_row_updated['Furnace_Effluent_C2H6_wt%']
        )) / 0.451606991

    delta_COT = selected_row_updated['Coil_Avg_COT'] - selected_row['Coil_Avg_COT_actual']
    selected_row_updated['Coil_Avg_COT'] = selected_row['Coil_Avg_COT'] + delta_COT

    # 'Overall_COT' (the name used in the Model details sheet) is the
    # same physical quantity as 'Coil_Avg_COT' (the real measured
    # historian tag, bias-corrected for the current scenario) -- just
    # exposed under the name the config/KPI cards/Actual-vs-estimated
    # table expect.
    selected_row['Overall_COT'] = selected_row['Coil_Avg_COT']
    selected_row_updated['Overall_COT'] = selected_row_updated['Coil_Avg_COT']

    return selected_row, selected_row_updated


# =====================================================================
# PRC (Propylene Refrigeration Compressor) section thermodynamics
# =====================================================================
def _PRC_section_power(df):
    Density_1st_stage, rho_1st_stage_flow = [], []
    for i in range(len(df)):
        T_K = df["PRC_1ST_STAGE_Suction_TEMP"].iloc[i] + 273.15
        P_Pa = df["PRC_1ST_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5
        rho_1st_stage = PropsSI('D', 'T', T_K, 'P', P_Pa, 'Propylene')
        volumetric_flow = df["PRC_1ST_STAGE_Suction_FLOW"].iloc[i] * 1000 / rho_1st_stage
        rho_1st_stage_flow.append(volumetric_flow)
        Density_1st_stage.append(rho_1st_stage)
    df["PRC_Density_1st_stage"] = Density_1st_stage
    df["PRC VOL FLOW 1ST STAGE"] = rho_1st_stage_flow

    Density_2nd_stage, rho_2nd_stage_flow = [], []
    for i in range(len(df)):
        T_K = df["PRC_2nd_stage_drum_Overhead_Temp"].iloc[i] + 273.15
        P_Pa = df["PRC_2ND_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5
        rho_2nd_stage = PropsSI('D', 'T', T_K, 'P', P_Pa, 'Propylene')
        volumetric_flow = (df["PRC_1ST_STAGE_Suction_FLOW"].iloc[i] + df["PRC_2nd_stage_drum_Overhead_Flow"].iloc[i]) * 1000 / rho_2nd_stage
        rho_2nd_stage_flow.append(volumetric_flow)
        Density_2nd_stage.append(rho_2nd_stage)
    df["PRC_Density_2nd_stage"] = Density_2nd_stage
    df["PRC VOL FLOW 2ND STAGE"] = rho_2nd_stage_flow

    Density_3rd_stage, rho_3rd_stage_flow = [], []
    for i in range(len(df)):
        T_K = df["PRC_3RD_STAGE_Suction_TEMP"].iloc[i] + 273.15
        P_Pa = df["PRC_3RD_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5
        rho_3rd_stage = PropsSI('D', 'T', T_K, 'P', P_Pa, 'Propylene')
        volumetric_flow = df["PRC_3RD_STAGE_Suction_FLOW"].iloc[i] * 1000 / rho_3rd_stage
        rho_3rd_stage_flow.append(volumetric_flow)
        Density_3rd_stage.append(rho_3rd_stage)
    df["PRC_Density_3rd_stage"] = Density_3rd_stage
    df["PRC VOL FLOW 3RD STAGE"] = rho_3rd_stage_flow

    # Compressor power via isentropic enthalpy at outlet pressure (constant entropy).
    eta = 0.70
    PRC_1st_stage_comp_estimated_power = []
    for i in range(len(df)):
        h1 = PropsSI('H', 'T', df["PRC_1ST_STAGE_Suction_TEMP"].iloc[i] + 273.15, 'P', df["PRC_1ST_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5, 'Propylene')
        s1 = PropsSI('S', 'T', df["PRC_1ST_STAGE_Suction_TEMP"].iloc[i] + 273.15, 'P', df["PRC_1ST_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5, 'Propylene')
        h2s = PropsSI('H', 'P', df["PRC_1ST_STAGE_Discharge_PRESSURE"].iloc[i] * 1000 + 1e5, 'S', s1, 'Propylene')
        h2 = h1 + (h2s - h1) / eta
        power = ((df["PRC_1ST_STAGE_Suction_FLOW"].iloc[i] * 1000) / 3600) * (h2 - h1) / 1e6
        PRC_1st_stage_comp_estimated_power.append(power)
    df["PRC_1st_stage_comp_estimated_power_MW"] = PRC_1st_stage_comp_estimated_power

    PRC_2nd_stage_comp_estimated_power = []
    for i in range(len(df)):
        h1 = PropsSI('H', 'T', df["PRC_2nd_stage_drum_Overhead_Temp"].iloc[i] + 273.15, 'P', df["PRC_2ND_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5, 'Propylene')
        s1 = PropsSI('S', 'T', df["PRC_2nd_stage_drum_Overhead_Temp"].iloc[i] + 273.15, 'P', df["PRC_2ND_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5, 'Propylene')
        h2s = PropsSI('H', 'P', df["PRC_3RD_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5, 'S', s1, 'Propylene')
        h2 = h1 + (h2s - h1) / eta
        power = (((df["PRC_2nd_stage_drum_Overhead_Flow"].iloc[i] + df["PRC_1ST_STAGE_Suction_FLOW"].iloc[i]) * 1000) / 3600) * (h2 - h1) / 1e6
        PRC_2nd_stage_comp_estimated_power.append(power)
    df["PRC_2nd_stage_comp_estimated_power_MW"] = PRC_2nd_stage_comp_estimated_power

    PRC_3rd_stage_comp_estimated_power = []
    for i in range(len(df)):
        h1 = PropsSI('H', 'T', df["PRC_3RD_STAGE_Suction_TEMP"].iloc[i] + 273.15, 'P', df["PRC_3RD_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5, 'Propylene')
        s1 = PropsSI('S', 'T', df["PRC_3RD_STAGE_Suction_TEMP"].iloc[i] + 273.15, 'P', df["PRC_3RD_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5, 'Propylene')
        h2s = PropsSI('H', 'P', df["PRC_3RD_STAGE_Discharge_PRESSURE"].iloc[i] * 1000 + 1e5, 'S', s1, 'Propylene')
        h2 = h1 + (h2s - h1) / eta
        power = ((df["PRC_3RD_STAGE_Suction_FLOW"].iloc[i] * 1000) / 3600) * (h2 - h1) / 1e6
        PRC_3rd_stage_comp_estimated_power.append(power)
    df["PRC_3rd_stage_comp_estimated_power_MW"] = PRC_3rd_stage_comp_estimated_power

    df["PRC_Total_estimated_power_MW"] = (df["PRC_1st_stage_comp_estimated_power_MW"] +
                                           df["PRC_2nd_stage_comp_estimated_power_MW"] +
                                           df["PRC_3rd_stage_comp_estimated_power_MW"])
    return df


def _PRC_turbine_extraction_steam_flow_prediction(df):
    cols = ["PRC_turbine_current_steam_enthalpy_KJ_Kg", "PRC_turbine_current_steam_entropy_KJ_KgK",
            "PRC_turbine_current_outlet_ethalpy_KJ_Kg", "PRC_turbine_current_outlet_isentropic_ethalpy_KJ_Kg",
            "PRC_turbine_current_power_gen_extraction_MW", "PRC_turbine_current_power_gen_exhaust_MW",
            "PRC_turbine_current_Turbine_power_MW_based_on_EE", "PRC_turbine_current_Turbine_power_MW_based_on_steam_flow",
            "PRC_turbine_current_Specific_steam_consumption_MT_MW"]
    buckets = {c: [] for c in cols}

    for i in range(len(df)):
        Steam_flow_TPH = df['PRC_turbine_steam_flow'].iloc[i]
        Condensate_flow_TPH = df['PRC_turbine_condensate_flow'].iloc[i]
        Extraction_flow_TPH = df['PRC_turbine_Extraction_flow'].iloc[i]

        Steam_flow_Kg_hr = Steam_flow_TPH * 1000
        Extraction_flow_Kg_hr = Extraction_flow_TPH * 1000
        Condensate_flow_Kg_hr = Condensate_flow_TPH * 1000

        P_steam = df['PRC_turbine_Steam_pressure'].iloc[i] * 1000
        T_steam = df['PRC_turbine_Steam_Temp'].iloc[i] + 273.15

        Pe = df['PRC_turbine_Extraction_Pressure'].iloc[i] * 1000
        T_sat_extraction = PropsSI('T', 'P', Pe, 'Q', 1, 'Water')

        Pc = df['PRC_turbine_Condensate_Pressure'].iloc[i] * 1000
        T_sat_condensate = PropsSI('T', 'P', Pc, 'Q', 0, 'Water')

        h_steam = PropsSI('H', 'P', P_steam, 'T', T_steam, 'Water') / 1000
        s_steam = PropsSI('S', 'P', P_steam, 'T', T_steam, 'Water') / 1000

        he = PropsSI('H', 'P', Pe, 'T', T_sat_extraction + 0.01, 'Water') / 1000
        hc_liquid = PropsSI('H', 'P', Pc, 'T', T_sat_condensate - 0.01, 'Water') / 1000
        dryness_fraction = 0.92
        hc_vapor = PropsSI('H', 'P', Pc, 'T', T_sat_condensate + 0.01, 'Water') / 1000
        hc = hc_liquid + hc_vapor * dryness_fraction

        power_gen_extraction = Extraction_flow_Kg_hr * (h_steam - he) / 3600 / 1000
        power_gen_exhaust = Condensate_flow_Kg_hr * (h_steam - hc) / 3600 / 1000
        Turbine_power_MW_EE = power_gen_extraction + power_gen_exhaust
        Specific_steam_consumption = Steam_flow_TPH / Turbine_power_MW_EE

        def isentropic_enthalpy(P_target, s_in):
            s_f = PropsSI("S", "P", P_target, "Q", 0, "Water") / 1000
            s_g = PropsSI("S", "P", P_target, "Q", 1, "Water") / 1000
            if s_f < s_in < s_g:
                x = (s_in - s_f) / (s_g - s_f)
                h_f = PropsSI("H", "P", P_target, "Q", 0, "Water")
                h_g = PropsSI("H", "P", P_target, "Q", 1, "Water")
                h_iso = h_f + x * (h_g - h_f)
            else:
                h_iso = PropsSI("H", "P", P_target, "S", s_in, "Water")
            return h_iso / 1000

        he_s = isentropic_enthalpy(Pe, s_steam)
        hc_s = isentropic_enthalpy(Pc, s_steam)
        h2_actual = (Extraction_flow_Kg_hr * he + Condensate_flow_Kg_hr * hc) / Steam_flow_Kg_hr
        h2s_ideal = (Extraction_flow_Kg_hr * he_s + Condensate_flow_Kg_hr * hc_s) / Steam_flow_Kg_hr
        turbine_power_MW_SF = (h_steam - h2_actual) * (Steam_flow_Kg_hr / (3600 * 1000))

        buckets["PRC_turbine_current_steam_enthalpy_KJ_Kg"].append(h_steam)
        buckets["PRC_turbine_current_steam_entropy_KJ_KgK"].append(s_steam)
        buckets["PRC_turbine_current_outlet_ethalpy_KJ_Kg"].append(h2_actual)
        buckets["PRC_turbine_current_outlet_isentropic_ethalpy_KJ_Kg"].append(h2s_ideal)
        buckets["PRC_turbine_current_power_gen_extraction_MW"].append(power_gen_extraction)
        buckets["PRC_turbine_current_power_gen_exhaust_MW"].append(power_gen_exhaust)
        buckets["PRC_turbine_current_Turbine_power_MW_based_on_EE"].append(Turbine_power_MW_EE)
        buckets["PRC_turbine_current_Turbine_power_MW_based_on_steam_flow"].append(turbine_power_MW_SF)
        buckets["PRC_turbine_current_Specific_steam_consumption_MT_MW"].append(Specific_steam_consumption)

    for c in cols:
        df[c] = buckets[c]

    def match_actual_power(row):
        try:
            P_steam = row["PRC_turbine_Steam_pressure"] * 1000
            T_steam = row["PRC_turbine_Steam_Temp"] + 273.15
            h_steam = PropsSI("H", "P", P_steam, "T", T_steam, "Water") / 1000

            Pe = row["PRC_turbine_Extraction_Pressure"] * 1000
            T_sat_extraction = PropsSI('T', 'P', Pe, 'Q', 1, 'Water')
            he = PropsSI('H', 'P', Pe, 'T', T_sat_extraction + 0.01, 'Water') / 1000

            Pc = row["PRC_turbine_Condensate_Pressure"] * 1000
            T_sat_condensate = PropsSI('T', 'P', Pc, 'Q', 0, 'Water')
            hc_liquid = PropsSI('H', 'P', Pc, 'T', T_sat_condensate - 0.01, 'Water') / 1000
            dryness_fraction = 0.92
            hc_vapor = PropsSI('H', 'P', Pc, 'T', T_sat_condensate + 0.01, 'Water') / 1000
            hc = hc_liquid + hc_vapor * dryness_fraction

            condensate_flow_TPH = row["PRC_turbine_condensate_flow"]
            condensate_flow_Kg_hr = condensate_flow_TPH * 1000
            actual_power = row["PRC_Total_estimated_power_MW"]

            def objective(extraction_flow_TPH):
                extraction_flow_Kg_hr = extraction_flow_TPH * 1000
                power = ((extraction_flow_Kg_hr * (h_steam - he)) +
                         (condensate_flow_Kg_hr * (h_steam - hc))) / 3600 / 1000
                return (power - actual_power) ** 2

            result = minimize_scalar(objective, bounds=(10, 350), method='bounded')

            if result.success:
                ef_opt = result.x
                ef_Kg_hr = ef_opt * 1000
                sf_opt = ef_opt + condensate_flow_TPH
                sf_Kg_hr = sf_opt * 1000
                power_matched_EE = ((ef_Kg_hr * (h_steam - he)) + (condensate_flow_Kg_hr * (h_steam - hc))) / 3600 / 1000
                h2_actual = (ef_Kg_hr * he + condensate_flow_Kg_hr * hc) / sf_Kg_hr
                power_matched_SF = (h_steam - h2_actual) * (sf_Kg_hr / 3600 / 1000)
                return ef_opt, sf_opt, power_matched_EE, power_matched_SF, h2_actual
            else:
                return (row["PRC_turbine_Extraction_flow"], row["PRC_turbine_steam_flow"],
                        row["PRC_turbine_current_Turbine_power_MW_based_on_EE"], row["PRC_turbine_current_Turbine_power_MW_based_on_steam_flow"],
                        None)
        except Exception as e:
            print(f"Error at index {row.name}: {e}")
            return (row["PRC_turbine_Extraction_flow"], row["PRC_turbine_steam_flow"],
                    row["PRC_turbine_current_Turbine_power_MW_based_on_EE"], row["PRC_turbine_current_Turbine_power_MW_based_on_steam_flow"],
                    None)

    opt_ext, calc_steam, matched_EE, matched_SF, matched_h2 = [], [], [], [], []
    for _, row in df.iterrows():
        ef, sf, power_EE, power_SF, h2 = match_actual_power(row)
        opt_ext.append(ef); calc_steam.append(sf)
        matched_EE.append(power_EE); matched_SF.append(power_SF); matched_h2.append(h2)

    df["PRC_turbine_Optimized_Extraction_flow_TPH"] = opt_ext
    df["PRC_turbine_Calculated_Steam_flow_TPH"] = calc_steam
    df["PRC_turbine_Matched_Turbine_power_MW_EE"] = matched_EE
    df["PRC_turbine_Matched_Turbine_power_MW_SF"] = matched_SF
    df["PRC_turbine_Matched_h2_actual_KJ_Kg"] = matched_h2
    df["Power_Error"] = df["PRC_turbine_Matched_Turbine_power_MW_EE"] - df["PRC_Total_estimated_power_MW"]
    df["Power_EE_vs_SF_Diff"] = df["PRC_turbine_Matched_Turbine_power_MW_EE"] - df["PRC_turbine_Matched_Turbine_power_MW_SF"]
    df["Devaiation in steam flow (Simulated-actual)"] = df["PRC_turbine_Calculated_Steam_flow_TPH"] - df["PRC_turbine_steam_flow"]
    df["Devaiation in extraction (Simulated-actual)"] = df["PRC_turbine_Optimized_Extraction_flow_TPH"] - df["PRC_turbine_Extraction_flow"]
    df["Specific_steam_consumption_MT_MW_updated"] = df["PRC_turbine_Calculated_Steam_flow_TPH"] / df["PRC_Total_estimated_power_MW"]

    return df


def prc_turbine_hook(selected_row, selected_row_updated):
    """Registered as HOOKS['after:PRC_2nd_stage_drum_Overhead_Flow'].
    Computes PRC compressor-stage power and matches turbine steam/
    extraction flow to the estimated power via CoolProp thermodynamics.
    This is what actually fills in PRC_Total_estimated_power_MW
    (declared in OWNED_PARAMETERS above).

    Runs the SAME physics on BOTH rows:
      * selected_row_updated -- the what-if scenario ('estimated'), and
      * selected_row         -- the untouched baseline ('actual').
    Without the baseline pass, every derived PRC column this hook creates
    (stage densities/volumetric flows, per-stage power, turbine enthalpy/
    entropy, optimized extraction & calculated steam flow, deviations,
    specific steam consumption, ...) exists ONLY in the estimated row --
    so the Actual-vs-estimated table and the KPI tiles show a blank
    actual and a blank/zero Change for all of them."""
    # Scenario / 'estimated' side
    selected_row_updated = _PRC_section_power(selected_row_updated)
    selected_row_updated = _PRC_turbine_extraction_steam_flow_prediction(selected_row_updated)

    # Baseline / 'actual' side -- same physics on the baseline inputs so
    # every derived column has a real actual value to compare against.
    try:
        selected_row = _PRC_section_power(selected_row)
        selected_row = _PRC_turbine_extraction_steam_flow_prediction(selected_row)
    except Exception as e:  # noqa: BLE001
        print(f"[yanpet_olf1] could not compute baseline (actual) PRC values: {e}; "
              f"the actual column will stay blank for the PRC-derived parameters.")

    return selected_row, selected_row_updated


# =====================================================================
# Plant-level aggregate totals (CGC + PRC + ERC sections)
# =====================================================================
def totals_hook(selected_row, selected_row_updated):
    """Registered as HOOKS['after:ERC_1ST_STAGE_Suction_PRESSURE'].
    Computes the plant-level totals on BOTH rows -- the scenario
    ('estimated') and the baseline ('actual') -- so the comparison table
    and KPI tiles always have an actual value and a real Change for
    Total_Power_(KW) and Total_required_steam_flow_(TPH), even when the
    historian workbook predates these columns (or training skipped them
    because PRC_turbine_Calculated_Steam_flow_TPH wasn't in the bulk
    dataset)."""
    for _label, _row in (("estimated", selected_row_updated), ("actual", selected_row)):
        try:
            _row["Total_Power_(KW)"] = (
                _row["CGC_Power_KW"] +
                _row["PRC_Total_estimated_power_MW"] * 1000 +
                _row["ERC_power"]
            )
            _row["Total_required_steam_flow_(TPH)"] = (
                _row["CGC_Turbine_HP_Steam_flow"] +
                _row["PRC_turbine_Calculated_Steam_flow_TPH"] +
                _row["ERC_turbine_steam_flow"]
            )
        except (KeyError, TypeError) as e:
            print(f"[yanpet_olf1] could not compute plant totals for the {_label} "
                  f"row (missing/invalid input: {e}); its totals will stay blank.")
    return selected_row, selected_row_updated


# ---------------------------------------------------------------------
# Hook registry consumed by the generic engine in whatif_runner.py.
# Key format: "after:<Predicted parameter name>" -> runs immediately
# after that parameter's Kalman prediction + user-override step.
# ---------------------------------------------------------------------
HOOKS = {
    "after:CGC_STAGE_1_SUCTION_PRESSURE": furnace_cot_hook,
    "after:PRC_2nd_stage_drum_Overhead_Flow": prc_turbine_hook,
    "after:ERC_1ST_STAGE_Suction_PRESSURE": totals_hook,
}


# ---------------------------------------------------------------------
# BULK_SIMULATION: consumed by BOTH sides of the platform now:
#   * the TRAINING script (Model_development_and_static_whatif_testing
#     .py) calls each function across the WHOLE historian dataframe so
#     the parameter lands in Raw_data_plus_simulated_data.xlsx just like
#     every Kalman-trained parameter does; and
#   * the RUNTIME what-if engine (whatif_runner.py) calls the same
#     function on the SINGLE selected/overridden row, at that
#     parameter's own slot in the execution order -- so any parameter
#     whose Model details 'model' column says Simulation/first-principle
#     is recomputed live and reacts to user input changes in the
#     What-if Dashboard.
# {"Predicted parameter name": callable(df) -> pd.Series}. The functions
# are naturally vectorized, so one implementation serves both the
# many-row (training) and one-row (runtime) cases. If a plant ever needs
# runtime physics that differ from the bulk/historical version, it can
# define a SIMULATION dict with the same signature -- the engine gives
# it precedence over the BULK_SIMULATION entry of the same name.
#
# PRC_Total_estimated_power_MW reuses the exact same _PRC_section_power
# physics already used at runtime (via prc_turbine_hook above) -- it's
# naturally vectorized across however many rows are passed in.
#
# Overall_COT is the same physical quantity as 'Coil_Avg_COT' -- a real
# measured historian tag (see 'selected_col' in the training script's
# furnace merge), which furnace_cot_hook already uses as the actual/
# baseline anchor for its bias-corrected estimate at runtime. In bulk
# historical mode there's no scenario/override to bias-correct against,
# so 'Overall_COT' is simply the historian's own 'Coil_Avg_COT' values,
# copied under the name the config/KPI cards expect.
# ---------------------------------------------------------------------
def _prc_total_power_bulk(df):
    return _PRC_section_power(df)["PRC_Total_estimated_power_MW"]


def _overall_cot_bulk(df):
    return df["Coil_Avg_COT"]


BULK_SIMULATION = {
    "PRC_Total_estimated_power_MW": _prc_total_power_bulk,
    "Overall_COT": _overall_cot_bulk,
}
