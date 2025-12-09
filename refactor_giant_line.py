
def refactor_line():
    lines = open('BB_Genetic_v4.py', 'r', encoding='utf-8').readlines()
    new_lines = []
    
    target_start = "html_content += f' <h2>In-Sample vs OOS Comparison"
    
    found = False
    for line in lines:
        if target_start in line:
            found = True
            # Insert the refactored block
            indent = "    "
            
            new_lines.append(indent + "html_content += ' <h2>In-Sample vs OOS Comparison<span class=\"tooltip-icon\">?</span> <span class=\"tooltip\">Comparison of strategy performance between in-sample (training) and out-of-sample (validation) data. This is critical for detecting overfitting. Good generalization: IS and OOS metrics are similar. Overfitting: IS is much better than OOS. Green differences indicate OOS is better (good sign), red indicates OOS is worse (potential overfitting).</span> </h2> <div class=\"info-section\"> <strong>Overfitting Detection:</strong> If OOS performance is significantly worse than IS, the strategy may be overfitted to the training data. Look for: (1) Sortino dropping >50% in OOS, (2) Drawdown increasing >100% in OOS, (3) Trade frequency dropping dramatically. Small differences (<20%) are normal and acceptable. </div> '\n")
            new_lines.append(indent + "html_content += comparison_html\n")
            new_lines.append(indent + "html_content += summary_html\n")
            new_lines.append(indent + "html_content += ' <h2>All Solutions<span class=\"tooltip-icon\">?</span> <span class=\"tooltip\">Complete list of all Pareto-optimal solutions ranked by Sortino Ratio. The selected solution is marked with *. You can compare different solutions to see parameter variations. Higher-ranked solutions have better risk-adjusted returns, but may have different drawdown or profit factor characteristics.</span> </h2> <div class=\"info-section\"> '\n")
            
            new_lines.append(indent + "if showing_actual:\n")
            new_lines.append(indent + "    html_content += '<strong> This table shows ACTUAL BACKTEST RESULTS from fresh backtests of each solution.</strong>'\n")
            new_lines.append(indent + "    html_content += ' <ul> <li><strong>All Metrics:</strong> ACTUAL VALUES from running fresh backtests on each solution using the full in-sample dataset. These values match what you would see if you ran a standalone backtest with these parameters.</li> <li><strong>Generation:</strong> Shows which generation each solution was found in. <strong>Why the same generation appears multiple times:</strong> The Hall of Fame (Pareto Front) contains non-dominated solutions from ALL generations. When one generation finds many good solutions (like Gen 7 with 15 solutions), they all enter the Hall of Fame if they\\'re Pareto-optimal. Old solutions from earlier generations remain if they haven\\'t been dominated. This is normal and healthy GA behavior - it shows good diversity and exploration!</li> <li><strong>Why these match \"Actual Backtest Results\":</strong> Both run fresh backtests using the same data and parameter conversion logic. Rank 1 (marked with *) should match the \"Actual Backtest Results\" section exactly.</li> </ul>'\n")
            new_lines.append(indent + "else:\n")
            new_lines.append(indent + "    html_content += '<strong>(!) IMPORTANT: This table shows NORMALIZED FITNESS VALUES, not actual backtest results!</strong>'\n")
            new_lines.append(indent + "    html_content += ' <ul> <li><strong>Sortino/Drawdown/PF/Total Profit:</strong> Normalized fitness values (0-1 range) used for optimization. Values of -1000 indicate hard constraint penalties (solution eliminated due to negative Sortino, negative PNL, or win rate < 40%).</li> <li><strong>Avg Trades/Day:</strong> RAW value (actual trades/day) - this is NOT normalized and shows real trade frequency.</li> <li><strong>Generation:</strong> Shows which generation each solution was found in. <strong>Why the same generation appears multiple times:</strong> The Hall of Fame (Pareto Front) contains non-dominated solutions from ALL generations. When one generation finds many good solutions (like Gen 7 with 15 solutions), they all enter the Hall of Fame if they\\'re Pareto-optimal. Old solutions from earlier generations remain if they haven\\'t been dominated. This is normal and healthy GA behavior - it shows good diversity and exploration!</li> <li><strong>Why values differ from \"Actual Backtest Results\":</strong> Fitness values are normalized for optimization efficiency. The \"Actual Backtest Results\" section runs real backtests and shows actual metrics.</li> <li><strong>If all solutions show Sortino = -1000:</strong> All solutions hit hard constraints (likely negative Sortino, negative PNL, or win rate < 40%). The GA eliminated them from optimization, but they may still appear here with invalid fitness values.</li> </ul>'\n")
            
            new_lines.append(indent + "html_content += ' <strong>Solution Selection:</strong> While the highest Sortino solution is automatically selected, you may want to manually review other solutions. For example, if Solution #2 has similar Sortino but much lower drawdown, it might be a better choice for risk-averse trading. All solutions in this table are Pareto-optimal. </div> '\n")
            new_lines.append(indent + "html_content += pareto_table_html\n")
            new_lines.append(indent + "html_content += ' </div> <h2>Parameter Analysis<span class=\"tooltip-icon\">?</span> <span class=\"tooltip\">Analysis of how strategy parameters affect performance metrics. Use this to identify which parameters are most important and how they correlate with fitness objectives.</span> </h2> <div class=\"info-section\"> <strong>Understanding Parameter Analysis:</strong> <ul> <li><strong>Correlation Heatmap:</strong> Shows how each parameter correlates with each metric. Positive (blue) = parameter increases with metric, Negative (red) = parameter decreases with metric.</li> <li><strong>Parameter Importance:</strong> Combines correlation, top-bottom difference, range utilization, and variability to identify the most important parameters.</li> <li><strong>Parameter Distributions (Top vs Bottom):</strong> Compares parameter values in top 25% vs bottom 25% solutions. Shows which parameters distinguish good from bad solutions.</li> <li><strong>Parameter Interactions:</strong> 2D scatter plots showing how top parameters interact. Color = Sortino (darker = better). Helps identify parameter combinations that work together.</li> <li><strong>Parameter Distribution Histograms:</strong> Shows distribution of all parameter values with valid ranges marked. <strong style=\"color: red;\">Red bars = values OUTSIDE valid range</strong>, Blue bars = values within range. Green/Red dashed lines = min/max boundaries. Use this to detect parameter clamping issues!</li> <li><strong>Focus on High-Importance Parameters:</strong> These are the parameters that most distinguish good solutions from bad ones.</li> </ul> <strong>Note:</strong> GA meta-parameters (POP_SIZE, NUM_GEN, etc.) are excluded from this analysis as they control the optimization algorithm, not the trading strategy. </div> <div class=\"chart-container\"> '\n")
            new_lines.append(indent + "html_content += param_analysis_html\n")
            new_lines.append(indent + "html_content += ' </div> '\n")
            new_lines.append(indent + "html_content += conv_script + ' ' + pareto3d_script + ' ' + pareto2d_script + ' ' + paretosize_script + ' ' + param_analysis_scripts\n")
            new_lines.append(indent + "html_content += ' </body></html>'\n")
            
        else:
            new_lines.append(line)
            
    if found:
        with open('BB_Genetic_v4.py', 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        print("Line refactored.")
    else:
        print("Target line not found.")

refactor_line()
