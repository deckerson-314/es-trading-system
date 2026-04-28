
import pandas as pd

results_file = r'c:\Trading\Trend\parameters\genetic_results_2026-04-14-13.csv'
param_file = r'c:\Trading\strategies\trend\parameters\trend_strategy_params.csv'

# Load files
results_df = pd.read_csv(results_file)
# Solution_10 is Column 17 if we count from Solution_0 at Column 7
col_name = 'Solution_10'

# Also check for Solution_10_SELECTED just in case
if col_name + '_SELECTED' in results_df.columns:
    col_name += '_SELECTED'

# Extract parameters
# We only care about rows where Type is not 'statistic' and not headers Like '==='
params_to_update = results_df[
    (results_df['Type'] != 'statistic') & 
    (~results_df['Name'].str.startswith('===').fillna(False))
].copy()

# Create a mapping for current production parameters
current_params_df = pd.read_csv(param_file)

# Update values in current_params_df using results_df values for col_name
for idx, row in current_params_df.iterrows():
    p_name = row['Name']
    if p_name in params_to_update['Name'].values:
        new_val = params_to_update[params_to_update['Name'] == p_name][col_name].values[0]
        # Skip empty/NaN values
        if pd.isna(new_val) or new_val == '':
            continue
        current_params_df.at[idx, 'Value'] = new_val

# Save updated parameters
current_params_df.to_csv(param_file, index=False)
print(f"Successfully updated {param_file} with parameters from {col_name}")
