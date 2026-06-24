"""
config.py
=========
Central configuration for the DVVNL / DISCOM AT&C Loss Management Review Dashboard.

Holds:
  - File paths
  - Month / Fiscal-Year (FY) parsing helpers (DISCOM fiscal year runs April -> March)
  - Category definitions (OVERALL / GOVT / NON_GOVT)
  - KPI metadata (display names, units, "higher is better" direction, formula text)
  - Colour palette / Plotly template used across the app

IMPORTANT DATA-MODEL ASSUMPTION (read this before touching kpi_engine.py)
---------------------------------------------------------------------------
The source CSV only carries "Input Energy (MU)" at the OVERALL (division)
level. UPPCL/DVVNL does not meter "Input Energy" separately for Government
vs Non-Government consumers -- input energy is a feeder/transformer-level
technical quantity, not a billing-category quantity.

Per the agreed convention for this dashboard, GOVT and NON_GOVT therefore
borrow the OVERALL division's figures as follows:
  * Input Energy, Line Loss % and Billing Efficiency % for GOVT/NON_GOVT are
    set equal to the OVERALL division's own values (the shared technical
    loss rate cannot be split by consumer category, so the same figure is
    shown across all three category views).
  * AT&C Loss (GOVT/NON_GOVT) = 100 - (OVERALL Billing Efficiency x
    category's OWN Collection Efficiency / 100). This was verified
    numerically against the source file's own "GOVERNMENT ATC Loss" /
    "NON GOVERNMENT ATC Loss" columns and matches DVVNL's own published
    methodology to within rounding.
  * Through Rate (GOVT/NON_GOVT) = category's OWN Realisation / OVERALL
    Input Energy -- this DOES differentiate meaningfully across categories
    because Realisation is genuinely category-specific.
  * Collection Efficiency and ABR are fully category-specific throughout
    because Assessment, Realisation and Unit Sold are all split by category
    in the source file.

This is explained again, with a live worked example, in the app's
"Methodology & Data Notes" tab so reviewers are never misled.
"""

from pathlib import Path
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR
DEFAULT_CSV_PATH = DATA_DIR / "ATC_MONTHLY_ALL_UNITS.csv"

APP_TITLE = "DVVNL Commercial Review Dashboard"
APP_ICON = "⚡"

# ---------------------------------------------------------------------------
# Hierarchy
# ---------------------------------------------------------------------------
HIERARCHY_LEVELS = ["DISCOM", "ZONE", "CIRCLE", "DIVISION"]

# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
CATEGORIES = ["OVERALL", "GOVT", "NON_GOVT"]
CATEGORY_LABELS = {
    "OVERALL": "Overall",
    "GOVT": "Government",
    "NON_GOVT": "Non-Government",
}

# ---------------------------------------------------------------------------
# Fiscal-year month helpers  (Indian power-utility FY: April -> March)
# ---------------------------------------------------------------------------
MONTH_NAME_TO_NUM = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12,
}

# Position of each calendar month within the Apr->Mar fiscal year (April = 1 ... March = 12)
FY_MONTH_POSITION = {
    4: 1, 5: 2, 6: 3, 7: 4, 8: 5, 9: 6,
    10: 7, 11: 8, 12: 9, 1: 10, 2: 11, 3: 12,
}

FY_MONTH_ORDER_NAMES = [
    "April", "May", "June", "July", "August", "September",
    "October", "November", "December", "January", "February", "March",
]


def parse_month_label(label: str):
    """
    Parse a raw CSV month label such as 'April-26' into structured fields.

    Returns a dict with:
        month_name   : 'April'
        month_num    : 4
        cal_year     : 2026          (full 4-digit calendar year)
        month_date   : pandas.Timestamp for the 1st of that month
        fy_label     : '2025-26'     (fiscal year string, Apr Y -> Mar Y+1)
        fy_month_pos : 1..12 (April=1 ... March=12), used for progressive/cumulative logic
    """
    name, yy = label.split("-")
    name = name.strip()
    yy = int(yy.strip())
    cal_year = 2000 + yy
    month_num = MONTH_NAME_TO_NUM[name]
    month_date = pd.Timestamp(year=cal_year, month=month_num, day=1)

    if month_num >= 4:  # April..December -> first year of the FY
        fy_start = cal_year
    else:  # Jan..March -> second year of the FY
        fy_start = cal_year - 1
    fy_label = f"{fy_start}-{str(fy_start + 1)[-2:]}"
    fy_month_pos = FY_MONTH_POSITION[month_num]

    return {
        "month_name": name,
        "month_num": month_num,
        "cal_year": cal_year,
        "month_date": month_date,
        "fy_label": fy_label,
        "fy_month_pos": fy_month_pos,
    }


# ---------------------------------------------------------------------------
# KPI metadata  (used for chart titles, axis labels, "good direction" arrows etc.)
# ---------------------------------------------------------------------------
KPI_META = {
    "line_loss_pct": {
        "label": "Distribution Loss",
        "unit": "%",
        "lower_is_better": True,
        "formula": "((Input Energy - Unit Sold) / Input Energy) x 100",
        "category_scope": ["OVERALL", "GOVT", "NON_GOVT"],
        "shared_as_overall": True,  # GOVT/NON_GOVT carry the OVERALL division's own value
    },
    "billing_efficiency_pct": {
        "label": "Billing Efficiency",
        "unit": "%",
        "lower_is_better": False,
        "formula": "(Unit Sold / Input Energy) x 100",
        "category_scope": ["OVERALL", "GOVT", "NON_GOVT"],
        "shared_as_overall": True,  # GOVT/NON_GOVT carry the OVERALL division's own value
    },
    "collection_efficiency_pct": {
        "label": "Collection Efficiency",
        "unit": "%",
        "lower_is_better": False,
        "formula": "(Realisation / Assessment) x 100",
        "category_scope": ["OVERALL", "GOVT", "NON_GOVT"],
        "shared_as_overall": False,
    },
    "atc_loss_pct": {
        "label": "AT&C Loss",
        "unit": "%",
        "lower_is_better": True,
        "formula": "100 - (Billing Efficiency x Collection Efficiency / 100)",
        "category_scope": ["OVERALL", "GOVT", "NON_GOVT"],
        "shared_as_overall": False,
    },
    "through_rate": {
        "label": "Through Rate (Input basis)",
        "unit": "Rs/Unit",
        "lower_is_better": False,
        "formula": "Realisation (category) / Input Energy (OVERALL)",
        "category_scope": ["OVERALL", "GOVT", "NON_GOVT"],
        "shared_as_overall": False,  # category-specific Realisation makes this differentiate by category
    },
    "abr": {
        "label": "Average Billing Rate (ABR)",
        "unit": "Rs/Unit",
        "lower_is_better": False,
        "formula": "Assessment / Unit Sold",
        "category_scope": ["OVERALL", "GOVT", "NON_GOVT"],
        "shared_as_overall": False,
    },
}

KPI_OPTIONS = list(KPI_META.keys())
KPI_LABELS = {k: v["label"] for k, v in KPI_META.items()}

# ---------------------------------------------------------------------------
# Visual theme
# ---------------------------------------------------------------------------
PRIMARY_COLOR = "#0B5394"
ACCENT_COLOR = "#F4A300"
GOOD_COLOR = "#1E8E3E"
BAD_COLOR = "#D93025"
NEUTRAL_COLOR = "#5F6368"

PLOTLY_TEMPLATE = "plotly_white"

ZONE_COLOR_SEQUENCE = [
    "#0B5394", "#F4A300", "#1E8E3E", "#D93025", "#8E24AA",
    "#00838F", "#6D4C41", "#5F6368", "#C2185B", "#3949AB",
]
