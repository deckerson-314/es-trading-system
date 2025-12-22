import pandas as pd
import sys

def extract_sol0():
    try:
        csv_path = r"Bollinger\parameters\genetic_results_2025-12-13-2.csv"
        df = pd.read_csv(csv_path)
        
        target_col = "Solution_0_SELECTED"
        if target_col not in df.columns:
            # Maybe it's just 'Solution_0'?
            target_col = "Solution_0"
            
        if target_col not in df.columns:
            print("Col not found")
            return

        with open("sol0_params.txt", "w") as f:
            f.write(f"Parameters for {target_col}\n")
            f.write("="*50 + "\n")
            
            for _, row in df.iterrows():
                name = row['Name']
                val = row[target_col]
                
                # Filter junk
                if pd.isna(name) or str(name).startswith("===") or str(name).startswith("__"):
                    continue
                    
                f.write(f"{name:<40} | {val}\n")
                
        print("Done.")

    except Exception as e:
        print(e)
        
if __name__ == "__main__":
    extract_sol0()
