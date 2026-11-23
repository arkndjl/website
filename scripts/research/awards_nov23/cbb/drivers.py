# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CBB award driver tests, Nov 23 2026 (preregistered in prereg.md beside this file).

    python3 scripts/research/awards_nov23/cbb/drivers.py     # -> drivers.json, scripts/.cache/awards/cbb_heldout_p.json

Each driver is added on its own to the race's voter model (its cols in data/awards_fit.json); leave one season out,
held-out log P(winner), one-sided paired t vs the voter model alone, Holm at .05 over every test, gain > 0 and most
seasons won. Also writes every player-season's held-out season-end P(win) for Wooden and the position awards
(scripts/.cache/awards/cbb_heldout_p.json: the awards -> FV candidate, fv_test.py). numpy."""
import csv, json, math, os, sys
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, '..', '..', '..')
sys.path.insert(0, SCR)
import numpy as np
import awards_engine as E
import awards_cbb as C
import awards_nba as A
import names as NM
from awards_research import t_sf, holm, L2

ROOT = os.path.join(SCR, '..')
FIT = json.load(open(os.path.join(ROOT, 'data', 'awards_fit.json')))['cbb']
NOCEIL = '/mnt/project-files/cbb/boards/noceilings.csv'


def ap_pre(season):
    """{team key: preseason AP rank} (Sports-Reference polls page, the Pre column)"""
    h = A.fetch(f'cbb_polls_{season}.html', f'https://www.sports-reference.com/cbb/seasons/men/{season}-polls.html')
    out = {}
    for r in A.table(h, 'ap-polls'):
        if r.get('school') in (None, 'School') or not (r.get('week1') or '').isdigit(): continue
        out[NM.team_key(r['school'].replace(' (NY)', ''))] = int(r['week1'])
    return out


def past_fv():
    d = json.load(open(os.path.join(ROOT, 'static', 'data', 'cbb-past.json')))
    out = defaultdict(dict)
    for row in d['rows']:
        r = dict(zip(d['cols'], row))
        k = NM.key(r['name'])
        out[r['season']][k] = max(out[r['season']].get(k, 0), r['fv'])
    return out


def bo_heldout():
    """{(Barttorvik pid, season the BO% is for): held-out P(breakout)}: the CBB breakout model's kept drivers, each
    season's predictions from a fit that left that season's outcomes out (scripts/cbb_breakout_research.py)"""
    import cbb_breakout_research as CR
    import cbb_breakout as B
    import breakout_lib as L
    P, raw = CR.load(CR.SRC)
    Cx = CR.context(P)
    sfit, folds, _ = CR.scaling(P, Cx)
    keep = json.load(open(os.path.join(ROOT, 'data', 'cbb_breakout_fit.json')))['breakout']['keep']
    bar = round(float(np.percentile([B.shr(o['bpm'], o['m']) for o in P.values() if o['y'] >= CR.Y0 and o['m'] >= B.ROLE_M],
                                    B.BAR_PCT)), 1)
    R, out = [], set()
    for (pid, y), a in P.items():
        b = P.get((pid, y + 1))
        if y < CR.Y0 or not b or a['m'] < CR.ROW_M or a['gp'] < CR.ROW_GP: continue
        if B.level(a, B.history(P, pid, y))[0] >= bar:
            out.add((pid, y + 1)); continue
        R.append((pid, y, a, b))
    S = np.array([y + 1 for _, y, _, _ in R], float)
    yv, rows, X6, X0 = [], [], [], []
    fin = folds['ts'][int(S[0])][2]
    for pid, y, a, b in R:
        hist = B.history(P, pid, y)
        s0, cur = B.level(a, hist)
        yv.append(1.0 if B.broke_out(b, bar) else 0.0)
        c = Cx[(pid, y)]
        lv = (c['lvl'], c['nlvl'], c['xfer'])
        v6, v0 = B.features('ts', a, hist, lv, 6.0), B.features('ts', a, hist, lv, 0.0)
        X6.append([v6[k] for k in fin]); X0.append([v0[k] for k in fin])
        rows.append(B.bo_feats(a, s0, cur, B.marcel(hist, y), c, 0.0))
    yv = np.array(yv)
    D6 = np.array(X6) - np.array(X0)
    lowu = np.array([max(0.0, 20 - a['usg']) / 10 for _, _, a, _ in R])
    base = np.array([r['base'] for r in rows])
    cands = {k: np.array([r[k] for r in rows]) for k in B.BO_CANDS if k != 'usage scaling'}

    def scal(s):
        sc = D6 @ folds['ts'][int(s)][1]
        return np.column_stack([sc, sc * lowu])
    ph = np.zeros(len(yv))
    for s in sorted(set(S.tolist())):
        te = S == s
        X = np.column_stack([base] + [scal(s) if k == 'usage scaling' else cands[k] for k in keep])
        b0, bb = L.logit(X[~te], yv[~te])
        ph[te] = L.sig(b0 + X[te] @ bb)
    return {(pid, y + 1): float(p) for (pid, y, _, _), p in zip(R, ph)}, out


def hype():
    """{season: {name key: -ln rank}} on the newest No Ceilings composite dated before March 1 of the season"""
    by = defaultdict(lambda: defaultdict(list))
    for r in csv.DictReader(open(NOCEIL)):
        if r['board_date'][:4].isdigit(): by[int(r['draft_year'])][r['board_date']].append(r)
    out = {}
    for y, d in by.items():
        ok = [k for k in d if k < f'{y}-03-01' and len(d[k]) >= 25]
        if ok: out[y] = {NM.key(r['name']): -math.log(float(r['rank'])) for r in d[max(ok)]}
    return out


def run(races, cols, extra):
    S = [s for s, _, _ in races]
    rr = lambda cs: [([[r[c] for c in cs] for r in p], o) for _, p, o in races]
    a, b = E.loso(rr(cols), S, l2=L2, depth=1), E.loso(rr(cols + extra), S, l2=L2, depth=1)
    pr = E.paired(b, a)
    bb, _, _ = E.fit([x for x in rr(cols + extra) if x[1]], l2=L2, depth=1)
    return {'gain': pr['gain'], 't': pr['t'], 'p': round(t_sf(pr['t'], pr['n'] - 1), 4), 'wins': pr['wins'], 'n': pr['n'],
            'hit': sum(x['hit'] for x in b), 'hit0': sum(x['hit'] for x in a), 'coef': [round(v, 3) for v in bb[-len(extra):]]}


def heldout_p(races, cols):
    """{(pid, season): held-out P(win)} for every pool row: the voter model fit on the other seasons"""
    S = [s for s, _, _ in races]
    out = {}
    for s, pool, _ in races:
        train = [([[r[c] for c in cols] for r in p], o) for t, p, o in races if t != s and o]
        b, mu, sd = E.fit(train, l2=L2, depth=1)
        for r, p in zip(pool, E.prob([[r[c] for c in cols] for r in pool], b, mu, sd)): out[(r['id'], s)] = p
    return out


def main():
    base = C.seasons_data()['wooden']
    races = dict(wooden=base, **C.more_races(base))
    FV, BO, HY = past_fv(), bo_heldout(), hype()
    bo, bo_out = BO
    nap = nfv = nbo = 0
    for s, pool, _ in base:
        ap = ap_pre(s)
        for r in pool:
            k = NM.key(r['n'])
            f = FV.get(s - 1, {}).get(k)
            r['pre_fv'] = f if f is not None else 20.0
            rk = ap.get(NM.team_key(r['tm']))
            r['ap_pre'] = 26.0 - rk if rk else 0.0
            r['bo'] = bo.get((r['id'], s), 0.0)
            r['bo_out'] = 1.0 if (r['id'], s) in bo_out else 0.0
            h = HY.get(s, {}).get(k)
            r['hype'] = h if h is not None else -math.log(75)
            nap += rk is not None; nfv += f is not None; nbo += (r['id'], s) in bo
        teams = {NM.team_key(r['tm']) for r in pool}
        miss = [t for t in ap if t not in teams]
        if miss: print('cbb', s, 'AP teams not matched', miss)
    print('rows with a preseason AP team', nap, 'with a past FV', nfv, 'with a held-out BO%', nbo)
    for s, pool, o in base:
        if o:
            w = pool[o[0]]
            print('  Wooden', s, w['n'], 'pre FV', w['pre_fv'], 'AP pre', w['ap_pre'], 'BO%', round(w['bo'], 3), 'out' if w['bo_out'] else '')
    TESTS = [(aw, ex) for aw in races for ex in (['pre_fv'], ['ap_pre'], ['bo', 'bo_out'])]
    res = []
    for aw, ex in TESTS:
        r = run(races[aw], [c for c in FIT[aw]['cols'] if c != 'ap_pre'], ex)
        res.append(dict(award=aw, driver='+'.join(ex), **r)); print(aw, ex, r, flush=True)
    hy = [x for x in base if x[0] >= 2022]
    r = run(hy, FIT['wooden']['cols'], ['hype'])
    res.append(dict(award='wooden', driver='hype (2022-26)', **r)); print('wooden hype', r)
    ok = holm([r['p'] for r in res])
    for r, k in zip(res, ok): r['pass'] = bool(k and r['gain'] > 0 and r['wins'] * 2 > r['n'])
    print('\n| award | driver | gain | t | p | wins/n | hits (with vs without) | pass |')
    for r in res:
        print(f"| {r['award']} | {r['driver']} | {r['gain']:+.3f} | {r['t']} | {r['p']} | {r['wins']}/{r['n']} | {r['hit']} vs {r['hit0']} | {'PASS' if r['pass'] else 'fail'} |")
    json.dump({'tests': res, 'holm_n': len(res)}, open(os.path.join(HERE, 'drivers.json'), 'w'), indent=1)
    # held-out season-end P(win) for the awards -> FV test (voter model cols only: no FV, no board term)
    HP = {aw: heldout_p(races[aw], [c for c in FIT[aw]['cols'] if c != 'ap_pre']) for aw in ('wooden', 'cousy', 'west', 'erving', 'malone', 'kareem')}
    rows = defaultdict(dict)
    for aw, d in HP.items():
        for (pid, s), p in d.items(): rows[f'{pid}|{s}'][aw] = round(p, 6)
    json.dump(rows, open(os.path.join(SCR, '.cache', 'awards', 'cbb_heldout_p.json'), 'w'), separators=(',', ':'))


if __name__ == '__main__':
    main()
