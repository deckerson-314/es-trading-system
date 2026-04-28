import os

file_path = r'c:\Trading\optimize.py'
try:
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
except UnicodeDecodeError:
    # Fallback to latin-1 if utf-8 fails
    with open(file_path, 'r', encoding='latin-1') as f:
        content = f.read()

# Unified Mapping
replacements = {
    "'max_drawdown'": "'max_dd'",
    '"max_drawdown"': '"max_dd"',
    "'profit_factor'": "'pf'",
    '"profit_factor"': '"pf"',
    "'total_profit'": "'pnl'",
    '"total_profit"': '"pnl"',
    "'avg_profit_per_trade'": "'ppt'",
    '"avg_profit_per_trade"': '"ppt"',
    "'avg_trades_day'": "'trades_day'",
    '"avg_trades_day"': '"trades_day"',
}

# Apply replacements
for old, new in replacements.items():
    content = content.replace(old, new)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Global replacement complete (with UTF-8 handling).")
