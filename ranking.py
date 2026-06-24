"""
ranking.py
==========
Best/Worst ranking engine + Month-on-Month (MoM) and Year-on-Year (YoY)
improvement leaderboards.

All ranking is performed AFTER kpi_engine has correctly summed numerators/
denominators and recomputed ratios (never ranks on an averaged percentage).
"""

from __future__ import annotations
import duckdb
import pandas as pd
from config import KPI_META
import kpi_engine as ke


def rank_table(con: duckdb.DuckDBPyConnection, level: str, category: str, kpi: str,
                period_type: str, month: str | None = None, upto_month_seq: int | None = None,
                fy_label: str | None = None, top_n: int = 5, mode: str = "worst",
                zone: str | None = None, circle: str | None = None) -> pd.DataFrame:
    """
    Return the Top-N or Bottom-N performers for a given KPI at a given
    hierarchy level (e.g. Division-within-Circle if `circle` is supplied,
    Circle-within-Zone if `zone` is supplied, or DISCOM-wide if neither is).

    mode='worst' -> the N worst performers (highest loss / lowest efficiency,
                     direction-aware via KPI_META[kpi]['lower_is_better'])
    mode='best'  -> the N best performers
    """
    df = ke.kpi_table(con, level, category, period_type, month=month,
                       upto_month_seq=upto_month_seq, fy_label=fy_label,
                       zone=zone, circle=circle)
    if kpi not in df.columns:
        raise KeyError(f"KPI '{kpi}' not found in kpi_table output")

    df = df.dropna(subset=[kpi])
    lower_is_better = KPI_META[kpi]["lower_is_better"]
    # "worst" performer = the bad end of the spectrum given the KPI's direction
    ascending = not lower_is_better if mode == "worst" else lower_is_better
    df = df.sort_values(kpi, ascending=ascending).head(top_n).reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))
    return df


def _label_col(level: str) -> str:
    return {"DISCOM": "discom", "ZONE": "zone", "CIRCLE": "circle", "DIVISION": "division"}[level]


def mom_yoy_table(con: duckdb.DuckDBPyConnection, level: str, category: str,
                    month: str, compare: str = "MoM",
                    zone: str | None = None, circle: str | None = None) -> pd.DataFrame:
    """
    Compare `month` against the previous month (compare='MoM') or the same
    month one fiscal year earlier (compare='YoY'), at the given hierarchy
    level. Returns delta and % improvement for every KPI, ready to be sorted
    into a most-improved / most-deteriorated leaderboard.

    Both periods are independently aggregated with proper SUM-then-ratio
    logic (kpi_table), so the comparison is never built from averaged
    percentages.
    """
    months_df = con.execute("SELECT DISTINCT month, seq_index, cal_year, month_num FROM atc_long").fetchdf()
    months_df = months_df.drop_duplicates(subset="month").sort_values("seq_index").reset_index(drop=True)
    cur_row = months_df[months_df["month"] == month]
    if cur_row.empty:
        raise KeyError(f"Month '{month}' not found")
    cur_seq = int(cur_row.iloc[0]["seq_index"])

    if compare == "MoM":
        prev_row = months_df[months_df["seq_index"] == cur_seq - 1]
    elif compare == "YoY":
        cur_month_num = int(cur_row.iloc[0]["month_num"])
        cur_cal_year = int(cur_row.iloc[0]["cal_year"])
        prev_row = months_df[(months_df["month_num"] == cur_month_num) &
                              (months_df["cal_year"] == cur_cal_year - 1)]
    else:
        raise ValueError("compare must be 'MoM' or 'YoY'")

    if prev_row.empty:
        return pd.DataFrame()  # no comparable prior period in the dataset

    prev_month = prev_row.iloc[0]["month"]

    cur_kpi = ke.kpi_table(con, level, category, "single", month=month, zone=zone, circle=circle)
    prev_kpi = ke.kpi_table(con, level, category, "single", month=prev_month, zone=zone, circle=circle)

    label_col = _label_col(level)
    group_cols = ke.LEVEL_COLUMNS[level] if level != "DISCOM" else [label_col]

    merged = cur_kpi.merge(prev_kpi, on=group_cols, suffixes=("_cur", "_prev"), how="inner")

    kpi_cols = ["line_loss_pct", "billing_efficiency_pct", "collection_efficiency_pct",
                "atc_loss_pct", "through_rate", "abr"]
    for k in kpi_cols:
        merged[f"{k}_delta"] = merged[f"{k}_cur"] - merged[f"{k}_prev"]
        merged[f"{k}_pct_change"] = (merged[f"{k}_delta"] / merged[f"{k}_prev"].abs()) * 100
        merged[f"{k}_pct_change"] = merged[f"{k}_pct_change"].replace([float("inf"), float("-inf")], pd.NA)

    merged["compare_type"] = compare
    merged["current_month"] = month
    merged["prior_month"] = prev_month
    return merged


def improvement_leaderboard(mom_yoy_df: pd.DataFrame, kpi: str, top_n: int = 5,
                              direction: str = "most_improved") -> pd.DataFrame:
    """
    Slice a mom_yoy_table() result into a most-improved / most-deteriorated
    leaderboard for one KPI. "Improved" is direction-aware: for
    lower_is_better KPIs (AT&C Loss, Line Loss) a NEGATIVE delta is an
    improvement; for higher_is_better KPIs (Billing/Collection Efficiency,
    Through Rate, ABR) a POSITIVE delta is an improvement.
    """
    delta_col = f"{kpi}_delta"
    if delta_col not in mom_yoy_df.columns:
        raise KeyError(f"{delta_col} not found - run mom_yoy_table first")

    df = mom_yoy_df.dropna(subset=[delta_col]).copy()
    lower_is_better = KPI_META[kpi]["lower_is_better"]

    if direction == "most_improved":
        # improvement = most-negative delta when lower_is_better, most-positive otherwise
        df = df.sort_values(delta_col, ascending=lower_is_better)
    else:  # most_deteriorated
        df = df.sort_values(delta_col, ascending=not lower_is_better)

    df = df.head(top_n).reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))
    return df
