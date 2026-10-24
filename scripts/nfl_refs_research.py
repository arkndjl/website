#!/usr/bin/env python3
"""NFL referee / officiating-crew effects on totals and margin residuals (research only, round 2, Oct 24 2026).

    python3 scripts/nfl_refs_research.py       # needs numpy; downloads nflverse games.csv + officials.csv

PRE-REGISTERED GATE (written before the numbers): leave-one-season-out over the walk-forward rows
(scripts/data/games_wf/nfl.json.gz, 2015-25). For each held-out season the ridge crew effects are fit on the other
seasons' residuals (target tot - tm for totals, res - m for margin), lambda picked by an inner leave-one-season-out
on the training seasons; the held-out game is predicted tm + train mean + effects. Compared with tm + train mean only.
Pass = pooled held-out MAE improves with paired t <= -2 on |error| differences and most seasons agree.
Also run: effects from past seasons only (walk-forward), the head referee alone vs the whole crew (sum of official
effects), and the same against the closing total (tot - T). Report everything, pass or fail.
"""
import csv
import gzip
import io
import json
import math
import os
import urllib.request
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
WF = os.path.join(HERE, 'data', 'games_wf', 'nfl.json.gz')
OUT = os.path.join(HERE, 'data', 'nfl_refs_research.json')
GAMES = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'
OFF = 'https://github.com/nflverse/nflverse-data/releases/download/officials/officials.csv'
LAMS = [25, 50, 100, 200, 400, 800]


def fetch(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'arkndjl.net research'}), timeout=90) as r:
        return list(csv.DictReader(io.StringIO(r.read().decode())))


def effects(rows, key, lam, mu):
    """ridge per official: sum of (resid - mu) over games / (n + lam); crew effect = sum over the crew's members,
    each member's effect fit on the game residual split equally (crew size c => resid/c)."""
    s, n = defaultdict(float), defaultdict(float)
    for r in rows:
        c = r[key]
        for o in c:
            s[o] += (r['y'] - mu) / len(c)
            n[o] += 1.0 / len(c)
    return {o: s[o] / (n[o] + lam) for o in s}


def pred(r, key, eff):
    return sum(eff.get(o, 0.0) for o in r[key])


def fit_lam(train, key):
    seasons = sorted({r['S'] for r in train})
    best, bl = None, None
    for lam in LAMS:
        err = 0.0
        for t in seasons:
            tr = [r for r in train if r['S'] != t]
            te = [r for r in train if r['S'] == t]
            mu = np.mean([r['y'] for r in tr])
            eff = effects(tr, key, lam, mu)
            err += sum(abs(r['y'] - mu - pred(r, key, eff)) for r in te)
        if best is None or err < best:
            best, bl = err, lam
    return bl


def evaluate(rows, key, mode):
    """mode 'loso' (all other seasons) or 'wf' (past seasons only). Returns per-game abs-error pairs."""
    out = []
    seasons = sorted({r['S'] for r in rows})
    for s in seasons:
        tr = [r for r in rows if (r['S'] != s if mode == 'loso' else r['S'] < s)]
        te = [r for r in rows if r['S'] == s]
        if len({r['S'] for r in tr}) < 3:
            continue
        lam = fit_lam(tr, key)
        mu = np.mean([r['y'] for r in tr])
        eff = effects(tr, key, lam, mu)
        for r in te:
            e0 = abs(r['y'] - mu)
            e1 = abs(r['y'] - mu - pred(r, key, eff))
            out.append((s, e0, e1, lam))
    return out


def summarize(pairs):
    d = np.array([p[2] - p[1] for p in pairs])
    n = len(d)
    t = float(d.mean() / (d.std(ddof=1) / math.sqrt(n)))
    bys = defaultdict(list)
    for s, e0, e1, _ in pairs:
        bys[s].append(e1 - e0)
    seas = {int(s): round(float(np.mean(v)), 3) for s, v in sorted(bys.items())}
    return {'n': n, 'mae0': round(float(np.mean([p[1] for p in pairs])), 3), 'mae1': round(float(np.mean([p[2] for p in pairs])), 3),
            'dMAE': round(float(d.mean()), 4), 't': round(t, 2), 'seasonsBetter': sum(1 for v in seas.values() if v < 0),
            'seasons': seas, 'lams': sorted({p[3] for p in pairs})}


def main():
    G = {g['old_game_id']: g for g in fetch(GAMES)}
    O = defaultdict(list)
    for o in fetch(OFF):
        O[o['game_id']].append(o)
    wf = json.load(gzip.open(WF))
    base = []
    for r in wf:
        gid = r['id']
        g = G.get(gid) or next((x for x in G.values() if x['game_id'] == gid), None)
        if not g:
            continue
        offs = O.get(g['old_game_id'], [])
        ref = (g.get('referee') or '').strip()
        crew = sorted({o['official_name'] for o in offs})
        if not ref and not crew:
            continue
        base.append({**r, 'ref': [ref] if ref else [], 'crew': crew or ([ref] if ref else [])})
    print(len(base), 'games joined;', sum(1 for r in base if len(r['crew']) > 1), 'with full crews')
    res = {'n': len(base)}
    for tgt in ('tot-tm', 'tot-T', 'res-m'):
        rows = []
        for r in base:
            if tgt == 'tot-tm' and r.get('tm') is not None and r.get('tot') is not None:
                y = r['tot'] - r['tm']
            elif tgt == 'tot-T' and r.get('T') is not None and r.get('tot') is not None:
                y = r['tot'] - r['T']
            elif tgt == 'res-m' and r.get('m') is not None and r.get('res') is not None:
                y = r['res'] - r['m']
            else:
                continue
            rows.append({'S': r['S'], 'y': y, 'ref': r['ref'], 'crew': r['crew']})
        for key in ('ref', 'crew'):
            sub = [r for r in rows if r[key]]
            for mode in ('loso', 'wf'):
                pairs = evaluate(sub, key, mode)
                if pairs:
                    res[f'{tgt}/{key}/{mode}'] = summarize(pairs)
                    s = res[f'{tgt}/{key}/{mode}']
                    print(f"{tgt:7s} {key:5s} {mode:4s} n{s['n']} MAE {s['mae0']} -> {s['mae1']} d{s['dMAE']} t{s['t']} better {s['seasonsBetter']}/{len(s['seasons'])} lam{s['lams']}")
    # split-half reliability of the head referee's mean total residual (odd vs even games)
    by = defaultdict(list)
    for r in base:
        if r.get('tm') is not None and r.get('tot') is not None and r['ref']:
            by[r['ref'][0]].append(r['tot'] - r['tm'])
    a, b = [], []
    for v in by.values():
        if len(v) >= 20:
            a.append(np.mean(v[0::2])); b.append(np.mean(v[1::2]))
    res['splitHalfR_tot-tm'] = round(float(np.corrcoef(a, b)[0, 1]), 3)
    res['splitHalfRefs'] = len(a)
    print('split-half r', res['splitHalfR_tot-tm'], 'refs', len(a))
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
