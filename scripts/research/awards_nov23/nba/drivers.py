# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NBA award driver tests, Nov 23 2026 (preregistered in prereg.md beside this file).

    python3 scripts/research/awards_nov23/nba/drivers.py     # -> drivers.json beside it

Each driver is added on its own to the award's voter model (its cols in data/awards_fit.json) and scored the way the
races are gated: leave one season out, held-out log P(winner) (winner races, depth as fitted) or log-likelihood of the
named k (All-NBA, All-Defensive, All-Rookie), one-sided paired t vs the voter model alone, Holm at .05 over every test
here, gain > 0 and most seasons won. numpy."""
import json, math, os, sys
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, '..', '..', '..')
sys.path.insert(0, SCR)
import numpy as np
import awards_engine as E
import awards_nba as A
import awards_more as M
import names as NM
from awards_research import t_sf, holm, L2

ROOT = os.path.join(SCR, '..')
FIT = json.load(open(os.path.join(ROOT, 'data', 'awards_fit.json')))['nba']
BOARDS = '/mnt/project-files/cbb/boards'


def bo_heldout():
    """{(bbref id, season the BO% is for): held-out P(breakout)} from the NBA breakout model's stage 1 (the shipped
    drivers), each season's predictions from a fit that left that season's outcomes out (scripts/nba_breakout_research.py)"""
    import nba_breakout_research as NR
    import nba_breakout as B
    import breakout_lib as L
    P = NR.seasons(NR.SRC)
    V = NR.vacated(P)
    keep = json.load(open(os.path.join(ROOT, 'data', 'nba_breakout_fit.json')))['breakout']['keep']
    DR = json.load(open(os.path.join(SCR, 'nba_draft_picks.json')))
    CC, OP = NR.coach_change(), NR.opportunity(P)
    R, out_of_pop = [], set()
    for (pid, y), a in P.items():
        if y < NR.Y0 or a['mp'] < 300: continue
        if B.career_best(P, pid, y) >= B.BAR:
            out_of_pop.add((pid, y + 1)); continue
        b = P.get((pid, y + 1))
        s0 = NR.shr(a['bpm'], a['mp'])
        hit = 1.0 if (b and b['mp'] >= 1000 and NR.shr(b['bpm'], b['mp']) >= B.BAR) else 0.0
        nfr = b['fr'] if b else a['fr']
        R.append((pid, y, a, s0, hit, V[(pid, y)], NR.marcel(P, pid, y), B.prev_shr(P, pid, y), DR.get(pid),
                  CC.get((nfr, y + 1)), OP[(pid, y)]))
    S = np.array([r[1] + 1 for r in R], float)
    yv = np.array([r[4] for r in R])
    rows = [B.bo_feats(a, s0, v, m, prev=pv, draft=dr, coach=cc, opp=op) for _, _, a, s0, _, v, m, pv, dr, cc, op in R]
    X = np.column_stack([np.array([r['base'] for r in rows])] + [np.array([r[k] for r in rows]) for k in keep])
    ph = np.zeros(len(yv))
    for s in sorted(set(S.tolist())):
        te = S == s
        b0, b = L.logit(X[~te], yv[~te])
        ph[te] = L.sig(b0 + X[te] @ b)
    return {(r[0], r[1] + 1): float(p) for r, p in zip(R, ph)}, out_of_pop


def boards():
    """{draft year: {name key: -ln mean rank}} on the final pre-draft boards (ESPN, NBADraft.net)"""
    import csv
    ranks = defaultdict(lambda: defaultdict(list))
    names = defaultdict(dict)
    for fn in ('espn.csv', 'nbadraftnet.csv'):
        for r in csv.DictReader(open(os.path.join(BOARDS, fn))):
            try: y, rk = int(r['draft_year']), float(r['rank'])
            except ValueError: continue
            k = NM.key(r['name'])
            ranks[y][k].append(rk); names[y][k] = r['name']
    return {y: {k: -math.log(sum(v) / len(v)) for k, v in d.items()} for y, d in ranks.items()}, names


def cbb_fv():
    """{draft year: {name key: FV on the CBB past board of his last college season}}"""
    d = json.load(open(os.path.join(ROOT, 'static', 'data', 'cbb-past.json')))
    C = d['cols']
    out = defaultdict(dict)
    for row in d['rows']:
        r = dict(zip(C, row))
        if r.get('draft'):
            k = NM.key(r['name'])
            if r['season'] >= out[r['draft']].get(k, (0, 0))[0]: out[r['draft']][k] = (r['season'], r['fv'])
    return {y: {k: v[1] for k, v in m.items()} for y, m in out.items()}


def rookie_terms(races):
    DR = json.load(open(os.path.join(SCR, 'nba_draft_picks.json')))
    BD, BN = boards()
    FV = cbb_fv()
    hit = tot = 0
    for s, pool, _ in races:
        dy = s - 1
        for r in pool:
            d = DR.get(r['id'])
            r['ln_pick'] = math.log(d[1]) if d and d[0] == dy and d[1] else math.log(61)
            k = NM.key(r['n'])
            c = BD.get(dy, {}).get(k)
            if c is None:
                c = next((v for kk, v in BD.get(dy, {}).items() if NM.same(BN[dy][kk], r['n'])), None)
            r['cons'] = c if c is not None else -math.log(150)
            fv = FV.get(dy, {}).get(k)
            r['cbb_fv'] = fv if fv is not None else 20.0
            r['no_college'] = 0.0 if fv is not None else 1.0
            tot += 1; hit += c is not None
    print('rookies on a final board', hit, 'of', tot)


def run(races, cols, extra, depth, k):
    S = [s for s, _, _ in races]
    rr = lambda cs: [([[r[c] for c in cs] for r in p], o) for _, p, o in races]
    if k:
        a, b = E.loso_k(rr(cols), S, k, l2=L2), E.loso_k(rr(cols + extra), S, k, l2=L2)
    else:
        a, b = E.loso(rr(cols), S, l2=L2, depth=depth), E.loso(rr(cols + extra), S, l2=L2, depth=depth)
    pr = E.paired(b, a)
    bb, mu, sd = E.fit([x for x in rr(cols + extra) if x[1]], l2=L2, depth=k or depth)
    return {'gain': pr['gain'], 't': pr['t'], 'p': round(t_sf(pr['t'], pr['n'] - 1), 4), 'wins': pr['wins'], 'n': pr['n'],
            'hit': sum(x['hit'] for x in b), 'hit0': sum(x['hit'] for x in a), 'coef': [round(v, 3) for v in bb[-len(extra):]]}


def main():
    R0 = A.seasons_data()
    for aw in ('mvp', 'dpoy', 'roy'):
        for s, pool, _ in R0[aw]: A.annotate(s, pool)
    ALL, _ = M.allnba_races()
    for s, pool, _ in ALL: A.annotate(s, pool)
    MR, _ = A.more_races()
    races = dict(R0, allnba=ALL, **MR)
    for s, pool, _ in races['mvp']:
        top = max(r['ppg'] for r in pool)
        for r in pool: r['ppg_title'] = 1.0 if r['ppg'] == top else 0.0
    rookie_terms(races['roy']); rookie_terms(races['allrookie'])
    bo, out = bo_heldout()
    n_bo = 0
    for s, pool, _ in races['mip']:
        for r in pool:
            r['bo'] = bo.get((r['id'], s), 0.0)
            r['bo_out'] = 1.0 if (r['id'], s) in out else 0.0
            n_bo += (r['id'], s) in bo
    print('MIP rows with a held-out BO%', n_bo)
    for s, pool, o in races['mip']:
        if o: w = pool[o[0]]; print('  MIP', s, w['n'], 'BO%', round(w['bo'], 3), 'out' if w['bo_out'] else '')
    for s, pool, _ in races['coy']:
        for r in pool: r['age'] = 0
    TESTS = [('mvp', ['pre_vorx']), ('mvp', ['pre_sxpm']), ('mvp', ['prev_share_mvp']), ('mvp', ['age']), ('mvp', ['ppg_title']),
             ('allnba', ['pre_vorx']), ('allnba', ['pre_sxpm']), ('allnba', ['age']),
             ('dpoy', ['pre_dxpm']), ('dpoy', ['prev_share_dpoy']),
             ('roy', ['ln_pick']), ('roy', ['cons']), ('roy', ['cbb_fv', 'no_college']), ('roy', ['age']),
             ('smoy', ['pre_vorx']), ('smoy', ['prev_share_smoy']),
             ('mip', ['bo', 'bo_out']), ('mip', ['age']),
             ('allrookie', ['ln_pick']), ('allrookie', ['cons']),
             ('alldef', ['pre_dxpm']), ('coy', ['pre_wp'])]
    res = []
    for aw, ex in TESTS:
        f = FIT[aw]
        r = run(races[aw], f['cols'], ex, f.get('depth', 3), f.get('k'))
        res.append(dict(award=aw, driver='+'.join(ex), **r))
        print(aw, ex, r, flush=True)
    ok = holm([r['p'] for r in res])
    for r, k in zip(res, ok):
        r['pass'] = bool(k and r['gain'] > 0 and r['wins'] * 2 > r['n'])
    print('\n| award | driver | gain | t | p | wins/n | hits (with vs without) | pass |')
    for r in res:
        print(f"| {r['award']} | {r['driver']} | {r['gain']:+.3f} | {r['t']} | {r['p']} | {r['wins']}/{r['n']} | {r['hit']} vs {r['hit0']} | {'PASS' if r['pass'] else 'fail'} |")
    json.dump({'tests': res, 'holm_n': len(res)}, open(os.path.join(HERE, 'drivers.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
