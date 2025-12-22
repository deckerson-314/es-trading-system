import pickle
import os
import glob

def inspect_checkpoints():
    print("Inspecting checkpoints in ga_diagnostics_v4...")
    files = glob.glob('ga_diagnostics_v4/*.pkl')
    
    for fpath in files:
        try:
            with open(fpath, 'rb') as f:
                data = pickle.load(f)
                
            gen = data.get('generation', 'N/A')
            logbook = data.get('logbook', [])
            
            check_gens = [225, 250]
            found_gens = []
            if logbook:
                gens_in_log = [entry['gen'] for entry in logbook]
                min_gen = min(gens_in_log) if gens_in_log else 'N/A'
                max_gen = max(gens_in_log) if gens_in_log else 'N/A'
                
                for g in check_gens:
                    if g in gens_in_log:
                        found_gens.append(g)
            else:
                min_gen = 'N/A'
                max_gen = 'N/A'
                
            print(f"File: {os.path.basename(fpath)}")
            print(f"  Current Generation: {gen}")
            print(f"  Logbook consistency: {len(logbook)} entries")
            print(f"  Range: {min_gen} - {max_gen}")
            print(f"  Contains requested gens {check_gens}: {found_gens}")
            print("-" * 40)
            
        except Exception as e:
            print(f"Error reading {fpath}: {e}")
            print("-" * 40)

if __name__ == "__main__":
    inspect_checkpoints()
