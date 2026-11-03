#!/usr/bin/env python3
"""1NT RWA build: every recent ESEA league player's round win % added per round (data/esea_rwa.json).

    python3 scripts/esea_rwa.py     # after fetch_esea.mjs (esea.yml); reads research/esea_matches.json.gz, the
                                    # run's .cache/esea/rounds.json (this season's maps) and data/esea_rwa_fit.json

Method and test: scripts/esea_rwa_research.py. The ratings use the fit's settings as of the build day.
"""
import gzip
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esea_rwa_research as R  # noqa: E402
import esea_standin_research as SR  # noqa: E402

ROOT = R.ROOT
FIT = R.OUT
CACHE = os.path.join(ROOT, '.cache', 'esea', 'rounds.json')
ESEA = os.path.join(ROOT, 'data', 'esea.json')
OUT = os.path.join(ROOT, 'data', 'esea_rwa.json')
RECENT_DAYS = 150


def full_of(q):
    """fetch_esea.mjs compact line [k, d, a, adr, k2, k3, k4, k5, entries, entryWins, 1v1W, 1v2W, utilDmg, flashed,
    flashSucc, utilSucc, MVPs, rf, ra, nick, id] -> the archive's 26-long box line"""
    f = [0] * 26
    f[0], f[6], f[7], f[8] = q[0], q[1], q[2], q[3]
    f[9], f[10], f[11], f[12] = q[4], q[5], q[6], q[7]
    f[2], f[13], f[14], f[15], f[16], f[17], f[18], f[19], f[20] = q[8], q[9], q[10], q[11], q[12], q[13], q[16], q[14], q[15]
    return f


def live_matches(seen, div, now):
    try:
        rc = json.load(open(CACHE))
    except Exception:
        return [], {}
    out, nick = [], {}
    for mid, L in (rc.get('P') or {}).items():
        if mid in seen or len(L) != 2:
            continue
        (ta, la), (tb, lb) = list(L.items())
        maps = []
        for i in range(min(len(la), len(lb))):
            a, b = la[i] or [], lb[i] or []
            if not a or not b or a[0][17] is None:
                continue
            row = lambda q: [q[20], q[0], q[1], q[2], q[3], full_of(q)]
            maps.append({'s1': a[0][17], 's2': a[0][18], 'p1': [row(q) for q in a if q[20]], 'p2': [row(q) for q in b if q[20]]})
            for q in a + b:
                if q[20]:
                    nick[q[20]] = q[19]
        if maps:
            # the cache keeps no match time: this season's maps count as of the build (no decay at the fit's h)
            out.append({'id': mid, 'at': now, 'season': 99, 'div_r': div, 'maps': maps})
    return out, nick


def main():
    fit = json.load(open(FIT))
    p = fit['params']
    now = time.time()
    d, ms = SR.load()
    for m in ms:
        m['div_r'] = SR.DIV.get(m['div'], 0)
    try:
        es = json.load(open(ESEA))
    except Exception:
        es = {}
    cn = ' %s ' % ((es.get('championship') or {}).get('name') or '')   # "S59 NA Main A - Regular Season"
    div = next((v for k, v in SR.DIV.items() if ' %s ' % k in cn), 0)
    live, nick = live_matches({m['id'] for m in ms}, div, now)
    M = R.Maps(ms + live)
    tune_g = (M.gseason >= 53) & (M.gseason <= R.TUNE[1])
    if p.get('w') == 'ols':
        c = R.contributions(M, np.array([fit['beta'][k] for k in R.STATS]), np.array(fit['mline']), p.get('pm', 0.0))
    else:
        c = R.ark_values(M, tune_g)
    th, ws = R.ratings(M, c, now + 1, p)
    last = np.zeros(len(M.pid))
    np.maximum.at(last, M.p, M.d)
    for x in es.get('members') or []:
        nick.setdefault(x.get('id'), x.get('nick'))
    for x in (es.get('rankings') or {}).get('players') or []:
        nick.setdefault(x.get('id'), x.get('name'))
    inv = {i: q for q, i in M.pid.items()}
    rounds = np.bincount(M.p, M.R, len(M.pid))
    keep = (last >= now - RECENT_DAYS * 86400) | np.isin(np.arange(len(M.pid)), [M.pid[x['id']] for x in es.get('members') or [] if x.get('id') in M.pid])
    # display scale: 0 = the average recent Main player (rounds-weighted); a shift only, gaps are unchanged
    w = M.R * (M.d >= now - RECENT_DAYS * 86400) * (M.dv == 0)
    wp = np.bincount(M.p, w, len(M.pid))
    center = float((th * wp).sum() / max(wp.sum(), 1e-9))
    # a player with no league maps: the mean of this division's recent low-sample players (under 300 rounds); the
    # fit's own prior sat above the average Main player, and new players were too rare in the test to tune it
    dl = np.bincount(M.p, M.R * M.dv, len(M.pid)) / np.maximum(rounds, 1)
    low = keep & (rounds < 300) & (np.abs(dl - div) < 0.5)
    new_v = float(th[low].mean() - center) if low.sum() >= 20 else float(p['g'] * div + p['nu'] - center)
    pl = {}
    for i in np.where(keep)[0]:
        pl[inv[i]] = [round(float(th[i] - center), 2), int(rounds[i])]
    rk = sorted(pl.items(), key=lambda kv: -kv[1][0])
    t = fit['tests']
    out = {'asof': time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime(now)), 'head': fit.get('head', 'ark'),
           'test': {k: t[k] for k in ('rwa_vs_ark', 'pelo+lv+rwa_vs_pelo+lv') if k in t},
           'params': p, 'center': round(center, 3), 'new': round(new_v, 2), 'n': len(pl), 'live_maps': sum(len(m['maps']) for m in live),
           'names': {q: nick[q] for q, _ in rk if nick.get(q)}, 'p': {q: v for q, v in rk}}
    s = json.dumps(out, separators=(',', ':'))
    open(OUT, 'w').write(s)
    print(f'wrote {OUT}: {len(pl)} players, {out["live_maps"]} live maps, {len(s) // 1024} KB', file=sys.stderr)


if __name__ == '__main__':
    main()
