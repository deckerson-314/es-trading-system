
import re

def flatten_multiline():
    lines = open('BB_Genetic_v4.py', 'r', encoding='utf-8').readlines()
    
    # Target range: Expanded to cover missed HTML blocks
    start_line = 1700
    end_line = 3600 
    
    new_lines = []
    i = 0
    in_multiline = False
    quote_char = None
    buffer = []
    
    while i < len(lines):
        line = lines[i]
        
        # Only process lines in range
        if i + 1 < start_line or i + 1 > end_line:
            new_lines.append(line)
            i += 1
            continue
            
        # Check for start of multiline
        # Detect """ or '''
        # Be careful not to detecting closing quotes if we are already inside
        
        if not in_multiline:
            # Check for Triple Quotes
            # We look for """ or '''
            # We also check if it is closed on the same line (e.g. """ foo """) - if so, skip logic
            
            tq1 = '"""'
            tq2 = "'''"
            
            has_tq1 = tq1 in line
            has_tq2 = tq2 in line
            
            found_quote = None
            if has_tq1 and not has_tq2: found_quote = tq1
            elif has_tq2 and not has_tq1: found_quote = tq2
            elif has_tq1 and has_tq2:
                # Ambiguous, take the first one? Or just skip to avoid complexity
                found_quote = tq1 if line.find(tq1) < line.find(tq2) else tq2
            
            if found_quote:
                # Check if it appears twice (opened and closed on same line)
                # Count occurrences
                count = line.count(found_quote)
                if count >= 2:
                    # Self-contained, assume it relies on newlines? 
                    # If it's self-contained single line, we don't need to flatten it (it's already 1 line)
                    # But if it has newlines within it? Python reads logical lines? No readlines reads physical lines.
                    # So if count >= 2, it starts and ends on this line. 
                    new_lines.append(line)
                    i += 1
                    continue
                else:
                    # Opened but not closed
                    in_multiline = True
                    quote_char = found_quote
                    buffer = [line.strip()] # Start buffer
                    # We need to preserve the indent of the variable assignment if present
                    # e.g. "    html = """
                    # The strip() removes leading indent.
                    # We should keep the leading indent of the FIRST line.
                    buffer = [line.rstrip()] # Keep leading indent, strip trailing newline
                    i += 1
                    continue
            else:
                new_lines.append(line)
                i += 1
                continue
        else:
            # We are IN multiline
            # Check for closing quote
            if quote_char in line:
                # Found closing quote
                # Append to buffer (stripped)
                buffer.append(line.strip())
                in_multiline = False
                
                # Join buffer
                full_line = " ".join(buffer)
                # Replace the triple quote with single quote (or double) to make it a normal string
                # BUT we must handle internal quotes.
                # Easiest is to keep using triple quotes but ensure it is one line?
                # No, triple quote on one line is valid.
                # line = """ foo bar """ is valid.
                # So we just join them.
                
                # Careful: We stripped the newline char from lines.
                new_lines.append(full_line + "\n")
                i += 1
            else:
                # Middle of multiline
                buffer.append(line.strip())
                i += 1
                
    with open('BB_Genetic_v4.py', 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    print("Multi-line strings flattened.")

flatten_multiline()
