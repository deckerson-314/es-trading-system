#!/usr/bin/env python3
"""
Visualize Parameter Analysis (V4)
Generates correlation heatmaps, tornado plots, and parameter convergence charts for the BB Strategy GA V4.
Handles V4 Data Structures (6-objective fitness) and Un-normalizes values for correct $ display.
"""

import sys
import os
import pickle
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from deap import base, creator, tools
from datetime import datetime

# ==============================================================================
# CONFIGURATION
# ==============================================================================
CHECKPOINT_FILE = r'ga_diagnostics_v4/ga_checkpoint_v4.pkl'
PARAM_FILE = r'Bollinger/parameters/backtest_params.csv'
# Output to WEB directory for remote access
OUTPUT_DIR = r'web/parameter_analysis'
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Define Normalization Defaults (Will be overwritten by CSV load)
NORM_DEFAULTS = {
    'NORM_SORTINO_MAX': 10.0,
    'NORM_DD_MAX': 50000.0, # Note: This is 50k in CSV, but Normalized DD is 1 - (DD/Max).
    'NORM_PF_MAX': 5.0,
    'NORM_TRADES_MAX': 3.0,
    'NORM_PNL_MAX': 600000.0, # Target 600k
    'NORM_PROFIT_TRADE_MAX': 100.0
}

# ==============================================================================
# DEAP SETUP (Required to unpickle)
# ==============================================================================
if not hasattr(creator, "FitnessMulti"):
    # V4 uses 6 weights: Sortino, DD, PF, Trades, Total PnL, Avg Profit/Trade
    creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 1.0, 2.0, 2.0))
if not hasattr(creator, "Individual"):
    creator.create("Individual", list, fitness=creator.FitnessMulti)

# ==============================================================================
# LOADING FUNCTIONS
# ==============================================================================
def load_normalization_constants():
    """Load normalization constants from backtest_params.csv"""
    norm_consts = NORM_DEFAULTS.copy()
    try:
        df = pd.read_csv(PARAM_FILE)
        for _, row in df.iterrows():
            name = str(row['Name'])
            if name in norm_consts:
                try:
                    norm_consts[name] = float(row['Value'])
                except:
                    pass
        print(f"Loaded Normalization Constants: PNL_MAX=${norm_consts['NORM_PNL_MAX']:,.0f}, DD_MAX=${norm_consts['NORM_DD_MAX']:,.0f}")
    except Exception as e:
        print(f"Warning: Could not load param CSV ({e}). Using defaults.")
    return norm_consts

def unnormalize_fitness(fitness_values, norm_consts):
    """
    Convert normalized fitness (0-1) back to raw values for display.
    V4 Tuple: (Sortino, DD, PF, Trades, PnL, AvgProfitMs)
    """
    # Unpack (Handle cases where tuple length varies if using older checkpoints)
    f = list(fitness_values)
    
    # 0: Sortino
    raw_sortino = f[0] * norm_consts['NORM_SORTINO_MAX']
    
    # 1: Drawdown (Normalized is 1.0 - (DD / Max))
    # So DD = (1.0 - Normalized) * Max
    # However, sometimes optimization pushes it above 1.0 or below 0.0 with penalties.
    # We need to be careful.
    raw_dd = (1.0 - f[1]) * norm_consts['NORM_DD_MAX']
    
    # 2: Profit Factor
    raw_pf = f[2] * norm_consts['NORM_PF_MAX']
    
    # 3: Trades (Actually Raw in V4? line 724: normalized_trades = avg_trades_day # Raw)
    # Wait, let's verify line 724 of BB_Genetic_v4.py: "normalized_trades = avg_trades_day  # Raw"
    # But later it applies penalties.
    # We will assume it's scaled by NORM_TRADES_MAX if it looks small (<=1.0) but if it's >1 it might be raw.
    # Actually, let's just assume Raw for Trades as per code comment, but if it looks like < 1.0 for a high freq strategy, it might be normalized?
    # View_file showed: normalized_trades = avg_trades_day (Line 724).
    # Then: output = (..., normalized_trades, ...)
    # So Trades is RAW.
    raw_trades = f[3]
    
    # 4: PnL
    raw_pnl = f[4] * norm_consts['NORM_PNL_MAX']
    
    # 5: Avg Profit/Trade
    # normalized_ppt = min(avg / max, 1.0)
    # So raw = normalized * max
    if len(f) > 5:
        raw_ppt = f[5] * norm_consts['NORM_PROFIT_TRADE_MAX']
    else:
        raw_ppt = 0.0
        
    return raw_sortino, raw_dd, raw_pf, raw_trades, raw_pnl, raw_ppt

def load_data():
    if not os.path.exists(CHECKPOINT_FILE):
        print(f"ERROR: Checkpoint not found at {CHECKPOINT_FILE}")
        return None, None
        
    try:
        with open(CHECKPOINT_FILE, 'rb') as f:
            cp = pickle.load(f)
        
        pop = cp.get('population', [])
        hof = cp.get('halloffame', [])
        
        # Merge Pop + Hall of Fame (unique only)
        # Use string representation of params as key
        unique_inds = {}
        
        # Parameters Keys
        # Try to find param_keys in cp, or load from CSV if missing
        if 'config' in cp and 'param_keys' in cp['config']:
            param_keys = cp['config']['param_keys']
        elif 'param_keys' in cp:
            param_keys = cp['param_keys']
        else:
            # Fallback reading CSV
            print("Warning: Param keys missing in checkpoint. Inferring from CSV.")
            df_p = pd.read_csv(PARAM_FILE)
            # Filter optimization params
            param_keys = []
            excluded_prefixes = ['NORM_', 'POP_', 'NUM_', 'CX_', 'MUT_', 'TARGET_', 'TRADES_', 'DD_', 'DATA_', 'USE_', 'MIN_']
            for _, row in df_p.iterrows():
                name = str(row['Name'])
                if name.startswith('==') or name.startswith('__'): continue
                # Skip config parameters
                if any(name.startswith(pre) for pre in excluded_prefixes): continue
                
                if row['Min'] != row['Max']:
                    param_keys.append(row['Name'])
                    
        # Process Individuals
        data = []
        norm_consts = load_normalization_constants()
        
        all_inds = list(pop) + list(hof)
        print(f"Processing {len(all_inds)} individuals...")
        
        for i, ind in enumerate(all_inds):
            if not ind.fitness.valid: continue
            
            # Un-normalize fitness
            s, d, p, t, pnl, ppt = unnormalize_fitness(ind.fitness.values, norm_consts)
            
            # Create Row
            row = {}
            # Add Params
            for k, v in zip(param_keys, ind):
                row[k] = v
                
            # Add Metrics
            row['Sortino'] = s
            row['MaxDD'] = d
            row['ProfitFactor'] = p
            row['TradesDay'] = t
            row['TotalPnL'] = pnl
            row['AvgProfitTrade'] = ppt
            row['Generation'] = getattr(ind, 'generation_found', 0)
            
            # Deduplication Key (Params)
            pkey = tuple(ind)
            if pkey not in unique_inds:
                unique_inds[pkey] = row
            else:
                # Keep the instance with better generation found? Or identical?
                pass
                
        df = pd.DataFrame(list(unique_inds.values()))
        print(f"Loaded {len(df)} unique solutions.")
        return df, param_keys
        
    except Exception as e:
        print(f"CRITICAL ERROR loading checkpoint: {e}")
        import traceback
        traceback.print_exc()
        return None, None

# ==============================================================================
# PLOTTING
# ==============================================================================
def create_correlation_heatmap(df, param_keys):
    """
    Heatmap: Correlations between Parameters and Metrics (PnL, Sortino)
    """
    # Select columns: All Params + Metrics
    metrics = ['Sortino', 'MaxDD', 'ProfitFactor', 'TradesDay', 'TotalPnL']
    
    # Filter keys to only those present in DF
    valid_keys = [k for k in param_keys if k in df.columns]
    
    cols = valid_keys + metrics
    
    # Calculate Correlation Matrix
    corr = df[cols].corr()
    
    # Extract only Param vs Metric correlations for cleaner view
    # Rows: Params, Cols: Metrics
    param_metric_corr = corr.loc[valid_keys, metrics]
    
    fig = px.imshow(param_metric_corr,
                    labels=dict(x="Metric", y="Parameter", color="Correlation"),
                    x=metrics,
                    y=valid_keys,
                    color_continuous_scale='RdBu_r',
                    title="Parameter Impact on Performance (Correlation Heatmap)")
    
    fig.update_layout(height=800, width=1000)
    
    filename = os.path.join(OUTPUT_DIR, 'parameter_correlation.html')
    fig.write_html(filename)
    print(f"Generated: {filename}")
    return filename

def create_tornado_plot(df, param_keys, target_metric='TotalPnL'):
    """
    Tornado Plot: Feature Importance (based on Correlation magnitude)
    """
    corrs = []
    for p in param_keys:
        try:
            c = df[p].corr(df[target_metric])
            corrs.append({'Parameter': p, 'Correlation': c, 'AbsCorr': abs(c)})
        except:
            pass
            
    cdf = pd.DataFrame(corrs).sort_values('AbsCorr', ascending=True)
    
    fig = px.bar(cdf, x='Correlation', y='Parameter', orientation='h',
                 title=f"Parameter Importance (Correlation with {target_metric})",
                 color='Correlation',
                 color_continuous_scale='RdBu_r')
                 
    fig.update_layout(height=800, width=1000)
    
    filename = os.path.join(OUTPUT_DIR, f'parameter_importance_{target_metric}.html')
    fig.write_html(filename)
    print(f"Generated: {filename}")
    return filename

def create_scatter_matrix(df, top_params, metric='TotalPnL'):
    """
    Scatter plot of Top 3 Params vs PnL
    """
    fig = px.scatter_matrix(df, dimensions=top_params, color=metric,
                            title=f"Interaction: Top Parameters vs {metric}",
                            color_continuous_scale='Viridis')
    fig.update_layout(height=1000, width=1000)
    filename = os.path.join(OUTPUT_DIR, 'parameter_interactions.html')
    fig.write_html(filename)
    print(f"Generated: {filename}")

def main():
    print("--- Starting GA Parameter Analysis (V4) ---")
    df, param_keys = load_data()
    if df is None or df.empty:
        print("No data loaded. Exiting.")
        return
    
    # Global Filter: Only keep keys present in DF
    # This handles mismatched config params
    valid_keys = [k for k in param_keys if k in df.columns]
    print(f"Valid Optimization Parameters found: {len(valid_keys)}")

    # Basic Stats
    print("\nTop Solution Stats (Raw/Un-normalized):")
    best_pnl = df.sort_values('TotalPnL', ascending=False).iloc[0]
    print(f"Best PnL:     ${best_pnl['TotalPnL']:,.2f}")
    print(f"Best Sortino: {best_pnl['Sortino']:.2f}")
    
    # Generate Charts using VALID keys
    create_correlation_heatmap(df, valid_keys)
    create_tornado_plot(df, valid_keys, 'TotalPnL')
    create_tornado_plot(df, valid_keys, 'Sortino')
    
    # Identify Top 4 Params for Scatter
    try:
        corrs = df[valid_keys].corrwith(df['TotalPnL']).abs().sort_values(ascending=False)
        top_params = corrs.head(4).index.tolist()
        create_scatter_matrix(df, top_params, 'TotalPnL')
    except Exception as e:
        print(f"Skipping Scatter Matrix: {e}")
    
    print("\nAnalysis Complete.")

if __name__ == "__main__":
    main()
