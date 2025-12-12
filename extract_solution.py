
import pandas as pd
import json

try:
    df = pd.read_csv('Bollinger/parameters/genetic_results_2025-12-11-1.csv')
    
    # The first few rows are header metadata. We need to be careful.
    # Actually, looking at the file content:
    # Row 0: Name, Value, Min, Max... Solution_0, Solution_1...
    # The 'Name' column contains the parameter names.
    # The 'Solution_3' column contains the values.
    
    # We filter for rows where 'Name' is a valid parameter (not empty, not starting with ===)
    
    params = {}
    for index, row in df.iterrows():
        name = str(row['Name']).strip()
        if not name or name.startswith('===') or name == 'nan':
            continue
            
        # Get value from Solution_3
        val_str = str(row['Solution_3']).strip()
        
        # Fallback to 'Value' if Solution_3 is empty/nan
        if val_str.lower() == 'nan' or val_str == '':
             val_str = str(row['Value']).strip()
        
        # Determine type from 'Type' column
        dtype = str(row['Type']).strip().lower()
        
        if dtype == 'int':
            try:
                # Handle cases like "1.0" for int
                val = int(float(val_str))
            except:
                # If fail, try to default? No, keep it as is or skip
                continue
        elif dtype == 'float':
            try:
                val = float(val_str)
            except:
                # Default to value from 'Value' column if extraction fails?
                # This happens for fixed params sometimes
                try:
                     val = float(row['Value'])
                except:
                     continue
        elif dtype == 'bool':
            # Handle True/False, true/false, 1/0
            v_low = val_str.lower()
            if v_low in ['true', '1', 'yes']:
                val = True
            else:
                val = False
        else:
            val = val_str
            
        params[name] = val
        
    print("Extracted Parameters for Solution #3:")
    print(json.dumps(params, indent=4))
    
    with open('solution_3_params.json', 'w') as f:
        json.dump(params, f, indent=4)
        
    print("Saved to solution_3_params.json")

except Exception as e:
    print(f"Error: {e}")
