
with open('BB_Genetic_v4.py', 'r') as f:
    for i, line in enumerate(f):
        if 'def parallel_evaluate' in line:
             print(f"{i+1}: {line.strip()}")
