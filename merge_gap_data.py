import pandas as pd
import os
import glob
import datetime
import shutil

def merge_data():
    print("--- Starting Data Merge ---")
    
    # 1. Identify paths
    main_file = r"c:\Trading\Backtrader\data\ES_full_1min_continuous_ratio_adjusted.csv"
    backup_file = r"c:\Trading\Backtrader\data\ES_full_1min_continuous_ratio_adjusted_BACKUP.csv"
    
    # Verify backup exists
    if not os.path.exists(backup_file):
        print(f"Error: Backup file not found at {backup_file}")
        # Option: Create it now?
        # print("Creating backup...")
        # shutil.copy(main_file, backup_file)
        return

    # 2. Find the newly downloaded file
    # The downloader uses a legacy path: /content/drive/MyDrive/TradingStrategyOptimization/data
    # On Windows, this often maps to C:\content...
    # We search multiple probable locations.
    
    # We search recursively from c:\Trading to be safe.
    # Updated: Found it at C:\content\...
    print("Searching for latest data file in download directory...")
    # hardcoded path assumed from previous context
    search_dir = r"C:\content\drive\MyDrive\TradingStrategyOptimization\data"
    search_pattern = os.path.join(search_dir, "ES_1min_90D_*.csv")
    files = glob.glob(search_pattern)
    
    if not files:
        print(f"Error: No data files found matching {search_pattern}")
        # Check if directory exists at least
        if not os.path.exists(search_dir):
            print(f"  Directory not found: {search_dir}")
        return
        
    # Pick newest file based on modification time
    new_data_path = max(files, key=os.path.getmtime)
    
    if not os.path.exists(new_data_path):
        print(f"Error: Selected file not found (race condition?): {new_data_path}")
        return
        
    print(f"Found newest data file: {new_data_path}")
    
    candidate_files = [new_data_path]
    
    # 3. Load Data
    print("Loading datasets...")
    
    # Load Main
    # IMPORTANT: Main file has NO HEADER.
    print(f"Reading Main File (No Header): {main_file}")
    df_main = pd.read_csv(main_file, header=None, names=['datetime', 'Open', 'High', 'Low', 'Close', 'Volume'])
    df_main['datetime'] = pd.to_datetime(df_main['datetime'])
    df_main.set_index('datetime', inplace=True)
    print(f"Main Data: {len(df_main)} rows. End: {df_main.index[-1]}")

    # Load New
    print(f"Reading New File (With Header): {new_data_path}")
    df_new = pd.read_csv(new_data_path)
    
    # Select only relevant columns
    desired_cols = ['datetime', 'Open', 'High', 'Low', 'Close', 'Volume']
    df_new = df_new[desired_cols]
    
    # The new data has strict timezone info likely (e.g. -05:00)
    # Force string conversion first to be safe
    df_new['datetime'] = df_new['datetime'].astype(str)
    # Parse to UTC to handle mixed timezones (DST transition)
    df_new['datetime'] = pd.to_datetime(df_new['datetime'], utc=True)
    
    # Drop invalid dates
    df_new.dropna(subset=['datetime'], inplace=True)
    
    df_new.set_index('datetime', inplace=True)
    print(f"New Data Index Type: {type(df_new.index)}")
    print(f"New Data: {len(df_new)} rows. Start: {df_new.index[0]} End: {df_new.index[-1]}")
    
    # Check if we have a valid DatetimeIndex
    if not isinstance(df_new.index, pd.DatetimeIndex):
         print("Error: Failed to create DatetimeIndex for New Data.")
         # Try to coerce if it's still object
         df_new.index = pd.to_datetime(df_new.index, utc=True, errors='coerce')
    
    # 4. Timezone Normalization
    print("Normalizing Timezones (converting New Data to ET/Naive match)...")
    
    # Check if main is naive
    is_main_naive = df_main.index.tz is None
    
    if is_main_naive:
        if df_new.index.tz is not None:
             print("Converting New (Aware) -> ET -> Naive")
             df_new_et = df_new.index.tz_convert('US/Eastern')
             df_new.index = df_new_et.tz_localize(None)
        else:
             print("Warning: New data is also naive. Assuming correctly aligned.")
    else:
        print("Main data is TZ-aware? Aligning new data.")
        df_new.index = df_new.index.tz_convert(df_main.index.tz)

    print(f"New Data (Normalized) End: {df_new.index[-1]}")
    
    # 5. Merge and Deduplicate
    print("Merging...")
    df_combined = pd.concat([df_main, df_new])
    
    # Sort
    df_combined.sort_index(inplace=True)
    
    # Remove duplicates (keep last/newest?)
    before_dedup = len(df_combined)
    df_combined = df_combined[~df_combined.index.duplicated(keep='last')]
    after_dedup = len(df_combined)
    print(f"Removed {before_dedup - after_dedup} duplicate bars.")
    
    print(f"Combined Start: {df_combined.index[0]}")
    print(f"Combined End:   {df_combined.index[-1]}")
    
    # 6. Save
    print(f"Saving to {main_file} (No Header)...")
    df_combined.to_csv(main_file, header=False)
    print("Success! Data gap filled.")

if __name__ == "__main__":
    merge_data()
