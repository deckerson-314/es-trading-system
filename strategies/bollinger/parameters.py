"""
Parameter Loading and Validation
=================================
Unified parameter loading from CSV with proper type handling.
Based on the comprehensive implementation from BB Genetic.ipynb.
"""

import pandas as pd
import ast


def load_params(csv_path, return_dataframe=False):
    """
    Load parameters from CSV file with proper type handling.
    
    Args:
        csv_path: Path to CSV file with columns: Name, Value, Min, Max, Type
        return_dataframe: If True, also return the original DataFrame
        
    Returns:
        dict: Dictionary of parameter name -> {'value': val, 'min': mn, 'max': mx, 'type': typ}
        If return_dataframe=True, returns (dict, DataFrame)
    """
    df = pd.read_csv(csv_path)
    d = {}
    
    for _, r in df.iterrows():
        # Skip if name is not a string (e.g. NaN)
        if pd.isna(r['Name']) or not isinstance(r['Name'], str):
            continue
            
        name = r['Name'].strip()
        
        # Skip section headers (lines starting with ===)
        if name.startswith('==='):
            continue
        
        val = r['Value']
        mn = r.get('Min', None)
        mx = r.get('Max', None)
        typ = r.get('Type', None)
        
        # Handle type conversion
        if pd.notna(typ):
            if typ == 'int':
                val = int(val) if pd.notna(val) else None
                mn = int(mn) if pd.notna(mn) else None
                mx = int(mx) if pd.notna(mx) else None
            elif typ == 'float':
                val = float(val) if pd.notna(val) else None
                mn = float(mn) if pd.notna(mn) else None
                mx = float(mx) if pd.notna(mx) else None
            elif typ == 'bool':
                if isinstance(val, str):
                    val = ast.literal_eval(val.capitalize())
                if pd.notna(mn) and isinstance(mn, str):
                    mn = ast.literal_eval(mn.capitalize())
                if pd.notna(mx) and isinstance(mx, str):
                    mx = ast.literal_eval(mx.capitalize())
        
        d[name] = {'value': val, 'min': mn, 'max': mx, 'type': typ}
    
    if return_dataframe:
        return d, df
    return d


def get_param_value(params_dict, name, default=None):
    """
    Safely get a parameter value from the params dictionary.
    
    Args:
        params_dict: Dictionary returned by load_params()
        name: Parameter name
        default: Default value if parameter not found
        
    Returns:
        Parameter value (extracted from 'value' key)
    """
    if name in params_dict:
        return params_dict[name]['value']
    return default

