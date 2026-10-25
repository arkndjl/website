#!/usr/bin/env python3
"""Research harness for the College Basketball FV core refit (audit items #20, #26, #16; Oct 25 2026).

    python3 scripts/cbb_careers_kit.py            # once: scripts/.cache/cbb/careers.json (with each NBA season's XPM)
    python3 scripts/cbb_fv_core.py window         # #20: outcome horizon and training window, rolling origin (fixed drivers)
    python3 scripts/cbb_fv_core.py newage         # #16: newcomer age candidates on the shipped newcomer drivers
    python3 scripts/cbb_fv_core.py grid           # configs A-F through one nested protocol (~1 h; cached in .cache/cbb)
    python3 scripts/cbb_fv_core.py gate a.json b.json   # two runs' out-of-fold E[FV] on the gates
    python3 scripts/cbb_fv_core.py reduce         # shipped drivers vs the ledger's "drop" set removed together

Common protocol (grid): outer folds hold out whole college classes (2009-23 exits); each config selects its drivers
inside (cbb_fit.select) on its own boards, outcome and inner folds; every 2009-19 board row is then scored out of fold.
Outcomes: whole-career peak-XPM FV, and the common-horizon FV (best 3 of the first six NBA seasons, fewer but >= 3 for
recent classes, each horizon on its own rarity-matched scale: cbb_fit.horizon_fv).

Results (Oct 25 2026; top-300 corr / top-50 realized FV per board, 2009-16 boards | held-out 2017-19 boards, 6-season FV):
  A shipped (2009-16, whole career, player folds)       .417 / 37.7 | .419 / 39.5
  B class-fold selection                                .444 / 38.5 | .418 / 39.4  (corr better 5/8 | 1/3)
  C 2009-19 boards, 6-season outcome, player folds      .420 / 37.7 | .370 / 38.7
  D 2009-19 boards, 6-season outcome, class folds       .443 / 38.1 | .370 / 38.6  (7/8 | 0/3)
  E B + newcomer age                                    .442 / 38.5 | .411 / 39.2  (vs B: 4/8 | 0/3)
P(NBA) AUC rises in every new config (.910 -> .914-.918): the extra boards and age sharpen who reaches the NBA, not who
stars, and the held-out top gets worse. Nothing ships to the live model. The shipped procedure's own nested out-of-fold
grades give the same shrink (r .81) and monotone calibration bands (55: 51.3, 50: 49.1, 45: 44.7, 40: 42.0).
reduce: dropping the ledger's nine "drop" drivers together loses on 2009-16 (deviance .8917 -> .8971, top 50 38.1 ->
37.05) and ties held out (.8890 -> .8904): they carry information jointly, so all stay.
"""
import json, math, os, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
import cbb_fit as F
from cbb_link import TIERS

NBA_LAST = 2026


def peak_h(c, H):
    """best 3 of the career's first H NBA seasons after college (shrunk XPM, padded at -2.5); None if no NBA games"""
    if c['nba']['games'] < 1: return None
    v = sorted((x for y, x in c['nba'].get('xs', []) if c['last'] < y <= c['last'] + H), reverse=True) + [-2.5] * 3
    return round(sum(v[:3]) / 3, 2)


def scale_h(careers, H):
    """the FV scale on the H-season peak: as many careers (2008-16 classes) at FV t or better as reached role tier t"""
    cs = [c for c in careers if c['last'] in F.SCALE_CLASSES]
    nba = sorted((peak_h(c, H) for c in cs if c['nba']['games'] >= 1), reverse=True)
    return {fv: nba[min(sum(1 for c in cs if c['nba']['fv'] >= fv), len(nba)) - 1] for fv, _, _ in TIERS if fv != F.FLOOR}


def fv_h(c, H, thr):
    x = peak_h(c, H)
    if x is None: return float(F.FLOOR)
    ts = sorted(thr)
    return round(float(np.interp(x, [thr[t] for t in ts], ts)), 2)


def load(years=range(2009, 2021)):
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    thr = F.xpm_scale(careers)
    sc = {H: scale_h(careers, H) for H in (3, 4, 5, 6)}
    F.TOP_MEAN = round(float(np.mean([F.xpm_fv(c, thr) for c in careers if c['last'] in F.SCALE_CLASSES and F.xpm_fv(c, thr) >= 60])), 2)
    rows = []
    for c in careers:
        k = min(6, NBA_LAST - c['last'])
        yfull = F.xpm_fv(c, thr)
        yk = fv_h(c, k, sc[k]) if k >= 3 else None
        for i, s in enumerate(c['seasons']):
            if s['year'] not in years: continue
            rows.append({'pid': c['pid'], 'name': c['name'], 'year': s['year'], 'last': c['last'], 'k': k, 'yfull': yfull, 'yk': yk,
                         'y6': fv_h(c, 6, sc[6]) if k >= 6 else None, 'draft': c['nba']['draft'], 'pick': c['nba']['pick'], 'f': F.features(c, i)})
    return careers, rows, sc


def fit_pred(train, test, kept, lam, ykey):
    """the cbb_fit ladder on kept drivers, fit on train (outcome ykey), E[FV] and rung probabilities on test"""
    for r in train: r['y'] = r[ykey]
    m = F.fit(train, F.matrix(train, kept), list(range(len(kept))), lam)
    _, P, e = F.predict(m, F.matrix(test, kept))
    return P, e


def board_scores(rows, e, ykey):
    y = np.array([r[ykey] for r in rows], float)
    o = np.argsort(-e)
    out = {'n': len(rows), 'corr300': float(np.corrcoef(e[o[:300]], y[o[:300]])[0, 1]), 'top50': float(y[o[:50]].mean()),
           'top150': float(y[o[:150]].mean()), 'rmse': float(np.sqrt(((e - y) ** 2).mean())), 'auc': F.auc(e, y >= 30)}
    return out


VARIANTS = {
    'cur: 2009-16, full peak': (lambda r, t: r['year'] <= 2016 and r['last'] <= 2020, 'yfull'),
    'cur window, 6-season peak': (lambda r, t: r['year'] <= 2016 and r['last'] <= 2020, 'y6'),
    'to t, 6-season peak, done': (lambda r, t: r['year'] <= t and r['last'] <= 2020, 'y6'),
    'to t, k-season peak (k>=3)': (lambda r, t: r['year'] <= t and r['yk'] is not None, 'yk'),
}


def window():
    """rolling origin: fit through board year t (players on board t+1 left out of the fit), score board t+1 against
    the outcome each player has had time to show (best 3 of the first k = min(6, seasons since) NBA seasons, k >= 3,
    on the k-season scale), whole boards (newcomers and returners on one list)"""
    careers, rows, sc = load()
    fit = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))
    res = defaultdict(list)
    for t in range(2016, 2020):
        test = [r for r in rows if r['year'] == t + 1 and r['yk'] is not None]
        out = {r['pid'] for r in test}
        y = np.array([r['yk'] for r in test])
        for name, (ok, yk) in VARIANTS.items():
            e = np.zeros(len(test)); P = np.zeros((len(test), 4))
            for grp in ('newcomer', 'returner'):
                m = fit['models'][grp]
                ix = [i for i, r in enumerate(test) if r['f']['newcomer'] == (grp == 'newcomer')]
                tr = [r for r in rows if r['f']['newcomer'] == (grp == 'newcomer') and ok(r, t) and r['pid'] not in out]
                P[ix], e[ix] = fit_pred(tr, [test[i] for i in ix], m['kept'], m['lam'], yk)
            s = board_scores(test, e, 'yk'); s['dev'] = F.deviance(P, y)
            res[name].append(s)
    base = res['cur: 2009-16, full peak']
    for name, ss in res.items():
        print(f'{name:28s}', ' '.join(f'{k} {np.mean([s[k] for s in ss]):.4f}' for k in ('dev', 'auc', 'rmse', 'corr300', 'top50', 'top150')),
              '| years better dev', sum(a['dev'] < b['dev'] for a, b in zip(ss, base)), 'top150', sum(a['top150'] > b['top150'] for a, b in zip(ss, base)))
    return res


def row_dev(P, y):
    """each row's share of the mean-over-rungs deviance / null (cbb_fit.deviance), rows x rungs"""
    out = np.zeros((len(y), len(F.LADDER)))
    for j, t in enumerate(F.LADDER):
        on = y >= (F.LADDER[j - 1] if j else -1)
        prev = P[on, j - 1] if j else np.ones(on.sum())
        c = np.clip(P[on, j] / np.maximum(prev, 1e-9), 1e-6, 1 - 1e-6)
        o = (y[on] >= t).astype(float); m = np.clip(o.mean(), 1e-6, 1 - 1e-6)
        null = -(o * np.log(m) + (1 - o) * np.log(1 - m)).sum()
        out[on, j] = -(o * np.log(c) + (1 - o) * np.log(1 - c)) / (null * len(F.LADDER))
    return out


def class_fold(last): return (last - 2009) % 5


def oof(rows, cols, lam, folds):
    X = F.matrix(rows, cols); P = np.zeros((len(rows), len(F.LADDER)))
    for k in sorted(set(folds)):
        tr, te = folds != k, folds == k
        P[te] = F.predict(F.fit([r for r, t in zip(rows, tr) if t], X[tr], list(range(len(cols))), lam), X[te])[1]
    return P


def add_test(rows, kept, cands, lam, label):
    import harness as H
    y = np.array([r['y'] for r in rows], float)
    cls = np.array([r['last'] for r in rows]); pid = np.array([r['pid'] for r in rows])
    splits = {'class': np.array([class_fold(r['last']) for r in rows]), 'player': np.array([F.fold_of(r['pid']) for r in rows])}
    base = {n: oof(rows, kept, lam, f) for n, f in splits.items()}
    bdev = {n: row_dev(P, y).sum(1) for n, P in base.items()}
    yrs = np.array([r['year'] for r in rows])
    def top(P, N):
        e = F.expected(P)
        return float(np.mean([y[np.where(yrs == b)[0][np.argsort(-e[yrs == b])[:N]]].mean() for b in sorted(set(yrs))]))
    print(f'{label}: {len(rows)} rows, base dev', {n: round(float(v.sum()), 4) for n, v in bdev.items()}, 'top30/board', round(top(base['class'], 30), 2))
    for c in cands:
        out = []
        for n, f in splits.items():
            P = oof(rows, kept + [c], lam, f); d = row_dev(P, y).sum(1)
            pt = H.paired(d, bdev[n], cls if n == 'class' else pid)
            fold = sum(1 for k in set(f) if d[f == k].sum() < bdev[n][f == k].sum())
            out.append(f"{n} gain {(bdev[n].sum() - d.sum()) * 100:+.3f}% t {-pt['t']:+.2f} folds {fold}/5")
            if n == 'class': tp = top(P, 30)
        print(f'  {c:10s}', ' | '.join(out), f'top30 {tp:.2f}')


def newage():
    careers, rows, sc = load(range(2009, 2020))
    fit = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))
    m = fit['models']['newcomer']
    cands = ['age_new', 'young_new', 'old_new', 'age_x_rk']
    g = [r for r in rows if r['f']['newcomer']]
    old = [dict(r, y=r['yfull']) for r in g if r['year'] <= 2016 and r['last'] <= 2020]
    new = [dict(r, y=r['yk']) for r in g if r['yk'] is not None]
    add_test(old, m['kept'], cands, m['lam'], 'newcomers, 2009-16 boards, full peak')
    add_test(new, m['kept'], cands, m['lam'], 'newcomers, 2009-19 boards, k-season peak')


def gate(old_path, new_path):
    """two cbb_fit runs' out-of-fold / forward E[FV] (scripts/.cache/cbb/fit_oof.json, one per run) on the same board
    rows: the top-300 correlation with the outcome, the realized FV of each board's top 50 / 150, AUC of reaching the
    NBA, by board group, on the whole-career outcome and on the common-horizon one"""
    import harness as H
    a = {(r[0], r[1]): r for r in json.load(open(old_path))}
    b = {(r[0], r[1]): r for r in json.load(open(new_path))}
    keys = [k for k in b if k in a]
    for lab, yrs in (('2009-16 boards', range(2009, 2017)), ('2017-19 boards', range(2017, 2020)), ('2020 board', range(2020, 2021))):
        for yi, yname in ((6, 'whole career'), (5, 'first 6 seasons')):
            res = defaultdict(list); top_rows = {'old': [], 'new': []}
            for yr in yrs:
                ks = [k for k in keys if k[1] == yr and b[k][yi] is not None and (yi == 5 or b[k][2] <= 2020 or b[k][6] > 20)]
                if not ks: continue
                y = np.array([b[k][yi] for k in ks], float)
                for nm, src in (('old', a), ('new', b)):
                    e = np.array([src[k][4] for k in ks]); o = np.argsort(-e)
                    res[nm].append((float(np.corrcoef(e[o[:300]], y[o[:300]])[0, 1]), y[o[:50]].mean(), y[o[:150]].mean(), F.auc(e, y >= 30)))
                    top_rows[nm] += list(y[o[:150]])
            if not res: continue
            line = ' | '.join(f"{nm} corr300 {np.mean([x[0] for x in v]):.3f} top50 {np.mean([x[1] for x in v]):.2f} top150 {np.mean([x[2] for x in v]):.2f} auc {np.mean([x[3] for x in v]):.4f}" for nm, v in res.items())
            wins = sum(1 for x, z in zip(res['old'], res['new']) if z[0] > x[0])
            print(f'{lab:15s} {yname:16s} {line} | corr300 better {wins}/{len(res["new"])}')


CONFIGS = {
    # name: (boards fit on, outcome, inner folds)
    'A old: 2009-16, whole career, player folds': (range(2009, 2017), 'yfull', 'player'),
    'B 2009-16, whole career, class folds': (range(2009, 2017), 'yfull', 'class'),
    'C 2009-19, 6-season peak, player folds': (range(2009, 2020), 'yk', 'player'),
    'D new: 2009-19, 6-season peak, class folds': (range(2009, 2020), 'yk', 'class'),
    'E 2009-16, whole career, class folds, newcomer age': (range(2009, 2017), 'yfull', 'class'),
    'F 2009-16, whole career, player folds, newcomer age': (range(2009, 2017), 'yfull', 'player'),
}
AGE = ('age_new', 'young_new', 'old_new')
REUSE = {'E': 'B', 'F': 'A'}   # same returner fits: only the newcomer candidates differ


def grid(which=None):
    """every config through one protocol: outer folds hold out whole college classes (2009-23 exits, 5 folds); inside,
    the config's own selection (cbb_fit.select) on its own boards, outcome and inner folds; the outer class is then
    scored on every 2009-19 board it appears on. The same rows for every config, so the gates compare like with like."""
    careers, rows, sc = load(range(2009, 2020))
    F.TOP_MEAN = round(float(np.mean([r['y6'] for r in rows if r['y6'] is not None and r['y6'] >= 60 and r['last'] in F.SCALE_CLASSES] or [67.0])), 2)
    univ = [r for r in rows if r['yk'] is not None]
    outer = np.array([class_fold(r['last']) for r in univ])
    cache = os.path.join(D.CACHE, 'core_grid.json')
    done = json.load(open(cache)) if os.path.exists(cache) else {}
    for name, (win, yk, inner) in CONFIGS.items():
        if which and not name.startswith(which): continue
        if name in done: continue
        e = np.zeros(len(univ)); kept = {}
        for grp in ('newcomer', 'returner'):
            cands = (F.NEW_CANDS + ([] if name[0] in 'AB' else list(AGE))) if grp == 'newcomer' else F.RET_CANDS
            gi = np.array([r['f']['newcomer'] == (grp == 'newcomer') for r in univ])
            if grp == 'returner' and name[0] in REUSE:
                src = next(v for n, v in done.items() if n[0] == REUSE[name[0]])
                e[gi] = np.array(src['e'])[gi]; continue
            for k in range(5):
                tr = []
                for r, o, g in zip(univ, outer, gi):
                    if not g or o == k or r['year'] not in win or r[yk] is None: continue
                    if yk == 'yfull' and r['last'] > 2020: continue
                    x = {'pid': r['pid'], 'y': r[yk], 'f': r['f']}
                    if inner == 'class': x['fold'] = class_fold(r['last'])
                    tr.append(x)
                sel = F.select(tr, cands, f'{name} {grp} outer {k}')
                m = F.fit(tr, F.matrix(tr, sel['kept']), list(range(len(sel['kept']))), sel['lam'])
                te = np.where(gi & (outer == k))[0]
                e[te] = F.predict(m, F.matrix([univ[i] for i in te], sel['kept']))[2]
                kept[f'{grp}{k}'] = sel['kept']
        done[name] = {'e': [round(float(x), 4) for x in e], 'kept': kept}
        json.dump(done, open(cache, 'w'))
    keys = [(r['pid'], r['year']) for r in univ]
    for name, v in done.items():
        json.dump([[r['pid'], r['year'], r['last'], int(r['f']['newcomer']), x, r['yk'], r['yfull']] for r, x in zip(univ, v['e'])],
                  open(os.path.join(D.CACHE, 'grid_' + name[0] + '.json'), 'w'))


def reduce():
    """the shipped drivers against the set without the ledger's 'drop' verdicts (data/cbb_fit.json ledger), same
    penalties, no reselection: 2009-16 boards out of fold (whole classes held out) and the 2017-19 boards forward
    (players on the training boards left out), on the gates"""
    careers, rows, sc = load(range(2009, 2020))
    fit = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))
    tr = [r for r in rows if r['year'] <= 2016 and r['last'] <= 2020]
    seen = {r['pid'] for r in tr}
    ho = [r for r in rows if r['year'] >= 2017 and r['yk'] is not None and r['pid'] not in seen]
    for r in tr: r['y'] = r['yfull']
    cls = np.array([class_fold(r['last']) for r in tr])
    res = {}
    for name in ('shipped', 'reduced'):
        e_tr, e_ho = np.zeros(len(tr)), np.zeros(len(ho)); Ptr = np.zeros((len(tr), 4)); Pho = np.zeros((len(ho), 4))
        for grp, m in fit['models'].items():
            kept = [k for k in m['kept'] if name == 'shipped' or next(x for x in m['ledger'] if x['term'].endswith(':' + k))['verdict'] != 'drop']
            gi = np.array([r['f']['newcomer'] == (grp == 'newcomer') for r in tr]); hi = np.array([r['f']['newcomer'] == (grp == 'newcomer') for r in ho])
            for k in range(5):
                a = [r for r, g, c in zip(tr, gi, cls) if g and c != k]; b = np.where(gi & (cls == k))[0]
                mm = F.fit(a, F.matrix(a, kept), list(range(len(kept))), m['lam'])
                _, Ptr[b], e_tr[b] = F.predict(mm, F.matrix([tr[i] for i in b], kept))
            a = [r for r, g in zip(tr, gi) if g]
            mm = F.fit(a, F.matrix(a, kept), list(range(len(kept))), m['lam'])
            b = np.where(hi)[0]; _, Pho[b], e_ho[b] = F.predict(mm, F.matrix([ho[i] for i in b], kept))
            print(name, grp, kept)
        res[name] = (e_tr, e_ho, Ptr, Pho)
    for lab, rs, ix, yk in (('2009-16 boards OOF', tr, 0, 'yfull'), ('2017-19 boards held', ho, 1, 'yk')):
        y = np.array([r[yk] for r in rs]); yr = np.array([r['year'] for r in rs])
        for name, v in res.items():
            e = v[ix]; out = []
            for b in sorted(set(yr)):
                m_ = yr == b; o = np.argsort(-e[m_]); yy = y[m_][o]; ee = e[m_][o]
                out.append((np.corrcoef(ee[:300], yy[:300])[0, 1], yy[:50].mean(), yy[:150].mean()))
            out = np.array(out)
            print(f'{lab:20s} {name:8s} dev {F.deviance(v[ix + 2], y):.4f} auc {F.auc(e, y >= 30):.4f} corr300 {out[:, 0].mean():.3f} top50 {out[:, 1].mean():.2f} top150 {out[:, 2].mean():.2f}  per board corr {np.round(out[:, 0], 3)}')


if __name__ == '__main__':
    ({'window': window, 'newage': newage, 'grid': lambda: grid(sys.argv[2] if len(sys.argv) > 2 else None), 'reduce': reduce, 'gate': lambda: gate(*sys.argv[2:4])})[sys.argv[1]]()
