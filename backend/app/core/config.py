"""
backend/app/core/config.py
============================
Backend-specific settings (CORS origins) that have no equivalent in the
Streamlit app. Paths/thresholds/defaults live in config.settings instead.
"""
from __future__ import annotations

# Vite's default dev server port.
CORS_ORIGINS: list[str] = ["http://localhost:5173"]
