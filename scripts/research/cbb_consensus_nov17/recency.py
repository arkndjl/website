#!/usr/bin/env python3
"""Recency weight for the CBB consensus (Nov 17 2026). Does down-weighting older boards beat the equal-weight
consensus (cbb_mock.consensus)? Proxy panel: at each dated No Ceilings board T (drafts 2022-26, before the draft), the
boards are every No Ceilings version dated <= T that cycle (older versions stand in for stale boards). Weight
w = 0.5 ** (age days / half-life); score = .5 weighted median + .5 weighted mean of ranks (missing = 1.5 x depth).
Target: real slot (ESPN picks, undrafted = 75). Metric: mean |ln cons rank - ln slot| over players on any panel board.
Half-life picked leave one draft out. Ship rule: gain > 0, row t >= 2, better in >= 4 of 5 drafts."""
import csv, datetime, math, os, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import cbb_data as D
import cbb_boards as CB

B = os.environ.get('CBB_BOARDS', '/mnt/project-files/cbb/boards')
UND = 75
HL = [7, 14, 30, 45, 60, 90, 120, 180, 365, math.inf]


def wmedian(x, w):
    o = np.argsort(x); x, w = np.asarray(x)[o], np.asarray(w)[o]; c = np.cumsum(w) / w.sum()
    return float(x[np.searchsorted(c, 0.5)])


def cons(boards, ages, hl):
    w = np.array([1.0 if hl == math.inf else 0.5 ** (a / hl) for a in ages])
    ppl = defaultdict(dict)
    for b, rows in enumerate(boards):
        for k, rk in rows.items(): ppl[k][b] = rk
    depth = [max(r.values()) for r in boards]
    sc = {k: 0.5 * wmedian([v.get(b, 1.5 * depth[b]) for b in range(len(boards))], w)
             + 0.5 * float(np.average([v.get(b, 1.5 * depth[b]) for b in range(len(boards))], weights=w)) for k, v in ppl.items()}
    order = sorted(sc, key=lambda k: (sc[k], -len(ppl[k])))
    return {k: i for i, k in enumerate(order, 1)}


def main():
    slot = {}
    for r in csv.DictReader(open(os.path.join(B, 'espn_picks.csv'))):
        if r['slot_pick']: slot[(int(r['draft_year']), D.norm(r['name']))] = int(r['slot_pick'])
    nc = defaultdict(lambda: defaultdict(dict))
    for r in csv.DictReader(open(os.path.join(B, 'noceilings.csv'))):
        y = int(r['draft_year'])
        if 2022 <= y <= 2026 and r['board_date'] < CB.DRAFT[y]: nc[y][r['board_date']][D.norm(r['name'])] = int(r['rank'])
    err = defaultdict(lambda: defaultdict(list))      # year -> hl -> per-row errors (rows aligned across hl)
    panels = 0
    for y, vs in nc.items():
        dates = sorted(vs)
        for i, T in enumerate(dates):
            if i == 0: continue
            ds = dates[:i + 1]
            ages = [(datetime.date.fromisoformat(T) - datetime.date.fromisoformat(d)).days for d in ds]
            panels += 1
            for hl in HL:
                c = cons([vs[d] for d in ds], ages, hl)
                for k in sorted(c):
                    err[y][hl].append(abs(math.log(c[k]) - math.log(slot.get((y, k), UND))))
    years = sorted(err)
    tot = lambda y, h: float(np.sum(err[y][h]))
    held, eq, pick = [], [], {}
    for y in years:
        h = min(HL, key=lambda h: sum(tot(z, h) for z in years if z != y)); pick[y] = h
        held.append(np.array(err[y][h])); eq.append(np.array(err[y][math.inf]))
    d = np.concatenate(eq) - np.concatenate(held)
    t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d))) if d.std() > 0 else 0.0
    better = sum(float((e - h).mean()) > 0 for e, h in zip(eq, held))
    print(panels, 'panels,', len(d), 'rows')
    for h in HL: print(f'half-life {h}: mean |ln err| {np.mean(np.concatenate([err[y][h] for y in years])):.4f}')
    print('LODO half-life', pick)
    print(f'equal {np.concatenate(eq).mean():.4f}  recency {np.concatenate(held).mean():.4f}  gain {d.mean():.4f}  t {t:.2f}  drafts better {better}/{len(years)}')
    for y, e, h in zip(years, eq, held): print('  ', y, f'{e.mean():.4f} -> {h.mean():.4f}')
    ok = d.mean() > 0 and t >= 2 and better >= 4
    print('PASS' if ok else 'FAIL')


if __name__ == '__main__' and '--independent' not in sys.argv:
    main()


def main2():
    """Test 2, independent analysts: panel = ESPN's and NBADraft.net's final boards (age 0) + one No Ceilings version
    (age = draft day - its date, > 14 days). Does a half-life on the stale board beat equal weight?"""
    slot = {}
    for r in csv.DictReader(open(os.path.join(B, 'espn_picks.csv'))):
        if r['slot_pick']: slot[(int(r['draft_year']), D.norm(r['name']))] = int(r['slot_pick'])
    fin = defaultdict(lambda: defaultdict(dict))
    for src, f in (('espn', 'espn.csv'), ('ndn', 'nbadraftnet.csv')):
        for r in csv.DictReader(open(os.path.join(B, f))):
            y = int(r['draft_year'])
            if 2022 <= y <= 2026 and r['rank']: fin[y][src].setdefault(D.norm(r['name']), int(r['rank']))
    nc = defaultdict(lambda: defaultdict(dict))
    for r in csv.DictReader(open(os.path.join(B, 'noceilings.csv'))):
        y = int(r['draft_year'])
        if 2022 <= y <= 2026 and r['board_date'] < CB.DRAFT[y]: nc[y][r['board_date']][D.norm(r['name'])] = int(r['rank'])
    err = defaultdict(lambda: defaultdict(list))
    for y, vs in nc.items():
        for T, b in vs.items():
            age = CB.days_to_draft(T, y)
            if age <= 14: continue
            for hl in HL:
                c = cons([fin[y]['espn'], fin[y]['ndn'], b], [0, 0, age], hl)
                for k in sorted(c): err[y][hl].append(abs(math.log(c[k]) - math.log(slot.get((y, k), UND))))
    years = sorted(err)
    tot = lambda y, h: float(np.sum(err[y][h]))
    held, eq, pick = [], [], {}
    for y in years:
        h = min(HL, key=lambda h: sum(tot(z, h) for z in years if z != y)); pick[y] = h
        held.append(np.array(err[y][h])); eq.append(np.array(err[y][math.inf]))
    d = np.concatenate(eq) - np.concatenate(held)
    t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))
    better = sum(float((e - h).mean()) > 0 for e, h in zip(eq, held))
    for h in HL: print(f'half-life {h}: {np.mean(np.concatenate([err[y][h] for y in years])):.4f}')
    print('LODO half-life', pick)
    print(f'equal {np.concatenate(eq).mean():.4f}  recency {np.concatenate(held).mean():.4f}  gain {d.mean():.4f}  t {t:.2f}  drafts better {better}/{len(years)}')
    print('PASS' if d.mean() > 0 and t >= 2 and better >= 4 else 'FAIL')


if __name__ == '__main__' and '--independent' in sys.argv:
    main2()
