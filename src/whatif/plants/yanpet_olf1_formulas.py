"""
src/whatif/plants/yanpet_olf1_formulas.py
============================================
YANPET_OLF1's plant-specific physics: the CoolProp/thermodynamics chain that
src/whatif/engine.py used to run as hardcoded, fixed-order steps. Relocated
here (not reimplemented — same formulas, same coefficients) so the generic
engine's dependency-graph/topological pipeline can treat these two predicted
parameters (Coil_Avg_COT, PRC_Total_estimated_power_MW) as plugin-owned
rather than Kalman-trained, per the "Model details" sheet's "First
principle" model type.

Given the real on-disk Config_file.xlsx, this plugin only needs to own these
2 parameters. Everything else the old hardcoded engine did — the turbine RPM
"bump to max" rules and the CGC_5TH_STG_DISCH_PRES abort — is fully
expressed by the Constraints sheet's Linked Parameter/Action columns and
handled generically by src/whatif/engine.py's apply_linked_constraints_for_inputs
/check_abort_constraints. Do NOT re-add hardcoded versions of those rules
here "for safety" — they would silently double-apply (harmlessly idempotent
today, but a trap for future edits) or drift out of sync with the
Constraints sheet, which is the single source of truth for them.

Plugin contract expected by src/whatif/engine.py:
  OWNED_PARAMETERS  -- predicted parameters this plugin computes itself;
                       the engine skips Kalman/simulation for these and
                       relies entirely on HOOKS to populate them.
  SKIP_PARAMETERS   -- predicted parameters to skip computing altogether.
  HOOKS             -- {"after:<trigger_param>": fn(actual_row, updated_row)
                       -> (actual_row, updated_row)}, fired once the trigger
                       parameter has been computed for the current run. Both
                       rows are single-row DataFrames; a hook may read/write
                       either or both (most of these only ever wrote the
                       scenario/"updated" row -- ported as-is, not expanded,
                       to keep this rewrite output-identical to the pipeline
                       it replaces).
  BULK_SIMULATION   -- {param: fn(df) -> Series} for training-time historian
                       preprocessing. Empty here today (see module-level note
                       below).
  SIMULATION        -- {param: fn(row) -> value} for runtime single-row
                       simulation. Empty here — nothing needs a plain
                       per-row simulation independent of the hook chain.
  KPI_PARAMETERS    -- extra tags to show as KPI tiles beyond what's already
                       implied by Model details/Constraints.
  KPI_REPLACEMENTS  -- KPI tile substitution map (tag -> tag), unused today.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from CoolProp.CoolProp import PropsSI
from scipy.optimize import minimize_scalar

OWNED_PARAMETERS = {"Coil_Avg_COT", "PRC_Total_estimated_power_MW"}
SKIP_PARAMETERS: set = set()

KPI_PARAMETERS = ["DMCTF_feed", "Total_Power_(KW)", "Total_required_steam_flow_(TPH)"]
KPI_REPLACEMENTS: dict = {}


# ---------------------------------------------------------------------------
# COT (Coil Outlet Temperature) calculation chain
# ---------------------------------------------------------------------------

def _cot_calculation(df_furnace: pd.DataFrame) -> pd.DataFrame:
    df_furnace["Plant_average_feed_rate_Coil"] = df_furnace["DMCTF_feed"] / (
        df_furnace["Number_Of_Furnaces_Online"] * 4
    )

    df_furnace["Coil_CIP_Calculated"] = (
        -131.3081
        + (0.0755 * df_furnace["Plant_average_feed_rate_Coil"])
        + (0.1463 * df_furnace["Ethane_Feed_Preheater_Ethane_Feed_Outlet_Pressure"])
        + (0.6819 * df_furnace["Furnace_Ethane_Feed_Preheater_Ethane_Feed_Outlet_Temperature"])
        + (0.4853 * df_furnace["Coil_Weighted_Avg_Feed_CV_opening"])
        + (0.8766 * df_furnace["Coil_Weighted_Avg_Steam_CV_opening"])
    )

    df_furnace["Coil_Steam_Flow"] = df_furnace["Coil_Avg_SHC_Ratio"] * df_furnace["Plant_average_feed_rate_Coil"]

    df_furnace["Coil_Mixed_Feed_flow"] = df_furnace["Coil_Steam_Flow"] + df_furnace["Plant_average_feed_rate_Coil"]

    df_furnace["Coil_Mixed_Feed_Cp"] = (
        (df_furnace["Coil_Steam_Flow"] * 2.067) + (df_furnace["Plant_average_feed_rate_Coil"] * 1.909)
    ) / (df_furnace["Coil_Steam_Flow"] + df_furnace["Plant_average_feed_rate_Coil"])

    df_furnace["Coil_Mixed_Feed_Mol_wt"] = df_furnace["Coil_Mixed_Feed_flow"] / (
        (df_furnace["Plant_average_feed_rate_Coil"] / df_furnace["Furnace_Feed_Average_Molecular_Wt"])
        + (df_furnace["Coil_Steam_Flow"] / 18.0)
    )

    df_furnace["Coil_Volumetric_Flow"] = df_furnace["Coil_Mixed_Feed_flow"] / (
        ((df_furnace["Coil_CIP_Calculated"] + 101.325) * 0.00982963 * df_furnace["Coil_Mixed_Feed_Mol_wt"])
        / (0.08206 * (df_furnace["Coil_Weighted_Avg_Coil_Mixed_Feed_Inlet_Temperature"] + 273.15))
    )

    df_furnace["Coil_CIP_Corrected_atma"] = np.where(
        (df_furnace["Coil_CIP_Calculated"] / 101.325 + 1) < 5,
        (df_furnace["Coil_CIP_Calculated"] / 101.325 + 1)
        - (df_furnace["Coil_Volumetric_Flow"] * 144 / 1309.83) * 0.00986923,
        (df_furnace["Coil_CIP_Calculated"] / 101.325 + 1)
        - (df_furnace["Coil_Volumetric_Flow"] * 131 / 1209.52) * 0.00986923,
    )
    return df_furnace


def _cot_regression(row_df: pd.DataFrame, corrected_cop_col: str, cot_out_col: str) -> pd.DataFrame:
    """The COT correlation itself (same regression for both actual and
    scenario rows); writes intermediate Furnace_Effluent_* columns plus
    `cot_out_col`."""
    row_df["Furnace_Effluent_C2H6"] = (
        (row_df["DMCTF_feed"] / 1000) * (row_df["Furnace_Normalised_Feed_C2H6_Wt"] / 100)
        * (1 - row_df["Furnace_conversion"])
    )
    row_df["Furnace_Effluent_C2H6_wt%"] = (
        row_df["Furnace_Effluent_C2H6"] / (row_df["DMCTF_feed"] / 1000)
    ) * 100
    row_df[cot_out_col] = (
        (
            0.937913371 * (row_df["Coil_CIP_Corrected_atma"] - 0.3)
            - 2.413045433 * (row_df[corrected_cop_col] / 101.325 + 1 - 0.2)
            + 2.774285758 * row_df["Coil_Avg_SHC_Ratio"]
            + 0.002253435 * row_df["Plant_average_feed_rate_Coil"]
            - 0.463411867 * row_df["Furnace_Normalised_Feed_C3H8_Wt"]
            + 0.674941411 * row_df["Furnace_Normalised_Feed_C2H6_Wt"]
            + 337.8851416 - row_df["Furnace_Effluent_C2H6_wt%"]
        ) / 0.451606991
    )
    return row_df


def furnace_cot_hook(actual_row: pd.DataFrame, updated_row: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fires after CGC_STAGE_1_SUCTION_PRESSURE is computed for the scenario
    row (the delta-correction below needs both the baseline and scenario
    values of that tag). Writes Coil_Avg_COT onto `updated_row`; `actual_row`
    keeps whatever Coil_Avg_COT value the historian already carries (from the
    training script's bulk simulation) as the base the delta is added to,
    exactly as the pipeline this replaces did — it never recomputed a
    first-principle "actual" COT independently of that baseline column."""
    actual_row = _cot_calculation(actual_row)
    actual_row["Corrected_COP_Furnace"] = actual_row["Coil_Weighted_Avg_COP"] + 0  # no correction on the actual side
    actual_row = _cot_regression(actual_row, "Corrected_COP_Furnace", "Coil_Avg_COT_actual")

    updated_row = _cot_calculation(updated_row)
    delta_cgc_suction_pressure = (
        updated_row["CGC_STAGE_1_SUCTION_PRESSURE"] - actual_row["CGC_STAGE_1_SUCTION_PRESSURE"]
    )
    updated_row["Corrected_COP_Furnace"] = updated_row["Coil_Weighted_Avg_COP"] + delta_cgc_suction_pressure

    if (updated_row["DMCTF_feed"].iloc[0] / 1000) - updated_row["Fresh_ethane_feed"].iloc[0] > 70:
        updated_row["Fresh_ethane_feed"] = (updated_row["DMCTF_feed"] / 1000) - 70

    updated_row["Furnace_conversion"] = (
        (updated_row["DMCTF_feed"] / 1000) * (updated_row["Furnace_Normalised_Feed_C2H6_Wt"] / 100)
        - (updated_row["DMCTF_feed"] / 1000 - updated_row["Fresh_ethane_feed"])
    ) / ((updated_row["DMCTF_feed"] / 1000) * updated_row["Furnace_Normalised_Feed_C2H6_Wt"] / 100)

    updated_row = _cot_regression(updated_row, "Corrected_COP_Furnace", "Coil_Avg_COT")

    delta_cot = updated_row["Coil_Avg_COT"] - actual_row["Coil_Avg_COT_actual"]
    updated_row["Coil_Avg_COT"] = actual_row["Coil_Avg_COT"] + delta_cot

    return actual_row, updated_row


# ---------------------------------------------------------------------------
# PRC (Propylene Refrigeration Compressor) section: power + turbine matching
# ---------------------------------------------------------------------------

def _prc_section_power(df: pd.DataFrame) -> pd.DataFrame:
    eta = 0.70  # assumed compressor efficiency

    density_1st, vol_flow_1st = [], []
    for i in range(len(df)):
        t_k = df["PRC_1ST_STAGE_Suction_TEMP"].iloc[i] + 273.15
        p_pa = df["PRC_1ST_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5
        rho = PropsSI("D", "T", t_k, "P", p_pa, "Propylene")
        vol_flow_1st.append(df["PRC_1ST_STAGE_Suction_FLOW"].iloc[i] * 1000 / rho)
        density_1st.append(rho)
    df["PRC_Density_1st_stage"] = density_1st
    df["PRC VOL FLOW 1ST STAGE"] = vol_flow_1st

    density_2nd, vol_flow_2nd = [], []
    for i in range(len(df)):
        t_k = df["PRC_2nd_stage_drum_Overhead_Temp"].iloc[i] + 273.15
        p_pa = df["PRC_2ND_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5
        rho = PropsSI("D", "T", t_k, "P", p_pa, "Propylene")
        vol_flow_2nd.append(
            (df["PRC_1ST_STAGE_Suction_FLOW"].iloc[i] + df["PRC_2nd_stage_drum_Overhead_Flow"].iloc[i]) * 1000 / rho
        )
        density_2nd.append(rho)
    df["PRC_Density_2nd_stage"] = density_2nd
    df["PRC VOL FLOW 2ND STAGE"] = vol_flow_2nd

    density_3rd, vol_flow_3rd = [], []
    for i in range(len(df)):
        t_k = df["PRC_3RD_STAGE_Suction_TEMP"].iloc[i] + 273.15
        p_pa = df["PRC_3RD_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5
        rho = PropsSI("D", "T", t_k, "P", p_pa, "Propylene")
        vol_flow_3rd.append(df["PRC_3RD_STAGE_Suction_FLOW"].iloc[i] * 1000 / rho)
        density_3rd.append(rho)
    df["PRC_Density_3rd_stage"] = density_3rd
    df["PRC VOL FLOW 3RD STAGE"] = vol_flow_3rd

    power_1st = []
    for i in range(len(df)):
        h1 = PropsSI("H", "T", df["PRC_1ST_STAGE_Suction_TEMP"].iloc[i] + 273.15, "P",
                     df["PRC_1ST_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5, "Propylene")
        s1 = PropsSI("S", "T", df["PRC_1ST_STAGE_Suction_TEMP"].iloc[i] + 273.15, "P",
                     df["PRC_1ST_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5, "Propylene")
        h2s = PropsSI("H", "P", df["PRC_1ST_STAGE_Discharge_PRESSURE"].iloc[i] * 1000 + 1e5, "S", s1, "Propylene")
        h2 = h1 + (h2s - h1) / eta
        power_1st.append(((df["PRC_1ST_STAGE_Suction_FLOW"].iloc[i] * 1000) / 3600) * (h2 - h1) / 1e6)
    df["PRC_1st_stage_comp_estimated_power_MW"] = power_1st

    power_2nd = []
    for i in range(len(df)):
        h1 = PropsSI("H", "T", df["PRC_2nd_stage_drum_Overhead_Temp"].iloc[i] + 273.15, "P",
                     df["PRC_2ND_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5, "Propylene")
        s1 = PropsSI("S", "T", df["PRC_2nd_stage_drum_Overhead_Temp"].iloc[i] + 273.15, "P",
                     df["PRC_2ND_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5, "Propylene")
        h2s = PropsSI("H", "P", df["PRC_3RD_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5, "S", s1, "Propylene")
        h2 = h1 + (h2s - h1) / eta
        power_2nd.append((
            ((df["PRC_2nd_stage_drum_Overhead_Flow"].iloc[i] + df["PRC_1ST_STAGE_Suction_FLOW"].iloc[i]) * 1000)
            / 3600
        ) * (h2 - h1) / 1e6)
    df["PRC_2nd_stage_comp_estimated_power_MW"] = power_2nd

    power_3rd = []
    for i in range(len(df)):
        h1 = PropsSI("H", "T", df["PRC_3RD_STAGE_Suction_TEMP"].iloc[i] + 273.15, "P",
                     df["PRC_3RD_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5, "Propylene")
        s1 = PropsSI("S", "T", df["PRC_3RD_STAGE_Suction_TEMP"].iloc[i] + 273.15, "P",
                     df["PRC_3RD_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5, "Propylene")
        h2s = PropsSI("H", "P", df["PRC_3RD_STAGE_Discharge_PRESSURE"].iloc[i] * 1000 + 1e5, "S", s1, "Propylene")
        h2 = h1 + (h2s - h1) / eta
        power_3rd.append(((df["PRC_3RD_STAGE_Suction_FLOW"].iloc[i] * 1000) / 3600) * (h2 - h1) / 1e6)
    df["PRC_3rd_stage_comp_estimated_power_MW"] = power_3rd

    df["PRC_Total_estimated_power_MW"] = (
        df["PRC_1st_stage_comp_estimated_power_MW"]
        + df["PRC_2nd_stage_comp_estimated_power_MW"]
        + df["PRC_3rd_stage_comp_estimated_power_MW"]
    )
    return df


def _isentropic_enthalpy(p_target: float, s_in: float) -> float:
    s_f = PropsSI("S", "P", p_target, "Q", 0, "Water") / 1000
    s_g = PropsSI("S", "P", p_target, "Q", 1, "Water") / 1000
    if s_f < s_in < s_g:
        x = (s_in - s_f) / (s_g - s_f)
        h_f = PropsSI("H", "P", p_target, "Q", 0, "Water")
        h_g = PropsSI("H", "P", p_target, "Q", 1, "Water")
        h_iso = h_f + x * (h_g - h_f)
    else:
        h_iso = PropsSI("H", "P", p_target, "S", s_in, "Water")
    return h_iso / 1000


def _match_actual_power(row: pd.Series) -> tuple:
    try:
        p_steam = row["PRC_turbine_Steam_pressure"] * 1000
        t_steam = row["PRC_turbine_Steam_Temp"] + 273.15
        h_steam = PropsSI("H", "P", p_steam, "T", t_steam, "Water") / 1000

        pe = row["PRC_turbine_Extraction_Pressure"] * 1000
        t_sat_extraction = PropsSI("T", "P", pe, "Q", 1, "Water")
        he = PropsSI("H", "P", pe, "T", t_sat_extraction + 0.01, "Water") / 1000

        pc = row["PRC_turbine_Condensate_Pressure"] * 1000
        t_sat_condensate = PropsSI("T", "P", pc, "Q", 0, "Water")
        hc_liquid = PropsSI("H", "P", pc, "T", t_sat_condensate - 0.01, "Water") / 1000
        dryness_fraction = 0.92
        hc_vapor = PropsSI("H", "P", pc, "T", t_sat_condensate + 0.01, "Water") / 1000
        hc = hc_liquid + hc_vapor * dryness_fraction

        condensate_flow_tph = row["PRC_turbine_condensate_flow"]
        condensate_flow_kg_hr = condensate_flow_tph * 1000
        actual_power = row["PRC_Total_estimated_power_MW"]

        def objective(extraction_flow_tph: float) -> float:
            extraction_flow_kg_hr = extraction_flow_tph * 1000
            power = (
                (extraction_flow_kg_hr * (h_steam - he)) + (condensate_flow_kg_hr * (h_steam - hc))
            ) / 3600 / 1000
            return (power - actual_power) ** 2

        result = minimize_scalar(objective, bounds=(10, 350), method="bounded")

        if result.success:
            ef_opt = result.x
            ef_kg_hr = ef_opt * 1000
            sf_opt = ef_opt + condensate_flow_tph
            sf_kg_hr = sf_opt * 1000
            power_matched_ee = ((ef_kg_hr * (h_steam - he)) + (condensate_flow_kg_hr * (h_steam - hc))) / 3600 / 1000
            h2_actual = (ef_kg_hr * he + condensate_flow_kg_hr * hc) / sf_kg_hr
            power_matched_sf = (h_steam - h2_actual) * (sf_kg_hr / 3600 / 1000)
            return ef_opt, sf_opt, power_matched_ee, power_matched_sf, h2_actual

        return (
            row["PRC_turbine_Extraction_flow"], row["PRC_turbine_steam_flow"],
            row["PRC_turbine_current_Turbine_power_MW_based_on_EE"],
            row["PRC_turbine_current_Turbine_power_MW_based_on_steam_flow"], None,
        )
    except Exception:
        return (
            row["PRC_turbine_Extraction_flow"], row["PRC_turbine_steam_flow"],
            row["PRC_turbine_current_Turbine_power_MW_based_on_EE"],
            row["PRC_turbine_current_Turbine_power_MW_based_on_steam_flow"], None,
        )


def _prc_turbine_extraction_steam_flow_prediction(df: pd.DataFrame) -> pd.DataFrame:
    steam_enth, steam_entr, out_enth, out_isen_enth = [], [], [], []
    power_ext, power_exh, power_ee, power_sf, spec_steam = [], [], [], [], []

    for i in range(len(df)):
        steam_flow_tph = df["PRC_turbine_steam_flow"].iloc[i]
        condensate_flow_tph = df["PRC_turbine_condensate_flow"].iloc[i]
        extraction_flow_tph = df["PRC_turbine_Extraction_flow"].iloc[i]

        steam_flow_kg_hr = steam_flow_tph * 1000
        extraction_flow_kg_hr = extraction_flow_tph * 1000
        condensate_flow_kg_hr = condensate_flow_tph * 1000

        p_steam = df["PRC_turbine_Steam_pressure"].iloc[i] * 1000
        t_steam = df["PRC_turbine_Steam_Temp"].iloc[i] + 273.15

        pe = df["PRC_turbine_Extraction_Pressure"].iloc[i] * 1000
        t_sat_extraction = PropsSI("T", "P", pe, "Q", 1, "Water")

        pc = df["PRC_turbine_Condensate_Pressure"].iloc[i] * 1000
        t_sat_condensate = PropsSI("T", "P", pc, "Q", 0, "Water")

        h_steam = PropsSI("H", "P", p_steam, "T", t_steam, "Water") / 1000
        s_steam = PropsSI("S", "P", p_steam, "T", t_steam, "Water") / 1000

        he = PropsSI("H", "P", pe, "T", t_sat_extraction + 0.01, "Water") / 1000
        hc_liquid = PropsSI("H", "P", pc, "T", t_sat_condensate - 0.01, "Water") / 1000
        dryness_fraction = 0.92
        hc_vapor = PropsSI("H", "P", pc, "T", t_sat_condensate + 0.01, "Water") / 1000
        hc = hc_liquid + hc_vapor * dryness_fraction

        power_gen_extraction = extraction_flow_kg_hr * (h_steam - he) / 3600 / 1000
        power_gen_exhaust = condensate_flow_kg_hr * (h_steam - hc) / 3600 / 1000
        turbine_power_mw_ee = power_gen_extraction + power_gen_exhaust
        specific_steam_consumption = steam_flow_tph / turbine_power_mw_ee

        he_s = _isentropic_enthalpy(pe, s_steam)
        hc_s = _isentropic_enthalpy(pc, s_steam)

        h2_actual = (extraction_flow_kg_hr * he + condensate_flow_kg_hr * hc) / steam_flow_kg_hr
        h2s_ideal = (extraction_flow_kg_hr * he_s + condensate_flow_kg_hr * hc_s) / steam_flow_kg_hr

        turbine_power_mw_sf = (h_steam - h2_actual) * (steam_flow_kg_hr / (3600 * 1000))

        steam_enth.append(h_steam)
        steam_entr.append(s_steam)
        out_enth.append(h2_actual)
        out_isen_enth.append(h2s_ideal)
        power_ext.append(power_gen_extraction)
        power_exh.append(power_gen_exhaust)
        power_ee.append(turbine_power_mw_ee)
        power_sf.append(turbine_power_mw_sf)
        spec_steam.append(specific_steam_consumption)

    df["PRC_turbine_current_steam_enthalpy_KJ_Kg"] = steam_enth
    df["PRC_turbine_current_steam_entropy_KJ_KgK"] = steam_entr
    df["PRC_turbine_current_outlet_ethalpy_KJ_Kg"] = out_enth
    df["PRC_turbine_current_outlet_isentropic_ethalpy_KJ_Kg"] = out_isen_enth
    df["PRC_turbine_current_power_gen_extraction_MW"] = power_ext
    df["PRC_turbine_current_power_gen_exhaust_MW"] = power_exh
    df["PRC_turbine_current_Turbine_power_MW_based_on_EE"] = power_ee
    df["PRC_turbine_current_Turbine_power_MW_based_on_steam_flow"] = power_sf
    df["PRC_turbine_current_Specific_steam_consumption_MT_MW"] = spec_steam

    optimized_extraction, calculated_steam_flow = [], []
    matched_power_ee, matched_power_sf, matched_h2 = [], [], []
    for _, row in df.iterrows():
        ef, sf, p_ee, p_sf, h2 = _match_actual_power(row)
        optimized_extraction.append(ef)
        calculated_steam_flow.append(sf)
        matched_power_ee.append(p_ee)
        matched_power_sf.append(p_sf)
        matched_h2.append(h2)

    df["PRC_turbine_Optimized_Extraction_flow_TPH"] = optimized_extraction
    df["PRC_turbine_Calculated_Steam_flow_TPH"] = calculated_steam_flow
    df["PRC_turbine_Matched_Turbine_power_MW_EE"] = matched_power_ee
    df["PRC_turbine_Matched_Turbine_power_MW_SF"] = matched_power_sf
    df["PRC_turbine_Matched_h2_actual_KJ_Kg"] = matched_h2
    df["Power_Error"] = df["PRC_turbine_Matched_Turbine_power_MW_EE"] - df["PRC_Total_estimated_power_MW"]
    df["Power_EE_vs_SF_Diff"] = df["PRC_turbine_Matched_Turbine_power_MW_EE"] - df["PRC_turbine_Matched_Turbine_power_MW_SF"]
    df["Devaiation in steam flow (Simulated-actual)"] = df["PRC_turbine_Calculated_Steam_flow_TPH"] - df["PRC_turbine_steam_flow"]
    df["Devaiation in extraction (Simulated-actual)"] = df["PRC_turbine_Optimized_Extraction_flow_TPH"] - df["PRC_turbine_Extraction_flow"]
    df["Specific_steam_consumption_MT_MW_updated"] = df["PRC_turbine_Calculated_Steam_flow_TPH"] / df["PRC_Total_estimated_power_MW"]
    return df


def prc_power_hook(actual_row: pd.DataFrame, updated_row: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fires after PRC_2nd_stage_drum_Overhead_Flow is computed. Only ever
    wrote the scenario/`updated_row` side in the pipeline this replaces —
    the actual side's PRC_Total_estimated_power_MW comes from whatever the
    historian already carries (ported as-is)."""
    updated_row = _prc_section_power(updated_row)
    updated_row = _prc_turbine_extraction_steam_flow_prediction(updated_row)
    return actual_row, updated_row


# ---------------------------------------------------------------------------
# Plant-wide totals
# ---------------------------------------------------------------------------

def totals_hook(actual_row: pd.DataFrame, updated_row: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fires after ERC_1ST_STAGE_Suction_PRESSURE is computed. Only ever
    wrote the scenario/`updated_row` side (ported as-is)."""
    updated_row["Total_Power_(KW)"] = (
        updated_row["CGC_Power_KW"]
        + updated_row["PRC_Total_estimated_power_MW"] * 1000
        + updated_row["ERC_power"]
    )
    updated_row["Total_required_steam_flow_(TPH)"] = (
        updated_row["CGC_Turbine_HP_Steam_flow"]
        + updated_row["PRC_turbine_Calculated_Steam_flow_TPH"]
        + updated_row["ERC_turbine_steam_flow"]
    )
    return actual_row, updated_row


HOOKS = {
    "after:CGC_STAGE_1_SUCTION_PRESSURE": furnace_cot_hook,
    "after:PRC_2nd_stage_drum_Overhead_Flow": prc_power_hook,
    "after:ERC_1ST_STAGE_Suction_PRESSURE": totals_hook,
}

def _bulk_prc_total_power(df: pd.DataFrame) -> pd.Series:
    """BULK_SIMULATION entry for PRC_Total_estimated_power_MW: confirmed by
    retraining (see the migration plan's Phase 2 verification note) that
    Raw_data_plus_simulated_data.xlsx has no baseline source for this column
    otherwise — without it, the "actual" side of every what-if scenario (and
    this KPI tile) would be permanently blank. Coil_Avg_COT needs no such
    entry: the training script's furnace-preprocessing block already bulk-
    populates it directly (a first-principle weighted average, not this
    plugin's regression-based runtime correction)."""
    df = _prc_section_power(df.copy())
    return df["PRC_Total_estimated_power_MW"]


# Only PRC_Total_estimated_power_MW needs a BULK_SIMULATION entry (see
# above). The turbine-matching columns _prc_turbine_extraction_steam_flow_prediction
# also produces (feeding Total_required_steam_flow_(TPH)) aren't reachable
# through this mechanism, since BULK_SIMULATION returns exactly one column
# per parameter and Total_required_steam_flow_(TPH) isn't itself a Model
# details predicted parameter — it stays populated on the scenario/"updated"
# side only (via totals_hook), matching this pipeline's existing behavior.
BULK_SIMULATION = {"PRC_Total_estimated_power_MW": _bulk_prc_total_power}
SIMULATION: dict = {}
