#!/usr/bin/env python3
"""NFL metric audit (Nov 24 2026) on one harness; see prereg.md. Needs prep.py + sv_prep.py caches and
`python3 scripts/nfl_xv.py --prep`. Writes results.json next to this file.
    python3 scripts/research/metric_audit_nov24/nfl/audit.py"""
import json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts')); sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'team_adj_nov24'))
import core  # noqa: E402
import nfl_xv as X, nfl_war as W, nfl_rate as R, nfl_rate_research as RR, nfl_market as MK  # noqa: E402
import nfl_season_value as NSV  # noqa: E402

CACHE = os.path.join(ROOT, 'scripts', '.cache', 'nfl')
YS = list(range(2018, 2026)); PAIRS = YS[:-1]; HIST = list(range(2016, 2026))
PPW, SVPW = 35.5, 36.0
_, VALUE, _ = W.sub_lines()
ALPHA = .4
rng = np.random.default_rng(0)

C = {(y, h): json.load(open(os.path.join(CACHE, f'audit_{y}_{h}.json'))) for y in HIST for h in ('full', 'h1')}
SV = {y: json.load(open(os.path.join(CACHE, f'audit_sv_{y}.json'))) for y in HIST}
S = X.load(); X.zscore(S)
MK.load()
X.SIDE_FIT = False    # baseline = the margin fit as shipped before C3; C3 uses fit_side below


# ------------------------------------------------------------------ XV weights (point in time)
def fit_side(Sx, ys, lam=20):
    """C3: offense columns fit on points scored a game, defense columns on points allowed (negated), centred per season"""
    w = np.zeros(len(X.COLS))
    for side in (0, 1):
        idx = [j for j, (g, _) in enumerate(X.COLS) if (g in X.OFF) == (side == 0)]
        Xm, Y = [], []
        for y in ys:
            d = Sx[y]; T = defaultdict(lambda: np.zeros(len(idx)))
            for p in d['players']:
                g = X.GROUP_OF[p['sub']]
                for k, j in enumerate(idx):
                    if X.COLS[j][0] == g: T[p['t']][k] += p['share'] * p['z'][X.COLS[j][1]]
            ts = list(d['teams'])
            yy = np.array([(d['teams'][t]['pf'] if side == 0 else -d['teams'][t]['pa']) / d['teams'][t]['g'] for t in ts])
            Xm += [T[t] for t in ts]; Y += list(yy - yy.mean())
        Xm, Y = np.array(Xm), np.array(Y)
        mu, sd = Xm.mean(0), Xm.std(0); sd[sd == 0] = 1
        A = np.vstack([(Xm - mu) / sd, math.sqrt(lam) * np.eye(len(idx))]); b = np.concatenate([Y, np.zeros(len(idx))])
        w[idx] = X.nnls(A, b) / sd
    return w


_WC = {}


def weights(excl, side=False):
    k = (tuple(sorted(excl)), side)
    if k not in _WC:
        tr = [v for v in YS if v not in excl]
        w = fit_side(S, tr) if side else X.fit_w(S, tr, 20)
        wd = {f'{g}.{part}': float(v) for (g, part), v in zip(X.COLS, w)}
        _WC[k] = (wd, X.q_means({y: S[y] for y in tr}, wd))
    return _WC[k]


def xv_rows(y, h, excl, side=False):
    """{(pfr, team, side): XV} for capture (y, h) on weights fit without seasons excl"""
    xr = C[(y, h)]['xrows']
    if not xr: return {}
    Sx = {y: {'players': [dict(p) for p in xr]}}
    X.zscore(Sx)
    wd, qm = weights(excl, side)
    out = defaultdict(float)
    for p, v in zip(Sx[y]['players'], X.xv_of(Sx, y, wd, VALUE, qm)):
        out[(p['pfr'], p['t'], 0 if X.GROUP_OF[p['sub']] in X.OFF else 1)] += v
    return out


# ------------------------------------------------------------------ per-season unit values
def units(y, h, excl, side=False):
    """rows: (pid, team key, sh, {metric: value}) for capture (y, h); pid = pfr|side, ST:gsis for special teams"""
    d = C[(y, h)]; xv = xv_rows(y, h, excl, side) if y >= 2018 else {}
    g2p = {g: p for p, g in d['gsis'].items()}
    sv = SV[y][h]
    out = []
    for r in d['rows']:
        k = (r['pfr'], r['t'], r['side'])
        x = xv.get(k)
        board = r['war'] if x is None else ALPHA * x + (1 - ALPHA) * r['war']
        m = {'board': board, 'boardNoST': board, 'avwar': r['war'], 'av': r['av'], 'rxp': board - VALUE.get(r['sub'], 0) * r['sh']}
        if x is not None: m['xv'] = x
        gs = d['gsis'].get(r['pfr'])
        s = sv.get(f'{gs}|{r["t"]}', {}) if gs else {}
        if r['side'] == 0:
            if r['g'] == 'QB': m['sv'] = s.get('qb', 0.0) / SVPW
            elif r['g'] in ('RB', 'WR', 'TE'): m['sv'] = s.get('sk', 0.0) / SVPW
            m['epa'] = s.get('epa', 0.0) / PPW
            if r['g'] == 'QB': m['cpoe'] = s.get('cp', 0.0)
        elif r['g'] in ('DL', 'LB', 'DB'):
            m['sv'] = (s.get('dc', 0.0) - NSV.REPL[r['g']] * r['snaps']) / SVPW
        out.append((f"{r['pfr']}|{r['side']}", f"{r['t']}|{'OD'[r['side']]}", r['sh'], m, r['g'], r['sub'], r['snaps']))
    for gs, v in d['st'].items():
        t = max(v['t'], key=v['t'].get); g = max(1, v.get('g') or 1)
        if t not in d['teams']: continue
        out.append((f'ST:{gs}', f'{t}|O', g / 17, {'board': v['pts'] / PPW, 'st': v['pts'] / PPW}, 'ST', 'ST', 0))
    return out


def board_rate_rows(y, h='full', U=None):
    """rate rows (nfl_rate_research shape) from unit rows: pts = (board WAR pre special teams - average) x 35.5"""
    U = U if U is not None else units(y, h, ())
    acc = {}
    for pid, t, sh, m, g, sub, sn in U:
        if g == 'ST': continue
        pfr = pid.split('|')[0]
        a = acc.setdefault(pfr, {'id': pfr, 'pts': 0.0, 'sn': 0.0, 'shr': 0.0, 'gs': defaultdict(float), 'ss': defaultdict(float)})
        a['pts'] += m['rxp'] * PPW; a['sn'] += sn; a['gs'][g] += sn + .01; a['ss'][sub] += sn + .01
        a['shr'] += sh
    out = {}
    for pfr, a in acc.items():
        if a['sn'] <= 0: continue
        g = max(a['gs'], key=a['gs'].get); sub = max(a['ss'], key=a['ss'].get)
        if g not in R.GROUPS: continue
        out[pfr] = {'id': pfr, 'sub': sub, 'grp': g, 'sn': a['sn'], 'pts': a['pts'], 'shr': a['shr']}
    return out


# in-sample board rate rows for the pXP hyper-parameters (XV in them uses weights fit on all seasons but the season)
DB_ = {y: board_rate_rows(y, U=units(y, 'full', (y,))) for y in HIST}
_PX = {}


def pxp_params(excl_target):
    if excl_target not in _PX:
        tr = [y for y in HIST[:-1] if y != excl_target]
        m, b, xb = RR.means(DB_, tr); mq = RR.mslopes(DB_, tr, m)
        K = RR.fit_k(DB_, tr, 'marcelM', m, b, xb, mq=mq)
        _PX[excl_target] = (K, m, b, xb, mq)
    return _PX[excl_target]


def pxp_of(y, h, excl, target_pair):
    """{pfr: pXP/60} for season y (capture h) with history y-1, y-2, XV on weights without excl, params without target pair"""
    D = {s: board_rate_rows(s, 'full', units(s, 'full', excl)) for s in (y - 2, y - 1) if s >= 2016}
    D[y] = board_rate_rows(y, h, units(y, h, excl))
    K, m, b, xb, mq = pxp_params(target_pair)
    return {pid: RR.pred(D, y, pid, 'marcelM', K, m, b, xb, mq=mq) for pid in D[y]}, D[y]


def add_pxp(U, px, Dy):
    for pid, t, sh, m, g, sub, sn in U:
        if g == 'ST':
            m['pxpST'] = m['st']; continue
        pfr, side = pid.split('|')
        r = Dy.get(pfr)
        if r is None or pfr not in px or g != r['grp']: continue
        v = px[pfr] / 60 * sn / PPW          # points a 60 snaps -> wins over this row's snaps
        m['pxp'] = v; m['pxpST'] = v; m['pwar'] = v + VALUE.get(sub, 0) * sh
    return U


# ------------------------------------------------------------------ harness
def season_D(U, teams, metric, expo=None):
    parts, num, den, grp, team, nm = [], defaultdict(float), defaultdict(float), {}, {}, {}
    for pid, t, sh, m, g, sub, sn in U:
        e = sh if expo is None else expo.get((pid, t), 0.0)
        if e > 0: parts.append((pid, t, e))
        if metric in m and sh > 0:
            num[pid] += m[metric]; den[pid] += sh; grp[pid] = sub
    for t, tm in teams.items():
        if tm['g'] <= 0: continue
        team[f'{t}|O'] = (tm['pf'], tm['g']); team[f'{t}|D'] = (-tm['pa'], tm['g']); nm[f'{t}|O'] = nm[f'{t}|D'] = t
    return {'parts': parts, 'val': {k: num[k] / den[k] for k in num if den[k] > 0}, 'team': team, 'grp': grp, 'net': nm}


def offense_only(D):
    return {**D, 'parts': [p for p in D['parts'] if p[1].endswith('|O')], 'team': {k: v for k, v in D['team'].items() if k.endswith('|O')}, 'net': None}


def rows_of(D, val, fill=None):
    return core.net(core.centred(D, 0, val, fill), D.get('net'))


def heldout(per):
    """per: {season: [(x, y)]} -> slope through the origin fit without the season; squared errors by season"""
    err = {}
    for n in per:
        xs = [x for m_ in per if m_ != n for x, _ in per[m_]]; ys = [y for m_ in per if m_ != n for _, y in per[m_]]
        b = float(np.dot(xs, ys) / np.dot(xs, xs)) if np.dot(xs, xs) > 0 else 0.0
        err[n] = [(y - b * x) ** 2 for x, y in per[n]]
    allE = [e for n in per for e in err[n]]; allY = [y for n in per for _, y in per[n]]
    return 1 - sum(allE) / sum(y * y for y in allY), err


def r2_pool(per, keys):
    rr = [r for k in keys for r in per[k]]
    return core.r2(*zip(*rr))


def ci(per, n=2000):
    keys = list(per)
    bs = [r2_pool(per, rng.choice(keys, len(keys))) for _ in range(n)]
    return [round(float(np.percentile(bs, 5)), 3), round(float(np.percentile(bs, 95)), 3)]


def predict(metric, P, off=False, pk=.2, lo_fill=.25, min_next=.4):
    per, px, py, pw, pr = {}, [], [], [], {}
    for n in PAIRS:
        Dn, D1 = P[n][0](metric), P[n][1](metric)
        if off: Dn, D1 = offense_only(Dn), offense_only(D1)
        expo = defaultdict(float)
        for pid, t, x in Dn['parts']: expo[pid] += x
        vn = {pid: v * expo[pid] / (expo[pid] + pk) for pid, v in Dn['val'].items()}
        gf, af = core.fillv(vn, expo, Dn['grp'], lo_fill)
        fill = {pid: gf.get(D1['grp'].get(pid), af) for pid, t, x in D1['parts'] if pid not in vn}
        per[n] = rows_of(D1, vn, fill)
        e1 = defaultdict(float)
        for pid, t, x in D1['parts']: e1[pid] += x
        q = [(vn[pid], D1['val'][pid], x) for pid, x in e1.items() if x >= min_next and pid in vn and pid in D1['val']]
        px += [a for a, _, _ in q]; py += [b for _, b, _ in q]; pw += [c for _, _, c in q]
        pr[n] = q
    ho, err = heldout(per)
    out = {'teamR2': round(r2_pool(per, PAIRS), 4), 'teamR2ci': ci(per), 'teamHeldR2': round(float(ho), 4),
           'playerR': round(core.wcorr(px, py, pw), 4) if len(px) > 2 else None, 'nPairs': len(PAIRS), 'teamSeasons': sum(len(v) for v in per.values()),
           'nPlayers': len(px)}
    if len(px) > 2:
        bs = []
        for _ in range(1000):
            ks = rng.choice(PAIRS, len(PAIRS)); q = [r for k in ks for r in pr[k]]
            bs.append(core.wcorr(*zip(*q)))
        out['playerRci'] = [round(float(np.percentile(bs, 5)), 3), round(float(np.percentile(bs, 95)), 3)]
    return out, err, per


def describe(metric, DF, DH, off=False):
    per, perh = {}, {}
    for y in YS:
        D = DF[y](metric); Dh = DH[y](metric)
        if off: D, Dh = offense_only(D), offense_only(Dh)
        per[y] = rows_of(D, D['val'])
        perh[y] = rows_of(Dh, Dh['val'])
    ho, err = heldout(perh)
    return {'R2': round(r2_pool(per, YS), 4), 'R2ci': ci(per), 'heldR2': round(float(ho), 4), 'heldCorr2': round(r2_pool(perh, YS), 4),
            'heldCorr2ci': ci(perh), 'seasons': len(YS)}, err


def main():
    # describe: full season (XV without its own season); held out: weeks 1-9 values, weeks 10+ exposure and results
    U_full, U_h1, EXPO2, T2, U_full_s, U_h1_s = {}, {}, {}, {}, {}, {}
    for y in YS:
        U_full[y] = units(y, 'full', (y,)); U_h1[y] = units(y, 'h1', (y,))
        U_full_s[y] = units(y, 'full', (y,), side=True); U_h1_s[y] = units(y, 'h1', (y,), side=True)
        px, Dy = pxp_of(y, 'full', (y,), y - 1); add_pxp(U_full[y], px, Dy)
        px, Dy = pxp_of(y, 'h1', (y,), y - 1); add_pxp(U_h1[y], px, Dy)
        e_full = defaultdict(float); e_h1 = defaultdict(float)
        for pid, t, sh, *_ in U_full[y]: e_full[(pid, t)] += sh
        for pid, t, sh, *_ in U_h1[y]: e_h1[(pid, t)] += sh
        EXPO2[y] = {k: max(0.0, v - e_h1.get(k, 0.0)) for k, v in e_full.items()}
        tf, th = C[(y, 'full')]['teams'], C[(y, 'h1')]['teams']
        T2[y] = {t: {'g': tf[t]['g'] - th.get(t, {}).get('g', 0), 'pf': tf[t]['pf'] - th.get(t, {}).get('pf', 0), 'pa': tf[t]['pa'] - th.get(t, {}).get('pa', 0)} for t in tf}
        print('describe units', y, flush=True)
    DF = {y: (lambda m, y=y: season_D(U_full[y], C[(y, 'full')]['teams'], m)) for y in YS}
    DH = {y: (lambda m, y=y: season_D(U_h1[y], T2[y], m, EXPO2[y])) for y in YS}
    DFs = {y: (lambda m, y=y: season_D(U_full_s[y], C[(y, 'full')]['teams'], m)) for y in YS}
    DHs = {y: (lambda m, y=y: season_D(U_h1_s[y], T2[y], m, EXPO2[y])) for y in YS}
    # predict: pair n, XV without n and n+1
    P = {}
    for n in PAIRS:
        Un, U1 = units(n, 'full', (n, n + 1)), units(n + 1, 'full', (n, n + 1))
        px, Dy = pxp_of(n, 'full', (n, n + 1), n); add_pxp(Un, px, Dy)
        P[n] = ((lambda m, U=Un, n=n: season_D(U, C[(n, 'full')]['teams'], m)), (lambda m, U=U1, n=n: season_D(U, C[(n + 1, 'full')]['teams'], m)))
        print('predict units', n, flush=True)
    # pXP player r: n pXP vs n+1 rXP/60 (its own target) -> harness's player test with target metric rXP
    metrics = ['board', 'avwar', 'xv', 'av', 'rxp', 'pxp', 'pwar', 'sv', 'epa', 'cpoe']
    res = {'metrics': {}, 'offense': {}, 'candidates': {}}
    E = {}
    for mt in metrics:
        d, de = describe(mt, DF, DH)
        p, pe, _ = predict(mt, P)
        res['metrics'][mt] = {'describe': d, 'predict': p}; E[mt] = (de, pe)
        print(mt, d, {k: p[k] for k in ('teamR2', 'teamHeldR2', 'playerR')}, flush=True)
    for mt in ['board', 'avwar', 'xv', 'pxp', 'sv', 'epa', 'cpoe']:
        d, _ = describe(mt, DF, DH, off=True); p, _, _ = predict(mt, P, off=True)
        res['offense'][mt] = {'describe': d, 'predict': p}
        print('O', mt, d['R2'], d['heldR2'], p['teamR2'], p['playerR'], flush=True)
    # by position family (only that family's rows summed): which metric describes / predicts best inside a tab
    res['byGroup'] = {}
    for gname, G in (('QB', {'QB'}), ('skill', {'RB', 'WR', 'TE'}), ('defense', {'DL', 'LB', 'DB'})):
        DFg = {y: (lambda m, y=y: season_D([u for u in U_full[y] if u[4] in G], C[(y, 'full')]['teams'], m)) for y in YS}
        DHg = {y: (lambda m, y=y: season_D([u for u in U_h1[y] if u[4] in G], T2[y], m, EXPO2[y])) for y in YS}
        res['byGroup'][gname] = {}
        for mt in ['board', 'avwar', 'xv', 'pxp', 'sv', 'epa'] + (['cpoe'] if gname == 'QB' else []):
            d, _ = describe(mt, DFg, DHg)
            res['byGroup'][gname][mt] = {'describe': d['R2'], 'describeHeld': d['heldR2'], 'ci': d['heldCorr2ci']}
        print('group', gname, {k: (v['describe'], v['describeHeld']) for k, v in res['byGroup'][gname].items()}, flush=True)
    # common forward player target: n value vs n+1 board WAR rate (so predictive metrics share one target)
    res['playerVsBoard'], res['playerVsRxp'] = {}, {}
    for tgt, key in (('board', 'playerVsBoard'), ('rxp', 'playerVsRxp')):
        for mt in ['board', 'avwar', 'xv', 'av', 'rxp', 'pxp', 'pwar', 'sv', 'epa']:
            px_, py_, pw_ = [], [], []
            for n in PAIRS:
                Dn, D1 = P[n][0](mt), P[n][1](tgt)
                expo = defaultdict(float)
                for pid, t, x in Dn['parts']: expo[pid] += x
                e1 = defaultdict(float)
                for pid, t, x in D1['parts']: e1[pid] += x
                for pid, x in e1.items():
                    if x >= .4 and pid in Dn['val'] and pid in D1['val']:
                        px_.append(Dn['val'][pid] * expo[pid] / (expo[pid] + .2)); py_.append(D1['val'][pid]); pw_.append(x)
            res[key][mt] = round(core.wcorr(px_, py_, pw_), 4)
    print('player r vs next board', res['playerVsBoard'], 'vs next rXP', res['playerVsRxp'])

    # ---------------- candidates
    def paired(e_new, e_old, keys):
        d = [a - b for k in keys for a, b in zip(e_new[k], e_old[k])]
        t = float(np.mean(d) / (np.std(d, ddof=1) / math.sqrt(len(d))))
        from math import erf
        p = .5 * (1 + erf(t / math.sqrt(2)))          # one-sided, new lower error
        better = sum(1 for k in keys if sum(e_new[k]) < sum(e_old[k]))
        return round(t, 3), p, better
    cand = {}
    p1, e1, _ = predict('pxpST', P); p0, e0, _ = predict('pxp', P)
    cand['C1 pXP/60 + special teams'] = {'target': 'predict team', 'before': p0['teamHeldR2'], 'after': p1['teamHeldR2'],
                                          'R2before': p0['teamR2'], 'R2after': p1['teamR2'], 'stat': paired(e1, e0, PAIRS), 'need': 5, 'of': len(PAIRS)}
    p2, e2, _ = predict('pwar', P)
    cand['C2 pWAR rate (pXP/60 + position value)'] = {'target': 'predict team', 'before': p0['teamHeldR2'], 'after': p2['teamHeldR2'],
                                                      'R2before': p0['teamR2'], 'R2after': p2['teamR2'], 'stat': paired(e2, e0, PAIRS), 'need': 5, 'of': len(PAIRS),
                                                      'playerR': [res['playerVsBoard']['pxp'], res['playerVsBoard']['pwar']], 'playerRvsRxp': [res['playerVsRxp']['pxp'], res['playerVsRxp']['pwar']]}
    d3, e3 = describe('xv', DFs, DHs); d0, e0d = describe('xv', DF, DH)
    cand['C3 XV fit per side'] = {'target': 'describe held out', 'before': d0['heldR2'], 'after': d3['heldR2'], 'R2before': d0['R2'], 'R2after': d3['R2'],
                                  'stat': paired(e3, e0d, YS), 'need': 6, 'of': len(YS)}
    Ps = {n: ((lambda m, U=units(n, 'full', (n, n + 1), side=True), n=n: season_D(U, C[(n, 'full')]['teams'], m)),
              (lambda m, U=units(n + 1, 'full', (n, n + 1), side=True), n=n: season_D(U, C[(n + 1, 'full')]['teams'], m))) for n in PAIRS}
    side_side = {}
    for mt in ('xv', 'board'):
        a, _, _ = predict(mt, P); b, _, _ = predict(mt, Ps)
        da, _ = describe(mt, DF, DH); db, _ = describe(mt, DFs, DHs)
        side_side[mt] = {'predictTeam': [a['teamR2'], b['teamR2']], 'playerR': [a['playerR'], b['playerR']],
                         'describe': [da['R2'], db['R2']], 'describeHeld': [da['heldR2'], db['heldR2']]}
    cand['C3 XV fit per side']['sideEffects'] = side_side
    dB, eB = describe('board', DF, DH); dN, eN = describe('boardNoST', DF, DH)
    cand['C4 board WAR with special teams (vs without)'] = {'target': 'describe held out', 'before': dN['heldR2'], 'after': dB['heldR2'], 'R2before': dN['R2'],
                                                             'R2after': dB['R2'], 'stat': paired(eB, eN, YS), 'need': 6, 'of': len(YS)}
    ps = sorted((c['stat'][1], k) for k, c in cand.items())
    m_ = len(ps)
    adj, run = {}, 0.0
    for i, (p, k) in enumerate(ps):
        run = max(run, min(1.0, (m_ - i) * p)); adj[k] = run
    for k, c in cand.items():
        t, p, better = c['stat']
        c['stat'] = {'t': t, 'p': round(p, 4), 'pHolm': round(adj[k], 4), 'better': better}
        c['pass'] = bool(adj[k] < .05 and better >= c['need'] and c['after'] > c['before'])
        if k.startswith('C2'): c['pass'] = c['pass'] and c['playerR'][1] >= c['playerR'][0] - .01
        print(k, c)
    res['candidates'] = cand
    json.dump(res, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
