#!/usr/bin/env python3
from __future__ import annotations
import os
os.environ.setdefault("STRATEGY", "trend")
import csv,statistics,sys,re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
NEW=Path('C:/Trading/Trend/parameters/genetic_results_2026-06-21-1.csv')
OLD=Path('C:/Trading/Trend/parameters/genetic_results_2026-06-20-1.csv')
B=[('lt22',lambda x:x.__lt__(22)),('22-59',lambda x:(not x.__lt__(22)) and x.__lt__(60)),('60-119',lambda x:(not x.__lt__(60)) and x.__lt__(120)),('120-239',lambda x:(not x.__lt__(120)) and x.__lt__(240)),('240p',lambda x:not x.__lt__(240))]
def rk(by,nd,prefer=None):
 c=[k for k in by if nd in k]
 if prefer:
  for k in c:
   if prefer in k: return k
 return c[0] if c else None
def pm(s):
 if s is None or not str(s).strip(): return None
 t=''.join(c for c in str(s).strip() if c.isdigit() or c in '.-')
 return float(t) if t else None
def pf(s):
 if s is None or not str(s).strip(): return None
 try: return float(''.join(c for c in str(s).strip() if c.isdigit() or c in '.-'))
 except ValueError: return None
def pp(s):
 if s is None or not str(s).strip(): return None
 try: return float(''.join(c for c in str(s).strip() if c.isdigit() or c in '.-'))
 except ValueError: return None
def ps(s):
 if s is None or not str(s).strip(): return None
 t=str(s).strip()
 if '/' in t:
  try: return int(t.split('/')[0])
  except ValueError: return None
 try: return int(float(t))
 except ValueError: return None
def load(p):
 with p.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
 cols=[c for c in rows[0] if c.startswith('Solution_')]
 by={r['Name']:r for r in rows if r.get('Name')}
 return rows,cols,by
@dataclass
class S:
 col:str
 is_sortino=None;oos_pnl=None;oos_pf=None;oos_atd=None;oos_span=None;robustness=None;deg=None;pos_splits=None
 trail_delay=None;timeframe=None;buy_lb=None;sell_lb=None;tp_atr=None;trail_atr=None
 ce_sell_lb=None;ce_buy_lb=None;ce_atr_offset=None
def ex(by,cols):
 K=dict(is_sortino=rk(by,'Aggregate IS Sortino'),oos_pnl=rk(by,'Total Profit',prefer='OOS aggregate'),oos_pf=rk(by,'Profit Factor',prefer='OOS'),oos_atd=rk(by,'Avg Trades/Day',prefer='OOS'),oos_span=rk(by,'Avg Trade Span',prefer='OOS aggregate'),rob=rk(by,'Live-Ready Robustness Score'),deg=rk(by,'Sortino IS-to-OOS Degradation'),pos=rk(by,'Positive OOS Splits'),delay=rk(by,'Trailing Delay (bars)'),tf=rk(by,'Timeframe (minutes)'),buy=rk(by,'Buy Lookback (minutes)'),sell=rk(by,'Sell Lookback (minutes)'),ce_sell=rk(by,'Channel Exit Sell Lookback (bars)'),ce_buy=rk(by,'Channel Exit Buy Lookback (bars)'),ce_off=rk(by,'Channel Exit ATR Offset'),tp=rk(by,'Take Profit ATR Multiplier'),trail=rk(by,'ATR Multiplier for Trailing Stop'))
 out=[]
 for c in cols:
  s=S(c)
  s.is_sortino=pf(by.get(K['is_sortino'],{}).get(c)); s.oos_pnl=pm(by.get(K['oos_pnl'],{}).get(c)); s.oos_pf=pf(by.get(K['oos_pf'],{}).get(c)); s.oos_atd=pf(by.get(K['oos_atd'],{}).get(c)); s.oos_span=pf(by.get(K['oos_span'],{}).get(c)); s.robustness=pf(by.get(K['rob'],{}).get(c)); s.deg=pp(by.get(K['deg'],{}).get(c)); s.pos_splits=ps(by.get(K['pos'],{}).get(c)); s.trail_delay=pf(by.get(K['delay'],{}).get(c)); s.timeframe=pf(by.get(K['tf'],{}).get(c)); s.buy_lb=pf(by.get(K['buy'],{}).get(c)); s.sell_lb=pf(by.get(K['sell'],{}).get(c)); s.ce_sell_lb=pf(by.get(K['ce_sell'],{}).get(c)); s.ce_buy_lb=pf(by.get(K['ce_buy'],{}).get(c)); s.ce_atr_offset=pf(by.get(K['ce_off'],{}).get(c)); s.tp_atr=pf(by.get(K['tp'],{}).get(c)); s.trail_atr=pf(by.get(K['trail'],{}).get(c)); out.append(s)
 return out
def agg(v):
 if not v: return None,None
 return statistics.mean(v),statistics.median(v)
def fn(x,money=False):
 if x is None: return 'n/a'
 if money: return (chr(36)+format(x,',.2f'))
 if abs(x-round(x))<1e-9: return str(int(round(x)))
 return f'{x:.4f}'
def hdr(t):
 print(); print('='*len(t)); print(t); print('='*len(t))
def cmp_tpl(orows,nrows):
 hdr('4. Template Min / Max / Value differences (OLD vs NEW)')
 ob={r['Name']:r for r in orows if r.get('Name')}; nb={r['Name']:r for r in nrows if r.get('Name')}
 dif=[]
 for name in sorted(set(ob)|set(nb)):
  o,n=ob.get(name),nb.get(name)
  if o is None: dif.append((name,'missing OLD',n.get('Value'),n.get('Min'),n.get('Max'))); continue
  if n is None: dif.append((name,'missing NEW',o.get('Value'),o.get('Min'),o.get('Max'))); continue
  for field in ('Value','Min','Max'):
   ov=(o.get(field) or '').strip(); nv=(n.get(field) or '').strip()
   if ov!=nv: dif.append((name,field,ov,nv))
 if not dif: print('No Value/Min/Max differences on shared template rows.')
 else:
  print(f'{'Name':<55} {'Field':<12} OLD -> NEW'); print('-'*100)
  for item in dif:
   if item[1].startswith('missing'): print(f'{item[0]:<55} {item[1]:<12} template Value={item[2]!r} Min={item[3]!r} Max={item[4]!r}')
   else: print(f'{item[0]:<55} {item[1]:<12} {item[2]!r} -> {item[3]!r}')
 print(f'\nTotal differing template fields: {len(dif)}')
def agg_metrics(label, sols):
    print(f"\n--- {label} ---")
    print(f"Solutions parsed: {len(sols)}")
    specs = [
        ("is_sortino", lambda s: s.is_sortino),
        ("oos_pnl", lambda s: s.oos_pnl),
        ("oos_pf", lambda s: s.oos_pf),
        ("oos_atd", lambda s: s.oos_atd),
        ("oos_span", lambda s: s.oos_span),
        ("robustness", lambda s: s.robustness),
        ("deg", lambda s: s.deg),
        ("pos_splits", lambda s: float(s.pos_splits) if s.pos_splits is not None else None),
    ]
    for nm, g in specs:
        vals = [g(s) for s in sols if g(s) is not None]
        m, med = agg(vals)
        print(f"  {nm:12} n={len(vals):5} mean={fn(m, money=(nm=='oos_pnl')):>14} median={fn(med, money=(nm=='oos_pnl')):>14}")

def trail(label, sols):
    print(f"\n--- Trailing delay (bars) - {label} ---")
    counts = Counter(int(s.trail_delay) for s in sols if s.trail_delay is not None)
    total = sum(counts.values())
    if not total:
        print("  (no data)")
        return
    for d in sorted(counts):
        print(f"  delay {d:3d}: {counts[d]:5d} ({100.0 * counts[d] / total:5.1f}%)")

def spanb(label, sols):
    print(f"\n--- OOS span bucket % - {label} ---")
    spans = [s.oos_span for s in sols if s.oos_span is not None]
    total = len(spans)
    if not total:
        print("  (no data)")
        return
    for name, fnb in B:
        c = sum(1 for x in spans if fnb(x))
        print(f"  {name:8}: {c:5d} ({100.0 * c / total:5.1f}%)")

def ok(s):
    return (
        s.robustness is not None and s.robustness >= 98
        and s.pos_splits is not None and s.pos_splits >= 4
        and s.deg is not None and s.deg <= 15
        and s.oos_pnl is not None and s.oos_pnl >= 400000
        and s.oos_span is not None and s.oos_span >= 22
    )

def line(s):
    return (
        f"{s.col}: oos_pnl={fn(s.oos_pnl, money=True)} rob={fn(s.robustness)} "
        f"pos={s.pos_splits if s.pos_splits is not None else 'n/a'} deg={fn(s.deg)} "
        f"span={fn(s.oos_span)} pf={fn(s.oos_pf)} atd={fn(s.oos_atd)} "
        f"ce_sell={fn(s.ce_sell_lb)} ce_buy={fn(s.ce_buy_lb)} ce_off={fn(s.ce_atr_offset)}"
    )

def corr(xs, ys):
    pairs=[(x,y) for x,y in zip(xs,ys) if x is not None and y is not None]
    if len(pairs)<3: return None
    n=len(pairs); mx=sum(a for a,_ in pairs)/n; my=sum(b for _,b in pairs)/n
    num=sum((a-mx)*(b-my) for a,b in pairs)
    den=(sum((a-mx)**2 for a,_ in pairs)*sum((b-my)**2 for _,b in pairs))**0.5
    return num/den if den else None

def channel_report(label, sols):
    hdr(f"Channel exit analysis - {label}")
    for attr,name in [('ce_sell_lb','CE Sell LB'),('ce_buy_lb','CE Buy LB'),('ce_atr_offset','CE ATR Offset')]:
        vals=[getattr(s,attr) for s in sols if getattr(s,attr) is not None]
        m,med=agg(vals)
        print(f"  {name:16} median={fn(med):>8} mean={fn(m):>8} min={fn(min(vals)) if vals else 'n/a':>8} max={fn(max(vals)) if vals else 'n/a':>8}")
    for attr,name in [('ce_sell_lb','CE Sell LB'),('ce_buy_lb','CE Buy LB'),('ce_atr_offset','CE ATR Offset')]:
        r=corr([getattr(s,attr) for s in sols],[s.oos_pnl for s in sols])
        print(f"  corr({name}, OOS PnL) = {r:+.3f}" if r is not None else f"  corr({name}, OOS PnL) = n/a")
    top=sorted(sols,key=lambda s:s.oos_pnl or -1e99,reverse=True)[:200]
    print("  Top-200 cluster:")
    for attr,name in [('ce_sell_lb','CE Sell LB'),('ce_buy_lb','CE Buy LB'),('ce_atr_offset','CE ATR Offset')]:
        vals=[getattr(s,attr) for s in top if getattr(s,attr) is not None]
        _,med=agg(vals)
        modes=Counter(int(v) if attr!='ce_atr_offset' else round(v,2) for v in vals)
        print(f"    {name:16} median={fn(med):>8} modes={modes.most_common(5)}")
    z=sum(1 for s in sols if s.ce_atr_offset==0)
    s6=sum(1 for s in sols if s.ce_sell_lb==6)
    print(f"  CE ATR Offset=0: {z}/{len(sols)} ({100*z/len(sols):.1f}%)")
    print(f"  CE Sell LB=6:    {s6}/{len(sols)} ({100*s6/len(sols):.1f}%)")

def deploy(label, sols):
    print(f"\n--- Deployment shortlist (rob>=98, pos>=4, deg<=15, oos_pnl>=400k, span>=22) - {label} ---")
    q = [s for s in sols if ok(s)]
    q.sort(key=lambda s: s.oos_pnl or -1e99, reverse=True)
    print(f"Qualified: {len(q)}")
    for s in q[:10]:
        print("  " + line(s))
    if not q:
        print("  (none)")

def top15(sols):
    hdr("9. Top 15 by OOS PnL - NEW (2026-06-16)")
    for s in sorted(sols, key=lambda s: s.oos_pnl or -1e99, reverse=True)[:15]:
        print(line(s))

def sel(label, by, col="Solution_0_SELECTED"):
    print(f"\n--- SELECTED row ({col}) - {label} ---")
    if col not in next(iter(by.values()), {}):
        print(f"  Column {col} not found.")
        return
    s = ex(by, [col])[0]
    print(f"  is_sortino   : {fn(s.is_sortino)}")
    print(f"  oos_pnl      : {fn(s.oos_pnl, money=True)}")
    print(f"  oos_pf       : {fn(s.oos_pf)}")
    print(f"  oos_atd      : {fn(s.oos_atd)}")
    print(f"  oos_span     : {fn(s.oos_span)}")
    print(f"  robustness   : {fn(s.robustness)}")
    print(f"  deg          : {fn(s.deg)}")
    print(f"  pos_splits   : {s.pos_splits}")
    print(f"  trail_delay  : {fn(s.trail_delay)}")
    print(f"  timeframe    : {fn(s.timeframe)}")
    print(f"  buy_lb       : {fn(s.buy_lb)}")
    print(f"  sell_lb      : {fn(s.sell_lb)}")
    print(f"  tp_atr       : {fn(s.tp_atr)}")
    print(f"  trail_atr    : {fn(s.trail_atr)}")

def cluster(old_s, new_s):
    hdr("11. Top-200 OOS PnL cluster comparison (OLD vs NEW)")

    def t200(sols):
        return sorted(sols, key=lambda s: s.oos_pnl or -1e99, reverse=True)[:200]

    o200, n200 = t200(old_s), t200(new_s)

    def summ(name, group):
        print(f"\n  [{name}] top-200 count={len(group)}")
        if not group:
            return
        pnls = [s.oos_pnl for s in group if s.oos_pnl is not None]
        m, med = agg(pnls)
        print(f"    oos_pnl mean={fn(m, money=True)} median={fn(med, money=True)}")
        for attr, lab in [
            ("robustness", "rob"), ("deg", "deg"), ("oos_span", "span"), ("trail_delay", "trail_delay"),
            ("timeframe", "timeframe"), ("buy_lb", "buy_lb"), ("sell_lb", "sell_lb"), ("tp_atr", "tp_atr"),
            ("trail_atr", "trail_atr"), ("oos_pf", "oos_pf"), ("is_sortino", "is_sortino"),
        ]:
            vals = [getattr(s, attr) for s in group if getattr(s, attr) is not None]
            m, med = agg(vals)
            print(f"    {lab:12} mean={fn(m):>10} median={fn(med):>10}")
        tf = Counter(int(s.timeframe) for s in group if s.timeframe is not None)
        dl = Counter(int(s.trail_delay) for s in group if s.trail_delay is not None)
        print(f"    timeframe modes: {tf.most_common(5)}")
        print(f"    trail_delay modes: {dl.most_common(5)}")

    summ("OLD", o200)
    summ("NEW", n200)
    print("\n  Delta (NEW top-200 median minus OLD top-200 median):")
    for attr, lab in [("oos_pnl", "oos_pnl"), ("robustness", "rob"), ("deg", "deg"), ("oos_span", "oos_span"), ("trail_delay", "trail_delay")]:
        ov = [getattr(s, attr) for s in o200 if getattr(s, attr) is not None]
        nv = [getattr(s, attr) for s in n200 if getattr(s, attr) is not None]
        _, om = agg(ov)
        _, nm = agg(nv)
        if om is None or nm is None:
            print(f"    {lab}: n/a")
        else:
            print(f"    {lab}: {nm - om:+.4f}" + (" (money)" if attr == "oos_pnl" else ""))

def best(label, sols):
    print(f"\n--- Best OOS PnL and best robustness - {label} ---")
    bp = max(sols, key=lambda s: s.oos_pnl or -1e99)
    br = max(sols, key=lambda s: s.robustness or -1e99)
    print("  Best OOS PnL:")
    print("    " + line(bp))
    print("  Best robustness:")
    print("    " + line(br))

def _param_dict_from_ga(path):
    import pandas as pd
    df = pd.read_csv(path)
    d = {}
    for _, r in df.iterrows():
        name = r.get("Name")
        if pd.isna(name):
            continue
        name = str(name).strip()
        if not name or name.startswith("===") or name.startswith("---"):
            continue
        typ = r.get("Type")
        if typ not in ("int", "float", "bool"):
            continue
        try:
            val = r.get("Value")
            mn = float(r["Min"]) if pd.notna(r.get("Min")) else None
            mx = float(r["Max"]) if pd.notna(r.get("Max")) else None
        except Exception:
            continue
        if typ == "int":
            val = int(float(val)) if pd.notna(val) else None
            mn = int(mn) if mn is not None else None
            mx = int(mx) if mx is not None else None
        elif typ == "float":
            val = float(val) if pd.notna(val) else None
        elif typ == "bool":
            val = str(val).lower() == "true" if pd.notna(val) else None
        d[name] = {"value": val, "min": mn, "max": mx, "type": typ}
    return d


def trailing_ab(sol_col="Solution_522"):
    import sys
    from pathlib import Path
    import pandas as pd

    root = Path("C:/Trading")
    sys.path.insert(0, str(root))
    os.environ["STRATEGY"] = "trend"
    from optimize import run_backtest, finalize_ga_solution_params

    ga = NEW
    df = pd.read_csv(ga)
    param_dict = _param_dict_from_ga(NEW)
    param_dict["strategy_name"] = "trend"
    raw = {}
    for _, row in df.iterrows():
        n = row.get("Name")
        if pd.isna(n):
            continue
        n = str(n).strip()
        if n.startswith("===") or "__" in n:
            continue
        v = row.get(sol_col)
        if pd.isna(v) or v == "":
            continue
        if n not in param_dict:
            continue
        meta = param_dict[n]
        if meta["type"] == "int":
            raw[n] = int(float(v))
        elif meta["type"] == "float":
            raw[n] = float(v)
        elif meta["type"] == "bool":
            raw[n] = str(v).lower() in ("true", "1")
        else:
            raw[n] = v

    base = finalize_ga_solution_params(raw, param_dict)
    off = finalize_ga_solution_params(dict(base), param_dict)
    on = finalize_ga_solution_params({**base, "Enable Trailing Stop": 1}, param_dict)

    data = root / "Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv"
    d = pd.read_csv(data, parse_dates=True, index_col=0)
    d.columns = [str(c).lower().strip() for c in d.columns]
    if not all(c in d.columns for c in ["open", "high", "low", "close", "volume"]):
        d = pd.read_csv(data, header=None, parse_dates=True, index_col=0)
        d.columns = ["open", "high", "low", "close", "volume"]
    d = d[["open", "high", "low", "close", "volume"]].dropna().loc["2020-01-02":"2025-10-10"]

    def one(p, label):
        r = run_backtest(p, d, param_dict, suppress_output=True)
        tr = r.get("trades_df")
        pnl = float(tr.pnl.sum()) if tr is not None and not tr.empty else 0.0
        n = len(tr) if tr is not None else 0
        reasons = {}
        if tr is not None and not tr.empty:
            for reason, g in tr.groupby("reason"):
                reasons[reason] = (len(g), round(float(g.pnl.sum()), 0))
        print(f"\n{label}")
        print(f"  trailing={p.get('Enable Trailing Stop')} sortino={r['sortino']:.4f} pnl={pnl:,.0f} trades={n}")
        print(f"  exit_mix={reasons}")

    hdr(f"Trailing A/B replay ({sol_col})")
    one(off, "exported (OFF)")
    one(on, "forced ON (genome trail params)")
    tpl_on = finalize_ga_solution_params(
        {
            **base,
            "Enable Trailing Stop": 1,
            "ATR Multiplier for Trailing Stop": 3.7652,
            "Trailing Delay (bars)": 28,
            "ATR Length for Trailing Stop": 1,
        },
        param_dict,
    )
    one(tpl_on, "forced ON (template trail params)")
    wide_on = finalize_ga_solution_params(
        {
            **base,
            "Enable Trailing Stop": 1,
            "ATR Multiplier for Trailing Stop": 5.0,
            "Trailing Delay (bars)": 10,
            "ATR Length for Trailing Stop": 14,
        },
        param_dict,
    )
    one(wide_on, "forced ON (wide trail params)")


def trailing_fitness_scan(n=40):
    import os
    import random
    import sys
    from pathlib import Path
    import pandas as pd

    root = Path("C:/Trading")
    sys.path.insert(0, str(root))
    os.environ["STRATEGY"] = "trend"
    from optimize import run_backtest, finalize_ga_solution_params
    from strategies.trend.parameters import load_params

    csv_path = root / "strategies/trend/parameters/trend_strategy_params.csv"
    param_dict, param_df = load_params(csv_path)
    param_keys, param_ranges = [], {}
    for _, row in param_df.iterrows():
        name = str(row.get("Name", "")).strip()
        if not name or name.startswith("==="):
            continue
        typ = row.get("Type")
        if typ not in ("int", "float"):
            continue
        try:
            mn, mx = float(row["Min"]), float(row["Max"])
        except Exception:
            continue
        if mn == mx:
            continue
        param_keys.append(name)
        param_ranges[name] = (mn, mx)

    data = root / "Bollinger/data/ES_full_1min_continuous_ratio_adjusted.csv"
    d = pd.read_csv(data, parse_dates=True, index_col=0)
    d.columns = [c.lower().strip() for c in d.columns]
    d = d[["open", "high", "low", "close", "volume"]].dropna().loc["2020-01-02":"2025-10-10"]

    random.seed(42)
    wins_on = wins_off = ties = 0
    hdr(f"Random genome trailing fitness scan (n={n})")
    for i in range(n):
        ind = [random.uniform(param_ranges[k][0], param_ranges[k][1]) for k in param_keys]
        params = dict(zip(param_keys, ind))
        off = finalize_ga_solution_params({**params, "Enable Trailing Stop": 0}, param_dict)
        on = finalize_ga_solution_params({**params, "Enable Trailing Stop": 1}, param_dict)
        r_off = run_backtest(off, d, param_dict, suppress_output=True)
        r_on = run_backtest(on, d, param_dict, suppress_output=True)
        s_off, s_on = r_off["sortino"], r_on["sortino"]
        if s_on > s_off + 1e-6:
            wins_on += 1
        elif s_off > s_on + 1e-6:
            wins_off += 1
        else:
            ties += 1
    print(f"  trailing ON better:  {wins_on}/{n}")
    print(f"  trailing OFF better: {wins_off}/{n}")
    print(f"  ties:                {ties}/{n}")


def main():
    hdr("Trailing stop investigation (Jun-21 GA)")
    trailing_ab("Solution_522")
    trailing_ab("Solution_0_SELECTED")

if __name__ == "__main__":
    main()
