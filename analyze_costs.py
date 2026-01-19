import pandas as pd

try:
    print("Loading live_trades.csv...")
    trades = pd.read_csv('c:/Trading/paper_logs/live_trades.csv')
    if 'Commission' in trades.columns:
        avg_comm_per_fill = trades['Commission'].mean()
        print(f"Average Commission per Fill: ${avg_comm_per_fill:.2f}")
        print(f"Estimated Round Trip Commission: ${avg_comm_per_fill * 2:.2f}")
    else:
        print("Commission column not found in live_trades.csv")

    print("\nLoading comparison_metrics_sequential.csv...")
    metrics = pd.read_csv('c:/Trading/comparison_metrics_sequential.csv')
    
    # Calculate Stats
    avg_diff = metrics['PnL Diff'].mean()
    median_diff = metrics['PnL Diff'].median()
    
    print(f"Average PnL Diff (Live - BT): ${avg_diff:.2f}")
    print(f"Median PnL Diff (Live - BT): ${median_diff:.2f}")
    
    # Logic: 
    # BT PnL was calculated as (Gross - 20)
    # Live PnL is Gross
    # Diff = Live - BT = Live_Gross - (BT_Gross - 20) = (Live_Gross - BT_Gross) + 20
    # Slippage = BT_Gross - Live_Gross
    # Diff = -Slippage + 20
    # Slippage = 20 - Diff
    
    est_slippage = 20 - avg_diff
    print(f"Estimated Avg Slippage: ${est_slippage:.2f}")
    
    # Total Cost Estimate
    # If we want the backtest to match the Live Result (Live_Gross - Comm)
    # Target BT Net PnL = Live_Gross - Comm
    # Currently BT Net = BT_Gross - Cost
    # We want BT_Gross - Cost = Live_Gross - Comm
    # Cost = (BT_Gross - Live_Gross) + Comm
    # Cost = Slippage + Comm
    
    comm_rt = avg_comm_per_fill * 2
    rec_cost = est_slippage + comm_rt
    
    print(f"Total Recommended Cost (Slippage + Comm): ${rec_cost:.2f}")

except Exception as e:
    print(f"Error: {e}")
