#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""T2: Polymarket tennis outrights against the event odds backtest (scoring only; a blend is never shipped from here).

    python3 t2_outrights.py <search.json> queue    # match winner markets to past draws, queue price paths
    python3 t2_outrights.py <search.json>          # score
Price time: 12:00 UTC on the day before the event's start date; the 12 most traded outcomes of each market are
pulled, the rest of the draw shares what is left of 1 after renormalising (floor .001 each)."""
import datetime as dt, math, pickle, re
from tcommon import *
import pm
import tennis_events as TE
from tennis_data import is_qual
TOPN = 12


def events(rows, y0=20250501):
    p = os.path.join(CACHE, 't2_events.pkl')
    if os.path.exists(p): return pickle.load(open(p, 'rb'))
    m = M.Model(live_P()); M.mark_two_week(rows)
    main = {}
    for r in rows:
        if y0 <= r[0] and (r[4] in ('QF', 'SF', 'F') or (r[4][:1] == 'R' and r[4][1:].isdigit())): main.setdefault(r[6], []).append(r)
    main = {t: v for t, v in main.items() if any(x[4] == 'F' and x[2] in ('G', 'M', 'A') for x in v)}
    lvl = {t: next(x[2] for x in v if x[4] == 'F') for t, v in main.items()}
    out, seen = [], set()
    for r in rows:
        tid = r[6]
        if tid in main and tid not in seen and not is_qual(r[4]):
            seen.add(tid)
            ms = sorted(main[tid], key=lambda x: {'QF': 500, 'SF': 600, 'F': 700}.get(x[4], 0) - (int(x[4][1:]) if x[4][1:].isdigit() else 0))
            unit, rank = {}, {}
            for x in ms:
                w, l = x[7], x[8]
                rank.setdefault(w, x[12]); rank.setdefault(l, x[13])
                unit[w] = (unit.get(w, w), unit.pop(l, l))
            fin = [x for x in ms if x[4] == 'F']
            if len(unit) == 1 and len(fin) == 1 and len(rank) >= 8:
                ps = list(rank); tour, sf, bo = r[1], r[3], max(x[5] for x in ms)
                day = (M.ymd(r[0]) - M.DAY0).days + 1
                pmx = {}
                for i, a in enumerate(ps):
                    for b in ps[i + 1:]:
                        q = m.predict(a, b, tour, sf, day, bo)[0]
                        pmx[(a, b)], pmx[(b, a)] = q, 1 - q
                P = TE.title_exact(next(iter(unit.values())), lambda a, b: pmx[(a, b)])
                out.append({'tid': tid, 'd': r[0], 'tour': tour, 'lv': lvl[tid], 'champ': fin[0][7], 'P': P})
        m.update(r)
    pickle.dump(out, open(p, 'wb'))
    return out


def match(evs, search, R):
    """winner markets -> our events: same tour, market end within the event window, 6+ of its names and 60%+ of them in the draw"""
    out = []
    for e in search:
        t = e.get('title') or ''
        if not re.search(r'winner', t, re.I) or re.search(r'doubles| vs |juniors|golf|pickle|ppa|chess|cs2|valorant|darts|olympia', t, re.I): continue
        ms = e.get('markets') or []
        if len(ms) < 8 or not e.get('endDate'): continue
        end = pm.ts(e['endDate'])
        if end is None or end >= pm.LOCK: continue
        best = None
        for tour in ('atp', 'wta'):
            ids = {}
            for x in ms:
                nme = x.get('groupItemTitle') or ''
                pid = R.pid(nme, tour) if nme else None
                if pid: ids[pid] = x
            for ev in evs:
                if ev['tour'] != tour: continue
                gap = end.date().toordinal() - dord(ev['d'])
                if not -1 <= gap <= 18: continue
                inn = sum(1 for p in ids if p in ev['P'])
                ov = inn / max(1, len(ids))
                if inn >= 6 and ov >= .6 and (best is None or ov > best[0]): best = (ov, ev, ids)
        if best: out.append({'pe': e, 'ev': best[1], 'ids': best[2], 'ov': best[0]})
    # one market per event: the most traded
    by = {}
    for x in out:
        k = x['ev']['tid']
        if k not in by or (x['pe'].get('volume') or 0) > (by[k]['pe'].get('volume') or 0): by[k] = x
    return list(by.values())


def tprice(ev):
    d = dt.date.fromordinal(dord(ev['d']) - 1)
    return dt.datetime(d.year, d.month, d.day, 12, tzinfo=dt.timezone.utc).timestamp()


def main():
    rows, players, tn = load_rows()
    R = Resolver(players, rows, 20240101)
    evs = events(rows)
    S = json.load(open(sys.argv[1]))
    Mx = match(evs, S, R)
    print('events in backtest', len(evs), 'matched markets', len(Mx))
    if 'queue' in sys.argv:
        q = []
        for x in Mx:
            T = tprice(x['ev'])
            top = sorted(x['ids'].items(), key=lambda kv: -float(kv[1].get('volumeNum') or kv[1].get('volume') or 0))[:TOPN]
            for pid, mk in top:
                q.append({'tok': json.loads(mk['clobTokenIds'])[0], 'a': T - 3 * 86400, 'b': T, 'f': 60, 'k': 'out'})
        p = os.path.join(pm.CACHE, 'queue.jsonl')
        old = [json.loads(l) for l in open(p)]
        with open(p, 'w') as f:
            for z in q + [o for o in old if o.get('k') != 'out']: f.write(json.dumps(z) + '\n')
        print('queued', len(q)); return
    H = pm.load_hist(); res = []
    for x in Mx:
        ev = x['ev']; T = tprice(ev)
        top = sorted(x['ids'].items(), key=lambda kv: -float(kv[1].get('volumeNum') or kv[1].get('volume') or 0))[:TOPN]
        pr = {}
        for pid, mk in top:
            h = H.get((json.loads(mk['clobTokenIds'])[0], 'out'))
            v = [p for t, p in (h or []) if t <= T]
            if v: pr[pid] = v[-1]
        if len(pr) < 6: continue
        rest = [p for p in ev['P'] if p not in pr]
        tot = sum(pr.values()) + .001 * len(rest)
        Q = {p: (pr[p] if p in pr else .001) / tot for p in ev['P']}
        ch = ev['champ']
        res.append({'tid': ev['tid'], 'name': tn.get(ev['tid']), 'd': ev['d'], 'tour': ev['tour'], 'lv': ev['lv'], 'n': len(ev['P']),
                    'P': ev['P'], 'Q': Q, 'champ': ch, 'll_m': -math.log(max(ev['P'][ch], 1e-6)), 'll_p': -math.log(max(Q[ch], 1e-6)),
                    'priced': len(pr), 'sum_raw': round(sum(pr.values()), 3), 'vol': x['pe'].get('volume')})
    def tt(d):
        d = np.array(d)
        return {'n': len(d), 'd': round(float(d.mean()), 4), 't': round(float(d.mean() / (d.std(ddof=1) / len(d) ** .5)), 2)} if len(d) > 2 else {'n': len(d)}
    out = {'events': len(res), 'll_model': round(float(np.mean([r['ll_m'] for r in res])), 4), 'll_price': round(float(np.mean([r['ll_p'] for r in res])), 4),
           'model_minus_price': tt([r['ll_m'] - r['ll_p'] for r in res]),
           'by_tier': {k: dict(tt([r['ll_m'] - r['ll_p'] for r in res if r['lv'] == k]), ll_model=round(float(np.mean([r['ll_m'] for r in res if r['lv'] == k] or [0])), 4),
                                ll_price=round(float(np.mean([r['ll_p'] for r in res if r['lv'] == k] or [0])), 4)) for k in 'GMA'}}
    # blend a * logit(model) + b * logit(price), renormalised; fit on 2025 events, scored on 2026 events
    lg = lambda p: math.log(max(p, 1e-5) / (1 - min(max(p, 1e-5), 1 - 1e-5)))  # noqa: E731
    def bl(r, a, b):
        s = {p: 1 / (1 + math.exp(-(a * lg(r['P'][p]) + b * lg(r['Q'][p])))) for p in r['P']}
        t = sum(s.values()); return -math.log(max(s[r['champ']] / t, 1e-9))
    tr = [r for r in res if r['d'] < 20260101]; te = [r for r in res if r['d'] >= 20260101]
    if len(tr) >= 5 and len(te) >= 5:
        grid = [(a, b) for a in np.arange(0, 1.51, .1) for b in np.arange(0, 1.51, .1) if a + b > 0]
        a, b = min(grid, key=lambda g: sum(bl(r, *g) for r in tr))
        out['blend'] = {'a': round(float(a), 2), 'b': round(float(b), 2), 'n_fit_2025': len(tr), 'n_2026': len(te),
                        'll_2026': {'model': round(float(np.mean([r['ll_m'] for r in te])), 4), 'price': round(float(np.mean([r['ll_p'] for r in te])), 4),
                                    'blend': round(float(np.mean([bl(r, a, b) for r in te])), 4)},
                        'blend_minus_model_2026': tt([bl(r, a, b) - r['ll_m'] for r in te]),
                        'blend_minus_price_2026': tt([bl(r, a, b) - r['ll_p'] for r in te])}
    out['list'] = [[r['name'], r['d'], r['tour'], r['lv'], r['priced'], r['sum_raw'], round(r['ll_m'], 3), round(r['ll_p'], 3)] for r in res]
    print(json.dumps({k: v for k, v in out.items() if k != 'list'}, indent=1)); save('t2_results', out)


if __name__ == '__main__':
    main()
