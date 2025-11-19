#!/usr/bin/env python3
# Genetic Optimization for Bollinger Band Strategy - Version 1.32
# =============================================================
# FINAL PRODUCTION SCRIPT
#   • Prints the exact CSV used
#   • All diagnostics → ga_diagnostics/
#   • Scalar fitness + IRONCLAD min-trades
#   • Enforces TARGET_TRADES_DAY=4, MIN_TRADES_DAY=2
#   • Optimizable Trailing Delay (bars) to control quick wins via TP
# =============================================================

import os, warnings, ast, random
import pandas as pd, numpy as np, matplotlib.pyplot as plt
from datetime import time
from deap import base, creator, tools, algorithms

warnings.filterwarnings("ignore")

# ----------------------------------------------------------------------
# CSV INPUT / OUTPUT
# ----------------------------------------------------------------------
PARAM_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_v1.12.csv'
OUTPUT_CSV = 'Bollinger/parameters/BB_Strategy_Parameters_optimized.csv'
TRADES_OOS_CSV = 'Bollinger/output/trades_oos.csv'
TRADES_IS_CSV = 'Bollinger/output/trades_is.csv'
DIAG_DIR = 'ga_diagnostics'
os.makedirs(DIAG_DIR, exist_ok=True)

# ----------------------------------------------------------------------
# Load CSV → dict + DataFrame
# ----------------------------------------------------------------------
def load_params(csv_path):
    df = pd.read_csv(csv_path)
    d = {}
    for _, r in df.iterrows():
        name, val, mn, mx, typ = r['Name'], r['Value'], r['Min'], r['Max'], r['Type']
        if pd.notna(typ):
            if typ == 'int':
                val = int(val); mn = int(mn) if pd.notna(mn) else None; mx = int(mx) if pd.notna(mx) else None
            elif typ == 'float':
                val = float(val); mn = float(mn) if pd.notna(mn) else None; mx = float(mx) if pd.notna(mx) else None
            elif typ == 'bool':
                val = ast.literal_eval(val.capitalize())
                mn = ast.literal_eval(mn.capitalize()) if pd.notna(mn) else None
                mx = ast.literal_eval(mx.capitalize()) if pd.notna(mx) else None
        d[name] = {'value': val, 'min': mn, 'max': mx, 'type': typ}
    return d, df

param_dict, param_df = load_params(PARAM_CSV)

# ----------------------------------------------------------------------
# Print the exact parameter file that will be used
# ----------------------------------------------------------------------
print("\n=== PARAMETER FILE USED (exact copy) ===")
print(param_df.to_string(index=False))
print("========================================\n")

# ----------------------------------------------------------------------
# GA configuration
# ----------------------------------------------------------------------
POP_SIZE = param_dict.get('POP_SIZE', {'value': 20})['value']
NUM_GEN  = param_dict.get('NUM_GEN',  {'value': 10})['value']
CX_PB    = param_dict.get('CX_PB',    {'value': 0.7})['value']
MUT_PB   = param_dict.get('MUT_PB',   {'value': 0.2})['value']
MUT_MU   = param_dict.get('MUT_MU',   {'value': 0.0})['value']
MUT_SIGMA= param_dict.get('MUT_SIGMA',{'value': 0.1})['value']
TARGET_TRADES_DAY = param_dict.get('TARGET_TRADES_DAY', {'value': 2})['value']
TRADES_PENALTY_WEIGHT = param_dict.get('TRADES_PENALTY_WEIGHT', {'value': 0.5})['value']
DD_WEIGHT = param_dict.get('DD_WEIGHT', {'value': 0.3})['value']
DATA_SPLITS = param_dict.get('DATA_SPLITS', {'value': 0.7})['value']
DATA_SIZE = param_dict.get('DATA_SIZE', {'value': 100000})['value']
MIN_TRADES_DAY = param_dict.get('MIN_TRADES_DAY', {'value': 1.0})['value']
MIN_TRADES_PEN_WEIGHT = param_dict.get('MIN_TRADES_PEN_WEIGHT', {'value': -100.0})['value']

# NEW: trailing delay from CSV
TRAILING_DELAY = param_dict.get('Trailing Delay (bars)', {'value': 5})['value']

# ----------------------------------------------------------------------
# Numeric ranges for the GA
# ----------------------------------------------------------------------
PARAM_RANGES = {n: (d['min'], d['max']) for n, d in param_dict.items()
                if d['type'] in ('int', 'float') and d['min'] is not None and d['max'] is not None}

# ----------------------------------------------------------------------
# Back-tester (v1.22) – receives clamped/cast params
# ----------------------------------------------------------------------
def run_backtest(params, df, suppress_output=True):
    if len(df) == 0:
        return {'sharpe':0, 'max_drawdown':0, 'avg_trades_day':0, 'profit_factor':0,
                'trades_df':pd.DataFrame()}

    # ---- fixed (non-optimised) params from CSV ----
    max_open_trades = int(param_dict['Max Open Trades']['value'])
    enable_long = param_dict['Enable Long Trades']['value']
    enable_short = param_dict['Enable Short Trades']['value']
    long_wick_touch = param_dict['Long Entry on Wick Touch']['value']
    long_body_zone = param_dict['Long Entry on Body in Zone']['value']
    long_trigger_pct = param_dict['Long Trigger (% From Lower Band)']['value']
    short_wick_touch = param_dict['Short Entry on Wick Touch']['value']
    short_body_zone = param_dict['Short Entry on Body in Zone']['value']
    short_trigger_pct = param_dict['Short Trigger (% From Upper Band)']['value']
    initial_sl_pct = param_dict['Initial Stop Loss (%)']['value']
    enable_trailing = param_dict['Enable Trailing Stop']['value']
    atr_length_ts = param_dict['ATR Length for Trailing Stop']['value']
    opposite_bb_tp = param_dict['Opposite Bollinger Band TP']['value']
    fixed_atr_tp = param_dict['Fixed ATR TP']['value']
    fixed_bb_entry_tp = param_dict['Fixed BB at Entry TP']['value']
    atr_length_tp = param_dict['ATR Length for TP']['value']
    atr_mult_tp = param_dict['ATR Multiplier for TP']['value']
    min_atr_points = param_dict['Min ATR Filter (Points)']['value']
    enable_rth_filter = param_dict['Enable RTH Filter']['value']
    rth_start_str = param_dict['RTH Start (HH:MM)']['value']
    rth_end_str = param_dict['RTH End (HH:MM)']['value']

    # ---- optimisable params (clamped & cast) ----
    bb_length = max(1, int(params.get('Bollinger Band Length',
                                      param_dict['Bollinger Band Length']['value'])))
    bb_stddev = float(params.get('Bollinger Band StdDev',
                                 param_dict['Bollinger Band StdDev']['value']))
    atr_mult_ts = float(params.get('ATR Multiplier for Trailing Stop',
                                   param_dict['ATR Multiplier for Trailing Stop']['value']))
    min_volume_multiplier = float(params.get('Min Volume Multiplier',
                                             param_dict['Min Volume Multiplier']['value']))
    timeframe = max(1, int(params.get('Timeframe (minutes)',
                                      param_dict['Timeframe (minutes)']['value'])))
    # NEW: trailing delay from params (optimizable)
    trailing_delay = max(0, int(params.get('Trailing Delay (bars)',
                                           param_dict['Trailing Delay (bars)']['value'])))

    # ---- RTH parsing ----
    def parse_time(s): 
        try: return pd.to_datetime(s, format='%H:%M').time()
        except: return time(9,30)
    rth_start, rth_end = parse_time(rth_start_str), parse_time(rth_end_str)

    # ---- Resample (if needed) ----
    if timeframe > 1:
        df = df.resample(f'{timeframe}T').agg({
            'open':'first','high':'max','low':'min','close':'last','volume':'sum'
        }).dropna()
        if len(df) == 0:
            return {'sharpe':0,'max_drawdown':0,'avg_trades_day':0,'profit_factor':0,
                    'trades_df':pd.DataFrame()}

    # ---- Indicators ----
    df['mid']   = df['close'].rolling(bb_length).mean()
    df['std']   = df['close'].rolling(bb_length).std()
    df['upper'] = df['mid'] + df['std']*bb_stddev
    df['lower'] = df['mid'] - df['std']*bb_stddev

    tr = np.maximum.reduce([df['high']-df['low'],
                            (df['high']-df['close'].shift()).abs(),
                            (df['low']-df['close'].shift()).abs()])
    df['atr_ts'] = pd.Series(tr, index=df.index).rolling(atr_length_ts).mean()
    if fixed_atr_tp:
        df['atr_tp'] = pd.Series(tr, index=df.index).rolling(atr_length_tp).mean()

    # ---- Filters ----
    df['avg_volume'] = df['volume'].rolling(50).mean()
    df['volume_filter'] = df['volume'] >= df['avg_volume']*min_volume_multiplier
    df['atr_filter']    = df['atr_ts'] >= min_atr_points
    df['in_rth'] = pd.Series([t.time() for t in df.index], index=df.index)\
                    .between(rth_start, rth_end) if enable_rth_filter else True
    df.dropna(inplace=True)
    if len(df) == 0:
        return {'sharpe':0,'max_drawdown':0,'avg_trades_day':0,'profit_factor':0,
                'trades_df':pd.DataFrame()}

    # ---- Simulation (itertuples for speed) ----
    positions, trades = [], []
    for row in df.itertuples():
        idx, high, low, close = row.Index, row.high, row.low, row.close
        atr_ts, upper, lower = row.atr_ts, row.upper, row.lower
        in_rth = row.in_rth; atr_f = row.atr_filter; vol_f = row.volume_filter

        # ---- exits ----
        for pos in positions[:]:
            dir_ = pos['direction']
            if dir_ == 1: pos['max_high'] = max(pos['max_high'], high)
            else:         pos['min_low']  = min(pos['min_low'], low)

            # Increment bars_held
            pos['bars_held'] = pos.get('bars_held', 0) + 1

            # Trailing stop (only after delay)
            if enable_trailing and pos['bars_held'] >= trailing_delay:
                atr = atr_ts
                if dir_ == 1:
                    new_stop = pos['max_high'] - atr * atr_mult_ts
                    pos['stop'] = max(pos['stop'], new_stop)
                else:
                    new_stop = pos['min_low'] + atr * atr_mult_ts
                    pos['stop'] = min(pos['stop'], new_stop)

            cand = []
            if dir_ == 1 and low  <= pos['stop']: cand.append(('Stop', pos['stop']))
            if dir_ ==-1 and high >= pos['stop']: cand.append(('Stop', pos['stop']))
            if opposite_bb_tp:
                if dir_ == 1 and high >= upper: cand.append(('TP Opp BB', upper))
                if dir_ ==-1 and low  <= lower: cand.append(('TP Opp BB', lower))
            if fixed_atr_tp and pos['tp'] is not None:
                if dir_ == 1 and high >= pos['tp']: cand.append(('TP ATR', pos['tp']))
                if dir_ ==-1 and low  <= pos['tp']: cand.append(('TP ATR', pos['tp']))
            if fixed_bb_entry_tp and pos['tp'] is not None:
                if dir_ == 1 and high >= pos['tp']: cand.append(('TP BB', pos['tp']))
                if dir_ ==-1 and low  <= pos['tp']: cand.append(('TP BB', pos['tp']))
            if cand:
                cand.sort(key=lambda x: abs(x[1]-pos['entry_price']))
                reason, price = cand[0]
                pnl = (price-pos['entry_price'])*dir_*50
                trades.append(pos | {'exit_time':idx,'exit_price':price,'pnl':pnl,'reason':reason})
                positions.remove(pos)

        if len(positions) >= max_open_trades or not (in_rth and atr_f and vol_f):
            continue

        # ---- entries ----
        enter_long = enter_short = False
        if enable_long:
            trig = lower * (1 - long_trigger_pct/100)
            if (long_wick_touch and low  <= trig) or (long_body_zone and close <= trig):
                enter_long = True
        if enable_short:
            trig = upper * (1 + short_trigger_pct/100)
            if (short_wick_touch and high >= trig) or (short_body_zone and close >= trig):
                enter_short = True

        if enter_long or enter_short:
            direction = 1 if enter_long else -1
            entry = close
            stop  = entry * (1 - direction * initial_sl_pct / 100)
            tp = None
            if fixed_atr_tp and 'atr_tp' in df.columns:
                atr_val = row.atr_tp
                if not pd.isna(atr_val):
                    tp = entry + direction * atr_val * atr_mult_tp
            elif fixed_bb_entry_tp:
                tp = upper if direction==1 else lower
            if enable_trailing:
                peak = high if direction==1 else low
                trail = peak - direction * atr_ts * atr_mult_ts
                stop = max(stop, trail) if direction==1 else min(stop, trail)
            positions.append({
                'entry_time':idx,'entry_price':entry,'direction':direction,
                'stop':stop,'tp':tp,
                'max_high':high if direction==1 else None,
                'min_low': low  if direction==-1 else None,
                'stop_history':[(idx,stop)],
                'bars_held': 0  # NEW: for trailing delay
            })

    # ---- final close ----
    for pos in positions:
        price = df.iloc[-1]['close']
        pnl = (price-pos['entry_price'])*pos['direction']*50
        trades.append(pos | {'exit_time':df.index[-1],'exit_price':price,'pnl':pnl,'reason':'EOD'})

    # ---- metrics ----
    trades_df = pd.DataFrame(trades)
    if trades_df.empty:
        return {'sharpe':0,'max_drawdown':0,'avg_trades_day':0,'profit_factor':0,
                'trades_df':trades_df}

    # daily equity (fill zero-PNL days)
    min_d = trades_df['exit_time'].min().date()
    max_d = trades_df['exit_time'].max().date()
    daily_pnl = trades_df.groupby(trades_df['exit_time'].dt.date)['pnl'].sum()\
                         .reindex(pd.date_range(min_d, max_d), fill_value=0)
    equity = 50000 + daily_pnl.cumsum()
    rets   = equity.pct_change().dropna()
    sharpe = 0.0 if len(rets) < 2 else (rets.mean()/rets.std()*np.sqrt(252)) if rets.std()!=0 else 0.0

    peak = 50000; dd = 0
    for p in equity:
        if p > peak: peak = p
        else: dd = max(dd, peak-p)

    days = (trades_df['exit_time'].max() - trades_df['entry_time'].min()).days or 1
    avg_trades_day = len(trades_df)/days

    # ---- profit_factor ----
    avg_win = trades_df[trades_df['pnl'] > 0]['pnl'].mean() if (trades_df['pnl'] > 0).any() else 0
    avg_loss = trades_df[trades_df['pnl'] < 0]['pnl'].mean() if (trades_df['pnl'] < 0).any() else 0
    profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    return {'sharpe':sharpe,'max_drawdown':dd,'avg_trades_day':avg_trades_day,'profit_factor':profit_factor,
            'trades_df':trades_df}

# ----------------------------------------------------------------------
# GA plumbing
# ----------------------------------------------------------------------
creator.create("FitnessMax", base.Fitness, weights=(1.0,))
creator.create("Individual", list, fitness=creator.FitnessMax)

param_keys = list(PARAM_RANGES.keys())

def create_individual():
    return creator.Individual(random.uniform(lo, hi) for lo, hi in PARAM_RANGES.values())

def custom_mutate(ind):
    tools.mutGaussian(ind, mu=MUT_MU, sigma=MUT_SIGMA, indpb=0.2)
    for i, (lo, hi) in enumerate(PARAM_RANGES.values()):
        ind[i] = max(lo, min(ind[i], hi))
    return ind,

def evaluate_scalar(ind_and_df):
    ind, df = ind_and_df
    params = dict(zip(param_keys, ind))
    # Clamp & cast
    for n, v in params.items():
        mn, mx, typ = param_dict[n]['min'], param_dict[n]['max'], param_dict[n]['type']
        v = max(mn, min(v, mx))
        params[n] = int(v) if typ=='int' else float(v)

    # Clamp timeframe to >=1
    params['Timeframe (minutes)'] = max(1, int(params.get('Timeframe (minutes)', 
                                                         param_dict['Timeframe (minutes)']['value'])))

    metrics = run_backtest(params, df, suppress_output=True)

    excess_pen = max(0.0, metrics['avg_trades_day'] - TARGET_TRADES_DAY)
    low_pen = max(0.0, MIN_TRADES_DAY - metrics['avg_trades_day'])

    fitness = (
        metrics['sharpe'] * 2.0
        - metrics['max_drawdown'] * 0.2
        - excess_pen * 0.2
        + metrics['profit_factor'] * 1.0
        - low_pen * 100.0   # ZERO TRADES = -100 → DEAD
    )
    return (fitness,)

toolbox = base.Toolbox()
toolbox.register("individual", create_individual)
toolbox.register("population", tools.initRepeat, list, toolbox.individual)
toolbox.register("evaluate", evaluate_scalar)
toolbox.register("mate", tools.cxBlend, alpha=0.5)
toolbox.register("mutate", custom_mutate)
toolbox.register("select", tools.selTournament, tournsize=3)

# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
def main():
    print("# Genetic Optimization for Bollinger Band Strategy - Version 1.31")
    print("# Timestamp: November 11, 2025")
    toolbox.register("map", map)

    DATA_CSV = 'Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv'
    df = pd.read_csv(DATA_CSV, header=None,
                     names=['datetime','open','high','low','close','volume'],
                     parse_dates=['datetime'], index_col='datetime')
    if DATA_SIZE > 0:
        df = df.tail(DATA_SIZE)
    split = int(len(df)*DATA_SPLITS)
    in_sample, oos = df.iloc[:split], df.iloc[split:]

    pop = toolbox.population(n=POP_SIZE)
    hof = tools.HallOfFame(1)
    stats = tools.Statistics(lambda i: i.fitness.values[0])
    stats.register("avg", np.mean)
    stats.register("min", np.min)
    stats.register("max", np.max)
    logbook = tools.Logbook()
    logbook.header = "gen", "evals", "avg", "min", "max"

    print(logbook.header)

    for gen in range(NUM_GEN):
        offspring = algorithms.varAnd(pop, toolbox, CX_PB, MUT_PB)
        fits = toolbox.map(toolbox.evaluate, [(ind, in_sample) for ind in offspring])
        for fit, ind in zip(fits, offspring):
            ind.fitness.values = fit
        pop = toolbox.select(offspring, len(pop))
        hof.update(pop)
        record = stats.compile(pop)
        logbook.record(gen=gen, evals=len(pop), **record)
        print(f"{gen}\t{len(pop)}\t{round(record['avg'],4)}\t{round(record['min'],4)}\t{round(record['max'],4)}")

    best = hof[0]
    best_params = dict(zip(param_keys, best))
    print("\n=== BEST INDIVIDUAL ===")
    print({k: round(v,4) if isinstance(v,float) else v for k,v in best_params.items()})

    # ------------------------------------------------------------------
    # In-sample & OOS validation
    # ------------------------------------------------------------------
    is_res = run_backtest(best_params, in_sample, suppress_output=False)
    trades_is = is_res.pop('trades_df')
    trades_is.to_csv(TRADES_IS_CSV, index=False)

    oos_res = run_backtest(best_params, oos, suppress_output=False)
    trades_oos = oos_res.pop('trades_df')
    trades_oos.to_csv(TRADES_OOS_CSV, index=False)

    print("\n=== In-Sample vs OOS Comparison ===")
    comp = pd.DataFrame([is_res, oos_res], index=['In-Sample', 'OOS'])
    print(comp)

    for label, trades in [('In-Sample', trades_is), ('OOS', trades_oos)]:
        if not trades.empty:
            total_pnl = trades['pnl'].sum()
            win_rate = (trades['pnl']>0).mean()*100
            pf = abs(trades[trades['pnl']>0]['pnl'].sum() /
                     trades[trades['pnl']<0]['pnl'].sum()) if (trades['pnl']<0).any() else np.inf
            calmar = total_pnl / comp.loc[label, 'max_drawdown'] if comp.loc[label, 'max_drawdown'] else np.inf
            print(f"{label}: PNL={total_pnl:,.0f} | Win%={win_rate:.1f} | PF={pf:.2f} | Calmar={calmar:.2f}")

    # ------------------------------------------------------------------
    # DIAGNOSTIC PLOTS → ga_diagnostics/
    # ------------------------------------------------------------------
    plt.figure(figsize=(8,4))
    plt.plot(logbook.select("gen"), logbook.select("avg"), label='Avg')
    plt.plot(logbook.select("gen"), logbook.select("max"), label='Best')
    plt.title('GA Convergence – Scalar Fitness')
    plt.xlabel('Generation'); plt.ylabel('Fitness')
    plt.legend(); plt.grid(); plt.tight_layout()
    plt.savefig(f'{DIAG_DIR}/convergence_fitness.png'); plt.close()
    print(f"Plot → {DIAG_DIR}/convergence_fitness.png")

    # Parameter evolution
    os.makedirs(f'{DIAG_DIR}/param_evolution', exist_ok=True)
    for i, pname in enumerate(param_keys):
        vals = [ind[i] for ind in hof]
        plt.figure(figsize=(6,3))
        plt.plot(range(len(vals)), vals, marker='.')
        plt.title(f'Best {pname}')
        plt.xlabel('Generation'); plt.ylabel(pname)
        plt.grid(); plt.tight_layout()
        plt.savefig(f'{DIAG_DIR}/param_evolution/{pname.replace(" ","_")}.png')
        plt.close()
    print(f"Parameter-evolution plots → {DIAG_DIR}/param_evolution/")

    # OOS trade-level plots
    if not trades_oos.empty:
        plt.figure(figsize=(8,4)); trades_oos['pnl'].hist(bins=20); plt.title('OOS PNL Histogram')
        plt.xlabel('PNL'); plt.ylabel('Count'); plt.grid(); plt.tight_layout()
        plt.savefig(f'{DIAG_DIR}/oos_pnl_hist.png'); plt.close()
        print(f"Plot → {DIAG_DIR}/oos_pnl_hist.png")

        plt.figure(figsize=(8,4))
        plt.scatter(trades_oos.index, trades_oos['pnl'], c=np.where(trades_oos['pnl']>0,'g','r'))
        plt.title('OOS Wins (Green) / Losses (Red)'); plt.ylabel('PNL')
        plt.grid(); plt.tight_layout()
        plt.savefig(f'{DIAG_DIR}/oos_win_loss.png'); plt.close()
        print(f"Plot → {DIAG_DIR}/oos_win_loss.png")

        trades_oos['duration'] = (trades_oos['exit_time']-trades_oos['entry_time']).dt.total_seconds()/60
        plt.figure(figsize=(8,4)); trades_oos['duration'].hist(bins=20)
        plt.title('OOS Trade Duration (min)'); plt.xlabel('Minutes'); plt.ylabel('Count')
        plt.grid(); plt.tight_layout()
        plt.savefig(f'{DIAG_DIR}/oos_trade_duration.png'); plt.close()
        print(f"Plot → {DIAG_DIR}/oos_trade_duration.png")

        equity = 50000 + trades_oos.groupby(trades_oos['exit_time'].dt.date)['pnl'].sum().cumsum()
        plt.figure(figsize=(10,4)); equity.plot()
        plt.title('OOS Equity Curve'); plt.ylabel('Equity'); plt.grid(); plt.tight_layout()
        plt.savefig(f'{DIAG_DIR}/oos_equity.png'); plt.close()
        print(f"OOS equity → {DIAG_DIR}/oos_equity.png")
        if len(set(equity)) == 1:
            print("OOS equity is suspicious (straight line) - no trades or zero variation")

    # ------------------------------------------------------------------
    # Write optimized CSV
    # ------------------------------------------------------------------
    for name, val in best_params.items():
        idx = param_df[param_df['Name']==name].index[0]
        typ = param_dict[name]['type']
        param_df.at[idx, 'Value'] = int(val) if typ=='int' else round(val,4)
    param_df.to_csv(OUTPUT_CSV, index=False)
    print(f"Optimized CSV → {OUTPUT_CSV}")

if __name__ == "__main__":
    main()

