import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import re

def extract_chart_html(html_str):
    """Extract div and script from plotly html string using regex."""
    # Find the main div
    # Plotly output usually has id="param_interactive_plot" (or whatever was passed)
    div_match = re.search(r'(<div id="[^"]+".*?</div>)', html_str, re.DOTALL)
    div_part = div_match.group(1) if div_match else ""
    
    # Find the script part
    script_match = re.search(r'(<script type="text/javascript">.*?</script>)', html_str, re.DOTALL)
    script_part = script_match.group(1) if script_match else ""
    
    if not div_part and 'param_interactive_plot' in html_str:
        # Fallback if regex fails but ID exists (maybe simple split)
        parts = html_str.split('<script')
        div_part = parts[0]
        if len(parts) > 1:
            script_part = '<script' + parts[1]
            
    return div_part, script_part

def clamp_params(params, param_dict):
    """Clamp parameters to valid ranges."""
    clamped = {}
    for k, v in params.items():
        if k in param_dict:
            try:
                p_min = param_dict[k]['min']
                p_max = param_dict[k]['max']
                p_type = param_dict[k]['type']
                
                # Ensure min/max are numeric before comparing
                try:
                   p_min_val = float(p_min)
                   p_max_val = float(p_max)
                except:
                   # If bounds are not numeric (e.g. strings), skip clamping
                   clamped[k] = v
                   continue
                
                # Check if v is numeric
                if not isinstance(v, (int, float, np.number)):
                    clamped[k] = v
                    continue

                val = max(p_min_val, min(v, p_max_val))
                if p_type == 'int':
                    clamped[k] = int(round(val))
                else:
                    clamped[k] = float(val)
            except Exception as e:
                # Fallback on error
                # print(f"Clamp error for {k}: {e}")
                clamped[k] = v
        else:
            clamped[k] = v
    return clamped

def generate_interactive_analysis(hof, param_keys, param_dict, current_gen):
    """
    Generate Interactive Parameter Analysis (Two Dropdowns: Param & Metric).
    Un-normalizes PnL and other metrics for display.
    """
    if not hof or len(hof) < 1:
        print("DEBUG: No solutions in HOF to analyze.")
        return "<div id='param_interactive_plot'>No solutions to analyze.</div>", ""

    # ---------------------------------------------------------
    # 1. Prepare Data & Un-normalize
    # ---------------------------------------------------------
    # Get Normalization Constants from param_dict
    try:
        # Safe extraction helper
        def get_val(key, default):
            item = param_dict.get(key)
            if isinstance(item, dict):
                return float(item.get('value', default))
            return default

        norm_pnl_max = get_val('NORM_PNL_MAX', 200000.0)
        norm_ppt_max = get_val('NORM_PROFIT_TRADE_MAX', 250.0)
    except:
        norm_pnl_max = 200000.0
        norm_ppt_max = 250.0
        
    print(f"DEBUG: restore_param_analysis running. HOF Size={len(hof)}. NORM_PNL_MAX={norm_pnl_max}")
    
    data = []
    for ind in hof:
        params = dict(zip(param_keys, ind))
        clamped = clamp_params(params, param_dict)
        
        if hasattr(ind, 'fitness') and ind.fitness.valid:
            f = ind.fitness.values
            # V4 Fitness Tuple: (Sortino, DD, PF, Trades, PnL, AvgPPT)
            # Un-normalize PnL and PPT
            raw_pnl = f[4] * norm_pnl_max
            raw_ppt = f[5] * norm_ppt_max if len(f) > 5 else 0.0
            
            row = clamped.copy()
            row['Sortino'] = f[0]
            row['MaxDD'] = f[1] # Keep as normalized 0-1 score or convert if possible? DD is geometric.
            row['ProfitFactor'] = f[2]
            row['AvgTradesDay'] = f[3] # Already raw
            row['TotalPnL'] = raw_pnl
            row['AvgProfitTrade'] = raw_ppt
            data.append(row)
            
    if not data:
        print("DEBUG: Data extraction yielded empty list (fitness invalid?).")
        return "<div id='param_interactive_plot'>No valid data found.</div>", ""
        
    df = pd.DataFrame(data)
    print(f"DEBUG: DataFrame Created. Shape: {df.shape}")
    
    # ---------------------------------------------------------
    # 2. Identify Optimizable Parameters
    # ---------------------------------------------------------
    # Filter out fixed params
    valid_params = []
    for col in param_keys:
        if col in df.columns and col in param_dict:
             if pd.api.types.is_numeric_dtype(df[col]):
                 p_min = param_dict[col]['min']
                 p_max = param_dict[col]['max']
                 try:
                    # Check if min != max roughly
                    if str(p_min) != str(p_max):
                        valid_params.append(col)
                 except:
                    valid_params.append(col)
                     
    # Sort by importance (Correlation with PnL)
    try:
        corrs = df[valid_params].corrwith(df['TotalPnL']).abs().sort_values(ascending=False)
        sorted_params = corrs.index.tolist()
    except Exception as e:
        print(f"DEBUG: Correlation Sort Failed: {e}")
        sorted_params = valid_params
        
    if not sorted_params:
        return "<div id='param_interactive_plot'>No optimizable parameters found.</div>", ""

    # Metrics to Analyze
    metrics = ['TotalPnL', 'Sortino', 'ProfitFactor', 'AvgTradesDay', 'AvgProfitTrade']
    metrics_labels = ['Total Profit ($)', 'Sortino Ratio', 'Profit Factor', 'Avg Trades/Day', 'Avg Profit/Trade ($)']
    
    # ensure cols exist
    available_metrics = [m for m in metrics if m in df.columns]
    if not available_metrics:
        available_metrics = ['TotalPnL']

    # ---------------------------------------------------------
    # 3. Build Interactive Plot
    # ---------------------------------------------------------
    # Initial X and Y
    init_param = sorted_params[0]
    init_metric = available_metrics[0]
    
    fig = go.Figure()
    
    # Single trace that we update
    fig.add_trace(go.Scatter(
        x=df[init_param],
        y=df[init_metric],
        mode='markers',
        marker=dict(
            size=10,
            color=df['Sortino'], # Always color by Sortino for consistency
            colorscale='Viridis',
            colorbar=dict(title="Sortino"),
            showscale=True,
            line=dict(width=1, color='DarkSlateGrey')
        ),
        text=[f"S={r['Sortino']:.2f}<br>PF={r['ProfitFactor']:.2f}<br>PnL=${r['TotalPnL']:,.0f}" for _, r in df.iterrows()],
        hovertemplate="<b>%{x}</b><br>Value: %{y}<br>%{text}<extra></extra>",
        name="Solutions"
    ))
    
    # 1. Parameter Dropdown (X-Axis)
    param_buttons = []
    for param in sorted_params:
        # Pre-calculate X data
        param_buttons.append(dict(
            label=param,
            method="update",
            args=[
                {"x": [df[param]]}, # Update X data
                {"xaxis": {"title": param}, # Update X Title
                 "title": f"Parameter Analysis: {param} vs {init_metric}"} # Update Main Title (Partial)
            ]
        ))

    # 2. Metric Dropdown (Y-Axis)
    metric_buttons = []
    for i, metric in enumerate(available_metrics):
        label = metrics_labels[i] if i < len(metrics_labels) else metric
        metric_buttons.append(dict(
            label=label,
            method="update",
            args=[
                {"y": [df[metric]]}, # Update Y data
                {"yaxis": {"title": label}} # Update Y Title
            ]
        ))

    fig.update_layout(
        updatemenus=[
            # Parameter Dropdown
            dict(
                active=0,
                buttons=param_buttons,
                x=0.0,
                y=1.25,
                xanchor='left',
                yanchor='top',
                pad={"r": 10, "t": 10},
                showactive=True
            ),
            # Metric Dropdown
            dict(
                active=0,
                buttons=metric_buttons,
                x=0.35, # Placed next to the first one
                y=1.25,
                xanchor='left',
                yanchor='top',
                pad={"r": 10, "t": 10},
                showactive=True
            )
        ],
        title=dict(text=f"Parameter Analysis", y=0.95),
        yaxis_title=metrics_labels[0] if metrics_labels else init_metric,
        xaxis_title=init_param,
        height=700,
        margin=dict(t=160, l=60, r=40, b=60),
        annotations=[
            dict(text="Parameter:", x=0.0, y=1.3, xref='paper', yref='paper', showarrow=False, xanchor='left', font=dict(size=11, color="gray")),
            dict(text="Metric:", x=0.35, y=1.3, xref='paper', yref='paper', showarrow=False, xanchor='left', font=dict(size=11, color="gray"))
        ]
    )
    
    # ---------------------------------------------------------
    # 4. Export
    # ---------------------------------------------------------
    plot_html = fig.to_html(include_plotlyjs=False, full_html=False, div_id='param_interactive_plot')
    
    div_part, script_part = extract_chart_html(plot_html)
    
    if not div_part or not script_part:
         print("DEBUG: extract_chart_html returned empty strings.")
         return "<div id='param_interactive_plot'>Error extracting chart HTML.</div>", ""
         
    return div_part, script_part
