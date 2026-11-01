#!/usr/bin/env python3
"""Backtest: do NHL badges (scripts/nhl_badges.py) predict next season's value beyond what the board already has?

    python3 scripts/nhl_badge_backtest.py      # needs MoneyPuck's season summaries in scripts/.cache/nhl/mp
                                               # (scripts/nhl_players.py pulls them) -> data/nhl_badge_backtest.json

Rows: every forward, defenceman and goalie in the badge pool in season S (2008-09 to 2024-25; skaters 200+ minutes,
goalies 600+), joined by NHL id to the board's season files (static/data/nhl-war/<S>.json).
Outcome: his descriptive WAR the next season, scaled to 82 team games (0 when he played no NHL games: replacement).
Held fixed: this season's WAR, pWAR (the board's projection) and HPM.
Per candidate:
  r, k     year-to-year r of the raw stat (pool both seasons) and k = n (1 - r) / r at the pairs' mean volume n;
           r < .15 is noise and the candidate is dropped
  t        the badge z's coefficient in next WAR ~ WAR + pWAR + HPM + z, standard error clustered by player
  oos      leave one season out: the gain in out-of-sample R^2 (x100) over the controls alone
  pass     t >= 2, oos > 0 (a badge is a good thing, so the sign has to be positive)
Passers then go in together (the joint fit, per group); a passer whose joint t drops under 2 or whose joint
leave-one-season-out gain over the others is not positive does not ship.

Results (Nov 1 2026; 17 seasons, 7,561 forward rows / 1,394 players, 4,173 defence / 783, 1,118 goalie / 206; full
numbers in the JSON, summary in the SHIP comment of scripts/nhl_badges.py):
  F  ship Scorer, Shooter, Playmaker, Play Driver, Takeaways (alone t 6.1-12.5; joint t 3.7-9.1; joint oos +3.0);
     Chance Getter and Power Play pass alone but not next to them; Sniper, Shot Suppressor fail; Physical, Shot Blocker,
     Faceoffs predict LOWER next WAR (t -7.6, -5.4, -2.1)
  D  ship Chance Getter, Shot Suppressor, Takeaways (joint t 4.5-6.5, joint oos +3.0); Scorer, Shooter, Playmaker
     pass alone, not next to Chance Getter; Play Driver, Power Play fail; Physical, Shot Blocker negative
  G  none: Shot Stopper (GSAx a shot) year-to-year r .12, High Danger t 1.0, Rebound Control .6, Puck Control .9
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import nhl_badges as B

WARD = os.path.join(ROOT, 'static', 'data', 'nhl-war')
OUT = os.path.join(ROOT, 'data', 'nhl_badge_backtest.json')
FIRST, LAST = 2009, 2025          # badge seasons; outcome season S + 1 <= 2026
CTRL = ['war', 'pwar', 'hpm']


def season_file(S):
    d = json.load(open(os.path.join(WARD, f'{S}.json')))
    return d['games'], {p['id']: p for p in d['players']}


def ols(X, y):
    X1 = np.column_stack([np.ones(len(y)), X])
    b, *_ = np.linalg.lstsq(X1, y, rcond=None)
    return b, X1


def cluster_t(X, y, cl):
    """OLS with CR1 cluster-robust standard errors; t of the last column"""
    b, X1 = ols(X, y)
    e = y - X1 @ b
    XtXi = np.linalg.inv(X1.T @ X1)
    meat = np.zeros((X1.shape[1],) * 2)
    for c in np.unique(cl):
        m = cl == c
        u = X1[m].T @ e[m]
        meat += np.outer(u, u)
    G, n, k = len(np.unique(cl)), len(y), X1.shape[1]
    V = XtXi @ meat @ XtXi * G / (G - 1) * (n - 1) / (n - k)
    return float(b[-1] / math.sqrt(V[-1, -1])), float(b[-1])


def loso(X0, X1, y, s):
    """out-of-sample R^2 gain x100 of X1 over X0, leaving one season out at a time"""
    sse0 = sse1 = sst = 0.0
    for v in np.unique(s):
        tr, te = s != v, s == v
        b0, _ = ols(X0[tr], y[tr]); b1, _ = ols(X1[tr], y[tr])
        p0 = b0[0] + X0[te] @ b0[1:]; p1 = b1[0] + X1[te] @ b1[1:]
        sse0 += ((y[te] - p0) ** 2).sum(); sse1 += ((y[te] - p1) ** 2).sum(); sst += ((y[te] - y[tr].mean()) ** 2).sum()
    return 100 * (sse0 - sse1) / sst


def r3(x):
    return None if x is None or not math.isfinite(x) else round(float(x), 3)


def main():
    raw = {S: B.raw(S) for S in range(FIRST - 1, LAST + 2)}
    files = {S: season_file(S) for S in range(FIRST, LAST + 2)}
    out = {'method': 'see scripts/nhl_badge_backtest.py', 'controls': CTRL, 'outcome': 'next-season WAR per 82 team games',
           'groups': {}}
    for g in 'FDG':
        res = {'badges': {}}
        zs = {}
        for key, name, grps, *_ in B.CANDS:
            if g not in grps:
                continue
            # year-to-year r on raw values, pool both seasons
            a, bb, nn = [], [], []
            for S in range(FIRST - 1, LAST + 1):
                d0, d1 = raw[S][key], raw[S + 1][key]
                for pid, (gg, v, n, m) in d0.items():
                    q = d1.get(pid)
                    if gg == g and m >= B.MIN_TOI[g] and q and q[0] == g and q[3] >= B.MIN_TOI[g]:
                        a.append(v); bb.append(q[1]); nn.append((n + q[2]) / 2)
            r = float(np.corrcoef(a, bb)[0, 1]) if len(a) > 30 else float('nan')
            n = float(np.mean(nn)) if nn else float('nan')
            k = n * (1 - r) / r if r > 0 else None
            ent = {'name': name, 'pairs': len(a), 'r': r3(r), 'volN': r3(n), 'k': r3(k)}
            res['badges'][key] = ent
            if not (r >= .15):
                ent['pass'] = False; ent['why'] = 'year-to-year r under .15'
                continue
            # rows
            rows = []
            for S in range(FIRST, LAST + 1):
                games, F0 = files[S]
                g1, F1 = files[S + 1]
                Z = B.regressed(raw[S][key], k, 82)
                for pid, (gg, v, z, pc) in Z.items():
                    p = F0.get(pid)
                    if gg != g or not p:
                        continue
                    nxt = F1.get(pid)
                    y = (nxt['war'] if nxt else 0.0) * 82 / g1
                    rows.append((pid, S, [p[c] for c in CTRL], z, y))
            zs[key] = {(pid, S): z for pid, S, _, z, _ in rows}
            X0 = np.array([x[2] for x in rows]); z = np.array([x[3] for x in rows]); y = np.array([x[4] for x in rows])
            cl = np.array([x[0] for x in rows]); s = np.array([x[1] for x in rows])
            X1 = np.column_stack([X0, z])
            t, b = cluster_t(X1, y, cl)
            gain = loso(X0, X1, y, s)
            ent.update({'n': len(rows), 'players': int(len(np.unique(cl))), 'coef': r3(b), 't': round(t, 2), 'oosGain': r3(gain),
                        'pass': bool(t >= 2 and gain > 0)})
            if not ent['pass']:
                ent['why'] = 'negative sign' if t <= -2 else ('t under 2' if t < 2 else 'no out-of-sample gain')
            print(g, key, ent, flush=True)
        # the passers together
        keys = [k_ for k_, v in res['badges'].items() if v.get('pass')]
        if keys:
            rows = []
            for S in range(FIRST, LAST + 1):
                games, F0 = files[S]; g1, F1 = files[S + 1]
                for pid, p in F0.items():
                    # a row in any passer's pool; a badge he has no line for (no power-play time) counts as average
                    if any((pid, S) in zs[k_] for k_ in keys):
                        nxt = F1.get(pid)
                        rows.append((pid, S, [p[c] for c in CTRL] + [zs[k_].get((pid, S), 0.0) for k_ in keys], (nxt['war'] if nxt else 0.0) * 82 / g1))
            X = np.array([x[2] for x in rows]); y = np.array([x[3] for x in rows])
            cl = np.array([x[0] for x in rows]); s = np.array([x[1] for x in rows])
            # drop the weakest joint failure and refit until every badge left holds up next to the others
            cols, rounds = list(range(len(keys))), []
            while cols:
                joint = {}
                for j in cols:
                    others = [c for c in range(len(CTRL))] + [len(CTRL) + c for c in cols if c != j]
                    t, b = cluster_t(X[:, others + [len(CTRL) + j]], y, cl)
                    gain = loso(X[:, others], X[:, others + [len(CTRL) + j]], y, s)
                    joint[keys[j]] = {'coef': r3(b), 't': round(t, 2), 'oosGain': r3(gain), 'ship': bool(t >= 2 and gain > 0)}
                rounds.append(joint)
                print(g, 'joint', joint, flush=True)
                bad = [j for j in cols if not joint[keys[j]]['ship']]
                if not bad:
                    break
                cols.remove(min(bad, key=lambda j: joint[keys[j]]['t']))
            sel = list(range(len(CTRL))) + [len(CTRL) + c for c in cols]
            res['joint'] = {'n': len(rows), 'rounds': rounds, 'ship': [keys[c] for c in cols],
                            'oosGainAll': r3(loso(X[:, :len(CTRL)], X[:, sel], y, s))}
            print(g, 'ship', res['joint']['ship'], res['joint']['oosGainAll'], flush=True)
        out['groups'][g] = res
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
