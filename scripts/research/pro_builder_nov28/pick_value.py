#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Draft pick value by slot for the pro team builder: what a pick at overall slot p has returned in the league's value unit
over the player's cheap years (NBA VORX over the four seasons after the draft, NFL WAR over his first four seasons, NHL WAR
over the seven seasons after the draft), 0 for a player who never played.

    python3 scripts/research/pro_builder_nov28/pick_value.py [nba nfl nhl]   -> research/pro_pick_value.json

  curve   v = a + b ln p + c (ln p)^2   (one fit across every slot)
  round   the mean of the pick's round  (the baseline)
Held out one draft at a time: the curve ships when it beats the round mean on MAE with paired t <= -2. The table holds the
curve at every slot (the live builder prices it at the league's $ a win, less the slot's rookie pay above the minimum).

Sources: picks = scripts/nba_draft_picks.json (Basketball-Reference ids), nflverse draft_picks.csv (gsis ids), the NHL
records draft API (NHL ids); values = static/data/nba-xpm, the NFL payroll panel (scripts/research/payrolls_nov28), static/data/nhl-war."""
import csv
import gzip
import io
import json
import math
import os
import sys
import time
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'payrolls_nov28'))
from test import ols, pred, tstat  # noqa: E402

CACHE = os.path.join(ROOT, 'scripts', '.cache', 'pro_builder')
OUT = os.path.join(ROOT, 'research', 'pro_pick_value.json')
UA = {'User-Agent': 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'}


def get(url, fn):
    p = os.path.join(CACHE, fn)
    if os.path.exists(p):
        return open(p, 'rb').read()
    os.makedirs(CACHE, exist_ok=True)
    for k in range(4):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()
            open(p, 'wb').write(b)
            time.sleep(1.2)
            return b
        except Exception as e:  # noqa: BLE001
            print('pick_value:', url, repr(e)); time.sleep(5 * (k + 1))
    raise RuntimeError(url)


def season_files(d):
    out = {}
    for f in os.listdir(d):
        if f[:4].isdigit():
            out[int(f[:4])] = {str(p['id']): p for p in json.load(open(os.path.join(d, f)))['players']}
    return out


def nba():
    picks = json.load(open(os.path.join(ROOT, 'scripts', 'nba_draft_picks.json')))
    S = season_files(os.path.join(ROOT, 'static', 'data', 'nba-xpm'))
    rows = []
    for pid, (y, p) in picks.items():
        if 2009 <= y <= 2022 and p and p <= 60:
            v = sum((S.get(y + k, {}).get(pid) or {}).get('vorx') or 0 for k in (1, 2, 3, 4))
            rows.append({'y': y, 'p': p, 'r': 1 if p <= 30 else 2, 'v': v})
    return rows, 60, 'VORX, the four seasons after the draft'


def nfl():
    raw = get('https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.csv', 'draft_picks.csv')
    P = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'research', 'payrolls_nov28', 'panel_nfl.json.gz')))
    V = defaultdict(float)
    for r in P['rows']:
        for q in r['pl']:
            V[(r['s'], q['id'])] += q['v'] or 0
    rows = []
    for d in csv.DictReader(io.StringIO(raw.decode())):
        y, p = int(d['season']), int(d['pick'])
        if 2013 <= y <= 2022:
            g = d['gsis_id']
            v = sum(V.get((y + k, g), 0.0) for k in (0, 1, 2, 3)) if g else 0.0
            rows.append({'y': y, 'p': p, 'r': int(d['round']), 'v': v})
    return rows, 257, 'WAR, his first four seasons'


def nhl():
    S = season_files(os.path.join(ROOT, 'static', 'data', 'nhl-war'))
    rows = []
    for y in range(2008, 2020):
        d = json.loads(get(f'https://records.nhl.com/site/api/draft?cayenneExp=draftYear={y}', f'nhl_draft_{y}.json'))['data']
        for x in d:
            p = x.get('overallPickNumber')
            if not p:
                continue
            pid = str(x.get('playerId') or '')
            v = sum((S.get(y + k, {}).get(pid) or {}).get('war') or 0 for k in range(1, 8)) if pid else 0.0
            rows.append({'y': y, 'p': p, 'r': x.get('roundNumber') or 7, 'v': v})
    return rows, 224, 'WAR, the seven seasons after the draft'


def feats(p):
    l = math.log(p)
    return [1, l, l * l]


def run(lg):
    rows, top, unit = {'nba': nba, 'nfl': nfl, 'nhl': nhl}[lg]()
    ys = sorted({r['y'] for r in rows})
    ec, er, by = [], [], {}
    for y in ys:
        tr, te = [r for r in rows if r['y'] != y], [r for r in rows if r['y'] == y]
        w = ols([feats(r['p']) for r in tr], [r['v'] for r in tr])
        rm = defaultdict(list)
        for r in tr:
            rm[r['r']].append(r['v'])
        c = [abs(r['v'] - pred(w, feats(r['p']))) for r in te]
        b = [abs(r['v'] - (sum(rm[r['r']]) / len(rm[r['r']]) if rm[r['r']] else 0)) for r in te]
        ec += c; er += b; by[y] = sum(c) / len(c) < sum(b) / len(b)
    d = [x - z for x, z in zip(ec, er)]
    w = ols([feats(r['p']) for r in rows], [r['v'] for r in rows])
    t = round(tstat(d), 2)
    won = sum(by.values())
    table = [round(max(pred(w, feats(p)), 0.0), 3) for p in range(1, top + 1)]
    return {'n': len(rows), 'drafts': f'{ys[0]}-{ys[-1]}', 'unit': unit, 'maeCurve': round(sum(ec) / len(ec), 3),
            'maeRound': round(sum(er) / len(er), 3), 't': t, 'won': f'{won}/{len(ys)}', 'pass': t <= -2 and won * 2 > len(ys),
            'b': [round(x, 4) for x in w], 'table': table}


def main():
    lgs = sys.argv[1:] or ['nba', 'nfl', 'nhl']
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for lg in lgs:
        out[lg] = run(lg)
        print(lg, json.dumps({k: v for k, v in out[lg].items() if k != 'table'}), out[lg]['table'][:5], out[lg]['table'][-3:])
    out['note'] = __doc__.strip()
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
