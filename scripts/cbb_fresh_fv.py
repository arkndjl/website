#!/usr/bin/env python3
"""Freshman (newcomer) FV candidates on the shipped newcomer drivers (research, Oct 30 2026)

    python3 scripts/cbb_careers_kit.py && python3 scripts/cbb_fresh_fv.py

Each candidate uses only what is known before the season: the team he joins (its conference, last season's box
margin), who else is on the roster (returning minutes, newcomers ranked above him) and his height with his rank.
Run through cbb_fv_core.add_test (class and player folds, clustered t, top 30 per board) on the 2009-16 boards
(whole-career FV) and on 2009-19 (common-horizon FV); `forward`: fit on 2009-16, grade the held-out 2017-19 boards.

Results (Oct 30 2026), nothing shipped: the team's last-season margin (tm_last) passes the folds (class t 2.5 5/5,
2009-19 horizon 2.0 / player 2.8) but not the held-out boards (t 0.3, corr300 worse 3/3). Returning minutes hurt
(t -2.2); returning BPM, newcomers ranked above him, top-ranked on the team, height x rank, height: below the bar.
"""
import math, os, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json
import cbb_data as D
import cbb_fit as F
import cbb_fv_core as C

CANDS = ['pw_new', 'tm_last', 'tm_ret', 'tm_retbpm', 'n_above', 'top_on_team', 'ht_x_rk', 'ht_top', 'ht']


def team_tables(careers):
    line = {}                       # (pid, year) -> season
    roster = defaultdict(list)      # (team, year) -> [(pid, season)]
    for c in careers:
        for s in c['seasons']:
            line[(c['pid'], s['year'])] = s; roster[(s['team'], s['year'])].append((c['pid'], s))
    margin = {k: sum((s['min_per'] or 0) / 100 * (s['bpm'] if s['bpm'] is not None else -4) for _, s in v) for k, v in roster.items()}
    return line, roster, margin


def add_feats(careers, rows):
    line, roster, margin = team_tables(careers)
    rk = {c['pid']: F.rec_feats(c, 9999)['rg_lrk'] for c in careers}
    team = {}
    for c in careers:
        for s in c['seasons']: team[(c['pid'], s['year'])] = (s['team'], s['conf'])
    for r in rows:
        t, conf = team[(r['pid'], r['year'])]; y = r['year']; f = r['f']
        f['pw_new'] = 1.0 if conf in F.POWER and (conf != 'P12' or y <= F.P12_LAST) else 0.0
        f['tm_last'] = margin.get((t, y - 1), -10.0)
        ret = [(p, line[(p, y - 1)]) for p, _ in roster[(t, y)] if (p, y - 1) in line and line[(p, y - 1)]['team'] == t]
        f['tm_ret'] = sum((s['min_per'] or 0) for _, s in ret) / 100
        f['tm_retbpm'] = sum((s['min_per'] or 0) / 100 * (s['bpm'] if s['bpm'] is not None else -4) for _, s in ret)
        mine = f['rg_lrk']
        newc = [p for p, _ in roster[(t, y)] if (p, y - 1) not in line and p != r['pid']]
        f['n_above'] = float(sum(1 for p in newc if rk.get(p, -9) > mine + 1e-9))
        f['top_on_team'] = 1.0 if f['n_above'] == 0 and f['rated'] else 0.0
        h = (f['ht'] or 77.0) - 78.0
        f['ht_x_rk'] = h * (mine + math.log(100))
        f['ht_top'] = h * f['top']


def main():
    fit = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))
    careers, rows, sc = C.load(range(2009, 2020))
    m = fit['models']['newcomer']
    g = [r for r in rows if r['f']['newcomer']]
    add_feats(careers, g)
    old = [dict(r, y=r['yfull']) for r in g if r['year'] <= 2016 and r['last'] <= 2020]
    new = [dict(r, y=r['yk']) for r in g if r['yk'] is not None]
    C.add_test(old, m['kept'], CANDS, m['lam'], 'newcomers, 2009-16 boards, full peak')
    C.add_test(new, m['kept'], CANDS, m['lam'], 'newcomers, 2009-19 boards, k-season peak')



def forward(cands=('tm_last', 'tm_retbpm', 'top_on_team', 'ht')):
    """fit on the 2009-16 boards (whole-career FV), grade the held-out 2017-19 boards (common-horizon FV)"""
    import harness as H
    fit = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))
    careers, rows, sc = C.load(range(2009, 2020))
    m = fit['models']['newcomer']; kept, lam = m['kept'], m['lam']
    g = [r for r in rows if r['f']['newcomer']]
    add_feats(careers, g)
    tr = [dict(r, y=r['yfull']) for r in g if r['year'] <= 2016 and r['last'] <= 2020]
    te = [dict(r, y=r['yk']) for r in g if 2017 <= r['year'] <= 2019 and r['yk'] is not None]
    yt = np.array([r['y'] for r in te], float); yrs = np.array([r['year'] for r in te])
    def run(cols):
        mod = F.fit(tr, F.matrix(tr, cols), list(range(len(cols))), lam)
        P = F.predict(mod, F.matrix(te, cols))[1]; e = F.expected(P)
        tops = [(float(yt[yrs == b][np.argsort(-e[yrs == b])[:30]].mean()), float(np.corrcoef(e[yrs == b][np.argsort(-e[yrs == b])[:300]], yt[yrs == b][np.argsort(-e[yrs == b])[:300]])[0, 1])) for b in (2017, 2018, 2019)]
        return C.row_dev(P, yt).sum(1), tops, mod
    d0, t0, _ = run(kept)
    print('base', [tuple(round(x, 3) for x in t) for t in t0])
    for c in cands:
        d1, t1, mod = run(kept + [c])
        pt = H.paired(d1, d0, np.array([r['pid'] for r in te]))
        print(f'{c:12s} gain {(d0.sum() - d1.sum()) * 100:+.3f}% t {-pt["t"]:+.2f} boards better {sum((d1[yrs == b].sum() < d0[yrs == b].sum()) for b in (2017, 2018, 2019))}/3',
              'top30/corr300', [tuple(round(x, 3) for x in t) for t in t1])


if __name__ == '__main__':
    forward() if 'forward' in sys.argv else main()
