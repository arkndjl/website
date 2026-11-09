# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Returning defensive playmakers in the CFB preseason prior (research, Nov 2 2026).

ESPN box scores carry tackles in full only from 2024, so defensive returning production was untestable
(scripts/cfb_roster_prior.py). ESPN's play text names defenders on four plays back to 2014: "sacked by X",
"broken up by X", "pass intercepted X return", "fumbled, forced by X". No tacklers (under 0.1% of runs/catches name
one). Per FBS team-season S-1: each defender's count of those plays (the defence = the side not on offence);
defPlay = the share made by players back in S. defPlayH = the same with S-1 >= 2024 counted from box scores
(sacks + passes defended + interceptions; the play text names few defenders after 2020, ~2 a team in 2026), the
version a live prior can compute. "Back" mirrors the offence rule: the name shows up for the team in S
(play text or box score) or, absent from S entirely, in S+1. Leak-free variant defPlayE reads S from weeks 1-2 only.
Names are joined within a team through scripts/names.py key() (ESPN spells a player the same way in both feeds).

Test = the live prior's own harness (cfb_roster_prior.Run): prior keys last, tal, offRet, qbRet, offIn (PTS_ROSTER),
+ defPlay; tune 2016-20 (prior fit leave-one-season-out), hold out 2021-26, paired per-game log loss and MAE.
247 talent comes from the committed scripts/data/cfb_roster_feats.json (2016+).
  python3 scripts/cfb_defret_research.py   (needs scripts/.cache/cfb: cfb_espn_pbp.py 2014 2026 fills it)
Result (Nov 2 2026): research harness passes (defPlayH tune log loss t -3.08, MAE -2.54; held -1.17 / -0.85; held
2024-26 -1.72 / -2.71, 2021-23 flat), but on the live model (cfb_hist_backtest.mjs DEFRET=1, extras p4,aggr) it is a near
miss: log loss tune t -1.25 (d -.0008), held -1.00 (-.0006), MAE flat (+.01 / +.004); weeks 1-4 log loss -1.76 / -1.83.
Not shipped (CFB gate: tune t <= -1.5). Re-score after the 2026 season joins scripts/data/cfb_hist_md.json.gz, same definitions.
  --feats PATH [--only-feats]   roster feats with defPlay for cfb_hist_backtest.mjs (ROSTER=PATH DEFRET=1)
  --display                     data/cfb_returning.json for the "returning" tab
Writes data/cfb_defret_research.json."""
import gzip
import json
import os
import re
import sys
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfb_roster_prior as RP  # noqa: E402
import names  # noqa: E402

ROOT = RP.ROOT
PBP = os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'espn_pbp')
NAME = r"([A-Z][A-Za-z.'\-]+(?: [A-Z][A-Za-z.'\-]+){0,3})"
PATS = [re.compile(r'sacked by ' + NAME), re.compile(r'broken up by ' + NAME), re.compile(r'pass intercepted (?:by )?' + NAME),
        re.compile(r'forced by ' + NAME)]
BAD = {'TEAM', 'Team'}


def defplays(G):
    """(S, team) -> Counter(name key) of defensive plays, and the same for weeks 1-2."""
    D, E = defaultdict(Counter), defaultdict(Counter)
    for S, g in G.items():
        for e in g['raw']:
            if e['grp'] != 'fbs':
                continue
            p = os.path.join(PBP, f"{e['id']}.json.gz")
            if not os.path.exists(p):
                continue
            d = json.load(gzip.open(p, 'rt'))
            ids = [t['id'] for t in d['teams']]
            if len(ids) != 2:
                continue
            for dr in d['drives']:
                for pl in dr['plays']:
                    x, off = pl.get('x') or '', pl.get('st') or dr.get('tm')
                    if off not in ids:
                        continue
                    de = ids[1] if off == ids[0] else ids[0]
                    for pat in PATS:
                        for m in pat.finditer(x):
                            nm = m.group(1).strip()
                            if nm.split()[0] in BAD or len(nm.split()) < 2:
                                continue
                            k = names.key(nm)
                            D[(S, de)][k] += 1
                            if e['w'] <= 2:
                                E[(S, de)][k] += 1
    return D, E


def box_def(G, D, E, since=2024):
    """from `since` on, replace the play-text counts with box-score sacks + passes defended + interceptions (ESPN's
    play text stops naming most defenders after 2020; its boxes carry full defence from 2024)"""
    D2 = defaultdict(Counter, {k: v for k, v in D.items() if k[0] < since})
    E2 = defaultdict(Counter, {k: v for k, v in E.items() if k[0] < since})
    for S, g in G.items():
        if S < since:
            continue
        for e in g['raw']:
            if e['grp'] != 'fbs':
                continue
            p = os.path.join(RP.DIR, 'box', f"{e['id']}.json")
            if not os.path.exists(p):
                continue
            for tid, P in json.load(open(p)).items():
                for s in P.values():
                    n = s.get('def_SACKS', 0) + s.get('def_PD', 0) + s.get('int_INT', 0)
                    if n and s.get('n'):
                        k = names.key(s['n'])
                        D2[(S, tid)][k] += n
                        if e['w'] <= 2:
                            E2[(S, tid)][k] += n
    return D2, E2


def box_names(G):
    """(S, team) -> set of name keys with any box-score line, all season and weeks 1-2"""
    A, AE = defaultdict(set), defaultdict(set)
    for S, g in G.items():
        for e in g['raw']:
            if e['grp'] != 'fbs':
                continue
            p = os.path.join(RP.DIR, 'box', f"{e['id']}.json")
            if not os.path.exists(p):
                continue
            for tid, P in json.load(open(p)).items():
                for s in P.values():
                    if s.get('n'):
                        k = names.key(s['n'])
                        A[(S, tid)].add(k)
                        if e['w'] <= 2:
                            AE[(S, tid)].add(k)
    return A, AE


def defret(G, D, A, early=None):
    """(S, team) -> share of S-1 defensive plays made by players back in S"""
    cur = defaultdict(set)
    for (S, t), c in D.items():
        cur[(S, t)] |= set(c)
    for k, v in A.items():
        cur[k] |= v
    src = cur if early is None else early
    anywhere = defaultdict(set)
    for (S, t), v in cur.items():
        for k in v:
            anywhere[(S, k)].add(t)
    out = {}
    for S in G:
        for t in G[S]['fbs']:
            P = D.get((S - 1, t))
            if not P or sum(P.values()) < 10:
                continue
            tot = sum(P.values())
            if early is None:
                back = lambda k: k in cur.get((S, t), ()) or (not anywhere.get((S, k)) and k in cur.get((S + 1, t), ()))
            else:
                back = lambda k: k in src.get((S, t), ())
            out[(S, t)] = sum(n for k, n in P.items() if back(k)) / tot
    return out


DISPLAY = os.path.join(ROOT, 'data', 'cfb_returning.json')


def display(G, B, onT, RET, D2, A, early2):
    """data/cfb_returning.json for the CFB "returning" tab (layouts/shortcodes/cfbreturning.html): every FBS
    team's share of last season back, by unit ("back" = played for the team this season, box score or play text):
    QB = passing yards, skill = rushing + receiving yards, defence = sacks + passes defended + interceptions (box
    scores, 2024 on), transfers in = skill yards brought from other FBS teams over the team's own; plus the biggest
    names lost and back on each side."""
    S = max(G)
    dep = {(t.get('logo') or '').rsplit('/', 1)[-1][:-4]: t for t in json.load(open(os.path.join(ROOT, 'static', 'data', 'depth', 'cfb.json')))['teams'] if t.get('logo')}
    RE, DE = RET, defret(G, D2, A)
    nm = {}
    for e in G[S - 1]['raw']:
        p = os.path.join(RP.DIR, 'box', f"{e['id']}.json")
        if e['grp'] == 'fbs' and os.path.exists(p):
            for P in json.load(open(p)).values():
                for a, s in P.items():
                    if s.get('n'):
                        nm[a] = s['n']
    yds = lambda s: s.get('pas_YDS', 0) + s.get('rus_YDS', 0) + s.get('rec_YDS', 0)
    dpl = lambda s: s.get('def_SACKS', 0) + s.get('def_PD', 0) + s.get('int_INT', 0)
    cur = onT[S]
    teams = []
    for t in sorted(G[S]['fbs']):
        r, info = RE.get((S, t)), dep.get(t)
        if not r or not info:
            continue
        P = B[S - 1].get(t, {})
        back = lambda a: t in cur.get(a, ())

        def top(f, kept, n, unit):
            xs = sorted(((f(s), nm[a]) for a, s in P.items() if a in nm and f(s) > 0 and back(a) == kept), reverse=True)[:n]
            return [[who, f"{int(v):,} {unit}"] for v, who in xs]
        pct = lambda v: None if v is None else round(100 * v)
        teams.append({'t': t, 'n': info['n'], 'logo': info['logo'], 'grp': info.get('grp'),
                      'qb': pct(r['qbRet']), 'off': pct(r['offRet']), 'def': pct(DE.get((S, t))), 'in': pct(r['offIn']),
                      'lostO': top(yds, False, 3, 'yds'), 'backO': top(yds, True, 3, 'yds'),
                      'lostD': top(dpl, False, 2, 'plays'), 'backD': top(dpl, True, 2, 'plays')})
    # Pts: the live prior's own weights on these shares (data/cfb_roster_prior.json final: points of preseason rating per
    # share of skill yards back, QB yards back, transfers in), centred on the FBS mean; defence is not in the prior
    fin = json.load(open(os.path.join(ROOT, 'data', 'cfb_roster_prior.json')))['final']
    w = dict(zip(fin['keys'], fin['w']))
    mu = {k: float(np.mean([x[k] for x in teams if x[k] is not None])) for k in ('qb', 'off', 'def')}
    for x in teams:
        x['pts'] = round((w['offRet'] * ((x['off'] if x['off'] is not None else mu['off']) - mu['off'])
                          + w['qbRet'] * ((x['qb'] if x['qb'] is not None else mu['qb']) - mu['qb']) + w['offIn'] * x['in']) / 100, 1)
    teams.sort(key=lambda x: -x['pts'])
    json.dump({'season': S, 'asof': str(__import__('datetime').date.today()), 'w': {k: round(w[k], 2) for k in ('offRet', 'qbRet', 'offIn')},
               'mean': {k: round(v) for k, v in mu.items()}, 'teams': teams},
              open(DISPLAY, 'w'), separators=(',', ':'), allow_nan=False, ensure_ascii=False)
    print('returning:', len(teams), 'teams ->', DISPLAY, flush=True)


def main():
    G = RP.load_games()
    F = RP.finals(G)
    B, onT = RP.boxes(G)
    RET = RP.returning(G, B, onT)
    feats = json.load(open(os.path.join(ROOT, 'scripts', 'data', 'cfb_roster_feats.json')))['feats']
    TAL = {(int(S), t): {'tal': v['tal247'], 'fresh': 0.0} for S, d in feats.items() for t, v in d.items()}
    X = RP.features(G, F, RET, TAL, {})
    D, E = defplays(G)
    A, AE = box_names(G)
    early = defaultdict(set)
    for (S, t), c in E.items():
        early[(S, t)] |= set(c)
    for k, v in AE.items():
        early[k] |= v
    DR, DRE = defret(G, D, A), defret(G, D, A, early)
    D2, E2 = box_def(G, D, E)
    early2 = defaultdict(set)
    for (S, t), c in E2.items():
        early2[(S, t)] |= set(c)
    for k, v in AE.items():
        early2[k] |= v
    DRH = defret(G, D2, A, early2)
    if '--display' in sys.argv:
        display(G, B, onT, RET, D2, A, early2)
        return
    cov = {S: [sum(1 for (s, t) in DR if s == S), len(G[S]['fbs']), round(float(np.mean([sum(D[(S, t)].values()) for t in G[S]['fbs'] if (S, t) in D] or [0])), 1)] for S in G}
    print('coverage (teams with defPlay, FBS teams, plays a team)', cov, flush=True)
    for nm, R in (('defPlay', DR), ('defPlayE', DRE), ('defPlayH', DRH)):
        for S in G:
            vals = [R[(s, t)] for (s, t) in R if s == S]
            mu = float(np.mean(vals)) if vals else 0.0
            for t in G[S]['fbs']:
                if (S, t) in X:
                    X[(S, t)][nm] = R.get((S, t), mu) - mu
    if '--feats' in sys.argv:
        # roster feats with defPlay (defPlayH: the live-computable reading, weeks 1-2 "back"), centred by season
        dst = sys.argv[sys.argv.index('--feats') + 1]
        for S, d in feats.items():
            for t, v in d.items():
                x = X.get((int(S), t))
                v['defPlay'] = round(float(x['defPlayH']), 4) if x and 'defPlayH' in x else 0.0
        json.dump({'feats': feats}, open(dst, 'w'))
        print('wrote', dst, flush=True)
        if '--only-feats' in sys.argv:
            return
    ok = [k for k in X if 'defPlay' in X[k] and k[0] >= 2016]
    print('team-seasons', len(ok), 'mean back', round(float(np.mean([DR[k] for k in DR if k[0] >= 2016])), 3), flush=True)
    # correlation with the offence's returning share (is it new information?)
    a = np.array([[X[k]['defPlay'], X[k]['offRet'], X[k]['qbRet']] for k in ok])
    out = {'note': __doc__.split('\n')[0], 'coverage': {str(k): v for k, v in cov.items()},
           'corr_offRet': round(float(np.corrcoef(a[:, 0], a[:, 1])[0, 1]), 3), 'corr_qbRet': round(float(np.corrcoef(a[:, 0], a[:, 2])[0, 1]), 3)}
    run = RP.Run(G, F, X, lam=3, hfa=2.5, sigma=17.131)
    BASEK = ['last', 'tal', 'offRet', 'qbRet', 'offIn']

    def evaluate(keys, tune, hold):
        ae_t, ll_t = [], []
        for S in tune:
            a_, l_, _, _ = run.metrics(keys, [s for s in tune if s != S], [S])
            ae_t.append(a_); ll_t.append(l_)
        a_h, l_h, w, _ = run.metrics(keys, tune, hold)
        return np.concatenate(ae_t), np.concatenate(ll_t), a_h, l_h, w
    base = evaluate(BASEK, RP.TUNE, RP.HOLD)
    for c in ('defPlay', 'defPlayE', 'defPlayH'):
        ev = evaluate(BASEK + [c], RP.TUNE, RP.HOLD)
        r = {'tune': {'dLogLoss': RP.paired(base[1], ev[1]), 'dMae': RP.paired(base[0], ev[0])},
             'hold': {'dLogLoss': RP.paired(base[3], ev[3]), 'dMae': RP.paired(base[2], ev[2])},
             'w': round(float(ev[4][-1]), 3), 'note': '[mean diff, t]; negative = better'}
        # weeks 1-4 only, where the prior matters most
        wk = lambda e, P: np.array([r_['w'] <= 4 for r_, _ in P])
        _, _, _, pb = run.metrics(BASEK, RP.TUNE, RP.HOLD)
        _, _, _, pn = run.metrics(BASEK + [c], RP.TUNE, RP.HOLD)
        m = wk(None, pb)
        r['holdWeeks1to4Mae'] = RP.paired(base[2][m], ev[2][m])
        yrs = np.array([r_['S'] for r_, _ in pb])
        for a_, b_ in ((2021, 2023), (2024, 2026)):
            mm = (yrs >= a_) & (yrs <= b_)
            r[f'hold{a_}_{b_}'] = {'dLogLoss': RP.paired(base[3][mm], ev[3][mm]), 'dMae': RP.paired(base[2][mm], ev[2][mm])}
        out[c] = r
        print(c, r, flush=True)
    json.dump(out, open(os.path.join(ROOT, 'data', 'cfb_defret_research.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
