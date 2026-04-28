import pandas as pd
import json

csv_path = r'C:\Trading\Trend\parameters\genetic_results_2026-04-14-13.csv'
df = pd.read_csv(csv_path)

# Solution_10 is the 11th solution column (starts at col 6)
# Col 0: Name
# Col 6: Solution_0
# Col 16: Solution_10
sol_col = 'Solution_10'

params = {}
for idx, row in df.iterrows():
    name = str(row['Name']).strip()
    if name.startswith('==='): continue
    val = row[sol_col]
    if pd.isna(val): continue
    
    # Try to convert to float/int
    try:
        if float(val) == int(float(val)):
            params[name] = int(float(val))
        else:
            params[name] = float(val)
    except:
        # Check for bool
        if str(val).lower() == 'true':
            params[name] = 1
        elif str(val).lower() == 'false':
            params[name] = 0
        else:
            params[name] = val

with open(r'c:\Trading\solution_10_414_v3.json', 'w') as f:
    json.dump(params, f, indent=4)

print("Extracted params:")
print(json.dumps(params, indent=4))
