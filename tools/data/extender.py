
import pandas as pd
from ib_insync import IB, Future, util
import datetime
import os
import time

# Configuration
MASTER_FILE = r'C:\Trading\Bollinger\data\ES_full_1min_continuous_ratio_adjusted.csv'
ESH6_EXPIRY = '20260320'
ESM6_EXPIRY = '20260618'

def extend_master_data():
    ib = IB()
    try:
        # 1. Connect
        print("Connecting to IBKR...")
        ib.connect('127.0.0.1', 7497, clientId=210)
        
        # 2. Analyze Master
        if not os.path.exists(MASTER_FILE):
             print(f"Error: Master file not found at {MASTER_FILE}")
             return

        print(f"Reading last line of master file: {MASTER_FILE}")
        with open(MASTER_FILE, 'r') as f:
            lines = f.readlines()
            if not lines:
                 print("Error: Master file is empty.")
                 return
            last_line = lines[-1].strip()
            parts = last_line.split(',')
            last_time_str = parts[0]
            last_close = float(parts[4])
        
        last_time = datetime.datetime.strptime(last_time_str, '%Y-%m-%d %H:%M:%S')
        print(f"Master file ends at: {last_time} with Adjusted Close: {last_close}")

        # 3. Setup Contracts
        march_contract = Future(symbol='ES', lastTradeDateOrContractMonth=ESH6_EXPIRY, exchange='CME', currency='USD')
        june_contract = Future(symbol='ES', lastTradeDateOrContractMonth=ESM6_EXPIRY, exchange='CME', currency='USD')
        ib.qualifyContracts(march_contract, june_contract)

        # 4. Download March Strip (Bridge Phase)
        march_roll_date = datetime.datetime(2026, 3, 12, 16, 0)
        delta = march_roll_date - last_time
        days_to_download = delta.days + 5
        
        all_bars = []
        end_dt = march_roll_date
        
        chunk_days = 7 # Small chunks for stability
        while True:
            duration = f"{chunk_days} D"
            print(f"  - Requesting ESH6 chunk ending {end_dt or 'now'} ({duration})...")
            
            bars = None
            for attempt in range(3):
                try:
                    bars = ib.reqHistoricalData(
                        march_contract,
                        endDateTime=end_dt,
                        durationStr=duration,
                        barSizeSetting='1 min',
                        whatToShow='TRADES',
                        useRTH=False,
                        formatDate=1
                    )
                    if bars: 
                        break
                    print(f"    - Empty bars on attempt {attempt+1}. Retrying...")
                except Exception as e:
                    print(f"    - Attempt {attempt+1} failed: {e}. Retrying...")
                ib.sleep(3)
            
            if not bars:
                print("  - Failed to get bars after retries. Stopping download.")
                break
            
            all_bars.extend(bars)
            end_dt = bars[0].date
            
            # Early exit if we have enough history
            if end_dt.replace(tzinfo=None) < last_time:
                 print(f"  - Target date {last_time} reached.")
                 break
                 
            ib.sleep(2.0)

        if not all_bars:
            print("Failed to download March data.")
            return

        df_march = util.df(all_bars)
        df_march.drop_duplicates(subset=['date'], inplace=True)
        df_march.sort_values('date', inplace=True)
        
        df_march['datetime'] = pd.to_datetime(df_march['date']).dt.tz_localize(None)
        df_march.set_index('datetime', inplace=True)
        
        # Find the bridge bar
        if last_time not in df_march.index:
            bridge_candidates = df_march[df_march.index > last_time]
            if bridge_candidates.empty:
                print("Could not find a bridge bar. Range mismatch?")
                return
            bridge_bar = bridge_candidates.iloc[0]
            print(f"Bridging at available bar: {bridge_candidates.index[0]}")
        else:
            bridge_bar = df_march.loc[last_time]
            print(f"Found exact bridge bar at {last_time}")

        # Calculate Multiplier
        multiplier_march = last_close / bridge_bar['close']
        print(f"Calculated March Multiplier: {multiplier_march:.8f}")

        # Adjust March bars
        new_march_bars = df_march[df_march.index > last_time].copy()
        for col in ['open', 'high', 'low', 'close']:
            new_march_bars[col] = new_march_bars[col] * multiplier_march
            
        # 5. Download June Strip (Roll Phase)
        print(f"\nPhase 2: Retrieving June 2026 (ESM6) data...")
        now = datetime.datetime.now()
        delta_june = (now - march_roll_date).days + 2
        
        june_bars = ib.reqHistoricalData(
            june_contract,
            endDateTime='',
            durationStr=f"{delta_june} D",
            barSizeSetting='1 min',
            whatToShow='TRADES',
            useRTH=False,
            formatDate=1
        )
        
        if not june_bars:
             print("Failed to download June data.")
             return
             
        df_june = util.df(june_bars)
        df_june['datetime'] = pd.to_datetime(df_june['date']).dt.tz_localize(None)
        df_june.set_index('datetime', inplace=True)
        df_june.sort_index(inplace=True)
        
        # Calculate June Multiplier at the Roll Date
        last_adj_march = new_march_bars[new_march_bars.index <= march_roll_date].iloc[-1]
        first_june = df_june[df_june.index >= last_adj_march.name].iloc[0]
        
        multiplier_june = last_adj_march['close'] / first_june['close']
        print(f"Rolling at {last_adj_march.name}. ESH6_adj: {last_adj_march['close']:.2f}, ESM6_real: {first_june['close']:.2f}")
        print(f"Calculated June Multiplier: {multiplier_june:.8f}")
        
        # Adjust June bars
        new_june_bars = df_june[df_june.index > last_adj_march.name].copy()
        for col in ['open', 'high', 'low', 'close']:
            new_june_bars[col] = new_june_bars[col] * multiplier_june
            
        # 6. Combine and Format
        combined_new = pd.concat([new_march_bars[new_march_bars.index <= last_adj_march.name], new_june_bars])
        combined_new.sort_index(inplace=True)
        
        # Format for CSV
        combined_new['output'] = combined_new.index.strftime('%Y-%m-%d %H:%M:%S') + "," + \
                                 combined_new['open'].map('{:.2f}'.format) + "," + \
                                 combined_new['high'].map('{:.2f}'.format) + "," + \
                                 combined_new['low'].map('{:.2f}'.format) + "," + \
                                 combined_new['close'].map('{:.2f}'.format) + "," + \
                                 combined_new['volume'].astype(int).astype(str)
        
        # 7. Append to Master
        print(f"\nAppending {len(combined_new)} rows to {MASTER_FILE}...")
        
        backup_file = MASTER_FILE + ".bak"
        import shutil
        shutil.copy2(MASTER_FILE, backup_file)
        
        with open(MASTER_FILE, 'a') as f:
            for row in combined_new['output']:
                f.write(row + "\n")
        
        print("Success!")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        ib.disconnect()

if __name__ == "__main__":
    extend_master_data()
