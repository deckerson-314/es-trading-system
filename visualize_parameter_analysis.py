#!/usr/bin/env python3
"""
Comprehensive parameter analysis and visualization for GA results.
Shows parameter convergence, effects on metrics, and sensitivity analysis.
"""

import pickle
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px

CHECKPOINT_FILE = 'ga_diagnostics_v3/ga_checkpoint_v3.pkl'
OUTPUT_DIR = 'ga_diagnostics_v3/parameter_analysis'
os.makedirs(OUTPUT_DIR, exist_ok=True)

print("="*80)
print("PARAMETER ANALYSIS AND VISUALIZATION")
print("="*80)

# Load checkpoint
if not os.path.exists(CHECKPOINT_FILE):
    print(f"ERROR: Checkpoint not found: {CHECKPOINT_FILE}")
    exit(1)

with open(CHECKPOINT_FILE, 'rb') as f:
    checkpoint = pickle.load(f)

hof = checkpoint.get('hall_of_fame', [])
logbook = checkpoint.get('logbook', None)
gen = checkpoint.get('generation', 0)

print(f"Generation: {gen}")
print(f"Pareto Solutions: {len(hof)}")
print()

# Load parameter dictionary to get parameter names
from bollinger_strategy.parameters import load_params
PARAM_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv'
param_dict, param_df = load_params(PARAM_CSV, return_dataframe=True)

# GA Criteria parameters (meta-parameters that control the GA itself)
GA_CRITERIA_PARAMS = {
    'POP_SIZE', 'NUM_GEN', 'CX_PB', 'MUT_PB', 'MUT_MU', 'MUT_SIGMA',
    'TARGET_TRADES_DAY', 'TRADES_PENALTY_WEIGHT', 'DD_WEIGHT',
    'DATA_SPLITS', 'DATA_SIZE', 'USE_INTERLEAVED_SPLIT', 'NUM_SPLIT_PERIODS',
    'MIN_TRADES_DAY', 'MIN_TRADES_PEN_WEIGHT', 'NORM_SORTINO_MAX', 'NORM_DD_MAX',
    'NORM_PF_MAX', 'NORM_TRADES_MAX', 'NORM_PNL_MAX', 'MIN_WIN_RATE', 'SORTINO_CAP'
}

# Get optimizable parameter keys (STRATEGY parameters only, exclude GA meta-parameters)
param_keys = [k for k in param_dict.keys() 
              if not k.startswith('__') 
              and k != '=== ENTRY CRITERIA ===' 
              and k != '=== TAKE PROFIT CRITERIA ==='
              and k != '=== STOP LOSS CRITERIA ==='
              and k != '=== GA CRITERIA ==='
              and k not in GA_CRITERIA_PARAMS  # Exclude GA meta-parameters
              and param_dict[k].get('type') in ('int', 'float')
              and param_dict[k].get('min') is not None 
              and param_dict[k].get('max') is not None
              and param_dict[k]['min'] != param_dict[k]['max']]  # Only optimizable params

print(f"Optimizable Parameters: {len(param_keys)}")
print(f"  {', '.join(param_keys[:10])}...")
print()

# Extract parameter values and fitness from Hall of Fame
if hof and len(hof) > 0:
    data = []
    for i, ind in enumerate(hof):
        if hasattr(ind, 'fitness') and ind.fitness.valid:
            fitness = ind.fitness.values
            if len(fitness) >= 5:
                row = {
                    'solution_id': i,
                    'sortino': fitness[0],
                    'drawdown': fitness[1],
                    'profit_factor': fitness[2],
                    'avg_trades_day': fitness[3],
                    'total_profit': fitness[4]
                }
                # Add parameter values
                for j, param_name in enumerate(param_keys):
                    if j < len(ind):
                        row[param_name] = ind[j]
                data.append(row)
    
    df = pd.DataFrame(data)
    print(f"Extracted {len(df)} solutions with valid fitness")
    print()
    
    # ====================================================================
    # 1. PARAMETER CONVERGENCE ANALYSIS
    # ====================================================================
    print("1. Generating Parameter Convergence Analysis...")
    
    # For convergence, we need generation-by-generation data
    # Since we only have final Hall of Fame, we'll analyze parameter distributions
    # and show how they relate to fitness
    
    # Filter to only parameters that exist in dataframe
    available_params = [p for p in param_keys if p in df.columns]
    if len(available_params) == 0:
        print("ERROR: No parameters found in dataframe!")
        exit(1)
    
    # Select top parameters to visualize (most variable or most important)
    param_variance = df[available_params].var().sort_values(ascending=False)
    top_params = param_variance.head(12).index.tolist()  # Top 12 most variable
    
    # Create convergence-style plots (parameter value vs fitness)
    fig_conv = make_subplots(
        rows=4, cols=3,
        subplot_titles=[f'{p}' for p in top_params],
        vertical_spacing=0.08,
        horizontal_spacing=0.1
    )
    
    for idx, param in enumerate(top_params):
        row = (idx // 3) + 1
        col = (idx % 3) + 1
        
        # Scatter: parameter value vs Sortino (main fitness metric)
        fig_conv.add_trace(
            go.Scatter(
                x=df[param],
                y=df['sortino'],
                mode='markers',
                marker=dict(size=5, opacity=0.6, color=df['avg_trades_day'], 
                          colorscale='Viridis', showscale=(idx==0),
                          colorbar=dict(title="Trades/Day", x=1.02)),
                name=param,
                showlegend=False
            ),
            row=row, col=col
        )
        
        # Add trend line
        z = np.polyfit(df[param], df['sortino'], 1)
        p = np.poly1d(z)
        x_trend = np.linspace(df[param].min(), df[param].max(), 100)
        fig_conv.add_trace(
            go.Scatter(
                x=x_trend,
                y=p(x_trend),
                mode='lines',
                line=dict(color='red', width=2, dash='dash'),
                name='Trend',
                showlegend=False
            ),
            row=row, col=col
        )
        
        fig_conv.update_xaxes(title_text=param, row=row, col=col)
        fig_conv.update_yaxes(title_text="Sortino", row=row, col=col)
    
    fig_conv.update_layout(
        height=1200,
        title_text="Parameter vs Sortino (Top 12 Most Variable Parameters)",
        showlegend=False
    )
    fig_conv.write_html(f'{OUTPUT_DIR}/parameter_convergence_vs_sortino.html')
    print(f"  → {OUTPUT_DIR}/parameter_convergence_vs_sortino.html")
    
    # ====================================================================
    # 2. PARAMETER EFFECTS ON METRICS (Correlation Analysis)
    # ====================================================================
    print("2. Generating Parameter Effects Analysis...")
    
    # Calculate correlations between parameters and metrics
    metrics = ['sortino', 'drawdown', 'profit_factor', 'avg_trades_day', 'total_profit']
    
    correlation_matrix = pd.DataFrame(index=available_params, columns=metrics)
    for param in available_params:
        for metric in metrics:
            try:
                from scipy import stats
                corr, p_value = stats.pearsonr(df[param], df[metric])
            except:
                # Fallback to numpy correlation
                corr = np.corrcoef(df[param], df[metric])[0, 1]
            correlation_matrix.loc[param, metric] = corr
    
    correlation_matrix = correlation_matrix.astype(float)
    
    # Create heatmap
    fig_heatmap = go.Figure(data=go.Heatmap(
        z=correlation_matrix.values,
        x=correlation_matrix.columns,
        y=correlation_matrix.index,
        colorscale='RdBu',
        zmid=0,
        text=correlation_matrix.values.round(2),
        texttemplate='%{text}',
        textfont={"size": 8},
        colorbar=dict(title="Correlation")
    ))
    
    fig_heatmap.update_layout(
        title="Parameter-Metric Correlation Heatmap",
        xaxis_title="Metrics",
        yaxis_title="Parameters",
        height=max(600, len(param_keys) * 20),
        width=800
    )
    fig_heatmap.write_html(f'{OUTPUT_DIR}/parameter_metric_correlation.html')
    print(f"  → {OUTPUT_DIR}/parameter_metric_correlation.html")
    
    # Save correlation matrix to CSV
    correlation_matrix.to_csv(f'{OUTPUT_DIR}/parameter_metric_correlation.csv')
    print(f"  → {OUTPUT_DIR}/parameter_metric_correlation.csv")
    
    # ====================================================================
    # 3. SENSITIVITY ANALYSIS (Parameter Importance)
    # ====================================================================
    print("3. Generating Sensitivity Analysis...")
    
    # Use multiple methods to assess parameter importance:
    # 1. Correlation with Sortino (primary objective)
    # 2. Variance in top solutions vs bottom solutions
    # 3. Range utilization (how much of the allowed range is used)
    
    sensitivity_data = []
    
    # Sort solutions by Sortino
    df_sorted = df.sort_values('sortino', ascending=False)
    top_25_pct = df_sorted.head(max(1, len(df_sorted) // 4))
    bottom_25_pct = df_sorted.tail(max(1, len(df_sorted) // 4))
    
    for param in available_params:
        
        # Method 1: Correlation with Sortino
        try:
            from scipy import stats
            corr_sortino, _ = stats.pearsonr(df[param], df['sortino'])
        except:
            corr_sortino = np.corrcoef(df[param], df['sortino'])[0, 1]
        
        # Method 2: Difference between top and bottom solutions
        if len(top_25_pct) > 0 and len(bottom_25_pct) > 0:
            top_mean = top_25_pct[param].mean()
            bottom_mean = bottom_25_pct[param].mean()
            diff_pct = abs((top_mean - bottom_mean) / (df[param].max() - df[param].min() + 1e-10)) * 100
        else:
            diff_pct = 0
        
        # Method 3: Range utilization
        param_min = param_dict[param]['min']
        param_max = param_dict[param]['max']
        range_used = (df[param].max() - df[param].min()) / (param_max - param_min + 1e-10) * 100
        
        # Method 4: Standard deviation (variability)
        std_dev = df[param].std()
        std_pct = (std_dev / (param_max - param_min + 1e-10)) * 100
        
        sensitivity_data.append({
            'parameter': param,
            'correlation_with_sortino': abs(corr_sortino),
            'top_bottom_diff_pct': diff_pct,
            'range_utilization_pct': range_used,
            'variability_pct': std_pct,
            'importance_score': abs(corr_sortino) * 0.4 + diff_pct * 0.3 + range_used * 0.2 + std_pct * 0.1
        })
    
    sensitivity_df = pd.DataFrame(sensitivity_data)
    sensitivity_df = sensitivity_df.sort_values('importance_score', ascending=False)
    
    # Create tornado plot (parameter importance)
    fig_tornado = go.Figure()
    
    top_10 = sensitivity_df.head(10)
    
    fig_tornado.add_trace(go.Bar(
        y=top_10['parameter'],
        x=top_10['importance_score'],
        orientation='h',
        marker=dict(color=top_10['importance_score'], colorscale='Viridis'),
        text=[f"{s:.2f}" for s in top_10['importance_score']],
        textposition='outside'
    ))
    
    fig_tornado.update_layout(
        title="Parameter Importance (Top 10)",
        xaxis_title="Importance Score",
        yaxis_title="Parameter",
        height=500,
        width=800
    )
    fig_tornado.write_html(f'{OUTPUT_DIR}/parameter_importance_tornado.html')
    print(f"  → {OUTPUT_DIR}/parameter_importance_tornado.html")
    
    # Save sensitivity analysis
    sensitivity_df.to_csv(f'{OUTPUT_DIR}/parameter_sensitivity_analysis.csv', index=False)
    print(f"  → {OUTPUT_DIR}/parameter_sensitivity_analysis.csv")
    
    # ====================================================================
    # 4. PARAMETER DISTRIBUTIONS
    # ====================================================================
    print("4. Generating Parameter Distribution Analysis...")
    
    # Compare parameter distributions in top vs bottom solutions
    fig_dist = make_subplots(
        rows=4, cols=3,
        subplot_titles=[f'{p}' for p in top_params],
        vertical_spacing=0.08,
        horizontal_spacing=0.1
    )
    
    for idx, param in enumerate(top_params):
        row = (idx // 3) + 1
        col = (idx % 3) + 1
        
        # Top 25% solutions
        fig_dist.add_trace(
            go.Histogram(
                x=top_25_pct[param],
                name='Top 25%',
                opacity=0.7,
                marker_color='green',
                nbinsx=20,
                showlegend=(idx==0)
            ),
            row=row, col=col
        )
        
        # Bottom 25% solutions
        fig_dist.add_trace(
            go.Histogram(
                x=bottom_25_pct[param],
                name='Bottom 25%',
                opacity=0.7,
                marker_color='red',
                nbinsx=20,
                showlegend=(idx==0)
            ),
            row=row, col=col
        )
        
        fig_dist.update_xaxes(title_text=param, row=row, col=col)
        fig_dist.update_yaxes(title_text="Count", row=row, col=col)
    
    fig_dist.update_layout(
        height=1200,
        title_text="Parameter Distributions: Top 25% vs Bottom 25% Solutions",
        barmode='overlay'
    )
    fig_dist.write_html(f'{OUTPUT_DIR}/parameter_distributions.html')
    print(f"  → {OUTPUT_DIR}/parameter_distributions.html")
    
    # ====================================================================
    # 5. PARAMETER INTERACTION EFFECTS
    # ====================================================================
    print("5. Generating Parameter Interaction Analysis...")
    
    # Find most important parameter pairs
    top_5_params = sensitivity_df.head(5)['parameter'].tolist()
    
    if len(top_5_params) >= 2:
        # Create 2D scatter plots for top parameter pairs
        fig_interactions = make_subplots(
            rows=2, cols=2,
            subplot_titles=[f'{top_5_params[i]} vs {top_5_params[i+1]}' 
                          for i in range(min(4, len(top_5_params)-1))],
            vertical_spacing=0.15,
            horizontal_spacing=0.15
        )
        
        for idx in range(min(4, len(top_5_params)-1)):
            row = (idx // 2) + 1
            col = (idx % 2) + 1
            param1 = top_5_params[idx]
            param2 = top_5_params[idx + 1]
            
            fig_interactions.add_trace(
                go.Scatter(
                    x=df[param1],
                    y=df[param2],
                    mode='markers',
                    marker=dict(
                        size=8,
                        color=df['sortino'],
                        colorscale='Viridis',
                        showscale=(idx==0),
                        colorbar=dict(title="Sortino", x=1.02) if idx==0 else None
                    ),
                    text=[f"Sortino: {s:.2f}<br>Trades/Day: {t:.2f}" 
                          for s, t in zip(df['sortino'], df['avg_trades_day'])],
                    hovertemplate='%{text}<extra></extra>',
                    showlegend=False
                ),
                row=row, col=col
            )
            
            fig_interactions.update_xaxes(title_text=param1, row=row, col=col)
            fig_interactions.update_yaxes(title_text=param2, row=row, col=col)
        
        fig_interactions.update_layout(
            height=800,
            title_text="Parameter Interactions (Top 5 Parameters)",
            showlegend=False
        )
        fig_interactions.write_html(f'{OUTPUT_DIR}/parameter_interactions.html')
        print(f"  → {OUTPUT_DIR}/parameter_interactions.html")
    
    # ====================================================================
    # 6. SUMMARY REPORT
    # ====================================================================
    print()
    print("="*80)
    print("PARAMETER ANALYSIS SUMMARY")
    print("="*80)
    print()
    print("Top 10 Most Important Parameters:")
    print(sensitivity_df.head(10)[['parameter', 'importance_score', 'correlation_with_sortino']].to_string(index=False))
    print()
    print("Parameters with Strongest Correlation to Sortino:")
    top_corr = sensitivity_df.nlargest(5, 'correlation_with_sortino')
    for _, row in top_corr.iterrows():
        print(f"  {row['parameter']}: {row['correlation_with_sortino']:.3f}")
    print()
    print("Parameters with Highest Top-Bottom Difference:")
    top_diff = sensitivity_df.nlargest(5, 'top_bottom_diff_pct')
    for _, row in top_diff.iterrows():
        print(f"  {row['parameter']}: {row['top_bottom_diff_pct']:.1f}%")
    print()
    print(f"All visualizations saved to: {OUTPUT_DIR}/")
    print("="*80)

