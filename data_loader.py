"""
data_loader.py
===============
Loads the raw DVVNL "ATC MONTHLY ALL UNITS.csv" file and reshapes it from its
native wide format (OVERALL / GOVERNMENT / NON GOVERNMENT columns side-by-side
for every division-month row) into a tidy LONG format with a single
`category` column, as required so every downstream chart/table/filter can
switch between OVERALL / GOVT / NON_GOVT via one selector.

Column names in the source CSV are matched by keyword (case-insensitive,
include/exclude rules) rather than hard-coded exact strings, so the loader
keeps working even if column order or minor spacing/punctuation in the
header changes between monthly exports.

Public entry points
--------------------
load_raw_csv(path_or_buffer)      -> pandas.DataFrame   (raw wide CSV, cleaned)
reshape_to_long(df_wide)          -> pandas.DataFrame   (tidy long format)
load_long_dataframe(path_or_buffer) -> convenience wrapper (raw -> long), cached in app.py
"""

from __future__ import annotations
import io
import pandas as pd
from config import parse_month_label, CATEGORIES


# ---------------------------------------------------------------------------
# Column auto-mapping helpers
# ---------------------------------------------------------------------------
def _find_col(cols, include, exclude=None):
    """Return the first column whose lowercase name contains every token in
    `include` and none of the tokens in `exclude`. Raises a clear error if
    zero or multiple candidates are found, so a schema drift fails loudly
    instead of silently picking the wrong column."""
    exclude = exclude or []
    matches = []
    for c in cols:
        lc = c.lower()
        if all(tok in lc for tok in include) and not any(tok in lc for tok in exclude):
            matches.append(c)
    if len(matches) == 0:
        raise KeyError(f"Could not find a column matching include={include} exclude={exclude}. "
                        f"Available columns: {list(cols)}")
    if len(matches) > 1:
        raise KeyError(f"Ambiguous column match for include={include} exclude={exclude}: {matches}")
    return matches[0]


def _exact_col(cols, name):
    for c in cols:
        if c.strip().lower() == name.lower():
            return c
    raise KeyError(f"Expected an exact column named '{name}'. Available columns: {list(cols)}")


def _build_column_map(cols):
    """Build the {logical_name: actual_csv_column_name} mapping used to pull
    out every field needed for the long-format reshape."""
    m = {}
    m["MONTH"] = _exact_col(cols, "MONTH")
    m["ZONE"] = _exact_col(cols, "ZONE")
    m["CIRCLE"] = _exact_col(cols, "CIRCLE")
    m["DIVISION"] = _exact_col(cols, "DIVISION")

    # ---- OVERALL block ----
    m["OVERALL_INPUT_ENERGY"] = _find_col(cols, ["overall", "input energy"])
    m["OVERALL_UNIT_SOLD"] = _find_col(cols, ["overall", "unit sold"])
    m["OVERALL_DIST_LOSS_PCT"] = _find_col(cols, ["overall", "distribution loss"])
    m["OVERALL_ASSESSMENT"] = _find_col(cols, ["overall", "assessment"])
    m["OVERALL_REALISATION"] = _find_col(cols, ["overall", "realisation"], exclude=["rate", "%"])
    m["OVERALL_PCT_REALISATION"] = _find_col(cols, ["overall", "%", "realisation"])
    m["OVERALL_ATC_LOSS"] = _find_col(cols, ["overall", "atc loss"])
    m["OVERALL_RATE_INPUT"] = _find_col(cols, ["overall", "realisation rate", "input"])
    m["OVERALL_RATE_SOLD"] = _find_col(cols, ["overall", "realisation rate", "sold"])

    # ---- GOVERNMENT block (exclude "non government") ----
    m["GOVT_UNIT_SOLD"] = _find_col(cols, ["government", "unit sold"], exclude=["non government"])
    m["GOVT_ASSESSMENT"] = _find_col(cols, ["government", "assessment"], exclude=["non government"])
    m["GOVT_REALISATION"] = _find_col(cols, ["government", "realisation"], exclude=["non government", "rate", "%"])
    m["GOVT_PCT_REALISATION"] = _find_col(cols, ["government", "%", "realisation"], exclude=["non government"])
    m["GOVT_ATC_LOSS"] = _find_col(cols, ["government", "atc loss"], exclude=["non government"])

    # ---- NON GOVERNMENT block ----
    m["NONGOVT_UNIT_SOLD"] = _find_col(cols, ["non government", "unit sold"])
    m["NONGOVT_ASSESSMENT"] = _find_col(cols, ["non government", "assessment"])
    m["NONGOVT_REALISATION"] = _find_col(cols, ["non government", "realisation"], exclude=["rate", "%"])
    m["NONGOVT_PCT_REALISATION"] = _find_col(cols, ["non government", "%", "realisation"])
    m["NONGOVT_ATC_LOSS"] = _find_col(cols, ["non government", "atc loss"])

    return m


# ---------------------------------------------------------------------------
# Raw load
# ---------------------------------------------------------------------------
def load_raw_csv(path_or_buffer) -> pd.DataFrame:
    """Read the raw wide CSV with a BOM-safe encoding and strip whitespace
    from string fields. Accepts a filesystem path OR a file-like object
    (e.g. a Streamlit UploadedFile)."""
    df = pd.read_csv(path_or_buffer, encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].astype(str).str.strip()
    return df


# ---------------------------------------------------------------------------
# Wide -> tidy long reshape
# ---------------------------------------------------------------------------
def reshape_to_long(df_wide: pd.DataFrame) -> pd.DataFrame:
    """
    Transform the wide CSV (one row per division-month, OVERALL/GOVT/NON_GOVT
    columns side by side) into a tidy long-format table with one row per
    division-month-category.

    Output columns:
        month, month_name, month_num, cal_year, month_date, fy_label, fy_month_pos,
        zone, circle, division, category,
        input_energy_mu, unit_sold_mu, assessment_lakh, realisation_lakh,
        src_distribution_loss_pct, src_pct_realisation, src_atc_loss,
        src_realisation_rate_input, src_realisation_rate_sold

    `input_energy_mu`, `src_distribution_loss_pct`, `src_realisation_rate_input`
    and `src_realisation_rate_sold` are populated ONLY for category == 'OVERALL'
    (NaN for GOVT / NON_GOVT) because the source data does not split Input
    Energy by consumer category -- see the data-model note at the top of
    config.py.
    """
    cols = df_wide.columns
    m = _build_column_map(cols)

    # --- month metadata (parsed once per unique month label) ---
    month_meta = {lbl: parse_month_label(lbl) for lbl in df_wide[m["MONTH"]].unique()}

    base = pd.DataFrame({
        "month": df_wide[m["MONTH"]],
        "zone": df_wide[m["ZONE"]],
        "circle": df_wide[m["CIRCLE"]],
        "division": df_wide[m["DIVISION"]],
    })

    frames = []

    # ---- OVERALL ----
    overall = base.copy()
    overall["category"] = "OVERALL"
    overall["input_energy_mu"] = pd.to_numeric(df_wide[m["OVERALL_INPUT_ENERGY"]], errors="coerce")
    overall["unit_sold_mu"] = pd.to_numeric(df_wide[m["OVERALL_UNIT_SOLD"]], errors="coerce")
    overall["assessment_lakh"] = pd.to_numeric(df_wide[m["OVERALL_ASSESSMENT"]], errors="coerce")
    overall["realisation_lakh"] = pd.to_numeric(df_wide[m["OVERALL_REALISATION"]], errors="coerce")
    overall["src_distribution_loss_pct"] = pd.to_numeric(df_wide[m["OVERALL_DIST_LOSS_PCT"]], errors="coerce")
    overall["src_pct_realisation"] = pd.to_numeric(df_wide[m["OVERALL_PCT_REALISATION"]], errors="coerce")
    overall["src_atc_loss"] = pd.to_numeric(df_wide[m["OVERALL_ATC_LOSS"]], errors="coerce")
    overall["src_realisation_rate_input"] = pd.to_numeric(df_wide[m["OVERALL_RATE_INPUT"]], errors="coerce")
    overall["src_realisation_rate_sold"] = pd.to_numeric(df_wide[m["OVERALL_RATE_SOLD"]], errors="coerce")
    frames.append(overall)

    # ---- GOVT ----
    govt = base.copy()
    govt["category"] = "GOVT"
    govt["input_energy_mu"] = pd.NA
    govt["unit_sold_mu"] = pd.to_numeric(df_wide[m["GOVT_UNIT_SOLD"]], errors="coerce")
    govt["assessment_lakh"] = pd.to_numeric(df_wide[m["GOVT_ASSESSMENT"]], errors="coerce")
    govt["realisation_lakh"] = pd.to_numeric(df_wide[m["GOVT_REALISATION"]], errors="coerce")
    govt["src_distribution_loss_pct"] = pd.NA
    govt["src_pct_realisation"] = pd.to_numeric(df_wide[m["GOVT_PCT_REALISATION"]], errors="coerce")
    govt["src_atc_loss"] = pd.to_numeric(df_wide[m["GOVT_ATC_LOSS"]], errors="coerce")
    govt["src_realisation_rate_input"] = pd.NA
    govt["src_realisation_rate_sold"] = pd.NA
    frames.append(govt)

    # ---- NON_GOVT ----
    nongovt = base.copy()
    nongovt["category"] = "NON_GOVT"
    nongovt["input_energy_mu"] = pd.NA
    nongovt["unit_sold_mu"] = pd.to_numeric(df_wide[m["NONGOVT_UNIT_SOLD"]], errors="coerce")
    nongovt["assessment_lakh"] = pd.to_numeric(df_wide[m["NONGOVT_ASSESSMENT"]], errors="coerce")
    nongovt["realisation_lakh"] = pd.to_numeric(df_wide[m["NONGOVT_REALISATION"]], errors="coerce")
    nongovt["src_distribution_loss_pct"] = pd.NA
    nongovt["src_pct_realisation"] = pd.to_numeric(df_wide[m["NONGOVT_PCT_REALISATION"]], errors="coerce")
    nongovt["src_atc_loss"] = pd.to_numeric(df_wide[m["NONGOVT_ATC_LOSS"]], errors="coerce")
    nongovt["src_realisation_rate_input"] = pd.NA
    nongovt["src_realisation_rate_sold"] = pd.NA
    frames.append(nongovt)

    long_df = pd.concat(frames, ignore_index=True)

    # attach parsed month metadata
    meta_df = pd.DataFrame(month_meta).T
    meta_df.index.name = "month"
    meta_df = meta_df.reset_index()
    long_df = long_df.merge(meta_df, on="month", how="left")

    numeric_fix_cols = [
        "month_num", "cal_year", "fy_month_pos",
        "input_energy_mu", "unit_sold_mu", "assessment_lakh", "realisation_lakh",
        "src_distribution_loss_pct", "src_pct_realisation", "src_atc_loss",
        "src_realisation_rate_input", "src_realisation_rate_sold",
    ]
    for c in numeric_fix_cols:
        long_df[c] = pd.to_numeric(long_df[c], errors="coerce")
    long_df["month_num"] = long_df["month_num"].astype("Int64")
    long_df["cal_year"] = long_df["cal_year"].astype("Int64")
    long_df["fy_month_pos"] = long_df["fy_month_pos"].astype("Int64")
    long_df["month_date"] = pd.to_datetime(long_df["month_date"])

    # stable chronological sequence index (1 = earliest month in file)
    month_order = (
        long_df[["month", "month_date"]]
        .drop_duplicates()
        .sort_values("month_date")
        .reset_index(drop=True)
    )
    month_order["seq_index"] = month_order.index + 1
    long_df = long_df.merge(month_order[["month", "seq_index"]], on="month", how="left")

    long_df["category"] = pd.Categorical(long_df["category"], categories=CATEGORIES, ordered=True)

    col_order = [
        "month", "month_name", "month_num", "cal_year", "month_date", "fy_label",
        "fy_month_pos", "seq_index", "zone", "circle", "division", "category",
        "input_energy_mu", "unit_sold_mu", "assessment_lakh", "realisation_lakh",
        "src_distribution_loss_pct", "src_pct_realisation", "src_atc_loss",
        "src_realisation_rate_input", "src_realisation_rate_sold",
    ]
    return long_df[col_order]


def load_long_dataframe(path_or_buffer=None) -> pd.DataFrame:
    """Convenience wrapper: raw CSV -> tidy long dataframe in one call."""
    from config import DEFAULT_CSV_PATH
    source = path_or_buffer if path_or_buffer is not None else DEFAULT_CSV_PATH
    df_wide = load_raw_csv(source)
    return reshape_to_long(df_wide)


def month_lookup_table(long_df: pd.DataFrame) -> pd.DataFrame:
    """Distinct month list in chronological order, for dropdowns."""
    return (
        long_df[["month", "month_date", "fy_label", "fy_month_pos", "seq_index"]]
        .drop_duplicates()
        .sort_values("seq_index")
        .reset_index(drop=True)
    )
