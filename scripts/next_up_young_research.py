# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Next up = young players (Noah, Nov 23 2026). Where each sport's age cutoff comes from: the breakout population of
each scripts/<sport>_breakout_research.py (players never yet at the bar, labelled by a first breakout next season),
first-breakout rate by age (college: by class year) against the population's rate.

Cutoff = the last age of the first run of ages (30+ rows) whose rate, smoothed over that age and its two neighbours (counts pooled), is still at or
above the population rate: the rising side of the breakout curve. College = underclassmen (Fr, So, redshirts by
class), as Noah asked; the class table is kept for the record.

    python3 scripts/next_up_young_research.py [sport ...]   # -> data/next_up_young.json (merged by sport)

Each research script runs until its breakout rows are built (its own data sources, see its docstring), then stops:
the harness wraps its bo_feats / bo_row to record each row's season line and reads the labels from the first
leave-one-season-out call over exactly those rows."""
import importlib
import json
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, '..', 'data', 'next_up_young.json')
SPORTS = ('nba', 'nhl', 'soccer', 'nfl', 'cfb', 'cbb')
ARGV = {'cfb': ['--offline']}
COLLEGE = {'cfb': 'yrs', 'cbb': 'cls'}


class _Done(Exception):
    pass


def capture(sport):
    R = importlib.import_module(sport + '_breakout_research')
    fn = 'bo_row' if sport == 'soccer' else 'bo_feats'
    rec, out, orig = [], [], getattr(R.B, fn)
    ai = 1 if sport == 'nfl' else 0

    def wrap(*a, **k):
        rec.append(a[ai])
        return orig(*a, **k)
    setattr(R.B, fn, wrap)
    oloso = R.L.loso

    def loso(S, fp, err):
        n = len(S)
        if n == len(rec) and n > 100:
            for f in (err, fp):
                for c in (f.__closure__ or []):
                    try:
                        v = c.cell_contents
                    except ValueError:
                        continue
                    if isinstance(v, np.ndarray) and v.ndim == 1 and len(v) == n and set(np.unique(v)) <= {0.0, 1.0}:
                        out.extend({'age': a.get('age'), 'cls': a.get(COLLEGE.get(sport, 'cls')), 'hit': float(h)}
                                   for a, h in zip(rec, v))
                        raise _Done
        return oloso(S, fp, err)
    R.L.loso = loso
    argv, sys.argv = sys.argv, [sys.argv[0]] + ARGV.get(sport, [])
    try:
        R.main()
    except _Done:
        pass
    finally:
        sys.argv = argv
    return out


def nhl_rows():
    """NHL from the site's WAR files (static/data/nhl-war/<season>.json: age, ice time, WAR), the same population and
    label as scripts/nhl_breakout_research.py (its NHL stats API pull needs every report; WAR + TOI are all this
    needs): skaters with ROW_MIN+ minutes (per 82 games), best shrunk WAR/1k so far under L; hit = next season
    ROLE_MIN+ minutes at L or over"""
    import nhl_breakout as B
    fit = json.load(open(os.path.join(HERE, '..', 'data', 'nhl_breakout_fit.json')))
    Lq, W = fit['L'], {}
    d = os.path.join(HERE, '..', 'static', 'data', 'nhl-war')
    for f in sorted(os.listdir(d)):
        w = json.load(open(os.path.join(d, f)))
        if w.get('label') and w['season'] < max(int(x[:4]) for x in os.listdir(d)):
            W[w['season']] = w
    shr = lambda p: p['war'] / (p['toi'] + B.K_SHR) * 1000
    best, out = {}, []
    for S in sorted(W):
        g = min(82, W[S].get('games') or 82) / 82
        nxt = {p['id']: p for p in W[S + 1]['players'] if p.get('grp') != 'G' and p.get('war') is not None} if S + 1 in W else None
        for p in W[S]['players']:
            if p.get('grp') == 'G' or p.get('war') is None or not p.get('toi'):
                continue
            b = max(best.get(p['id'], -9), shr(p))
            if nxt is not None and S >= 2013 and p['toi'] >= B.ROW_MIN * g and b < Lq:
                q = nxt.get(p['id'])
                g1 = min(82, W[S + 1].get('games') or 82) / 82
                out.append({'age': p.get('age'), 'cls': None,
                            'hit': 1.0 if q and q.get('toi') and q['toi'] >= B.ROLE_MIN * g1 and shr(q) >= Lq else 0.0})
            if p['toi'] >= B.ROW_MIN * g:
                best[p['id']] = b
    return out


def table(rows, k):
    rows = [r for r in rows if r[k] is not None]
    rate = sum(r['hit'] for r in rows) / len(rows)
    by = defaultdict(lambda: [0, 0.0])
    for r in rows:
        by[int(r[k])][0] += 1
        by[int(r[k])][1] += r['hit']
    tot, cum, T = sum(h for _, h in by.values()), 0.0, []
    for a in sorted(by):
        n, h = by[a]
        cum += h
        sn = sum(by[b][0] for b in (a - 1, a, a + 1) if b in by)
        sh = sum(by[b][1] for b in (a - 1, a, a + 1) if b in by)
        T.append({'k': a, 'n': n, 'hits': int(h), 'rate': round(h / n, 4), 'smooth': round(sh / sn, 4),
                  'x': round(sh / sn / rate, 2), 'cum': round(cum / tot, 3)})
    return rate, T


def main():
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for s in sys.argv[1:] or SPORTS:
        rows = nhl_rows() if s == 'nhl' else capture(s)
        rate, T = table(rows, 'age') if any(r['age'] is not None for r in rows) else (None, [])
        rate = sum(r['hit'] for r in rows) / len(rows)
        o = {'n': len(rows), 'rate': round(rate, 4), 'by_age': T}
        if s in COLLEGE:
            o['by_class'] = table(rows, 'cls')[1]
            o['rule'] = 'cls'
            o['keep'] = ['Fr', 'So', 'RS-Fr', 'RS-So']
        else:
            big = [t for t in T if t['n'] >= 30]
            top, seen = None, False
            for t in big:                                  # the end of the first run at or above the pool rate
                if t['x'] >= 1.0:
                    top, seen = t['k'], True
                elif seen:
                    break
            o['rule'] = 'age'
            o['max_age'] = top
            o['share_of_breakouts'] = next(t['cum'] for t in T if t['k'] == o['max_age'])
        res[s] = o
        print(s, {k: v for k, v in o.items() if not k.startswith('by_')}, flush=True)
    json.dump(res, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
