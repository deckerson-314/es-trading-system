
with open('c:/Trading/ib_deployment_v4.py', 'r') as f:
    for i, line in enumerate(f, 1):
        if 'ib = IB(' in line or 'ib=IB(' in line or 'ib = IB (' in line:
            print(f"Line {i}: {line.strip()}")
