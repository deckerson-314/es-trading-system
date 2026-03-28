
import datetime
last_time = datetime.datetime(2025, 10, 10, 16, 59)
march_roll_date = datetime.datetime(2026, 3, 12, 16, 0)
delta = march_roll_date - last_time
print(f"Delta: {delta}")
print(f"Days: {delta.days}")
