"""
app.py
======
DVVNL AT&C Loss Management Review Dashboard.

Run with:
    streamlit run app.py

See README.md for setup instructions.
"""

from __future__ import annotations
import io
import duckdb
import pandas as pd
import streamlit as st

import config
from consolidated_report import render_consolidated_report_tab
import data_loader as dl
import kpi_engine as ke
import ranking as rk
import export_utils as eu
import ui_helpers as uh
from config import (
    CATEGORIES, CATEGORY_LABELS, KPI_META, KPI_OPTIONS, KPI_LABELS,
    APP_TITLE, APP_ICON, PRIMARY_COLOR,
)
from slab_analytics import render_slab_analytics_tab

st.set_page_config(page_title=APP_TITLE, page_icon=APP_ICON, layout="wide",
                    initial_sidebar_state="expanded",menu_items=None)

st.markdown("""
<style>
/* Hide Streamlit toolbar */
[data-testid="stToolbar"] {
    display: none !important;
}

/* Hide Deploy button */
.stDeployButton {
    display: none !important;
}

/* Hide top right decoration */
[data-testid="stDecoration"] {
    display: none !important;
}

/* Hide hamburger menu */
#MainMenu {
    visibility: hidden;
}

/* Hide footer */
footer {
    visibility: hidden;
}

/* Hide header */
header {
    visibility: hidden;
}
            
[data-testid="stToolbar"] {
    display:none;
}

header {
    display:none;
}

[data-testid="stDecoration"] {
    display:none;
}
            
.block-container {
    padding-top: 0rem !important;
}
            
/* Hide file uploader widget */
[data-testid="stFileUploader"] {
    display: none !important;
}

/* Hide expander containing uploader (optional) */
div[data-testid="stExpander"] {
    display: none !important;
}

div[data-testid="stMarkdownContainer"] h3 {

    background: white;

    color: #0B5394 !important;

    border-left: 8px solid #F4A300;

    padding: 10px 15px;

    border-radius: 8px;

    font-weight: 700;

    font-size: 1.2rem;

    box-shadow:
        0 2px 10px rgba(0,0,0,0.08);

    margin-top: 15px;
    margin-bottom: 10px;
}

 div[data-testid="stCaptionContainer"] p {

    background: linear-gradient(
        90deg,
        rgba(11,83,148,0.08),
        rgba(244,163,0,0.08)
    );

    color: #000000 !important;

    font-weight: 700 !important;

    font-size: 0.95rem !important;

    padding: 8px 12px;

    border-radius: 8px;

    border-left: 5px solid #F4A300;

    box-shadow:
        0 1px 4px rgba(0,0,0,0.08);

    margin-top: 6px;

    margin-bottom: 6px;
}

.stTabs [data-baseweb="tab-list"]{
    gap:6px;
}

.stTabs [data-baseweb="tab"]{

    background:#ffffff;

    border-radius:8px;

    border-left:4px solid #F4A300;

    color:#0B5394;

    font-weight:900;

    padding:12px 20px;
}

.stTabs [aria-selected="true"]{

    background:#0B5394 !important;

    color:white !important;

    border-left:6px solid #F4A300 !important;
}

                     
</style>
""", unsafe_allow_html=True)


st.markdown(f"""
<style>
    .block-container {{ padding-top: 0.1rem;padding-left:1rem;padding-right:1rem; background-color:#e5ede2;}}
    h1, h2, h3 {{ color: {PRIMARY_COLOR}; }}
    div[data-testid="stMetric"] {{
        background: #F7F9FC; border: 2px solid #E3E8EF; border-radius: 10px;
        padding: 10px 12px 6px 12px;
    }}
    div[data-testid="stMetricLabel"] {{ font-size: 0.80rem; color: #46505A; }}
    .stTabs [data-baseweb="tab"] {{ font-size: 0.95rem; padding: 8px 14px; }}
    .review-caption {{ color: #5F6368; font-size: 0.92rem; margin-bottom: 0.4rem; }}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Cached data loading (st.cache_data) and DuckDB connection (st.cache_resource)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Loading and reshaping ATC MONTHLY data...")
def load_long_data(file_bytes: bytes | None) -> pd.DataFrame:
    if file_bytes is not None:
        return dl.load_long_dataframe(io.BytesIO(file_bytes))
    return dl.load_long_dataframe()


@st.cache_resource
def get_duckdb_connection() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(database=":memory:")


# ---- thin caching wrappers around the DuckDB query layer (connection arg
# prefixed with "_" so Streamlit does not try to hash the unhashable
# DuckDBPyConnection object) ----
@st.cache_data(show_spinner=False)
def q_kpi_table(_con, level, category, period_type, month=None, upto_month_seq=None,
                 fy_label=None, zone=None, circle=None, division=None):
    return ke.kpi_table(_con, level, category, period_type, month=month,
                         upto_month_seq=upto_month_seq, fy_label=fy_label,
                         zone=zone, circle=circle, division=division)


@st.cache_data(show_spinner=False)
def q_trend_table(_con, level, category, zone=None, circle=None, division=None, fy_label=None):
    return ke.trend_table(_con, level, category, zone=zone, circle=circle,
                           division=division, fy_label=fy_label)


@st.cache_data(show_spinner=False)
def q_rank_table(_con, level, category, kpi, period_type, month=None, upto_month_seq=None,
                  fy_label=None, top_n=5, mode="worst", zone=None, circle=None):
    return rk.rank_table(_con, level, category, kpi, period_type, month=month,
                          upto_month_seq=upto_month_seq, fy_label=fy_label,
                          top_n=top_n, mode=mode, zone=zone, circle=circle)


@st.cache_data(show_spinner=False)
def q_mom_yoy(_con, level, category, month, compare="MoM", zone=None, circle=None):
    return rk.mom_yoy_table(_con, level, category, month, compare=compare, zone=zone, circle=circle)


@st.cache_data(show_spinner=False)
def q_explorer(_con, categories, months, zones, circles, divisions):
    frames = []
    for cat in categories:
        for m in months:
            frames.append(q_kpi_table(_con, "DIVISION", cat, "single", month=m))
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if df.empty:
        return df
    if zones:
        df = df[df["zone"].isin(zones)]
    if circles:
        df = df[df["circle"].isin(circles)]
    if divisions:
        df = df[df["division"].isin(divisions)]
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.title(f"{APP_ICON} Select Criteria")

with st.sidebar.expander("Data source", expanded=False):
    uploaded = st.file_uploader(
        "Replace the bundled CSV (optional)", type=["csv"],
        help="Defaults to data/ATC_MONTHLY_ALL_UNITS.csv bundled with this app. "
             "Upload a fresh monthly export with the same column layout to refresh.")

file_bytes = uploaded.getvalue() if uploaded is not None else None
long_df = load_long_data(file_bytes)
con = get_duckdb_connection()
con.register("atc_long", long_df)

month_lookup = dl.month_lookup_table(long_df)
month_options = month_lookup["month"].tolist()

st.sidebar.markdown("**Category**")
category = st.sidebar.radio(
    "Category", CATEGORIES, format_func=lambda c: CATEGORY_LABELS[c],
    label_visibility="collapsed", horizontal=True,
)

st.sidebar.markdown("**Period**")
period_mode = st.sidebar.radio(
    "Period mode", ["Monthly", "Progressive (Cumulative)"],
    label_visibility="collapsed",
)
selected_month = st.sidebar.selectbox("Month", month_options, index=len(month_options) - 1)

m_row = month_lookup[month_lookup["month"] == selected_month].iloc[0]
fy_label = m_row["fy_label"]
seq_index = int(m_row["seq_index"])

if period_mode == "Monthly":
    period_type = "single"
    period_kwargs = dict(period_type="single", month=selected_month)
else:
    period_type = "progressive"
    period_kwargs = dict(period_type="progressive", upto_month_seq=seq_index, fy_label=fy_label)

st.sidebar.markdown("**Top / Bottom N**")
top_n = st.sidebar.number_input("Top / Bottom N", min_value=3, max_value=25, value=5,
                                 label_visibility="collapsed")

st.sidebar.caption(uh.period_caption(period_type, selected_month, fy_label))
st.sidebar.divider()
st.sidebar.caption(
    f"Data Coverage (Include Torrent): **{month_options[0]} -> {month_options[-1]}**  \n"
    f"{long_df['zone'].nunique()-1} Zones | {long_df['circle'].nunique()-1} Circles | "
    f"{long_df['division'].nunique()-1} Divisions"
)

# previous single month (for MoM deltas on KPI cards), independent of progressive toggle
prev_month_row = month_lookup[month_lookup["seq_index"] == seq_index - 1]
prev_month = prev_month_row.iloc[0]["month"] if not prev_month_row.empty else None


def quick_export_buttons(df: pd.DataFrame, key_prefix: str, title: str):
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("Download CSV", eu.to_csv_bytes(df), file_name=f"{key_prefix}.csv",
                            mime="text/csv", key=f"{key_prefix}_csv", width='stretch')
    with c2:
        st.download_button("Download Excel", eu.to_excel_bytes(df, title[:31]),
                            file_name=f"{key_prefix}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"{key_prefix}_xlsx", width='stretch')

# ---------------------------------------------------------------------------
# KPI SLAB ENGINE
# ---------------------------------------------------------------------------

SLAB_CONFIG = {

    "atc_loss_pct": [
        (15, "<15%"),
        (20, "15-20%"),
        (25, "20-25%"),
        (30, "25-30%"),
        (35, "30-35%"),
        (40, "35-40%"),
        (999, ">40%")
    ],

    "line_loss_pct": [
        (10, "<10%"),
        (15, "10-15%"),
        (20, "15-20%"),
        (25, "20-25%"),
        (30, "25-30%"),
        (999, ">30%")
    ],

    "billing_efficiency_pct": [
        (70, "<70%"),
        (80, "70-80%"),
        (85, "80-85%"),
        (90, "85-90%"),
        (95, "90-95%"),
        (999, ">95%")
    ],

    "collection_efficiency_pct": [
        (70, "<70%"),
        (80, "70-80%"),
        (85, "80-85%"),
        (90, "85-90%"),
        (95, "90-95%"),
        (999, ">95%")
    ],

    "through_rate": [
        (3, "<3"),
        (4, "3-4"),
        (5, "4-5"),
        (6, "5-6"),
        (999, ">6")
    ],

    "abr": [
        (4, "<4"),
        (5, "4-5"),
        (6, "5-6"),
        (7, "6-7"),
        (999, ">7")
    ]
}


def get_kpi_slab(kpi, value):

    if pd.isna(value):
        return "NA"

    if kpi not in SLAB_CONFIG:
        return "NA"

    for upper, slab in SLAB_CONFIG[kpi]:

        if value <= upper:
            return slab

    return "NA"
# ---------------------------------------------------------------------------
def slab_summary_table(df, level_col, kpi, discom_value):

    if kpi in ["billing_efficiency_pct",
               "collection_efficiency_pct"]:

        slabs = [
            ("<70", df[kpi] < 70),
            ("70-80", (df[kpi] >= 70) & (df[kpi] < 80)),
            ("80-90", (df[kpi] >= 80) & (df[kpi] < 90)),
            (">90", df[kpi] >= 90),
            ("> Discom Avg", df[kpi] > discom_value)
        ]

    elif kpi in ["atc_loss_pct","line_loss_pct"]:

        slabs = [
            ("<10", df[kpi] < 10),
            ("10-20", (df[kpi] >= 10) & (df[kpi] < 20)),
            ("20-30", (df[kpi] >= 20) & (df[kpi] < 30)),
            ("30-40", (df[kpi] >= 30) & (df[kpi] < 40)),
            (">40", df[kpi] >= 40),
            ("< Discom Avg", df[kpi] < discom_value)
        ]

    else:

        q1 = df[kpi].quantile(.25)
        q2 = df[kpi].quantile(.50)
        q3 = df[kpi].quantile(.75)

        slabs = [
            ("Bottom 25%", df[kpi] <= q1),
            ("25-50%", (df[kpi] > q1) & (df[kpi] <= q2)),
            ("50-75%", (df[kpi] > q2) & (df[kpi] <= q3)),
            ("Top 25%", df[kpi] > q3),
            ("> Discom Avg", df[kpi] > discom_value)
        ]

    rows = []

    for slab_name, condition in slabs:

        units = df.loc[condition]

        rows.append({
            "Slab": slab_name,
            "Count": len(units),
            "Units": units
        })

    return rows
# Header
# ---------------------------------------------------------------------------
st.title(f"{APP_ICON} {APP_TITLE}")
st.markdown(
    f"<div class='review-caption'>DISCOM &rarr; Zone &rarr; Circle &rarr; Division | "
    f"Category: <b>{CATEGORY_LABELS[category]}</b> | {uh.period_caption(period_type, selected_month, fy_label)}</div>",
    unsafe_allow_html=True,
)

tabs = st.tabs([
    "🏢 DISCOM Overview", "🌐 Zone Review", "🏛️ Circle Review", "📍 Division Review",
    "🏆 Rankings", "📈 MoM / YoY", "📤 Data Explorer & Export","📊 KPI Analytics","🎯 Slab Analytics","Report",
])

# =============================================================================
# TAB 1 — DISCOM OVERVIEW
# =============================================================================
with tabs[0]:
    discom_row = q_kpi_table(con, "DISCOM", category, **period_kwargs).iloc[0]
    delta_row = None
    if period_type == "single" and prev_month is not None:
        delta_row = q_kpi_table(con, "DISCOM", category, "single", month=prev_month).iloc[0]

    st.subheader("DVVNL-wide KPIs")
    uh.kpi_card_row(discom_row, category, delta_row)



    # =========================================================================
    # KPI BAR CHARTS — Monthly (all months) or Progressive (current FY vs prior FY same span)
    # =========================================================================

    _BAR_KPIS = [
        ("atc_loss_pct",             "AT&C Loss (%)"),
        ("line_loss_pct",            "Line / Distribution Loss (%)"),
        ("billing_efficiency_pct",   "Billing Efficiency (%)"),
        ("collection_efficiency_pct","Collection Efficiency (%)"),
        ("through_rate",             "Through Rate (Rs/Unit)"),
        ("abr",                      "ABR (Rs/Unit)"),
    ]
    _BAR_LOWER_IS_BETTER = {
        "atc_loss_pct": True, "line_loss_pct": True,
        "billing_efficiency_pct": False, "collection_efficiency_pct": False,
        "through_rate": False, "abr": False,
    }
    _COL_GOOD   = "#1E8E3E"
    _COL_BAD    = "#D93025"
    _COL_CURR   = "#0B5394"
    _COL_PRIOR  = "#B0C4DE"

    if period_type == "single":
        # ---- Monthly mode: one bar per month, all months in dataset ----
        st.subheader("KPI Monthly Trend — Bar Charts (Apr 25 to May 26)")
        st.caption(f"DVVNL DISCOM-wide | Category: {CATEGORY_LABELS[category]} | "
                   f"Selected month **{selected_month}** highlighted.")

        _all_months_trend = q_trend_table(con, "DISCOM", category)
        _all_months_trend = _all_months_trend.sort_values("seq_index")

        _bar_chart_rows = [_BAR_KPIS[i:i+2] for i in range(0, 6, 2)]   # 2 charts per row, 3 rows
        _cols = st.columns(2)
        for _row_kpis in _bar_chart_rows:
            _cols = st.columns(2)
            for _col, (_kpi, _kpi_title) in zip(_cols, _row_kpis):
                with _col:
                    _df = _all_months_trend.dropna(subset=[_kpi]).copy()
                    if _df.empty:
                        st.info(f"No data: {_kpi_title}")
                        continue

                    # Colour: highlight selected month; red/green tint rest by direction
                    _lib = _BAR_LOWER_IS_BETTER[_kpi]
                    _colors = []
                    for _, _r in _df.iterrows():
                        if _r["month"] == selected_month:
                            _colors.append(_COL_CURR)
                        elif _lib:
                            _colors.append(_COL_BAD if _r[_kpi] > _df[_kpi].median() else _COL_GOOD)
                        else:
                            _colors.append(_COL_GOOD if _r[_kpi] >= _df[_kpi].median() else _COL_BAD)

                    import plotly.graph_objects as _go
                    _fig = _go.Figure(_go.Bar(
                        x=list(_df["month"]),
                        y=list(_df[_kpi].round(2)),
                        marker_color=_colors,
                        text=[f"{v:.1f}" for v in _df[_kpi]],
                        textposition="outside",
                        textfont=dict(
                                    size=14,
                                     family="Arial Black",
                                        color="#0A2036"
                                    ),
                        name=_kpi_title,
                    ))
                    _fig.update_layout(
                        title=dict(text=_kpi_title, font=dict(size=16)),
                        xaxis=dict(tickangle=-45, tickfont=dict( size=12,              # Increase font size
                                           # family="Arial Black", # Bold-looking font
                                             color="#1A1C1E")),
                        yaxis=dict(showgrid=True, gridcolor="#EBEBEB"),
                        height=320,
                        margin=dict(t=40, b=10, l=10, r=10),
                        plot_bgcolor="white",
                        showlegend=False,
                    )
                    _fig.add_hline(
                        y=float(_df[_kpi].mean()),
                        line_dash="dot", line_color="#888888",
                        annotation_text=f"Avg {_df[_kpi].mean():.1f}",
                        annotation_font_size=9,
                    )
                    st.plotly_chart(_fig, width='stretch',
                                    key=f"discom_bar_monthly_{_kpi}")

    else:
        # ---- Progressive mode: 2-bar comparison (current FY cumulative vs prior FY same span) ----
        st.subheader("KPI Progressive Comparison — Current FY vs Prior FY (Same Period)")

        # Current FY: fy_label + upto seq_index
        _cur_prog = q_kpi_table(con, "DISCOM", category,
                                 "progressive", upto_month_seq=seq_index, fy_label=fy_label)

        # Prior FY: same fy_month_pos ceiling, but one FY earlier
        _cur_fy_pos = int(m_row["fy_month_pos"])
        _prior_fy_rows = month_lookup[
            (month_lookup["fy_month_pos"] <= _cur_fy_pos) &
            (month_lookup["fy_label"] != fy_label)
        ]
        # pick the most recent prior FY that has at least 1 matching month
        _prior_fy_candidates = _prior_fy_rows["fy_label"].unique()

        if len(_prior_fy_candidates) == 0:
            st.info("No prior FY data available for progressive comparison.")
        else:
            _prior_fy_label = sorted(_prior_fy_candidates)[-1]          # most recent prior FY
            _prior_max_seq   = int(
                _prior_fy_rows[_prior_fy_rows["fy_label"] == _prior_fy_label]["seq_index"].max()
            )
            _prior_prog = q_kpi_table(con, "DISCOM", category,
                                       "progressive", upto_month_seq=_prior_max_seq,
                                       fy_label=_prior_fy_label)

            # Build period labels for axis
            _cur_start_month  = month_lookup[month_lookup["fy_label"] == fy_label]["month"].iloc[0]
            _prior_start_month = month_lookup[month_lookup["fy_label"] == _prior_fy_label]["month"].iloc[0]
            _prior_end_month   = month_lookup[month_lookup["seq_index"] == _prior_max_seq]["month"].iloc[0]
            _cur_label   = f"Current FY {fy_label}\n({_cur_start_month} → {selected_month})"
            _prior_label = f"Prior FY {_prior_fy_label}\n({_prior_start_month} → {_prior_end_month})"

            st.caption(
                f"Category: {CATEGORY_LABELS[category]} | "
                f"**{_cur_label.replace(chr(10),' ')}** vs **{_prior_label.replace(chr(10),' ')}**"
            )

            _bar_chart_rows2 = [_BAR_KPIS[:3], _BAR_KPIS[3:]]

            for _row_kpis in _bar_chart_rows2:
                _cols = st.columns(3)
                for _col, (_kpi, _kpi_title) in zip(_cols, _row_kpis):
                    with _col:
                        if _cur_prog.empty or _prior_prog.empty:
                            st.info(f"No data: {_kpi_title}")
                            continue

                        _v_cur   = float(_cur_prog.iloc[0][_kpi])   if pd.notna(_cur_prog.iloc[0][_kpi])   else 0
                        _v_prior = float(_prior_prog.iloc[0][_kpi]) if pd.notna(_prior_prog.iloc[0][_kpi]) else 0
                        _lib     = _BAR_LOWER_IS_BETTER[_kpi]
                        # current bar colour: green if improved vs prior, red if deteriorated
                        _improved = (_v_cur < _v_prior) if _lib else (_v_cur > _v_prior)
                        _cur_color = _COL_GOOD if _improved else _COL_BAD

                        import plotly.graph_objects as _go2
                        _fig2 = _go2.Figure()
                        _fig2.add_trace(_go2.Bar(
                            x=[_cur_label],
                            y=[round(_v_cur, 2)],
                            marker_color=_cur_color,
                            text=[f"{_v_cur:.2f}"],
                            textposition="outside",
                            textfont=dict(size=16, color="#1A1C1E"),
                            name="Current FY",
                        ))
                        _fig2.add_trace(_go2.Bar(
                            x=[_prior_label],
                            y=[round(_v_prior, 2)],
                            marker_color=_COL_PRIOR,
                            text=[f"{_v_prior:.2f}"],
                            textposition="outside",
                            textfont=dict(size=16, color="#1A1C1E"),
                            name="Prior FY",
                        ))
                        _delta = _v_cur - _v_prior
                        _delta_str = (f"▼ {abs(_delta):.2f} {'✓ Improved' if _improved else '✗ Worse'}"
                                      if _delta != 0 else "No change")
                        _fig2.update_layout(
                            title=dict(
                                text=f"{_kpi_title}<br>Δ {_delta_str}",
                                font=dict(size=16)
                            ),
                            yaxis=dict(showgrid=True, gridcolor="#EBEBEB"),
                            height=350,
                            margin=dict(t=60, b=10, l=10, r=10),
                            plot_bgcolor="white",
                            showlegend=False,
                            barmode="group",
                        )
                        st.plotly_chart(_fig2, width='stretch',
                                        key=f"discom_bar_prog_{_kpi}")


    # =========================================================================
    # ZONE-WISE KPI TABLES — 6 tables, one per KPI, worst → best, DISCOM last row
    # =========================================================================
    st.divider()
    st.subheader("Zone-wise KPI Summary Tables — Worst to Best")
    st.caption(
        f"Category: **{CATEGORY_LABELS[category]}** | "
        f"{uh.period_caption(period_type, selected_month, fy_label)} | "
        f"Each table sorted worst → best for that KPI. Last row = DVVNL DISCOM total."
    )

    _ALL_KPI_COLS = [
        "line_loss_pct", "billing_efficiency_pct", "collection_efficiency_pct",
        "atc_loss_pct", "through_rate", "abr",
    ]
    _KPI_DISPLAY_NAMES = {
        "line_loss_pct":             "Line Loss %",
        "billing_efficiency_pct":    "Billing Eff %",
        "collection_efficiency_pct": "Coll Eff %",
        "atc_loss_pct":              "AT&C Loss %",
        "through_rate":              "Through Rate",
        "abr":                       "ABR",
    }
    _LOWER_BETTER = {
        "line_loss_pct": True, "billing_efficiency_pct": False,
        "collection_efficiency_pct": False, "atc_loss_pct": True,
        "through_rate": False, "abr": False,
    }

    # Fetch zone-level data once and DISCOM total once
    _zt = q_kpi_table(con, "ZONE", category, **period_kwargs).copy()
    _dt = q_kpi_table(con, "DISCOM", category, **period_kwargs).copy()

    # Round all KPI columns to 2 decimal places
    for _c in _ALL_KPI_COLS:
        if _c in _zt.columns:
            _zt[_c] = _zt[_c].round(2)
        if _c in _dt.columns:
            _dt[_c] = _dt[_c].round(2)

    # Build the DISCOM row with "DVVNL DISCOM" as zone label
    _dt_row = _dt.iloc[0].copy() if not _dt.empty else pd.Series(dtype=float)
    _dt_row["zone"] = "★ DVVNL DISCOM"

    # Two tables per row  →  3 rows of 2
    _tbl_pairs = [(_ALL_KPI_COLS[i], _ALL_KPI_COLS[i + 1]) for i in range(0, 6, 2)]

    for _kpi_a, _kpi_b in _tbl_pairs:
        _tcols = st.columns(2)

        for _tcol, _focal_kpi in zip(_tcols, [_kpi_a, _kpi_b]):
            with _tcol:
                _lib = _LOWER_BETTER[_focal_kpi]
                # Sort: worst first (highest for lower-is-better, lowest for higher-is-better)
                _sorted = _zt.sort_values(_focal_kpi, ascending=not _lib).reset_index(drop=True)
                _sorted.index = range(1, len(_sorted) + 1)   # rank 1 = worst

                # Build display dataframe: focal KPI first, then the rest
                _other_kpis = [k for k in _ALL_KPI_COLS if k != _focal_kpi]
                _col_order   = ["zone", _focal_kpi] + _other_kpis

                _display = _sorted[[c for c in _col_order if c in _sorted.columns]].copy()

                # Append DISCOM row (no rank number — it's a total, not a ranked unit)
                _discom_display = pd.DataFrame(
                    [[_dt_row.get(c, "") for c in _col_order]],
                    columns=_col_order,
                )
                # Concat with index reset so DISCOM row shows as plain last row
                _display = pd.concat([_display.reset_index(drop=True),
                                       _discom_display], ignore_index=True)

                # Rename columns for display
                _rename_map = {"zone": "Zone"} | {k: _KPI_DISPLAY_NAMES[k] for k in _ALL_KPI_COLS}
                _display = _display.rename(columns=_rename_map)

                # Add rank column (1=worst … N=best, blank for DISCOM row)
                _rank_col = [""] * len(_display)
                for _ri in range(len(_display) - 1):   # last row = DISCOM, no rank
                    _rank_col[_ri] = str(_ri + 1)
                _display.insert(0, "#", _rank_col)

                st.markdown(
                    f"**{_KPI_DISPLAY_NAMES[_focal_kpi]}** — "
                    f"{'⬇ lower is better' if _lib else '⬆ higher is better'}"
                )
                st.dataframe(
                    _display,
                    width='stretch',
                    hide_index=True,
                )


    # =========================================================================
    # ZONE-WISE MoM DELTA TABLES — 6 tables, one per KPI, sorted worst→best improvement
    # =========================================================================
    if prev_month is not None:
        st.divider()
        st.subheader("Zone-wise KPI Improvement Tables — MoM Δ (Worst → Best Change)")
        st.caption(
            f"Category: **{CATEGORY_LABELS[category]}** | "
            f"Current: **{selected_month}** vs Prior: **{prev_month}** | "
            f"Sorted by improvement on that KPI (worst change first). "
            f"Columns: Δ, % Chg, Current, Prior — then all other KPIs current values."
        )

        # Fetch MoM delta at ZONE and DISCOM level
        _mom_zones  = q_mom_yoy(con, "ZONE",  category, selected_month, compare="MoM")
        _mom_discom = q_mom_yoy(con, "DISCOM", category, selected_month, compare="MoM")

        if not _mom_zones.empty:
            # Round all numeric cols to 2 dp
            for _c in _mom_zones.select_dtypes(include="float").columns:
                _mom_zones[_c] = _mom_zones[_c].round(2)
            if not _mom_discom.empty:
                for _c in _mom_discom.select_dtypes(include="float").columns:
                    _mom_discom[_c] = _mom_discom[_c].round(2)
                _mom_discom["zone"] = "★ DVVNL DISCOM"

            # Also fetch current period zone values for all KPIs
            _zt_cur = q_kpi_table(con, "ZONE", category, **period_kwargs).copy()
            for _c in _zt_cur.select_dtypes(include="float").columns:
                _zt_cur[_c] = _zt_cur[_c].round(2)

            _delta_pairs = [(_ALL_KPI_COLS[i], _ALL_KPI_COLS[i + 1]) for i in range(0, 6, 2)]

            for _kpi_a, _kpi_b in _delta_pairs:
                _dcols = st.columns(2)

                for _dcol, _fkpi in zip(_dcols, [_kpi_a, _kpi_b]):
                    with _dcol:
                        _lib = _LOWER_BETTER[_fkpi]
                        _delta_col   = f"{_fkpi}_delta"
                        _pct_col     = f"{_fkpi}_pct_change"
                        _cur_col     = f"{_fkpi}_cur"
                        _prev_col    = f"{_fkpi}_prev"

                        # Sort: worst improvement first
                        # lower_is_better → improvement = negative delta → worst = most positive delta
                        # higher_is_better → improvement = positive delta → worst = most negative delta
                        _sorted_mom = _mom_zones.sort_values(
                            _delta_col, ascending=not _lib
                        ).reset_index(drop=True)

                        # Build display: focal delta/pct/cur/prev cols first, then other KPI cur values
                        _other_kpis_cur = [f"{k}_cur" for k in _ALL_KPI_COLS if k != _fkpi]
                        _other_kpi_names = {f"{k}_cur": _KPI_DISPLAY_NAMES[k]
                                             for k in _ALL_KPI_COLS if k != _fkpi}

                        _sel_cols = (
                            ["zone", _delta_col, _pct_col, _cur_col, _prev_col] +
                            [c for c in _other_kpis_cur if c in _sorted_mom.columns]
                        )
                        _disp_mom = _sorted_mom[[c for c in _sel_cols
                                                   if c in _sorted_mom.columns]].copy()

                        # Append DISCOM row
                        if not _mom_discom.empty:
                            _dis_row_sel = [c for c in _sel_cols if c in _mom_discom.columns]
                            _dis_row_df  = _mom_discom[_dis_row_sel].copy()
                            # fill any missing sel cols with ""
                            for _mc in _sel_cols:
                                if _mc not in _dis_row_df.columns:
                                    _dis_row_df[_mc] = ""
                            _dis_row_df = _dis_row_df[_sel_cols]
                            _disp_mom = pd.concat(
                                [_disp_mom, _dis_row_df], ignore_index=True
                            )

                        # Rank column (blank for DISCOM row)
                        _rk = [str(i + 1) for i in range(len(_disp_mom) - 1)] + [""]
                        _disp_mom.insert(0, "#", _rk)

                        # Rename columns for display
                        _col_renames = {
                            "zone":       "Zone",
                            _delta_col:   f"Δ {_KPI_DISPLAY_NAMES[_fkpi]}",
                            _pct_col:     "% Chg",
                            _cur_col:     f"{_KPI_DISPLAY_NAMES[_fkpi]} ({selected_month})",
                            _prev_col:    f"{_KPI_DISPLAY_NAMES[_fkpi]} ({prev_month})",
                        } | _other_kpi_names
                        _disp_mom = _disp_mom.rename(columns=_col_renames)

                        # Direction hint for the subtitle
                        _improve_hint = "Δ negative = improved" if _lib else "Δ positive = improved"
                        st.markdown(
                            f"**{_KPI_DISPLAY_NAMES[_fkpi]}** — "
                            f"{'⬇ lower is better' if _lib else '⬆ higher is better'} | "
                            f"_{_improve_hint}_"
                        )
                        st.dataframe(_disp_mom, width='stretch', hide_index=True)

    else:
        st.info(f"No prior month available for {selected_month} — MoM delta tables not shown.")

    # =========================================================================
    # ZONE-WISE YoY DELTA TABLES — 6 tables, one per KPI, sorted worst→best improvement
    # =========================================================================
    # Determine if a YoY comparable month exists
    _yoy_zones  = q_mom_yoy(con, "ZONE",  category, selected_month, compare="YoY")
    _yoy_discom = q_mom_yoy(con, "DISCOM", category, selected_month, compare="YoY")

    if not _yoy_zones.empty:
        _yoy_prior_month = _yoy_zones.iloc[0]["prior_month"]

        st.divider()
        st.subheader("Zone-wise KPI Improvement Tables — YoY Δ (Worst → Best Change)")
        st.caption(
            f"Category: **{CATEGORY_LABELS[category]}** | "
            f"Current: **{selected_month}** vs Same Month Last Year: **{_yoy_prior_month}** | "
            f"Sorted by improvement on that KPI (worst change first). "
            f"Columns: Δ, % Chg, Current, Prior — then all other KPIs current values."
        )

        # Round all numeric cols to 2 dp
        for _c in _yoy_zones.select_dtypes(include="float").columns:
            _yoy_zones[_c] = _yoy_zones[_c].round(2)
        if not _yoy_discom.empty:
            for _c in _yoy_discom.select_dtypes(include="float").columns:
                _yoy_discom[_c] = _yoy_discom[_c].round(2)
            _yoy_discom["zone"] = "★ DVVNL DISCOM"

        _yoy_pairs = [(_ALL_KPI_COLS[i], _ALL_KPI_COLS[i + 1]) for i in range(0, 6, 2)]

        for _kpi_a, _kpi_b in _yoy_pairs:
            _ycols = st.columns(2)

            for _ycol, _fkpi in zip(_ycols, [_kpi_a, _kpi_b]):
                with _ycol:
                    _lib        = _LOWER_BETTER[_fkpi]
                    _delta_col  = f"{_fkpi}_delta"
                    _pct_col    = f"{_fkpi}_pct_change"
                    _cur_col    = f"{_fkpi}_cur"
                    _prev_col   = f"{_fkpi}_prev"

                    # Sort: worst improvement first (direction-aware, same as MoM)
                    _sorted_yoy = _yoy_zones.sort_values(
                        _delta_col, ascending=not _lib
                    ).reset_index(drop=True)

                    # Build column order: focal KPI delta/pct/cur/prev first, then other KPIs cur
                    _other_cur_yoy  = [f"{k}_cur" for k in _ALL_KPI_COLS if k != _fkpi]
                    _other_names_yoy = {f"{k}_cur": _KPI_DISPLAY_NAMES[k]
                                         for k in _ALL_KPI_COLS if k != _fkpi}

                    _sel_yoy = (
                        ["zone", _delta_col, _pct_col, _cur_col, _prev_col] +
                        [c for c in _other_cur_yoy if c in _sorted_yoy.columns]
                    )
                    _disp_yoy = _sorted_yoy[
                        [c for c in _sel_yoy if c in _sorted_yoy.columns]
                    ].copy()

                    # Append DISCOM row
                    if not _yoy_discom.empty:
                        _dis_yoy_sel = [c for c in _sel_yoy if c in _yoy_discom.columns]
                        _dis_yoy_df  = _yoy_discom[_dis_yoy_sel].copy()
                        for _mc in _sel_yoy:
                            if _mc not in _dis_yoy_df.columns:
                                _dis_yoy_df[_mc] = ""
                        _dis_yoy_df = _dis_yoy_df[_sel_yoy]
                        _disp_yoy = pd.concat(
                            [_disp_yoy, _dis_yoy_df], ignore_index=True
                        )

                    # Rank column (blank for DISCOM row)
                    _rk_yoy = [str(i + 1) for i in range(len(_disp_yoy) - 1)] + [""]
                    _disp_yoy.insert(0, "#", _rk_yoy)

                    # Rename columns for display
                    _yoy_renames = {
                        "zone":      "Zone",
                        _delta_col:  f"Δ {_KPI_DISPLAY_NAMES[_fkpi]}",
                        _pct_col:    "% Chg (YoY)",
                        _cur_col:    f"{_KPI_DISPLAY_NAMES[_fkpi]} ({selected_month})",
                        _prev_col:   f"{_KPI_DISPLAY_NAMES[_fkpi]} ({_yoy_prior_month})",
                    } | _other_names_yoy
                    _disp_yoy = _disp_yoy.rename(columns=_yoy_renames)

                    _improve_hint = "Δ negative = improved" if _lib else "Δ positive = improved"
                    st.markdown(
                        f"**{_KPI_DISPLAY_NAMES[_fkpi]}** — "
                        f"{'⬇ lower is better' if _lib else '⬆ higher is better'} | "
                        f"_{_improve_hint}_ | YoY vs **{_yoy_prior_month}**"
                    )
                    st.dataframe(_disp_yoy, width='stretch', hide_index=True)

    else:
        st.info(
            f"No same-month prior year data available for **{selected_month}** — "
            f"YoY delta tables not shown. (Data starts from {month_options[0]}.)"
        )


    # =========================================================================
    # PROGRESSIVE CUMULATIVE ZONE-WISE KPI TABLES — 6 tables, one per KPI, worst → best
    # Always computed on progressive (FY cumulative) basis regardless of sidebar mode
    # =========================================================================
    st.divider()
    st.subheader("Zone-wise KPI Summary Tables — Progressive (FY Cumulative) Basis")
    st.caption(
        f"Category: **{CATEGORY_LABELS[category]}** | "
        f"Progressive cumulative from **Apr** upto **{selected_month}** (FY {fy_label}) | "
        f"Each table sorted worst → best for that KPI. Last row = DVVNL DISCOM total."
    )

    # Always use progressive kwargs for this section
    _prog_kwargs = dict(period_type="progressive", upto_month_seq=seq_index, fy_label=fy_label)

    _prog_zt = q_kpi_table(con, "ZONE", category, **_prog_kwargs).copy()
    _prog_dt = q_kpi_table(con, "DISCOM", category, **_prog_kwargs).copy()

    for _c in _ALL_KPI_COLS:
        if _c in _prog_zt.columns:
            _prog_zt[_c] = _prog_zt[_c].round(2)
        if _c in _prog_dt.columns:
            _prog_dt[_c] = _prog_dt[_c].round(2)

    _prog_dt_row = _prog_dt.iloc[0].copy() if not _prog_dt.empty else pd.Series(dtype=float)
    _prog_dt_row["zone"] = "★ DVVNL DISCOM"

    _prog_tbl_pairs = [(_ALL_KPI_COLS[i], _ALL_KPI_COLS[i + 1]) for i in range(0, 6, 2)]

    for _kpi_a, _kpi_b in _prog_tbl_pairs:
        _ptcols = st.columns(2)

        for _ptcol, _pfocal_kpi in zip(_ptcols, [_kpi_a, _kpi_b]):
            with _ptcol:
                _plib = _LOWER_BETTER[_pfocal_kpi]
                _psorted = _prog_zt.sort_values(_pfocal_kpi, ascending=not _plib).reset_index(drop=True)
                _psorted.index = range(1, len(_psorted) + 1)

                _pother_kpis = [k for k in _ALL_KPI_COLS if k != _pfocal_kpi]
                _pcol_order  = ["zone", _pfocal_kpi] + _pother_kpis

                _pdisplay = _psorted[[c for c in _pcol_order if c in _psorted.columns]].copy()

                _pdiscom_display = pd.DataFrame(
                    [[_prog_dt_row.get(c, "") for c in _pcol_order]],
                    columns=_pcol_order,
                )
                _pdisplay = pd.concat([_pdisplay.reset_index(drop=True), _pdiscom_display], ignore_index=True)

                _prename_map = {"zone": "Zone"} | {k: _KPI_DISPLAY_NAMES[k] for k in _ALL_KPI_COLS}
                _pdisplay = _pdisplay.rename(columns=_prename_map)

                _prank_col = [""] * len(_pdisplay)
                for _pri in range(len(_pdisplay) - 1):
                    _prank_col[_pri] = str(_pri + 1)
                _pdisplay.insert(0, "#", _prank_col)

                st.markdown(
                    f"**{_KPI_DISPLAY_NAMES[_pfocal_kpi]}** — "
                    f"{'⬇ lower is better' if _plib else '⬆ higher is better'} | Progressive (Apr → {selected_month})"
                )
                st.dataframe(_pdisplay, width='stretch', hide_index=True)

    # =========================================================================
    # PROGRESSIVE WORST→BEST DELTA TABLES — 6 KPI tables
    # Delta = Current FY progressive vs Prior FY same span (progressive)
    # Columns order: Zone | Last FY Prog | Cur FY Prog | Δ | % Chg | other KPIs cur
    # Sorted worst→best improvement per KPI; DISCOM row appended at bottom
    # =========================================================================

    # Resolve prior FY progressive data (same logic as bar charts above)
    _cur_fy_pos_d = int(m_row["fy_month_pos"])
    _prior_fy_rows_d = month_lookup[
        (month_lookup["fy_month_pos"] <= _cur_fy_pos_d) &
        (month_lookup["fy_label"] != fy_label)
    ]
    _prior_fy_candidates_d = _prior_fy_rows_d["fy_label"].unique()

    if len(_prior_fy_candidates_d) > 0:
        _prior_fy_label_d = sorted(_prior_fy_candidates_d)[-1]
        _prior_max_seq_d  = int(
            _prior_fy_rows_d[_prior_fy_rows_d["fy_label"] == _prior_fy_label_d]["seq_index"].max()
        )
        _prior_prog_kwargs_d = dict(
            period_type="progressive",
            upto_month_seq=_prior_max_seq_d,
            fy_label=_prior_fy_label_d,
        )

        # Fetch prior FY progressive zone-level and DISCOM data
        _pfy_zt = q_kpi_table(con, "ZONE",   category, **_prior_prog_kwargs_d).copy()
        _pfy_dt = q_kpi_table(con, "DISCOM", category, **_prior_prog_kwargs_d).copy()

        # Prior FY label string for column headers
        _prior_start_m_d  = month_lookup[month_lookup["fy_label"] == _prior_fy_label_d]["month"].iloc[0]
        _prior_end_m_d    = month_lookup[month_lookup["seq_index"] == _prior_max_seq_d]["month"].iloc[0]
        _cur_start_m_d    = month_lookup[month_lookup["fy_label"] == fy_label]["month"].iloc[0]
        _prior_span_label = f"Apr→{_prior_end_m_d} ({_prior_fy_label_d})"
        _cur_span_label   = f"Apr→{selected_month} ({fy_label})"

        if not _pfy_zt.empty and not _prog_zt.empty:
            st.divider()
            st.subheader("Zone-wise KPI Progressive Delta Tables — Worst → Best Improvement")
            st.caption(
                f"Category: **{CATEGORY_LABELS[category]}** | "
                f"Progressive comparison: **{_cur_span_label}** vs **{_prior_span_label}** | "
                f"Sorted by improvement on the selected KPI (worst change first). "
                f"DISCOM row appended at bottom. "
                f"Columns: Last FY Prog → Cur FY Prog → Δ → % Chg → other KPIs (current progressive)."
            )

            # Round to 2dp
            for _c in _ALL_KPI_COLS:
                if _c in _pfy_zt.columns:
                    _pfy_zt[_c] = _pfy_zt[_c].round(2)
                if _c in _prog_zt.columns:
                    _prog_zt[_c] = _prog_zt[_c].round(2)
            if not _pfy_dt.empty:
                for _c in _ALL_KPI_COLS:
                    if _c in _pfy_dt.columns:
                        _pfy_dt[_c] = _pfy_dt[_c].round(2)
                if _c in _prog_dt.columns:
                    _prog_dt[_c] = _prog_dt[_c].round(2)

            # Merge cur + prior on zone
            _merged_prog = _prog_zt[["zone"] + _ALL_KPI_COLS].merge(
                _pfy_zt[["zone"] + _ALL_KPI_COLS].rename(columns={k: f"{k}_prior" for k in _ALL_KPI_COLS}),
                on="zone", how="inner"
            )

            # Compute delta and pct_change for each KPI
            for _k in _ALL_KPI_COLS:
                _merged_prog[f"{_k}_delta"]      = (_merged_prog[_k] - _merged_prog[f"{_k}_prior"]).round(2)
                _merged_prog[f"{_k}_pct_change"] = (
                    (_merged_prog[_k] - _merged_prog[f"{_k}_prior"]) /
                    _merged_prog[f"{_k}_prior"].replace(0, float("nan")) * 100
                ).round(2)

            # Build DISCOM combined row
            if not _pfy_dt.empty and not _prog_dt.empty:
                _discom_merged = _prog_dt[["discom"] + _ALL_KPI_COLS].copy() if "discom" in _prog_dt.columns else _prog_dt[_ALL_KPI_COLS].copy()
                _discom_merged_prior = _pfy_dt[_ALL_KPI_COLS].copy().rename(columns={k: f"{k}_prior" for k in _ALL_KPI_COLS})
                # reset index to align single rows
                _discom_merged = _discom_merged.reset_index(drop=True)
                _discom_merged_prior = _discom_merged_prior.reset_index(drop=True)
                _discom_merged_full = pd.concat([_discom_merged, _discom_merged_prior], axis=1)
                for _k in _ALL_KPI_COLS:
                    if _k in _discom_merged_full.columns and f"{_k}_prior" in _discom_merged_full.columns:
                        _discom_merged_full[f"{_k}_delta"]      = (_discom_merged_full[_k] - _discom_merged_full[f"{_k}_prior"]).round(2)
                        _discom_merged_full[f"{_k}_pct_change"] = (
                            (_discom_merged_full[_k] - _discom_merged_full[f"{_k}_prior"]) /
                            _discom_merged_full[f"{_k}_prior"].replace(0, float("nan")) * 100
                        ).round(2)
                _discom_merged_full["zone"] = "★ DVVNL DISCOM"
            else:
                _discom_merged_full = pd.DataFrame()

            _pdelta_pairs = [(_ALL_KPI_COLS[i], _ALL_KPI_COLS[i + 1]) for i in range(0, 6, 2)]

            for _kpi_a_pd, _kpi_b_pd in _pdelta_pairs:
                _pdcols = st.columns(2)

                for _pdcol, _pfkpi in zip(_pdcols, [_kpi_a_pd, _kpi_b_pd]):
                    with _pdcol:
                        _pdlib        = _LOWER_BETTER[_pfkpi]
                        _pd_delta_col = f"{_pfkpi}_delta"
                        _pd_pct_col   = f"{_pfkpi}_pct_change"
                        _pd_prior_col = f"{_pfkpi}_prior"

                        # Sort worst improvement first (direction-aware)
                        # lower_is_better: improvement = delta < 0; worst = most positive delta → ascending=False
                        # higher_is_better: improvement = delta > 0; worst = most negative delta → ascending=True
                        _psorted_delta = _merged_prog.sort_values(
                            _pd_delta_col, ascending=not _pdlib
                        ).reset_index(drop=True)

                        # Column selection: zone | prior FY | cur FY | delta | pct | other KPIs cur
                        _pd_other_cur  = [k for k in _ALL_KPI_COLS if k != _pfkpi]
                        _pd_sel_cols   = (
                            ["zone", _pd_prior_col, _pfkpi, _pd_delta_col, _pd_pct_col] +
                            [c for c in _pd_other_cur if c in _psorted_delta.columns]
                        )
                        _pd_disp = _psorted_delta[[c for c in _pd_sel_cols if c in _psorted_delta.columns]].copy()

                        # Append DISCOM row
                        if not _discom_merged_full.empty:
                            _pd_dis_cols = [c for c in _pd_sel_cols if c in _discom_merged_full.columns]
                            _pd_dis_df   = _discom_merged_full[_pd_dis_cols].copy()
                            for _mc in _pd_sel_cols:
                                if _mc not in _pd_dis_df.columns:
                                    _pd_dis_df[_mc] = ""
                            _pd_dis_df = _pd_dis_df[_pd_sel_cols]
                            _pd_disp = pd.concat([_pd_disp, _pd_dis_df], ignore_index=True)

                        # Rank column (blank for DISCOM row)
                        _pd_rk = [str(i + 1) for i in range(len(_pd_disp) - 1)] + [""]
                        _pd_disp.insert(0, "#", _pd_rk)

                        # Rename columns for display
                        _pd_renames = {
                            "zone":          "Zone",
                            _pd_prior_col:   f"{_KPI_DISPLAY_NAMES[_pfkpi]} ({_prior_span_label})",
                            _pfkpi:          f"{_KPI_DISPLAY_NAMES[_pfkpi]} ({_cur_span_label})",
                            _pd_delta_col:   f"Δ {_KPI_DISPLAY_NAMES[_pfkpi]}",
                            _pd_pct_col:     "% Chg (Prog)",
                        } | {k: _KPI_DISPLAY_NAMES[k] for k in _pd_other_cur}
                        _pd_disp = _pd_disp.rename(columns=_pd_renames)

                        _pd_improve_hint = "Δ negative = improved" if _pdlib else "Δ positive = improved"
                        st.markdown(
                            f"**{_KPI_DISPLAY_NAMES[_pfkpi]}** — "
                            f"{'⬇ lower is better' if _pdlib else '⬆ higher is better'} | "
                            f"_{_pd_improve_hint}_ | Progressive: {_cur_span_label} vs {_prior_span_label}"
                        )
                        st.dataframe(_pd_disp, width='stretch', hide_index=True)
                        quick_export_buttons(_pd_disp, f"prog_delta_{_pfkpi}", f"Prog Delta {_KPI_DISPLAY_NAMES[_pfkpi]}")

    else:
        st.info(
            f"No prior FY progressive data available for **{selected_month}** — "
            f"Progressive delta tables not shown. (Data starts from {month_options[0]}.)"
        )




    # st.divider()
    # col_trend, col_zone = st.columns([3, 2])
    # with col_trend:
    #     st.subheader("Trend (Monthly)")
    #     trend_kpi = st.selectbox("KPI to trend", KPI_OPTIONS, format_func=lambda k: KPI_LABELS[k],
    #                               key="discom_trend_kpi")
    #     discom_trend = q_trend_table(con, "DISCOM", category)
    #     uh.trend_line_chart(discom_trend, trend_kpi, title=None, key="trend_discom")
    #     with st.expander("Quick native trend (st.line_chart)"):
    #         nt = discom_trend.dropna(subset=[trend_kpi]).set_index("month")[[trend_kpi]]
    #         st.line_chart(nt)

    # with col_zone:
    #     st.subheader(f"Zone-wise — {KPI_LABELS[trend_kpi]}")
    #     zone_now = q_kpi_table(con, "ZONE", category, **period_kwargs)
    #     uh.rank_bar_chart(zone_now.sort_values(trend_kpi, ascending=KPI_META[trend_kpi]["lower_is_better"]),
    #                        trend_kpi, "zone", mode="worst", key="bar_discom_zone_overview")

    # st.divider()
    # st.subheader(f"Zone-wise AT&C Loss — ({CATEGORY_LABELS[category]})")
    # zone_list = sorted(long_df["zone"].unique())
    # spark_cols = st.columns(5)
    # for i, z in enumerate(zone_list):
    #     with spark_cols[i % 5]:
    #         z_trend = q_trend_table(con, "ZONE", category, zone=z)
    #         ch = uh.altair_sparkline(z_trend, "atc_loss_pct")
    #         st.caption(z)
    #         if ch is not None:
    #             st.altair_chart(ch, width='stretch', key=f"spark_{z}")

    # st.divider()
    # c1, c2 = st.columns(2)
    # with c1:
    #     st.subheader(f"Worst {top_n} Zones — {KPI_LABELS[trend_kpi]}")
    #     worst_zones = q_rank_table(con, "ZONE", category, trend_kpi, top_n=top_n, mode="worst", **period_kwargs)
    #     st.dataframe(worst_zones, width='stretch', hide_index=True)
    #     quick_export_buttons(worst_zones, "discom_worst_zones", "Worst Zones")
    # with c2:
    #     st.subheader(f"Best {top_n} Zones — {KPI_LABELS[trend_kpi]}")
    #     best_zones = q_rank_table(con, "ZONE", category, trend_kpi, top_n=top_n, mode="best", **period_kwargs)
    #     st.dataframe(best_zones, width='stretch', hide_index=True)
    #     quick_export_buttons(best_zones, "discom_best_zones", "Best Zones")

    # =========================================================================
    # DISCOM CATEGORY SUMMARY TABLE — Overall / Govt / Non-Govt (3 rows)
    # =========================================================================
    st.divider()
    st.subheader("DISCOM Category Summary — Overall | Government | Non-Government")
    st.caption(
        f"{uh.period_caption(period_type, selected_month, fy_label)} | "
        f"All six KPIs for each consumer category at DISCOM level."
    )
 
    _cat_summary_rows = []
    for _cat_key, _cat_label in zip(
        ["OVERALL", "GOVT", "NON_GOVT"],
        ["Overall", "Government", "Non-Government"],
    ):
        _cat_row = q_kpi_table(con, "DISCOM", _cat_key, **period_kwargs)
        if not _cat_row.empty:
            _r = _cat_row.iloc[0].copy()
            _r["Category"] = _cat_label
            _cat_summary_rows.append(_r)
 
    if _cat_summary_rows:
        _cat_df = pd.DataFrame(_cat_summary_rows)
        _cat_display_cols = ["Category"] + _ALL_KPI_COLS
        _cat_df = _cat_df[[c for c in _cat_display_cols if c in _cat_df.columns]]
        for _c in _ALL_KPI_COLS:
            if _c in _cat_df.columns:
                _cat_df[_c] = _cat_df[_c].round(2)
        _cat_df = _cat_df.rename(columns=_KPI_DISPLAY_NAMES)
        st.dataframe(_cat_df, width='stretch', hide_index=True)
        quick_export_buttons(_cat_df, "discom_category_summary", "DISCOM Category Summary")
    else:
        st.info("No category data available for the selected period.")


# # =============================================================================
# # TAB 2 — ZONE REVIEW
# # =============================================================================
# with tabs[1]:
#     zone_list = sorted(long_df["zone"].unique())
#     sel_zone = st.selectbox("Select Zone", zone_list, key="zr_zone")

#     zrow = q_kpi_table(con, "ZONE", category, zone=sel_zone, **period_kwargs)
#     if zrow.empty:
#         st.warning("No data for this zone/period.")
#     else:
#         zrow = zrow.iloc[0]
#         zdelta = None
#         if period_type == "single" and prev_month is not None:
#             pdf_ = q_kpi_table(con, "ZONE", category, "single", month=prev_month, zone=sel_zone)
#             zdelta = pdf_.iloc[0] if not pdf_.empty else None

#         st.subheader(f"{sel_zone} Zone — KPIs")
#         uh.kpi_card_row(zrow, category, zdelta)

#         st.divider()
#         col_t, col_r = st.columns([3, 2])
#         with col_t:
#             st.subheader("Zone Trend")
#             zkpi = st.selectbox("KPI", KPI_OPTIONS, format_func=lambda k: KPI_LABELS[k], key="zone_trend_kpi")
#             ztrend = q_trend_table(con, "ZONE", category, zone=sel_zone)
#             uh.trend_line_chart(ztrend, zkpi, title=f"{sel_zone} — {KPI_LABELS[zkpi]}", key="trend_zone")
#         with col_r:
#             st.subheader("Circle-wise comparison")
#             circ_now = q_kpi_table(con, "CIRCLE", category, zone=sel_zone, **period_kwargs)
#             uh.rank_bar_chart(circ_now, zkpi, "circle", mode="worst", key="bar_zone_circle_overview")

#         st.divider()
#         st.subheader(f"Circle ranking within {sel_zone} — {KPI_LABELS[zkpi]}")
#         c1, c2 = st.columns(2)
#         with c1:
#             st.caption(f"Worst {top_n} Circles")
#             wc = q_rank_table(con, "CIRCLE", category, zkpi, top_n=top_n, mode="worst", zone=sel_zone, **period_kwargs)
#             st.dataframe(wc, width='stretch', hide_index=True)
#             quick_export_buttons(wc, "zone_worst_circles", "Worst Circles")
#         with c2:
#             st.caption(f"Best {top_n} Circles")
#             bc = q_rank_table(con, "CIRCLE", category, zkpi, top_n=top_n, mode="best", zone=sel_zone, **period_kwargs)
#             st.dataframe(bc, width='stretch', hide_index=True)
#             quick_export_buttons(bc, "zone_best_circles", "Best Circles")



# =============================================================================
# TAB 2 — ZONE REVIEW  (mirrors Tab 0 structure, scoped to circles in a zone)
# =============================================================================
with tabs[1]:
    _Z_ALL_KPI_COLS = [
        "line_loss_pct", "billing_efficiency_pct", "collection_efficiency_pct",
        "atc_loss_pct", "through_rate", "abr",
    ]
    _Z_KPI_DISPLAY_NAMES = {
        "line_loss_pct":             "Line Loss %",
        "billing_efficiency_pct":    "Billing Eff %",
        "collection_efficiency_pct": "Coll Eff %",
        "atc_loss_pct":              "AT&C Loss %",
        "through_rate":              "Through Rate",
        "abr":                       "ABR",
    }
    _Z_LOWER_BETTER = {
        "line_loss_pct": True, "billing_efficiency_pct": False,
        "collection_efficiency_pct": False, "atc_loss_pct": True,
        "through_rate": False, "abr": False,
    }
    _Z_BAR_KPIS = [
        ("atc_loss_pct",              "AT&C Loss (%)"),
        ("line_loss_pct",             "Line / Distribution Loss (%)"),
        ("billing_efficiency_pct",    "Billing Efficiency (%)"),
        ("collection_efficiency_pct", "Collection Efficiency (%)"),
        ("through_rate",              "Through Rate (Rs/Unit)"),
        ("abr",                       "ABR (Rs/Unit)"),
    ]
    _Z_BAR_LIB = {
        "atc_loss_pct": True, "line_loss_pct": True,
        "billing_efficiency_pct": False, "collection_efficiency_pct": False,
        "through_rate": False, "abr": False,
    }
    _ZC_GOOD  = "#1E8E3E"
    _ZC_BAD   = "#D93025"
    _ZC_CURR  = "#0B5394"
    _ZC_PRIOR = "#B0C4DE"

    zone_list = sorted(long_df["zone"].unique())
    sel_zone = st.selectbox("Select Zone", zone_list, key="zr_zone")

    zrow = q_kpi_table(con, "ZONE", category, zone=sel_zone, **period_kwargs)
    if zrow.empty:
        st.warning("No data for this zone/period.")
    else:
        zrow_val = zrow.iloc[0]
        zdelta = None
        if period_type == "single" and prev_month is not None:
            _zpdf = q_kpi_table(con, "ZONE", category, "single", month=prev_month, zone=sel_zone)
            zdelta = _zpdf.iloc[0] if not _zpdf.empty else None

        st.subheader(f"{sel_zone} Zone — KPIs")
        uh.kpi_card_row(zrow_val, category, zdelta)

        # =====================================================================
        # 6 KPI BAR CHARTS — Monthly trend OR Progressive comparison
        # Scoped to the selected zone (mirrors Tab 0 exactly)
        # =====================================================================
        st.divider()

        if period_type == "single":
            # ---- Monthly mode: one bar per month for this zone ----
            st.subheader(f"KPI Monthly Trend — Bar Charts  [{sel_zone}]")
            st.caption(
                f"Zone: **{sel_zone}** | Category: {CATEGORY_LABELS[category]} | "
                f"Selected month **{selected_month}** highlighted."
            )

            import plotly.graph_objects as _zgo
            _z_trend_data = q_trend_table(con, "ZONE", category, zone=sel_zone)
            _z_trend_data = _z_trend_data.sort_values("seq_index")

            for _zrow_kpis in [_Z_BAR_KPIS[i:i+2] for i in range(0, 6, 2)]:
                _zcols = st.columns(2)
                for _zcol, (_zkpi, _zkpi_title) in zip(_zcols, _zrow_kpis):
                    with _zcol:
                        _zdf = _z_trend_data.dropna(subset=[_zkpi]).copy()
                        if _zdf.empty:
                            st.info(f"No data: {_zkpi_title}")
                            continue
                        _zlib = _Z_BAR_LIB[_zkpi]
                        _zcolors = []
                        for _, _zr in _zdf.iterrows():
                            if _zr["month"] == selected_month:
                                _zcolors.append(_ZC_CURR)
                            elif _zlib:
                                _zcolors.append(_ZC_BAD if _zr[_zkpi] > _zdf[_zkpi].median() else _ZC_GOOD)
                            else:
                                _zcolors.append(_ZC_GOOD if _zr[_zkpi] >= _zdf[_zkpi].median() else _ZC_BAD)
                        _zfig = _zgo.Figure(_zgo.Bar(
                            x=list(_zdf["month"]),
                            y=list(_zdf[_zkpi].round(2)),
                            marker_color=_zcolors,
                            text=[f"{v:.1f}" for v in _zdf[_zkpi]],
                            textposition="outside",
                           textfont=dict(
                                    size=14,
                                     family="Arial Black",
                                        color="#0A2036"
                                    ),
                            name=_zkpi_title,
                        ))
                        _zfig.update_layout(
                            title=dict(text=_zkpi_title, font=dict(size=16)),
                            xaxis=dict(tickangle=-45, tickfont=dict(size=12,
                                                                    #family="Arial Black", # Bold-looking font
                                                                    color="#1A1C1E")),
                            yaxis=dict(showgrid=True, gridcolor="#EBEBEB"),
                            height=320,
                            margin=dict(t=40, b=10, l=10, r=10),
                            plot_bgcolor="white",
                            showlegend=False,
                        )
                        _zfig.add_hline(
                            y=float(_zdf[_zkpi].mean()),
                            line_dash="dot", line_color="#888888",
                            annotation_text=f"Avg {_zdf[_zkpi].mean():.1f}",
                            annotation_font_size=9,
                        )
                        st.plotly_chart(_zfig, width='stretch',
                                        key=f"zone_bar_monthly_{sel_zone}_{_zkpi}")

        else:
            # ---- Progressive mode: 2-bar comparison for this zone ----
            st.subheader(f"KPI Progressive Comparison — Current FY vs Prior FY  [{sel_zone}]")

            import plotly.graph_objects as _zgo2
            _z_cur_prog = q_kpi_table(con, "ZONE", category, zone=sel_zone,
                                       period_type="progressive",
                                       upto_month_seq=seq_index, fy_label=fy_label)

            _z_bar_fy_pos = int(m_row["fy_month_pos"])
            _z_bar_prior_rows = month_lookup[
                (month_lookup["fy_month_pos"] <= _z_bar_fy_pos) &
                (month_lookup["fy_label"] != fy_label)
            ]
            _z_bar_prior_cands = _z_bar_prior_rows["fy_label"].unique()

            if len(_z_bar_prior_cands) == 0:
                st.info("No prior FY data available for progressive comparison.")
            else:
                _z_bar_prior_fy   = sorted(_z_bar_prior_cands)[-1]
                _z_bar_prior_seq  = int(
                    _z_bar_prior_rows[_z_bar_prior_rows["fy_label"] == _z_bar_prior_fy]["seq_index"].max()
                )
                _z_prior_prog = q_kpi_table(con, "ZONE", category, zone=sel_zone,
                                             period_type="progressive",
                                             upto_month_seq=_z_bar_prior_seq,
                                             fy_label=_z_bar_prior_fy)

                _z_cur_start  = month_lookup[month_lookup["fy_label"] == fy_label]["month"].iloc[0]
                _z_pri_start  = month_lookup[month_lookup["fy_label"] == _z_bar_prior_fy]["month"].iloc[0]
                _z_pri_end    = month_lookup[month_lookup["seq_index"] == _z_bar_prior_seq]["month"].iloc[0]
                _z_cur_lbl    = f"Current FY {fy_label}\n({_z_cur_start} → {selected_month})"
                _z_prior_lbl  = f"Prior FY {_z_bar_prior_fy}\n({_z_pri_start} → {_z_pri_end})"

                st.caption(
                    f"Zone: **{sel_zone}** | Category: {CATEGORY_LABELS[category]} | "
                    f"**{_z_cur_lbl.replace(chr(10),' ')}** vs **{_z_prior_lbl.replace(chr(10),' ')}**"
                )

                for _z_bar_row in [_Z_BAR_KPIS[:3], _Z_BAR_KPIS[3:]]:
                    _z_pcols = st.columns(3)
                    for _z_pcol, (_z_bkpi, _z_bkpi_title) in zip(_z_pcols, _z_bar_row):
                        with _z_pcol:
                            if _z_cur_prog.empty or _z_prior_prog.empty:
                                st.info(f"No data: {_z_bkpi_title}")
                                continue
                            _zv_cur   = float(_z_cur_prog.iloc[0][_z_bkpi])   if pd.notna(_z_cur_prog.iloc[0][_z_bkpi])   else 0
                            _zv_prior = float(_z_prior_prog.iloc[0][_z_bkpi]) if pd.notna(_z_prior_prog.iloc[0][_z_bkpi]) else 0
                            _zb_lib   = _Z_BAR_LIB[_z_bkpi]
                            _zb_imp   = (_zv_cur < _zv_prior) if _zb_lib else (_zv_cur > _zv_prior)
                            _zb_color = _ZC_GOOD if _zb_imp else _ZC_BAD
                            _zfig2 = _zgo2.Figure()
                            _zfig2.add_trace(_zgo2.Bar(
                                x=[_z_cur_lbl], y=[round(_zv_cur, 2)],
                                marker_color=_zb_color,
                                text=[f"{_zv_cur:.2f}"], textposition="outside",
                                textfont=dict(size=11, color="#1A1C1E"), name="Current FY",
                            ))
                            _zfig2.add_trace(_zgo2.Bar(
                                x=[_z_prior_lbl], y=[round(_zv_prior, 2)],
                                marker_color=_ZC_PRIOR,
                                text=[f"{_zv_prior:.2f}"], textposition="outside",
                                textfont=dict(size=11, color="#1A1C1E"), name="Prior FY",
                            ))
                            _zdelta    = _zv_cur - _zv_prior
                            _zdelta_s  = (f"▼ {abs(_zdelta):.2f} {'✓ Improved' if _zb_imp else '✗ Worse'}"
                                          if _zdelta != 0 else "No change")
                            _zfig2.update_layout(
                                title=dict(text=f"{_z_bkpi_title}<br>Δ {_zdelta_s}",
                                           font=dict(size=14)),
                                yaxis=dict(showgrid=True, gridcolor="#EBEBEB"),
                                height=350,
                                margin=dict(t=60, b=10, l=10, r=10),
                                plot_bgcolor="white",
                                showlegend=False,
                                barmode="group",
                            )
                            st.plotly_chart(_zfig2, width='stretch',
                                            key=f"zone_bar_prog_{sel_zone}_{_z_bkpi}")

    # st.divider()
    # col_t, col_r = st.columns([3, 2])
    # with col_t:
    #     st.subheader("Zone Trend")
    #     zkpi = st.selectbox("KPI", KPI_OPTIONS, format_func=lambda k: KPI_LABELS[k], key="zone_trend_kpi")
    #     ztrend = q_trend_table(con, "ZONE", category, zone=sel_zone)
    #     uh.trend_line_chart(ztrend, zkpi, title=f"{sel_zone} — {KPI_LABELS[zkpi]}", key="trend_zone")
    # with col_r:
    #     st.subheader("Circle-wise comparison")
    #     circ_now_bar = q_kpi_table(con, "CIRCLE", category, zone=sel_zone, **period_kwargs)
    #     uh.rank_bar_chart(circ_now_bar, zkpi, "circle", mode="worst", key="bar_zone_circle_overview")

    # st.divider()
    # st.subheader(f"Circle ranking within {sel_zone} — {KPI_LABELS[zkpi]}")
    # zrc1, zrc2 = st.columns(2)
    # with zrc1:
    #     st.caption(f"Worst {top_n} Circles")
    #     wc = q_rank_table(con, "CIRCLE", category, zkpi, top_n=top_n, mode="worst", zone=sel_zone, **period_kwargs)
    #     st.dataframe(wc, width='stretch', hide_index=True)
    #     quick_export_buttons(wc, "zone_worst_circles", "Worst Circles")
    # with zrc2:
    #     st.caption(f"Best {top_n} Circles")
    #     bc = q_rank_table(con, "CIRCLE", category, zkpi, top_n=top_n, mode="best", zone=sel_zone, **period_kwargs)
    #     st.dataframe(bc, width='stretch', hide_index=True)
    #     quick_export_buttons(bc, "zone_best_circles", "Best Circles")

    # =========================================================================
    # CIRCLE-WISE KPI TABLES — 6 tables, one per KPI, worst → best
    # Zone total row appended at bottom  (mirrors Tab 0 Zone-wise tables)
    # =========================================================================
    st.divider()
    st.subheader(f"Circle-wise KPI Summary Tables — Worst to Best  [{sel_zone}]")
    st.caption(
        f"Category: **{CATEGORY_LABELS[category]}** | "
        f"{uh.period_caption(period_type, selected_month, fy_label)} | "
        f"Each table sorted worst → best for that KPI. Last row = {sel_zone} Zone total."
    )

    _z_ct = q_kpi_table(con, "CIRCLE", category, zone=sel_zone, **period_kwargs).copy()
    _z_zt = q_kpi_table(con, "ZONE",   category, zone=sel_zone, **period_kwargs).copy()

    for _c in _Z_ALL_KPI_COLS:
        if _c in _z_ct.columns: _z_ct[_c] = _z_ct[_c].round(2)
        if _c in _z_zt.columns: _z_zt[_c] = _z_zt[_c].round(2)

    _z_zt_row = _z_zt.iloc[0].copy() if not _z_zt.empty else pd.Series(dtype=float)
    _z_zt_row["circle"] = f"★ {sel_zone} Zone Total"

    for _kpi_a, _kpi_b in [(_Z_ALL_KPI_COLS[i], _Z_ALL_KPI_COLS[i+1]) for i in range(0, 6, 2)]:
        _z_tcols = st.columns(2)
        for _z_tcol, _z_focal in zip(_z_tcols, [_kpi_a, _kpi_b]):
            with _z_tcol:
                _z_lib = _Z_LOWER_BETTER[_z_focal]
                _z_sorted = _z_ct.sort_values(_z_focal, ascending=not _z_lib).reset_index(drop=True)
                _z_others  = [k for k in _Z_ALL_KPI_COLS if k != _z_focal]
                _z_cols    = ["circle", _z_focal] + _z_others
                _z_disp    = _z_sorted[[c for c in _z_cols if c in _z_sorted.columns]].copy()
                _z_zone_row = pd.DataFrame([[_z_zt_row.get(c, "") for c in _z_cols]], columns=_z_cols)
                _z_disp = pd.concat([_z_disp.reset_index(drop=True), _z_zone_row], ignore_index=True)
                _z_renames = {"circle": "Circle"} | {k: _Z_KPI_DISPLAY_NAMES[k] for k in _Z_ALL_KPI_COLS}
                _z_disp = _z_disp.rename(columns=_z_renames)
                _z_rank = [str(i+1) for i in range(len(_z_disp)-1)] + [""]
                _z_disp.insert(0, "#", _z_rank)
                st.markdown(
                    f"**{_Z_KPI_DISPLAY_NAMES[_z_focal]}** — "
                    f"{'⬇ lower is better' if _z_lib else '⬆ higher is better'}"
                )
                st.dataframe(_z_disp, width='stretch', hide_index=True)

    # =========================================================================
    # MoM DELTA TABLES — circle-wise, sorted worst → best improvement
    # =========================================================================
    if prev_month is not None:
        st.divider()
        st.subheader(f"Circle-wise KPI Improvement Tables — MoM Δ (Worst → Best)  [{sel_zone}]")
        st.caption(
            f"Category: **{CATEGORY_LABELS[category]}** | "
            f"Current: **{selected_month}** vs Prior: **{prev_month}** | "
            f"Sorted by improvement on that KPI (worst change first)."
        )

        _z_mom_circles = q_mom_yoy(con, "CIRCLE", category, selected_month, compare="MoM", zone=sel_zone)
        _z_mom_zone    = q_mom_yoy(con, "ZONE",   category, selected_month, compare="MoM", zone=sel_zone)

        if not _z_mom_circles.empty:
            for _c in _z_mom_circles.select_dtypes(include="float").columns:
                _z_mom_circles[_c] = _z_mom_circles[_c].round(2)
            if not _z_mom_zone.empty:
                for _c in _z_mom_zone.select_dtypes(include="float").columns:
                    _z_mom_zone[_c] = _z_mom_zone[_c].round(2)
                _z_mom_zone["circle"] = f"★ {sel_zone} Zone Total"

            for _kpi_a, _kpi_b in [(_Z_ALL_KPI_COLS[i], _Z_ALL_KPI_COLS[i+1]) for i in range(0, 6, 2)]:
                _z_dcols = st.columns(2)
                for _z_dcol, _z_fkpi in zip(_z_dcols, [_kpi_a, _kpi_b]):
                    with _z_dcol:
                        _z_lib2      = _Z_LOWER_BETTER[_z_fkpi]
                        _z_delta_col = f"{_z_fkpi}_delta"
                        _z_pct_col   = f"{_z_fkpi}_pct_change"
                        _z_cur_col   = f"{_z_fkpi}_cur"
                        _z_prev_col  = f"{_z_fkpi}_prev"

                        _z_sorted_m = _z_mom_circles.sort_values(
                            _z_delta_col, ascending=not _z_lib2
                        ).reset_index(drop=True)

                        _z_other_cur = [f"{k}_cur" for k in _Z_ALL_KPI_COLS if k != _z_fkpi]
                        _z_other_names = {f"{k}_cur": _Z_KPI_DISPLAY_NAMES[k] for k in _Z_ALL_KPI_COLS if k != _z_fkpi}
                        _z_sel = (["circle", _z_delta_col, _z_pct_col, _z_cur_col, _z_prev_col]
                                  + [c for c in _z_other_cur if c in _z_sorted_m.columns])
                        _z_disp_m = _z_sorted_m[[c for c in _z_sel if c in _z_sorted_m.columns]].copy()

                        if not _z_mom_zone.empty:
                            _z_dis_sel = [c for c in _z_sel if c in _z_mom_zone.columns]
                            _z_dis_df  = _z_mom_zone[_z_dis_sel].copy()
                            for _mc in _z_sel:
                                if _mc not in _z_dis_df.columns: _z_dis_df[_mc] = ""
                            _z_dis_df  = _z_dis_df[_z_sel]
                            _z_disp_m  = pd.concat([_z_disp_m, _z_dis_df], ignore_index=True)

                        _z_rk_m = [str(i+1) for i in range(len(_z_disp_m)-1)] + [""]
                        _z_disp_m.insert(0, "#", _z_rk_m)
                        _z_col_renames_m = {
                            "circle":    "Circle",
                            _z_delta_col: f"Δ {_Z_KPI_DISPLAY_NAMES[_z_fkpi]}",
                            _z_pct_col:  "% Chg",
                            _z_cur_col:  f"{_Z_KPI_DISPLAY_NAMES[_z_fkpi]} ({selected_month})",
                            _z_prev_col: f"{_Z_KPI_DISPLAY_NAMES[_z_fkpi]} ({prev_month})",
                        } | _z_other_names
                        _z_disp_m = _z_disp_m.rename(columns=_z_col_renames_m)
                        _z_hint_m = "Δ negative = improved" if _z_lib2 else "Δ positive = improved"
                        st.markdown(
                            f"**{_Z_KPI_DISPLAY_NAMES[_z_fkpi]}** — "
                            f"{'⬇ lower is better' if _z_lib2 else '⬆ higher is better'} | _{_z_hint_m}_"
                        )
                        st.dataframe(_z_disp_m, width='stretch', hide_index=True)
        else:
            st.info(f"No MoM comparable period for {selected_month} in {sel_zone}.")
    else:
        st.info(f"No prior month available for {selected_month} — MoM delta tables not shown.")

    # =========================================================================
    # YoY DELTA TABLES — circle-wise, sorted worst → best improvement
    # =========================================================================
    _z_yoy_circles = q_mom_yoy(con, "CIRCLE", category, selected_month, compare="YoY", zone=sel_zone)
    _z_yoy_zone    = q_mom_yoy(con, "ZONE",   category, selected_month, compare="YoY", zone=sel_zone)

    if not _z_yoy_circles.empty:
        _z_yoy_prior_month = _z_yoy_circles.iloc[0]["prior_month"]
        st.divider()
        st.subheader(f"Circle-wise KPI Improvement Tables — YoY Δ (Worst → Best)  [{sel_zone}]")
        st.caption(
            f"Category: **{CATEGORY_LABELS[category]}** | "
            f"Current: **{selected_month}** vs Same Month Last Year: **{_z_yoy_prior_month}** | "
            f"Sorted by improvement on that KPI (worst change first)."
        )

        for _c in _z_yoy_circles.select_dtypes(include="float").columns:
            _z_yoy_circles[_c] = _z_yoy_circles[_c].round(2)
        if not _z_yoy_zone.empty:
            for _c in _z_yoy_zone.select_dtypes(include="float").columns:
                _z_yoy_zone[_c] = _z_yoy_zone[_c].round(2)
            _z_yoy_zone["circle"] = f"★ {sel_zone} Zone Total"

        for _kpi_a, _kpi_b in [(_Z_ALL_KPI_COLS[i], _Z_ALL_KPI_COLS[i+1]) for i in range(0, 6, 2)]:
            _z_ycols = st.columns(2)
            for _z_ycol, _z_fkpi_y in zip(_z_ycols, [_kpi_a, _kpi_b]):
                with _z_ycol:
                    _z_lib_y      = _Z_LOWER_BETTER[_z_fkpi_y]
                    _z_delta_y    = f"{_z_fkpi_y}_delta"
                    _z_pct_y      = f"{_z_fkpi_y}_pct_change"
                    _z_cur_y      = f"{_z_fkpi_y}_cur"
                    _z_prev_y     = f"{_z_fkpi_y}_prev"

                    _z_sorted_y = _z_yoy_circles.sort_values(
                        _z_delta_y, ascending=not _z_lib_y
                    ).reset_index(drop=True)

                    _z_other_cur_y  = [f"{k}_cur" for k in _Z_ALL_KPI_COLS if k != _z_fkpi_y]
                    _z_other_name_y = {f"{k}_cur": _Z_KPI_DISPLAY_NAMES[k] for k in _Z_ALL_KPI_COLS if k != _z_fkpi_y}
                    _z_sel_y = (["circle", _z_delta_y, _z_pct_y, _z_cur_y, _z_prev_y]
                                + [c for c in _z_other_cur_y if c in _z_sorted_y.columns])
                    _z_disp_y = _z_sorted_y[[c for c in _z_sel_y if c in _z_sorted_y.columns]].copy()

                    if not _z_yoy_zone.empty:
                        _z_dis_y_sel = [c for c in _z_sel_y if c in _z_yoy_zone.columns]
                        _z_dis_y_df  = _z_yoy_zone[_z_dis_y_sel].copy()
                        for _mc in _z_sel_y:
                            if _mc not in _z_dis_y_df.columns: _z_dis_y_df[_mc] = ""
                        _z_dis_y_df  = _z_dis_y_df[_z_sel_y]
                        _z_disp_y    = pd.concat([_z_disp_y, _z_dis_y_df], ignore_index=True)

                    _z_rk_y = [str(i+1) for i in range(len(_z_disp_y)-1)] + [""]
                    _z_disp_y.insert(0, "#", _z_rk_y)
                    _z_col_renames_y = {
                        "circle":   "Circle",
                        _z_delta_y: f"Δ {_Z_KPI_DISPLAY_NAMES[_z_fkpi_y]}",
                        _z_pct_y:   "% Chg (YoY)",
                        _z_cur_y:   f"{_Z_KPI_DISPLAY_NAMES[_z_fkpi_y]} ({selected_month})",
                        _z_prev_y:  f"{_Z_KPI_DISPLAY_NAMES[_z_fkpi_y]} ({_z_yoy_prior_month})",
                    } | _z_other_name_y
                    _z_disp_y = _z_disp_y.rename(columns=_z_col_renames_y)
                    _z_hint_y = "Δ negative = improved" if _z_lib_y else "Δ positive = improved"
                    st.markdown(
                        f"**{_Z_KPI_DISPLAY_NAMES[_z_fkpi_y]}** — "
                        f"{'⬇ lower is better' if _z_lib_y else '⬆ higher is better'} | "
                        f"_{_z_hint_y}_ | YoY vs **{_z_yoy_prior_month}**"
                    )
                    st.dataframe(_z_disp_y, width='stretch', hide_index=True)
    else:
        st.info(
            f"No same-month prior year data for **{selected_month}** in **{sel_zone}** — "
            f"YoY delta tables not shown."
        )

    # =========================================================================
    # PROGRESSIVE CUMULATIVE CIRCLE-WISE KPI TABLES — always FY cumulative
    # =========================================================================
    st.divider()
    st.subheader(f"Circle-wise KPI Tables — Progressive (FY Cumulative)  [{sel_zone}]")
    st.caption(
        f"Category: **{CATEGORY_LABELS[category]}** | "
        f"Progressive cumulative Apr → **{selected_month}** (FY {fy_label}) | "
        f"Each table sorted worst → best. Last row = {sel_zone} Zone total."
    )

    _z_prog_kwargs = dict(period_type="progressive", upto_month_seq=seq_index, fy_label=fy_label)
    _z_prog_ct = q_kpi_table(con, "CIRCLE", category, zone=sel_zone, **_z_prog_kwargs).copy()
    _z_prog_zt = q_kpi_table(con, "ZONE",   category, zone=sel_zone, **_z_prog_kwargs).copy()

    for _c in _Z_ALL_KPI_COLS:
        if _c in _z_prog_ct.columns: _z_prog_ct[_c] = _z_prog_ct[_c].round(2)
        if _c in _z_prog_zt.columns: _z_prog_zt[_c] = _z_prog_zt[_c].round(2)

    _z_prog_zt_row = _z_prog_zt.iloc[0].copy() if not _z_prog_zt.empty else pd.Series(dtype=float)
    _z_prog_zt_row["circle"] = f"★ {sel_zone} Zone Total"

    for _kpi_a, _kpi_b in [(_Z_ALL_KPI_COLS[i], _Z_ALL_KPI_COLS[i+1]) for i in range(0, 6, 2)]:
        _z_ptcols = st.columns(2)
        for _z_ptcol, _z_pfocal in zip(_z_ptcols, [_kpi_a, _kpi_b]):
            with _z_ptcol:
                _z_plib = _Z_LOWER_BETTER[_z_pfocal]
                _z_psorted = _z_prog_ct.sort_values(_z_pfocal, ascending=not _z_plib).reset_index(drop=True)
                _z_pothers = [k for k in _Z_ALL_KPI_COLS if k != _z_pfocal]
                _z_pcols   = ["circle", _z_pfocal] + _z_pothers
                _z_pdisp   = _z_psorted[[c for c in _z_pcols if c in _z_psorted.columns]].copy()
                _z_pzone_row = pd.DataFrame([[_z_prog_zt_row.get(c, "") for c in _z_pcols]], columns=_z_pcols)
                _z_pdisp = pd.concat([_z_pdisp.reset_index(drop=True), _z_pzone_row], ignore_index=True)
                _z_prenames = {"circle": "Circle"} | {k: _Z_KPI_DISPLAY_NAMES[k] for k in _Z_ALL_KPI_COLS}
                _z_pdisp = _z_pdisp.rename(columns=_z_prenames)
                _z_prank = [str(i+1) for i in range(len(_z_pdisp)-1)] + [""]
                _z_pdisp.insert(0, "#", _z_prank)
                st.markdown(
                    f"**{_Z_KPI_DISPLAY_NAMES[_z_pfocal]}** — "
                    f"{'⬇ lower is better' if _z_plib else '⬆ higher is better'} | "
                    f"Progressive (Apr → {selected_month})"
                )
                st.dataframe(_z_pdisp, width='stretch', hide_index=True)

    # =========================================================================
    # PROGRESSIVE WORST→BEST DELTA TABLES — current FY vs prior FY same span
    # =========================================================================
    _z_cur_fy_pos = int(m_row["fy_month_pos"])
    _z_prior_fy_rows = month_lookup[
        (month_lookup["fy_month_pos"] <= _z_cur_fy_pos) &
        (month_lookup["fy_label"] != fy_label)
    ]
    _z_prior_fy_cands = _z_prior_fy_rows["fy_label"].unique()

    if len(_z_prior_fy_cands) > 0:
        _z_prior_fy_lbl   = sorted(_z_prior_fy_cands)[-1]
        _z_prior_max_seq  = int(
            _z_prior_fy_rows[_z_prior_fy_rows["fy_label"] == _z_prior_fy_lbl]["seq_index"].max()
        )
        _z_prior_prog_kw  = dict(period_type="progressive", upto_month_seq=_z_prior_max_seq, fy_label=_z_prior_fy_lbl)

        _z_pfy_ct = q_kpi_table(con, "CIRCLE", category, zone=sel_zone, **_z_prior_prog_kw).copy()
        _z_pfy_zt = q_kpi_table(con, "ZONE",   category, zone=sel_zone, **_z_prior_prog_kw).copy()

        _z_prior_end_m  = month_lookup[month_lookup["seq_index"] == _z_prior_max_seq]["month"].iloc[0]
        _z_prior_span   = f"Apr→{_z_prior_end_m} ({_z_prior_fy_lbl})"
        _z_cur_span     = f"Apr→{selected_month} ({fy_label})"

        if not _z_pfy_ct.empty and not _z_prog_ct.empty:
            st.divider()
            st.subheader(f"Circle-wise KPI Progressive Delta Tables — Worst → Best  [{sel_zone}]")
            st.caption(
                f"Category: **{CATEGORY_LABELS[category]}** | "
                f"**{_z_cur_span}** vs **{_z_prior_span}** | "
                f"Columns: Last FY Prog → Cur FY Prog → Δ → % Chg → other KPIs (current). "
                f"Sorted worst improvement first. Last row = {sel_zone} Zone total."
            )

            for _c in _Z_ALL_KPI_COLS:
                if _c in _z_pfy_ct.columns: _z_pfy_ct[_c] = _z_pfy_ct[_c].round(2)
                if _c in _z_prog_ct.columns: _z_prog_ct[_c] = _z_prog_ct[_c].round(2)
                if _c in _z_pfy_zt.columns: _z_pfy_zt[_c] = _z_pfy_zt[_c].round(2)
                if _c in _z_prog_zt.columns: _z_prog_zt[_c] = _z_prog_zt[_c].round(2)

            _z_merged = _z_prog_ct[["circle"] + _Z_ALL_KPI_COLS].merge(
                _z_pfy_ct[["circle"] + _Z_ALL_KPI_COLS].rename(columns={k: f"{k}_prior" for k in _Z_ALL_KPI_COLS}),
                on="circle", how="inner"
            )
            for _k in _Z_ALL_KPI_COLS:
                _z_merged[f"{_k}_delta"]      = (_z_merged[_k] - _z_merged[f"{_k}_prior"]).round(2)
                _z_merged[f"{_k}_pct_change"] = (
                    (_z_merged[_k] - _z_merged[f"{_k}_prior"]) /
                    _z_merged[f"{_k}_prior"].replace(0, float("nan")) * 100
                ).round(2)

            # Build zone total reference row
            if not _z_pfy_zt.empty and not _z_prog_zt.empty:
                _z_zone_cur  = _z_prog_zt[_Z_ALL_KPI_COLS].reset_index(drop=True)
                _z_zone_pri  = _z_pfy_zt[_Z_ALL_KPI_COLS].rename(columns={k: f"{k}_prior" for k in _Z_ALL_KPI_COLS}).reset_index(drop=True)
                _z_zone_full = pd.concat([_z_zone_cur, _z_zone_pri], axis=1)
                for _k in _Z_ALL_KPI_COLS:
                    _z_zone_full[f"{_k}_delta"] = (_z_zone_full[_k] - _z_zone_full[f"{_k}_prior"]).round(2)
                    _z_zone_full[f"{_k}_pct_change"] = (
                        (_z_zone_full[_k] - _z_zone_full[f"{_k}_prior"]) /
                        _z_zone_full[f"{_k}_prior"].replace(0, float("nan")) * 100
                    ).round(2)
                _z_zone_full["circle"] = f"★ {sel_zone} Zone Total"
            else:
                _z_zone_full = pd.DataFrame()

            for _kpi_a, _kpi_b in [(_Z_ALL_KPI_COLS[i], _Z_ALL_KPI_COLS[i+1]) for i in range(0, 6, 2)]:
                _z_pdcols = st.columns(2)
                for _z_pdcol, _z_pfkpi in zip(_z_pdcols, [_kpi_a, _kpi_b]):
                    with _z_pdcol:
                        _z_pdlib   = _Z_LOWER_BETTER[_z_pfkpi]
                        _z_pd_d    = f"{_z_pfkpi}_delta"
                        _z_pd_pct  = f"{_z_pfkpi}_pct_change"
                        _z_pd_pri  = f"{_z_pfkpi}_prior"

                        _z_psorted_d = _z_merged.sort_values(_z_pd_d, ascending=not _z_pdlib).reset_index(drop=True)
                        _z_pd_other  = [k for k in _Z_ALL_KPI_COLS if k != _z_pfkpi]
                        _z_pd_sel    = (["circle", _z_pd_pri, _z_pfkpi, _z_pd_d, _z_pd_pct]
                                        + [c for c in _z_pd_other if c in _z_psorted_d.columns])
                        _z_pd_disp   = _z_psorted_d[[c for c in _z_pd_sel if c in _z_psorted_d.columns]].copy()

                        if not _z_zone_full.empty:
                            _z_zf_sel = [c for c in _z_pd_sel if c in _z_zone_full.columns]
                            _z_zf_df  = _z_zone_full[_z_zf_sel].copy()
                            for _mc in _z_pd_sel:
                                if _mc not in _z_zf_df.columns: _z_zf_df[_mc] = ""
                            _z_zf_df  = _z_zf_df[_z_pd_sel]
                            _z_pd_disp = pd.concat([_z_pd_disp, _z_zf_df], ignore_index=True)

                        _z_pd_rk = [str(i+1) for i in range(len(_z_pd_disp)-1)] + [""]
                        _z_pd_disp.insert(0, "#", _z_pd_rk)
                        _z_pd_renames = {
                            "circle":   "Circle",
                            _z_pd_pri:  f"{_Z_KPI_DISPLAY_NAMES[_z_pfkpi]} ({_z_prior_span})",
                            _z_pfkpi:   f"{_Z_KPI_DISPLAY_NAMES[_z_pfkpi]} ({_z_cur_span})",
                            _z_pd_d:    f"Δ {_Z_KPI_DISPLAY_NAMES[_z_pfkpi]}",
                            _z_pd_pct:  "% Chg (Prog)",
                        } | {k: _Z_KPI_DISPLAY_NAMES[k] for k in _z_pd_other}
                        _z_pd_disp = _z_pd_disp.rename(columns=_z_pd_renames)
                        _z_pd_hint = "Δ negative = improved" if _z_pdlib else "Δ positive = improved"
                        st.markdown(
                            f"**{_Z_KPI_DISPLAY_NAMES[_z_pfkpi]}** — "
                            f"{'⬇ lower is better' if _z_pdlib else '⬆ higher is better'} | "
                            f"_{_z_pd_hint}_ | {_z_cur_span} vs {_z_prior_span}"
                        )
                        st.dataframe(_z_pd_disp, width='stretch', hide_index=True)
                        quick_export_buttons(_z_pd_disp, f"z_prog_delta_{_z_pfkpi}", f"Zone Prog Delta {_Z_KPI_DISPLAY_NAMES[_z_pfkpi]}")
    else:
        st.info(
            f"No prior FY progressive data for **{sel_zone}** — "
            f"Progressive delta tables not shown."
        )

    # =========================================================================
    # ZONE CATEGORY SUMMARY TABLE — Overall / Govt / Non-Govt (3 rows)
    # =========================================================================
    st.divider()
    st.subheader(f"Zone Category Summary — Overall | Government | Non-Government  [{sel_zone}]")
    st.caption(
        f"{uh.period_caption(period_type, selected_month, fy_label)} | "
        f"All six KPIs for each consumer category at {sel_zone} Zone level."
    )

    _z_cat_rows = []
    for _zcat_key, _zcat_label in zip(
        ["OVERALL", "GOVT", "NON_GOVT"],
        ["Overall", "Government", "Non-Government"],
    ):
        _zcat_row = q_kpi_table(con, "ZONE", _zcat_key, zone=sel_zone, **period_kwargs)
        if not _zcat_row.empty:
            _zr = _zcat_row.iloc[0].copy()
            _zr["Category"] = _zcat_label
            _z_cat_rows.append(_zr)

    if _z_cat_rows:
        _z_cat_df = pd.DataFrame(_z_cat_rows)
        _z_cat_display_cols = ["Category"] + _Z_ALL_KPI_COLS
        _z_cat_df = _z_cat_df[[c for c in _z_cat_display_cols if c in _z_cat_df.columns]]
        for _c in _Z_ALL_KPI_COLS:
            if _c in _z_cat_df.columns:
                _z_cat_df[_c] = _z_cat_df[_c].round(2)
        _z_cat_df = _z_cat_df.rename(columns=_Z_KPI_DISPLAY_NAMES)
        st.dataframe(_z_cat_df, width='stretch', hide_index=True)
        quick_export_buttons(_z_cat_df, "zone_category_summary", f"{sel_zone} Category Summary")
    else:
        st.info("No category data available for the selected period.")


# =============================================================================
# TAB 3 — CIRCLE REVIEW
# =============================================================================
with tabs[2]:
    zone_list = sorted(long_df["zone"].unique())
    c0, c1 = st.columns(2)
    with c0:
        cr_zone = st.selectbox("Zone", zone_list, key="cr_zone")
    circle_pool = sorted(long_df.loc[long_df["zone"] == cr_zone, "circle"].unique())
    with c1:
        cr_circle = st.selectbox("Circle", circle_pool, key="cr_circle")

    crow = q_kpi_table(con, "CIRCLE", category, zone=cr_zone, circle=cr_circle, **period_kwargs)
    if crow.empty:
        st.warning("No data for this circle/period.")
    else:
        crow = crow.iloc[0]
        cdelta = None
        if period_type == "single" and prev_month is not None:
            pdf_ = q_kpi_table(con, "CIRCLE", category, "single", month=prev_month, zone=cr_zone, circle=cr_circle)
            cdelta = pdf_.iloc[0] if not pdf_.empty else None

        st.subheader(f"{cr_circle} — KPIs")
        uh.kpi_card_row(crow, category, cdelta)

        st.divider()
        col_t, col_r = st.columns([3, 2])
        with col_t:
            st.subheader("Circle Trend")
            ckpi = st.selectbox("KPI", KPI_OPTIONS, format_func=lambda k: KPI_LABELS[k], key="circle_trend_kpi")
            ctrend = q_trend_table(con, "CIRCLE", category, zone=cr_zone, circle=cr_circle)
            uh.trend_line_chart(ctrend, ckpi, title=f"{cr_circle} — {KPI_LABELS[ckpi]}", key="trend_circle")
        with col_r:
            st.subheader("Division-wise comparison")
            div_now = q_kpi_table(con, "DIVISION", category, zone=cr_zone, circle=cr_circle, **period_kwargs)
            uh.rank_bar_chart(div_now, ckpi, "division", mode="worst", key="bar_circle_division_overview")

        st.divider()
        st.subheader(f"Division ranking within {cr_circle} — {KPI_LABELS[ckpi]}")
        d1, d2 = st.columns(2)
        with d1:
            st.caption(f"Worst {top_n} Divisions")
            wd = q_rank_table(con, "DIVISION", category, ckpi, top_n=top_n, mode="worst",
                               zone=cr_zone, circle=cr_circle, **period_kwargs)
            st.dataframe(wd, width='stretch', hide_index=True)
            quick_export_buttons(wd, "circle_worst_divisions", "Worst Divisions")
        with d2:
            st.caption(f"Best {top_n} Divisions")
            bd = q_rank_table(con, "DIVISION", category, ckpi, top_n=top_n, mode="best",
                               zone=cr_zone, circle=cr_circle, **period_kwargs)
            st.dataframe(bd, width='stretch', hide_index=True)
            quick_export_buttons(bd, "circle_best_divisions", "Best Divisions")

# =============================================================================
# TAB 4 — DIVISION REVIEW
# =============================================================================
with tabs[3]:
    zone_list = sorted(long_df["zone"].unique())
    e0, e1, e2 = st.columns(3)
    with e0:
        dr_zone = st.selectbox("Zone", zone_list, key="dr_zone")
    circle_pool = sorted(long_df.loc[long_df["zone"] == dr_zone, "circle"].unique())
    with e1:
        dr_circle = st.selectbox("Circle", circle_pool, key="dr_circle")
    div_pool = sorted(long_df.loc[(long_df["zone"] == dr_zone) & (long_df["circle"] == dr_circle), "division"].unique())
    with e2:
        dr_division = st.selectbox("Division", div_pool, key="dr_division")

    drow = q_kpi_table(con, "DIVISION", category, zone=dr_zone, circle=dr_circle, division=dr_division, **period_kwargs)
    if drow.empty:
        st.warning("No data for this division/period.")
    else:
        drow = drow.iloc[0]
        ddelta = None
        if period_type == "single" and prev_month is not None:
            pdf_ = q_kpi_table(con, "DIVISION", category, "single", month=prev_month,
                                zone=dr_zone, circle=dr_circle, division=dr_division)
            ddelta = pdf_.iloc[0] if not pdf_.empty else None

        st.subheader(f"{dr_division} — KPIs ({CATEGORY_LABELS[category]})")
        uh.kpi_card_row(drow, category, ddelta)

        st.divider()
        st.subheader("Division Trend")
        dkpi = st.selectbox("KPI", KPI_OPTIONS, format_func=lambda k: KPI_LABELS[k], key="div_trend_kpi")
        dtrend = q_trend_table(con, "DIVISION", category, zone=dr_zone, circle=dr_circle, division=dr_division)
        uh.trend_line_chart(dtrend, dkpi, title=f"{dr_division} — {KPI_LABELS[dkpi]}", key="trend_division")

        st.divider()
        st.subheader("Category comparison (Overall vs Govt vs Non-Govt)")
        rows = []
        for cat in CATEGORIES:
            r = q_kpi_table(con, "DIVISION", cat, zone=dr_zone, circle=dr_circle, division=dr_division, **period_kwargs)
            if not r.empty:
                r = r.iloc[0].copy()
                r["category"] = CATEGORY_LABELS[cat]
                rows.append(r)
        cat_compare = pd.DataFrame(rows)
        display_cols = ["category"] + [k for k in KPI_OPTIONS]
        display_cols = [c for c in display_cols if c in cat_compare.columns]
        st.dataframe(cat_compare[display_cols].rename(columns=KPI_LABELS), width='stretch', hide_index=True)
        st.caption("Line Loss and Billing Efficiency are the OVERALL division's shared technical-loss "
                   "figures (input energy is not metered separately by Govt / Non-Govt) — see Methodology tab.")
        quick_export_buttons(cat_compare[display_cols], "division_category_compare", "Category Compare")

# =============================================================================
# TAB 5 — RANKINGS
# =============================================================================
# with tabs[4]:
#     st.subheader(" Best / Worst Ranking ")
#     r0, r1, r2, r3 = st.columns(4)
#     with r0:
#         rk_level = st.selectbox("Rank Unit", ["Division", "Circle", "Zone"], key="rk_level")
#     with r1:
#         rk_kpi_options = [k for k in KPI_OPTIONS if category in KPI_META[k]["category_scope"]]
#         rk_kpi = st.selectbox("By KPI", rk_kpi_options, format_func=lambda k: KPI_LABELS[k], key="rk_kpi")
#     with r2:
#         rk_mode = st.radio("Show", ["worst", "best"], horizontal=True, key="rk_mode",
#                             format_func=lambda m: "Worst" if m == "worst" else "Best")
#     with r3:
#         st.metric("Top / Bottom N", top_n)

#     rk_zone, rk_circle = None, None
#     if rk_level == "Circle":
#         scope = st.radio("Scope", ["DISCOM-wide", "Within a Zone"], horizontal=True, key="rk_scope_circle")
#         if scope == "Within a Zone":
#             rk_zone = st.selectbox("Zone", sorted(long_df["zone"].unique()), key="rk_zone_pick")
#     elif rk_level == "Division":
#         scope = st.radio("Scope", ["DISCOM-wide", "Within a Zone", "Within a Circle"], horizontal=True,
#                           key="rk_scope_div")
#         if scope in ("Within a Zone", "Within a Circle"):
#             rk_zone = st.selectbox("Zone", sorted(long_df["zone"].unique()), key="rk_zone_pick2")
#         if scope == "Within a Circle":
#             pool = sorted(long_df.loc[long_df["zone"] == rk_zone, "circle"].unique())
#             rk_circle = st.selectbox("Circle", pool, key="rk_circle_pick")

#     level_map = {"Division": "DIVISION", "Circle": "CIRCLE", "Zone": "ZONE"}
#     label_col_map = {"Division": "division", "Circle": "circle", "Zone": "zone"}

#     rank_df = q_rank_table(con, level_map[rk_level], category, rk_kpi, top_n=top_n, mode=rk_mode,
#                             zone=rk_zone, circle=rk_circle, **period_kwargs)

# #    cL, cR = st.columns([10, 3])
# #    with cL:
#     st.dataframe(rank_df, width='stretch', hide_index=True)
#     quick_export_buttons(rank_df, "ranking_table", "Ranking")
#     pdf_bytes = eu.to_pdf_bytes(rank_df, title=f"{rk_mode.title()} {top_n} {rk_level}(s) — {KPI_LABELS[rk_kpi]}",
#                                      subtitle=uh.period_caption(period_type, selected_month, fy_label))
#     st.download_button("Download PDF Report", pdf_bytes, file_name="ranking_report.pdf",
#                             mime="application/pdf", key="ranking_pdf")
#    with cR:
#        uh.rank_bar_chart(rank_df, rk_kpi, label_col_map[rk_level], mode=rk_mode, key="bar_rankings_main")

with tabs[4]:
    st.subheader("Best / Worst Rankings — All 6 KPIs")
    st.caption(
        "Worst N and Best N shown side-by-side for every KPI. "
        "Use the controls below to set the ranking unit, scope and N."
    )

    _rk_level_map  = {"Division": "DIVISION", "Circle": "CIRCLE", "Zone": "ZONE"}
    _rk_all_kpis   = [
        ("line_loss_pct",             "Line-Distribution Loss %"),
        ("billing_efficiency_pct",    "Billing Efficiency %"),
        ("collection_efficiency_pct", "Collection Efficiency %"),
        ("atc_loss_pct",              "AT&C Loss %"),
        ("through_rate",              "Through Rate (Rs-Unit)"),
        ("abr",                       "ABR (Rs-Unit)"),
    ]

    # ---- Filter controls (no By KPI selector) ----
    _rk_c0, _rk_c1, _rk_c2 = st.columns([1, 1, 5])
    with _rk_c0:
        rk_level = st.selectbox("Rank Unit", ["Division", "Circle", "Zone"], key="rk_level")
    with _rk_c1:
        st.metric("Top / Bottom N", top_n)

    rk_zone, rk_circle = None, None
    with _rk_c2:
        if rk_level == "Circle":
            scope = st.radio(
            "Scope", ["DISCOM-wide", "Within a Zone"],
            horizontal=True, key="rk_scope_circle"
            )
            if scope == "Within a Zone":
                rk_zone = st.selectbox("Zone", sorted(long_df["zone"].unique()), key="rk_zone_pick")
        elif rk_level == "Division":
            scope = st.radio(
            "Scope", ["DISCOM-wide", "Within a Zone", "Within a Circle"],
            horizontal=True, key="rk_scope_div"
        )
            if scope in ("Within a Zone", "Within a Circle"):
                rk_zone = st.selectbox("Zone", sorted(long_df["zone"].unique()), key="rk_zone_pick2")
            if scope == "Within a Circle":
                _rk_pool = sorted(long_df.loc[long_df["zone"] == rk_zone, "circle"].unique())
                rk_circle = st.selectbox("Circle", _rk_pool, key="rk_circle_pick")

    _rk_level_sql = _rk_level_map[rk_level]
    _rk_scope_note = (
        f"within **{rk_circle}**" if rk_circle else
        f"within **{rk_zone}**"   if rk_zone   else "DISCOM-wide"
    )

    st.caption(
        f"Ranking unit: **{rk_level}** | Scope: {_rk_scope_note} | "
        f"Category: **{CATEGORY_LABELS[category]}** | "
        f"{uh.period_caption(period_type, selected_month, fy_label)} | "
        f"Top / Bottom N = **{top_n}**"
    )

    # ---- One section per KPI, Worst | Best side-by-side ----
    for _rk_kpi, _rk_kpi_title in _rk_all_kpis:
        # skip KPIs not in scope for this category
        if category not in KPI_META.get(_rk_kpi, {}).get("category_scope", [category]):
            continue

#        st.divider()
#        st.markdown(f"### {_rk_kpi_title}")

        _rk_worst = q_rank_table(
            con, _rk_level_sql, category, _rk_kpi,
            top_n=top_n, mode="worst",
            zone=rk_zone, circle=rk_circle, **period_kwargs
        )
        _rk_best = q_rank_table(
            con, _rk_level_sql, category, _rk_kpi,
            top_n=top_n, mode="best",
            zone=rk_zone, circle=rk_circle, **period_kwargs
        )

        _rk_col_w, _rk_col_b = st.columns(2)
        with _rk_col_w:
            st.caption(f"⚠️ Worst {top_n} {rk_level}(s) — {_rk_kpi_title}")
            st.dataframe(_rk_worst, width='stretch', hide_index=True)
#            quick_export_buttons(_rk_worst, f"rk_worst_{_rk_kpi}", f"Worst {_rk_kpi_title}")
        with _rk_col_b:
            st.caption(f"✅ Best {top_n} {rk_level}(s) — {_rk_kpi_title}")
            st.dataframe(_rk_best, width='stretch', hide_index=True)
#            quick_export_buttons(_rk_best, f"rk_best_{_rk_kpi}", f"Best {_rk_kpi_title}")



# =============================================================================
# TAB 6 — MoM / YoY
# =============================================================================
with tabs[5]:
    # st.subheader("Month-on-Month and Year-on-Year Improvement")
    # st.caption("Compares the sidebar's selected month against the previous month (MoM) or the same "
    #            "month one fiscal year earlier (YoY). Both periods are independently summed-then-ratioed.")

    # m0, m1, m2 = st.columns(3)
    # with m0:
    #     compare_type = st.radio("Compare", ["MoM", "YoY"], horizontal=True, key="my_compare")
    # with m1:
    #     my_level = st.selectbox("Level", ["DISCOM", "Zone", "Circle", "Division"], key="my_level")
    # with m2:
    #     my_kpi_options = [k for k in KPI_OPTIONS if category in KPI_META[k]["category_scope"]]
    #     my_kpi = st.selectbox("KPI", my_kpi_options, format_func=lambda k: KPI_LABELS[k], key="my_kpi")

    # my_zone, my_circle = None, None
    # if my_level == "Circle":
    #     my_zone = st.selectbox("Within Zone (optional)", ["(DISCOM-wide)"] + sorted(long_df["zone"].unique()),
    #                             key="my_zone_pick")
    #     my_zone = None if my_zone == "(DISCOM-wide)" else my_zone
    # elif my_level == "Division":
    #     my_zone = st.selectbox("Zone (optional scope)", ["(DISCOM-wide)"] + sorted(long_df["zone"].unique()),
    #                             key="my_zone_pick2")
    #     my_zone = None if my_zone == "(DISCOM-wide)" else my_zone
    #     if my_zone:
    #         pool = sorted(long_df.loc[long_df["zone"] == my_zone, "circle"].unique())
    #         my_circle = st.selectbox("Circle (optional further scope)", ["(All circles in zone)"] + pool,
    #                                   key="my_circle_pick")
    #         my_circle = None if my_circle == "(All circles in zone)" else my_circle

    # level_map2 = {"DISCOM": "DISCOM", "Zone": "ZONE", "Circle": "CIRCLE", "Division": "DIVISION"}
    # label_col_map2 = {"DISCOM": "discom", "Zone": "zone", "Circle": "circle", "Division": "division"}

    # my_df = q_mom_yoy(con, level_map2[my_level], category, selected_month, compare=compare_type,
    #                    zone=my_zone, circle=my_circle)

    # if my_df.empty:
    #     st.warning(f"No comparable {compare_type} period exists in the dataset for {selected_month}.")
    # else:
    #     st.markdown(f"**{compare_type} comparison:** `{my_df.iloc[0]['current_month']}` vs "
    #                 f"`{my_df.iloc[0]['prior_month']}`")

    #     label_col = label_col_map2[my_level]
    #     show_cols = [label_col, f"{my_kpi}_prev", f"{my_kpi}_cur", f"{my_kpi}_delta", f"{my_kpi}_pct_change"]
    #     show_cols = [c for c in show_cols if c in my_df.columns]
    #     rename = {f"{my_kpi}_prev": "Previous", f"{my_kpi}_cur": "Current",
    #               f"{my_kpi}_delta": "Delta", f"{my_kpi}_pct_change": "% Change"}
    #     st.dataframe(my_df[show_cols].rename(columns=rename), width='stretch', hide_index=True)
    #     quick_export_buttons(my_df[show_cols].rename(columns=rename), "mom_yoy_table", "MoM-YoY")

    #     st.divider()
    #     st.subheader(f"Improvement Leaderboards — {KPI_LABELS[my_kpi]}")
    #     lb1, lb2 = st.columns(2)
    #     with lb1:
    #         st.caption(f"Most Improved (Top {top_n})")
    #         mi = rk.improvement_leaderboard(my_df, my_kpi, top_n=top_n, direction="most_improved")
    #         st.dataframe(mi[["rank", label_col, f"{my_kpi}_delta"]], width='stretch', hide_index=True)
    #         uh.leaderboard_bar_chart(mi, my_kpi, label_col, "most_improved", key="bar_mom_most_improved")
    #     with lb2:
    #         st.caption(f"Most Deteriorated (Top {top_n})")
    #         md = rk.improvement_leaderboard(my_df, my_kpi, top_n=top_n, direction="most_deteriorated")
    #         st.dataframe(md[["rank", label_col, f"{my_kpi}_delta"]], width='stretch', hide_index=True)
    #         uh.leaderboard_bar_chart(md, my_kpi, label_col, "most_deteriorated", key="bar_mom_most_deteriorated")

    st.subheader("Month-on-Month and Year-on-Year Improvement")
    st.caption(
        "Compares the sidebar's selected month against the previous month (MoM) or "
        "the same month one fiscal year earlier (YoY). "
        "All 6 KPIs shown one below the other for the selected level and scope. "
        "Both periods are independently summed-then-ratioed."
    )

    # ── Controls (no KPI filter) ──────────────────────────────────────────────
    _m0, _m1 = st.columns(2)
    with _m0:
        compare_type = st.radio(
            "Compare", ["MoM", "YoY"], horizontal=True, key="my_compare"
        )
    with _m1:
        my_level = st.selectbox(
            "Level", ["DISCOM", "Zone", "Circle", "Division"], key="my_level"
        )

    my_zone, my_circle = None, None
    if my_level == "Circle":
        my_zone = st.selectbox(
            "Within Zone (optional)",
            ["(DISCOM-wide)"] + sorted(long_df["zone"].unique()),
            key="my_zone_pick",
        )
        my_zone = None if my_zone == "(DISCOM-wide)" else my_zone
    elif my_level == "Division":
        _dz0, _dz1 = st.columns(2)
        with _dz0:
            my_zone = st.selectbox(
                "Zone (optional scope)",
                ["(DISCOM-wide)"] + sorted(long_df["zone"].unique()),
                key="my_zone_pick2",
            )
            my_zone = None if my_zone == "(DISCOM-wide)" else my_zone
        with _dz1:
            if my_zone:
                _pool = sorted(long_df.loc[long_df["zone"] == my_zone, "circle"].unique())
                my_circle = st.selectbox(
                    "Circle (optional further scope)",
                    ["(All circles in zone)"] + _pool,
                    key="my_circle_pick",
                )
                my_circle = None if my_circle == "(All circles in zone)" else my_circle

    _level_map2     = {"DISCOM": "DISCOM", "Zone": "ZONE", "Circle": "CIRCLE", "Division": "DIVISION"}
    _label_col_map2 = {"DISCOM": "discom", "Zone": "zone",  "Circle": "circle", "Division": "division"}
    _level_sql  = _level_map2[my_level]
    _label_col  = _label_col_map2[my_level]

    # ── Fetch delta data for the selected level / compare type ────────────────
    my_df = q_mom_yoy(
        con, _level_sql, category, selected_month,
        compare=compare_type, zone=my_zone, circle=my_circle,
    )

    if my_df.empty:
        st.warning(
            f"No comparable {compare_type} period exists in the dataset "
            f"for **{selected_month}**."
        )
    else:
        _cur_month_lbl  = my_df.iloc[0]["current_month"]
        _prev_month_lbl = my_df.iloc[0]["prior_month"]

        st.markdown(
            f"**{compare_type} comparison:** `{_cur_month_lbl}` vs `{_prev_month_lbl}` "
            f"| Level: **{my_level}** | Category: **{CATEGORY_LABELS[category]}**"
        )

        # Round numeric cols to 2 dp
        _my_df_r = my_df.copy()
        for _c in _my_df_r.select_dtypes(include="float").columns:
            _my_df_r[_c] = _my_df_r[_c].round(2)

        # ── All 6 KPI tables, one below another ──────────────────────────────
        _ALL_KPIS_MOM = [
            "atc_loss_pct",
            "line_loss_pct",
            "billing_efficiency_pct",
            "collection_efficiency_pct",
            "through_rate",
            "abr",
        ]
        _KPI_SHORT = {
            "atc_loss_pct":             "AT&C Loss %",
            "line_loss_pct":            "Line Loss %",
            "billing_efficiency_pct":   "Billing Eff %",
            "collection_efficiency_pct":"Coll Eff %",
            "through_rate":             "Through Rate",
            "abr":                      "ABR",
        }
        _LIB_MOM = {
            "atc_loss_pct": True, "line_loss_pct": True,
            "billing_efficiency_pct": False, "collection_efficiency_pct": False,
            "through_rate": False, "abr": False,
        }

        for _idx, _kpi in enumerate(_ALL_KPIS_MOM):
            _dc  = f"{_kpi}_delta"
            _pc  = f"{_kpi}_pct_change"
            _cc  = f"{_kpi}_cur"
            _pvc = f"{_kpi}_prev"

            # Direction helpers
            _lib         = _LIB_MOM[_kpi]
            _good_dir    = "⬇ lower is better" if _lib else "⬆ higher is better"
            _imp_hint    = "Δ negative = improved" if _lib else "Δ positive = improved"

            # Sort: worst improvement first
            _sorted_df = _my_df_r.sort_values(_dc, ascending=not _lib).reset_index(drop=True)

            # Build display columns:
            # [label] | Δ | % Chg | Current | Prior | (other KPIs current values)
            _other_cur_cols  = [f"{k}_cur" for k in _ALL_KPIS_MOM if k != _kpi
                                  and f"{k}_cur" in _sorted_df.columns]
            _other_cur_names = {f"{k}_cur": _KPI_SHORT[k]
                                 for k in _ALL_KPIS_MOM if k != _kpi}

            _sel_cols = (
                [_label_col] +
                [_dc, _pc, _cc, _pvc] +
                _other_cur_cols
            )
            _sel_cols = [c for c in _sel_cols if c in _sorted_df.columns]
            _disp = _sorted_df[_sel_cols].copy()

            # Rank column (1 = worst improvement)
            _rk_col = [str(i + 1) for i in range(len(_disp))]
            _disp.insert(0, "#", _rk_col)

            # Rename
            _col_rn = {
                _label_col: my_level,
                _dc:        f"Δ {_KPI_SHORT[_kpi]}",
                _pc:        "% Chg",
                _cc:        f"{_KPI_SHORT[_kpi]} ({_cur_month_lbl})",
                _pvc:       f"{_KPI_SHORT[_kpi]} ({_prev_month_lbl})",
            } | _other_cur_names
            _disp = _disp.rename(columns=_col_rn)

            st.divider()
            st.markdown(
                f"### {_KPI_SHORT[_kpi]}"
                f"&nbsp;&nbsp;<span style='font-size:0.85rem;font-weight:400;"
                f"color:#5F6368'>{_good_dir} &nbsp;|&nbsp; {_imp_hint}</span>",
                unsafe_allow_html=True,
            )
            st.dataframe(_disp, width="stretch", hide_index=True)
            quick_export_buttons(
                _disp,
                f"mom_yoy_{_kpi}_{compare_type.lower()}",
                f"{_KPI_SHORT[_kpi]} {compare_type}",
            )

        # ── Improvement Leaderboards for all KPIs (compact, 2 cols per KPI) ──
        st.divider()
        st.subheader(f"Improvement Leaderboards — All KPIs ({compare_type})")
        st.caption(
            f"Most improved and most deteriorated {my_level}s "
            f"for each KPI | Top {top_n} each."
        )

        for _kpi in _ALL_KPIS_MOM:
            _dc  = f"{_kpi}_delta"
            if _dc not in _my_df_r.columns:
                continue
            _lib = _LIB_MOM[_kpi]

            st.markdown(f"**{_KPI_SHORT[_kpi]}**")
            _lb1, _lb2 = st.columns(2)
            with _lb1:
                st.caption(f"Most Improved — Top {top_n}")
                _mi = rk.improvement_leaderboard(
                    _my_df_r, _kpi, top_n=top_n, direction="most_improved"
                )
                _mi_cols = [c for c in ["rank", _label_col, _dc, f"{_kpi}_pct_change"]
                             if c in _mi.columns]
                _mi_rn   = {_label_col: my_level, _dc: "Δ", f"{_kpi}_pct_change": "% Chg"}
                st.dataframe(
                    _mi[_mi_cols].rename(columns=_mi_rn),
                    width="stretch", hide_index=True,
                )
            with _lb2:
                st.caption(f"Most Deteriorated — Top {top_n}")
                _md = rk.improvement_leaderboard(
                    _my_df_r, _kpi, top_n=top_n, direction="most_deteriorated"
                )
                _md_cols = [c for c in ["rank", _label_col, _dc, f"{_kpi}_pct_change"]
                             if c in _md.columns]
                _md_rn   = {_label_col: my_level, _dc: "Δ", f"{_kpi}_pct_change": "% Chg"}
                st.dataframe(
                    _md[_md_cols].rename(columns=_md_rn),
                    width="stretch", hide_index=True,
                )



# =============================================================================
# TAB 7 — DATA EXPLORER & EXPORT
# =============================================================================
with tabs[6]:
    st.subheader("Data Explorer")
    st.caption("Filter the Division-level KPI table below, then export to CSV, Excel or PDF. "
               "Click any column header to sort.")

    f0, f1, f2 = st.columns(3)
    with f0:
        ex_zones = st.multiselect("Zone(s)", sorted(long_df["zone"].unique()), key="ex_zones")
    pool_c = long_df[long_df["zone"].isin(ex_zones)] if ex_zones else long_df
    with f1:
        ex_circles = st.multiselect("Circle(s)", sorted(pool_c["circle"].unique()), key="ex_circles")
    pool_d = pool_c[pool_c["circle"].isin(ex_circles)] if ex_circles else pool_c
    with f2:
        ex_divisions = st.multiselect("Division(s)", sorted(pool_d["division"].unique()), key="ex_divisions")

    f3, f4 = st.columns([1, 2])
    with f3:
        ex_categories = st.multiselect("Category", CATEGORIES, default=["OVERALL"],
                                        format_func=lambda c: CATEGORY_LABELS[c], key="ex_categories")
    with f4:
        ex_months = st.multiselect("Month(s)", month_options, default=[selected_month], key="ex_months")

    if not ex_categories or not ex_months:
        st.info("Select at least one category and one month to populate the table.")
        explorer_df = pd.DataFrame()
    else:
        explorer_df = q_explorer(con, tuple(ex_categories), tuple(ex_months),
                                  tuple(ex_zones), tuple(ex_circles), tuple(ex_divisions))

    if not explorer_df.empty:
        display_cols = ["zone", "circle", "division", "category", "month"] if "month" in explorer_df.columns \
            else ["zone", "circle", "division", "category"]
        display_cols = [c for c in (["zone", "circle", "division", "category"]) if c in explorer_df.columns] + \
                        [c for c in KPI_OPTIONS if c in explorer_df.columns]
        st.dataframe(explorer_df[display_cols].rename(columns=KPI_LABELS), width='stretch', hide_index=True)
        st.caption(f"{len(explorer_df):,} rows")

        st.divider()
        st.subheader("Export filtered view")
        ce1, ce2, ce3 = st.columns(3)
        export_df = explorer_df[display_cols].rename(columns=KPI_LABELS)
        with ce1:
            st.download_button("Download CSV", eu.to_csv_bytes(export_df), file_name="atc_filtered_export.csv",
                                mime="text/csv", width='stretch')
        with ce2:
            st.download_button("Download Excel", eu.to_excel_bytes(export_df, "Filtered Data"),
                                file_name="atc_filtered_export.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                width='stretch')
        with ce3:
            pdf_bytes = eu.to_pdf_bytes(export_df, title="DVVNL AT&C Filtered Data Export",
                                         subtitle=f"{len(ex_categories)} categor(y/ies), {len(ex_months)} month(s)")
            st.download_button("Download PDF Report", pdf_bytes, file_name="atc_filtered_export.pdf",
                                mime="application/pdf", width='stretch')
    else:
        st.info("No rows match the current filter selection.")

# =============================================================================
# TAB 8 — METHODOLOGY & NOTES
# =============================================================================
# with tabs[7]:
#     st.subheader("Methodology & Data Notes")

#     st.markdown("""
# **Data hierarchy:** DISCOM → Zone → Circle → Division. Division-level monthly figures are summed
# upward to Circle, Zone and DISCOM — the dashboard never averages a percentage directly; it always
# sums the absolute quantities (Input Energy, Unit Sold, Assessment, Realisation) for whatever rows
# are in scope, then recomputes every ratio KPI from those summed numerators/denominators.

# **Fiscal Year:** Indian power-utility FY runs April → March. "Progressive / Cumulative" figures
# sum April-of-the-FY through the selected month, within the same FY (a month in April only covers
# that one month; a month in March covers the full preceding 11 months too).

# **KPI formulas applied after the sum-then-ratio step:**
# """)
#     formula_rows = [{"KPI": v["label"], "Formula": v["formula"], "Unit": v["unit"],
#                       "Direction": "Lower is better" if v["lower_is_better"] else "Higher is better",
#                       "Govt / Non-Govt treatment": ("Shared with OVERALL (technical loss not split by category)"
#                                                      if v.get("shared_as_overall")
#                                                      else "Category-specific")}
#                      for v in KPI_META.values()]
#     st.dataframe(pd.DataFrame(formula_rows), width='stretch', hide_index=True)

#     st.markdown("""
# **How Line Loss / Billing Efficiency / Through Rate work for Government / Non-Government:**
# UPPCL/DVVNL meters "Input Energy" at the feeder/transformer (division) level only — it is a
# technical quantity, not split by consumer billing category. So Line Loss % and Billing Efficiency %
# for Govt and Non-Govt are set equal to the OVERALL division's own values (the shared technical loss
# rate cannot be attributed to Govt vs Non-Govt connections specifically). Through Rate, however, uses
# the category's OWN Realisation over that same OVERALL Input Energy, so it DOES differentiate
# meaningfully between Govt and Non-Govt. Collection Efficiency and ABR are fully category-specific
# throughout because Assessment, Realisation and Unit Sold are all split by category in the source file.

# **How AT&C Loss is computed for Govt / Non-Govt:**
# AT&C Loss (Govt/Non-Govt) = 100 − (OVERALL Billing Efficiency × category's own Collection
# Efficiency / 100). The technical loss component is shared across all consumers on a feeder (it
# cannot be attributed to Govt vs Non-Govt connections specifically), so the dashboard borrows the
# division's OVERALL Billing Efficiency and combines it with the category's own Collection
# Efficiency. This was verified numerically against the source CSV's own "GOVERNMENT ATC Loss" /
# "NON GOVERNMENT ATC Loss" columns and matches DVVNL's published figures to within rounding.
# """)

#     st.divider()
#     st.subheader("Worked example (live, from the current data file)")
#     example_division = long_df["division"].iloc[0]
#     example_month = month_options[-1]
#     ex_zone = long_df.loc[long_df["division"] == example_division, "zone"].iloc[0]
#     ex_circle = long_df.loc[long_df["division"] == example_division, "circle"].iloc[0]
#     ov = q_kpi_table(con, "DIVISION", "OVERALL", "single", month=example_month,
#                       zone=ex_zone, circle=ex_circle, division=example_division)
#     gv = q_kpi_table(con, "DIVISION", "GOVT", "single", month=example_month,
#                       zone=ex_zone, circle=ex_circle, division=example_division)
#     ng = q_kpi_table(con, "DIVISION", "NON_GOVT", "single", month=example_month,
#                       zone=ex_zone, circle=ex_circle, division=example_division)
#     if not ov.empty and not gv.empty and not ng.empty:
#         be = ov.iloc[0]["billing_efficiency_pct"]
#         ll = ov.iloc[0]["line_loss_pct"]
#         ce = gv.iloc[0]["collection_efficiency_pct"]
#         atc = gv.iloc[0]["atc_loss_pct"]
#         tr_govt = gv.iloc[0]["through_rate"]
#         tr_nongovt = ng.iloc[0]["through_rate"]
#         tr_overall = ov.iloc[0]["through_rate"]
#         st.markdown(f"""
# For **{example_division}** ({example_month}):
# - OVERALL Line Loss = `{ll:.2f}%`, OVERALL Billing Efficiency = `{be:.2f}%` — **carried across
#   unchanged** to the Govt and Non-Govt views.
# - GOVT Collection Efficiency = `{ce:.2f}%`
# - GOVT AT&C Loss = 100 − ({be:.2f} × {ce:.2f} / 100) = **`{atc:.2f}%`**
# - Through Rate differentiates by category despite sharing the OVERALL Input Energy base:
#   OVERALL = `Rs {tr_overall:.2f}/Unit`, GOVT = `Rs {tr_govt:.2f}/Unit`, NON-GOVT = `Rs {tr_nongovt:.2f}/Unit`
#   (each is that category's own Realisation ÷ the OVERALL division's Input Energy).
# """)

#     st.divider()
#     st.subheader("Architecture")
#     st.markdown("""
# | Module | Responsibility |
# |---|---|
# | `data_loader.py` | Loads the wide CSV, auto-maps columns by keyword, reshapes to tidy long format with a `category` column |
# | `kpi_engine.py` | DuckDB SQL aggregation (sum-then-ratio) for any hierarchy level / category / period |
# | `ranking.py` | Top/Bottom-N ranking engine, MoM/YoY comparison, improvement leaderboards |
# | `export_utils.py` | CSV / Excel (openpyxl) / PDF (reportlab) export |
# | `ui_helpers.py` | Shared Streamlit/Plotly/Altair rendering helpers |
# | `app.py` | Streamlit UI — sidebar filters + 8 review tabs |

# Caching: `st.cache_data` on the CSV load/reshape and on every DuckDB query wrapper;
# `st.cache_resource` on the DuckDB connection itself, per the spec.
# """)

# =============================================================================
# TAB 9 — KPI ANALYTICS (level-wise comparative table + worst/best engine)
# =============================================================================
with tabs[7]:
    AN_KPIS = ["line_loss_pct", "billing_efficiency_pct", "collection_efficiency_pct",
               "atc_loss_pct", "through_rate", "abr"]
    AN_LEVEL_MAP = {"Zone": "ZONE", "Circle": "CIRCLE", "Division": "DIVISION"}
    AN_ID_COLS = {"Zone": ["zone"], "Circle": ["zone", "circle"], "Division": ["zone", "circle", "division"]}
    DISCOM_LABEL = "DVVNL (DISCOM Total)"

    st.subheader("Level-wise KPI Comparative Table")
    st.caption("All six KPIs, column-wise, for the selected hierarchy level — with the DVVNL DISCOM "
               "total as the last row in every view. Set Category / Month / comparison basis below.")

    a0, a1, a2, a3 = st.columns([1.3, 1, 1.1, 1])
    with a0:
        an_category = st.radio("Category", CATEGORIES, format_func=lambda c: CATEGORY_LABELS[c],
                                horizontal=True, key="an_category",
                                index=CATEGORIES.index(category))
    with a1:
        an_month = st.selectbox("Month", month_options, index=month_options.index(selected_month),
                                 key="an_month")
    with a2:
        an_level = st.radio("View by", ["Zone", "Circle", "Division"], horizontal=True, key="an_level")
    with a3:
        an_compare = st.radio("Comparison", ["None", "MoM", "YoY"], horizontal=True, key="an_compare",
                               help="Adds a Δ column next to every KPI showing change vs the previous "
                                    "month (MoM) or the same month last fiscal year (YoY).")

    an_level_sql = AN_LEVEL_MAP[an_level]
    an_id_cols = AN_ID_COLS[an_level]

    # ---- current-period values at the chosen level, + DISCOM total row ----
    cur_tbl = q_kpi_table(con, an_level_sql, an_category, "single", month=an_month)
    discom_cur = q_kpi_table(con, "DISCOM", an_category, "single", month=an_month).rename(
        columns={"discom": an_id_cols[-1]})
    for c in an_id_cols:
        if c not in discom_cur.columns:
            discom_cur[c] = ""
    discom_cur[an_id_cols[-1]] = DISCOM_LABEL
    cur_combined = pd.concat([cur_tbl, discom_cur], ignore_index=True)

    if an_compare == "None":
        show_df = cur_combined[an_id_cols + AN_KPIS].rename(columns=KPI_LABELS)
        cap = f"{an_level}-wise KPIs for **{an_month}** ({CATEGORY_LABELS[an_category]})."
    else:
        my_now = q_mom_yoy(con, an_level_sql, an_category, an_month, compare=an_compare)
        my_discom = q_mom_yoy(con, "DISCOM", an_category, an_month, compare=an_compare)
        if my_now.empty and my_discom.empty:
            st.warning(f"No comparable {an_compare} period exists in the dataset for {an_month}.")
            show_df = pd.DataFrame()
            cap = ""
        else:
            if not my_discom.empty:
                my_discom = my_discom.rename(columns={"discom": an_id_cols[-1]})
                for c in an_id_cols:
                    if c not in my_discom.columns:
                        my_discom[c] = ""
                my_discom[an_id_cols[-1]] = DISCOM_LABEL
            my_combined = pd.concat([my_now, my_discom], ignore_index=True) if not my_now.empty else my_discom

            out = {}
            for c in an_id_cols:
                out[c] = my_combined[c].reset_index(drop=True)
            for k in AN_KPIS:
                out[KPI_LABELS[k]] = my_combined[f"{k}_cur"].reset_index(drop=True)
                out[f"Δ {KPI_LABELS[k]}"] = my_combined[f"{k}_delta"].reset_index(drop=True)
            show_df = pd.DataFrame(out)
            prior_label = my_combined["prior_month"].iloc[0] if "prior_month" in my_combined.columns and len(my_combined) else "?"
            cap = (f"{an_level}-wise KPIs for **{an_month}** vs **{prior_label}** "
                   f"({an_compare}, {CATEGORY_LABELS[an_category]}). Δ = current minus prior period.")

    if not show_df.empty:
        st.caption(cap)
        st.dataframe(show_df, width='stretch', hide_index=True)
        quick_export_buttons(show_df, f"analytics_{an_level.lower()}_table", f"{an_level} KPI Table")
        st.caption("Last row is the DVVNL DISCOM-wide total. Click a column header to sort.")

    st.divider()
    st.subheader("Worst / Best N — by KPI")
    st.caption(f"DISCOM-wide ranking for **{an_month}** ({CATEGORY_LABELS[an_category]}). "
               f"Use the dedicated Rankings tab for Zone/Circle-scoped ranking.")
    b0, b1, b2 = st.columns(3)
    with b0:
        an_rank_level = st.selectbox("Level", ["Division", "Circle", "Zone"], key="an_rank_level")
    with b1:
        an_rank_kpi_opts = AN_KPIS
        an_rank_kpi = st.selectbox("KPI", an_rank_kpi_opts, format_func=lambda k: KPI_LABELS[k],
                                    key="an_rank_kpi")
    with b2:
        an_top_n = st.number_input("N", min_value=3, max_value=25, value=int(top_n), key="an_top_n")

    an_level_sql2 = AN_LEVEL_MAP[an_rank_level]
    an_worst = q_rank_table(con, an_level_sql2, an_category, an_rank_kpi, "single", month=an_month,
                             top_n=an_top_n, mode="worst")
    an_best = q_rank_table(con, an_level_sql2, an_category, an_rank_kpi, "single", month=an_month,
                            top_n=an_top_n, mode="best")

    rc1, rc2 = st.columns(2)
    with rc1:
        st.caption(f"Worst {an_top_n} {an_rank_level}(s) — {KPI_LABELS[an_rank_kpi]}")
        st.dataframe(an_worst, width='stretch', hide_index=True)
        quick_export_buttons(an_worst, "analytics_worst_n", "Analytics Worst N")
    with rc2:
        st.caption(f"Best {an_top_n} {an_rank_level}(s) — {KPI_LABELS[an_rank_kpi]}")
        st.dataframe(an_best, width='stretch', hide_index=True)
        quick_export_buttons(an_best, "analytics_best_n", "Analytics Best N")


# =============================================================================
# TAB 9 — SLAB ANALYTICS
# =============================================================================
with tabs[8]:

    render_slab_analytics_tab(
        con, long_df, category, period_kwargs, period_type,
        selected_month, month_options, KPI_LABELS,
    )


# =============================================================================
# TAB 10 — CONSOLIDATED REPORT (Overall / Govt / Non-Govt single-row view)
# =============================================================================
with tabs[9]:
    render_consolidated_report_tab(
        con, long_df, period_kwargs, period_type,
        selected_month, month_options,
    )