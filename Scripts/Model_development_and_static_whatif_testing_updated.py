# -*- coding: utf-8 -*-
"""
Created on Thu Apr  9 12:55:23 2026

@author: 30793167 : Sumit Kumar
"""
# Import libraries

import pandas as pd
import numpy as np
import random
import seaborn as sns
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from sklearn.multioutput import MultiOutputRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from xgboost import XGBRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge, LinearRegression
from sklearn.svm import SVR
import os
from plotly.offline import plot
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LinearRegression
import xgboost as xgb
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score, mean_absolute_percentage_error
import pickle
import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor
from scipy.signal import cont2discrete
from nfoursid.nfoursid import NFourSID
from nfoursid.state_space import StateSpace
from nfoursid.kalman import Kalman
import joblib
from CoolProp.CoolProp import PropsSI
from scipy.optimize import minimize_scalar
import ipywidgets as widgets
from IPython.display import display
import plotly.graph_objects as go
import plotly.io as pio
 

#%% data loading
# For reproducibility.

# ---------------------------------------------------------------------
# MULTI-PLANT SUPPORT
# ---------------------------------------------------------------------
# Every path below used to be hardcoded to a single plant's deployment
# ("..\Data", "..\Results\Model", ...). To reuse this exact script for
# a different plant, nothing in the code below needs to change -- just
# point PLANT_NAME (env var, set automatically by the Streamlit
# dashboard's plant selector, or set manually when running this script
# standalone) at a folder that holds that plant's own Config_file.xlsx /
# DMC_Screen_tags_data.xlsx:
#
#   Data/<PLANT_NAME>/Config_file.xlsx
#   Data/<PLANT_NAME>/DMC_Screen_tags_data.xlsx
#   Results/<PLANT_NAME>/Model/*.pkl              (written by this script)
#
# If no such subfolder exists yet, the script falls back to the flat
# Data/ , Results/ layout so single-plant deployments created before
# multi-plant support existed keep working unchanged.
# ---------------------------------------------------------------------
PLANT_NAME = (os.environ.get("PLANT_NAME") or "YANPET_OLF1").strip() or "YANPET_OLF1"


def _resolve_plant_dir(base_dir: str, plant_name: str) -> str:
    """Prefer <base_dir>/<plant_name>; fall back to a flat <base_dir>
    layout for deployments created before multi-plant support existed."""
    nested = os.path.join(base_dir, plant_name)
    return nested if os.path.isdir(nested) else base_dir


file_path = _resolve_plant_dir("..\\Data", PLANT_NAME)
RESULTS_DIR = _resolve_plant_dir("..\\Results", PLANT_NAME)
RESULTS_MODEL_DIR = os.path.join(RESULTS_DIR, "Model")
os.makedirs(RESULTS_MODEL_DIR, exist_ok=True)
# CONFIG_DIR lets the caller point us at a throwaway scratch folder holding
# a just-uploaded Config_file.xlsx, instead of this plant's persistent
# Data/<plant>/ folder -- the config is never required to be saved there.
# Falls back to file_path so this script still runs standalone (outside the
# dashboard) unchanged.
CONFIG_DIR = os.environ.get("CONFIG_DIR") or file_path
print(f"[plant_engine] PLANT_NAME='{PLANT_NAME}'  data='{file_path}'  config='{CONFIG_DIR}'  results='{RESULTS_DIR}'")

# ---------------------------------------------------------------------
# MULTI-PLANT SUPPORT: DMC_Screen_tags_data.xlsx no longer has to
# contain BOTH the "PI data" and "Furnace data" sheets. A plant with
# no separate furnace/cracking section (or vice-versa) can supply just
# one of the two -- whichever predicted parameters need columns from
# the sheet that wasn't provided simply won't have a trained model for
# them (the what-if engine already falls back to the historical/
# baseline value for any parameter with no trained model -- see
# whatif_runner.predict_and_update_with_kalman's FileNotFoundError
# handling), everything else still trains normally.
# ---------------------------------------------------------------------
_dmc_workbook_path = os.path.join(file_path, "DMC_Screen_tags_data.xlsx")
_dmc_sheet_names = pd.ExcelFile(_dmc_workbook_path).sheet_names
HAS_PI_DATA = "PI data" in _dmc_sheet_names
HAS_FURNACE_DATA = "Furnace data" in _dmc_sheet_names
print(f"[plant_engine] DMC_Screen_tags_data.xlsx sheets found: {_dmc_sheet_names} "
      f"(PI data={HAS_PI_DATA}, Furnace data={HAS_FURNACE_DATA})")
if not HAS_PI_DATA and not HAS_FURNACE_DATA:
    raise ValueError(
        "DMC_Screen_tags_data.xlsx must contain at least one of the sheets "
        "'PI data' or 'Furnace data'. Found: " + str(_dmc_sheet_names)
    )

df = None
if HAS_PI_DATA:
    df = pd.read_excel(
        _dmc_workbook_path,
        sheet_name="PI data"
    )

    df.columns = df.iloc[0]
    df = df[1:].reset_index(drop=True)
    df.set_index("Timestamp",inplace =True)

    df["CGC_Power_KW"] = (df["CGC_Stage_1_power"] + df["CGC_Stage_2_power"] + df["CGC_Stage_3_power"]
                                    + df["CGC_Stage_4_power"] + df["CGC_Stage_5_power"])

    df.dropna(inplace =True)

    df = df.apply(pd.to_numeric, errors='coerce')

df_stats = df.describe(include='all') if df is not None else None

#%% Furnace average COT calculation
# 1. Load and Clean Data
if HAS_FURNACE_DATA:
    df_furnace = pd.read_excel(
        os.path.join(file_path, "DMC_Screen_tags_data.xlsx"),
        sheet_name="Furnace data"
    )

    # Set first row as header and clean
    df_furnace.columns = df_furnace.iloc[0]
    df_furnace = df_furnace[1:].reset_index(drop=True)
    df_furnace.columns = df_furnace.columns.str.strip()

    # Ensure Timestamp is index and data is numeric
    if "Timestamp" in df_furnace.columns:
        df_furnace.set_index("Timestamp", inplace=True)

    df_furnace = df_furnace.apply(pd.to_numeric, errors='coerce')

    # 2. Define Global Accumulators
    # We will sum (Value * Feed) and Sum(Feed) across ALL furnaces and coils
    metrics_config = [
        ('Global_WA_COT', 'Furnace_Coil_Outlet_Temperature_Coil', 'Furnace_Feed_Rate_Coil'),
        ('Global_WA_CIP', 'Coil', 'Furnace_Feed_Rate_Coil', '_CIP_Corrected_atma'), # Special pattern
        ('Global_WA_SHC', 'Furnace_Coil', 'Furnace_Feed_Rate_Coil', '_SHC_Ratio'),  # Special pattern
        ('Global_WA_Feed_CV', 'Furnace_Feed_Coil', 'Furnace_Feed_Rate_Coil', '_CV_Opening'),
        ('Global_WA_Steam_CV', 'Furnace_Dilution_Steam_Coil', 'Furnace_Feed_Rate_Coil', '_CV_Opening'),
        ('Global_WA_Mixed_Feed_Temp', 'Coil', 'Furnace_Feed_Rate_Coil', '_Mixed_Feed_Inlet_Temperature')
    ]

    # Initialize columns to 0 for accumulation
    total_valid_feed_sum = pd.Series(0, index=df_furnace.index, dtype=float)
    weighted_sums = {name: pd.Series(0, index=df_furnace.index, dtype=float) for name, *_ in metrics_config}

    # 3. Iterate through every Furnace (1-12) and Coil (1-4)
    for furnace in range(1, 13):
        status_col = f'F{furnace}_online_status'
    
        # Base Status Mask
        if status_col in df_furnace.columns:
            status_mask = (df_furnace[status_col] == 1)
        else:
            status_mask = pd.Series(True, index=df_furnace.index)

        for coil in range(1, 5):
            feed_col = f'F{furnace}_Furnace_Feed_Rate_Coil{coil}'
            if feed_col not in df_furnace.columns:
                continue

            feed_series = df_furnace[feed_col] # Keep NaNs for now to check validity
        
            # Basic Mask: Online AND Feed exists and > 0
            # We fillna(0) ONLY for the feed check to treat missing feed as 0
            feed_valid = feed_series.fillna(0) > 0
            base_mask = status_mask & feed_valid

            # Add valid feed to total denominator immediately (if base conditions met)
            # Note: We will adjust this later per metric if the VALUE is missing
            current_feed = feed_series.fillna(0).where(base_mask, 0)
        
            for config in metrics_config:
                metric_name = config[0]
            
                # Construct Value Column
                if len(config) == 3:
                    val_col = f'F{furnace}_{config[1]}{coil}'
                else:
                    val_col = f'F{furnace}_{config[1]}{coil}{config[3]}'
            
                if val_col not in df_furnace.columns:
                    continue

                val_series = df_furnace[val_col] # Keep NaNs
            
                # CRITICAL FIX: Specific Mask for this Metric
                # Data is only valid if: Base Mask is True AND Value is NOT NaN
                valid_data_mask = base_mask & val_series.notna()
            
                # Extract feed and value ONLY where data is fully valid
                valid_feed = current_feed.where(valid_data_mask, 0)
                valid_value = val_series.where(valid_data_mask, 0) # NaNs become 0 here safely
            
                # Accumulate
                weighted_sums[metric_name] += (valid_value * valid_feed)
            
                # Add to metric-specific total feed denominator
                # We create a temporary total feed tracker per metric to be precise, 
                # OR we can just accumulate to a global dict of feed sums per metric.
                # To keep it simple and accurate, let's accumulate valid feed per metric inside the loop 
                # by using a separate dictionary for denominators.
                if f"{metric_name}_feed" not in weighted_sums:
                    weighted_sums[f"{metric_name}_feed"] = pd.Series(0, index=df_furnace.index, dtype=float)
            
                weighted_sums[f"{metric_name}_feed"] += valid_feed

    # --- 4. Final Calculation ---
    for metric_name in [c[0] for c in metrics_config]:
        result_col = f"{metric_name}_AllCoils"
        feed_col = f"{metric_name}_feed"
    
        denominator = weighted_sums[feed_col]
        numerator = weighted_sums[metric_name]
    
        df_furnace[result_col] = np.where(
            denominator > 0,
            numerator / denominator,
            np.nan
        )

    # Cleanup helper columns if needed (optional, as they were dict keys not DF cols)
    # The logic above used the dict to store intermediate feed sums per metric.

    print("Calculation complete with NaN handling.")
    print(df_furnace.filter(like="Global_WA").head())

    # Initialize accumulators for COP calculation
    global_weighted_sum_cop = pd.Series(0, index=df_furnace.index, dtype=float)
    global_valid_feed_cop = pd.Series(0, index=df_furnace.index, dtype=float)

    for furnace in range(1, 13):
        # Define Columns
        feed_1 = f'F{furnace}_Furnace_Feed_Rate_Coil1'
        feed_2 = f'F{furnace}_Furnace_Feed_Rate_Coil2'
        feed_3 = f'F{furnace}_Furnace_Feed_Rate_Coil3'
        feed_4 = f'F{furnace}_Furnace_Feed_Rate_Coil4'
    
        cop_tlea = f'F{furnace}_Corrected_COP_Furnace_TLEA'
        cop_tleb = f'F{furnace}_Corrected_COP_Furnace_TLEB'
    
        status_col = f'F{furnace}_online_status'
    
        required_cols = [feed_1, feed_2, feed_3, feed_4, cop_tlea, cop_tleb, status_col]
    
        if all(col in df_furnace.columns for col in required_cols):
            # Get Series (keep NaNs for COP, fill NaNs with 0 for Feed checks)
            f1 = df_furnace[feed_1].fillna(0)
            f2 = df_furnace[feed_2].fillna(0)
            f3 = df_furnace[feed_3].fillna(0)
            f4 = df_furnace[feed_4].fillna(0)
        
            cop_a = df_furnace[cop_tlea] # Keep NaNs
            cop_b = df_furnace[cop_tleb] # Keep NaNs
        
            status = df_furnace[status_col]
        
            # Base Mask: Furnace Online
            base_mask = (status == 1)
        
            # --- TLEA Calculation (Coils 1 & 2) ---
            feed_tlea = f1 + f2
            # Valid only if Online, Feed > 0, AND COP is not NaN
            mask_tlea = base_mask & (feed_tlea > 0) & cop_a.notna()
        
            # --- TLEB Calculation (Coils 3 & 4) ---
            feed_tleb = f3 + f4
            # Valid only if Online, Feed > 0, AND COP is not NaN
            mask_tleb = base_mask & (feed_tleb > 0) & cop_b.notna()
        
            # Accumulate Weighted Sum (NaNs in COP become 0 when multiplied, but mask prevents bad data addition)
            # We use .where(mask, 0) to ensure only valid rows contribute
            term_a = (cop_a * feed_tlea).where(mask_tlea, 0)
            term_b = (cop_b * feed_tleb).where(mask_tleb, 0)
        
            global_weighted_sum_cop += term_a + term_b
        
            # Accumulate VALID Feed Denominator
            # Only add feed_tlea if mask_tlea is True, same for TLEB
            global_valid_feed_cop += feed_tlea.where(mask_tlea, 0) + feed_tleb.where(mask_tleb, 0)

    # Final Global Calculation
    df_furnace['Global_Weighted_Avg_COP_AllCoils'] = np.where(
        global_valid_feed_cop > 0,
        global_weighted_sum_cop / global_valid_feed_cop,
        np.nan
    )

    col_rename = {'Global_WA_COT_AllCoils': 'Coil_Avg_COT',
                  'Global_WA_CIP_AllCoils': 'Coil_Avg_CIP',
                  'Global_WA_SHC_AllCoils': 'Coil_Avg_SHC_Ratio',
                  'Global_Weighted_Avg_COP_AllCoils': 'Coil_Weighted_Avg_COP',
                  'Global_WA_Feed_CV_AllCoils': 'Coil_Weighted_Avg_Feed_CV_opening',
                  'Global_WA_Steam_CV_AllCoils': 'Coil_Weighted_Avg_Steam_CV_opening',
                  'Global_WA_Mixed_Feed_Temp_AllCoils': 'Coil_Weighted_Avg_Coil_Mixed_Feed_Inlet_Temperature'
                  }

    df_furnace.rename(columns=col_rename, inplace=True, errors='ignore')

    #Average molecular weight calculation
    df_furnace["Furnace_Sum_of_Feed_Components"] = (df_furnace["Furnace_Ethane_Feed_Preheater_Ethane_Feed_CH4"] + 
                                              df_furnace["Furnace_Ethane_Feed_Preheater_Ethane_Feed_C2H6"] + 
                                              df_furnace["Furnace_Ethane_Feed_Preheater_Ethane_Feed_C3H8"])

    df_furnace['Furnace_Normalised_Feed_CH4'] = df_furnace['Furnace_Ethane_Feed_Preheater_Ethane_Feed_CH4']*100/df_furnace["Furnace_Sum_of_Feed_Components"]
    df_furnace["Furnace_Normalised_Feed_C2H6"] = df_furnace['Furnace_Ethane_Feed_Preheater_Ethane_Feed_C2H6']*100/df_furnace["Furnace_Sum_of_Feed_Components"]
    df_furnace["Furnace_Normalised_Feed_C3H8"] = df_furnace['Furnace_Ethane_Feed_Preheater_Ethane_Feed_C3H8']*100/df_furnace["Furnace_Sum_of_Feed_Components"]

    df_furnace['Furnace_Normalised_Feed_CH4_Wt'] = df_furnace['Furnace_Normalised_Feed_CH4']*16*100/(df_furnace['Furnace_Normalised_Feed_CH4']*16+df_furnace["Furnace_Normalised_Feed_C2H6"]*30+df_furnace["Furnace_Normalised_Feed_C3H8"]*44)
    df_furnace['Furnace_Normalised_Feed_C2H6_Wt'] = df_furnace['Furnace_Normalised_Feed_C2H6']*30*100/(df_furnace['Furnace_Normalised_Feed_CH4']*16+df_furnace["Furnace_Normalised_Feed_C2H6"]*30+df_furnace["Furnace_Normalised_Feed_C3H8"]*44)
    df_furnace['Furnace_Normalised_Feed_C3H8_Wt'] = df_furnace['Furnace_Normalised_Feed_C3H8']*44*100/(df_furnace['Furnace_Normalised_Feed_CH4']*16+df_furnace["Furnace_Normalised_Feed_C2H6"]*30+df_furnace["Furnace_Normalised_Feed_C3H8"]*44)

    df_furnace["Furnace_Feed_Average_Molecular_Wt"] = df_furnace['Furnace_Normalised_Feed_CH4']/100*16+df_furnace["Furnace_Normalised_Feed_C2H6"]/100*30+df_furnace["Furnace_Normalised_Feed_C3H8"]/100*44

    df_furnace['Furnace_conversion'] = ((df_furnace['DMCTF_feed']/1000)*(df_furnace['Furnace_Normalised_Feed_C2H6_Wt']/100) - 
                                (df_furnace['DMCTF_feed']/1000-df_furnace['Fresh ethane feed']))/((df_furnace['DMCTF_feed']/1000)*df_furnace['Furnace_Normalised_Feed_C2H6_Wt']/100)

    df_furnace['Furnace_Effluent_C2H6'] = (df_furnace['DMCTF_feed']/1000)*(df_furnace['Furnace_Normalised_Feed_C2H6_Wt']/100) * (1 - df_furnace['Furnace_conversion'])

    df_furnace['Furnace_Effluent_C2H6_wt%'] =(df_furnace['Furnace_Effluent_C2H6']/(df_furnace['DMCTF_feed']/1000))*100

    df_furnace['Plant_average_feed_rate_Coil'] = df_furnace["DMCTF_feed"]/(df_furnace["Number_Of_Furnaces_Online"]*4)

    df_furnace['Coil_CIP_Calculated'] = (-131.3081 +
            (0.0755 * df_furnace['Plant_average_feed_rate_Coil']) +
            (0.1463 * df_furnace['Ethane_Feed_Preheater_Ethane_Feed_Outlet_Pressure']) +
            (0.6819 * df_furnace['Furnace_Ethane_Feed_Preheater_Ethane_Feed_Outlet_Temperature']) +
            (0.4853 * df_furnace['Coil_Weighted_Avg_Feed_CV_opening']) +
            (0.8766 * df_furnace['Coil_Weighted_Avg_Steam_CV_opening']))

    df_furnace['Coil_Steam_Flow'] = (df_furnace['Coil_Avg_SHC_Ratio']*df_furnace['Plant_average_feed_rate_Coil'])
       
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
          0.00982963 * df_furnace['Coil_Mixed_Feed_Mol_wt'] ) / 
        (0.08206 * (df_furnace['Coil_Weighted_Avg_Coil_Mixed_Feed_Inlet_Temperature'] + 273.15))
    )

    df_furnace['Coil_CIP_Corrected_atma'] = np.where(
        (df_furnace['Coil_CIP_Calculated'] / 101.325 + 1) < 5,
        (df_furnace['Coil_CIP_Calculated'] / 101.325 + 1) - 
        (df_furnace['Coil_Volumetric_Flow'] * 144 / 1309.83) * 0.00986923,
        (df_furnace['Coil_CIP_Calculated'] / 101.325 + 1) - 
        (df_furnace['Coil_Volumetric_Flow'] * 131 / 1209.52) * 0.00986923
    )

    selected_col = ['Coil_Avg_COT','Ethane_Feed_Preheater_Ethane_Feed_Outlet_Pressure', 
                    'Furnace_Ethane_Feed_Preheater_Ethane_Feed_Outlet_Temperature','Coil_Weighted_Avg_Feed_CV_opening', 
                    'Coil_Weighted_Avg_Steam_CV_opening', 'Coil_Avg_SHC_Ratio','Coil_Weighted_Avg_COP',
                    'Coil_Weighted_Avg_Coil_Mixed_Feed_Inlet_Temperature',"Furnace_Feed_Average_Molecular_Wt",
                    'Coil_CIP_Calculated','Coil_Steam_Flow', 'Coil_Mixed_Feed_flow','Coil_Mixed_Feed_Cp',
                    'Coil_Mixed_Feed_Mol_wt', 'Coil_Volumetric_Flow', 'Coil_CIP_Corrected_atma',
                    'Furnace_Normalised_Feed_C2H6_Wt','Furnace_Normalised_Feed_C3H8_Wt',"Number_Of_Furnaces_Online",
                    'Furnace_conversion','Furnace_Effluent_C2H6','Furnace_Effluent_C2H6_wt%']


    df_furnace_truncate = df_furnace[selected_col]

# Merge whichever of the two tables were actually built. If both sheets
# were supplied, behaviour is unchanged (inner join on Timestamp). If
# only one was supplied, that one alone becomes `df` -- any predicted
# parameter (per the Model details sheet) whose input columns aren't in
# it simply won't find those columns and its training block below will
# raise a clear KeyError naming the missing column, rather than the
# whole run refusing to start.
if HAS_PI_DATA and HAS_FURNACE_DATA:
    df = df.merge(df_furnace_truncate, how="inner", left_index=True, right_index=True)
elif HAS_FURNACE_DATA and not HAS_PI_DATA:
    print("[plant_engine] 'PI data' sheet not supplied; using 'Furnace data' alone as the training table.")
    df = df_furnace_truncate.copy()
    df_stats = df.describe(include='all')
# else: HAS_PI_DATA only -> df already holds the PI-data table, nothing to merge.


#%% Config file loading
config_df_model_details = pd.read_excel(CONFIG_DIR + "/" + "Config_file.xlsx", sheet_name='Model details')

#%% Generic Kalman-filter training loop
# ---------------------------------------------------------------------
# Trains ONE state-space (Kalman filter) model per "Predicted parameter"
# row found in the "Model details" sheet of Config_file_updated.xlsx --
# but ONLY for rows whose "model" column says this is a data-driven
# model. Rows marked as a first-principle / simulation model are
# skipped here entirely: those parameters are computed by separate
# simulation/physics files (e.g. a plant's formulas plug-in used by
# whatif_runner.py), not by a Kalman filter trained on historian data.
#
# Nothing about the parameter names is hardcoded -- to train a different
# set of predicted parameters (e.g. for a different plant), just change
# what's in that config sheet: add a row, remove a row, rename a
# parameter, point its input columns at different historian tags, or
# flip its "model" value between a data-driven and a simulation/
# first-principle type.
# ---------------------------------------------------------------------

# Only "Input parameter_N" columns are ever treated as model inputs --
# explicitly, by name -- so any other metadata column added to this
# sheet in future (like "model") is never mistaken for an input tag.
_INPUT_PARAM_COLS = [c for c in config_df_model_details.columns
                     if str(c).strip().lower().startswith("input parameter")]

# The column that says whether a row is a data-driven (Kalman) model or
# a simulation / first-principle model. Tolerant of naming variants
# ("model", "Model type", "model_type", ...).
_MODEL_TYPE_COL = next(
    (c for c in config_df_model_details.columns
     if str(c).strip().lower() in ("model", "model type", "model_type")
     or ("model" in str(c).strip().lower() and "type" in str(c).strip().lower())),
    None
)


def _model_type_for(y_col: str) -> str:
    """Returns the (lower-cased, stripped) 'model' value for a predicted
    parameter's row, or '' if there's no such column / it's blank --
    an empty/unrecognised value is treated as a data-driven model, so
    existing config workbooks without this column keep working exactly
    as before."""
    if _MODEL_TYPE_COL is None:
        return ""
    rows = config_df_model_details.loc[
        config_df_model_details["Predicted parameter"] == y_col, _MODEL_TYPE_COL
    ]
    if rows.empty or pd.isna(rows.iloc[0]):
        return ""
    return str(rows.iloc[0]).strip().lower()


def _is_data_model(y_col: str) -> bool:
    """'Data model' (or anything containing 'data') -> Kalman training.
    Anything else explicitly set ('First principle', 'Simulation', ...)
    -> NOT trained here; a blank/missing value defaults to Kalman so
    older config workbooks without the 'model' column are unaffected."""
    mtype = _model_type_for(y_col)
    return mtype == "" or "data" in mtype


predicted_parameters = (
    config_df_model_details["Predicted parameter"]
    .dropna().astype(str).str.strip()
)
predicted_parameters = [p for p in predicted_parameters.unique() if p]

print(f"[plant_engine] {len(predicted_parameters)} predicted parameter(s) found: "
      f"{predicted_parameters}")

trained_parameters = []
skipped_parameters = []
simulation_parameters = []
accuracy_records = []

for y_col in predicted_parameters:
    if not _is_data_model(y_col):
        mtype = _model_type_for(y_col) or "(unspecified)"
        print(f"[plant_engine] '{y_col}' is a '{mtype}' model, not a Data model -- "
              f"skipping Kalman training. This parameter's output is expected to "
              f"come from a separate simulation/first-principle file, not this script.")
        simulation_parameters.append(y_col)
        accuracy_records.append({
            "Predicted parameter": y_col, "Status": "Simulation/first-principle (not trained here)",
            "Model type": mtype, "Input parameters": "", "Train rows": np.nan, "Test rows": np.nan,
            "RMSE": np.nan, "MAE": np.nan, "MAPE_%": np.nan, "R2": np.nan,
        })
        continue

    print(f"\n{'='*70}\n[plant_engine] Training model for predicted parameter: '{y_col}'\n{'='*70}")

    row = config_df_model_details[config_df_model_details["Predicted parameter"] == y_col]
    u_cols = row[_INPUT_PARAM_COLS].dropna(axis=1).values.ravel().tolist()
    u_cols = [str(c).strip() for c in u_cols if str(c).strip()]

    if not u_cols:
        print(f"[plant_engine] SKIPPING '{y_col}' -- no input parameters listed for it "
              f"in the Model details sheet.")
        skipped_parameters.append(y_col)
        accuracy_records.append({
            "Predicted parameter": y_col, "Status": "Skipped (no input parameters listed)",
            "Model type": "Data model", "Input parameters": "", "Train rows": np.nan, "Test rows": np.nan,
            "RMSE": np.nan, "MAE": np.nan, "MAPE_%": np.nan, "R2": np.nan,
        })
        continue

    missing_cols = [c for c in ([y_col] + u_cols) if c not in df.columns]
    if missing_cols:
        print(f"[plant_engine] SKIPPING '{y_col}' -- missing column(s) in the training "
              f"data: {missing_cols}. Check the Model details sheet against the "
              f"historian tags actually present in DMC_Screen_tags_data.xlsx.")
        skipped_parameters.append(y_col)
        accuracy_records.append({
            "Predicted parameter": y_col, "Status": f"Skipped (missing column(s): {missing_cols})",
            "Model type": "Data model", "Input parameters": ", ".join(u_cols), "Train rows": np.nan,
            "Test rows": np.nan, "RMSE": np.nan, "MAE": np.nan, "MAPE_%": np.nan, "R2": np.nan,
        })
        continue

    X = df[u_cols].values
    y = df[y_col].values

    X_train, X_test, y_train, y_test = train_test_split(df[u_cols], df[y_col], test_size=0.2, shuffle=True)

    # Scale data
    scaler_X = StandardScaler()
    scaler_y = StandardScaler()

    X_scaled_train = scaler_X.fit_transform(X_train)
    y_scaled_train = scaler_y.fit_transform(y_train.values.reshape(-1, 1))

    X_scaled_test = scaler_X.transform(X_test)  # Use same scaler
    y_scaled_test = scaler_y.transform(y_test.values.reshape(-1, 1))

    # After scaling
    X_scaled_train = pd.DataFrame(X_scaled_train, columns=u_cols, index=X_train.index)
    X_scaled_test = pd.DataFrame(X_scaled_test, columns=u_cols, index=X_test.index)
    y_scaled_train = pd.DataFrame(y_scaled_train, columns=[y_col], index=y_train.index)
    y_scaled_test = pd.DataFrame(y_scaled_test, columns=[y_col], index=y_test.index)

    # Now concat with proper column names
    train_data = pd.concat([X_scaled_train, y_scaled_train], axis=1)
    test_data = pd.concat([X_scaled_test, y_scaled_test], axis=1)

    common_index = train_data.index.intersection(test_data.index)
    num_common = len(common_index)
    print(f"Number of common rows based on timestamp index: {num_common}")

    X_scaled_train = X_scaled_train.to_numpy()
    X_scaled_test = X_scaled_test.to_numpy()
    y_scaled_train = y_scaled_train.to_numpy()
    y_scaled_test = y_scaled_test.to_numpy()

    # System identification
    try:
        nfoursid = NFourSID(
            train_data,
            output_columns=[y_col],
            input_columns=u_cols,
            num_block_rows=10
        )
        nfoursid.subspace_identification()
        state_space, _ = nfoursid.system_identification(rank=2)
    except Exception as fit_err:  # noqa: BLE001
        print(f"[plant_engine] SKIPPING '{y_col}' -- system identification failed: {fit_err}")
        skipped_parameters.append(y_col)
        accuracy_records.append({
            "Predicted parameter": y_col, "Status": f"Skipped (system identification failed: {fit_err})",
            "Model type": "Data model", "Input parameters": ", ".join(u_cols),
            "Train rows": len(X_train), "Test rows": len(X_test),
            "RMSE": np.nan, "MAE": np.nan, "MAPE_%": np.nan, "R2": np.nan,
        })
        continue

    """
    The D matrix in the state-space model shows how inputs directly affect the output.
    A larger absolute value indicates higher direct impact
    """
    D_matrix = state_space.d  # Shape: (n_outputs, n_inputs)
    D_matrix = pd.DataFrame(D_matrix, columns=u_cols, index=[y_col]).round(2)

    """
    The B matrix determines how inputs affect the internal states. Combined with C, it affects long-term behavior.
    """
    B_matrix = state_space.b  # Shape: (n_states, n_inputs)
    B_matrix = pd.DataFrame(B_matrix, columns=u_cols, index=[f'State_{i}' for i in range(B_matrix.shape[0])]).round(4)

    """You can compute the total influence of each input as the Frobenius norm across states:"""
    input_influence_B = np.linalg.norm(B_matrix, axis=0)
    input_importance_B = pd.Series(input_influence_B, index=u_cols).sort_values(ascending=False)
    print("Input Importance (via B matrix):")
    print(input_importance_B)

    """Combine B and D for Overall Importance"""
    total_importance = pd.Series(
        input_influence_B + np.abs(D_matrix.to_numpy()).flatten(),
        index=u_cols
    ).sort_values(ascending=False)
    print("Overall Variable Importance:")
    print(total_importance)

    # Plots are saved to file rather than plt.show()'n -- with an
    # arbitrary/unknown number of predicted parameters per plant, a
    # blocking plt.show() per model would stall an unattended training
    # run (and is a no-op anyway under the Agg backend the dashboard uses).
    fig_imp = plt.figure()
    total_importance.plot(kind='barh', title=f'Variable_Importance_for {y_col}')
    plt.xlabel('Composite Importance Score (B + D)')
    plt.tight_layout()
    plt.savefig(os.path.join(RESULTS_MODEL_DIR, f'variable_importance_{y_col}.png'))
    plt.close(fig_imp)

    kalman = Kalman(state_space=state_space, noise_covariance=np.eye(3))

    for i in range(len(X_scaled_test)):
        u_step = X_scaled_test[i].reshape(-1, 1)
        # Pass y=None to indicate missing measurement
        kalman.step(y=None, u=u_step)

    results_test = kalman.to_dataframe()
    y_pred_scaled = results_test[('$y_0$', 'filtered', 'output')].values
    y_pred = scaler_y.inverse_transform(y_pred_scaled.reshape(-1, 1)).ravel()
    y_true = y_test.values.ravel()

    # --- Plot Results ---
    fig_pred = plt.figure(figsize=(12, 5))
    plt.plot(y_true, label='Measured', alpha=0.7)
    plt.plot(y_pred, label='Predicted (Kalman)', linestyle='--')
    plt.legend()
    plt.xlabel('Time Step')
    plt.ylabel(f'{y_col}')
    plt.title(f'{y_col}_Prediction')
    plt.grid(True)
    plt.savefig(os.path.join(RESULTS_MODEL_DIR, f'prediction_plot_{y_col}.png'))
    plt.close(fig_pred)

    rmse = np.sqrt(np.mean((y_true - y_pred) ** 2))
    r2 = r2_score(y_true, y_pred)
    mae = mean_absolute_error(y_true, y_pred)
    try:
        mape = mean_absolute_percentage_error(y_true, y_pred) * 100
    except Exception:  # noqa: BLE001
        mape = np.nan
    print(f"RMSE: {rmse:.3f}")
    print(f"R\u00b2: {r2:.3f}")
    print(f"MAE: {mae:.3f}")
    if pd.notna(mape):
        print(f"MAPE: {mape:.2f}%")

    # Save the trained Kalman filter model
    with open(RESULTS_MODEL_DIR+"/"+f'kalman_filter_model_{y_col}.pkl', 'wb') as f:
        pickle.dump(kalman, f)

    joblib.dump(scaler_X, RESULTS_MODEL_DIR+"/"+f'scaler_X_{y_col}.pkl')
    joblib.dump(scaler_y, RESULTS_MODEL_DIR+"/"+f'scaler_y_{y_col}.pkl')

    trained_parameters.append(y_col)
    accuracy_records.append({
        "Predicted parameter": y_col,
        "Status": "Trained",
        "Model type": _model_type_for(y_col) or "Data model",
        "Input parameters": ", ".join(u_cols),
        "Train rows": len(X_scaled_train),
        "Test rows": len(X_scaled_test),
        "RMSE": round(float(rmse), 4),
        "MAE": round(float(mae), 4),
        "MAPE_%": round(float(mape), 2) if pd.notna(mape) else np.nan,
        "R2": round(float(r2), 4),
    })

#%% Bulk simulation / first-principle parameters
# ---------------------------------------------------------------------
# Predicted parameters marked as a simulation/first-principle model
# (anything other than "Data model") in the Model details sheet are
# computed HERE, across the whole historian dataframe, by calling into
# this plant's own formulas plug-in -- so they land in
# Raw_data_plus_simulated_data.xlsx the same way every Kalman-trained
# parameter does, instead of just being skipped with a log message.
#
# The plug-in (e.g. yanpet_olf1_formulas.py) opts a parameter into this
# by adding it to a BULK_SIMULATION dict: {"Predicted parameter name":
# callable(df) -> pd.Series}. A parameter with no BULK_SIMULATION entry
# is left out of Raw_data_plus_simulated_data.xlsx with a clear message
# -- nothing here crashes the rest of training.
# ---------------------------------------------------------------------
def _load_plant_formulas(plant_name: str):
    here = os.path.dirname(os.path.abspath(__file__))
    plant_name = (plant_name or "").strip().lower().replace(" ", "_")
    candidates = [
        os.path.join(here, "plants", f"{plant_name}_formulas.py"),  # whatif_runner.py's layout
        os.path.join(here, f"{plant_name}_formulas.py"),            # plug-in next to this script
    ]
    candidate = next((c for c in candidates if os.path.isfile(c)), None)
    if candidate is None:
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(f"plant_formulas_{plant_name}", candidate)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:  # noqa: BLE001
        print(f"[plant_engine] could not load plant physics plug-in '{candidate}': {e}")
        return None


def _set_accuracy_status(y_col: str, status: str):
    for _rec in accuracy_records:
        if _rec["Predicted parameter"] == y_col:
            _rec["Status"] = status
            return


_plant_formulas = _load_plant_formulas(PLANT_NAME)
_bulk_sim = getattr(_plant_formulas, "BULK_SIMULATION", {}) if _plant_formulas else {}

if simulation_parameters and not _plant_formulas:
    print(f"[plant_engine] {len(simulation_parameters)} simulation/first-principle parameter(s) "
          f"{simulation_parameters} found, but no formulas plug-in was found for plant "
          f"'{PLANT_NAME}' -- they will be left out of Raw_data_plus_simulated_data.xlsx.")

for y_col in simulation_parameters:
    sim_func = _bulk_sim.get(y_col)
    if sim_func is None:
        if _plant_formulas is not None:
            print(f"[plant_engine] '{y_col}' is a simulation/first-principle parameter but has "
                  f"no BULK_SIMULATION entry in this plant's formulas plug-in -- leaving it out "
                  f"of Raw_data_plus_simulated_data.xlsx. Add it to BULK_SIMULATION there to "
                  f"have it computed here.")
            _set_accuracy_status(y_col, "Simulation (no BULK_SIMULATION function registered for it)")
        else:
            _set_accuracy_status(y_col, "Simulation (no formulas plug-in found for this plant)")
        continue
    try:
        df[y_col] = sim_func(df.copy())
        print(f"[plant_engine] Computed '{y_col}' via its simulation/first-principle formula "
              f"for all {len(df)} historian rows.")
        _set_accuracy_status(y_col, "Simulated (bulk first-principle formula)")
    except Exception as sim_err:  # noqa: BLE001
        print(f"[plant_engine] SKIPPING bulk simulation for '{y_col}' -- {sim_err}")
        _set_accuracy_status(y_col, f"Simulation failed: {sim_err}")

print(f"\n[plant_engine] Training complete: {len(trained_parameters)} Kalman model(s) trained "
      f"({trained_parameters}); {len(simulation_parameters)} left to a simulation/"
      f"first-principle file ({simulation_parameters}); {len(skipped_parameters)} "
      f"skipped due to missing data ({skipped_parameters}).")

#%% Save per-model accuracy summary
# ---------------------------------------------------------------------
# One row per predicted parameter (trained, simulation/first-principle,
# or skipped), with RMSE / MAE / MAPE / R² for whichever ones actually
# got a Kalman model trained. Saved both as an Excel workbook (for
# opening/sharing) and a CSV (for easy programmatic reuse, e.g. by the
# dashboard). Re-running training overwrites both with the latest run.
# ---------------------------------------------------------------------
accuracy_df = pd.DataFrame(accuracy_records, columns=[
    "Predicted parameter", "Status", "Model type", "Input parameters",
    "Train rows", "Test rows", "RMSE", "MAE", "MAPE_%", "R2",
])
accuracy_df.to_excel(os.path.join(RESULTS_MODEL_DIR, "Model_accuracy_summary.xlsx"), index=False)
accuracy_df.to_csv(os.path.join(RESULTS_MODEL_DIR, "Model_accuracy_summary.csv"), index=False)
print(f"\n[plant_engine] Saved accuracy summary for {len(accuracy_df)} predicted parameter(s) to "
      f"{os.path.join(RESULTS_MODEL_DIR, 'Model_accuracy_summary.xlsx')}")
print(accuracy_df.to_string(index=False))

# ---------------------------------------------------------------------
# PLANT-SPECIFIC derived columns (YANPET_OLF1's own CGC/PRC/ERC naming).
# Other plants won't have these exact tags -- guarded so a missing
# column here just skips this summary instead of crashing the whole
# training run. If a different plant wants its own derived summary
# columns, add them the same way, guarded the same way, or move them
# into that plant's own formulas plug-in (see yanpet_olf1_formulas.py).
# ---------------------------------------------------------------------
try:
    df["Total_Power_(KW)"] = df["CGC_Power_KW"] + df["PRC_Total_estimated_power_MW"] * 1000 + df["ERC_power"]
    df["Total_required_steam_flow_(TPH)"] = (
        df["CGC_Turbine_HP_Steam_flow"] + df["PRC_turbine_Calculated_Steam_flow_TPH"] + df["ERC_turbine_steam_flow"]
    )
except KeyError as _missing:
    print(f"[plant_engine] Skipping Total_Power_(KW) / Total_required_steam_flow_(TPH) "
          f"summary columns -- not applicable to this plant (missing {_missing}).")

df.to_excel(os.path.join(RESULTS_DIR, 'Raw_data_plus_simulated_data.xlsx'))

df_corr = df.corr (method = "pearson").round(2)

def color_columns(val):
    if val > 0.4:
        color = 'background-color: green'
    elif val < -0.4:
        color = 'background-color: red'
    else:
        color = ''
    return color

with pd.ExcelWriter(RESULTS_DIR +'/'+'correlation_with_color_conditioning.xlsx', engine='openpyxl') as writer:
    # Write the DataFrame to the Excel file with styling
    df_corr.style.applymap(color_columns).to_excel(writer, index=True)

# #%% LBT creation

# # ============================== 
# # CONFIGURATION SECTION
# # ==============================

# # EXCEL_FILE = "LBT_Input.xlsx"            # 📥 Input Excel file with test, clean, and config data
# # OUTPUT_FILE = "LBT_Result.xlsx"      # 📤 Output Excel file with results
# # MAX_BENCHMARKS = 10                           # 🧮 Max benchmark rows to pick per match

# # SHEET_T = "test_data"                         # 🧪 Sheet with actual test data
# # SHEET_C = "clean_data"                        # ✅ Sheet with clean benchmark/reference data
# # SHEET_L = "lbt_input"                         # ⚙️ Sheet with matching rules and tolerances

# # ==============================
# # FUNCTION DEFINITIONS
# # ==============================

# T = df.copy()
# C = df.copy()
# L = pd.read_excel(file_path + "/" + 'DMC_Screen_tags_data.xlsx',sheet_name= "lbt_input" )
# # 🕒 Convert Timestamp to datetime
# T = T.reset_index(drop=False)
# C = C.reset_index(drop=False)

# T["Timestamp"] = pd.to_datetime(T["Timestamp"], errors="coerce")
# C["Timestamp"] = pd.to_datetime(C["Timestamp"], errors="coerce")

# # 📏 Dictionary: Match tag → decimal precision
# decimal_dict = L.set_index("Match_tags")["Match_Tag_Decimal"].dropna().to_dict()
# MAX_BENCHMARKS = 10   

# # def load_data(excel_file):
# #     # 🔄 Load all input sheets
# #     T = pd.read_excel(excel_file, sheet_name=SHEET_T)
# #     C = pd.read_excel(excel_file, sheet_name=SHEET_C)
# #     L = pd.read_excel(excel_file, sheet_name=SHEET_L)

# #     # 🕒 Convert Timestamp to datetime
# #     T["Timestamp"] = pd.to_datetime(T["Timestamp"], errors="coerce")
# #     C["Timestamp"] = pd.to_datetime(C["Timestamp"], errors="coerce")

# #     # 📏 Dictionary: Match tag → decimal precision
# #     decimal_dict = L.set_index("Match_tags")["Match_Tag_Decimal"].dropna().to_dict()
# #     return T, C, L, decimal_dict

# def build_result(row_t, matched_row, T, C, L, match_tags, iteration_unused, decimal_dict):
#     result = {}

#     # ✅ Add actual and benchmark values for T columns
#     for col in T.columns:
#         val_actual = row_t[col]
#         val_benchmark = matched_row.get(col, np.nan)

#         if col in decimal_dict:
#             decimals = int(decimal_dict[col])
#             val_actual = round(val_actual, decimals) if pd.notnull(val_actual) else val_actual
#             val_benchmark = round(val_benchmark, decimals) if pd.notnull(val_benchmark) else val_benchmark

#         result[f"{col}_Actual"] = val_actual
#         result[f"{col}_benchmark"] = val_benchmark

#     # ➕ Add extra benchmark-only columns from C
#     for col in C.columns:
#         if col not in T.columns:
#             val_benchmark = matched_row.get(col, np.nan)
#             if col in decimal_dict:
#                 decimals = int(decimal_dict[col])
#                 val_benchmark = round(val_benchmark, decimals) if pd.notnull(val_benchmark) else val_benchmark
#             result[f"{col}_benchmark"] = val_benchmark

#     matched_iterations = []

#     # 🔁 For each matching tag, calculate delta and find which iteration matched
#     for tag in match_tags:
#         delta_col = f"{tag}_delta"
#         iter_col = f"matched_iteration_{tag}"

#         actual_val = row_t.get(tag, np.nan)
#         benchmark_val = matched_row.get(tag, np.nan)

#         if pd.notnull(actual_val) and pd.notnull(benchmark_val):
#             decimals = int(decimal_dict.get(tag, 4))
#             actual_val = round(actual_val, decimals)
#             benchmark_val = round(benchmark_val, decimals)
#             delta = round(benchmark_val - actual_val, decimals)
#             result[delta_col] = delta

#             found_iter = None
#             for _, tol_row in L[L["Match_tags"] == tag].iterrows():
#                 it_no = tol_row["Iteration No"]
#                 min_tol = tol_row["Tolerance_minimum"]
#                 max_tol = tol_row["Tolerance_maximum"]
#                 if -min_tol <= delta <= max_tol:
#                     found_iter = it_no
#                     break

#             result[iter_col] = found_iter
#             if found_iter is not None:
#                 matched_iterations.append(found_iter)
#         else:
#             result[delta_col] = np.nan
#             result[iter_col] = None

#     result["iteration_matched"] = max(matched_iterations) if matched_iterations else None
#     return result

# def build_no_match_result(row_t, T, C, match_tags, decimal_dict):
#     result = {}

#     # 🚫 If no match is found, store actuals and fill rest with "BENCHMARK NOT FOUND".
#     for col in T.columns:
#         val_actual = row_t[col]
#         if col in decimal_dict:
#             decimals = int(decimal_dict[col])
#             val_actual = round(val_actual, decimals) if pd.notnull(val_actual) else val_actual
#         result[f"{col}_Actual"] = val_actual
#         result[f"{col}_benchmark"] = "BENCHMARK NOT FOUND"

#     for col in C.columns:
#         if col not in T.columns:
#             result[f"{col}_benchmark"] = "BENCHMARK NOT FOUND"

#     for tag in match_tags:
#         result[f"{tag}_delta"] = "BENCHMARK NOT FOUND"
#         result[f"matched_iteration_{tag}"] = "BENCHMARK NOT FOUND"

#     result["iteration_matched"] = "BENCHMARK NOT FOUND"
#     return result

# def match_records(T, C, L, max_benchmarks, decimal_dict):
#     results = []
#     match_tags = L["Match_tags"].dropna().unique().tolist()
#     max_iterations = int(pd.to_numeric(L["Iteration No"], errors="coerce").dropna().max())

#     for _, row_t in T.iterrows():
#         match_found = False

#         for iteration in range(1, max_iterations + 1):
#             current_tol = L[L["Iteration No"] == iteration]
#             filtered_C = C.copy()

#             for _, tol_row in current_tol.iterrows():
#                 col = tol_row["Match_tags"]
#                 min_tol = tol_row["Tolerance_minimum"]
#                 max_tol = tol_row["Tolerance_maximum"]

#                 if col not in T.columns or col not in C.columns or col == "Timestamp":
#                     continue

#                 val_t = row_t[col]
#                 if pd.isnull(val_t):
#                     continue

#                 if col in decimal_dict:
#                     decimals = int(decimal_dict[col])
#                     val_t = round(val_t, decimals)
#                     filtered_C[col] = filtered_C[col].round(decimals)

#                 filtered_C = filtered_C[
#                     (filtered_C[col] >= val_t - min_tol) & (filtered_C[col] <= val_t + max_tol)
#                 ]

#             if not filtered_C.empty:
#                 match_found = True
#                 for _, matched_row in filtered_C.head(max_benchmarks).iterrows():
#                     results.append(build_result(row_t, matched_row, T, C, L, match_tags, iteration, decimal_dict))
#                 break

#         if not match_found:
#             results.append(build_no_match_result(row_t, T, C, match_tags, decimal_dict))

#     return results

# def filter_optimal_rows(df, L):
#     perf_config = L[["performance_tag", "direction"]].dropna().drop_duplicates()

#     if perf_config.empty:
#         print("⚠️ No performance tag found in config - skipping filtering.")
#         return df

#     perf_tag = perf_config.iloc[0]["performance_tag"]
#     direction = perf_config.iloc[0]["direction"].strip().lower()
#     perf_col = f"{perf_tag}_benchmark"

#     if perf_col not in df.columns:
#         print(f"⚠️ Performance column '{perf_col}' not found - skipping filtering.")
#         return df

#     df[perf_col] = pd.to_numeric(df[perf_col], errors="coerce")
#     matched_df = df.dropna(subset=[perf_col])
#     unmatched_df = df[df[perf_col].isna()]

#     if direction == "minimize":
#         optimal_df = matched_df.loc[matched_df.groupby("Timestamp_Actual")[perf_col].idxmin()]
#     elif direction == "maximize":
#         optimal_df = matched_df.loc[matched_df.groupby("Timestamp_Actual")[perf_col].idxmax()]
#     else:
#         raise ValueError(f"Unknown direction '{direction}' in performance config.")

#     unmatched_latest = unmatched_df.sort_values("Timestamp_Actual").drop_duplicates(
#         subset=["Timestamp_Actual"], keep="last"
#     )

#     return pd.concat(
#         [optimal_df, unmatched_latest[~unmatched_latest["Timestamp_Actual"].isin(optimal_df["Timestamp_Actual"])]],
#         ignore_index=True,
#     ).sort_values("Timestamp_Actual").reset_index(drop=True)

# def process_results(results, T, C, L):
#     df = pd.DataFrame(results)
#     df.dropna(axis=1, how="all", inplace=True)
#     df = df.loc[:, ~df.columns.str.contains("^Unnamed")]

#     for col in [c for c in df.columns if c.endswith("Timestamp_benchmark")]:
#         df[col] = df[col].fillna("BENCHMARK NOT FOUND")  # Consistent fill

#     actual_bench_cols = []
#     for col in T.columns:
#         if f"{col}_Actual" in df.columns: actual_bench_cols.append(f"{col}_Actual")
#         if f"{col}_benchmark" in df.columns: actual_bench_cols.append(f"{col}_benchmark")

#     for col in C.columns:
#         if col not in T.columns and f"{col}_benchmark" in df.columns:
#             actual_bench_cols.append(f"{col}_benchmark")

#     delta_cols = sorted([c for c in df.columns if c.endswith("_delta")])
#     iter_cols = sorted([c for c in df.columns if c.startswith("matched_iteration_")])

#     final_cols = actual_bench_cols + delta_cols + iter_cols
#     if "iteration_matched" in df.columns:
#         final_cols.append("iteration_matched")

#     remaining = [c for c in df.columns if c not in final_cols]
#     df = df[final_cols + remaining]

#     return filter_optimal_rows(df, L)

# # def save_results(df, output_file):
# #     df.to_excel(output_file, index=False)
# #     print(f"✅ Results saved to: {output_file}")

# # ==============================
# # MAIN EXECUTION BLOCK
# # ==============================

# # 📦 Load input data
# # T, C, L, decimal_dict = load_data(EXCEL_FILE)

# # 🔍 Perform record matching
# results = match_records(T, C, L, MAX_BENCHMARKS, decimal_dict)

# # 🧹 Clean and organize results
# final_df = process_results(results, T, C, L)

# # 💾 Save to Excel
# # save_results(final_df, OUTPUT_FILE)

# final_df.to_excel(RESULTS_DIR+"/"+"YP_OlF1_LBT_result.xlsx")


#%% what if preparation for YANPET OLF1
# config_df_model_details_model_details = pd.read_excel(file_path +"/" + "Config_file_updated.xlsx", sheet_name= 'Model details')
# user_input_df = pd.read_excel(file_path + "/" + 'Config_file.xlsx',sheet_name= "user inputs")
# constraints_df = pd.read_excel(file_path + "/" + 'Config_file.xlsx',sheet_name= "Constraints")
# user_time = '2025-02-11 07:00:00'
# row = df.loc[user_time]

# # user_input = input("Enter timestamp (YYYY-MM-DD HH:MM:SS):")
# user_input = user_time
# selected_row = df.loc[user_input]
# selected_row = pd.DataFrame(selected_row).T  # Convert Series to DataFrame
# selected_row.index.name = "Timestamp"

# selected_row_updated = selected_row.copy()

# def predict_and_update_with_kalman(
#     y_col: str, 
#     selected_row_updated: pd.DataFrame, 
#     config_df_model_details: pd.DataFrame, 
#     results_dir: str = RESULTS_MODEL_DIR
# ) -> pd.DataFrame:
#     """
#     Generalizes the Kalman filter loading, scaling, prediction, and dataframe update process
#     for any target column (y_col).
    
#     Parameters:
#     - y_col: The target parameter name (string).
#     - selected_row_updated: The input DataFrame containing feature data.
#     - config_df_model_details: DataFrame containing configuration mapping for features.
#     - results_dir: Directory where models and scalers are stored.
    
#     Returns:
#     - selected_row_updated with the predicted value updated for y_col.
#     """
#     # 1. Extract feature columns dynamically
#     u_cols = config_df_model_details[config_df_model_details["Predicted parameter"] == y_col]
#     u_cols = u_cols.dropna(axis=1)
#     u_cols = u_cols.iloc[:, 1:].values.ravel().tolist()

#     # 2. Construct dynamic file paths
#     model_path = os.path.join(results_dir, f'kalman_filter_model_{y_col}.pkl')
#     scaler_x_path = os.path.join(results_dir, f'scaler_X_{y_col}.pkl')
#     scaler_y_path = os.path.join(results_dir, f'scaler_y_{y_col}.pkl')

#     # 3. Load the model and scalers dynamically
#     with open(model_path, 'rb') as f:
#         kalman_model = pickle.load(f)

#     scaler_X = joblib.load(scaler_x_path)
#     scaler_y = joblib.load(scaler_y_path)

#     # 4. Prepare data and run the Kalman filter step
#     feature_df = selected_row_updated[u_cols]
#     scaled_test = scaler_X.transform(feature_df)
#     kalman_model.step(y=None, u=scaled_test.reshape(-1, 1))

#     # 5. Extract results and inverse transform
#     results = kalman_model.to_dataframe()
#     pred_scaled = results[('$y_0$', 'filtered', 'output')].iloc[-1]
#     pred_unscaled = scaler_y.inverse_transform([[pred_scaled]]).ravel()

#     # 6. Update the DataFrame dynamically using `loc`
#     selected_row_updated.loc[:, y_col] = pred_unscaled[0]

#     return selected_row_updated

# def update_parameter_from_user_input(
#     y_col: str, 
#     user_input_df: pd.DataFrame, 
#     selected_row_updated: pd.DataFrame
# ) -> pd.DataFrame:
#     """
#     Generalizes fetching user input for a specific parameter (y_col),
#     handling type conversion/NaNs, and updating the selected_row_updated dataframe 
#     if a valid user input exists.
    
#     Parameters:
#     - y_col: The target parameter name (string).
#     - user_input_df: DataFrame containing user inputs with "Parameter" and "Value" columns.
#     - selected_row_updated: DataFrame (or Series) containing the current row/values.
    
#     Returns:
#     - selected_row_updated with the parameter updated if valid user input is provided.
#     """
#     # 1. Fetch user input for the specific parameter dynamically
#     matching_input = user_input_df.loc[user_input_df["Parameter"].str.strip() == y_col, 'Value']
#     raw_input_val = matching_input.iloc[0] if not matching_input.empty else np.nan
    
#     # 2. Convert to float and handle NaN / exceptions safely
#     try:
#         user_value = float(raw_input_val) if pd.notna(raw_input_val) else np.nan
#     except (ValueError, TypeError):
#         user_value = np.nan

#     # 3. Safely extract the current/default value from selected_row_updated
#     current_val_series = selected_row_updated.get(y_col, np.nan)
#     current_value = current_val_series.iloc[0] if isinstance(current_val_series, pd.Series) and not current_val_series.empty else current_val_series

#     # 4. Update with user input if valid, otherwise keep the current value
#     final_value = user_value if not np.isnan(user_value) else current_value
    
#     # Assign back safely using .loc if it's a DataFrame or dictionary-like assignment
#     if isinstance(selected_row_updated, pd.DataFrame):
#         selected_row_updated.loc[:, y_col] = final_value
#     else:
#         selected_row_updated[y_col] = final_value

#     return selected_row_updated

# #User based DNCTF input updation
# y_col = "DMCTF_feed"
# selected_row_updated = update_parameter_from_user_input(
#     y_col=y_col,
#     user_input_df=user_input_df,
#     selected_row_updated=selected_row_updated
# )

# # Quench section prediction updation
# y_col = "Quench_tower_overhead_temp"
# selected_row_updated = predict_and_update_with_kalman(
#     y_col=y_col,
#     selected_row_updated=selected_row_updated,
#     config_df_model_details=config_df_model_details
# )

# y_col = "Quench_tower_overhead_temp"
# selected_row_updated = update_parameter_from_user_input(
#     y_col=y_col,
#     user_input_df=user_input_df,
#     selected_row_updated=selected_row_updated
# )

# # CGC suction pressure prediction updation
# mask = (selected_row_updated['CGC_Turbine_HP_Steam_flow'] < constraints_df[constraints_df["Parameter"]=="CGC_Turbine_HP_Steam_flow"]["user input value"].values[0]) & (selected_row_updated['CGC_TURBINE_1_SPEED_(RPM)'] < constraints_df[constraints_df["Parameter"]=="CGC_TURBINE_1_SPEED_(RPM)"]["user input value"].values[0])
# selected_row_updated.loc[mask, 'CGC_TURBINE_1_SPEED_(RPM)'] = constraints_df[constraints_df["Parameter"]=="CGC_TURBINE_1_SPEED_(RPM)"]["Max vlaue"].values[0] 

# #KT1301 Turbine RPM user based input
# y_col = 'CGC_TURBINE_1_SPEED_(RPM)'
# selected_row_updated = update_parameter_from_user_input(
#     y_col=y_col,
#     user_input_df=user_input_df,
#     selected_row_updated=selected_row_updated
# )

# y_col = "CGC_STAGE_1_SUCTION_PRESSURE"
# selected_row_updated = predict_and_update_with_kalman(
#     y_col=y_col,
#     selected_row_updated=selected_row_updated,
#     config_df_model_details=config_df_model_details
# )

# # CGC Suction pressure user based value 
# y_col = "CGC_STAGE_1_SUCTION_PRESSURE"
# selected_row_updated = update_parameter_from_user_input(
#     y_col=y_col,
#     user_input_df=user_input_df,
#     selected_row_updated=selected_row_updated
# )

# #Overall COT analysis
# def COT_calculation(df_furnace):
#     df_furnace['Plant_average_feed_rate_Coil'] = df_furnace["DMCTF_feed"]/(df_furnace["Number_Of_Furnaces_Online"]*4)
    
#     df_furnace['Coil_CIP_Calculated'] = (-131.3081 +
#             (0.0755 * df_furnace['Plant_average_feed_rate_Coil']) +
#             (0.1463 * df_furnace['Ethane_Feed_Preheater_Ethane_Feed_Outlet_Pressure']) +
#             (0.6819 * df_furnace['Furnace_Ethane_Feed_Preheater_Ethane_Feed_Outlet_Temperature']) +
#             (0.4853 * df_furnace['Coil_Weighted_Avg_Feed_CV_opening']) +
#             (0.8766 * df_furnace['Coil_Weighted_Avg_Steam_CV_opening']))
    
#     df_furnace['Coil_Steam_Flow'] = (df_furnace['Coil_Avg_SHC_Ratio']*df_furnace['Plant_average_feed_rate_Coil'])
           
#     df_furnace['Coil_Mixed_Feed_flow'] = df_furnace['Coil_Steam_Flow'] + df_furnace['Plant_average_feed_rate_Coil']
    
#     df_furnace['Coil_Mixed_Feed_Cp'] = (
#         (df_furnace['Coil_Steam_Flow'] * 2.067) + 
#         (df_furnace['Plant_average_feed_rate_Coil'] * 1.909)
#     ) / (df_furnace['Coil_Steam_Flow'] + df_furnace['Plant_average_feed_rate_Coil'])   
    
#     df_furnace['Coil_Mixed_Feed_Mol_wt'] = (
#         df_furnace['Coil_Mixed_Feed_flow'] / 
#         (
#             (df_furnace['Plant_average_feed_rate_Coil'] / df_furnace["Furnace_Feed_Average_Molecular_Wt"]) + 
#             (df_furnace['Coil_Steam_Flow'] / 18.0)
#         )
#     )
    
#     df_furnace['Coil_Volumetric_Flow'] = (
#         df_furnace['Coil_Mixed_Feed_flow']
#     ) / (
#         ((df_furnace['Coil_CIP_Calculated'] + 101.325) * 
#           0.00982963 * df_furnace['Coil_Mixed_Feed_Mol_wt'] ) / 
#         (0.08206 * (df_furnace['Coil_Weighted_Avg_Coil_Mixed_Feed_Inlet_Temperature'] + 273.15))
#     )
    
#     df_furnace['Coil_CIP_Corrected_atma'] = np.where(
#         (df_furnace['Coil_CIP_Calculated'] / 101.325 + 1) < 5,
#         (df_furnace['Coil_CIP_Calculated'] / 101.325 + 1) - 
#         (df_furnace['Coil_Volumetric_Flow'] * 144 / 1309.83) * 0.00986923,
#         (df_furnace['Coil_CIP_Calculated'] / 101.325 + 1) - 
#         (df_furnace['Coil_Volumetric_Flow'] * 131 / 1209.52) * 0.00986923
#     )
#     return df_furnace

# selected_row = COT_calculation(selected_row)

# Delta_CGC_Suction_Pressure_old = 0

# selected_row['Corrected_COP_Furnace'] = selected_row['Coil_Weighted_Avg_COP'] + Delta_CGC_Suction_Pressure_old

# selected_row['Furnace_Effluent_C2H6'] = (selected_row['DMCTF_feed']/1000)*(selected_row['Furnace_Normalised_Feed_C2H6_Wt']/100) * (1 - selected_row['Furnace_conversion'])

# selected_row['Furnace_Effluent_C2H6_wt%'] =(selected_row['Furnace_Effluent_C2H6']/(selected_row['DMCTF_feed']/1000))*100

# selected_row['Coil_Avg_COT_actual'] = ((
#     0.937913371 * (selected_row['Coil_CIP_Corrected_atma'] - 0.3) -
#     2.413045433 * (selected_row['Corrected_COP_Furnace'] / 101.325 + 1 - 0.2) +
#     2.774285758 * selected_row['Coil_Avg_SHC_Ratio'] +
#     0.002253435 * selected_row['Plant_average_feed_rate_Coil'] -
#     0.463411867 * selected_row['Furnace_Normalised_Feed_C3H8_Wt'] +
#     0.674941411 * selected_row['Furnace_Normalised_Feed_C2H6_Wt'] +
#     337.8851416 - selected_row['Furnace_Effluent_C2H6_wt%']
#     ))/0.451606991


# selected_row_updated = COT_calculation(selected_row_updated)

# Delta_CGC_Suction_Pressure = selected_row_updated["CGC_STAGE_1_SUCTION_PRESSURE"] - selected_row["CGC_STAGE_1_SUCTION_PRESSURE"]

# selected_row_updated['Corrected_COP_Furnace'] = selected_row_updated['Coil_Weighted_Avg_COP'] + Delta_CGC_Suction_Pressure

# if ((selected_row_updated['DMCTF_feed'].iloc[0] / 1000) - selected_row_updated['Fresh_ethane_feed'].iloc[0])>70:
#     selected_row_updated['Fresh_ethane_feed'] = (selected_row_updated['DMCTF_feed']/1000) - 70

# selected_row_updated['Furnace_conversion'] = ((selected_row_updated['DMCTF_feed']/1000)*(selected_row_updated['Furnace_Normalised_Feed_C2H6_Wt']/100) - 
#                             (selected_row_updated['DMCTF_feed']/1000-selected_row_updated['Fresh_ethane_feed']))/((selected_row_updated['DMCTF_feed']/1000)*selected_row_updated['Furnace_Normalised_Feed_C2H6_Wt']/100)

# selected_row_updated['Furnace_Effluent_C2H6'] = (selected_row_updated['DMCTF_feed']/1000)*(selected_row_updated['Furnace_Normalised_Feed_C2H6_Wt']/100) * (1 - selected_row_updated['Furnace_conversion'])

# selected_row_updated['Furnace_Effluent_C2H6_wt%'] =(selected_row_updated['Furnace_Effluent_C2H6']/(selected_row_updated['DMCTF_feed']/1000))*100

# selected_row_updated['Coil_Avg_COT'] = ((
#     0.937913371 * (selected_row_updated['Coil_CIP_Corrected_atma'] - 0.3) -
#     2.413045433 * (selected_row_updated['Corrected_COP_Furnace'] / 101.325 + 1 - 0.2) +
#     2.774285758 * selected_row_updated['Coil_Avg_SHC_Ratio'] +
#     0.002253435 * selected_row_updated['Plant_average_feed_rate_Coil'] -
#     0.463411867 * selected_row_updated['Furnace_Normalised_Feed_C3H8_Wt'] +
#     0.674941411 * selected_row_updated['Furnace_Normalised_Feed_C2H6_Wt'] +
#     337.8851416 - selected_row_updated['Furnace_Effluent_C2H6_wt%']
#     ))/0.451606991

# delta_COT = selected_row_updated['Coil_Avg_COT'] -selected_row['Coil_Avg_COT_actual']

# selected_row_updated['Coil_Avg_COT'] = selected_row['Coil_Avg_COT'] + delta_COT


# # CGC stage 5 pressure prediction updation
# y_col = "CGC_5TH_STG_DISCH_PRES"
# selected_row_updated = predict_and_update_with_kalman(
#     y_col=y_col,
#     selected_row_updated=selected_row_updated,
#     config_df_model_details=config_df_model_details
# )

# #Fifth stage discharge pressure user based value
# y_col = "CGC_5TH_STG_DISCH_PRES"
# selected_row_updated = update_parameter_from_user_input(
#     y_col=y_col,
#     user_input_df=user_input_df,
#     selected_row_updated=selected_row_updated
# )

# # 1. Safe Constraint Check
# constraint_hit = False
# param_name = "CGC_5TH_STG_DISCH_PRES"

# # Check if parameter exists in constraints_df before accessing
# mask = constraints_df["Parameter"] == param_name
# if mask.any():
#     limit = constraints_df.loc[mask, "user input value"].values[0]
#     if selected_row_updated[param_name].values[0] > limit:
#         selected_row_updated[param_name] = "constraints hits: Reduce the DMCTF"
#         constraint_hit = True
#         Actual_vs_estimated = pd.concat([selected_row, selected_row_updated], axis=0)
#         Actual_vs_estimated.index = ["actual", "estimated"]
#         styled = Actual_vs_estimated
#         styled.to_excel(os.path.join(RESULTS_DIR, "Actual_vs_estimated what if.xlsx"), engine='openpyxl')
# else:
#     print(f"⚠️ Warning: Parameter '{param_name}' not found in constraints_df")

# if not constraint_hit:
#     # CGC power prediction
#     y_col = "CGC_Power_KW"
#     selected_row_updated = predict_and_update_with_kalman(
#     y_col=y_col,
#     selected_row_updated=selected_row_updated,
#     config_df_model_details=config_df_model_details)
    
#     # CGC Turbine HP steam flow
#     y_col = "CGC_Turbine_HP_Steam_flow"
#     selected_row_updated = predict_and_update_with_kalman(
#         y_col=y_col,
#         selected_row_updated=selected_row_updated,
#         config_df_model_details=config_df_model_details
#     )
    
#     # PRC 1st stage suction flow prediction
#     mask = (selected_row_updated['PRC_turbine_steam_flow'] < constraints_df[constraints_df["Parameter"]=="PRC_turbine_steam_flow"]["user input value"].values[0]) & (selected_row_updated['PRC_turbine_RPM'] < constraints_df[constraints_df["Parameter"]=="PRC_turbine_RPM"]["user input value"].values[0])
#     selected_row_updated.loc[mask, 'PRC_turbine_RPM'] = constraints_df[constraints_df["Parameter"]=="PRC_turbine_RPM"]["Max vlaue"].values[0] 
    
#     #PRC_turbine Turbine speed user based input
#     y_col = "PRC_turbine_RPM"
#     selected_row_updated = update_parameter_from_user_input(
#         y_col=y_col,
#         user_input_df=user_input_df,
#         selected_row_updated=selected_row_updated
#     )
    
#     y_col = "PRC_1ST_STAGE_Suction_FLOW"
#     selected_row_updated = predict_and_update_with_kalman(
#     y_col=y_col,
#     selected_row_updated=selected_row_updated,
#     config_df_model_details=config_df_model_details
#     )
    
#     # PRC 1st stage suction Pressure prediction 
#     y_col = "PRC_1ST_STAGE_Suction_PRESSURE"
#     selected_row_updated = predict_and_update_with_kalman(
#     y_col=y_col,
#     selected_row_updated=selected_row_updated,
#     config_df_model_details=config_df_model_details
#     )
    
#     #PRC_1ST_STAGE_Suction_PRESSURE user based input
#     y_col = "PRC_1ST_STAGE_Suction_PRESSURE"
#     selected_row_updated = update_parameter_from_user_input(
#         y_col=y_col,
#         user_input_df=user_input_df,
#         selected_row_updated=selected_row_updated
#     )
    
#     # PRC PRC_2nd_stage_drum_Overhead_Flow prediction
#     y_col = "PRC_2nd_stage_drum_Overhead_Flow"
#     selected_row_updated = predict_and_update_with_kalman(
#     y_col=y_col,
#     selected_row_updated=selected_row_updated,
#     config_df_model_details=config_df_model_details
#     )   
    
#     def PRC_section_power(df):
#         Density_1st_stage =[]
#         rho_1st_stage_flow = []
#         for i in range(len(df)):
#             T_K = df["PRC_1ST_STAGE_Suction_TEMP"].iloc[i] + 273.15
#             P_Pa = df["PRC_1ST_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5
#             rho_1st_stage = PropsSI('D', 'T', T_K, 'P', P_Pa, 'Propylene')
#             volumetric_flow = df["PRC_1ST_STAGE_Suction_FLOW"].iloc[i] * 1000 / rho_1st_stage
#             rho_1st_stage_flow.append(volumetric_flow)
#             Density_1st_stage.append(rho_1st_stage)
               
#         df["PRC_Density_1st_stage"] = Density_1st_stage
#         df["PRC VOL FLOW 1ST STAGE"] = rho_1st_stage_flow

#         Density_2nd_stage =[]
#         rho_2nd_stage_flow = []
#         for i in range(len(df)):
#             T_K = df["PRC_2nd_stage_drum_Overhead_Temp"].iloc[i] + 273.15
#             P_Pa = df["PRC_2ND_STAGE_Suction_PRESSURE"].iloc[i]* 1000 + 1e5
#             rho_2nd_stage = PropsSI('D', 'T', T_K, 'P', P_Pa, 'Propylene')
#             volumetric_flow = (df["PRC_1ST_STAGE_Suction_FLOW"].iloc[i] + df["PRC_2nd_stage_drum_Overhead_Flow"].iloc[i]) * 1000 / rho_2nd_stage
#             rho_2nd_stage_flow.append(volumetric_flow)
#             Density_2nd_stage.append(rho_2nd_stage)
            
#         df["PRC_Density_2nd_stage"] = Density_2nd_stage   
#         df["PRC VOL FLOW 2ND STAGE"] = rho_2nd_stage_flow

#         Density_3rd_stage =[]
#         rho_3rd_stage_flow = []

#         for i in range(len(df)):
#             T_K = df["PRC_3RD_STAGE_Suction_TEMP"].iloc[i] + 273.15
#             P_Pa = df["PRC_3RD_STAGE_Suction_PRESSURE"].iloc[i] * 1000 + 1e5
#             rho_3rd_stage = PropsSI('D', 'T', T_K, 'P', P_Pa, 'Propylene')
#             volumetric_flow = df["PRC_3RD_STAGE_Suction_FLOW"].iloc[i]  * 1000 / rho_3rd_stage
#             rho_3rd_stage_flow.append(volumetric_flow)
#             Density_3rd_stage.append(rho_3rd_stage)

#         df["PRC_Density_3rd_stage"] = Density_3rd_stage
#         df["PRC VOL FLOW 3RD STAGE"] = rho_3rd_stage_flow

#         #Compressor power calculation based on isentropic enthalpy at outlet pressure, keeping entropy constant (i.e., isentropic compression).
#         eta = 0.70  # Assume Compressor efficiency
#         PRC_1st_stage_comp_estimated_power =[]
#         # Step 2: Get inlet enthalpy and entropy
#         for i in range(len(df)):
#             h1 = PropsSI('H', 'T',df["PRC_1ST_STAGE_Suction_TEMP"].iloc[i] + 273.15 , 'P', df["PRC_1ST_STAGE_Suction_PRESSURE"].iloc[i] * 1000+ 1e5, 'Propylene')  # J/kg
#             s1 = PropsSI('S', 'T',df["PRC_1ST_STAGE_Suction_TEMP"].iloc[i] + 273.15 , 'P', df["PRC_1ST_STAGE_Suction_PRESSURE"].iloc[i] * 1000+ 1e5, 'Propylene')  # J/kg.K
#             #Get isentropic outlet enthalpy (h2s at P2, s1)
#             T2s = PropsSI('T', 'P', df["PRC_1ST_STAGE_Discharge_PRESSURE"].iloc[i]* 1000 + 1e5, 'S', s1, 'Propylene')  # isentropic outlet temp
#             h2s = PropsSI('H', 'P', df["PRC_1ST_STAGE_Discharge_PRESSURE"].iloc[i]* 1000+ 1e5, 'S', s1, 'Propylene')  # J/kg
#             h2 = h1 + (h2s - h1) / eta
#             power = ((df["PRC_1ST_STAGE_Suction_FLOW"].iloc[i] * 1000)/3600) * (h2 - h1)/1e6  # KW
#             PRC_1st_stage_comp_estimated_power.append(power)
            
#         df["PRC_1st_stage_comp_estimated_power_MW"] = PRC_1st_stage_comp_estimated_power

#         # 2nd stage compressor power
#         PRC_2nd_stage_comp_estimated_power =[]
#         # Step 2: Get inlet enthalpy and entropy
#         for i in range(len(df)):
#             h1 = PropsSI('H', 'T',df["PRC_2nd_stage_drum_Overhead_Temp"].iloc[i] + 273.15 , 'P', df["PRC_2ND_STAGE_Suction_PRESSURE"].iloc[i] * 1000+ 1e5, 'Propylene')  # J/kg
#             s1 = PropsSI('S', 'T',df["PRC_2nd_stage_drum_Overhead_Temp"].iloc[i] + 273.15 , 'P', df["PRC_2ND_STAGE_Suction_PRESSURE"].iloc[i] * 1000+ 1e5, 'Propylene')  # J/kg.K
#             #Get isentropic outlet enthalpy (h2s at P2, s1)
#             T2s = PropsSI('T', 'P', df["PRC_3RD_STAGE_Suction_PRESSURE"].iloc[i]* 1000 + 1e5, 'S', s1, 'Propylene')  # isentropic outlet temp
#             h2s = PropsSI('H', 'P', df["PRC_3RD_STAGE_Suction_PRESSURE"].iloc[i]* 1000+ 1e5, 'S', s1, 'Propylene')  # J/kg
#             h2 = h1 + (h2s - h1) / eta
#             power = (((df["PRC_2nd_stage_drum_Overhead_Flow"].iloc[i] + df["PRC_1ST_STAGE_Suction_FLOW"].iloc[i]) * 1000)/3600) * (h2 - h1)/1e6  # MW
#             PRC_2nd_stage_comp_estimated_power.append(power)
            
#         df["PRC_2nd_stage_comp_estimated_power_MW"] = PRC_2nd_stage_comp_estimated_power

#         # 3rd stage compressor power
#         PRC_3rd_stage_comp_estimated_power =[]
#         # Step 2: Get inlet enthalpy and entropy
#         for i in range(len(df)):
#             h1 = PropsSI('H', 'T',df["PRC_3RD_STAGE_Suction_TEMP"].iloc[i] + 273.15 , 'P', df["PRC_3RD_STAGE_Suction_PRESSURE"].iloc[i] * 1000+ 1e5, 'Propylene')  # J/kg
#             s1 = PropsSI('S', 'T',df["PRC_3RD_STAGE_Suction_TEMP"].iloc[i] + 273.15 , 'P', df["PRC_3RD_STAGE_Suction_PRESSURE"].iloc[i] * 1000+ 1e5, 'Propylene')  # J/kg.K
#             #Get isentropic outlet enthalpy (h2s at P2, s1)
#             T2s = PropsSI('T', 'P', df["PRC_3RD_STAGE_Discharge_PRESSURE"].iloc[i]* 1000 + 1e5, 'S', s1, 'Propylene')  # isentropic outlet temp
#             h2s = PropsSI('H', 'P', df["PRC_3RD_STAGE_Discharge_PRESSURE"].iloc[i]* 1000+ 1e5, 'S', s1, 'Propylene')  # J/kg
#             h2 = h1 + (h2s - h1) / eta
#             power = ((df["PRC_3RD_STAGE_Suction_FLOW"].iloc[i]* 1000)/3600) * (h2 - h1)/1e6  # MW
#             PRC_3rd_stage_comp_estimated_power.append(power)
            
#         df["PRC_3rd_stage_comp_estimated_power_MW"] = PRC_3rd_stage_comp_estimated_power

#         df["PRC_Total_estimated_power_MW"] = df["PRC_1st_stage_comp_estimated_power_MW"]+df["PRC_2nd_stage_comp_estimated_power_MW"]+df["PRC_3rd_stage_comp_estimated_power_MW"]

#         return df
    
#     selected_row_updated = PRC_section_power(selected_row_updated)
    
#     def PRC_turbine_extraction_steam_flow_prediction (df):
#         PRC_turbine_current_steam_enthalpy_KJ_Kg = []
#         PRC_turbine_current_steam_entropy_KJ_KgK =[]
#         PRC_turbine_current_outlet_ethalpy_KJ_Kg =[]
#         PRC_turbine_current_outlet_isentropic_ethalpy_KJ_Kg =[]
#         PRC_turbine_current_power_gen_extraction_MW = []
#         PRC_turbine_current_power_gen_exhaust_MW =[]
#         PRC_turbine_current_Turbine_power_MW_based_on_EE = []
#         PRC_turbine_current_Turbine_power_MW_based_on_steam_flow = []
#         PRC_turbine_current_Specific_steam_consumption_MT_MW =[]
#         #turbine_efficiency =[]
        
#         for i in range(len(df)):
#             Steam_flow_TPH = df['PRC_turbine_steam_flow'].iloc[i]
#             Condensate_flow_TPH = df['PRC_turbine_condensate_flow'].iloc[i]
#             Extraction_flow_TPH = df['PRC_turbine_Extraction_flow'].iloc[i]
            
#             Steam_flow_Kg_hr       = Steam_flow_TPH *1000
#             Extraction_flow_Kg_hr  = Extraction_flow_TPH *1000
#             Condensate_flow_Kg_hr  = Condensate_flow_TPH *1000
        
#             # Steam Inlet conditions
#             P_steam = df['PRC_turbine_Steam_pressure'].iloc[i]*1000   # Pa
#             T_steam = df['PRC_turbine_Steam_Temp'].iloc[i] +273.15   # K
#             T_sat_steam = PropsSI('T', 'P', P_steam, 'Q', 1, 'Water') - 273.15 # degC
        
#             # Extraction pressure
#             Pe = df['PRC_turbine_Extraction_Pressure'].iloc[i]*1000      # Pa 
#             T_sat_extraction = PropsSI('T', 'P', Pe, 'Q', 1, 'Water') # K
        
#             # Condenser pressure
#             Pc = df['PRC_turbine_Condensate_Pressure'].iloc[i]*1000
#             Tc_actual = df['PRC_turbine_Condensate_Temperature'].iloc[i] +273.15  # K (actual exhaust steam temp)
#             T_sat_condensate = PropsSI('T', 'P', Pc, 'Q', 0, 'Water') # degC
            
#             # Steam (inlet) Enthalpy calculation 
#             h_steam = PropsSI('H', 'P', P_steam, 'T', T_steam,'Water')/1000   # kJ/kg
#             s_steam = PropsSI('S', 'P', P_steam, 'T', T_steam, 'Water')/1000  # KJ/kg·K
            
#             # Actual outlet enthalpies
#             # Actual outlet enthalpies
#             # he = PropsSI('H', 'P', Pe, 'T', Te_actual, 'Water')/1000  # Extracted steam (actual)
#             he = PropsSI('H', 'P', Pe, 'T', T_sat_extraction + 0.01, 'Water')/1000  # Extracted steam (actual)
#             #hc = PropsSI('H', 'P', Pc, 'T', Tc_actual, 'Water')/1000  # Condenser outlet (actual)
#             hc_liquid = PropsSI('H', 'P', Pc, 'T', T_sat_condensate - 0.01, 'Water')/1000  # Condenser outlet (actual)
#             dryness_fraction = 0.92
#             hc_vapor = PropsSI('H', 'P', Pc, 'T', T_sat_condensate + 0.01, 'Water')/1000  # Condenser outlet (actual)
        
#             hc = hc_liquid + hc_vapor*dryness_fraction
        
#             Net_heat_release = Steam_flow_Kg_hr*h_steam -Extraction_flow_Kg_hr*he - Condensate_flow_Kg_hr*hc
#             power_gen_extraction = Extraction_flow_Kg_hr*(h_steam-he)/3600/1000
#             power_gen_exhaust = Condensate_flow_Kg_hr*(h_steam-hc)/3600/1000
#             Turbine_power_MW_EE = power_gen_extraction + power_gen_exhaust
#             Specific_steam_consumption = Steam_flow_TPH/(Turbine_power_MW_EE) # MT/MW
        
#             def isentropic_enthalpy(P_target, s_in):
#                 # Keep everything in J/kg·K
#                 s_f = PropsSI("S", "P", P_target, "Q", 0, "Water")/1000
#                 s_g = PropsSI("S", "P", P_target, "Q", 1, "Water")/1000
            
#                 if s_f < s_in < s_g:
#                     x = (s_in - s_f) / (s_g - s_f)
#                     h_f = PropsSI("H", "P", P_target, "Q", 0, "Water")
#                     h_g = PropsSI("H", "P", P_target, "Q", 1, "Water")
#                     h_iso = h_f + x * (h_g - h_f)
#                 else:
#                     h_iso = PropsSI("H", "P", P_target, "S", s_in, "Water")
            
#                 return h_iso / 1000  # Convert to kJ/kg
        
        
#             # Isentropic outlet enthalpies
#             he_s = isentropic_enthalpy(Pe, s_steam)
#             hc_s = isentropic_enthalpy(Pc, s_steam)
            
#             # Mass-weighted outlet enthalpies
#             h2_actual = (Extraction_flow_Kg_hr * he + Condensate_flow_Kg_hr * hc) / Steam_flow_Kg_hr
#             h2s_ideal = (Extraction_flow_Kg_hr  * he_s + Condensate_flow_Kg_hr * hc_s) / Steam_flow_Kg_hr
            
#             # Turbine isentropic efficiency
#             efficiency = (h_steam - h2_actual) / (h_steam - h2s_ideal)*100
            
#             turbine_power_MW_SF = (h_steam - h2_actual) * (Steam_flow_Kg_hr / (3600*1000))  # Convert kg/hr to kg/s
            
#             PRC_turbine_current_steam_enthalpy_KJ_Kg.append(h_steam)
#             PRC_turbine_current_steam_entropy_KJ_KgK.append(s_steam)
#             PRC_turbine_current_outlet_ethalpy_KJ_Kg.append(h2_actual)
#             PRC_turbine_current_outlet_isentropic_ethalpy_KJ_Kg.append(h2s_ideal)
#             PRC_turbine_current_power_gen_extraction_MW.append(power_gen_extraction)
#             PRC_turbine_current_power_gen_exhaust_MW.append(power_gen_exhaust)
#             PRC_turbine_current_Turbine_power_MW_based_on_EE.append(Turbine_power_MW_EE)
#             PRC_turbine_current_Turbine_power_MW_based_on_steam_flow.append(turbine_power_MW_SF)
#             PRC_turbine_current_Specific_steam_consumption_MT_MW.append(Specific_steam_consumption)
#             #turbine_efficiency.append(efficiency)
            
#         df["PRC_turbine_current_steam_enthalpy_KJ_Kg"] = PRC_turbine_current_steam_enthalpy_KJ_Kg
#         df["PRC_turbine_current_steam_entropy_KJ_KgK"] = PRC_turbine_current_steam_entropy_KJ_KgK
#         df["PRC_turbine_current_outlet_ethalpy_KJ_Kg"] = PRC_turbine_current_outlet_ethalpy_KJ_Kg
#         df["PRC_turbine_current_outlet_isentropic_ethalpy_KJ_Kg"] = PRC_turbine_current_outlet_isentropic_ethalpy_KJ_Kg
#         df["PRC_turbine_current_power_gen_extraction_MW"] = PRC_turbine_current_power_gen_extraction_MW
#         df["PRC_turbine_current_power_gen_exhaust_MW"] = PRC_turbine_current_power_gen_exhaust_MW
#         df["PRC_turbine_current_Turbine_power_MW_based_on_EE"] = PRC_turbine_current_Turbine_power_MW_based_on_EE
#         df["PRC_turbine_current_Turbine_power_MW_based_on_steam_flow"] = PRC_turbine_current_Turbine_power_MW_based_on_steam_flow
#         df["PRC_turbine_current_Specific_steam_consumption_MT_MW"] = PRC_turbine_current_Specific_steam_consumption_MT_MW
# #df["turbine_efficiency"] = turbine_efficiency
    
#         PRC_turbine_optimized_extraction = []
#         PRC_turbine_calculated_steam_flow = []
#         PRC_turbine_matched_power_EE = []
#         PRC_turbine_matched_power_SF = []
#         PRC_turbine_matched_h2_actual = []

#         def match_actual_power(row):
#             try:
#                 # Steam inlet enthalpy
#                 P_steam = row["PRC_turbine_Steam_pressure"] * 1000  # Pa
#                 T_steam = row["PRC_turbine_Steam_Temp"] + 273.15    # K
#                 h_steam = PropsSI("H", "P", P_steam, "T", T_steam, "Water") / 1000  # kJ/kg
             
#                 # Actual extracted steam enthalpy (he)
#                 Pe = row["PRC_turbine_Extraction_Pressure"] * 1000  # Pa
#                 # Te_actual = row["Extraction Temperature"] + 273.15  # K
#                 T_sat_extraction = PropsSI('T', 'P', Pe, 'Q', 1, 'Water') # K
#                 he = PropsSI('H', 'P', Pe, 'T', T_sat_extraction + 0.01, 'Water')/1000  # Extracted steam (actual)
                
#                 # Actual condenser steam enthalpy (hc)
#                 Pc = row["PRC_turbine_Condensate_Pressure"] * 1000  # Pa
#                 # Tc_actual = row["Condensate Temperature"] + 273.15  # K
#                 T_sat_condensate = PropsSI('T', 'P', Pc, 'Q', 0, 'Water') # degC
#                 hc_liquid = PropsSI('H', 'P', Pc, 'T', T_sat_condensate - 0.01, 'Water')/1000  # Condenser outlet (actual)
#                 dryness_fraction = 0.92
#                 hc_vapor = PropsSI('H', 'P', Pc, 'T', T_sat_condensate + 0.01, 'Water')/1000  # Condenser outlet (actual)
            
#                 hc = hc_liquid + hc_vapor*dryness_fraction
            
#                 condensate_flow_TPH = row["PRC_turbine_condensate_flow"]
#                 condensate_flow_Kg_hr = condensate_flow_TPH * 1000
#                 actual_power = row["PRC_Total_estimated_power_MW"]
            
#                 def objective(extraction_flow_TPH):
#                     extraction_flow_Kg_hr = extraction_flow_TPH * 1000
#                     steam_flow_Kg_hr = extraction_flow_Kg_hr + condensate_flow_Kg_hr
            
#                     power = ((extraction_flow_Kg_hr * (h_steam - he)) + 
#                              (condensate_flow_Kg_hr * (h_steam - hc))) / 3600 / 1000
#                     return (power - actual_power) ** 2
            
#                 result = minimize_scalar(objective, bounds=(10, 350), method='bounded')
            
#                 if result.success:
#                     ef_opt = result.x
#                     ef_Kg_hr = ef_opt * 1000
#                     sf_opt = ef_opt + condensate_flow_TPH
#                     sf_Kg_hr = sf_opt * 1000
#                     # Matched power via energy balance
#                     power_matched_EE = ((ef_Kg_hr * (h_steam - he)) + (condensate_flow_Kg_hr * (h_steam - hc))) / 3600 / 1000
    
#                     # Mass-weighted outlet enthalpy
#                     h2_actual = (ef_Kg_hr * he + condensate_flow_Kg_hr * hc) / sf_Kg_hr
    
#                     # Power via inlet/outlet enthalpy and total flow
#                     power_matched_SF = (h_steam - h2_actual) * (sf_Kg_hr / 3600 / 1000)
    
#                     return ef_opt, sf_opt, power_matched_EE, power_matched_SF, h2_actual
#                 else:
#                     return (row["PRC_turbine_Extraction_flow"], row["PRC_turbine_steam_flow"],
#                             row["PRC_turbine_current_Turbine_power_MW_based_on_EE"], row["PRC_turbine_current_Turbine_power_MW_based_on_steam_flow"],
#                             None)
#             except Exception as e:
#                 print(f"Error at index {row.name}: {e}")
#                 return (row["PRC_turbine_Extraction_flow"], row["PRC_turbine_steam_flow"],
#                         row["PRC_turbine_current_Turbine_power_MW_based_on_EE"], row["PRC_turbine_current_Turbine_power_MW_based_on_steam_flow"],
#                         None)
            
#         # Loop and apply
#         for _, row in df.iterrows():
#             ef, sf, power_EE, power_SF, h2 = match_actual_power(row)
#             PRC_turbine_optimized_extraction.append(ef)
#             PRC_turbine_calculated_steam_flow.append(sf)
#             PRC_turbine_matched_power_EE.append(power_EE)
#             PRC_turbine_matched_power_SF.append(power_SF)
#             PRC_turbine_matched_h2_actual.append(h2)
    
#         # Save to DataFrame
#         df["PRC_turbine_Optimized_Extraction_flow_TPH"] = PRC_turbine_optimized_extraction
#         df["PRC_turbine_Calculated_Steam_flow_TPH"] = PRC_turbine_calculated_steam_flow
#         df["PRC_turbine_Matched_Turbine_power_MW_EE"] = PRC_turbine_matched_power_EE
#         df["PRC_turbine_Matched_Turbine_power_MW_SF"] = PRC_turbine_matched_power_SF
#         df["PRC_turbine_Matched_h2_actual_KJ_Kg"] = PRC_turbine_matched_h2_actual
#         df["Power_Error"] = (
#             df["PRC_turbine_Matched_Turbine_power_MW_EE"] -
#             df["PRC_Total_estimated_power_MW"]
#         )
#         df["Power_EE_vs_SF_Diff"] = (
#             df["PRC_turbine_Matched_Turbine_power_MW_EE"] -
#             df["PRC_turbine_Matched_Turbine_power_MW_SF"]
#         )
#         df["Devaiation in steam flow (Simulated-actual)"] = df["PRC_turbine_Calculated_Steam_flow_TPH"]- df["PRC_turbine_steam_flow"]
#         df["Devaiation in extraction (Simulated-actual)"] = df["PRC_turbine_Optimized_Extraction_flow_TPH"]- df["PRC_turbine_Extraction_flow"]
#         df["Specific_steam_consumption_MT_MW_updated"] = df["PRC_turbine_Calculated_Steam_flow_TPH"] / df["PRC_Total_estimated_power_MW"]

#         return df
    
#     selected_row_updated = PRC_turbine_extraction_steam_flow_prediction (selected_row_updated)
    
#     # ERC ERC_2nd_stage_drum_Overhead_Flow prediction
#     mask = (selected_row_updated['ERC_turbine_steam_flow'] < constraints_df[constraints_df["Parameter"]=='ERC_turbine_steam_flow']["user input value"].values[0]) & (selected_row_updated['ERC_turbine_Speed'] < constraints_df[constraints_df["Parameter"]=="ERC_turbine_Speed"]["user input value"].values[0])
#     selected_row_updated.loc[mask, 'ERC_turbine_Speed'] =constraints_df[constraints_df["Parameter"]=="ERC_turbine_Speed"]["Max vlaue"].values[0] 
    
#     #ERC_turbine_Speed user based input
#     y_col = "ERC_turbine_Speed"
#     selected_row_updated = update_parameter_from_user_input(
#         y_col=y_col,
#         user_input_df=user_input_df,
#         selected_row_updated=selected_row_updated
#     )
    
#     y_col = "ERC_2nd_stage_drum_Overhead_Flow"
#     selected_row_updated = predict_and_update_with_kalman(
#     y_col=y_col,
#     selected_row_updated=selected_row_updated,
#     config_df_model_details=config_df_model_details
#     )

#     # KT1701 steam flow prediction
#     y_col = "ERC_turbine_steam_flow"
#     selected_row_updated = predict_and_update_with_kalman(
#     y_col=y_col,
#     selected_row_updated=selected_row_updated,
#     config_df_model_details=config_df_model_details
#     )
    
#     # ERC power prediction through Steam flow
#     y_col = "ERC_power"
#     selected_row_updated = predict_and_update_with_kalman(
#     y_col=y_col,
#     selected_row_updated=selected_row_updated,
#     config_df_model_details=config_df_model_details
#     )
    
#     #ERC first stage suction flow prediction
#     y_col = "ERC_1ST_STAGE_Suction_FLOW"
#     selected_row_updated = predict_and_update_with_kalman(
#     y_col=y_col,
#     selected_row_updated=selected_row_updated,
#     config_df_model_details=config_df_model_details
#     )

#     # ERC first stage suction pressure prediction
#     y_col = "ERC_1ST_STAGE_Suction_PRESSURE"
#     selected_row_updated = predict_and_update_with_kalman(
#     y_col=y_col,
#     selected_row_updated=selected_row_updated,
#     config_df_model_details=config_df_model_details
#     )
    
#     #ERC_1ST_STAGE_Suction_PRESSURE user based input
#     y_col = "ERC_1ST_STAGE_Suction_PRESSURE"
#     selected_row_updated = update_parameter_from_user_input(
#         y_col=y_col,
#         user_input_df=user_input_df,
#         selected_row_updated=selected_row_updated
#     )

#     selected_row_updated["Total_Power_(KW)"]= selected_row_updated["CGC_Power_KW"] + selected_row_updated["PRC_Total_estimated_power_MW"]*1000 + selected_row_updated["ERC_power"]
#     selected_row_updated["Total_required_steam_flow_(TPH)"] = selected_row_updated["CGC_Turbine_HP_Steam_flow"] + selected_row_updated["PRC_turbine_Calculated_Steam_flow_TPH"] + selected_row_updated["ERC_turbine_steam_flow"]
    
#     # Ethylene loss to fuel prediction
#     y_col = "TOTAL_ETHYLENE_LOSS_to_fuel"
#     selected_row_updated = predict_and_update_with_kalman(
#     y_col=y_col,
#     selected_row_updated=selected_row_updated,
#     config_df_model_details=config_df_model_details
#     )
    
#     # Ethylene product flow prediction
#     y_col = "Ethylene_product_flow"
#     selected_row_updated = predict_and_update_with_kalman(
#     y_col=y_col,
#     selected_row_updated=selected_row_updated,
#     config_df_model_details=config_df_model_details
#     )
    
#     Actual_vs_estimated = pd.concat([selected_row, selected_row_updated], axis=0)
#     Actual_vs_estimated.index = ["actual", "estimated"]
    
#     def color_diff(val):
#         color = 'green' if val > 0 else 'red' if val < 0 else ''
#         return f'background-color: {color}' if color else ''
    
#     diff = Actual_vs_estimated.loc['estimated'] - Actual_vs_estimated.loc['actual']
#     Actual_vs_estimated["Timestamp"] = user_time
#     styled = Actual_vs_estimated.style.apply(lambda _: diff.map(color_diff), axis=1)
#     styled.to_excel(os.path.join(RESULTS_DIR, "Actual_vs_estimated what if.xlsx"), engine='openpyxl')



