
import os

file_path = r'c:\Trading\ib_deployment_v4.py'
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
inserted_global = False
modified_on_bar = False
modified_main = False

for i, line in enumerate(lines):
    new_lines.append(line)
    
    # 1. Insert Global Variable
    if not inserted_global and 'contract = None' in line and 'ib = IB()' not in line: # Ensure correct block
        # Check surrounding lines to be sure
        if i > 0 and 'bars = None' in lines[i-1]:
            new_lines.append('last_data_receipt_time = datetime.now() # Track data liveness\n')
            inserted_global = True
            print("Inserted global variable.")

    # 2. Modify on_bar_update
    if 'def on_bar_update(bars, hasNewBar):' in line:
        # Expect next line to be global decl, or docstring?
        # Let's peek
        pass 
    
    if 'global data, bar_count' in line and 'def on_bar_update' in lines[i-1]:
         # Replace this line
         new_lines[-1] = '    global data, bar_count, last_data_receipt_time\n'
         # Insert update logic
         new_lines.append('    try:\n')
         new_lines.append('        # Update liveness tracker\n')
         new_lines.append('        last_data_receipt_time = datetime.now()\n')
         modified_on_bar = True
         print("Modified on_bar_update.")
         # Note: The original 'try:' is in the next line usually?
         # Check content of on_bar_update in previous steps
         # Step 9313:
         # def on_bar_update(bars, hasNewBar):
         #    global data, bar_count
         #    try:
         #        if not hasNewBar:
         
         # So my insertion adds an extra try?
         # I should just replace the global line and add the update BEFORE the existing try, or inside it.
         # Let's be careful.
         
for i in range(len(new_lines)):
    if 'def on_bar_update' in new_lines[i]:
        # Reset modify flag locally tracking
        pass

# Re-reading to apply precise transformation for on_bar_update
final_lines = []
skip = False
for i, line in enumerate(lines):
    # 1. Global
    if 'contract = None' in line and 'bars = None' in lines[i-1]:
        final_lines.append(line)
        final_lines.append('last_data_receipt_time = datetime.now() # Track data liveness\n')
        continue

    # 2. on_bar_update
    if 'global data, bar_count' in line and 'def on_bar_update' in lines[i-1]:
        final_lines.append('    global data, bar_count, last_data_receipt_time\n')
        # Insert update immediately
        final_lines.append('    last_data_receipt_time = datetime.now()\n') 
        continue

    # 3. Main Loop Liveness Check
    # Context: inside main loop, after loop_count += 1
    # Step 9309:
    # 3818:                 loop_count += 1
    # 3819:                 if loop_count % 1 == 0:  # Update every 10 seconds (every iteration)
    # 3820:                     update_dashboard()
    
    if 'if loop_count % 1 == 0:' in line and 'update_dashboard()' in lines[i+1]:
        final_lines.append(line)
        # Insert check before update_dashboard? Or after?
        # update_dashboard()
        # Insert check here
        continue
    
    if 'update_dashboard()' in line and 'loop_count % 1 == 0' in lines[i-1]:
        final_lines.append(line)
        # Add liveness check
        final_lines.append('\n                # DATA LIVENESS CHECK\n')
        final_lines.append('                time_since_last_data = (datetime.now() - last_data_receipt_time).total_seconds()\n')
        final_lines.append('                if time_since_last_data > 60:\n')
        final_lines.append('                    logging.warning(f"⚠️ DATA STALLED! No bars for {time_since_last_data:.1f}s. Force-restarting data...")\n')
        final_lines.append('                    add_to_live_tracker(\'warning\', \'Data Stalled - Forcing Restart\')\n')
        final_lines.append('                    ensure_connected_and_subscribed()\n')
        final_lines.append('                    last_data_receipt_time = datetime.now() # Reset to avoid loop\n')
        continue

    final_lines.append(line)

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(final_lines)
    
print("Done.")
