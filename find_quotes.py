
lines = open('BB_Genetic_v4.py', 'r', encoding='utf-8').readlines()
count = 0
for i, line in enumerate(lines):
    if '"""' in line or "'''" in line:
        print(f"{i+1}: {line.strip()[:100]}...") # Truncate for readability
        count += 1
print(f"Found {count} lines with triple quotes.")
