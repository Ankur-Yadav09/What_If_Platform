// KPI_TAGS/VALIDATION_TAGS used to be hardcoded here (ported verbatim from
// Scripts/Whatif_streamlit_dashboard.py). Both are now derived server-side
// from the live config — see src/whatif/kpi.py::derive_kpi_tags — and the
// backend's response is rendered as-is (KpiCardsRow, ValidationFiltersPanel),
// with no client-side tag whitelist.

export const SECTION_OPTIONS = ['', 'CGC', 'PRC', 'ERC', 'Furnace', 'Quench', 'Cold']
