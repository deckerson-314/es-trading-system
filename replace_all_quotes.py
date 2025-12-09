
def replace_quotes():
    lines = open('BB_Genetic_v4.py', 'r', encoding='utf-8').readlines()
    new_lines = []
    
    for i, line in enumerate(lines):
        if '"""' in line or "'''" in line:
            tq = '"""' if '"""' in line else "'''"
            
            # Only process if it starts and ends on this line (count >= 2)
            if line.count(tq) >= 2:
                # We assume simple case: prefix + tq + content + tq + suffix
                parts = line.split(tq)
                # If split gives > 3 parts, it means > 2 quotes. 
                # e.g. prefix """ content """ suffix """ comment """
                # We'll validly assume the first and last are the boundaries? No.
                # We'll assume strict 2 quotes for now as flattened strings usually match this.
                
                if len(parts) == 3: # Correct count (empty strings around quotes count as parts)
                    prefix = parts[0]
                    content = parts[1]
                    suffix = parts[2]
                    
                    # Choose delimiter
                    if content.count("'") < content.count('"'):
                        new_q = "'"
                        content = content.replace("'", "\\'")
                    else:
                        new_q = '"'
                        content = content.replace('"', '\\"')
                        
                    new_line = prefix + new_q + content + new_q + suffix
                    new_lines.append(new_line)
                else:
                    print(f"Skipping line {i+1}: counts mismatch (parts={len(parts)})")
                    new_lines.append(line)
            else:
                 # Docstrings or multiline that wasn't flattened
                 new_lines.append(line)
        else:
            new_lines.append(line)
            
    with open('BB_Genetic_v4.py', 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    print("Triple quotes replaced.")

replace_quotes()
