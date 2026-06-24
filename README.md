# DVVNL AT&C Loss Management Review Dashboard

An enterprise-grade Streamlit + DuckDB management review dashboard built on
`ATC_MONTHLY_ALL_UNITS.csv` (Division-level, monthly, April 2025 - May 2026).

## 1. Setup (VS Code / local machine)

```bash
# 1. Unzip the project and open the folder in VS Code
cd atc_dashboard

# 2. (Recommended) create a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app
streamlit run app.py
```

The app opens at `http://localhost:8501`. The bundled CSV at
`data/ATC_MONTHLY_ALL_UNITS.csv` loads automatically — no extra configuration
needed. To refresh with a newer monthly export, either replace that file or
use the "Data source" uploader in the sidebar (same column layout required).

## 2. Project structure

```
atc_dashboard/
├── app.py              Streamlit UI — sidebar filters + 8 review tabs
├── config.py            Constants, FY/month parsing, KPI metadata, theme
├── data_loader.py        CSV ingestion + wide-to-long reshape (tidy format)
├── kpi_engine.py          DuckDB SQL aggregation engine (sum-then-ratio KPIs)
├── ranking.py             Best/Worst ranking + MoM/YoY improvement leaderboards
├── export_utils.py        CSV / Excel / PDF export helpers
├── ui_helpers.py          Shared Plotly / Altair / st.metric rendering helpers
├── requirements.txt
├── data/
│   └── ATC_MONTHLY_ALL_UNITS.csv   (bundled sample data)
└── .streamlit/
    └── config.toml        Theme colours
```

## 3. What's inside the dashboard

- **DISCOM Overview** — DVVNL-wide KPI cards, monthly trend, zone-wise
  comparison bar chart, zone AT&C sparkline grid, Top/Bottom-N zones.
- **Zone Review** — drill into one zone: KPI cards, trend, circle-wise
  comparison and ranking within that zone.
- **Circle Review** — drill into one circle (Zone → Circle cascading
  selectors): KPI cards, trend, division-wise comparison and ranking.
- **Division Review** — drill into one division (Zone → Circle → Division
  cascading selectors): KPI cards, trend, and an Overall/Govt/Non-Govt
  side-by-side comparison table.
- **Rankings** — flexible Top/Bottom-N engine: rank Divisions, Circles or
  Zones, scoped DISCOM-wide / within a Zone / within a Circle, by any KPI,
  for the sidebar's selected period.
- **MoM / YoY** — Month-on-Month or Year-on-Year delta tables and
  most-improved / most-deteriorated leaderboards at any hierarchy level.
- **Data Explorer & Export** — multi-select filters (Zone/Circle/Division/
  Category/Month), sortable table, and CSV / Excel / PDF export of the
  filtered view.
- **Methodology & Notes** — every KPI formula, the FY/progressive-period
  logic, and a transparent explanation (with a live worked example from the
  loaded data) of how AT&C Loss is computed for Govt / Non-Govt categories
  given that Input Energy is only available at OVERALL level in the source
  file.

## 4. KPI formulas (applied after summing numerators/denominators — never on
an averaged percentage)

| KPI | Formula |
|---|---|
| Line Loss (%) | ((Input Energy − Unit Sold) / Input Energy) × 100 |
| Billing Efficiency (%) | (Unit Sold / Input Energy) × 100 |
| Collection Efficiency (%) | (Realisation / Assessment) × 100 |
| AT&C Loss (%) | 100 − (Billing Efficiency × Collection Efficiency / 100) |
| Through Rate (Rs/Unit) | Realisation / Input Energy |
| ABR (Rs/Unit) | Assessment / Unit Sold |

Line Loss, Billing Efficiency and the input-based Through Rate are only
computed at **OVERALL** level because the source CSV does not split Input
Energy by Government / Non-Government consumer category (it's a technical,
feeder-level quantity). AT&C Loss for Govt / Non-Govt borrows the OVERALL
division's Billing Efficiency and combines it with the category's own
Collection Efficiency — see the in-app Methodology tab for the full
explanation and a live numeric example.

## 5. Performance & caching

- `st.cache_data` caches the CSV load/reshape and every DuckDB query result.
- `st.cache_resource` caches the DuckDB connection itself.
- All grouping/aggregation/ranking is pushed into DuckDB SQL — no repeated
  full-CSV pandas groupbys.

## 6. Refreshing with new monthly data

Drop a new export with the same column layout into `data/` (overwriting
`ATC_MONTHLY_ALL_UNITS.csv`), or upload it via the sidebar. Column matching
is keyword-based (see `data_loader._build_column_map`), so minor header
spacing/punctuation differences won't break the load — only a genuine
structural change (e.g. a renamed/missing field) will raise a clear error.
