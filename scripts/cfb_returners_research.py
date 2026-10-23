#!/usr/bin/env python3
"""Research: college football players back from a lost season in the preseason prior (Oct 23 2026; the NBA's is PR
#347).

    OMP_NUM_THREADS=1 python3 scripts/cfb_returners_research.py    # -> data/cfb_returners_research.json

The prior (scripts/cfb_roster_prior.py, the live model's PTS_ROSTER) reads returning QB and skill production as the
share of last season's yards thrown, run or caught by players back on the team. A starter hurt all of last season
counts for the few yards he had then, though he is the team's QB or back again: his healthy season never enters.

Returner: back on the team in S (as cfb_roster_prior reads "back"), had QBMIN+ passing yards (or SKMIN+ rushing +
receiving) for the team in S-2, and in S-1 under a quarter of that and no stat line for another team. qbInj / offInj:
the returners' S-2 yards over the team's S-2 totals (the share of a healthy season's production he stands for).
Variants against the kept prior (last, tal, offRet, qbRet, offIn), tuned leave-one-season-out on 2016-20 and held out
2021-26 by cfb_roster_prior's own evaluate:
    sum      qbRet + qbInj and offRet + offInj (each capped at 1: the room is back in full)
    max      max(qbRet, qbInj), max(offRet, offInj)
    sep      qbInj and offInj as their own inputs

Results (Oct 23 2026, data/cfb_returners_research.json): nothing ships. Only 1-14 teams a season get a QB back this way
(25-60 a skill player). Base reproduces the shipped prior (held out MAE 13.065, log loss .4952). sum: tune log loss
t +1.7, max +1.7 (both worse); sep t -1.7 but on a negative qbInj weight (-4.7: a team whose QB missed last season has
its backups' yards counted as returning too, so the term undoes a double count, not a returner gain) and fails the
sign rule; skill alone t +0.2.
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfb_roster_prior as P  # noqa: E402

OUT = os.path.join(P.ROOT, 'data', 'cfb_returners_research.json')
QBMIN, SKMIN = 500.0, 250.0


def injured_back(G, B, onT):
    """(S, team) -> {'qbInj', 'offInj', 'n', 'who'}: returners from a lost season and their S-2 share."""
    out = {}
    for S in G:
        if S - 2 not in B or S - 1 not in B:
            continue
        cur, nxt = onT[S], onT.get(S + 1, {})
        back = lambda aid, t: t in cur.get(aid, ()) or (not cur.get(aid) and t in nxt.get(aid, ()))
        prev1 = B[S - 1]
        on1 = onT[S - 1]
        for t in G[S]['fbs']:
            P2 = B[S - 2].get(t, {})
            pas2 = sum(s.get('pas_YDS', 0) for s in P2.values())
            off2 = sum(s.get('rus_YDS', 0) + s.get('rec_YDS', 0) for s in P2.values())
            qi = oi = 0.0
            who = []
            for aid, s in P2.items():
                if not back(aid, t) or any(u != t for u in on1.get(aid, ())):
                    continue
                s1 = prev1.get(t, {}).get(aid, {})
                py, oy = s.get('pas_YDS', 0), s.get('rus_YDS', 0) + s.get('rec_YDS', 0)
                if py >= QBMIN and s1.get('pas_YDS', 0) < 0.25 * py:
                    qi += py; who.append((s.get('n'), 'QB', py, s1.get('pas_YDS', 0)))
                if oy >= SKMIN and s1.get('rus_YDS', 0) + s1.get('rec_YDS', 0) < 0.25 * oy:
                    oi += oy; who.append((s.get('n'), 'skill', oy, s1.get('rus_YDS', 0) + s1.get('rec_YDS', 0)))
            out[(S, t)] = {'qbInj': qi / pas2 if pas2 > 0 else 0.0, 'offInj': oi / off2 if off2 > 0 else 0.0, 'who': who}
    return out


def main():
    G = P.load_games()
    F = P.finals(G)
    B, onT = P.boxes(G)
    RET = P.returning(G, B, onT)
    TAL, _ = P.talent(G)
    HCN = P.coaches(G) if os.path.exists(P.HC) else {}     # head coach change isn't in the kept prior
    INJ = injured_back(G, B, onT)
    keys0 = ['last', 'tal', 'offRet', 'qbRet', 'offIn']

    def feats(mode):
        R2 = {}
        for k, v in RET.items():
            v = dict(v); j = INJ.get(k, {})
            qi, oi = j.get('qbInj', 0.0), j.get('offInj', 0.0)
            if mode == 'sum':
                v['qbRet'] = min(1.0, v['qbRet'] + qi) if v['qbRet'] is not None else (min(1.0, qi) if qi else None)
                v['offRet'] = min(1.0, v['offRet'] + oi) if v['offRet'] is not None else (min(1.0, oi) if oi else None)
            elif mode == 'max':
                v['qbRet'] = max(v['qbRet'], qi) if v['qbRet'] is not None else (qi or None)
                v['offRet'] = max(v['offRet'], oi) if v['offRet'] is not None else (oi or None)
            R2[k] = v
        X = P.features(G, F, R2, TAL, HCN)
        for k, x in X.items():
            j = INJ.get(k, {})
            x['qbInj'], x['offInj'] = j.get('qbInj', 0.0), j.get('offInj', 0.0)
        return X

    X0 = feats('none')
    run = P.Run(G, F, X0, lam=3, hfa=2.5, sigma=17.131)    # the shipped hyperparameters (data/cfb_roster_prior.json)

    def evaluate(X, keys, weeks=None):
        run.X = X
        ae_t, ll_t = [], []
        for S in P.TUNE:
            a, l, _, _ = run.metrics(keys, [s for s in P.TUNE if s != S], [S], weeks)
            ae_t.append(a); ll_t.append(l)
        a_h, l_h, w, _ = run.metrics(keys, P.TUNE, P.HOLD, weeks)
        return np.concatenate(ae_t), np.concatenate(ll_t), a_h, l_h, w

    n = defaultdict(lambda: [0, 0])
    for (S, t), j in INJ.items():
        n[S][0] += j['qbInj'] > 0; n[S][1] += j['offInj'] > 0
    res = {'rule': {'qbMin': QBMIN, 'skillMin': SKMIN, 'lastSeason': '< 25% of S-2'},
           'teamsWithReturners [qb, skill]': {str(S): v for S, v in sorted(n.items())},
           'examples2026': sorted([(t, j['who']) for (S, t), j in INJ.items() if S == 2026 and j['who']], key=lambda x: -len(x[1]))[:25]}
    base = {w: evaluate(X0, keys0, w) for w in (None, 4)}
    res['base'] = {'tuneMae': P.r4(base[None][0].mean()), 'tuneLL': P.r4(np.nanmean(base[None][1])),
                   'holdMae': P.r4(base[None][2].mean()), 'holdLL': P.r4(np.nanmean(base[None][3]))}
    print('base', res['base'], flush=True)
    res['variants'] = {}
    for name, X, keys in (('sum', feats('sum'), keys0), ('max', feats('max'), keys0), ('sep', X0, keys0 + ['qbInj', 'offInj']),
                          ('sepQB', X0, keys0 + ['qbInj']), ('sepSkill', X0, keys0 + ['offInj'])):
        r = {}
        for w in (None, 4):
            ev = evaluate(X, keys, w); b = base[w]
            r['all' if w is None else 'wk1to4'] = {'tune': {'dLL': P.paired(b[1], ev[1]), 'dMae': P.paired(b[0], ev[0])},
                                                   'hold': {'dLL': P.paired(b[3], ev[3]), 'dMae': P.paired(b[2], ev[2])}}
            if w is None:
                r['w'] = dict(zip(['1'] + keys, [P.r4(v) for v in ev[4]]))
        res['variants'][name] = r
        print(name, r, flush=True)
    res['asof'] = __import__('datetime').date.today().isoformat()
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
