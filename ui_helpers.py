"""
ui_helpers.py
=============
Shared Streamlit/Plotly/Altair rendering helpers used across every tab of
app.py, kept separate so app.py stays readable.
"""

from __future__ import annotations
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import altair as alt

from config import KPI_META, CATEGORY_LABELS, PRIMARY_COLOR, ACCENT_COLOR, GOOD_COLOR, BAD_COLOR, \
    PLOTLY_TEMPLATE, ZONE_COLOR_SEQUENCE


def fmt_value(val, kpi):
    if pd.isna(val):
        return "N/A"
    unit = KPI_META[kpi]["unit"]
    if unit == "%":
        return f"{val:,.2f}%"
    return f"Rs {val:,.2f}"


def kpi_applicable(kpi, category):
    return category in KPI_META[kpi]["category_scope"]


def kpi_card_row(row: pd.Series, category: str, delta_row: pd.Series | None = None,
                  kpis=("atc_loss_pct", "line_loss_pct", "billing_efficiency_pct",
                        "collection_efficiency_pct", "through_rate", "abr")):
    """Render a row of st.metric KPI cards for one aggregated KPI result row.
    `delta_row` (optional) supplies the prior period's same-row values so a
    MoM delta arrow can be shown (red/green is direction-aware per KPI)."""
    cols = st.columns(len(kpis))
    for col, kpi in zip(cols, kpis):
        meta = KPI_META[kpi]
        applicable = kpi_applicable(kpi, category)
        with col:
            if not applicable:
                st.metric(meta["label"], "N/A", help=f"{meta['label']} requires Input Energy, which the "
                                                       f"source data only provides at OVERALL level (not "
                                                       f"split by Govt/Non-Govt). See Methodology tab.")
                continue
            val = row.get(kpi)
            delta_str = None
            if delta_row is not None and pd.notna(delta_row.get(kpi)) and pd.notna(val):
                d = val - delta_row.get(kpi)
                delta_str = f"{d:+.2f}"
            help_text = f"Formula: {meta['formula']}"
            if meta.get("shared_as_overall") and category != "OVERALL":
                help_text += (" -- Input Energy is not metered separately by Govt/Non-Govt, so this "
                               "is the OVERALL division's shared technical-loss figure, carried across "
                               "to this category view. See Methodology tab.")
            st.metric(
                meta["label"],
                fmt_value(val, kpi),
                delta=delta_str,
                delta_color="inverse" if meta["lower_is_better"] else "normal",
                help=help_text,
            )


def trend_line_chart(trend_df: pd.DataFrame, kpi: str, group_col: str | None = None,
                      title: str | None = None, key: str | None = None):
    """Plotly line chart of a KPI over the available months, optionally one
    line per `group_col` (e.g. 'zone')."""
    meta = KPI_META[kpi]
    df = trend_df.dropna(subset=[kpi]).copy()
    if df.empty:
        st.info("No data available for this selection.")
        return
    color_arg = group_col if group_col and group_col in df.columns else None
    fig = px.line(
        df, x="month", y=kpi, color=color_arg, markers=True,
        category_orders={"month": list(df.sort_values("seq_index")["month"].unique())},
        color_discrete_sequence=ZONE_COLOR_SEQUENCE,
        template=PLOTLY_TEMPLATE,
        labels={kpi: f"{meta['label']} ({meta['unit']})", "month": "Month"},
        title=title or f"{meta['label']} Trend",
    )
    fig.update_layout(height=380, legend_title_text=group_col.title() if group_col else None,
                       margin=dict(t=50, b=10, l=10, r=10))
    st.plotly_chart(fig, width='stretch', key=key)


def altair_sparkline(trend_df: pd.DataFrame, kpi: str, height: int = 90):
    meta = KPI_META[kpi]
    df = trend_df.dropna(subset=[kpi]).sort_values("seq_index")
    if df.empty:
        return None
    chart = (
        alt.Chart(df)
        .mark_line(point=True, color=PRIMARY_COLOR)
        .encode(
            x=alt.X("month:N", sort=list(df["month"]), axis=None),
            y=alt.Y(f"{kpi}:Q", axis=None),
            tooltip=["month", alt.Tooltip(f"{kpi}:Q", format=".2f", title=meta["label"])],
        )
        .properties(height=height)
    )
    return chart


def rank_bar_chart(rank_df: pd.DataFrame, kpi: str, label_col: str, mode: str = "worst",
                    key: str | None = None):
    meta = KPI_META[kpi]
    df = rank_df.dropna(subset=[kpi]).copy()
    if df.empty:
        st.info("No data available for this selection.")
        return
    color = BAD_COLOR if mode == "worst" else GOOD_COLOR
    df = df.sort_values(kpi, ascending=(mode != "worst"))
    fig = px.bar(
        df, x=kpi, y=label_col, orientation="h",
        template=PLOTLY_TEMPLATE,
        labels={kpi: f"{meta['label']} ({meta['unit']})", label_col: label_col.title()},
        text=df[kpi].round(2),
    )
    fig.update_traces(marker_color=color)
    fig.update_layout(height=max(280, 38 * len(df)), margin=dict(t=20, b=10, l=10, r=10),
                       yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, width='stretch', key=key)


def leaderboard_bar_chart(lb_df: pd.DataFrame, kpi: str, label_col: str, direction: str,
                           key: str | None = None):
    meta = KPI_META[kpi]
    delta_col = f"{kpi}_delta"
    df = lb_df.dropna(subset=[delta_col]).copy()
    if df.empty:
        st.info("No comparable data available.")
        return
    color = GOOD_COLOR if direction == "most_improved" else BAD_COLOR
    fig = px.bar(
        df, x=delta_col, y=label_col, orientation="h",
        template=PLOTLY_TEMPLATE,
        labels={delta_col: f"Change in {meta['label']} ({meta['unit']})", label_col: label_col.title()},
        text=df[delta_col].round(2),
    )
    fig.update_traces(marker_color=color)
    fig.update_layout(height=max(280, 38 * len(df)), margin=dict(t=20, b=10, l=10, r=10),
                       yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, width='stretch', key=key)


def style_kpi_table(df: pd.DataFrame):
    """Return a pandas Styler with red/green text on loss-direction KPI
    columns, for use in st.dataframe."""
    fmt = {}
    for kpi, meta in KPI_META.items():
        if kpi in df.columns:
            fmt[kpi] = "{:.2f}" + ("%" if meta["unit"] == "%" else "")
    styler = df.style.format(fmt, na_rep="N/A")
    for kpi, meta in KPI_META.items():
        if kpi not in df.columns:
            continue
        if meta["lower_is_better"]:
            styler = styler.background_gradient(subset=[kpi], cmap="Reds")
        else:
            styler = styler.background_gradient(subset=[kpi], cmap="Greens")
    return styler


def period_caption(period_type: str, month: str, fy_label: str | None = None) -> str:
    if period_type == "single":
        return f"Viewing Data for **{month}**"
    return f"Viewing Progressive / Cumulative **{fy_label}** (From Apr {fy_label.split('-')[0]} To **{month}**)"
