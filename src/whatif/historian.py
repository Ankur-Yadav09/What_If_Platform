"""
src/whatif/historian.py
=========================
Loads and cleans the What-If module's historian file
(Results/Raw_data_plus_simulated_data.xlsx), folding together the original
Scripts/whatif_runner.py raw loader and Scripts/Whatif_streamlit_dashboard.py's
separate get_cached_process_data() cleaning step into one function.
"""
from __future__ import annotations

import pandas as pd


def load_process_data(path: str) -> pd.DataFrame:
    """Reads the historian workbook, forces a clean sorted DatetimeIndex on
    'Timestamp', and drops fully-empty columns."""
    df = pd.read_excel(path)
    df.set_index("Timestamp", inplace=True)

    df.index = pd.to_datetime(df.index, errors="coerce")
    df = df[df.index.notna()].sort_index()
    df = df.dropna(axis=1, how="all")
    if df.empty:
        raise RuntimeError("No rows with valid timestamps found in historian data.")
    return df
