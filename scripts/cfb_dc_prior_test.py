#!/usr/bin/env python3
"""Does a defensive coordinator's career record help the CFB preseason prior? Follow-up to scripts/cfb_coord_va.py,
where a DC's old-job defense rating over roster talent carried to his new job (walk-forward t -3.3 on movers).

Candidate inputs for season S, from the DC on the S infobox (2026: data/cfb_staff.json):
  dcCar   his career defense over talent: mean over his DC seasons before S (any team) of the unit's points-held
          rating over what the roster's talent predicts, z within season, shrunk n / (n + K) toward 0
  dcNew   dcCar for a DC in his first season at the team, else 0 (a returning DC's record is already in `last`)
Tested on top of the live roster prior (data/cfb_roster_prior.json portal.kept) with scripts/cfb_roster_prior.py's
walk and selection rule: tune 2016-20 (prior fit leave-one-season-out), hold out 2021-26; pass = tune t <= -1.5,
weight positive, held-out log loss no worse. Needs the caches of cfb_espn_hist.py (games) and cfb_coord_va.py.
  python3 scripts/cfb_dc_prior_test.py   -> data/cfb_dc_prior_test.json
"""
import json
import os
import sys
import time
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.argv.append('--offline')
import cfb_coach_va as cv  # noqa: E402
import cfb_coord_va as cd  # noqa: E402
import cfb_roster_prior as rp  # noqa: E402

OUT = os.path.join(cv.ROOT, 'data', 'cfb_dc_prior_test.json')
K = 3.0


def dc_records():
    """{(S, tid): dc key} for 2005-26 and {(S, tid): defense over talent z} for 2005-25"""
    teams, meta, g, rec, _ = cv.pull()
    titles, cur = {}, {}
    for (s, t), m in meta.items():
        if m.get('full'): cur.setdefault(t, m['full'])
    for (s, t), m in meta.items():
        full = cv.WIKI_NAME.get(t) or m.get('full') or cur.get(t)
        if full: titles[(s, t)] = f'{s} {full} football team'
    wc = cd.wiki_coords(sorted(set(titles.values())))
    dc = {}
    for k, v in titles.items():
        names = (wc.get(v) or {}).get('def') or []
        if len(names) == 1: dc[k] = cv.norm(names[0])
    staff = json.load(open(os.path.join(cv.ROOT, 'data', 'cfb_staff.json')))
    for t, s in (staff.get('teams', staff)).items():
        n = (s.get('dc') or {}).get('names') or ([s['dc']['name']] if (s.get('dc') or {}).get('name') else [])
        if len(n) == 1: dc[(2026, t)] = cv.norm(n[0])
    rows = cd.panel(teams, meta, g, rec, {})
    over = {}
    for s in cv.SEASONS:
        rs = [r for r in rows if r['s'] == s and r['side'] == 'def' and r['srs'] is not None and r['tal'] is not None]
        if len(rs) < 50: continue
        b = cv.ols([[1, r['tal']] for r in rs], [r['srs'] for r in rs])
        e = np.array([r['srs'] - b[0] - b[1] * r['tal'] for r in rs]); sd = e.std()
        for r, x in zip(rs, e): over[(s, r['tid'])] = float(x / sd)
    return dc, over


def features(dc, over):
    car = defaultdict(list)   # coach -> [(season, z)]
    for (s, t), c in dc.items():
        if (s, t) in over: car[c].append((s, over[(s, t)]))
    F = {}
    for (S, t), c in dc.items():
        xs = [z for s, z in car[c] if s < S]
        v = sum(xs) / (len(xs) + K) if xs else 0.0
        new = dc.get((S - 1, t)) != c
        F[(S, t)] = {'dcCar': v, 'dcNew': v if new else 0.0, 'dcN': len(xs), 'new': new}
    return F


def main():
    dc, over = dc_records()
    D = features(dc, over)
    G = rp.load_games()
    F = rp.finals(G)
    feats = json.load(open(os.path.join(cv.ROOT, 'scripts', 'data', 'cfb_roster_feats.json')))['feats']
    X = {}
    for S in G:
        if S - 1 not in F or str(S) not in feats: continue
        fcs1 = F[S - 1].get(rp.FCS, -20)
        for t in G[S]['fbs']:
            f = feats[str(S)].get(t, {})
            d = D.get((S, t), {})
            X[(S, t)] = {'last': F[S - 1].get(t, fcs1), 'tal': f.get('tal247', -1.0), 'offRet': f.get('offRet', 0.0), 'qbRet': f.get('qbRet', 0.0),
                         'offIn': f.get('offIn', 0.0), 'dcCar': d.get('dcCar', 0.0), 'dcNew': d.get('dcNew', 0.0)}
    cov = {S: {'teams': sum(1 for (s, t) in X if s == S), 'dc': sum(1 for (s, t) in X if s == S and (s, t) in D),
               'withRecord': sum(1 for (s, t) in X if s == S and D.get((s, t), {}).get('dcN', 0) > 0),
               'newWithRecord': sum(1 for (s, t) in X if s == S and D.get((s, t), {}).get('new') and D[(s, t)]['dcN'] > 0)} for S in sorted(G)}
    print('coverage', cov, flush=True)
    base = json.load(open(rp.OUT))
    keys = base['portal']['kept']; hy = base['hyper']
    run = rp.Run(G, F, X, lam=hy['lam'], hfa=hy['hfa'], sigma=hy['sigma'])

    def evaluate(ks, tune, hold, weeks=None):
        ae_t, ll_t = [], []
        for S in tune:
            a, l, _, _ = run.metrics(ks, [s for s in tune if s != S], [S], weeks)
            ae_t.append(a); ll_t.append(l)
        a_h, l_h, w, _ = run.metrics(ks, tune, hold, weeks)
        return np.concatenate(ae_t), np.concatenate(ll_t), a_h, l_h, w

    res = {'asof': time.strftime('%Y-%m-%d'), 'base': keys, 'hyper': hy, 'K': K, 'coverage': {str(k): v for k, v in cov.items()}, 'cands': {}}
    b_all = evaluate(keys, rp.TUNE, rp.HOLD); b_4 = evaluate(keys, rp.TUNE, rp.HOLD, 4)
    for c in ('dcCar', 'dcNew'):
        out = {}
        for lab, b, wk in (('all', b_all, None), ('weeks1to4', b_4, 4)):
            e = evaluate(keys + [c], rp.TUNE, rp.HOLD, wk)
            out[lab] = {'tune': dict(zip(('dLogLoss', 't'), rp.paired(b[1], e[1]))), 'tuneMae': dict(zip(('d', 't'), rp.paired(b[0], e[0]))),
                        'hold': dict(zip(('dLogLoss', 't'), rp.paired(b[3], e[3]))), 'holdMae': dict(zip(('d', 't'), rp.paired(b[2], e[2]))),
                        'w': rp.r4(e[4][-1])}
        a = out['all']
        out['pass'] = bool(a['tune']['t'] <= -1.5 and a['w'] > 0 and a['hold']['dLogLoss'] <= 0)
        res['cands'][c] = out
        print(c, json.dumps(out), flush=True)
    res['shipped'] = False
    with open(OUT, 'w') as h: json.dump(res, h, indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
