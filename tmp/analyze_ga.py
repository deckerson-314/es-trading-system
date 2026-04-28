
import csv

def analyze_file(filepath):
    with open(filepath, 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            if "Enable ADX Filter" in row[0]:
                solutions = row[6:]
                # Convert to int, handle potential noise
                vals = []
                for s in solutions:
                    try:
                        vals.append(int(s))
                    except:
                        pass
                zeros = vals.count(0)
                ones = vals.count(1)
                total = len(vals)
                return zeros, ones, total
    return None

files = [
    r"c:\Trading\Trend\parameters\genetic_results_2026-04-01-1.csv",
    r"c:\Trading\Trend\parameters\genetic_results_2026-04-03-1.csv"
]

for f in files:
    res = analyze_file(f)
    print(f"File: {f}")
    if res:
        zeros, ones, total = res
        print(f"  Total Solutions: {total}")
        print(f"  Enable ADX Filter = 0: {zeros} ({zeros/total*100:.2f}%)")
        print(f"  Enable ADX Filter = 1: {ones} ({ones/total*100:.2f}%)")
    else:
        print("  Parameter not found")
