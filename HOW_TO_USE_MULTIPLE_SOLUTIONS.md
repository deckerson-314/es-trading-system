# How to Use Multiple Pareto-Optimal Solutions

## Overview

The optimized parameter CSV file (`BB_Strategy_Parameters_optimized_v3.csv`) now contains **ALL Pareto-optimal solutions** as separate columns, allowing you to easily compare and use different solutions side-by-side.

---

## CSV Structure

The CSV file has the following structure:

### Standard Columns (from original CSV):
- `Name` - Parameter name
- `Value` - Original/default value
- `Min` - Minimum allowed value
- `Max` - Maximum allowed value
- `Type` - Parameter type (int, float, bool, str)
- `Description` - Parameter description

### Solution Columns (added by GA):
- `Solution_0_SELECTED` - **Best solution** (highest Sortino Ratio) - **This is the default selected solution**
- `Solution_1` - Second best solution (2nd highest Sortino)
- `Solution_2` - Third best solution (3rd highest Sortino)
- ... and so on for all Pareto-optimal solutions

### Statistics Rows (at bottom of CSV):
At the end of the CSV, you'll find statistics rows showing metrics for each solution:
- `Sortino Ratio` - Risk-adjusted returns
- `Max Drawdown ($)` - Maximum drawdown in dollars
- `Profit Factor` - Gross profit / Gross loss
- `Avg Trades/Day` - Average number of trades per day
- `Solution Rank` - Ranking by Sortino (0 = highest)

---

## How to View Solutions Side-by-Side

### Method 1: Open in Excel/Spreadsheet

1. Open `BB_Strategy_Parameters_optimized_v3.csv` in Excel, Google Sheets, or any spreadsheet application
2. Scroll to the bottom to see the statistics rows
3. Compare metrics across solutions:
   - **Solution_0_SELECTED** = Best Sortino (default)
   - **Solution_1** = Might have lower drawdown
   - **Solution_2** = Might have higher profit factor
   - etc.

### Method 2: Use Python/Pandas

```python
import pandas as pd

# Load the CSV
df = pd.read_csv('Bollinger/parameters/BB_Strategy_Parameters_optimized_v3.csv')

# View statistics (last few rows)
print(df.tail(10))

# Compare specific solutions
print("\nSolution Comparison:")
print(df[['Name', 'Solution_0_SELECTED', 'Solution_1', 'Solution_2']].tail(10))
```

### Method 3: Filter by Statistics

Look at the statistics rows to find solutions that match your criteria:
- **Lowest Drawdown**: Find solution with minimum "Max Drawdown ($)"
- **Highest Profit Factor**: Find solution with maximum "Profit Factor"
- **Most Trades**: Find solution with maximum "Avg Trades/Day"
- **Balanced**: Find solution with good balance of all metrics

---

## How to Use a Different Solution

### Option 1: Manual CSV Edit

1. Open `BB_Strategy_Parameters_optimized_v3.csv`
2. Copy values from your desired solution column (e.g., `Solution_2`)
3. Paste into the `Value` column
4. Save the file
5. Use with `BB_Strategy_v3.py`

### Option 2: Python Script

Create a script to extract a specific solution:

```python
import pandas as pd

# Load CSV
df = pd.read_csv('Bollinger/parameters/BB_Strategy_Parameters_optimized_v3.csv')

# Select solution (0 = best, 1 = second best, etc.)
solution_idx = 2  # Use Solution_2
col_name = f"Solution_{solution_idx}"

# Update Value column with selected solution
df['Value'] = df[col_name].fillna(df['Value'])

# Save to new file or overwrite
df.to_csv('Bollinger/parameters/BB_Strategy_Parameters_selected.csv', index=False)
```

### Option 3: Modify BB_Strategy_v3.py

You can modify `BB_Strategy_v3.py` to read from a specific solution column:

```python
# In BB_Strategy_v3.py, change:
PARAMS_CSV = os.path.join(DRIVE_PATH, 'parameters', 'BB_Strategy_Parameters_optimized.csv')

# To read from a specific solution:
df = pd.read_csv(PARAMS_CSV)
solution_col = 'Solution_2'  # Change this to select different solution
df['Value'] = df[solution_col].fillna(df['Value'])
params_dict = load_params_from_dataframe(df)  # You'd need to modify load_params to accept dataframe
```

---

## Example: Comparing Solutions

### Scenario: You want lower drawdown

1. Open the CSV and scroll to statistics rows
2. Find the "Max Drawdown ($)" row
3. Compare values across solutions:
   - Solution_0_SELECTED: $59,262
   - Solution_1: $52,100
   - Solution_2: $48,500 ← **Lowest drawdown**
4. Check other metrics for Solution_2:
   - Sortino: 27.80 (vs 30.00 for Solution_0)
   - Profit Factor: 3.85 (vs 3.96 for Solution_0)
5. Decide if the lower drawdown is worth the slightly lower Sortino
6. If yes, copy Solution_2 values to Value column

---

## Understanding Solution Rankings

Solutions are ranked by **Sortino Ratio** (descending):
- **Solution_0_SELECTED**: Highest Sortino (best risk-adjusted returns)
- **Solution_1**: 2nd highest Sortino
- **Solution_2**: 3rd highest Sortino
- etc.

**Important**: Higher Sortino doesn't always mean "better" - consider:
- **Drawdown**: Lower is better (less risk)
- **Profit Factor**: Higher is better (more profitable)
- **Trade Frequency**: Depends on your goals

---

## Tips for Solution Selection

1. **Risk-Averse**: Choose solution with lowest drawdown
2. **Profit-Focused**: Choose solution with highest profit factor
3. **Balanced**: Choose solution with good balance of all metrics
4. **High Frequency**: Choose solution with highest avg trades/day
5. **Conservative**: Stick with Solution_0_SELECTED (highest Sortino)

---

## Statistics Row Format

The statistics rows at the bottom show:

```
Name                    | Solution_0_SELECTED | Solution_1 | Solution_2 | ...
------------------------|---------------------|------------|------------|----
Sortino Ratio           | 30.0000            | 28.4500    | 27.8000    | ...
Max Drawdown ($)        | $59,262.48         | $52,100.00 | $48,500.00 | ...
Profit Factor           | 3.9600             | 4.1200     | 3.8500     | ...
Avg Trades/Day          | 1.464              | 1.520      | 1.380      | ...
Solution Rank           | #0 (SELECTED)      | #1         | #2         | ...
```

---

## Notes

- All solutions are **Pareto-optimal** - no solution is better in ALL objectives
- The selected solution (Solution_0) has the highest Sortino, but may not be best for your specific needs
- You can test multiple solutions by creating separate CSV files for each
- The checkpoint file is now kept (not deleted) so you can also use `extract_pareto_solution.py` if needed

---

## Quick Reference

**Default Solution**: `Solution_0_SELECTED` (highest Sortino)  
**Find Lowest Drawdown**: Check "Max Drawdown ($)" row, find minimum value  
**Find Highest PF**: Check "Profit Factor" row, find maximum value  
**Compare Solutions**: Open CSV in spreadsheet, scroll to statistics rows

