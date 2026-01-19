
import sys

def refactor_html():
    lines = open('BB_Genetic_v4.py', 'r', encoding='utf-8').readlines()
    
    # 0-based indices for lines 1944-2214
    start_idx = 1944 - 1
    end_idx = 2214 - 1
    
    # Check if we are targeting the right block
    if 'html_content = f"""<!DOCTYPE html>' not in lines[start_idx]:
        print(f"Error: Start line {start_idx+1} does not match expected content.")
        print(f"Content: {lines[start_idx]}")
        sys.exit(1)
        
    if '</body></html>"""' not in lines[end_idx]:
        print(f"Error: End line {end_idx+1} does not match expected content.")
        print(f"Content: {lines[end_idx]}")
        sys.exit(1)

    # New content construction
    new_code = []
    
    # Define variables if not already defined (safety)
    # The user already added pre-calcs in previous steps, but we can rely on them being there.
    # We will just write the HTML generation line by line.
    
    new_code.append('    # Refactored HTML generation to avoid f-string limits\n')
    new_code.append('    html_content = "<!DOCTYPE html>\\n"\n')
    new_code.append('    html_content += "<html><head><title>GA Dashboard v3.0</title>\\n"\n')
    new_code.append(f'    html_content += f"{{refresh_script}}\\n"\n')
    new_code.append('    html_content += "<script src=\'https://cdn.plot.ly/plotly-latest.min.js\'></script>\\n"\n')
    new_code.append('    html_content += "<style> body { font-family: Arial; margin: 0; padding: 0; background: #f5f5f5; padding-top: 60px; } .container { max-width: 1400px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; } h1 { color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; } h2 { color: #555; margin-top: 30px; border-bottom: 2px solid #ddd; position: relative; } h2 .tooltip-icon { display: inline-block; width: 18px; height: 18px; background: #4CAF50; color: white; border-radius: 50%; text-align: center; line-height: 18px; font-size: 12px; margin-left: 8px; cursor: help; vertical-align: middle; } h2 .tooltip { visibility: hidden; width: 300px; background-color: #333; color: #fff; text-align: left; border-radius: 6px; padding: 10px; position: absolute; z-index: 1; bottom: 125%; left: 0; font-size: 12px; line-height: 1.4; box-shadow: 0 2px 8px rgba(0,0,0,0.3); } h2 .tooltip-icon:hover + .tooltip { visibility: visible; } table { width: 100%; border-collapse: collapse; margin: 15px 0; } th { background: #4CAF50; color: white; padding: 10px; text-align: left; position: relative; } th .tooltip-icon { display: inline-block; width: 16px; height: 16px; background: rgba(255,255,255,0.3); color: white; border-radius: 50%; text-align: center; line-height: 16px; font-size: 11px; margin-left: 5px; cursor: help; vertical-align: middle; } th .tooltip { visibility: hidden; width: 280px; background-color: #333; color: #fff; text-align: left; border-radius: 6px; padding: 8px; position: absolute; z-index: 1; bottom: 125%; left: 0; font-size: 11px; line-height: 1.3; box-shadow: 0 2px 8px rgba(0,0,0,0.3); } th .tooltip-icon:hover + .tooltip { visibility: visible; } td { padding: 8px; border: 1px solid #ddd; } tr:nth-child(even) { background: #f9f9f9; } .selected-row { background: #fff3cd !important; font-weight: bold; } .positive { color: green; } .negative { color: red; } .metric-box { display: inline-block; background: #4CAF50; color: white; padding: 10px 20px; margin: 5px; border-radius: 5px; font-weight: bold; position: relative; cursor: help; } .metric-box .tooltip { visibility: hidden; width: 250px; background-color: #333; color: #fff; text-align: left; border-radius: 6px; padding: 8px; position: absolute; z-index: 1; bottom: 125%; left: 50%; transform: translateX(-50%); font-size: 11px; line-height: 1.3; box-shadow: 0 2px 8px rgba(0,0,0,0.3); } .metric-box:hover .tooltip { visibility: visible; } .info-section { background: #e3f2fd; border-left: 4px solid #2196F3; padding: 12px; margin: 15px 0; border-radius: 4px; font-size: 0.9em; line-height: 1.5; } .chart-container { margin: 20px 0; padding: 20px 0; border-top: 1px solid #ddd; border-bottom: 1px solid #ddd; } .chart-container .plotly-graph-div { margin: 20px 0; display: block; min-height: 400px; } .return-button { display: inline-block; margin-bottom: 20px; padding: 10px 20px; background: #667eea; color: white; text-decoration: none; border-radius: 5px; font-weight: bold; } .return-button:hover { background: #5568d3; } </style></head><body>\\n"\n')
    
    new_code.append(f'    html_content += f"{{progress_html}}\\n"\n')
    new_code.append('    html_content += "<div class=\'container\'>\\n"\n')
    new_code.append('    html_content += "<a href=\'index.html\' class=\'return-button\'>&larr; Back to Main Dashboard</a>\\n"\n')
    new_code.append('    html_content += "<h1>GA Optimization Dashboard - v3.0</h1>\\n"\n')
    new_code.append(f"    html_content += f\"<p><strong>Generated:</strong> {{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}}</p>\\n\"\n")
    
    new_code.append(f'    html_content += f"<div class=\'metric-box\'>Pareto Solutions: {{len(hof)}}<span class=\'tooltip\'>Number of non-dominated solutions found.</span></div>\\n"\n')
    new_code.append(f'    html_content += f"<div class=\'metric-box\'>Generations: {{len(gens)}}<span class=\'tooltip\'>Total number of generations completed.</span></div>\\n"\n')
    
    new_code.append(f'    html_content += f"{{fitness_weights_html}}\\n"\n')
    
    new_code.append('    html_content += "<h2>Selected Solution Performance</h2>\\n"\n')
    
    # Handle the relationship conditions
    new_code.append('    sel_crit_text = "The solution with the highest Sortino Ratio is selected."\n')
    new_code.append('    gen_found_text = f"Generation {best_gen_found}" if best_gen_found is not None else ""\n')
    new_code.append('    html_content += f"<div class=\'info-section\'><strong>Selection Criteria:</strong> {sel_crit_text}<br><strong>Generation:</strong> {gen_found_text}</div>\\n"\n')

    new_code.append('    html_content += "<h3>Actual Backtest Results (In-Sample)</h3>\\n"\n')
    
    # Use variable names s_val, d_val, etc. defined previously
    new_code.append(f'    html_content += f"<div class=\'metric-box\'>Sortino: {{s_val:.6f}}</div>\\n"\n')
    new_code.append(f'    html_content += f"<div class=\'metric-box\'>Max DD: ${{d_val:,.2f}}</div>\\n"\n')
    new_code.append(f'    html_content += f"<div class=\'metric-box\'>PF: {{pf_val:.6f}}</div>\\n"\n')
    new_code.append(f'    html_content += f"<div class=\'metric-box\'>Avg Trades/Day: {{trades_val:.3f}}</div>\\n"\n')
    new_code.append(f'    html_content += f"<div class=\'metric-box\'>Total Profit: ${{tp_val:,.2f}}</div>\\n"\n')
    
    new_code.append('    html_content += "<h4>Monthly Profit Statistics</h4>\\n"\n')
    new_code.append(f'    html_content += f"<div class=\'metric-box\'>Max Monthly: ${{m_max:,.2f}}</div>\\n"\n')
    new_code.append(f'    html_content += f"<div class=\'metric-box\'>Min Monthly: ${{m_min:,.2f}}</div>\\n"\n')
    new_code.append(f'    html_content += f"<div class=\'metric-box\'>Avg Monthly: ${{m_avg:,.2f}}</div>\\n"\n')
    
    new_code.append('    html_content += "<p><em>Note: Total Profit shown here is from actual backtest.</em></p>\\n"\n')
    
    new_code.append('    html_content += "<h2>Parameters</h2>\\n"\n')
    new_code.append(f'    html_content += f"{{best_params_html}}\\n"\n')
    
    new_code.append('    html_content += "<h2>Convergence</h2>\\n"\n')
    new_code.append(f'    html_content += f"{{conv_div}}\\n"\n')
    
    new_code.append('    html_content += "<h2>Pareto Front 3D</h2>\\n"\n')
    new_code.append(f'    html_content += f"{{pareto3d_div}}\\n"\n')
     
    new_code.append('    html_content += "<h2>Pareto Front 2D</h2>\\n"\n')
    new_code.append(f'    html_content += f"{{pareto2d_div}}\\n"\n')
     
    new_code.append('    html_content += "<h2>Pareto Size</h2>\\n"\n')
    new_code.append(f'    html_content += f"{{paretosize_div}}\\n"\n')
    
    # Deep Dive Analysis Links (New for V4 Upgrade)
    new_code.append('    html_content += "<h2>Deep Dive Analysis (New V4)</h2>\\n"\n')
    new_code.append('    html_content += "<div class=\'info-section\'>\\n"\n')
    new_code.append('    html_content += "  <p>View detailed parameter analysis reports (generated separately):</p>\\n"\n')
    new_code.append('    html_content += "  <ul>\\n"\n')
    new_code.append('    html_content += "    <li><a href=\'parameter_analysis/parameter_correlation.html\' target=\'_blank\'>Correlation Heatmap (Parameters vs Metrics)</a></li>\\n"\n')
    new_code.append('    html_content += "    <li><a href=\'parameter_analysis/parameter_importance_TotalPnL.html\' target=\'_blank\'>Parameter Importance (Total PnL)</a></li>\\n"\n')
    new_code.append('    html_content += "    <li><a href=\'parameter_analysis/parameter_interactions.html\' target=\'_blank\'>Parameter Interactions (Scatter Matrix)</a></li>\\n"\n')
    new_code.append('    html_content += "  </ul>\\n"\n')
    new_code.append('    html_content += "</div>\\n"\n')
    
    # OOS, Comparison, All Solutions
    new_code.append('    html_content += "<h2>Data Split Information</h2>\\n"\n')
    new_code.append('    html_content += "<div class=\'info-section\'>Data split into IS and OOS periods.</div>\\n"\n')
    
    # We can rely on appending the periods_html later as the original code does.
    # The original code closes the big f-string around 2065, then does:
    # 2068: if is_periods is not None...
    # So we just need to ensure `html_content` ends cleanly.
    
    # But wait, the original code CONTINUED the f-string until 2205!
    # lines 2067 to 2095 were NOT inside the f-string?
    # Ah, let's look at line 2065: """
    # line 2067: # Add IS and OOS period dates
    
    # Wait, my line reading showed:
    # 2065: """
    # 2067: # Add IS and OOS period dates
    # ...
    # 2084: html_content += periods_html
    # ...
    # 2088: html_content += """
    # ...
    # 2160: html_content += f"""
    # ...
    # 2167: {comparison_html}
    # ...
    
    # So the f-string I am replacing ENDS at 2065??
    # Let me re-read line 2065 from Step 1714.
    # 2065: """
    
    # YES! The giant f-string ends at 2065.
    # Then there is python code (lines 2067-2159) appending to it.
    # Then another f-string starts at 2160 and ends at 2214.
    
    # Okay, so I should ONLY replace 1944 to 2065 in this pass.
    # And then handle the second block (2160-2214) separately or in the same script.
    
    # Let's adjust end_idx.
    end_idx = 2065 - 1
    
    new_lines = lines[:start_idx] + new_code + lines[end_idx+1:]
    
    with open('BB_Genetic_v4.py', 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    print("HTML Refactored.")

refactor_html()
