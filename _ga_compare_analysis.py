import numpy as np
import pandas as pd
from pathlib import Path

LABELS = {
    "sortino_is": "Sortino Ratio (IS aggregate)",
    "dd_is": "Max Drawdown ($) (IS aggregate)",
    "dd_oos": "Max Drawdown ($) (OOS aggregate)",
    "pf_is": "Profit Factor (IS aggregate)",
    "pf_oos": "Profit Factor (OOS aggregate)",
    "trades_is": "Avg Trades/Day (IS aggregate)",
    "trades_oos": "Avg Trades/Day (OOS aggregate)",
    "pnl_is": "Total Profit ($) (IS aggregate)",
    "pnl_oos": "Total Profit ($) (OOS aggregate)",
    "ppt_is": "Avg Profit/Trade ($) (IS aggregate)",
    "ppt_oos": "Avg Profit/Trade ($) (OOS aggregate)",
    "agg_is_sortino": "Aggregate IS Sortino",
    "agg_oos_sortino": "Aggregate OOS Sortino",
    "degradation": "Sortino IS-to-OOS Degradation",
    "positive_splits": "Positive OOS Splits",
}

def row_numeric(df, label):
    m = df[0].astype(str) == label
    if not m.any():
        return None
    return pd.to_numeric(df.loc[m].iloc[0].iloc[6:], errors="coerce")

def row_pct(df, label):
    m = df[0].astype(str) == label
    if not m.any():
        return None
    out = []
    for x in df.loc[m].iloc[0].iloc[6:]:
        if pd.isna(x) or x == "":
            out.append(np.nan)
            continue
        s = str(x).strip().rstrip("%")
        try:
            out.append(float(s))
        except ValueError:
            out.append(np.nan)
    return pd.Series(out)

def analyze(path):
    df = pd.read_csv(path, header=None, low_memory=False)
    series_list = {}
    for k, lab in LABELS.items():
        series_list[k] = row_pct(df, lab) if k == "degradation" else row_numeric(df, lab)
    lengths = [len(s.dropna()) for s in series_list.values() if s is not None]
    n = max(lengths) if lengths else 0
    mat = {k: s.values[:n] for k, s in series_list.items() if s is not None}
    return df.shape, pd.DataFrame(mat)

def summarize(tab, name):
    print(f"=== {name} ===")
    print(f"Solutions: {len(tab)}")
    if tab.empty:
        return
    cols_m = ["sortino_is","agg_oos_sortino","pf_is","pf_oos","dd_is","dd_oos","pnl_is","pnl_oos","trades_is","degradation","positive_splits"]
    for col in cols_m:
        if col not in tab.columns:
            continue
        s = tab[col].dropna()
        if len(s) == 0:
            continue
        suf = "%" if col == "degradation" else ""
        print(f"  {col}: n={len(s)} med={s.median():.5g}{suf} p10-p90=[{s.quantile(0.1):.5g},{s.quantile(0.9):.5g}] max={s.max():.5g}")

def compare(a, b, col, la, lb):
    if col not in a.columns or col not in b.columns:
        return
    sa, sb = a[col].dropna(), b[col].dropna()
    if len(sa) == 0 or len(sb) == 0:
        return
    print(f"  {col}: {la} med={sa.median():.5g} vs {lb} med={sb.median():.5g} (delta {sa.median() - sb.median():+.5g})")

base = Path(r"C:\Trading\Trend\parameters")
runs = {
    "Latest 2026-05-08-2": base / "genetic_results_2026-05-08-2.csv",
    "Prior 2026-05-08-1": base / "genetic_results_2026-05-08-1.csv",
    "Prior 2026-05-07-1 (50 cap)": base / "genetic_results_2026-05-07-1.csv",
    "Prior 2026-05-05-1": base / "genetic_results_2026-05-05-1.csv",
}
tables = {}
for name, p in runs.items():
    sh, tab = analyze(str(p))
    print(f"\nFile {p.name} raw shape {sh}")
    summarize(tab, name)
    tables[name] = tab

tab = tables["Latest 2026-05-08-2"]
cols = [c for c in ["sortino_is","agg_oos_sortino","pf_is","pf_oos","dd_is","dd_oos","pnl_is","pnl_oos","trades_is","degradation","positive_splits"] if c in tab.columns]
if len(tab):
    print("\n--- Top 12 by IS Sortino (latest run) ---")
    print(tab.nlargest(12, "sortino_is")[cols].to_string())
    print("\n--- Lowest degradation in top decile IS Sortino (latest) ---")
    d0 = tab["sortino_is"].quantile(0.9)
    hi = tab[tab["sortino_is"] >= d0].copy()
    if "degradation" in hi.columns:
        hi = hi.sort_values(["degradation", "sortino_is"], ascending=[True, False])
        print(f"P90 IS Sortino cutoff = {d0:.4g}, n={len(hi)}")
        print(hi.head(12)[cols].to_string())
    print("\n--- Highest OOS PF in top quartile IS Sortino (latest) ---")
    q75 = tab["sortino_is"].quantile(0.75)
    hi2 = tab[tab["sortino_is"] >= q75]
    if "pf_oos" in hi2.columns:
        print(f"Q75 IS Sortino = {q75:.4g}, pool n={len(hi2)}")
        print(hi2.nlargest(12, "pf_oos")[cols].to_string())

print("\n--- Latest vs 2026-05-08-1 (median shifts) ---")
compare(tables["Latest 2026-05-08-2"], tables["Prior 2026-05-08-1"], "sortino_is", "latest", "05-08-1")
compare(tables["Latest 2026-05-08-2"], tables["Prior 2026-05-08-1"], "pf_is", "latest", "05-08-1")
compare(tables["Latest 2026-05-08-2"], tables["Prior 2026-05-08-1"], "pf_oos", "latest", "05-08-1")
compare(tables["Latest 2026-05-08-2"], tables["Prior 2026-05-08-1"], "dd_is", "latest", "05-08-1")
compare(tables["Latest 2026-05-08-2"], tables["Prior 2026-05-08-1"], "degradation", "latest", "05-08-1")
compare(tables["Latest 2026-05-08-2"], tables["Prior 2026-05-08-1"], "trades_is", "latest", "05-08-1")

print("\n--- Latest vs 2026-05-05-1 (median shifts) ---")
compare(tables["Latest 2026-05-08-2"], tables["Prior 2026-05-05-1"], "sortino_is", "latest", "05-05")
compare(tables["Latest 2026-05-08-2"], tables["Prior 2026-05-05-1"], "pf_oos", "latest", "05-05")
