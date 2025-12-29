# System Architecture

This diagram illustrates the components of the Bollinger Band Trading Platform, showing how the Strategy Logic, Genetic Algorithm, Live Trading, and Verification tools interact.

```mermaid
graph TD
    %% Styles
    classDef logic fill:#f9f,stroke:#333,stroke-width:2px;
    classDef script fill:#e1f5fe,stroke:#0277bd,stroke-width:2px;
    classDef data fill:#fff9c4,stroke:#fbc02d,stroke-width:2px,shape:cylinder;
    classDef output fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
    classDef trigger stroke-dasharray: 5 5;

    %% --- 1. CORE LOGIC ---
    subgraph Core["Shared Strategy Core"]
        StratLogic[("BollingerBandStrategyV4<br/>(bollinger_strategy pkg)")]:::logic
    end

    %% --- 2. OPTIMIZATION (GA) ---
    subgraph Optimization["Optimization Engine"]
        GA["ga_runner_v4.py<br/>(Genetic Algorithm)"]:::script
        HistData[("Historical Data<br/>(c:/Trading/data/*.csv)")]:::data
        
        GA -->|Run| StratLogic
        GA -->|Read| HistData
        GA -->|Generate| SolJSON[("solutions.json")]:::data
        GA -->|Export Best| LiveParams[("live_params.csv")]:::data
    end

    %% --- 3. LIVE TRADING ---
    subgraph LiveTrading["Live Execution"]
        IBLive["ib_deployment_v4.py<br/>(IBKR Connection)"]:::script
        IBKR[("Interactive Brokers<br/>(TWS/Gateway)")]
        
        IBLive -->|Load Config| LiveParams
        IBLive -->|Execute| StratLogic
        IBLive <-->|Order/Data| IBKR
        
        IBLive -->|Log Exec| LiveTradesCSV[("live_trades.csv")]:::data
        IBLive -->|Log Market| LiveDataCSV[("live_data.csv")]:::data
        IBLive -->|Log Text| LogFile[("ib_deployment.log")]:::data
    end

    %% --- 4. BACKTESTING & DASHBOARD ---
    subgraph Backtesting["Backtesting Engine"]
        Backtester["run_backtest_v4<br/>(Simulation)"]:::script
        Reporter["reporting.py<br/>(Dashboard Gen)"]:::script
        
        Backtester -->|Simulate| StratLogic
        Backtester -->|Read| HistData
        Backtester -->|Generate| BTTrades[("backtest_trades.csv")]:::data
        Backtester -->|Call| Reporter
        Reporter -->|Output| Dashboard[("dashboard.html")]:::output
    end

    %% --- 5. VERIFICATION ---
    subgraph Verification["Verification Suite"]
        Comparator["compare_live_vs_backtest.py"]:::script
        Plotter["plot_comparison.py"]:::script
        
        Comparator -->|Read| LiveTradesCSV
        Comparator -->|Read| LiveDataCSV
        Comparator -->|Read| HistData
        
        Comparator -->|Re-Run Logic| StratLogic
        Comparator -- "Compare" --> BTTrades
        
        Comparator -->|Generate| CompReport[("comparison_result.txt")]:::output
        Comparator -->|Call| Plotter
        Plotter -->|Generate| OverlayCharts[("comparison_charts/*.html")]:::output
    end

    %% Key Relationships
    LiveParams -.->|Defines Behavior| IBLive
    LiveParams -.->|Defines Behavior| Backtester
    LiveTradesCSV -.->|Source of Truth| Comparator
```

## Component Descriptions

1.  **Shared Strategy Core (`bollinger_strategy`):** The "Brain". Contains the exact logic for Entry, Exit, Filters, and Indicators. It is imported by GA, Backtester, and Live Script to ensure logic parity.
2.  **Optimization Engine (`ga_runner_v4`):** Evolves parameters against historical data to find the best configuration, saving it to `live_params.csv`.
3.  **Live Execution (`ib_deployment_v4`):** Runs the strategy in real-time. It reads `live_params.csv`, connects to IBKR, and executes trades. It logs every tick to `live_data.csv` and every trade to `live_trades.csv` (in Eastern Time).
4.  **Verification Suite (`compare_live_vs_backtest`):** The "Auditor". It takes the logs from the Live session and acts as a forensic tool. It re-runs the Backtester using the exact Live Data and Parameters to verify that the code did exactly what it was supposed to do. It produces text reports and visual **Overlay Charts**.
