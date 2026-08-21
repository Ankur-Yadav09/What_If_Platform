"""
src/whatif/plants/__init__.py
================================
Plugin loader for plant-specific physics/KPI extensions (see
yanpet_olf1_formulas.py for the contract). Fixed to YANPET_OLF1 for now —
per the migration plan's single-plant scope decision, this repo doesn't
implement the multi-plant PLANT_NAME/dynamic-import-path machinery the
reference Streamlit scripts have; the only thing a future multi-plant phase
would need to change is this one function.
"""
from __future__ import annotations

import logging
from types import ModuleType

logger = logging.getLogger(__name__)


def load_plant_formulas() -> ModuleType | None:
    """Returns the yanpet_olf1_formulas plugin module, or None (logged) if
    it's missing/broken, so the engine degrades to pure-Kalman/no-op-hook
    behavior rather than crashing."""
    try:
        from src.whatif.plants import yanpet_olf1_formulas
        return yanpet_olf1_formulas
    except Exception:
        logger.exception("Failed to load the YANPET_OLF1 physics plugin; continuing without it.")
        return None
