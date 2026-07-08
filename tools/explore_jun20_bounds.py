#!/usr/bin/env python3
from __future__ import annotations
import csv,statistics,sys,re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
NEW=Path('C:/Trading/Trend/parameters/genetic_results_2026-06-20-1.csv')
OLD=Path('C:/Trading/Trend/parameters/genetic_results_2026-06-11-1.csv')
MID=Path('C:/Trading/Trend/parameters/genetic_results_2026-06-16-1.csv')
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
def ex(by,cols):
 K=dict(is_sortino=rk(by,'Aggregate IS Sortino'),oos_pnl=rk(by,'Total Profit',prefer='OOS'),oos_pf=rk(by,'Profit Factor',prefer='OOS'),oos_atd=rk(by,'Avg Trades/Day',prefer='OOS'),oos_span=rk(by,'Avg Trade Span',prefer='OOS'),rob=rk(by,'Robustness Score'),deg=rk(by,'Degradation'),pos=rk(by,'Positive OOS'),delay=rk(by,'Trailing Delay'),tf=rk(by,'Timeframe'),buy=rk(by,'Buy Lookback'),sell=rk(by,'Sell Lookback'),tp=rk(by,'Take Profit ATR'),trail=rk(by,'ATR Multiplier for Trailing'))
 out=[]
 for c in cols:
  s=S(c)
  s.is_sortino=pf(by.get(K['is_sortino'],{}).get(c)); s.oos_pnl=pm(by.get(K['oos_pnl'],{}).get(c)); s.oos_pf=pf(by.get(K['oos_pf'],{}).get(c)); s.oos_atd=pf(by.get(K['oos_atd'],{}).get(c)); s.oos_span=pf(by.get(K['oos_span'],{}).get(c)); s.robustness=pf(by.get(K['rob'],{}).get(c)); s.deg=pp(by.get(K['deg'],{}).get(c)); s.pos_splits=ps(by.get(K['pos'],{}).get(c)); s.trail_delay=pf(by.get(K['delay'],{}).get(c)); s.timeframe=pf(by.get(K['tf'],{}).get(c)); s.buy_lb=pf(by.get(K['buy'],{}).get(c)); s.sell_lb=pf(by.get(K['sell'],{}).get(c)); s.tp_atr=pf(by.get(K['tp'],{}).get(c)); s.trail_atr=pf(by.get(K['trail'],{}).get(c)); out.append(s)
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
        f"is_sortino={fn(s.is_sortino)} delay={fn(s.trail_delay)} tf={fn(s.timeframe)} "
        f"buy={fn(s.buy_lb)} sell={fn(s.sell_lb)} tp_atr={fn(s.tp_atr)} trail_atr={fn(s.trail_atr)}"
    )

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

def main():
    hdr("GA results comparison")
    print(f"NEW: {NEW}")
    print(f"OLD: {OLD}")
    nr, nc, nb = load(NEW)
    orows, oc, ob = load(OLD)
    print(f"\nSolution columns: NEW={len(nc)} OLD={len(oc)}")
    print(f"Template rows: NEW={len(nr)} OLD={len(orows)}")
    ns, os = ex(nb, nc), ex(ob, oc)
    cmp_tpl(orows, nr)
    hdr("5. Aggregate medians / means - key metrics")
    agg_metrics("OLD (2026-06-11)", os)
    agg_metrics("NEW (2026-06-16)", ns)
    hdr("6. Trailing delay distribution")
    trail("OLD", os)
    trail("NEW", ns)
    hdr("7. OOS span bucket percentages")
    spanb("OLD", os)
    spanb("NEW", ns)
    hdr("8. Deployment shortlist - top 10 each run")
    deploy("OLD", os)
    deploy("NEW", ns)
    top15(ns)
    hdr("10. SELECTED row stats both runs")
    sel("OLD", ob)
    sel("NEW", nb)
    cluster(os, ns)
    hdr("12. Best OOS and best robustness each run")
    best("OLD", os)
    best("NEW", ns)

def explore_bounds():
    hdr("Jun-20 boundary pressure and cluster analysis")
    rows, cols, by = load(NEW)

    def genes_list():
        out = []
        for name, r in by.items():
            if not name or str(name).startswith("==="):
                continue
            typ = (r.get("Type") or "").strip()
            if typ not in ("int", "float"):
                continue
            mn, mx = pf(r.get("Min")), pf(r.get("Max"))
            if mn is None or mx is None or mn == mx:
                continue
            out.append(name)
        return out

    genes = genes_list()
    oos_k = rk(by, "Total Profit", prefer="OOS")
    span_k = rk(by, "Avg Trade Span", prefer="OOS")
    sols = sorted(
        [{"col": c, "oos": pm(by[oos_k].get(c)), "span": pf(by[span_k].get(c))} for c in cols],
        key=lambda s: s["oos"] or -1e9,
        reverse=True,
    )
    top200 = sols[:200]
    pos200 = [s for s in sols if s["oos"] and s["oos"] > 0][:200]

    print("\n--- Boundary pressure (all solutions, within 5% of Min/Max) ---")
    print(f"{'Name':<46} {'Min':>8} {'Max':>8} {'Med':>8} {'%Lo':>5} {'%Hi':>5}")
    print("-" * 90)
    pressured = []
    for name in genes:
        r = by[name]
        mn, mx = pf(r.get("Min")), pf(r.get("Max"))
        vals = [pf(r.get(c)) for c in cols if pf(r.get(c)) is not None]
        if not vals:
            continue
        w = max(mx - mn, 1e-9)
        lo = sum(1 for v in vals if v <= mn + 0.05 * w)
        hi = sum(1 for v in vals if v >= mx - 0.05 * w)
        med = statistics.median(vals)
        print(f"{name[:46]:<46} {mn:8.3g} {mx:8.3g} {med:8.3g} {100*lo/len(vals):5.0f} {100*hi/len(vals):5.0f}")
        if lo / len(vals) > 0.35 or hi / len(vals) > 0.35:
            pressured.append((name, lo / len(vals), hi / len(vals), med, mn, mx))

    print("\n--- Top-200 OOS median vs bounds (AT bound if med within 2%) ---")
    for name in genes:
        r = by[name]
        mn, mx = pf(r.get("Min")), pf(r.get("Max"))
        vals = [pf(by[name].get(s["col"])) for s in top200 if pf(by[name].get(s["col"])) is not None]
        if not vals:
            continue
        med = statistics.median(vals)
        w = max(mx - mn, 1e-9)
        tag = ""
        if med <= mn + 0.02 * w:
            tag = " << AT_MIN"
        elif med >= mx - 0.02 * w:
            tag = " << AT_MAX"
        if tag:
            print(f"  {name[:44]:44} med={med:.4g} [{mn},{mx}]{tag}")

    hdr("Positive-OOS cluster (top 200 by OOS among OOS>0)")
    keys = [
        "Timeframe (minutes)",
        "ATR Multiplier for Trailing Stop",
        "Trailing Delay (bars)",
        "Initial Stop Loss (%)",
        "Buy Lookback",
        "Sell Lookback",
        "Take Profit ATR Multiplier",
        "Enable Trailing Stop",
        "Enable ADX Filter",
        "Enable SMA Filter",
        "Enable RSI Filter",
        "Enable VWAP Filter",
    ]
    for name in keys:
        if name not in by:
            continue
        vals = [pf(by[name].get(s["col"])) for s in pos200 if pf(by[name].get(s["col"])) is not None]
        if not vals:
            continue
        if "Enable" in name:
            print(f"  {name}: {Counter(int(v) for v in vals).most_common(3)}")
        elif name == "Timeframe (minutes)":
            print(f"  {name}: med={statistics.median(vals):.0f} modes={Counter(int(v) for v in vals).most_common(4)}")
        else:
            print(f"  {name}: med={statistics.median(vals):.3g} modes={Counter(round(v, 2) for v in vals).most_common(4)}")

    hdr("Span / timeframe cross-tab (top 200 OOS)")
    t200 = ex(by, [s["col"] for s in top200])
    print("  TF modes:", Counter(int(s.timeframe) for s in t200 if s.timeframe).most_common(5))
    print("  delay modes:", Counter(int(s.trail_delay) for s in t200 if s.trail_delay).most_common(5))
    print("  trail_atr med:", statistics.median([s.trail_atr for s in t200 if s.trail_atr]))
    spans = [s.oos_span for s in t200 if s.oos_span]
    print("  span med:", statistics.median(spans))

    hdr("Trailing OFF vs ON (all solutions)")
    ten = "Enable Trailing Stop"
    for v in (0, 1):
        sub = [s for s in sols if pf(by[ten].get(s["col"])) == v]
        pos = sum(1 for s in sub if s["oos"] and s["oos"] > 0)
        med = statistics.median([s["oos"] for s in sub if s["oos"] is not None])
        print(f"  trailing={v}: n={len(sub)} oos_pos={pos} ({100*pos/max(1,len(sub)):.1f}%) oos_med={fn(med, True)}")

    hdr("High boundary-pressure genes (expand candidate list)")
    for item in sorted(pressured, key=lambda x: max(x[1], x[2]), reverse=True)[:15]:
        name, pl, ph, med, mn, mx = item
        side = "MIN" if pl > ph else "MAX"
        print(f"  {name}: {100*max(pl,ph):.0f}% at {side}, med={med:.3g}")


if __name__ == "__main__":
    explore_bounds()
