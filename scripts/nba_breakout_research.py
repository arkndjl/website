# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NBA Potential Breakout research: usage scaling and breakout signals, leave-one-season-out (scripts/breakout_lib.py).

    python3 scripts/nba_breakout_research.py [laker_history.json]   # -> data/nba_breakout_fit.json

History: nbarapm.com LAKER_history regular-season rows 1990-2026 (bbref box rates: usage %, TS+, TOV %, BPM, ...),
project files nba-metrics/raw/load_LAKER_history.json. Traded players' stints are pooled by minutes.

A. Usage scaling. Pairs of seasons (400+ MP both), weight = the smaller MP. Next-season TS+ (and TOV %) on this
   season's (shrunk by MP) + age + usage, then + the usage change (dU), then + dU x traits. Held-out error on all pairs
   and on the pairs whose usage rose 3+ points (the case the tab projects).
B. Breakout odds. Rows: 300+ MP this season. Breakout = next season 1000+ MP and BPM 2+ over his established level:
   the higher of this season's BPM shrunk to -2 by MP (k 600) and his 3-season Marcel (a healthy star's bounce-back
   is not a breakout). Baseline logistic: shrunk BPM, ln MP. Candidates one at a time, then the passers
   together."""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import nba_breakout as B  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SRC = '/mnt/project-files/nba-metrics/raw/load_LAKER_history.json'
OUT = os.path.join(ROOT, 'data', 'nba_breakout_fit.json')
Y0 = 1990
RATE = ('usage_pct', 'ts_plus', 'tov_pct', 'ast_pct', 'ftr_plus', 'threepar_plus', 'fg3_plus', 'ft_plus', 'bpm',
        'obpm', 'dbpm', 'points_per_100', 'orb_pct', 'drb_pct', 'c_pct', 'pf_pct', 'pg_pct', 'sg_pct', 'fg2_plus')
K_SHR = 600.0
BPM_REP = -2.0


def seasons(src):
    rows = [r for r in json.load(open(src)) if r['season_type'] == 'RS' and r['year'] >= Y0 - 3]
    by = defaultdict(list)
    for r in rows:
        if r['minutes'] and r['minutes'] > 0:
            by[(r['player_id'], r['year'])].append(r)
    P = {}
    for (pid, y), rs in by.items():
        mp = sum(r['minutes'] for r in rs)
        o = {'pid': pid, 'y': y, 'n': rs[0]['player_name'], 'age': rs[0]['age'], 'mp': mp,
             'fr': max(rs, key=lambda r: r['minutes'])['franchise']}
        for k in RATE:
            v = [(float(r[k]), r['minutes']) for r in rs if isinstance(r.get(k), (int, float))]
            o[k] = sum(a * b for a, b in v) / sum(b for _, b in v) if v else 0.0
        P[(pid, y)] = o
    return P


def shr(bpm, mp):
    return (bpm * mp + BPM_REP * K_SHR) / (mp + K_SHR)


def vacated(P):
    """share of a franchise's usage-minutes this season from players not on it next season (the max-MP team)"""
    tot, gone = defaultdict(float), defaultdict(float)
    for (pid, y), o in P.items():
        um = o['usage_pct'] * o['mp']
        tot[(o['fr'], y)] += um
        nx = P.get((pid, y + 1))
        if nx is None or nx['fr'] != o['fr']:
            gone[(o['fr'], y)] += um
    V = {}
    for (pid, y), o in P.items():
        k = (o['fr'], y)
        nx = P.get((pid, y + 1))
        own = o['usage_pct'] * o['mp'] if (nx is None or nx['fr'] != o['fr']) else 0.0
        V[(pid, y)] = (gone[k] - own) / tot[k] if tot[k] else 0.0
    return V


def marcel(P, pid, y):
    num = den = 0.0
    for lag, w in ((0, 5), (1, 4), (2, 3)):
        o = P.get((pid, y - lag))
        if o:
            num += w * o['bpm'] * o['mp']
            den += w * o['mp']
    return (num + BPM_REP * 1000) / (den + 1000)


# ---------- A. usage scaling ----------
def scaling(P, HT):
    """contextual usage scaling: next-season rate on this season's + dU + dU x context blocks (scripts/nba_breakout.py
    builds the same columns for the live board), ridge strength picked inside each training fold"""
    R = []
    for (pid, y), a in P.items():
        b = P.get((pid, y + 1))
        if y < Y0 or not b or a['mp'] < 400 or b['mp'] < 400:
            continue
        R.append((pid, y, a, b))
    S = np.array([y + 1 for _, y, _, _ in R], float)
    w = np.array([min(a['mp'], b['mp']) for _, _, a, b in R], float)
    du = np.array([b['usage_pct'] - a['usage_pct'] for _, _, a, b in R])
    out = {}
    for tgt in B.TARGETS:
        y = np.array([b[tgt] for _, _, a, b in R])
        F = np.array([B.features(tgt, a, B.history(P, pid, yy), HT.get(pid), d)
                      for (pid, yy, a, b), d in zip(R, du)])
        cols = B.columns(tgt)
        ix = lambda names: [cols.index(c) for c in names]  # noqa: E731
        base_c = B.BASE
        sets = {'base': base_c, 'dU': base_c + ['dU']}
        for blk, traits in B.BLOCKS.items():
            sets[blk] = base_c + ['dU'] + sum([['dU*' + t, t] for t in traits], [])
        sets['full'] = cols
        up3, up6 = du >= 3, du >= 6
        res = {k: {} for k in ('all', 'up3', 'up6')}
        for nm, cs in sets.items():
            X = F[:, ix(cs)]

            def fp(trn, te, X=X):
                lam = pick_lam(X[trn], y[trn], w[trn], S[trn])
                b0, b = L.wls(X[trn], y[trn], w[trn], lam)
                return b0 + X[te] @ b
            preds = {}

            def err_m(m):
                def e(p, te):
                    mm = m[te]
                    return (float((w[te][mm] * (y[te][mm] - p[mm]) ** 2).sum()), float(w[te][mm].sum()) or 1e-9)
                return e
            for key, m in (('all', np.ones(len(y), bool)), ('up3', up3), ('up6', up6)):
                res[key][nm] = L.loso(S, fp, err_m(m))
        cmp = {'dU vs base (all)': L.compare(res['all']['base'], res['all']['dU']),
               'dU vs base (rose 3+)': L.compare(res['up3']['base'], res['up3']['dU']),
               'full vs base (all)': L.compare(res['all']['base'], res['all']['full']),
               'full vs base (rose 3+)': L.compare(res['up3']['base'], res['up3']['full']),
               'full vs base (rose 6+)': L.compare(res['up6']['base'], res['up6']['full']),
               'full vs dU (rose 3+)': L.compare(res['up3']['dU'], res['up3']['full'])}
        blocks = {k: L.compare(res['up3']['dU'], res['up3'][k]) for k in B.BLOCKS}
        L.holm(blocks)
        keep = [k for k in B.BLOCKS if blocks[k]['pass']]
        fin = base_c + ['dU'] + sum([sum([['dU*' + t, t] for t in B.BLOCKS[k]], []) for k in keep], [])
        X = F[:, ix(fin)]

        def fpf(trn, te):
            lam = pick_lam(X[trn], y[trn], w[trn], S[trn])
            b0, b = L.wls(X[trn], y[trn], w[trn], lam)
            return b0 + X[te] @ b

        def e_all(p, te):
            return (float((w[te] * (y[te] - p) ** 2).sum()), float(w[te].sum()))

        def e_up(p, te):
            mm = up3[te]
            return (float((w[te][mm] * (y[te][mm] - p[mm]) ** 2).sum()), float(w[te][mm].sum()) or 1e-9)
        cmp['kept vs base (all)'] = L.compare(res['all']['base'], L.loso(S, fpf, e_all))
        cmp['kept vs base (rose 3+)'] = L.compare(res['up3']['base'], L.loso(S, fpf, e_up))
        lam = pick_lam(X, y, w, S)
        b0, b = L.wls(X, y, w, lam)
        out[tgt] = {'n': len(R), 'n_up3': int(up3.sum()), 'n_up6': int(up6.sum()), 'tests': cmp, 'blocks': blocks,
                    'keep': keep, 'lam': lam, 'fit': {'b0': round(b0, 5), 'cols': fin,
                                                       'b': [round(float(v), 7) for v in b]}}
        print(tgt, flush=True)
        for k, v in cmp.items():
            print('  ', k, v, flush=True)
        for k, v in blocks.items():
            print('   block', k, v, flush=True)
    return out


LAMS = (1e-4, 1e-3, 1e-2, 3e-2, 0.1)


def pick_lam(X, y, w, S):
    """ridge strength from an inner split of the training seasons (every third season held out)"""
    u = sorted(set(S.tolist()))
    hold = np.isin(S, u[1::3])
    best, bl = None, LAMS[0]
    for lam in LAMS:
        b0, b = L.wls(X[~hold], y[~hold], w[~hold], lam)
        e = float((w[hold] * (y[hold] - b0 - X[hold] @ b) ** 2).sum())
        if best is None or e < best:
            best, bl = e, lam
    return bl


# ---------- B. breakout odds (not yet broken out -> first season at the quality bar) ----------
def coach_change():
    """{(franchise, next season): 1 if the franchise opened next season with a different head coach}"""
    C = json.load(open(os.path.join(ROOT, 'scripts', 'nba_coaches.json')))
    out = {}
    for y in C:
        nx = C.get(str(int(y) + 1))
        if not nx:
            continue
        for tm, cs in C[y].items():
            n = nx.get(tm)
            if cs and n:
                out[(B.TM.get(tm, tm), int(y) + 1)] = 1.0 if n[0]['id'] != cs[-1]['id'] else 0.0
    return out


def opportunity(P):
    """MP (/1000) of same-group teammates with a higher shrunk BPM who leave the franchise, and of teammates 32+"""
    by = defaultdict(list)
    for (pid, y), o in P.items():
        by[(o['fr'], y)].append(o)
    out = {}
    for (pid, y), o in P.items():
        g = B.group(o)
        s0 = B.shr(o['bpm'], o['mp'])
        ahead = old = 0.0
        for t in by[(o['fr'], y)]:
            if t['pid'] == pid or B.group(t) != g:
                continue
            nx = P.get((t['pid'], y + 1))
            if B.shr(t['bpm'], t['mp']) > s0 and (nx is None or nx['fr'] != o['fr']):
                ahead += t['mp'] / 1000
            if t['age'] >= 32:
                old += t['mp'] / 1000
        out[(pid, y)] = (ahead, old)
    return out


def breakout(P, V):
    DR = json.load(open(os.path.join(ROOT, 'scripts', 'nba_draft_picks.json')))
    CC = coach_change()
    OP = opportunity(P)
    R = []
    for (pid, y), a in P.items():
        if y < Y0 or y >= 2026 or a['mp'] < 300:
            continue
        if B.career_best(P, pid, y) >= B.BAR:
            continue                                         # already broke out: Standouts, not next up
        b = P.get((pid, y + 1))
        s0 = shr(a['bpm'], a['mp'])
        hit = 1.0 if (b and b['mp'] >= 1000 and shr(b['bpm'], b['mp']) >= B.BAR) else 0.0
        nfr = b['fr'] if b else a['fr']
        R.append((a, s0, hit, V[(pid, y)], marcel(P, pid, y), B.prev_shr(P, pid, y), DR.get(pid),
                  CC.get((nfr, y + 1)), OP[(pid, y)]))
    S = np.array([a['y'] + 1 for a, *_ in R], float)
    y = np.array([r[2] for r in R])
    rows = [B.bo_feats(a, s0, v, m, prev=pv, draft=dr, coach=cc, opp=op) for a, s0, _, v, m, pv, dr, cc, op in R]
    base = np.array([r['base'] for r in rows])
    cands = {k: np.array([r[k] for r in rows]) for k in B.BO_CANDS}
    cands2 = {k: np.array([r[k] for r in rows]) for k in B.BO_CANDS2}
    has_cc = np.array([cc is not None for *_, cc, _ in R])

    def ll(p, te):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return (float(-(y[te] * np.log(p) + (1 - y[te]) * np.log(1 - p)).sum()), float(te.sum()))

    def run(X, mask=None):
        def fp(trn, te):
            if mask is not None:
                trn = trn & mask
            b0, b = L.logit(X[trn], y[trn])
            return L.sig(b0 + X[te] @ b)
        return L.loso(S, fp, ll) if mask is None else _loso_mask(S, mask, fp, ll)
    rb = run(base)
    res = {k: L.compare(rb, run(np.column_stack([base, X]))) for k, X in cands.items()}
    L.holm(res)
    keep = [k for k in cands if res[k]['pass']]
    X1 = np.column_stack([base] + [cands[k] for k in keep])
    r1 = run(X1)
    stage1 = L.compare(rb, r1)
    print('population', len(y), 'rate', round(float(y.mean()), 4), flush=True)
    for k, v in res.items():
        print(' ', k, v, flush=True)
    print(' stage 1', keep, stage1, flush=True)
    # ---- stage 2: each alone on top of the stage-1 model ----
    res2 = {}
    for k, Xc in cands2.items():
        if k == 'coaching change':
            res2[k] = L.compare(run(X1, has_cc), run(np.column_stack([X1, Xc]), has_cc))
        else:
            res2[k] = L.compare(r1, run(np.column_stack([X1, Xc])))
        print('  s2', k, res2[k], flush=True)
    # splines on shrunk BPM, age, ln MP
    Xs = np.column_stack([X1, B.spline(base[:, 0], B.KN_S), B.spline(np.array([a['age'] for a, *_ in R], float), B.KN_A),
                          B.spline(base[:, 1], B.KN_M)])
    res2['splines'] = L.compare(r1, run(Xs))
    print('  s2 splines', res2['splines'], flush=True)
    # Platt on inner held-out predictions
    def fp_platt(trn, te):
        inner = np.zeros(len(y))
        for s in sorted(set(S[trn].tolist())):
            it = trn & (S == s)
            b0, b = L.logit(X1[trn & ~it], y[trn & ~it])
            inner[it] = b0 + X1[it] @ b
        a0, a1 = L.logit(inner[trn][:, None], y[trn], lam=1e-6)
        b0, b = L.logit(X1[trn], y[trn])
        return L.sig(a0 + a1[0] * (b0 + X1[te] @ b))
    res2['platt'] = L.compare(r1, L.loso(S, fp_platt, ll))
    print('  s2 platt', res2['platt'], flush=True)
    # GBM vs logistic, 6 blocks of seasons (fit cost), both on the same blocks
    blocks = _blocks(S, 6)
    lg, gb = {}, {}
    for te_s in blocks:
        te = np.isin(S, te_s)
        trn = ~te
        b0, b = L.logit(X1[trn], y[trn])
        pl = L.sig(b0 + X1[te] @ b)
        tr_s = sorted(set(S[trn].tolist()))
        iv = np.isin(S, tr_s[2::3]) & trn
        _, _, best = L.gbm_fit(X1[trn & ~iv], y[trn & ~iv], rounds=250, lr=0.05, Xv=X1[iv], yv=y[iv])
        f0, trees, _ = L.gbm_fit(X1[trn], y[trn], rounds=best, lr=0.05)
        pg = L.gbm_pred(f0, trees, X1[te])
        for s in te_s:
            m = S[te] == s
            lg[s] = ll(pl[m], S == s)
            gb[s] = ll(pg[m], S == s)
    res2['gbm'] = L.compare(lg, gb)
    print('  s2 gbm', res2['gbm'], flush=True)
    L.holm(res2)
    keep2 = [k for k in B.BO_CANDS2 if res2[k]['pass']]
    X = np.column_stack([X1] + [cands2[k] for k in keep2])
    final = L.compare(rb, run(X))
    vs1 = L.compare(r1, run(X))
    b0, b = L.logit(X, y)
    # held-out calibration of the final model
    pho = np.zeros(len(y))
    for s in sorted(set(S.tolist())):
        te = S == s
        c0, c = L.logit(X[~te], y[~te])
        pho[te] = L.sig(c0 + X[te] @ c)
    cal = []
    for lo, hi in ((0, .03), (.03, .06), (.06, .1), (.1, .2), (.2, .35), (.35, 1)):
        m = (pho >= lo) & (pho < hi)
        if m.sum():
            cal.append([lo, hi, int(m.sum()), round(float(pho[m].mean()), 3), round(float(y[m].mean()), 3)])
    print(' final', keep, keep2, final, 'vs stage 1', vs1, flush=True)
    print(' calib', cal, flush=True)
    return {'bar': B.BAR, 'n': len(y), 'rate': round(float(y.mean()), 4), 'tests': res, 'keep': keep, 'stage1': stage1,
            'tests2': res2, 'keep2': keep2, 'final': final, 'final_vs_stage1': vs1, 'calib': cal,
            'fit': {'b0': round(b0, 5), 'b': [round(float(v), 6) for v in b], 'mu': [round(float(v), 5) for v in X.mean(axis=0)]}}


def _blocks(S, k):
    u = sorted(set(S.tolist()))
    return [u[i::k] for i in range(k)]


def _loso_mask(S, mask, fp, err):
    out = {}
    for s in sorted(set(S[mask].tolist())):
        te = (S == s) & mask
        out[s] = err(fp(~(S == s), te), te)
    return out


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else SRC
    P = seasons(src)
    V = vacated(P)
    HT = json.load(open(os.path.join(ROOT, 'scripts', 'nba_htwt.json')))
    A = scaling(P, HT)
    B = breakout(P, V)
    # league constant: points per 100 = 2 x TS+/100 x (1 - TOV%) x USG x K (K = league TS x plays per 100, by season)
    K = {}
    for y in range(2020, 2027):
        v = [o['points_per_100'] / (2 * o['ts_plus'] / 100 * (1 - o['tov_pct'] / 100) * o['usage_pct'] / 100)
             for o in P.values() if o['y'] == y and o['mp'] > 500 and o['usage_pct'] > 0]
        K[y] = round(float(np.median(v)), 3)
    json.dump({'source': 'LAKER_history RS 1990-2026', 'scaling': A, 'breakout': B, 'K': K,
               'k_shrink': K_SHR, 'bpm_rep': BPM_REP}, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
