
import pandas as pd
import os

def check_continuity(filepath):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return

    print(f"Checking continuity for: {filepath}")
    
    try:
        # Load data
        df = pd.read_csv(filepath, index_col=0, parse_dates=True)
        
        # Sort just in case
        df.sort_index(inplace=True)
        
        # Calculate time differences
        time_diffs = df.index.to_series().diff()
        
        # Define gap threshold (e.g., > 2 minutes for 1-minute bars)
        gap_threshold = pd.Timedelta(minutes=2)
        
        gaps = time_diffs[time_diffs > gap_threshold]
        
        print(f"Total rows: {len(df)}")
        print(f"Date Range: {df.index.min()} to {df.index.max()}")
        print(f"Found {len(gaps)} gaps larger than {gap_threshold}.")
        
        if not gaps.empty:
            print("\nTop 20 Largest Gaps:")
            sorted_gaps = gaps.sort_values(ascending=False).head(20)
            for date, diff in sorted_gaps.items():
                print(f"  Gap ending at {date}: {diff}")
                
            print("\nGaps within Dec 29-31, 2025:")
            # Use tz-aware timestamps for comparison if index is tz-aware
            tz = gaps.index.tz
            start_date = pd.Timestamp("2025-12-29").tz_localize(tz)
            end_date = pd.Timestamp("2026-01-01").tz_localize(tz)
            
            relevant_gaps = gaps[(gaps.index >= start_date) & (gaps.index < end_date)]
            
            if relevant_gaps.empty:
                print("  No significant gaps found in the target period.")
            else:
                for date, diff in relevant_gaps.sort_values(ascending=False).items():
                     prev_timestamp = date - diff
                     print(f"  Gap: {diff} | START: {prev_timestamp} -> END: {date}")

    except Exception as e:
        print(f"Error checking file: {e}")

if __name__ == "__main__":
    # Check the historical download file
    check_continuity(r"c:\Trading\ES_1min_Dec29_31_20251231.csv")
