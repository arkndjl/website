#!/usr/bin/env python3
"""CFB ARK Ranking sweep (thread "Improve CFB arkrank team rankings", Oct 29 2026): do better-built efficiency ratings add
to the shipped game model (the ARK Ranking is its neutral-field rating)?

Rows: scripts/data/games_wf/cfb.json.gz (lined FBS games 2017-26, the shipped walk-forward margin m, close L, result res).
Team-game play stats: scripts/cfb_rank_sweep_plays.mjs (ESPN play-by-play on the model's EP curve).
Every candidate is a team rating opponent-adjusted as the model's efficiency (y = mu + O[off] + D[def] + h side, plays
weighted, each team shrunk toward half its last season's final rating with LAM games of weight), rated from the weeks
before each game, entered as home minus away on top of m and the script's own EPA rating: res = m + a + c ppa + b x (fit on tune). Pre-registered before any
outcome was looked at:
  ppa     garbage-time-out EPA a play (the model's own input; b should be ~0, a sanity check)
  all     EPA a play with garbage time kept
  lev     EPA weighted by leverage, 4 wp (1 - wp) from score and clock (no hard cut)
  fumN    fumble recoveries neutral: every fumble charged the league's mean fumble EPA, lost or not
  toN     fumN plus interceptions regressed half way to the league rate on the team's passes
  pass, rush  pass and rush EPA a play, both columns together (a pass-heavy weighting)
  sr      success rate
  havoc   havoc allowed: tackles for loss, sacks and takeaways a play (sign -1)
  asym    offense over defense: (O_h - O_a) + (D_h - D_a) on EPA (+: offense counts more than defense)
  dec4, dec8  EPA with in-season decay, half-life 4 and 8 weeks
Pass bar (project rule): tune 2017-20 paired squared error t <= -1.5 with the expected sign, held out 2021-26 t <= 0
and MAE not worse; reported against the close too (res - L on x). Clustered by game day.
    python3 scripts/cfb_rank_sweep.py [--cached]   -> data/cfb_rank_sweep.json
Result Oct 29 2026 (squared error t, tune / held; b on top of m and own EPA):
  fumN  -1.06 / -4.37, vs the close held -3.66; b positive in 9 of 10 seasons -> retested inside the model
        (scripts/cfb_fumble_test.mjs: log loss t -1.72 / -2.72, MAE -1.25 / -3.02) and SHIPPED (cfb_model.mjs FUMN)
  sr    -2.20 / -1.71, but log loss and MAE flat (as the model's own sr input): not shipped
  toN, pass, passrush: held out only (-5.7, -3.4, -2.8; tune > -1). Rush EPA under-weighted 2021-26 (also the model's
        stuff/line inputs, held only): watch, retest after 2026
  all, lev, havoc, asym, dec4, dec8: fail
"""
import collections
import datetime
import gzip
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import harness as H  # noqa: E402

WF = os.path.join(HERE, 'data', 'games_wf', 'cfb.json.gz')
PLAYS = os.path.join(HERE, '.cache', 'cfb', 'rank_sweep_plays.json.gz')
HIST = os.path.join(HERE, '.cache', 'cfb', 'espn_hist')
OUT = os.path.join(ROOT, 'data', 'cfb_rank_sweep.json')
TUNE, HELD = range(2017, 2021), range(2021, 2027)
LAM, CARRY = 3.0, 0.5
FCS = 'FCS'


def season_games(S):
    return {g['id']: g for g in json.load(open(os.path.join(HIST, f'games{S}.json')))}


def fbs_of(games):
    n = collections.Counter()
    for g in games.values():
        if g.get('grp') == 'fbs':
            n[g['h']] += 1
            n[g['a']] += 1
    return {t for t, c in n.items() if c >= 4}


def metrics(rows):
    """per team-game: {metric: (y, w)}; league constants from all rows (counts only, no outcomes)"""
    F = sum(r['fumE'] for r in rows) / max(1, sum(r['fum'] for r in rows))
    I = sum(r['intE'] for r in rows) / max(1, sum(r['int'] for r in rows))
    ir = sum(r['int'] for r in rows) / max(1, sum(r['pn'] for r in rows))
    out = []
    for r in rows:
        n = r['n']
        if n < 10:
            out.append(None)
            continue
        fumN = r['e'] - r['fumE'] + r['fum'] * F
        intX = 0.5 * r['int'] + 0.5 * r['pn'] * ir
        m = {'ppa': (r['e'] / n, n / 65), 'all': (r['eAll'] / r['nAll'], r['nAll'] / 65), 'lev': (r['lwE'] / r['lw'], r['lw'] / 50),
             'fumN': (fumN / n, n / 65), 'toN': ((fumN - r['intE'] + intX * I) / n, n / 65), 'sr': (r['sr'] / n, n / 65),
             'havoc': ((r['tfl'] + r['sack'] + r['int'] + r['fumL']) / n, n / 65)}
        if r['pn'] >= 5:
            m['pass'] = (r['pe'] / r['pn'], r['pn'] / 30)
        if r['rn'] >= 5:
            m['rush'] = (r['re'] / r['rn'], r['rn'] / 32)
        out.append(m)
    return out


def adjust(obs, teams, prior, lam=LAM):
    """obs: (off, def, y, w, side). Ridge: y = mu + O + D + h s, O/D shrunk to prior with lam. Returns O, D dicts."""
    idx = {t: i for i, t in enumerate(teams)}
    k = len(teams)
    nP = 2 * k + 2
    A = np.zeros((nP, nP))
    b = np.zeros(nP)
    for o, d, y, w, s in obs:
        x = np.zeros(nP)
        x[0] = 1
        x[1] = s
        x[2 + idx[o]] = 1
        x[2 + k + idx[d]] = 1
        A += w * np.outer(x, x)
        b += w * y * x
    for t, i in idx.items():
        po, pd = prior.get(t, (0.0, 0.0))
        A[2 + i, 2 + i] += lam
        b[2 + i] += lam * po
        A[2 + k + i, 2 + k + i] += lam
        b[2 + k + i] += lam * pd
    A[0, 0] += 1e-6
    A[1, 1] += 1e-6
    sol = np.linalg.solve(A, b)
    return {t: (sol[2 + i], sol[2 + k + i]) for t, i in idx.items()}


def build():
    plays = json.load(gzip.open(PLAYS))
    wf = [r for r in json.load(gzip.open(WF)) if r['res'] is not None and r['L'] is not None and r['S'] >= 2017]
    seasons = sorted({r['S'] for r in plays})
    feats = {}                      # game id -> {metric: (O_h, D_h, O_a, D_a)}
    final = {}                      # (S, metric) -> {team: (O, D)}
    names = ['ppa', 'all', 'lev', 'fumN', 'toN', 'sr', 'havoc', 'pass', 'rush', 'dec4', 'dec8']
    for S in seasons:
        G = season_games(S)
        fbs = fbs_of(G)
        tid = lambda t: t if t in fbs else FCS
        rows = [r for r in plays if r['S'] == S and r['g'] in G]
        M = metrics(rows)
        wk = lambda gid: G[gid]['w']
        teams = sorted(fbs) + [FCS]
        keyed = [(r, m, wk(r['g'])) for r, m in zip(rows, M) if m]
        weeks = sorted({G[g]['w'] for g in G if G[g].get('done')})
        targets = collections.defaultdict(list)
        for g in G.values():
            targets[g['w']].append(g)
        for w in weeks + [max(weeks) + 1]:
            past = [(r, m, ww) for r, m, ww in keyed if ww < w]
            cur = {}
            for nm in names:
                base = 'ppa' if nm.startswith('dec') else nm
                hl = {'dec4': 4, 'dec8': 8}.get(nm)
                lastw = max([ww for _, _, ww in past], default=0)
                obs = []
                for r, m, ww in past:
                    if base not in m:
                        continue
                    y, wt = m[base]
                    if hl:
                        wt *= 0.5 ** ((lastw - ww) / hl)
                    obs.append((tid(r['t']), tid(r['d']), y, wt, r['s']))
                pr = {t: (CARRY * v[0], CARRY * v[1]) for t, v in final.get((S - 1, base), {}).items()}
                cur[nm] = adjust(obs, teams, pr) if obs else {t: pr.get(t, (0.0, 0.0)) for t in teams}
            if w > max(weeks):
                for nm in names:
                    if not nm.startswith('dec'):
                        final[(S, nm)] = cur[nm]
                break
            for g in targets[w]:
                h, a = tid(g['h']), tid(g['a'])
                feats[g['id']] = {nm: (*cur[nm].get(h, (0, 0)), *cur[nm].get(a, (0, 0))) for nm in names}
        print(S, len(rows), 'team-games', flush=True)
    return wf, feats


def column(f, nm):
    Oh, Dh, Oa, Da = f[nm]
    return (Oh - Dh) - (Oa - Da)


CANDS = {
    'ppa': (lambda f: [65 * column(f, 'ppa')], 1),
    'all': (lambda f: [65 * column(f, 'all')], 1),
    'lev': (lambda f: [65 * column(f, 'lev')], 1),
    'fumN': (lambda f: [65 * column(f, 'fumN')], 1),
    'toN': (lambda f: [65 * column(f, 'toN')], 1),
    'passrush': (lambda f: [65 * column(f, 'pass'), 65 * column(f, 'rush')], None),
    'pass': (lambda f: [65 * column(f, 'pass')], 1),
    'sr': (lambda f: [100 * column(f, 'sr')], 1),
    'havoc': (lambda f: [100 * column(f, 'havoc')], -1),
    'asym': (lambda f: [65 * ((f['ppa'][0] - f['ppa'][2]) + (f['ppa'][1] - f['ppa'][3]))], None),
    'dec4': (lambda f: [65 * column(f, 'dec4')], 1),
    'dec8': (lambda f: [65 * column(f, 'dec8')], 1),
    'sr+havoc': (lambda f: [100 * column(f, 'sr'), 100 * column(f, 'havoc')], None),
    'sr+havoc+rush': (lambda f: [100 * column(f, 'sr'), 100 * column(f, 'havoc'), 65 * column(f, 'rush')], None),
}


def ols_cl(X, y, c):
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X)
    meat = sum(np.outer(s, s) for s in (X[c == g].T @ e[c == g] for g in np.unique(c)))
    n, k = X.shape
    G = len(np.unique(c))
    V = XtXi @ meat @ XtXi * G / (G - 1) * (n - 1) / (n - k)
    return b, np.sqrt(np.diag(V))


def research(wf, feats):
    rows = [r for r in wf if r['id'] in feats]
    S = np.array([r['S'] for r in rows])
    wk = np.array([r['wk'] for r in rows])
    day = np.array([r['date'][:10] for r in rows])
    y, L, m = (np.array([r[k] for r in rows], float) for k in ('res', 'L', 'm'))
    sig = np.array([r.get('sigma') or 14.5 for r in rows], float)
    tune, held = np.isin(S, TUNE), np.isin(S, HELD)
    early = wk <= 4
    Phi = lambda z: 0.5 * (1 + np.vectorize(math.erf)(np.asarray(z) / math.sqrt(2)))
    win = (y > 0) + 0.5 * (y == 0)
    ll = lambda p: -(win * np.log(np.clip(p, 1e-9, 1)) + (1 - win) * np.log(np.clip(1 - p, 1e-9, 1)))
    out = {'asof': datetime.date.today().isoformat(), 'rows': int(len(rows)), 'tune': [TUNE[0], TUNE[-1]], 'held': [HELD[0], HELD[-1]],
           'lam': LAM, 'carry': CARRY, 'base': {'maeModel': {p: round(float(np.abs(y - m)[mk].mean()), 3) for p, mk in (('tune', tune), ('held', held))},
                                                'maeClose': {p: round(float(np.abs(y - L)[mk].mean()), 3) for p, mk in (('tune', tune), ('held', held))}}, 'cands': {}}
    # every candidate is scored against m plus this script's own EPA rating (same prior carry and shrink), so a gain is
    # the new measure itself and not the half-carried prior that all of them share
    C0 = np.array([CANDS['ppa'][0](feats[r['id']]) for r in rows], float)
    for k, (fx, sg) in CANDS.items():
        X0 = np.array([fx(feats[r['id']]) for r in rows], float)
        X = np.c_[np.ones(len(rows)), C0, X0] if k != 'ppa' else np.c_[np.ones(len(rows)), X0]
        Xb = np.c_[np.ones(len(rows)), C0] if k != 'ppa' else np.ones((len(rows), 1))
        nb = Xb.shape[1]
        o = {}
        for base, nm in ((m, 'model'), (L, 'close')):
            res = y - base
            bt, st = ols_cl(X[tune], res[tune], day[tune])
            bh, sh = ols_cl(X[held], res[held], day[held])
            b0 = np.linalg.lstsq(Xb[tune], res[tune], rcond=None)[0]
            new, old = base + X @ bt, base + Xb @ b0
            r = {'b_tune': [round(float(v), 3) for v in bt[nb:]], 't_tune': [round(float(v), 2) for v in (bt / st)[nb:]],
                 'b_held': [round(float(v), 3) for v in bh[nb:]], 't_held': [round(float(v), 2) for v in (bh / sh)[nb:]]}
            for part, mk in (('tune', tune), ('held', held), ('heldEarly', held & early)):
                pr = H.paired(H.se(new[mk], y[mk]), H.se(old[mk], y[mk]), cluster=day[mk])
                pa = H.paired(np.abs(new - y)[mk], np.abs(old - y)[mk], cluster=day[mk])
                r['se_' + part] = {'d': round(pr['d'], 3), 't': round(pr['t'], 2), 'n': pr['n']}
                r['ae_' + part] = {'d': round(pa['d'], 4), 't': round(pa['t'], 2)}
                if nm == 'model':
                    pl = H.paired(ll(Phi(new / sig))[mk], ll(Phi(old / sig))[mk], cluster=day[mk])
                    r['ll_' + part] = {'d': round(pl['d'], 5), 't': round(pl['t'], 2)}
            o[nm] = r
        mo = o['model']
        signok = sg is None or (mo['b_tune'][0] * sg > 0)
        o['pass'] = bool(signok and mo['se_tune']['t'] <= -1.5 and mo['se_held']['t'] <= 0 and mo['ae_held']['d'] <= 0)
        out['cands'][k] = o
        print(k, json.dumps({'tune': mo['se_tune'], 'held': mo['se_held'], 'b': mo['b_tune'], 'close_held': o['close']['se_held'], 'pass': o['pass']}), flush=True)
    return out


if __name__ == '__main__':
    cache = os.path.join(HERE, '.cache', 'cfb', 'rank_sweep_feats.pkl')
    if '--cached' in sys.argv and os.path.exists(cache):
        import pickle
        wf, feats = pickle.load(open(cache, 'rb'))
    else:
        import pickle
        wf, feats = build()
        pickle.dump((wf, feats), open(cache, 'wb'))
    res = research(wf, feats)
    json.dump(res, open(OUT, 'w'), indent=1)
    print('->', OUT)
