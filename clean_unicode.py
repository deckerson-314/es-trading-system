
import re

with open('BB_Genetic_v4.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace specifically known ones with ASCII equivalents if possible
content = content.replace('←', '<-')
content = content.replace('★', '*')
content = content.replace('⚠️', '(!)')
content = content.replace('🔗', '-')

# Strip remaining non-ASCII
# This regex matches any character that is NOT standard ASCII (0-127)
clean_content = re.sub(r'[^\x00-\x7F]+', '', content)

with open('BB_Genetic_v4.py', 'w', encoding='utf-8') as f:
    f.write(clean_content)

print("Unicode stripped.")
