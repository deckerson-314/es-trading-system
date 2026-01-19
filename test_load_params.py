import sys
import os
sys.path.append(os.getcwd())
from bollinger_strategy.parameters import load_params

p = load_params(r'c:\Trading\Bollinger\parameters\live_params.csv')
key = 'Opposite Bollinger Band TP'
if key in p:
    print(f"{key}: {p[key]}")
else:
    print(f"{key} NOT FOUND")

key2 = 'Fixed BB at Entry TP'
print(f"{key2}: {p.get(key2, 'NOT FOUND')}")

key3 = 'TP Method'
print(f"{key3}: {p.get(key3, 'NOT FOUND')}")
