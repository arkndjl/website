#!/usr/bin/env python3
"""Coordinator value-added: does a coordinator's record at his old job (his unit's rating over the program's
before him and the roster's talent) carry to his new job? The head-coach version (scripts/cfb_coach_va.py) failed;
this is the same test on offensive and defensive coordinators, on unit ratings instead of team ratings.

    python3 scripts/cfb_coord_va.py            # pull (shares scripts/.cache/coachva with cfb_coach_va.py), test, write
    python3 scripts/cfb_coord_va.py --offline  # cached pulls only

Data: the head-coach test's games, recruiting and Wikipedia season pages ('<year> <team> football team'), whose
infobox also names the coordinators (off_coach / def_coach). A season with co-coordinators or a change is left out.
Unit ratings: per season, points scored by each side as offense + opposing defense + home edge (ridge, points capped
at CAP_PTS, FCS pooled): off = points scored over an average FBS team, def = points held under one.
Rows are (team, side): the coach-VA functions run unchanged on them, with a coordinator keyed by side, so a mover is
an OC who takes another OC job (or DC to DC). Pass rule (pre-set, the same as the head coaches'): shrunk old-job VA or
the two-way fixed-effect coordinator effect predicts new-job residuals on held-out movers, slope t >= 2, beats
predicting no coordinator effect, paired t <= -2, and the walk-forward version beats the movers' mean, t <= -2.
Writes data/cfb_coord_va.json.
"""
import json
import os
import re
import sys
import time
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfb_coach_va as cv  # noqa: E402

OUT = os.path.join(cv.ROOT, 'data', 'cfb_coord_va.json')
CAP_PTS = 56
FIELDS = {'off': 'off_coach', 'def': 'def_coach'}


def wiki_coords(titles):
    """coordinators in each season page's infobox, from the cached pages cfb_coach_va.wiki_hc pulled:
    {title: {'off': [names], 'def': [names]}}"""
    cv.wiki_hc(titles)   # makes sure every page is cached
    out = {}
    for i in range(0, len(titles), 50):
        url = ('https://en.wikipedia.org/w/api.php?action=query&format=json&prop=revisions&rvprop=content&rvslots=main'
               '&rvsection=0&redirects=1&titles=' + cv.requests.utils.quote('|'.join(titles[i:i + 50])))
        f = os.path.join(cv.CACHE, cv.hashlib.sha1(url.encode()).hexdigest() + '.json')
        if not os.path.exists(f): continue
        d = json.load(open(f))
        back = {}
        for n in (d['query'].get('normalized') or []): back[n['to']] = n['from']
        for n in (d['query'].get('redirects') or []): back[n['to']] = back.get(n['from'], n['from'])
        for pg in d['query']['pages'].values():
            rv = pg.get('revisions')
            if not rv: continue
            txt = rv[0]['slots']['main']['*']
            got = {}
            for side, fld in FIELDS.items():
                ms = re.findall(r'\|\s*' + fld + r'\s*=(.*?)(?=\n\s*\||\n\}\})', txt, re.S)
                if not ms: continue
                v = re.sub(r'<ref.*?(</ref>|/>)', '', '<br>'.join(ms), flags=re.S)
                v = re.sub(r'\{\{(?:sortname|nowrap)\|([^}|]+)\|([^}|]+)[^}]*\}\}', r'[[\1 \2]]', v, flags=re.I)
                names = [re.sub(r'\s*\(.*?\)', '', n).strip() for n in re.findall(r'\[\[([^\]|#]+)', v)]
                if not names: names = [x.strip() for x in re.split(r'<br\s*/?>|,|\(|;|/| and ', v) if x.strip() and not x.strip().startswith(')')][:3]
                names = [n for n in names if n and not re.search(r'interim|^\d|season|scheme|offense|defense|^\W', n, re.I)]
                if names: got[side] = names
            if got: out[back.get(pg['title'], pg['title'])] = got
    return out


def units(gs, fbs):
    """offense and defense rating per FBS team, points over / held under an average FBS team"""
    ix = {t: i for i, t in enumerate(sorted(fbs))}; F = len(ix)   # index F = pooled FCS
    rows, y = [], []
    for h, a, hs, as_, neu in gs:
        if h not in ix and a not in ix: continue
        for o, d, pts, home in ((h, a, hs, 0 if neu else 1), (a, h, as_, 0)):
            x = np.zeros(2 * (F + 1) + 2)
            x[ix.get(o, F)] = 1; x[F + 1 + ix.get(d, F)] = 1; x[-2] = 1; x[-1] = home
            rows.append(x); y.append(min(pts, CAP_PTS))
    X, y = np.array(rows), np.array(y, float)
    pen = np.full(X.shape[1], 0.5); pen[-2:] = 0
    b = np.linalg.solve(X.T @ X + np.diag(pen), X.T @ y)
    o, d = b[:F], b[F + 1:2 * F + 1]
    return {t: (float(o[i] - o.mean()), float(d.mean() - d[i])) for t, i in ix.items()}


def panel(teams, meta, g, rec, coord):
    ng = defaultdict(int)
    for s in cv.SEASONS:
        for h, a, *_ in g[s]: ng[(s, h)] += 1; ng[(s, a)] += 1
    teams = {s: [t for t in ts if ng[(s, t)] >= 6] for s, ts in teams.items()}
    rat = {}
    for s in cv.SEASONS:
        for t, v in units(g[s], teams[s]).items(): rat[(s, t)] = v
    tal = cv.talent(rec, teams)
    rows = []
    for s in cv.SEASONS:
        for t in teams[s]:
            m = meta.get((s, t)) or {}
            conf = m.get('conf') or ''
            p4 = int(conf in cv.P4_NAMES and not (conf == 'Pac-12' and s >= 2024)) or int(t == '87')
            for k, side in enumerate(('off', 'def')):
                names = (coord.get((s, t)) or {}).get(side) or []
                r = rat.get((s, t))
                # coach keyed by side: an OC who becomes a DC elsewhere isn't a mover
                rows.append({'s': s, 't': f'{t}:{side}', 'tid': t, 'side': side, 'name': m.get('name'), 'conf': conf, 'p4': p4,
                             'srs': r[k] if r else None, 'tal': tal.get((s, t)), 'hc': [f'{cv.norm(n)}|{side}' for n in names], 'hcName': names})
    return rows


def main():
    teams, meta, g, rec, _ = cv.pull()
    titles = {}
    cur = {}
    for (s, t), m in meta.items():
        if m.get('full'): cur.setdefault(t, m['full'])
    for (s, t), m in meta.items():
        full = cv.WIKI_NAME.get(t) or m.get('full') or cur.get(t)
        if full: titles[(s, t)] = f'{s} {full} football team'
    wc = wiki_coords(sorted(set(titles.values())))
    coord = {k: wc.get(v) for k, v in titles.items()}
    rows = panel(teams, meta, g, rec, coord)
    cv.tenures(rows)
    named = sum(1 for r in rows if r['hc']); sole = sum(1 for r in rows if r.get('sole'))
    print('unit-seasons', len(rows), 'named', named, 'sole', sole, 'usable', sum(1 for r in rows if cv.usable(r)))
    res = {}
    for key, side in (('all', None), ('off', 'off'), ('def', 'def')):
        rs = [r for r in rows if side is None or r['side'] == side]
        out = {}
        for total in (False, True):
            b, k, va, sig_c, sig_e = cv.fit_va(rs, total)
            mv, mrows = cv.mover_test(rs, total)
            out['total' if total else 'onField'] = {
                'expect': dict(zip(['const', 'base', 'talent', 'talentMissing', 'p4'], [round(float(x), 3) for x in b])),
                'shrinkK': round(k, 2), 'coordSd': round(float(np.sqrt(sig_c)), 2), 'seasonSd': round(float(np.sqrt(sig_e)), 2),
                'movers': mv, 'walkForward': cv.walk_forward(rs, total)}
            if key == 'all' and not total: out['moverRows'] = mrows
        res[key] = out
        print(key, json.dumps({k: {kk: vv for kk, vv in v.items() if kk != 'moverRows'} if isinstance(v, dict) else v for k, v in out.items() if k != 'moverRows'}))
    ok = {f'{k}.{t}': any(v[t]['movers'].get(m, {}).get('slopeT', 0) >= 2 and v[t]['movers'].get(m, {}).get('gainT', 0) <= -2 for m in ('va', 'akm'))
          and v[t]['walkForward']['res']['gainT'] <= -2 for k, v in res.items() for t in ('onField', 'total')}
    out = {'asof': time.strftime('%Y-%m-%d'), 'seasons': [cv.SEASONS[0], cv.SEASONS[-1]], 'unitSeasons': len(rows), 'named': named, 'sole': sole,
           'usable': sum(1 for r in rows if cv.usable(r)), 'movers': len(cv.movers(rows)), 'capPts': CAP_PTS, 'results': res, 'pass': ok,
           'shipped': False}
    with open(OUT, 'w') as h: json.dump(out, h, indent=1)
    print('pass', ok, 'wrote', OUT)


if __name__ == '__main__':
    main()
