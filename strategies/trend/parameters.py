"""
Parameter Loading and Validation for Trend Strategy
===================================================
Unified parameter loading from CSV with proper type handling.
Mirroring logic from strategies/bollinger/parameters.py
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
    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        print(f"Warning: Parameter file {csv_path} not found.")
        return ({}, None) if return_dataframe else {}
        
    d = {}
    
    for _, r in df.iterrows():
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
                    val = val.lower() == 'true'
                if isinstance(mn, str):
                    mn = mn.lower() == 'true'
                if isinstance(mx, str):
                    mx = mx.lower() == 'true'
        
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


TRAILING_DELAY_BARS = "Trailing Delay (bars)"
TRAILING_DELAY_MINUTES = "Trailing Delay (minutes)"
CHANNEL_EXIT_SELL_LOOKBACK = "Channel Exit Sell Lookback (bars)"
CHANNEL_EXIT_BUY_LOOKBACK = "Channel Exit Buy Lookback (bars)"
CHANNEL_EXIT_ATR_OFFSET = "Channel Exit ATR Offset"


def is_optimizable_param(meta) -> bool:
    if not isinstance(meta, dict):
        return False
    if meta.get("type") not in ("int", "float"):
        return False
    mn, mx = meta.get("min"), meta.get("max")
    if mn is None or mx is None:
        return False
    try:
        return float(mn) != float(mx)
    except (TypeError, ValueError):
        return False


def active_trailing_delay_gene_key(param_dict) -> str | None:
    if not param_dict:
        return None
    if is_optimizable_param(param_dict.get(TRAILING_DELAY_MINUTES)):
        return TRAILING_DELAY_MINUTES
    if is_optimizable_param(param_dict.get(TRAILING_DELAY_BARS)):
        return TRAILING_DELAY_BARS
    return None


def exclude_trailing_delay_from_param_ranges(name: str, param_dict) -> bool:
    gene = active_trailing_delay_gene_key(param_dict)
    if gene is None:
        return False
    if name == TRAILING_DELAY_BARS and gene == TRAILING_DELAY_MINUTES:
        return True
    if name == TRAILING_DELAY_MINUTES and gene == TRAILING_DELAY_BARS:
        return True
    return False


def _timeframe_minutes(params_local, param_dict_local, fallback_tf) -> int:
    tf = params_local.get("Timeframe (minutes)")
    if tf is None and param_dict_local:
        meta = param_dict_local.get("Timeframe (minutes)", {})
        if isinstance(meta, dict):
            tf = meta.get("value")
    try:
        return max(1, int(round(float(tf if tf is not None else fallback_tf))))
    except (TypeError, ValueError):
        return max(1, int(fallback_tf))


def _get_scalar(params_local, param_dict_local, key):
    if key in params_local:
        return params_local[key]
    if param_dict_local:
        meta = param_dict_local.get(key, {})
        if isinstance(meta, dict):
            return meta.get("value")
    return None


def resolve_trailing_delay_bars(params_local, param_dict_local=None, fallback_tf=15) -> int:
    if params_local is None:
        params_local = {}
    gene = active_trailing_delay_gene_key(param_dict_local or {})
    tf = _timeframe_minutes(params_local, param_dict_local, fallback_tf)
    if gene == TRAILING_DELAY_MINUTES:
        mins = _get_scalar(params_local, param_dict_local, TRAILING_DELAY_MINUTES)
        try:
            return max(0, int(round(max(0.0, float(mins)) / tf)))
        except (TypeError, ValueError):
            return 0
    if gene == TRAILING_DELAY_BARS:
        bars = _get_scalar(params_local, param_dict_local, TRAILING_DELAY_BARS)
        try:
            return max(0, int(round(float(bars))))
        except (TypeError, ValueError):
            return 0
    mins = _get_scalar(params_local, param_dict_local, TRAILING_DELAY_MINUTES)
    if mins is not None:
        try:
            return max(0, int(round(max(0.0, float(mins)) / tf)))
        except (TypeError, ValueError):
            pass
    bars = _get_scalar(params_local, param_dict_local, TRAILING_DELAY_BARS)
    try:
        return max(0, int(round(float(bars if bars is not None else 0))))
    except (TypeError, ValueError):
        return 0


def resolve_channel_exit_sell_lookback(params_local, param_dict_local=None, fallback_sell_bars=20) -> int:
    """Donchian low lookback for long channel exits; falls back to entry sell lookback."""
    if param_dict_local and CHANNEL_EXIT_SELL_LOOKBACK not in param_dict_local:
        return max(1, int(round(float(fallback_sell_bars))))
    val = _get_scalar(params_local, param_dict_local, CHANNEL_EXIT_SELL_LOOKBACK)
    if val is None:
        return max(1, int(round(float(fallback_sell_bars))))
    try:
        return max(1, int(round(float(val))))
    except (TypeError, ValueError):
        return max(1, int(round(float(fallback_sell_bars))))


def resolve_channel_exit_buy_lookback(params_local, param_dict_local=None, fallback_buy_bars=20) -> int:
    """Donchian high lookback for short channel exits; falls back to entry buy lookback."""
    if param_dict_local and CHANNEL_EXIT_BUY_LOOKBACK not in param_dict_local:
        return max(1, int(round(float(fallback_buy_bars))))
    val = _get_scalar(params_local, param_dict_local, CHANNEL_EXIT_BUY_LOOKBACK)
    if val is None:
        return max(1, int(round(float(fallback_buy_bars))))
    try:
        return max(1, int(round(float(val))))
    except (TypeError, ValueError):
        return max(1, int(round(float(fallback_buy_bars))))


def resolve_channel_exit_atr_offset(params_local, param_dict_local=None) -> float:
    """ATR multiplier applied to exit bands (looser channel exit when > 0)."""
    if param_dict_local and CHANNEL_EXIT_ATR_OFFSET not in param_dict_local:
        return 0.0
    val = _get_scalar(params_local, param_dict_local, CHANNEL_EXIT_ATR_OFFSET)
    if val is None:
        return 0.0
    try:
        return max(0.0, float(val))
    except (TypeError, ValueError):
        return 0.0


def sync_trailing_delay_params(params_local, param_dict_local=None, fallback_tf=15) -> dict:
    if params_local is None:
        return params_local
    gene = active_trailing_delay_gene_key(param_dict_local or {})
    tf = _timeframe_minutes(params_local, param_dict_local, fallback_tf)
    bars = resolve_trailing_delay_bars(params_local, param_dict_local, fallback_tf)
    params_local[TRAILING_DELAY_BARS] = bars
    if gene == TRAILING_DELAY_BARS:
        params_local[TRAILING_DELAY_MINUTES] = int(bars * tf)
    return params_local
