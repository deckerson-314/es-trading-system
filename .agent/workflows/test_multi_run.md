---
description: Test workflow for Multi-Solution Backtest functionality
---
1. Verify legacy mode works (should not crash)
// turbo
cd c:\Trading && python BB_Strategy_v4.py --data market_data.csv --params Bollinger/parameters/backtest_params.csv

2. Verify Single Solution GA mode (should run for Solution 0)
// turbo
cd c:\Trading && python BB_Strategy_v4.py --data market_data.csv --ga-file latest --solutions 0

3. Verify Comparison Mode (should generate summary csv and plot)
// turbo
cd c:\Trading && python BB_Strategy_v4.py --data market_data.csv --ga-file latest --solutions 0,1,2
