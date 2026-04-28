import pickle

checkpoint_path = r'Trend\diagnostics\ga_checkpoint_2026-04-24-1.pkl'
with open(checkpoint_path, 'rb') as f:
    cp = pickle.load(f)

print("Checkpoint Keys:", cp.keys())
if 'param_keys' in cp:
    print("Param Keys from Checkpoint:", cp['param_keys'])
else:
    print("param_keys NOT in checkpoint.")

# Check the first few individuals to see their structure
if 'hall_of_fame' in cp:
    hof = cp['hall_of_fame']
    if len(hof) > 0:
        print("HOF[0] length:", len(hof[0]))
        print("HOF[0] value samples:", hof[0][:5])
