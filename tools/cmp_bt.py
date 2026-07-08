import os
import sys
sys.path.insert(0, r"C:\Trading")
import pandas as pd
from backtest import load_ga_params, run_backtest
from strategies.bollinger.parameters import load_params
from strategies.trend.parameters import get_param_value
from strategies.trend.reporting import calculate_stats, generate_dashboard

DATA = r"C:\Trading\Bollinger\data\ES_full_1min_continuous_ratio_adjusted.csv"
GA = r"C:\Trading\Trend\parameters\genetic_results_2026-06-11-1.csv"
DEP = r"C:\Trading\strategies\trend\parameters\trend_strategy_params.csv"
START, END = "2020-01-02", "2025-10-10"

def bar_span_minutes(trades_df, tf):
    if trades_df is None or trades_df.empty:
        return 0.0
    st = pd.to_datetime(trades_df["entry_time"])
    et = pd.to_datetime(trades_df["exit_time"])
    rule = f"{int(tf)}min"
    entry_bar = st.dt.floor(rule)
    exit_bar = et.dt.floor(rule)
    delta = (exit_bar - entry_bar).dt.total_seconds() / 60.0
    n_bars = (delta.fillna(0) / tf + 1.0).clip(lower=1.0)
    return float((n_bars * tf).mean())

def run_case(label, params, src):
    res = run_backtest("trend", DATA, params, suppress_log=True, start_date=START, end_date=END)
    stats = calculate_stats(res["trades_df"], res.get("equity_curve"))
    tf = int(get_param_value(params, "Timeframe (minutes)", 15))
    span = bar_span_minutes(res["trades_df"], tf)
    return label, src, tf, stats, span, res

print("=== Full-period backtest (backtest.py) ===")
print("Window:", START, "to", END)
rows = []
solutions = []
for label, loader in [
    ("Deployed (Value)", lambda: load_params(DEP)),
    ("Solution_2044", lambda: load_ga_params(GA, 2044)[0]),
]:
    src = DEP if label.startswith("Deployed") else GA
    params = loader()
    label, src, tf, stats, span, res = run_case(label, params, src)
    print("\n" + label)
    print("  PnL:       ${:,.2f}".format(stats["Total PnL"]))
    print("  Trades:    {}".format(stats["Trades"]))
    print("  Win rate:  {:.1f}%".format(stats["Win Rate"]))
    print("  PF:        {:.3f}".format(stats["Profit Factor"]))
    print("  Sortino:   {:.3f}".format(stats["Sortino"]))
    print("  Max DD:    ${:,.2f}".format(stats["Max Drawdown"]))
    print("  Ret/DD:    {:.1f}".format(stats["Ret/DD"]))
    print("  Trades/d:  {:.3f}".format(stats["Avg Trades/Day"]))
    print("  Span:      {:.1f} min".format(span))
    print("  Raw dur:   {:.1f} min".format(stats["Avg Duration (min)"]))
    print("  PnL/trade: ${:,.2f}".format(stats["Total PnL"] / max(1, stats["Trades"])))
    print("  TF:        {} min".format(tf))
    rows.append({
        "Label": label,
        "Total_PnL": stats["Total PnL"],
        "Trades": stats["Trades"],
        "Win_Rate_pct": stats["Win Rate"],
        "PF": stats["Profit Factor"],
        "Sortino": stats["Sortino"],
        "Max_DD": stats["Max Drawdown"],
        "Ret_DD": stats["Ret/DD"],
        "Trades_Day": stats["Avg Trades/Day"],
        "Span_bar_grid_min": span,
        "Duration_raw_min": stats["Avg Duration (min)"],
        "Timeframe_min": tf,
    })
    solutions.append({
        "name": label,
        "stats": stats,
        "params": params,
        "params_source": src,
        "trades_df": res["trades_df"],
        "equity_curve": res.get("equity_curve", pd.Series(dtype=float)),
        "df": res.get("df"),
        "action_log": res.get("action_log", []),
    })

out = r"C:\Trading\results\comparison_deployed_vs_2044.csv"
pd.DataFrame(rows).to_csv(out, index=False)
print("\nSaved:", out)
web = r"C:\Trading\web"
os.makedirs(web, exist_ok=True)
dash = "backtest_comparison_deployed_vs_2044.html"
generate_dashboard(solutions, output_dir=web, version="5.0", filename=dash, open_browser=False)
print("Dashboard:", os.path.join(web, dash))
