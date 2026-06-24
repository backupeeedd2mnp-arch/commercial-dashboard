"""
slab_analytics.py
====================
"Slab Analytics" tab — bucket every Division/Circle/Zone into slabs (bands)
of each KPI (Distribution Loss, Billing Efficiency, Collection Efficiency,
AT&C Loss, Through Rate, ABR), show a summary matrix of slab-wise counts at
each hierarchy level (mirroring the Excel-style layout supplied as a
reference image), let the user click any count to drill into the underlying
unit records (AgGrid), and provide a cascading multi-KPI AND/OR filter
builder so reviewers can isolate units meeting several slab criteria at
once (e.g. "Billing Efficiency 70-80% AND Collection Efficiency <70%").

Public entry point
--------------------
render_slab_analytics_tab(con, long_df, category, period_kwargs, period_type,
                           selected_month, month_options, KPI_LABELS)

Everything else in this module is implementation detail.

Why AgGrid
-----------
st.dataframe does not support clickable cells that trigger a Python-side
action. streamlit-aggrid (`st_aggrid`) does, via `JsCode` cell renderers +
`GridOptionsBuilder` selection callbacks, which is how the "click a slab
count -> see the underlying units" drill-down is implemented here.

If `streamlit-aggrid` is not installed, the module degrades gracefully:
slab counts render as a plain st.dataframe with a manual "view details"
selectbox fallback instead of true clickable cells.
"""

from __future__ import annotations
import pandas as pd
import streamlit as st

import kpi_engine as ke
from config import KPI_META, CATEGORIES, CATEGORY_LABELS

try:
    from st_aggrid import AgGrid, GridOptionsBuilder, JsCode, GridUpdateMode, DataReturnMode
    AGGRID_AVAILABLE = True
except Exception:
    AGGRID_AVAILABLE = False


# ---------------------------------------------------------------------------
# Slab definitions
# ---------------------------------------------------------------------------
# Each KPI maps to an ordered list of (label, lower_inclusive, upper_exclusive).
# `None` means unbounded on that side. These mirror the reference layout
# (e.g. Billing/Collection Efficiency: <70, 70-80, 80-90, >90) while keeping
# AT&C / Line Loss in finer 5-point bands and Through Rate / ABR in Rs/Unit
# bands, since these are typically reviewed at a different granularity.
SLAB_DEFS = {
    "line_loss_pct": [
        ("<10%", None, 10), ("10-15%", 10, 15), ("15-20%", 15, 20),
        ("20-25%", 20, 25), ("25-30%", 25, 30), (">30%", 30, None),
    ],
    "billing_efficiency_pct": [
        ("<70%", None, 70), ("70-80%", 70, 80), ("80-90%", 80, 90), (">90%", 90, None),
    ],
    "collection_efficiency_pct": [
        ("<70%", None, 70), ("70-80%", 70, 80), ("80-90%", 80, 90), (">90%", 90, None),
    ],
    "atc_loss_pct": [
        ("<15%", None, 15), ("15-20%", 15, 20), ("20-25%", 20, 25),
        ("25-30%", 25, 30), ("30-35%", 30, 35), ("35-40%", 35, 40), (">40%", 40, None),
    ],
    "through_rate": [
        ("<3", None, 3), ("3-4", 3, 4), ("4-5", 4, 5), ("5-6", 5, 6), (">6", 6, None),
    ],
    "abr": [
        ("<4", None, 4), ("4-5", 4, 5), ("5-6", 5, 6), ("6-7", 6, 7), (">7", 7, None),
    ],
}

SLAB_KPI_ORDER = ["billing_efficiency_pct", "collection_efficiency_pct", "atc_loss_pct",
                   "line_loss_pct", "through_rate", "abr"]

LEVEL_SQL_MAP = {"Division": "DIVISION", "Circle": "CIRCLE", "Zone": "ZONE"}
LEVEL_ID_COLS = {"Division": ["zone", "circle", "division"],
                  "Circle": ["zone", "circle"],
                  "Zone": ["zone"]}


def _assign_slab(value: float, kpi: str) -> str:
    if pd.isna(value):
        return "NA"
    for label, lo, hi in SLAB_DEFS[kpi]:
        if (lo is None or value >= lo) and (hi is None or value < hi):
            return label
    return "NA"


def _slab_order(kpi: str) -> list:
    return [s[0] for s in SLAB_DEFS[kpi]]


@st.cache_data(show_spinner=False)
def _build_unit_table(_con, category: str, period_type: str, month=None,
                       upto_month_seq=None, fy_label=None) -> dict:
    """
    Build the three base unit-level KPI tables (Division, Circle, Zone) for
    the selected category/period, with a slab column attached for every KPI.
    Returns {'Division': df, 'Circle': df, 'Zone': df}.
    """
    out = {}
    for level_label, level_sql in LEVEL_SQL_MAP.items():
        df = ke.kpi_table(_con, level_sql, category, period_type, month=month,
                           upto_month_seq=upto_month_seq, fy_label=fy_label)
        for kpi in SLAB_KPI_ORDER:
            df[f"{kpi}__slab"] = df[kpi].apply(lambda v, k=kpi: _assign_slab(v, k))
        out[level_label] = df
    return out


def _discom_value(_con, category: str, kpi: str, period_type: str, month=None,
                   upto_month_seq=None, fy_label=None) -> float:
    discom_df = ke.kpi_table(_con, "DISCOM", category, period_type, month=month,
                              upto_month_seq=upto_month_seq, fy_label=fy_label)
    if discom_df.empty or kpi not in discom_df.columns:
        return float("nan")
    return float(discom_df.iloc[0][kpi])


# ---------------------------------------------------------------------------
# Summary matrix (Division / Circle / Zone counts per slab) — one per KPI
# ---------------------------------------------------------------------------
def _slab_matrix_for_kpi(unit_tables: dict, kpi: str, discom_val: float) -> pd.DataFrame:
    """Rows = slab labels (+ a '< / > Discom Avg' row), columns = Division /
    Circle / Zone counts — exactly mirroring the reference Excel layout."""
    slab_labels = _slab_order(kpi)
    rows = []
    for slab in slab_labels:
        row = {"Slab": slab}
        for level_label in ["Division", "Circle", "Zone"]:
            df = unit_tables[level_label]
            row[level_label.lower() + "s"] = int((df[f"{kpi}__slab"] == slab).sum())
        rows.append(row)

    lower_is_better = KPI_META[kpi]["lower_is_better"]
    relative_label = "< Discom Avg" if lower_is_better else "> Discom Avg"
    rel_row = {"Slab": relative_label}
    for level_label in ["Division", "Circle", "Zone"]:
        df = unit_tables[level_label]
        if pd.isna(discom_val):
            rel_row[level_label.lower() + "s"] = 0
        elif lower_is_better:
            rel_row[level_label.lower() + "s"] = int((df[kpi] < discom_val).sum())
        else:
            rel_row[level_label.lower() + "s"] = int((df[kpi] > discom_val).sum())
    rows.append(rel_row)

    return pd.DataFrame(rows)


def _render_clickable_matrix(matrix_df: pd.DataFrame, kpi: str, key: str):
    """
    Render one KPI's slab matrix as a clickable AgGrid (falls back to a
    plain dataframe + selectbox if streamlit-aggrid isn't installed).
    Returns (selected_slab, selected_level) or (None, None) if nothing
    was clicked this run.
    """
    meta = KPI_META[kpi]
    st.markdown(f"**{meta['label']} Slab**")

    if not AGGRID_AVAILABLE:
        st.dataframe(matrix_df, hide_index=True, width="stretch")
        c1, c2 = st.columns(2)
        with c1:
            sel_slab = st.selectbox("View details for slab", matrix_df["Slab"].tolist(),
                                     key=f"{key}_slab_fallback")
        with c2:
            sel_level = st.selectbox("Level", ["Division", "Circle", "Zone"], key=f"{key}_level_fallback")
        if st.button("View units", key=f"{key}_view_btn"):
            return sel_slab, sel_level
        return None, None

    level_cols = ["divisions", "circles", "zones"]
    cell_style_jscode = JsCode("""
    function(params) {
        if (params.value > 0) {
            return {'color': '#0B5394', 'fontWeight': '700', 'textDecoration': 'underline',
                    'cursor': 'pointer', 'backgroundColor': '#EAF1FB'};
        }
        return {'color': '#9AA5B1'};
    }
    """)

    gb = GridOptionsBuilder.from_dataframe(matrix_df)
    gb.configure_column("Slab", pinned="left", width=150,
                         cellStyle={"fontWeight": "600", "backgroundColor": "#F7F9FC"})
    for c in level_cols:
        if c in matrix_df.columns:
            gb.configure_column(c, type=["numericColumn"], cellStyle=cell_style_jscode, width=110)
    gb.configure_selection(selection_mode="single", use_checkbox=False)
    grid_options = gb.build()

    grid_response = AgGrid(
        matrix_df,
        gridOptions=grid_options,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        data_return_mode=DataReturnMode.AS_INPUT,
        allow_unsafe_jscode=True,
        fit_columns_on_grid_load=True,
        theme="balham",
        height=min(260, 46 * (len(matrix_df) + 1)),
        key=key,
    )

    sel_slab_level = st.radio(
        "View Data By", ["Division", "Circle", "Zone"], horizontal=True,
        key=f"{key}_drill_level",
        help="Choose which hierarchy level's count you want to inspect when you click a row.",
    )

    selected = grid_response.get("selected_rows")
    if selected is not None and len(selected) > 0:
        if isinstance(selected, pd.DataFrame):
            sel_row = selected.iloc[0].to_dict()
        else:
            sel_row = selected[0]
        count_col = sel_slab_level.lower() + "s"
        if sel_row.get(count_col, 0) and int(sel_row.get(count_col, 0)) > 0:
            return sel_row["Slab"], sel_slab_level
    return None, None


def _render_detail_grid(df: pd.DataFrame, id_cols: list, kpi: str, title: str, key: str):
    """Render a detail AgGrid of underlying unit records for a drill-down,
    with row-click -> full-record detail panel beneath the grid."""
    meta = KPI_META[kpi]
    show_cols = id_cols + [kpi] + (["category"] if "category" in df.columns else [])
    show_df = df[show_cols].rename(columns={kpi: f"{meta['label']} ({meta['unit']})"}).copy()
    show_df = show_df.sort_values(show_df.columns[-1] if "category" not in show_df.columns
                                   else f"{meta['label']} ({meta['unit']})", ascending=False)

    st.markdown(f"##### {title} — {len(show_df)} unit(s)")

    if not AGGRID_AVAILABLE:
        st.dataframe(show_df, hide_index=True, width="stretch")
        return

    gb = GridOptionsBuilder.from_dataframe(show_df)
    gb.configure_default_column(filter=True, sortable=True, resizable=True)
    gb.configure_selection(selection_mode="single", use_checkbox=False)
    grid_options = gb.build()

    resp = AgGrid(
        show_df, gridOptions=grid_options,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        allow_unsafe_jscode=True, fit_columns_on_grid_load=True,
        theme="balham", height=min(420, 38 * (len(show_df) + 1)), key=key,
    )

    selected = resp.get("selected_rows")
    if selected is not None and len(selected) > 0:
        sel_row = selected.iloc[0].to_dict() if isinstance(selected, pd.DataFrame) else selected[0]
        with st.expander("🔍 Full record detail", expanded=True):
            detail_cols = st.columns(3)
            items = list(sel_row.items())
            for i, (k, v) in enumerate(items):
                with detail_cols[i % 3]:
                    st.metric(k.replace("_", " ").title(), f"{v:.2f}" if isinstance(v, float) else str(v))


# ---------------------------------------------------------------------------
# Cascading multi-KPI AND/OR criteria builder
# ---------------------------------------------------------------------------
def _criteria_mask(df: pd.DataFrame, criteria: list, logic: str) -> pd.Series:
    """Combine a list of (kpi, slab_label) conditions into a single boolean
    mask over `df` using AND or OR logic."""
    if not criteria:
        return pd.Series([True] * len(df), index=df.index)
    masks = [df[f"{kpi}__slab"] == slab for kpi, slab in criteria]
    combined = masks[0]
    for m in masks[1:]:
        combined = (combined & m) if logic == "AND" else (combined | m)
    return combined


def _render_criteria_builder(unit_tables: dict, key_prefix: str):
    st.markdown("#### 🎛️ Multi-Slab Criteria Builder")
    st.caption(
        "Build a cascading multi-KPI filter — choose any number of KPI + Slab conditions and combine "
        "them with AND (all conditions must hold) or OR (any condition holds) to isolate units for review."
    )

    level_label = st.radio("Apply criteria at level", ["Division", "Circle", "Zone"],
                            horizontal=True, key=f"{key_prefix}_level")
    df = unit_tables[level_label]

    n_conditions = st.number_input("Number of conditions", min_value=1, max_value=6, value=2,
                                    key=f"{key_prefix}_n_cond")

    logic = st.radio("Combine conditions with", ["AND", "OR"], horizontal=True,
                      key=f"{key_prefix}_logic",
                      help="AND = unit must satisfy every condition. OR = unit must satisfy at least one.")

    criteria = []
    cols = st.columns(2)
    for i in range(int(n_conditions)):
        with cols[i % 2]:
            st.markdown(f"**Condition {i + 1}**")
            cc1, cc2 = st.columns(2)
            with cc1:
                kpi = st.selectbox("KPI", SLAB_KPI_ORDER, format_func=lambda k: KPI_META[k]["label"],
                                    key=f"{key_prefix}_kpi_{i}")
            with cc2:
                slab = st.selectbox("Slab", _slab_order(kpi), key=f"{key_prefix}_slab_{i}")
            criteria.append((kpi, slab))

    mask = _criteria_mask(df, criteria, logic)
    matched = df.loc[mask]

    st.divider()
    st.markdown(
        f"**Result: {len(matched)} of {len(df)} {level_label.lower()}(s) match "
        f"({logic} of {int(n_conditions)} condition(s))**"
    )

    summary_bits = " ".join(
        [f"`{KPI_META[k]['label']} = {s}`" + (f" **{logic}** " if idx < len(criteria) - 1 else "")
         for idx, (k, s) in enumerate(criteria)]
    )
    st.caption(summary_bits)

    id_cols = LEVEL_ID_COLS[level_label]
    kpi_cols_present = [k for k in SLAB_KPI_ORDER if k in matched.columns]
    display_cols = id_cols + kpi_cols_present
    display_df = matched[display_cols].rename(columns={k: KPI_META[k]["label"] for k in kpi_cols_present})

    if AGGRID_AVAILABLE:
        gb = GridOptionsBuilder.from_dataframe(display_df)
        gb.configure_default_column(filter=True, sortable=True, resizable=True)
        gb.configure_selection(selection_mode="single", use_checkbox=False)
        grid_options = gb.build()
        resp = AgGrid(
            display_df, gridOptions=grid_options,
            update_mode=GridUpdateMode.SELECTION_CHANGED,
            allow_unsafe_jscode=True, fit_columns_on_grid_load=True,
            theme="balham", height=min(440, 38 * (len(display_df) + 1)),
            key=f"{key_prefix}_result_grid",
        )
        selected = resp.get("selected_rows")
        if selected is not None and len(selected) > 0:
            sel_row = selected.iloc[0].to_dict() if isinstance(selected, pd.DataFrame) else selected[0]
            with st.expander("🔍 Full record detail", expanded=True):
                detail_cols = st.columns(3)
                for i, (k, v) in enumerate(sel_row.items()):
                    with detail_cols[i % 3]:
                        st.metric(k, f"{v:.2f}" if isinstance(v, float) else str(v))
    else:
        st.dataframe(display_df, hide_index=True, width="stretch")

    if len(matched) > 0:
        import export_utils as eu
        ec1, ec2 = st.columns(2)
        with ec1:
            st.download_button("Download CSV", eu.to_csv_bytes(display_df),
                                file_name=f"slab_criteria_{level_label.lower()}.csv",
                                mime="text/csv", key=f"{key_prefix}_dl_csv", width="stretch")
        with ec2:
            st.download_button("Download Excel", eu.to_excel_bytes(display_df, "Slab Criteria"),
                                file_name=f"slab_criteria_{level_label.lower()}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key=f"{key_prefix}_dl_xlsx", width="stretch")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def render_slab_analytics_tab(con, long_df, category, period_kwargs, period_type,
                               selected_month, month_options, KPI_LABELS_ARG=None):
    """
    Render the full Slab Analytics tab.

    con              : DuckDB connection (already has `atc_long` registered)
    long_df          : tidy long-format dataframe (for category/zone lookups)
    category         : currently selected OVERALL/GOVT/NON_GOVT (sidebar)
    period_kwargs    : dict to pass straight into ke.kpi_table(...) for the
                        sidebar's selected period (single month or progressive)
    period_type      : "single" or "progressive" (sidebar)
    selected_month   : sidebar-selected month label
    month_options    : list of all month labels (chronological)
    """
    if not AGGRID_AVAILABLE:
        st.warning(
            "⚠️ `streamlit-aggrid` is not installed, so clickable grids are running in fallback mode "
            "(plain tables + selectboxes). Install it for the full clickable experience:\n\n"
            "`pip install streamlit-aggrid`"
        )

    st.subheader("🎯 Slab Analytics")
    

    sa1, sa2 = st.columns(2)
    with sa1:
        sa_category = st.radio("Category", CATEGORIES, format_func=lambda c: CATEGORY_LABELS[c],
                                horizontal=True, key="sa_category",
                                index=CATEGORIES.index(category))
    with sa2:
        sa_month = st.selectbox("Month", month_options, index=month_options.index(selected_month),
                                 key="sa_month")

    sa_period_kwargs = dict(period_type="single", month=sa_month)

    unit_tables = _build_unit_table(con, sa_category, **sa_period_kwargs)

    st.markdown("### 📊 Slab Summary Matrix")
    st.caption(
        f"Division / Circle / Zone counts per slab — {CATEGORY_LABELS[sa_category]}, **{sa_month}**. "
        "Click a Count, Choose the drill-down level, then view matching Zones/Circles/Divisions below."
    )

    drill_request = None  # (kpi, slab, level)

    row1 = st.columns(3)
    row2 = st.columns(3)
    kpi_grid_slots = row1 + row2

    for slot, kpi in zip(kpi_grid_slots, SLAB_KPI_ORDER):
        with slot:
            discom_val = _discom_value(con, sa_category, kpi, **sa_period_kwargs)
            matrix_df = _slab_matrix_for_kpi(unit_tables, kpi, discom_val)
            sel_slab, sel_level = _render_clickable_matrix(
                matrix_df, kpi, key=f"sa_matrix_{kpi}"
            )
            if sel_slab is not None:
                drill_request = (kpi, sel_slab, sel_level)

    if drill_request is not None:
        kpi, slab, level = drill_request
        st.divider()
        st.markdown(f"### 🔍 View: {KPI_META[kpi]['label']} = `{slab}` at {level} level")
        df = unit_tables[level]
        matched = df[df[f"{kpi}__slab"] == slab]
        id_cols = LEVEL_ID_COLS[level]
        _render_detail_grid(matched, id_cols, kpi, f"{KPI_META[kpi]['label']} — {slab}",
                             key=f"sa_drill_{kpi}_{slab}_{level}")

        import export_utils as eu
        dl_df = matched[id_cols + [kpi]].rename(columns={kpi: KPI_META[kpi]["label"]})
        st.download_button("Download these units (CSV)", eu.to_csv_bytes(dl_df),
                            file_name=f"slab_drilldown_{kpi}_{slab}_{level}.csv".replace(" ", "_"),
                            mime="text/csv", key="sa_drill_dl")

    st.divider()
#    _render_criteria_builder(unit_tables, key_prefix="sa_criteria")
