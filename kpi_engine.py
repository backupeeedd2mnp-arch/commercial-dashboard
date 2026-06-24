"""
kpi_engine.py
=============
DuckDB-backed KPI calculation engine.

All grouping / aggregation / ratio-recomputation is pushed into DuckDB SQL
(rather than repeated pandas groupbys) so the dashboard stays fast across
14 months x ~117 divisions x 3 categories (~3,300 long-format rows, but the
pattern scales the same way to much larger exports).

CORE AGGREGATION RULE (per the spec)
-------------------------------------
Never average a percentage. Always:
  1. SUM the absolute quantities (Input Energy, Unit Sold, Assessment, Realisation)
     across whatever rows are in scope (a Division roll-up to Circle, a month
     range for a progressive/cumulative period, etc).
  2. THEN recompute the ratio KPIs from those summed numerators/denominators.

KPI FORMULAS (applied after step 1 above)
------------------------------------------
  Line Loss (%)            = ((Input Energy - Unit Sold) / Input Energy) x 100
  Billing Efficiency (%)   = (Unit Sold / Input Energy) x 100
  Collection Efficiency(%) = (Realisation / Assessment) x 100
  AT&C Loss (%)            = 100 - (Billing Efficiency x Collection Efficiency / 100)
  Through Rate (Rs/Unit)   = Realisation / Input Energy        [Rs(Lakh->Rs) / Units(MU->units)]
  ABR (Rs/Unit)            = Assessment / Unit Sold

Category convention for GOVT / NON_GOVT (see config.py docstring for the full
explanation of why -- Input Energy is only metered at OVERALL/division level,
not split by consumer billing category):
  - Input Energy, Line Loss % and Billing Efficiency % are carried across
    from the OVERALL division's own figures (the shared/common technical
    loss rate applies equally to every category, since it cannot actually
    be split by consumer category).
  - AT&C Loss borrows that same shared Billing Efficiency and combines it
    with the category's OWN Collection Efficiency.
  - Through Rate uses the category's OWN Realisation over the shared
    OVERALL Input Energy, so it DOES differentiate meaningfully by category.
  - Collection Efficiency and ABR are fully category-specific throughout.
"""

from __future__ import annotations
import duckdb
import pandas as pd

LEVEL_COLUMNS = {
    "DISCOM": [],
    "ZONE": ["zone"],
    "CIRCLE": ["zone", "circle"],
    "DIVISION": ["zone", "circle", "division"],
}

RS_PER_LAKH = 100_000
UNITS_PER_MU = 1_000_000
# Rs/Unit = (Lakh * 100,000) / (MU * 1,000,000) = Lakh / (MU * 10)
LAKH_TO_MU_RS_PER_UNIT_DIVISOR = 10


def get_connection(long_df: pd.DataFrame) -> duckdb.DuckDBPyConnection:
    """Create an in-memory DuckDB connection with the long-format dataframe
    registered as a view called `atc_long`. Cache this at app.py level with
    st.cache_resource (paired with the cached dataframe from st.cache_data)."""
    con = duckdb.connect(database=":memory:")
    con.register("atc_long", long_df)
    return con


def _period_filter_sql(period_type: str, month: str | None, upto_month_seq: int | None,
                        fy_label: str | None) -> str:
    """
    Build the WHERE clause fragment for the requested period.

    period_type == 'single'      -> exactly one month (`month`)
    period_type == 'progressive' -> cumulative from the start of the fiscal
                                     year (fy_month_pos = 1) through the
                                     selected month, WITHIN THE SAME FY
                                     (i.e. "Apr-of-FY through selected month").
    period_type == 'range'       -> all months between two seq_index values
                                     (used by trend charts) -- handled by caller,
                                     not this helper.
    """
    if period_type == "single":
        return f"month = '{month}'"
    elif period_type == "progressive":
        return f"fy_label = '{fy_label}' AND seq_index <= {upto_month_seq}"
    else:
        raise ValueError(f"Unsupported period_type: {period_type}")


def kpi_table(con: duckdb.DuckDBPyConnection, level: str, category: str,
              period_type: str, month: str | None = None,
              upto_month_seq: int | None = None, fy_label: str | None = None,
              zone: str | None = None, circle: str | None = None,
              division: str | None = None) -> pd.DataFrame:
    """
    Core KPI aggregation. Returns one row per group at the requested
    hierarchy `level` (DISCOM / ZONE / CIRCLE / DIVISION), for the requested
    `category` (OVERALL / GOVT / NON_GOVT) and period.

    Implementation detail: we ALWAYS aggregate OVERALL input-energy /
    unit-sold for the same grouping & period (to get the shared Billing
    Efficiency), and separately aggregate the requested category's
    assessment/realisation/unit-sold, then combine per the formulas above.
    This single query therefore correctly handles both:
      - category == 'OVERALL'  (self-consistent, BE and CE both from OVERALL rows)
      - category in ('GOVT','NON_GOVT') (CE from the category, BE borrowed from OVERALL)
    """
    group_cols = LEVEL_COLUMNS[level]
    select_group = ", ".join(group_cols) if group_cols else "'DVVNL' AS discom"
    group_by = ", ".join(group_cols) if group_cols else ""

    where_clauses = []
    if period_type == "single":
        where_clauses.append(f"month = '{month}'")
    elif period_type == "progressive":
        where_clauses.append(f"fy_label = '{fy_label}' AND seq_index <= {upto_month_seq}")
    else:
        raise ValueError(f"Unsupported period_type: {period_type}")

    if zone:
        where_clauses.append(f"zone = '{zone}'")
    if circle:
        where_clauses.append(f"circle = '{circle}'")
    if division:
        where_clauses.append(f"division = '{division}'")
    where_sql = " AND ".join(where_clauses)

    join_keys = " AND ".join([f"o.{c} = c.{c}" for c in group_cols]) if group_cols else "1=1"

    sql = f"""
    WITH overall_agg AS (
        SELECT {select_group},
               SUM(input_energy_mu) AS input_energy_mu,
               SUM(unit_sold_mu)    AS overall_unit_sold_mu
        FROM atc_long
        WHERE category = 'OVERALL' AND {where_sql}
        {f"GROUP BY {group_by}" if group_by else ""}
    ),
    cat_agg AS (
        SELECT {select_group},
               SUM(unit_sold_mu)    AS unit_sold_mu,
               SUM(assessment_lakh) AS assessment_lakh,
               SUM(realisation_lakh) AS realisation_lakh
        FROM atc_long
        WHERE category = '{category}' AND {where_sql}
        {f"GROUP BY {group_by}" if group_by else ""}
    )
    SELECT
        {("o." + ", o.".join(group_cols)) if group_cols else "'DVVNL' AS discom"},
        o.input_energy_mu,
        o.overall_unit_sold_mu,
        c.unit_sold_mu,
        c.assessment_lakh,
        c.realisation_lakh
    FROM overall_agg o
    JOIN cat_agg c ON {join_keys}
    """
    df = con.execute(sql).fetchdf()
    return _compute_kpis(df, category)


def _compute_kpis(df: pd.DataFrame, category: str) -> pd.DataFrame:
    """Take the raw summed numerators/denominators and compute every ratio
    KPI. This is where the formulas in the module docstring are applied.

    GOVT / NON_GOVT convention (input energy is not separately metered per
    category in the source data -- see module docstring):
      - input_energy_mu, line_loss_pct, billing_efficiency_pct: these use
        `input_energy_mu` / `overall_unit_sold_mu`, which the SQL above
        ALWAYS sources from the OVERALL rows of the same division-period
        regardless of which `category` was requested. So for GOVT/NON_GOVT
        these three come out numerically identical to the OVERALL division's
        own figures -- i.e. the shared/common technical loss rate is simply
        carried across to the category view, exactly as directed.
      - through_rate: realisation_lakh is category-specific (govt vs
        non-govt realisation differ) while input_energy_mu is still the
        OVERALL division figure -- so this metric DOES differentiate
        meaningfully by category even though it borrows the OVERALL energy
        base.
      - collection_efficiency_pct, atc_loss_pct, abr: fully category-specific,
        unchanged.
    """
    df = df.copy()

    billing_eff = (df["overall_unit_sold_mu"] / df["input_energy_mu"]) * 100
    line_loss = 100 - billing_eff
    collection_eff = (df["realisation_lakh"] / df["assessment_lakh"]) * 100
    atc_loss = 100 - (billing_eff * collection_eff / 100)
    abr = df["assessment_lakh"] / (df["unit_sold_mu"] * LAKH_TO_MU_RS_PER_UNIT_DIVISOR)
    realisation_rate_sold = df["realisation_lakh"] / (df["unit_sold_mu"] * LAKH_TO_MU_RS_PER_UNIT_DIVISOR)

    df["billing_efficiency_pct"] = billing_eff
    df["line_loss_pct"] = line_loss
    df["collection_efficiency_pct"] = collection_eff
    df["atc_loss_pct"] = atc_loss
    df["abr"] = abr
    df["realisation_rate_sold"] = realisation_rate_sold

    # Through Rate (input basis): category-specific Realisation over the
    # shared OVERALL Input Energy -- computed for every category per the
    # specified convention (no longer OVERALL-only).
    df["through_rate"] = df["realisation_lakh"] / (df["input_energy_mu"] * LAKH_TO_MU_RS_PER_UNIT_DIVISOR)

    df["category"] = category
    return df


def trend_table(con: duckdb.DuckDBPyConnection, level: str, category: str,
                 zone: str | None = None, circle: str | None = None,
                 division: str | None = None, fy_label: str | None = None) -> pd.DataFrame:
    """Month-by-month (not cumulative) KPI series for trend charts /
    sparklines, optionally filtered to a single FY and/or a hierarchy node."""
    months = con.execute("SELECT DISTINCT month, seq_index FROM atc_long ORDER BY seq_index").fetchdf()
    if fy_label:
        months_in_fy = con.execute(
            f"SELECT DISTINCT month FROM atc_long WHERE fy_label = '{fy_label}'"
        ).fetchdf()["month"].tolist()
        months = months[months["month"].isin(months_in_fy)]

    rows = []
    for _, r in months.iterrows():
        kt = kpi_table(con, level, category, "single", month=r["month"],
                        zone=zone, circle=circle, division=division)
        kt["month"] = r["month"]
        kt["seq_index"] = r["seq_index"]
        rows.append(kt)
    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    return out.sort_values("seq_index")


def filter_options(con: duckdb.DuckDBPyConnection, zone: str | None = None,
                    circle: str | None = None) -> dict:
    """Cascading filter option lists for the sidebar (Zone -> Circle -> Division)."""
    zones = con.execute("SELECT DISTINCT zone FROM atc_long ORDER BY zone").fetchdf()["zone"].tolist()
    circle_sql = "SELECT DISTINCT circle FROM atc_long"
    if zone:
        circle_sql += f" WHERE zone = '{zone}'"
    circles = con.execute(circle_sql + " ORDER BY circle").fetchdf()["circle"].tolist()

    div_sql = "SELECT DISTINCT division FROM atc_long WHERE 1=1"
    if zone:
        div_sql += f" AND zone = '{zone}'"
    if circle:
        div_sql += f" AND circle = '{circle}'"
    divisions = con.execute(div_sql + " ORDER BY division").fetchdf()["division"].tolist()

    return {"zones": zones, "circles": circles, "divisions": divisions}
