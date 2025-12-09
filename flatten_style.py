
lines = open('BB_Genetic_v4.py', 'r', encoding='utf-8').readlines()
start_idx = 1948 - 1  # 0-based
end_idx = 2073 - 1    # 0-based inclusive

css_lines = lines[start_idx:end_idx+1]
joined_css = "".join([l.strip() + " " for l in css_lines])
joined_css = joined_css.replace('{', '{{').replace('}', '}}') # Proper escaping for f-string
# But wait, original code ALREADY escaped {{?
# Line 1949: body {{ font-family ... }}
# If I join them, I have {{ font-family ... }}
# If I run replace('{', '{{') on `{{`, I get `{{{{`. That's bad.
# The original code ALREADY has double braces for f-string.
# So I should NOT escape them again if they are already escaped.
# Actually, I should just join them. 
# But stripping newlines might merge `}}` with next `.class`? `}} .class`. Safe.

joined_css = "".join([l.strip() + " " for l in css_lines])

# Replace the block with the single line
new_lines = lines[:start_idx] + [joined_css + "\n"] + lines[end_idx+1:]

with open('BB_Genetic_v4.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print("CSS flattened.")
