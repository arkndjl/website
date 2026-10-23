#!/usr/bin/env python3
"""Research: college basketball players back from a lost season in the preseason prior (Oct 23 2026; the NBA's is
PR #347).

    OMP_NUM_THREADS=1 python3 scripts/cbb_returners_research.py    # -> data/cbb_returners_research.json

scripts/cbb_roster.py projects each player from last season's Barttorvik line. A player with no line last season (hurt
all year, or a transfer sitting out) was a newcomer: projected from height and recruiting rank like a juco or an
international, and one who played a few minutes before getting hurt was projected off those few minutes. Returner
('back'): no line or under LOWMIN% of the team's minutes last season, HMIN%+ in one of the two seasons before. His own
projection (fit walk-forward on earlier returners) reads the healthy line: BPM, 3-season BPM, minutes, class then,
moved schools, years lost.

Player level: every returner 2016-26, the back model against what he got before (new / ret / tr), BPM error weighted
by the minutes he went on to play, and minutes error. Game level: the full walk (as cbb_roster.py --test), the live
prior (PRIOR_F) with returners off against each variant with them on, tune 2016-20, held out 2021-26:
    shipped   the same terms; rret counts the returners back from a lost season (on the team or not)
    +rback    the returners from a lost season as their own term on top
Results (Oct 23 2026): returners as a separate kind was worse when kept out of rret (t +2.4 on 2016-20); in rret
2016-20 MAE 9.3698 -> 9.3632 (t -3.7), 2021-26 9.7193 -> 9.7182 (t -0.9), lined 2021-26 t -2.6: shipped. rback on
top of the old rret t -3.4 / -0.9, as a second term on the new rret no further gain.
"""
import copy
import json
import os
import sys
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_games as C   # noqa: E402
import cbb_roster as R  # noqa: E402

OUT = os.path.join(C.ROOT, 'data', 'cbb_returners_research.json')


def player_level():
    by = R.load_seasons(); ts = R.team_strength(by)
    rows = defaultdict(list)
    cnt = Counter()
    for y in sorted(by):
        if y - 1 not in by:
            continue
        for pid, r in by[y].items():
            p = by[y - 1].get(pid)
            h = R.healthy({y - k: by[y - k][pid] for k in (1, 2, 3) if y - k in by and pid in by[y - k]}, y)
            k, k0 = R.kind(r, p, h), R.kind(r, p)
            if y >= C.SCORE0:
                cnt[f'{k}<-{k0}'] += 1
            rows[y].append((k, k0, R.xrow(k, r, h if h else p, ts, y), R.xrow(k0, r, p, ts, y), R.f(r['bpm'], R.REPL), R.f(r['min_per'], 0)))
    res = {'kinds2016on': dict(cnt)}
    for lab, ys in (('tune', range(C.SCORE0, C.TUNE_END + 1)), ('held', range(C.TUNE_END + 1, C.LAST + 1))):
        E0, E1, W, M0, M1, A = [], [], [], [], [], []
        for y in ys:
            tr = [q for yy in rows if yy < y for q in rows[yy]]

            def fit(kk, xi, ki):
                Q = [q for q in tr if q[ki] == kk]
                return (R.wls([q[xi] for q in Q], [max(-15, min(15, q[4])) for q in Q], [q[5] / 100 + 0.02 for q in Q]),
                        R.wls([q[xi] for q in Q], [q[5] for q in Q], [1.0] * len(Q)))
            Mb = fit('back', 2, 0); Mo = {k: fit(k, 3, 1) for k in ('new', 'ret', 'tr', 'fr')}
            for q in rows[y]:
                if q[0] != 'back':
                    continue
                b1, m1 = float(np.dot(Mb[0], q[2])), float(np.dot(Mb[1], q[2]))
                b0, m0 = float(np.dot(Mo[q[1]][0], q[3])), float(np.dot(Mo[q[1]][1], q[3]))
                yb = max(-15, min(15, q[4]))
                E0.append(abs(b0 - yb)); E1.append(abs(b1 - yb)); W.append(q[5] / 100 + 0.02)
                M0.append(abs(m0 - q[5])); M1.append(abs(m1 - q[5])); A.append((q[5], m0, m1, yb, b0, b1))
        E0, E1, W, M0, M1, A = map(np.array, (E0, E1, W, M0, M1, A))
        wm = lambda v: round(float((v * W).sum() / W.sum()), 3)
        res[lab] = {'n': len(E0), 'bpmMaeWeighted': [wm(E0), wm(E1)], 't': round(C.paired_t(E1, E0), 2),
                    'minMae': [round(float(M0.mean()), 2), round(float(M1.mean()), 2)], 'tMin': round(C.paired_t(M1, M0), 2),
                    'meanMin [actual, before, back]': [round(float(A[:, i].mean()), 1) for i in (0, 1, 2)],
                    'meanBpmWeighted [actual, before, back]': [wm(A[:, i]) for i in (3, 4, 5)]}
    b = Mb[0]
    res['backModel2026'] = {'bpm': [round(float(v), 3) for v in b],
                            'inputs': ['one', 'bpm', 'bpm3', 'min share', 'bpm x min', 'freshman then', 'moved', 'moved x bpm',
                                       'years lost', 'recruit log rank']}
    return res


def main():
    res = {'rule': {'hmin': R.HMIN, 'lowmin': R.LOWMIN}, 'player': player_level()}
    print('player', res['player'], flush=True)
    games, btname, d1s, tprior, avs = C.load_all()
    F = json.load(open(C.FIT))
    P, feats = F['params'], F['feats']
    base_pf = list(C.PRIOR_F)
    keys = ('rret', 'rback', 'newmin', 'tenure')
    R.BACK = False
    tp0 = copy.deepcopy(tprior); R.add_terms(tp0, keys=keys)
    R.BACK = True
    tp1 = copy.deepcopy(tprior); R.add_terms(tp1, keys=keys)

    def run(tp, pf):
        C.PRIOR_F = pf
        W, rows = C.run_walk(P, games, tp, btname, d1s, avs)
        D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
        return C.walk_pred(Xm, y, S, d1), y, S, d1, D, W.prior_coef(C.LAST + 1)

    b, y, S, d1, D, bc = run(tp0, base_pf)
    ok = ~np.isnan(b) & d1
    tune, held = ok & (S <= C.TUNE_END), ok & (S > C.TUNE_END)
    lined = np.array([g.get('spread') is not None for g, _, _ in D])
    early = np.array([g['date'][5:7] == '11' or (g['date'][5:7] == '12' and int(g['date'][8:10]) < 15) for g, _, _ in D])

    def cmp(p):
        e0, e1 = np.abs(b - y), np.abs(p - y)
        out = {}
        for lab, k in (('tune', tune), ('held', held), ('linedHeld', held & lined), ('earlyTune', tune & early), ('earlyHeld', held & early)):
            out[lab] = [round(float(e0[k].mean()), 4), round(float(e1[k].mean()), 4), round(C.paired_t(e1[k], e0[k]), 2)]
        return out
    res['base'] = {'prior': base_pf, 'coef': {k: round(float(bc[k]), 3) for k in base_pf}}
    variants = {'shipped': base_pf, '+rback': base_pf + ['rback']}
    res['games'] = {}
    for name, pf in variants.items():
        p, _, _, _, _, pc = run(tp1, pf)
        res['games'][name] = {**cmp(p), 'coef': {k: round(float(pc[k]), 3) for k in pf}}
        print(name, res['games'][name], flush=True)
    C.PRIOR_F = base_pf
    res['asof'] = __import__('datetime').date.today().isoformat()
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
