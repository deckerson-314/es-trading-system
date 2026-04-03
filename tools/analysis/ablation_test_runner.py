import pandas as pd
import os
import subprocess
import json
import re
from datetime import datetime

# Configuration
STRATEGY = "trend"
DATA_PATH = r"c:\Trading\data\Q1_ES_1min_cleaned.csv"
BASE_PARAMS_PATH = r"c:\Trading\strategies\trend\parameters\params_naked.csv"
RESULTS_FILE = r"c:\Trading\phase3_results.md"

def load_params(path):
    return pd.read_csv(path)

def save_params(df, path):
    df.to_csv(path, index=False)

def run_backtest(params_path):
    cmd = [
        "python", "backtest.py",
        "--strategy", STRATEGY,
        "--data", DATA_PATH,
        "--params", params_path
    ]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout

def parse_metrics(output):
    # Total PnL: $-475.00 | WR: 30.0% | PF: 0.97
    metrics = {}
    pnl_match = re.search(r"Total PnL: \$(-?[\d,.]+)", output)
    wr_match = re.search(r"WR: ([\d.]+)%", output)
    pf_match = re.search(r"PF: ([\d.]+)", output)
    
    # We also want Trades and Sortino if available in single-run mode
    # If not, we might need to modify backtest.py to print them or parse the trades_v4 CSV
    metrics['PnL'] = float(pnl_match.group(1).replace(',', '')) if pnl_match else 0.0
    metrics['WR%'] = float(wr_match.group(1)) if wr_match else 0.0
    metrics['PF'] = float(pf_match.group(1)) if pf_match else 0.0
    
    # Estimate trades from log if not explicitly printed
    # In single run mode, backtest.py might not print trade count directly in the "Total PnL" line
    # But it calculates it. 
    return metrics

def main():
    base_df = load_params(BASE_PARAMS_PATH)
    
    test_suites = [
        {"name": "Baseline (Naked)", "changes": {}},
        
        {"name": "Vol: Min ATR (2.0)", "changes": {"Min ATR (Points)": 2.0}},
        {"name": "Vol: Volume Filter (1.5x)", "changes": {"Enable Volume Filter": 1, "Min Volume Multiplier": 1.5}},
        
        {"name": "Mom: ADX Filter (20)", "changes": {"Enable ADX Filter": 1, "Min ADX Threshold": 20.0}},
        {"name": "Mom: ADX Filter (30)", "changes": {"Enable ADX Filter": 1, "Min ADX Threshold": 30.0}},
        
        {"name": "Trend: SMA 200", "changes": {"Enable SMA Filter": 1, "SMA Period": 200}},
        {"name": "Trend: VWAP", "changes": {"Enable VWAP Filter": 1}},
        
        {"name": "Exh: RSI (70/30)", "changes": {"Enable RSI Filter": 1, "RSI Max Buy Threshold": 70, "RSI Min Sell Threshold": 30}},
        
        {"name": "Combined: Vol + Trend", "changes": {
            "Enable Volume Filter": 1, "Min Volume Multiplier": 1.5,
            "Enable SMA Filter": 1, "SMA Period": 200,
            "Enable VWAP Filter": 1
        }}
    ]
    
    final_results = []
    
    for suite in test_suites:
        print(f"\n--- Testing Suite: {suite['name']} ---")
        temp_params = base_df.copy()
        for param, val in suite['changes'].items():
            temp_params.loc[temp_params['Name'] == param, 'Value'] = val
            
        temp_path = f"params_temp_{datetime.now().strftime('%H%M%S')}.csv"
        save_params(temp_params, temp_path)
        
        output = run_backtest(temp_path)
        metrics = parse_metrics(output)
        metrics['Suite'] = suite['name']
        final_results.append(metrics)
        
        os.remove(temp_path)
        
    # Generate Markdown Table
    res_df = pd.DataFrame(final_results)
    res_df = res_df[['Suite', 'PnL', 'WR%', 'PF']]
    
    # Simple manual markdown builder
    headers = res_df.columns.tolist()
    header_row = "| " + " | ".join(headers) + " |"
    sep_row = "| " + " | ".join(["---"] * len(headers)) + " |"
    
    data_rows = []
    for _, row in res_df.iterrows():
        row_str = "| " + " | ".join([str(val) for val in row.values]) + " |"
        data_rows.append(row_str)
        
    md_table = "\n".join([header_row, sep_row] + data_rows)
    
    report = f"# Phase 3: Ablation Study Results\n\nGenerated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n{md_table}"
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
    
    with open(RESULTS_FILE, 'w') as f:
        f.write(report)
        
    print(f"\nResults saved to {RESULTS_FILE}")

if __name__ == "__main__":
    main()
