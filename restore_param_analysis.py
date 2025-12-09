def generate_parameter_analysis(hof, param_keys, param_dict, current_gen):
    if not hof or len(hof) < 1:
        return "<p>No solutions to analyze.</p>", ""

    # Extract data for analysis
    data = []
    for ind in hof:
        params = dict(zip(param_keys, ind))
        # Clamp params
        clamped_params = clamp_params(params, param_dict)
        
        # Get fitness values
        if hasattr(ind, 'fitness') and ind.fitness.valid:
            sortino = ind.fitness.values[0]
            row = clamped_params.copy()
            row['Sortino'] = sortino
            data.append(row)
    
    if not data:
        return "<p>No valid data for analysis.</p>", ""

    df_analysis = pd.DataFrame(data)
    
    # Identify top important parameters (high variance in top solutions)
    # Simple heuristic: sort by variance relative to range
    importance = {}
    for col in param_keys:
        if col in df_analysis.columns and col in param_dict:
            # Check if numeric
            if pd.api.types.is_numeric_dtype(df_analysis[col]):
                p_min = param_dict[col]['min']
                p_max = param_dict[col]['max']
                p_range = p_max - p_min
                if p_range > 0:
                    std = df_analysis[col].std()
                    importance[col] = std / p_range
    
    # Get top 6 parameters
    top_params = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:6]
    top_param_names = [p[0] for p in top_params]
    
    if not top_param_names:
        return "<p>Not enough variation to analyze parameters.</p>", ""

    # Create subplots (2x3 grid)
    rows = (len(top_param_names) + 2) // 3
    fig = make_subplots(rows=rows, cols=3, subplot_titles=top_param_names)
    
    for i, param in enumerate(top_param_names):
        row = (i // 3) + 1
        col = (i % 3) + 1
        
        fig.add_trace(
            go.Scatter(
                x=df_analysis[param],
                y=df_analysis['Sortino'],
                mode='markers',
                marker=dict(
                    size=8,
                    color=df_analysis['Sortino'],
                    colorscale='Viridis',
                    showscale=False
                ),
                name=param
            ),
            row=row, col=col
        )
        # Add simpler trendline if enough points
        if len(df_analysis) > 5:
             try:
                 z = np.polyfit(df_analysis[param], df_analysis['Sortino'], 1)
                 p = np.poly1d(z)
                 x_range = np.linspace(df_analysis[param].min(), df_analysis[param].max(), 10)
                 fig.add_trace(
                     go.Scatter(x=x_range, y=p(x_range), mode='lines', line=dict(color='red', width=2, dash='dash'), showlegend=False),
                     row=row, col=col
                 )
             except:
                 pass

    fig.update_layout(height=300 * rows, title_text="Top Parameters vs Sortino Ratio (Pareto Front)", showlegend=False)
    
    # Convert to HTML
    plot_html = fig.to_html(include_plotlyjs=False, full_html=False, div_id='param_analysis_plot')
    
    # Extract
    div_part, script_part = extract_chart_html(plot_html)
    
    return div_part, script_part
