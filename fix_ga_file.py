
lines = open('BB_Genetic_v4.py', 'r', encoding='utf-8').readlines()
with open('BB_Genetic_v4.py', 'w', encoding='utf-8') as f:
    for i, line in enumerate(lines):
        # 1-based index to 0-based
        idx = i + 1
        if 1564 <= idx <= 2367:
            continue
        f.write(line)
print("Files trimmed.")
