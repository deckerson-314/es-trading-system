import pandas as pd

def check_ts():
    df = pd.read_csv('c:\\Trading\\temp_combined_data.csv', index_col=0, parse_dates=True)
    if not df.empty:
         ts = df.index[0]
         print(f"Timestamp Type: {type(ts)}")
         print(f"String Rep: '{str(ts)}'")
         
         # Check 09:12
         mask = df.index.astype(str).str.contains('09:12')
         if mask.any():
              match = df.index[mask][0]
              print(f"09:12 Match: '{str(match)}'")
              print(f"StartsWith 2026-01-15 09:1? {str(match).startswith('2026-01-15 09:1')}")
    else:
         print("DF Empty")

if __name__ == "__main__":
    check_ts()
