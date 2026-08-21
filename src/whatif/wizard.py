"""
src/whatif/wizard.py
======================
Ported, Streamlit-free version of the Plant Configuration Wizard and PI
tag-dictionary helpers from Scripts/Whatif_streamlit_dashboard.py.

Includes an actual implementation of infer_section(), which the original
file calls from normalize_pi_df() but never defines anywhere in the repo —
a latent NameError on any blank-Section row. The real Config_file.xlsx has
no blank-Section rows today, but a re-generated/hand-edited mapping could.
"""
from __future__ import annotations

import re

import pandas as pd

from src.whatif.config_io import PI_COLUMNS

_ORDINAL_TO_INT = {"1ST": 1, "2ND": 2, "3RD": 3, "4TH": 4, "5TH": 5, "6TH": 6, "7TH": 7, "8TH": 8}
_STAGE_RE = re.compile(r"(1ST|2ND|3RD|[4-8]TH)[_\s]*(?:STG|STAGE)", re.IGNORECASE)
_FURNACE_RE = re.compile(r"_F(\d{1,2})(?:_|$)")
_FURNACE_RANGE_RE = re.compile(r"_F(\d{1,2})_(\d{1,2})(?:_|$)")

_SECTION_KEYWORDS = [
    ("CGC", ("cgc", "cracked gas")),
    ("PRC", ("prc", "propylene")),
    ("ERC", ("erc", "ethylene refrig")),
    ("Furnace", ("furnace", "coil", "cot", "cip")),
    ("Quench", ("quench",)),
    ("Cold", ("cold", "demethaniser", "demethanizer", "deethaniser", "deethanizer")),
]


def infer_section(description: str) -> str:
    """Best-effort section inference for a tag with a blank Section, based on
    keyword matches in its Generalized Description. Falls back to
    'Unclassified' rather than raising, unlike the original (undefined)
    infer_section reference."""
    text = str(description or "").lower()
    for section, keywords in _SECTION_KEYWORDS:
        if any(kw in text for kw in keywords):
            return section
    return "Unclassified"


def extract_stage_number(tag: str) -> int | None:
    """'CGC_5TH_STG_DISCH_PRES' -> 5 ; 'PRC_1ST_STAGE_Suction_FLOW' -> 1"""
    if not isinstance(tag, str):
        return None
    m = _STAGE_RE.search(tag.upper())
    return _ORDINAL_TO_INT.get(m.group(1).upper()) if m else None


def extract_furnace_numbers(tag: str) -> set:
    """Single ('..._F7' -> {7}) and range ('..._F6_12' -> {6..12}) furnace tags."""
    if not isinstance(tag, str):
        return set()
    rng = _FURNACE_RANGE_RE.search(tag)
    if rng:
        lo, hi = int(rng.group(1)), int(rng.group(2))
        if lo <= hi <= 20:
            return set(range(lo, hi + 1))
    single = _FURNACE_RE.search(tag)
    if single:
        return {int(single.group(1))}
    return set()


def normalize_pi_df(pi_df: pd.DataFrame) -> pd.DataFrame:
    """Trims text, title-cases Section, infers blank sections, drops blank tags."""
    if pi_df is None or pi_df.empty:
        return pd.DataFrame(columns=PI_COLUMNS)
    out = pi_df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    for col in PI_COLUMNS:
        if col not in out.columns:
            out[col] = None
    out["Pi_tags"] = out["Pi_tags"].astype(str).str.strip()
    out["Generalized Description"] = out["Generalized Description"].astype(str).str.strip()
    out["Section"] = (
        out["Section"].astype(str).str.strip().str.title()
        .replace({"Nan": "", "None": "", "Cgc": "CGC", "Prc": "PRC", "Erc": "ERC"})
    )
    blank = out["Section"] == ""
    if blank.any():
        out.loc[blank, "Section"] = out.loc[blank, "Generalized Description"].map(infer_section)
    out = out[(out["Pi_tags"] != "") & (out["Pi_tags"].str.lower() != "nan")]
    return out.reset_index(drop=True)


def segregate_tags_by_section(pi_df: pd.DataFrame) -> dict:
    if pi_df is None or pi_df.empty or "Section" not in pi_df.columns:
        return {}
    return {sec: grp.reset_index(drop=True) for sec, grp in pi_df.groupby("Section", dropna=False)}


def available_stages(pi_df: pd.DataFrame, section: str) -> list:
    if pi_df is None or pi_df.empty:
        return []
    sub = pi_df[pi_df["Section"].str.upper() == section.upper()]
    stages = {extract_stage_number(t) for t in sub["Generalized Description"]}
    return sorted(s for s in stages if s is not None)


def available_furnaces(pi_df: pd.DataFrame) -> list:
    if pi_df is None or pi_df.empty:
        return []
    sub = pi_df[pi_df["Section"].str.upper() == "FURNACE"]
    nums: set = set()
    for t in sub["Generalized Description"]:
        nums |= extract_furnace_numbers(t)
    return sorted(nums)


def generate_pi_mapping(
    pi_df: pd.DataFrame,
    cgc_stages: list,
    prc_stages: list,
    erc_stages: list,
    furnaces: list,
) -> pd.DataFrame:
    """Filters the PI dictionary down to the tags matching a plant line-up:
    stage-numbered tags kept only for selected stages (stage-agnostic tags
    always kept); furnace-numbered tags kept only for selected furnaces
    (furnace-agnostic tags always kept); all other sections kept in full."""
    if pi_df is None or pi_df.empty:
        return pd.DataFrame(columns=PI_COLUMNS)

    stage_sel = {"CGC": set(cgc_stages or []), "PRC": set(prc_stages or []), "ERC": set(erc_stages or [])}
    furnace_sel = set(furnaces or [])

    def _keep(row) -> bool:
        section = str(row.get("Section", "")).upper()
        tag = str(row.get("Generalized Description", ""))
        if section in stage_sel:
            stg = extract_stage_number(tag)
            return True if stg is None else stg in stage_sel[section]
        if section == "FURNACE":
            f_nums = extract_furnace_numbers(tag)
            return True if not f_nums else bool(f_nums & furnace_sel)
        return True

    mask = pi_df.apply(_keep, axis=1)
    return pi_df[mask].reset_index(drop=True)
