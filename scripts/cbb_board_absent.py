#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The board stage's term for a player on none of today's draft boards (Adonis Ratliff check, Nov 18 2026).

    python3 scripts/cbb_board_absent.py     # fit + held-out test -> scripts/data/cbb_board_absent.json
                                            # (needs the board history in /mnt/project-files/cbb/boards or $CBB_BOARDS)

cbb_fit.board_e gives a player on no board the chance of a June board and the rank he'd get there from his E[FV] alone
(onLogit/onRank, fit on the 2009-16 June boards). That ignores that today's boards left him off: on the 2022-26 classes,
preseason players off No Ceilings' first board with E[FV] 33+ came out +4 to +5 E[FV] too high against the stage's value
at their real June rank (30% made a June board; listed players at the same E, 70%). Listed players (preseason_att) sat
at bias ~0. This refits both on the players off the first board (E from static/data/cbb-past.json fvg, the preseason
grade, on emap 'model'); the live board takes min(the old term, this one), so being off the boards never adds credit.
Kept when it lowers held-out squared error in 4 of 5 classes (leave one class out), over all of them and over E 33+.
Not yet in preseason_sim (the stage map emap 'stage'): that needs a full cbb_fit.py refit.
"""
import json, math, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import cbb_fit as F, cbb_data as D

ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, 'data', 'cbb_board_absent.json')
TOP = 33.0          # the E[FV] the test's top cut starts at
MIN_WINS = 4


def stage_at(C, e, lr):
    mu, sd, W = np.array(C['mean']), np.array(C['sd']), [np.array(w) for w in C['w']]
    z = (np.array([e, max(lr, C['fill'])]) - mu) / sd
    ps = np.cumprod([1 / (1 + math.exp(-max(-30, min(30, w[0] + w[1:] @ z)))) for w in W])
    return F.FLOOR + 10 * (ps[0] + ps[1] + ps[2]) + (C['topMean'] - 50) * ps[3]


def absent_value(C, e, A):
    """E[FV] after the stage for a player off the boards, under the off-board fit A (onLogit, onRank, onSd)"""
    p = 1 / (1 + math.exp(-max(-30, min(30, A['onLogit'][0] + A['onLogit'][1] * e))))
    on = sum(wt * stage_at(C, e, A['onRank'][0] * e + A['onRank'][1] + A['onSd'] * x) for x, wt in zip(*F._GH)) / F._GH[1].sum()
    return (1 - p) * stage_at(C, e, C['fill']) + p * on


def rows(fit):
    C = fit['boards']
    eg = np.linspace(20, 60, 4001); gx = np.array(F.grade_abs(eg, fit['emap']['model'])[2], float)
    nc, es = F.nc_espn()
    past = json.load(open(os.path.join(ROOT, 'static', 'data', 'cbb-past.json'))); c = past['cols']
    out = []
    for y in sorted(nc):
        if not es.get(y): continue
        first = nc[y][min(nc[y])]
        for r in past['rows']:
            x = dict(zip(c, r))
            if x['season'] != y: continue
            k = D.norm(x['name'])
            if k in first: continue
            e = float(np.interp(x['fvg'], gx, eg)); jr = es[y].get(k)
            out.append({'y': y, 'e': e, 'jr': jr, 'oracle': stage_at(C, e, -math.log(jr) if jr else C['fill']),
                        'old': F.board_e(e, None, C)[0]})
    return out


def fit_absent(rr):
    e = np.array([r['e'] for r in rr]); on = np.array([r['jr'] is not None for r in rr], float)
    m0, s0 = e.mean(), e.std(); X = np.c_[np.ones_like(e), (e - m0) / s0]; g = np.zeros(2)
    for _ in range(100):
        p = 1 / (1 + np.exp(-np.clip(X @ g, -30, 30)))
        g = g + np.linalg.solve(X.T @ (X * (p * (1 - p))[:, None]) + 1e-3 * np.eye(2), X.T @ (on - p) - 1e-3 * g)
    lr = np.array([-math.log(r['jr']) for r in rr if r['jr']]); m = on > 0
    b1, b0 = np.polyfit(e[m], lr, 1)
    return {'onLogit': [round(float(g[0] - g[1] * m0 / s0), 6), round(float(g[1] / s0), 6)],
            'onRank': [round(float(b1), 6), round(float(b0), 6)], 'onSd': round(float(np.std(lr - b0 - b1 * e[m], ddof=2)), 4)}


def main():
    fit = json.load(open(os.path.join(ROOT, 'data', 'cbb_fit.json'))); C = fit['boards']
    rr = rows(fit)
    test = {}
    for tag, lo in (('all', 0.0), (f'E{int(TOP)}+', TOP)):
        per = []
        for y in sorted({r['y'] for r in rr}):
            A = fit_absent([r for r in rr if r['y'] != y]); te = [r for r in rr if r['y'] == y and r['e'] >= lo]
            if not te: continue
            old = [r['old'] - r['oracle'] for r in te]
            new = [min(r['old'], absent_value(C, r['e'], A)) - r['oracle'] for r in te]
            per.append({'class': y, 'n': len(te), 'mseOld': round(float(np.mean(np.square(old))), 3), 'mseNew': round(float(np.mean(np.square(new))), 3),
                        'biasOld': round(float(np.mean(old)), 3), 'biasNew': round(float(np.mean(new)), 3)})
        test[tag] = {'wins': sum(p['mseNew'] < p['mseOld'] for p in per), 'classes': per}
        print(tag, 'wins', test[tag]['wins'], '/', len(per), [(p['class'], p['n'], p['mseOld'], p['mseNew']) for p in per])
    keep = all(t['wins'] >= MIN_WINS for t in test.values())
    out = dict(fit_absent(rr), keep=keep, rows=len(rr), onJune=sum(r['jr'] is not None for r in rr), test=test,
               note='players off No Ceilings first board, 2022-26 classes; live uses min(old term, this)')
    json.dump(out, open(OUT, 'w'), indent=1)
    print('kept', keep, '->', OUT)


if __name__ == '__main__':
    main()
