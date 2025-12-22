
import pickle
import sys
import os
from deap import base, creator, tools

# Setup DEAP environment to allow unpickling
if not hasattr(creator, "FitnessMulti"):
    creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0, 1.0, 1.0, 2.0, 2.0))
if not hasattr(creator, "Individual"):
    creator.create("Individual", list, fitness=creator.FitnessMulti)

def inspect_checkpoint(filepath):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return

    try:
        with open(filepath, "rb") as f:
            cp = pickle.load(f)
        
        pop = cp.get("population", [])
        gen = cp.get("generation", 0)
        
        print(f"Checkpoint Information:")
        print(f"  Generation: {gen}")
        print(f"  Population Size: {len(pop)}")
        
        if not pop:
            print("  Population is empty.")
            return

        # Check fitness values
        # Fitness weights: (Sortino, DD, PF, Trades, PnL, PPT)
        # We are interested in Sortino (Index 0) and PnL (Index 4)
        
        sortinos = []
        pnls = []
        
        for ind in pop:
            if ind.fitness.valid:
                vals = ind.fitness.values
                # Note: fitness values in DEAP are stored as-is (unweighted? No, unweighted inputs).
                # Wait, my code returns NORMALIZED values.
                # So if I see negative values here, it confirms the fix.
                sortinos.append(vals[0])
                pnls.append(vals[4])

        if sortinos:
            print(f"  Best Sortino: {max(sortinos):.6f}")
            print(f"  Worst Sortino: {min(sortinos):.6f}")
            print(f"  Avg Sortino: {sum(sortinos)/len(sortinos):.6f}")
            
            print(f"  Best PnL (Norm): {max(pnls):.6f}")
            print(f"  Worst PnL (Norm): {min(pnls):.6f}")
            
            # Count negatives
            neg_sortinos = sum(1 for x in sortinos if x < 0)
            print(f"  Negative Sortinos: {neg_sortinos} / {len(sortinos)}")
            
            # Diversity Check
            unique_inds = set(tuple(ind) for ind in pop)
            diversity_pct = (len(unique_inds) / len(pop)) * 100.0
            print(f"  Population Diversity: {diversity_pct:.1f}% ({len(unique_inds)}/{len(pop)} unique)")
            
            # Print Top 3 Individuals
            print("\n  Top 3 Candidates (by Sortino):")
            # Sort by Sortino descending
            sorted_pop = sorted(pop, key=lambda ind: ind.fitness.values[0], reverse=True)
            
            for i in range(min(3, len(sorted_pop))):
                ind = sorted_pop[i]
                try:
                    # Try to get trades/day from fitness if available (index 3)
                    trades_val = ind.fitness.values[3] if len(ind.fitness.values) > 3 else 0
                    print(f"    #{i+1}: Sortino={ind.fitness.values[0]:.4f}, DD={ind.fitness.values[1]:.4f}, PnL={ind.fitness.values[4]:.4f}, Trades/Day={trades_val:.4f}")
                    if i == 0:
                        print(f"       Params: {ind}")
                except Exception as e: # Corrected the syntax error in the original snippet's except block
                     print(f"    #{i+1}: {ind.fitness.values} (Error: {e})")

    except Exception as e:
        print(f"Error reading checkpoint: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] in ['?', '-?', '/?', '--help', '-h']:
            print(f"""
================================================================================
             GA CHECKPOINT INSPECTOR
================================================================================

DESCRIPTION:
  Analyzes a binary Genetic Algorithm Checkpoint (.pkl) file and reports statistics
  about the population, including:
  - Best/Worst/Average Sortino Ratio
  - Number of Negative/Invalid solutions
  - Population Diversity (Uniqueness %)
  - Top 3 Candidate Details (Sortino, DD, PnL, Trades/Day)

USAGE:
  python inspect_checkpoint.py [CHECKPOINT_FILE]

ARGUMENTS:
  CHECKPOINT_FILE   Path to the .pkl file to inspect.
                    (Optional. If invalid or missing, defaults to latest hardcoded path).

EXAMPLES:
  Inspect Latest:   python inspect_checkpoint.py
  Inspect Specific: python inspect_checkpoint.py ga_diagnostics_v4/ga_checkpoint_2025-12-13-1.pkl
  Get Help:         python inspect_checkpoint.py ?

================================================================================
""")
            sys.exit(0)
        # Allow passing filename as argument
        inspect_checkpoint(sys.argv[1])
    else:
        inspect_checkpoint("ga_diagnostics_v4/ga_checkpoint_2025-12-13-1.pkl")

