
import pandas as pd
import pytz

def verify_aggregation():
    # Load the recently downloaded data
    # IMPORTANT: download_recent_data.py saves with timezone info
    try:
        df = pd.read_csv('c:/Trading/recent_warmup_data.csv', parse_dates=['datetime'])
        df.set_index('datetime', inplace=True)
        
        # Convert to Eastern Time for comparison with Live Log (which prints simple time)
        # Note: Live Log prints local time of machine? Or Eastern?
        # ib_deployment_v4.py converts to 'US/Eastern' explicitly before logging.
        # So we must convert to US/Eastern here.
        if df.index.tz is None:
             df.index = df.index.tz_localize('UTC').tz_convert('US/Eastern')
        else:
             df.index = df.index.tz_convert('US/Eastern')
             
    except Exception as e:
        print(f"Error loading data: {e}")
        return

    # Select recent data (post 19:00)
    cutoff = pd.Timestamp.now(tz=pytz.timezone('US/Eastern')).replace(hour=19, minute=0, second=0)
    df = df[df.index >= cutoff]
    
    print(f"Loaded {len(df)} 1-min bars since 19:00.")
    print("Sample 1-min bars (last 5):")
    print(df[['open', 'high', 'low', 'close', 'volume']].tail())

    # Aggregate to 2-min using FIXED logic
    # Logic: df.resample('2T', label='right', closed='left')
    df_resampled = df.resample('2T', label='right', closed='left').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    })
    
    print("\n--- Aggregated 2-Min Bars (closed='left') ---")
    # Filter for the user's specific times: 19:52, 19:54, 19:56, 19:58, 20:00
    target_times = [
        '19:52:00', '19:54:00', '19:56:00', '19:58:00', '20:00:00'
    ]
    
    # We grep the string representation because dates might vary if crossing midnight (unlikely here)
    # But safer to just print the tail that matches time.
    
    print(df_resampled[['open', 'high', 'low', 'close', 'volume']].tail(10))

if __name__ == "__main__":
    verify_aggregation()
