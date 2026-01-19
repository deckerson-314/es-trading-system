try:
    with open(r'c:\Trading\results_final_check.txt', 'r') as f:
        lines = f.readlines()
        print("--- LAST 48H ANALYSIS ---")
        for line in lines:
            if "2026-01-14" in line or "2026-01-15" in line or "2026-01-16" in line:
                if "MATCHED" in line or "ONLY" in line or "MISMATCH" in line:
                     # Clean up extra whitespace/indents
                     print(" ".join(line.split()))
except Exception as e:
    print(e)
