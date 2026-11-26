#!/usr/bin/env python3
"""FotMob GAR / SV stand-in against the Understat version (prereg.md). Needs the caches: Understat match files
(untar /mnt/project-files/soccer/understat_cache.tgz into scripts/.cache/soccer), FotMob's season lists for
2021..2026 (pull.py -> scripts/.cache/soccer/fmg_raw) and the freezes (snaps.py).
    python3 scripts/research/soccer_fotmob_nov26/test.py     -> results.json"""
import json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import soccer_data as D, soccer_players as P, soccer_sv as SV, soccer_fm_gar as FG  # noqa: E402

SEASONS = list(range(2021, 2027)); FS = ['0.25', '0.5', '0.75']
LAMS, SHRINKS = [.003, .03, .3, 3], [450, 900, 1800]
RAW = {(lg, S): D.load(os.path.join(D.CACHE, 'fmg_raw', f'{lg}_{S}.json.gz')) for lg in FG.FMB5 for S in SEASONS}
F, FSV, LS = P._fit(), SV._fit(), P.league_strength()
TARGETS = {'gar': ('gv', True), 'sv': ('sv_', False)}


def wmse(rows, key, pred):
    w = np.array([r['min'] for r in rows], float)
    return float((w * (np.array([r[key] for r in rows]) - np.array(pred)) ** 2).sum() / w.sum())


def loso_score(DS, lam, target, prior, seasons):
    e = n = 0.0
    for s in seasons:
        tr = [r for r in DS if r['S'] in seasons and r['S'] != s]; te = [r for r in DS if r['S'] == s]
        co = FG.fit_models(tr, lam, target, prior)
        w = sum(r['min'] for r in te)
        e += wmse(te, target, [FG.predict(r, co, prior) for r in te]) * w; n += w
    return e / n


# every FotMob player of each season with features at each shrink (matched rows carry the Understat targets)
ALL = {}
for sh in SHRINKS:
    ds = FG.dataset(SEASONS, RAW, sh)
    ALL[sh] = ds
    print('shrink', sh, len(ds), 'matched player-seasons', flush=True)
cover = {}
for S in SEASONS:
    us = FG.us_season(S, F, FSV, LS)
    got = {(r['lg'], r['us']) for r in ALL[900] if r['S'] == S}
    cover[S] = round(sum(u['min'] for u in us if (u['lg'], u['p']) in got) / sum(u['min'] for u in us), 4)
print('share of Understat minutes matched to a FotMob player', cover, flush=True)

OUT = {'seasons': SEASONS, 'matchedMinutes': cover, 'emulator': {}, 'freeze': {}, 'picks': {}}
PRED = {m: {} for m in TARGETS}            # metric -> {(S, fm p): held-out league-relative value a 90}
for m, (tg, prior) in TARGETS.items():
    per = {}
    for s in SEASONS:
        tr = [x for x in SEASONS if x != s]
        best = min(((loso_score(ALL[sh], lam, tg, prior, tr), lam, sh) for sh in SHRINKS for lam in LAMS))
        _, lam, sh = best
        co = FG.fit_models([r for r in ALL[sh] if r['S'] != s], lam, tg, prior)
        te = [r for r in ALL[sh] if r['S'] == s]
        pr = [FG.predict(r, co, prior) for r in te]
        for r, v in zip(te, pr):
            PRED[m][(s, r['p'])] = v
        y = np.array([r[tg] for r in te]); w = np.array([r['min'] for r in te], float); pr = np.array(pr)
        mu = (w * y).sum() / w.sum()
        cov = lambda a, b: float((w * (a - (w * a).sum() / w.sum()) * (b - (w * b).sum() / w.sum())).sum() / w.sum())
        per[s] = {'lam': lam, 'shrink': sh, 'r': round(cov(y, pr) / (cov(y, y) * cov(pr, pr)) ** .5, 3),
                  'r2': round(1 - float((w * (y - pr) ** 2).sum() / (w * (y - mu) ** 2).sum()), 3), 'n': len(te)}
        OUT['picks'].setdefault(m, {})[s] = [lam, sh]
        print(m, s, per[s], flush=True)
    OUT['emulator'][m] = per

# ---------------------------------------------------------------- freezes
ROWS = {}                                   # season -> evaluation rows (FotMob players matched to the Understat truth)
for S in SEASONS:
    snap = D.load(os.path.join(D.CACHE, f'fm_snaps_{S}.json.gz'))
    fz = {}
    for f in FS:
        a = {}
        for o in snap[f]['p']:
            q = a.setdefault((o['lg'], o['p']), {'min': 0, 'gar': 0.0, 'sv': 0.0, 'pos': o['pos']})
            q['min'] += o['min']; q['gar'] += o['gar90'] * o['min'] / 90; q['sv'] += o['sv'] * o['min'] / 90
        fz[f] = a
    us = {(u['lg'], u['p']): u for u in FG.us_season(S, F, FSV, LS)}
    rows = []
    for r in ALL[900]:
        if r['S'] != S or r['min'] < 90:
            continue
        u = us[(r['lg'], r['us'])]
        o = {'S': S, 'lg': r['lg'], 'p': r['p'], 'us': r['us'], 'pos': u['pos'], 'tid': r['tid'], 'fmin': r['min'], 'umin': u['min'],
             'T_gar': u['gar'], 'T_sv': u['svar'],
             'E_gar': PRED['gar'][(S, r['p'])] + FG.lg_g(F, LS, r['lg'], S) - F['repl'][u['pos']],
             'E_sv': PRED['sv'][(S, r['p'])] + FG.lg_s(FSV, LS, r['lg'], S) - FSV['repl'][u['pos']]}
        for f in FS:
            q = fz[f].get((r['lg'], r['us']))
            o['z' + f] = None if not q or q['min'] < 1 else (q['min'], q['gar'], q['sv'])
        rows.append(o)
    ROWS[S] = rows
    # position mean frozen rate, for C1 on players with no frozen row
    for f in FS:
        for m in ('gar', 'sv'):
            for pos in ('GK', 'D', 'M', 'F'):
                g = [q for q in fz[f].values() if q['pos'] == pos]
                ROWS[(S, f, m, pos)] = sum(q[m] for q in g) / max(1, sum(q['min'] for q in g)) * 90
GRID = [(a, k) for a in (.4, .5, .6, .7, .8, .9, 1.0) for k in (0, 90, 180, 360, 720, 1440)]


def cands(o, f, m, a=None, k=None):
    """totals (C0, C1, C2[, C3]) for one row"""
    z = o['z' + f]; n90 = o['fmin'] / 90; e = o['E_' + m]
    i = 1 if m == 'gar' else 2
    fr = z[i] / z[0] * 90 if z else None
    c0 = z[i] if z else 0.0
    c1 = (fr if z else ROWS[(o['S'], f, m, o['pos'])]) * n90
    out = [c0, c1, e * n90]
    if a is not None:
        w = a * z[0] / (z[0] + k) if z and (z[0] + k) > 0 else 0.0
        out.append((w * fr + (1 - w) * e) * n90 if z else e * n90)
    return out


def sse(rows, f, m, a, k):
    return sum((cands(o, f, m, a, k)[3] - o['T_' + m]) ** 2 for o in rows)


def paired(rows, ea, eb):
    """paired t on squared error, players as units (a player's seasons averaged): a minus b"""
    d = defaultdict(list)
    for o, x, y in zip(rows, ea, eb):
        d[o['us']].append(x - y)
    v = np.array([np.mean(x) for x in d.values()])
    return round(float(v.mean() / (v.std(ddof=1) / len(v) ** .5)), 2)


def spearman(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def describe(rows, tot):
    """squared correlation of the roster sum a match with the side's goal difference a match, centred by league-season"""
    xs, ys = [], []
    by = defaultdict(lambda: defaultdict(float))
    for o, t in zip(rows, tot):
        by[(o['S'], o['lg'])][o['tid']] += t
    for (S, lg), g in by.items():
        T = FG.table(lg, S, raw=RAW[(lg, S)])['teams']
        v = [(x / max(T[t]['mp'], 1), T[t]['tg'] - T[t]['tga']) for t, x in g.items() if t in T]
        mx, my = np.mean([a for a, _ in v]), np.mean([b for _, b in v])
        xs += [a - mx for a, _ in v]; ys += [b - my for _, b in v]
    return round(float(np.corrcoef(xs, ys)[0, 1] ** 2), 3)


for m in ('gar', 'sv'):
    for f in FS:
        res = {'bySeason': {}, 'ak': {}}
        allr, E = [], [[], [], [], []]
        for s in SEASONS:
            tr = [o for x in SEASONS if x != s for o in ROWS[x]]
            a, k = min(GRID, key=lambda g: sse(tr, f, m, *g))
            te = ROWS[s]
            C = np.array([cands(o, f, m, a, k) for o in te]); T = np.array([o['T_' + m] for o in te])
            rm = [round(float(np.sqrt(np.mean((C[:, j] - T) ** 2))), 3) for j in range(4)]
            top = np.argsort(-T)[:150]
            res['bySeason'][s] = {'rmse': dict(zip(('C0', 'C1', 'C2', 'C3'), rm)), 'a': a, 'k': k,
                                  'top150': {c: round(spearman(C[top, j], T[top]), 3) for j, c in enumerate(('C0', 'C1', 'C2', 'C3'))}}
            res['ak'][s] = [a, k]
            allr += te
            for j in range(4):
                E[j] += list((C[:, j] - T) ** 2)
        Call = np.array([cands(o, f, m, *res['ak'][o['S']]) for o in allr]); Tall = np.array([o['T_' + m] for o in allr])
        res['rmse'] = {c: round(float(np.sqrt(np.mean(E[j]))), 3) for j, c in enumerate(('C0', 'C1', 'C2', 'C3'))}
        res['describe'] = {c: describe(allr, Call[:, j]) for j, c in enumerate(('C0', 'C1', 'C2', 'C3'))}
        res['describe']['truth'] = describe(allr, Tall)
        res['top150'] = {c: round(float(np.mean([res['bySeason'][s]['top150'][c] for s in SEASONS])), 3) for c in ('C0', 'C1', 'C2', 'C3')}
        for c, j in (('C2', 2), ('C3', 3)):
            for b, i in (('C0', 0), ('C1', 1)):
                res[f't_{c}_vs_{b}'] = paired(allr, E[j], E[i])
                res[f'won_{c}_vs_{b}'] = sum(res['bySeason'][s]['rmse'][c] < res['bySeason'][s]['rmse'][b] for s in SEASONS)
        res['n'] = len(allr)
        OUT['freeze'][f'{m}_{f}'] = res
        print(m, f, {k_: v for k_, v in res.items() if k_ not in ('bySeason', 'ak')}, flush=True)
    # the live table: one (a, k) per depth on every season
    OUT.setdefault('blend', {})[m] = {f: list(min(GRID, key=lambda g: sum(sse(ROWS[x], f, m, *g) for x in SEASONS))) for f in FS}

# ---------------------------------------------------------------- gate 2: blended in while Understat is up
def next_rows(n, b):
    """season n rate (Understat GAR a 90, FotMob estimate blended in at weight b) x n+1 minutes -> n+1 goal difference"""
    val = {}
    for o in ROWS[n]:
        val[(o['lg'], o['us'])] = (1 - b) * o['T_gar'] / (o['umin'] / 90) + b * o['E_gar']
    pm = defaultdict(list)
    for o in ROWS[n]:
        pm[o['pos']].append((val[(o['lg'], o['us'])], o['umin']))
    fill = {p: sum(v * w for v, w in x) / sum(w for _, w in x) for p, x in pm.items()}
    by = defaultdict(lambda: defaultdict(float))
    for o in ROWS[n + 1]:
        by[o['lg']][o['tid']] += val.get((o['lg'], o['us']), fill[o['pos']]) * o['fmin'] / 90
    out = []
    for lg, g in by.items():
        T = FG.table(lg, n + 1, raw=RAW[(lg, n + 1)])['teams']
        v = [(x / max(T[t]['mp'], 1), T[t]['tg'] - T[t]['tga']) for t, x in g.items() if t in T]
        mx, my = np.mean([a for a, _ in v]), np.mean([b_ for _, b_ in v])
        out += [(a - mx, b_ - my) for a, b_ in v]
    return out


def fit_err(tr, te):
    sl = sum(x * y for x, y in tr) / sum(x * x for x, y in tr)
    return [(y - sl * x) ** 2 for x, y in te]


PAIRS = SEASONS[:-1]; BS = [0, .1, .2, .3, .4, .5]
NR = {(n, b): next_rows(n, b) for n in PAIRS for b in BS}
e0, e1, picks = [], [], {}
for n in PAIRS:
    tr = [x for x in PAIRS if x != n]
    b = min(BS[1:], key=lambda b_: sum(sum(fit_err([r for y in tr if y != x for r in NR[(y, b_)]], NR[(x, b_)])) for x in tr))
    picks[n] = b
    e0.append(fit_err([r for x in tr for r in NR[(x, 0)]], NR[(n, 0)])); e1.append(fit_err([r for x in tr for r in NR[(x, b)]], NR[(n, b)]))
d = np.array([np.mean(a) - np.mean(c) for a, c in zip(e1, e0)])
ss = sum(y * y for n in PAIRS for _, y in NR[(n, 0)])
OUT['blendUp'] = {'r2Understat': round(1 - sum(map(sum, e0)) / ss, 3), 'r2Blend': round(1 - sum(map(sum, e1)) / ss, 3), 'b': picks,
                  't': round(float(d.mean() / (d.std(ddof=1) / len(d) ** .5)), 2), 'pairsBetter': int((d < 0).sum()), 'pairs': len(PAIRS),
                  'r2FotmobAlone': round(1 - sum(sum(fit_err([r for x in PAIRS if x != n for r in NR.setdefault((x, 1), next_rows(x, 1))], NR.setdefault((n, 1), next_rows(n, 1)))) for n in PAIRS) / ss, 3)}
print('blend while up', OUT['blendUp'], flush=True)
json.dump(json.loads(json.dumps(OUT, default=float)), open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
