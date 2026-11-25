#!/usr/bin/env python3
"""CS2 metric audit (Nov 24 2026): team ratings on the series harness (prereg.md). -> team.json  (~3 min, two replays)
predict: month-start (frozen) and in-month live ratings -> that month's series, logistic slope (top-50 / rest, as
cs2_model) fit on earlier months only (expanding from Aug 2024); log loss + R2 (squared correlation of the gap with
the result, sides oriented by hash). describe: end-of-month ratings -> that month's series; held out = a replay that
never sees one hash half of every month's series, scored on that half. ARK settings as shipped (not retuned)."""
import datetime as dt, gzip, json, math, sys, zlib
from collections import defaultdict
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C
from common import P
import cs2_bo3, cs2_model as CM, names  # noqa: E402

H = json.load(gzip.open(CM.HIST))
series = [r for r in H['series'] if r[6] == 'vrs' and r[0] < C.LOCK]
vrs = CM.Vrs(H['vrs']); pa = json.loads(CM.FIT.read_text())['params']
MO = C.months('2024-08', C.LAST)
starts = [m + '-01' for m in MO] + ['2026-11-01']
def _day_start_replay():
    """cs2_model.replay with one extra row field xd: the player-Elo gap from ratings as of the start of the series' day
    (Valve lists dates only, so live x can see same-day series that may have been played later)"""
    import inspect
    src = inspect.getsource(CM.replay)
    a = '    want, kept = sorted(snaps or []), {}\n'
    b = '        d, a, b, y, ra, rb = r[:6]\n'
    c = '            rows.append({"i": orig[i], "d": d, "a": ka, "b": kb,'
    assert a in src and b in src and c in src
    src = src.replace(a, a + '    _cur, _pl0, _ro0 = [None], {}, {}\n')
    src = src.replace(b, b + '        if d[:10] != _cur[0]:\n            _cur[0] = d[:10]; _pl0.clear(); _pl0.update(pl); _ro0.clear(); _ro0.update(roff)\n')
    src = src.replace(c, '            _t0 = lambda ros, k, g: (sum(_pl0.get(q, warm.get(q, 0.0 if d < BURN else p["mu_new"])) for q in ros) / len(ros) if ros else team.get(k, p["mu_new"])) + (_ro0.get(g, 0.0) if g else 0.0)\n'
                      + c + ' "xd": (_t0(ra, ka, rga) - _t0(rb, kb, rgb)) / 400,')
    ns = dict(CM.__dict__); exec(src, ns); return ns['replay']


CM.replay_xd = _day_start_replay()
def hh(r):
    """hash half of a series: on the date + both fives (Valve lists ~24% of held series twice under other team names,
    same ten players and winner), so a series and its copies fall in the same half"""
    if r[4] and r[5] and len(r[4]) == 5 and len(r[5]) == 5:
        return zlib.crc32((r[0] + '|' + '|'.join(sorted(['/'.join(sorted(r[4])), '/'.join(sorted(r[5]))]))).encode()) % 2
    return zlib.crc32(f'{r[0]}|{r[1]}|{r[2]}'.encode()) % 2
rows, st = CM.replay_xd(series, vrs, pa, bo3=cs2_bo3.Bo3(), snaps=starts)
keepB = [r for r in series if not (r[0] >= '2024-08-01' and hh(r) == 1)]
bB = cs2_bo3.Bo3(); jj = bB.join(series)
for i, mm in jj.items():   # the held half's bo3.gg matches must not come back as lower-tier update rows
    if series[i][0] >= '2024-08-01' and hh(series[i]) == 1: bB.mt.pop(mm[0], None)
bB.alias = {}
rowsB, stB = CM.replay(keepB, vrs, pa, bo3=bB, snaps=starts)
# replay C: Valve's repeat listings (same day, same ten players) dropped before the replay (what a deduplicated ARK reads)
_seen, keepC = set(), []
for j, r in enumerate(series):
    k10 = (r[0], frozenset([frozenset(r[4] or []), frozenset(r[5] or [])]))
    if r[4] and r[5] and len(r[4]) == 5 and len(r[5]) == 5 and k10 in _seen: continue
    _seen.add(k10); keepC.append(j)
rowsC, _ = CM.replay_xd([series[j] for j in keepC], vrs, pa, bo3=cs2_bo3.Bo3())
byC = {keepC[r['i']]: r for r in rowsC}
rows = [r for r in rows if '2024-08-01' <= r['d'] < '2026-11-01']
print('series', len(rows), file=sys.stderr)


def nxt(d): return (dt.date.fromisoformat(d[:7] + '-01') + dt.timedelta(days=32)).replace(day=1).isoformat()


def frozen(S, r, d):
    """ARK player-Elo gap and team-name Elo gap from a kept state S (cs2_model.replay snaps)"""
    def tr(ros, k):
        v = [S['pl'].get(q, pa['mu_new']) for q in ros or []]
        g = vrs.region(k, d); off = S['roff'].get(g, 0.0) if g else 0.0
        return (sum(v) / len(v) if v else S['team'].get(k, pa['mu_new'])) + off
    ra, rb = r['r'][4] or S['lastros'].get(r['a']), r['r'][5] or S['lastros'].get(r['b'])
    return (tr(ra, r['a']) - tr(rb, r['b'])) / 400, (S['team'].get(r['a'], pa['mu_new']) - S['team'].get(r['b'], pa['mu_new'])) / 400


def vgap(r, d):
    va, vb = vrs.get(r['a'], d), vrs.get(r['b'], d)
    return ((va[1] if va else 400) - (vb[1] if vb else 400)) / 400


# team RWA: five's mean RWA rating at a date (stat weights refit on maps before it)
M = C.load(); bo3 = cs2_bo3.Bo3(); nk, nkt = P.nick_index(M, bo3); _th = {}


def rwa_gap(r, d):
    if d not in _th:
        T = P.ordd(d); b, ml, _ = C.weights(M, T)
        _th[d] = C.ratings_ex(M, P.contributions(M, b, ml, C.SHIP['pm']), T, C.SHIP)[0]
    th = _th[d]

    def mean(ros, k):
        v = [th[i] for q in ros or [] if (i := nkt.get((names.key(q), k), nk.get(names.key(q)))) is not None]
        return np.mean(v) if len(v) >= 3 else None
    a, b = mean(r['r'][4], r['a']), mean(r['r'][5], r['b'])
    return (a - b) / 10 if a is not None and b is not None else 0.0


feat = defaultdict(list); seen = set()
for r in rows:
    ra_, rb_ = r['r'][4] or [], r['r'][5] or []
    k10 = (r['d'], frozenset([frozenset(ra_), frozenset(rb_)]))
    feat['dup'].append(len(ra_) == 5 and len(rb_) == 5 and k10 in seen); seen.add(k10)
    d0, d1 = r['d'][:7] + '-01', nxt(r['d'])
    S0, S1, S1B = st['snaps'][d0], st['snaps'][d1], stB['snaps'][d1]
    xf, ef = frozen(S0, r, d0); xe, ee = frozen(S1, r, d1); xb, eb = frozen(S1B, r, d1)
    rc = byC.get(r['i'])
    f = {'ARK live (x, VRS, map rating)': [r['x'], r['v'], r['t']],
         'ARK live, dedup replay': [rc['x'], rc['v'], rc['t']] if rc else [r['x'], r['v'], r['t']],
         'ARK live, dedup replay, day start': [rc['xd'], rc['v'], rc['t']] if rc else [r['xd'], r['v'], r['t']], 'ARK player Elo, live': [r['x']], 'ARK player Elo, day start': [r['xd']], 'ARK live, day start (xd, VRS, map rating)': [r['xd'], r['v'], r['t']], 'VRS points': [r['v']],
         'bo3 team map rating, live': [r['t']], 'ARK player Elo, month start': [xf], 'team-name Elo, month start': [ef],
         'VRS, month start': [vgap(r, d0)], 'team RWA, month start': [rwa_gap(r, d0)]}
    g = {'ARK player Elo, month end': [xe], 'ARK player Elo, month end (held half)': [xb], 'team-name Elo, month end': [ee],
         'team-name Elo, month end (held half)': [eb], 'VRS, month end': [vgap(r, d1)], 'team RWA, month end': [rwa_gap(r, d1)]}
    feat['m'].append(r['d'][:7]); feat['s'].append(r['s']); feat['top'].append(r['top']); feat['h'].append(hh(r['r']))
    for k, v in {**f, **g}.items(): feat[k].append(v)
m0, s0, top0, hf0, dup = (np.array(feat[k]) for k in ('m', 's', 'top', 'h', 'dup')); s0 = s0.astype(float)
sg0 = np.where(np.array([zlib.crc32(f'o{i}'.encode()) % 2 for i in range(len(s0))]) == 1, -1.0, 1.0)
PRED = ['ARK live (x, VRS, map rating)', 'ARK live, dedup replay', 'ARK live, dedup replay, day start', 'ARK live, day start (xd, VRS, map rating)', 'ARK player Elo, live', 'ARK player Elo, day start', 'VRS points', 'bo3 team map rating, live',
        'ARK player Elo, month start', 'team-name Elo, month start', 'VRS, month start', 'team RWA, month start']
DESC = ['ARK player Elo, month end', 'team-name Elo, month end', 'VRS, month end', 'team RWA, month end']


def wf(X):
    """walk-forward tiered logistic: month k scored with weights fit on months before k (from Aug 2024)"""
    q = np.full(len(s), np.nan)
    for mo in MO[1:]:
        te = m == mo; tr = m < mo
        for t in (True, False):
            a, b = tr & (top == t), te & (top == t)
            if b.any(): q[b] = 1 / (1 + np.exp(-X[b] @ CM.fitlog(X[a], s[a])))
    return q


res = {'nSeries': int(len(s0)), 'nDuplicate': int(dup.sum()), 'months': MO[1:]}


def score(keep):
    global m, s, top, hf, sg
    m, s, top, hf, sg = m0[keep], s0[keep], top0[keep], hf0[keep], sg0[keep]
    F = {k: [v for v, z in zip(feat[k], keep) if z] for k in PRED + DESC + [d + ' (held half)' for d in DESC if d + ' (held half)' in feat]}
    out = {'predict': {}, 'describe': {}}
    sc = m >= MO[1]; held = m >= '2025-07'
    L = {}
    for k in PRED:
        X = np.array(F[k], float); q = wf(X); l = CM.ll(q[sc], s[sc]); L[k] = l
        x = X[:, 0] if X.shape[1] == 1 else np.log(q / (1 - q))
        out['predict'][k] = {'ll': round(float(l.mean()), 4), 'llHeld': round(float(CM.ll(q[held], s[held]).mean()), 4),
                             'r2': round(C.r2((x * sg)[sc], ((s - .5) * sg)[sc]), 4)}
    ms = m[sc]
    for k in PRED:
        d = L[k] - L['ARK live (x, VRS, map rating)']
        out['predict'][k]['tVsArkByMonth'] = round(C.tby([d[ms == mo].mean() for mo in MO[1:]]), 2)
        out['predict'][k]['bootLlCI'] = [round(float(v), 4) for v in np.percentile(
            [np.mean([L[k][ms == mo].mean() for mo in np.random.default_rng(i).choice(MO[1:], len(MO) - 1)]) for i in range(500)], [5, 95])]
    for k in DESC:
        x = np.array(F[k], float)[:, 0]
        out['describe'][k] = {'r2In': round(C.r2(x * sg, (s - .5) * sg), 4)}
        kb = k + ' (held half)'
        if kb in feat:
            xb = np.array(F[kb], float)[:, 0]
            out['describe'][k]['r2Held'] = round(C.r2((xb * sg)[hf == 1], ((s - .5) * sg)[hf == 1]), 4)
            out['describe'][k]['r2InSameHalf'] = round(C.r2((x * sg)[hf == 1], ((s - .5) * sg)[hf == 1]), 4)
    return out


res['all rows (as the shipped backtest)'] = score(np.ones(len(s0), bool))
res['duplicates dropped'] = score(~dup)
print(json.dumps(res, indent=1))
Path(__file__).with_name('team.json').write_text(json.dumps(res, indent=1))
