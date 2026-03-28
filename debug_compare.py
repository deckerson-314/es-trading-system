"""
debug_compare.py — Forensic comparison of paper vs backtest signals
=====================================================================
Isolates each step in the signal chain to find exactly where the mismatch occurs.
"""
import pandas as pd
import numpy as np
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategies.trend.strategy import TrendStrategy
from strategies.trend.parameters import get_param_value
from compare_paper_backtest_trend import load_trend_params

# ── CONFIG ──
PARAMS_PATH = r'c:\Trading\strategies\trend\parameters\trend_strategy_params_testing_ultra_high.csv'
LIVE_DATA_PATH = r'c:\Trading\paper_logs\live_data.csv'
LIVE_TRADES_PATH = r'c:\Trading\paper_logs\live_trades.csv'

print("=" * 80)
print("STEP 1: Load and inspect the LIVE DATA (what the paper bot sees)")
print("=" * 80)

# Load raw live_data.csv exactly as the paper bot wrote it
raw = pd.read_csv(LIVE_DATA_PATH)
print(f"  Total rows: {len(raw)}")
print(f"  Columns: {list(raw.columns)}")
print(f"  First timestamp: {raw.iloc[0]['datetime']}")
print(f"  Last timestamp:  {raw.iloc[-1]['datetime']}")

# Check the index column name — is 'datetime' the index or a column?
print(f"\n  Index column type: {type(raw.index)}")
print(f"  'datetime' dtype: {raw['datetime'].dtype}")

# Parse timestamps
raw['dt'] = pd.to_datetime(raw['datetime'])
print(f"\n  Parsed first: {raw['dt'].iloc[0]}")
print(f"  Parsed last:  {raw['dt'].iloc[-1]}")
print(f"  TZ info:      {raw['dt'].iloc[0].tzinfo}")

print("\n" + "=" * 80)
print("STEP 2: Load LIVE TRADES (what the paper bot actually executed)")
print("=" * 80)

trades = pd.read_csv(LIVE_TRADES_PATH)
print(f"  Columns: {list(trades.columns)}")
trades['Time'] = pd.to_datetime(trades['Time'])
today_trades = trades[trades['Time'].dt.date == pd.Timestamp.now().date()]
print(f"  Total trades: {len(trades)}")
print(f"  Today's trades: {len(today_trades)}")
if not today_trades.empty:
    print(f"  Today's first: {today_trades.iloc[0]['Time']} {today_trades.iloc[0]['Side']} @ {today_trades.iloc[0]['Price']}")
    print(f"  Today's last:  {today_trades.iloc[-1]['Time']} {today_trades.iloc[-1]['Side']} @ {today_trades.iloc[-1]['Price']}")

print("\n" + "=" * 80)
print("STEP 3: Load PARAMETERS and init strategy")
print("=" * 80)

params_dict = load_trend_params(PARAMS_PATH)
strategy = TrendStrategy(params_dict)
print(f"  Timeframe: {strategy.timeframe} min")
print(f"  Buy Lookback: {strategy.lookback_buy}")
print(f"  Sell Lookback: {strategy.lookback_sell}")
print(f"  Enable SMA: {strategy.enable_sma_filter} (period={strategy.sma_period})")
print(f"  Enable ADX: {strategy.enable_adx_filter}")
print(f"  Enable Vol: {getattr(strategy, 'enable_vol_filter', False)}")
print(f"  Enable RSI: {getattr(strategy, 'enable_rsi_filter', False)}")
print(f"  Enable VWAP: {getattr(strategy, 'enable_vwap_filter', False)}")
print(f"  Enable RTH: {strategy.enable_rth_filter}")
print(f"  Enable Maint: {strategy.enable_maintenance_filter}")
print(f"  Min bars required: {strategy.min_bars_required}")

print("\n" + "=" * 80)
print("STEP 4: Prepare data for backtest (EXACTLY as compare script does it)")
print("=" * 80)

# This is what compare_paper_backtest_trend.py does:
df_data = pd.read_csv(LIVE_DATA_PATH, index_col=0, parse_dates=True)
df_data.columns = [c.lower().strip() for c in df_data.columns]
print(f"  After read_csv with index_col=0:")
print(f"    Index name: {df_data.index.name}")
print(f"    Index dtype: {df_data.index.dtype}")
print(f"    Index[0]: {df_data.index[0]}")
print(f"    Index[-1]: {df_data.index[-1]}")
print(f"    Columns: {list(df_data.columns)}")

# Timezone conversion — this is where bugs often hide
print(f"\n  Before TZ conversion:")
print(f"    tz info: {getattr(df_data.index, 'tz', 'NONE')}")

df_data.index = pd.to_datetime(df_data.index, utc=True)
print(f"  After pd.to_datetime(utc=True):")
print(f"    tz info: {getattr(df_data.index, 'tz', 'NONE')}")
print(f"    Index[0]: {df_data.index[0]}")

if getattr(df_data.index, 'tz', None) is not None and str(df_data.index.tz) != 'US/Eastern':
    df_data.index = df_data.index.tz_convert('US/Eastern').tz_localize(None)
else:
    df_data.index = df_data.index.tz_localize(None)

print(f"  After TZ conversion to Eastern + localize(None):")
print(f"    tz info: {getattr(df_data.index, 'tz', 'NONE')}")
print(f"    Index[0]: {df_data.index[0]}")
print(f"    Index[-1]: {df_data.index[-1]}")

print("\n" + "=" * 80)
print("STEP 5: Compare data timestamps to trade timestamps")
print("=" * 80)

if not today_trades.empty:
    first_trade_time = today_trades.iloc[0]['Time']
    # Find the closest data bar to the first trade
    trade_ts = pd.Timestamp(first_trade_time)
    print(f"  First trade timestamp (raw): {first_trade_time}")
    print(f"  First trade as Timestamp:    {trade_ts}")
    print(f"  First trade tz:              {trade_ts.tzinfo}")
    
    # Strip tz from trade if needed for comparison
    trade_ts_naive = trade_ts.tz_localize(None) if trade_ts.tzinfo else trade_ts
    
    # Find data bars around that time
    nearby = df_data[(df_data.index >= trade_ts_naive - pd.Timedelta(minutes=5)) & 
                     (df_data.index <= trade_ts_naive + pd.Timedelta(minutes=5))]
    print(f"\n  Data bars within ±5 min of first trade:")
    if nearby.empty:
        print(f"    *** NONE FOUND — this is a TIMESTAMP ALIGNMENT PROBLEM ***")
        # Try with different tz interpretation
        print(f"\n  Trying raw comparison without TZ conversion...")
        raw_df = pd.read_csv(LIVE_DATA_PATH, index_col=0, parse_dates=True)
        raw_df.columns = [c.lower().strip() for c in raw_df.columns]
        raw_nearby = raw_df[(raw_df.index >= str(first_trade_time)[:19]) ]
        print(f"    Raw data near trade time:")
        print(f"    {raw_nearby.head(3)[['open','high','low','close']].to_string()}")
    else:
        print(f"    {nearby[['open','high','low','close']].to_string()}")

print("\n" + "=" * 80)
print("STEP 6: Run indicators on the data and check breakout signals")
print("=" * 80)

# Get today's data only (to match what the bot has)
today_mask = df_data.index.date == pd.Timestamp.now().date()
today_data = df_data[today_mask]
print(f"  Today's data rows: {len(today_data)}")

if len(today_data) > 0:
    print(f"  Today data range: {today_data.index[0]} to {today_data.index[-1]}")
    
    # Calculate indicators
    df_ind = strategy.calculate_indicators(today_data.copy())
    print(f"  After calculate_indicators: {len(df_ind)} rows")
    print(f"  Columns added: {[c for c in df_ind.columns if c not in today_data.columns]}")
    
    if 'donchian_high' in df_ind.columns:
        # Check signals
        long_sigs, short_sigs = strategy.calculate_entry_signals(df_ind)
        
        long_bars = df_ind[long_sigs == True] if hasattr(long_sigs, '__len__') else pd.DataFrame()
        short_bars = df_ind[short_sigs == True] if hasattr(short_sigs, '__len__') else pd.DataFrame()
        
        print(f"\n  Long signals generated: {long_sigs.sum() if hasattr(long_sigs, 'sum') else 'N/A'}")
        print(f"  Short signals generated: {short_sigs.sum() if hasattr(short_sigs, 'sum') else 'N/A'}")
        
        if hasattr(long_sigs, 'sum') and long_sigs.sum() > 0:
            print(f"\n  First 5 LONG signal bars:")
            idx = long_sigs[long_sigs].index[:5] if hasattr(long_sigs, 'index') else df_ind.index[long_sigs][:5]
            for ts in idx:
                row = df_ind.loc[ts]
                print(f"    {ts} | High={row['high']:.2f} > DC_High={row['donchian_high']:.2f} | Close={row['close']:.2f}")
        
        if hasattr(short_sigs, 'sum') and short_sigs.sum() > 0:
            print(f"\n  First 5 SHORT signal bars:")
            idx = short_sigs[short_sigs].index[:5] if hasattr(short_sigs, 'index') else df_ind.index[short_sigs][:5]
            for ts in idx:
                row = df_ind.loc[ts]
                print(f"    {ts} | Low={row['low']:.2f} < DC_Low={row['donchian_low']:.2f} | Close={row['close']:.2f}")
    else:
        print("  WARNING: donchian_high not in columns after calculate_indicators!")
        print(f"  Available: {list(df_ind.columns)}")

print("\n" + "=" * 80)
print("STEP 7: Cross-reference signals to paper trades")
print("=" * 80)

if not today_trades.empty and len(today_data) > 0 and 'donchian_high' in df_ind.columns:
    for _, trade in today_trades.head(10).iterrows():
        trade_time = trade['Time']
        trade_ts_naive = trade_time.tz_localize(None) if trade_time.tzinfo else trade_time
        side = trade['Side']
        price = trade['Price']
        
        # Find the data bar at or just before this trade
        prior_bars = df_ind[df_ind.index <= trade_ts_naive]
        if len(prior_bars) > 0:
            bar = prior_bars.iloc[-1]
            bar_time = prior_bars.index[-1]
            time_diff = (trade_ts_naive - bar_time).total_seconds()
            
            dc_h = bar.get('donchian_high', None)
            dc_l = bar.get('donchian_low', None)
            
            if side == 'BOT':
                signal_match = bar['high'] > dc_h if dc_h else "N/A"
            else:
                signal_match = bar['low'] < dc_l if dc_l else "N/A"
            
            print(f"  Trade {trade_time.strftime('%H:%M:%S')} {side} @ {price:.2f} | "
                  f"Nearest bar: {bar_time.strftime('%H:%M:%S')} (Δ={time_diff:.0f}s) | "
                  f"DC: H={dc_h:.2f if dc_h else 0} L={dc_l:.2f if dc_l else 0} | "
                  f"Signal match: {signal_match}")
        else:
            print(f"  Trade {trade_time.strftime('%H:%M:%S')} {side} @ {price:.2f} | NO DATA BAR FOUND")

print("\n" + "=" * 80)
print("DONE — Check output above for the mismatch root cause")
print("=" * 80)
