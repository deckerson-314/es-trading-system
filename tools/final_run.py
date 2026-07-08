exec(open(r"C:/Trading/tools/build_list.py", encoding="utf-8").read())
for i, l in enumerate(LIST):
    if isinstance(l, str) and "f'{'" in l:
        LIST[i] = "  print('{0:<55} {1:<12} OLD -> NEW'.format('Name', 'Field'))"

code = chr(10).join(LIST) + chr(10)\ng = {}\nexec(compile(code, "ga_cmp.py", "exec"), g)\nglobals().update(g)\n\ndef agg_metrics(label, sols):
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
        f"{s.col}: oos_pnl={fn(s.oos_pnl, m=True)} rob={fn(s.robustness)} "
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
    print(f"  oos_pnl      : {fn(s.oos_pnl, m=True)}")
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
        print(f"    oos_pnl mean={fn(m, m=True)} median={fn(med, m=True)}")
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

if __name__ == "__main__":
    main()
