#!/usr/bin/env python3
"""New-driver search for the College Basketball ARKBOARD FV model (research harness, Oct 24 2026).

    python3 scripts/cbb_careers_kit.py          # once: scripts/.cache/cbb/careers.json
    python3 scripts/cbb_fv_drivers.py           # -> scripts/data/cbb_fv_drivers.json

Each candidate is added on its own to the shipped driver set (data/cbb_fit.json, same rung penalties) and scored the
way cbb_fit.py selects: out-of-sample deviance over the ladder rungs (P(NBA), 40+, 50+, 60+), each rung on the players
who reached the rung below, divided by its null deviance. Two independent 5-fold splits by player (cbb_fit's md5 split
and a salted one), and a player-clustered paired t on the per-row deviance change. Bar to send to cbb_fit's selection:
gain in both splits, >= 4/5 folds in each, clustered t >= 2. The candidates are draft-analytics staples the board had
not tried: age-adjusted and peak production, development slope, skill for size (passing, shooting, blocks by a guard),
team context (team strength, share of the team's production, conference strength), availability (games missed),
transfer level, pedigree x production and pedigree decay. The outcome is cbb_fit's: realized FV on peak NBA XPM.
    python3 scripts/cbb_fv_drivers.py --hurdle +bpm3_age     # phase 2: drivers limited to the P(NBA) rung (*@1, *@2)
    python3 scripts/cbb_fv_drivers.py --forward a.json b.json   # two cbb_fit.json fits on the 2017-20 boards

Result (Oct 24 2026; scripts/data/cbb_fv_drivers.json, cbb_fv_drivers_hurdle.json): three pass this bar. bpm3_age (3-season
BPM - 1.5 x (age - 20.5); OOS +0.9 points, t 3.5, mostly the star rung), and on the P(NBA) rung only usage (+0.38, t 4.4)
and last season's team strength (minutes-weighted team BPM, +0.32, t 4.6). Refit through cbb_fit's own selection,
returner OOS pseudo-R2 .170 -> .186 (all three) or .177 (bpm3_age alone). None shipped: the held-out checks that read
the headline disagree. Forward on the 2017-20 boards (fit on 2009-16), bpm3_age lowers RMSE of E[FV] (3.904 -> 3.882)
and lifts the top 50 a board (38.3 -> 38.5; top 150 33.6 -> 33.4), but on the 2009-16 boards out of fold the top 300's correlation with the
outcome falls (.439 -> .417) and the FV range fit (fv_dist_fit.py) scores worse (RPS .0767 -> .0782). Usage and team
strength sharpen P(NBA) (AUC .927 -> .931) but push down the top (the 150 highest E[FV] of the 2017-20 boards
realized 40.3 -> 39.4). A
gradient-boosted ladder on the same and 24 more drivers (sklearn, research only) loses to the logistic ladder held out
(upper rungs overfit, deviance .83 -> 1.0): the board's drivers sit near what Barttorvik and recruiting data can say.
"""
import json, math, os, sys, hashlib
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
import cbb_fit as F

OUT = os.environ.get('CBB_DRV_OUT') or os.path.join(D.ROOT, 'scripts', 'data', 'cbb_fv_drivers.json')


def team_maps(careers):
    """per (team, year): games (the most any player played), strength (minutes-weighted BPM sum, about the team's
    net per 100 over an average D-I team) and the PRPG! total; per (conf, year): mean team strength."""
    g = defaultdict(float); st = defaultdict(float); pr = defaultdict(float); conf = {}
    for c in careers:
        for s in c['seasons']:
            k = (s['team'], s['year'])
            g[k] = max(g[k], s['gp'] or 0)
            mp = (s['min_per'] or 0) / 100
            st[k] += (s['bpm'] or 0) * mp
            pr[k] += max(0.0, (s['porpag'] or 0) * mp)
            conf[k] = s['conf']
    cs = defaultdict(list)
    for k, v in st.items(): cs[(conf[k], k[1])].append(v)
    return g, st, pr, {k: float(np.mean(v)) for k, v in cs.items()}


TM = None


def game_splits():
    """Barttorvik player game logs ({year}_all_advgames.json.gz, cached in scripts/.cache/cbb/advgames with the
    {year}_team_results.csv tables): per (pid, year), BPM against top-50 adjusted defenses minus the season's BPM, and
    the second half of the season minus the first, each weighted by the player's possessions and shrunk at 150."""
    import csv, gzip
    d = os.path.join(D.CACHE, 'advgames')
    out = {}
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith('.json.gz'):
            continue
        y = int(fn[:4])
        rk = {r['team']: int(r['de Rank']) for r in csv.DictReader(open(os.path.join(d, f'team{y}.csv')))}
        by = defaultdict(list)
        for g in json.load(gzip.open(os.path.join(d, fn))):
            try:
                w = float(g[43]) * float(g[8]) / 100
            except (TypeError, ValueError):
                continue
            if w > 0 and g[44] is not None:
                by[str(g[51])].append((g[0], w, float(g[44]), rk.get(g[5], 999)))
        for pid, gs in by.items():
            gs.sort()
            W = sum(x[1] for x in gs)
            if W < 100:
                continue
            m = sum(x[1] * x[2] for x in gs) / W
            t = [x for x in gs if x[3] <= 50]
            tw = sum(x[1] for x in t)
            top = (sum(x[1] * x[2] for x in t) / tw - m) * tw / (tw + 150) if tw else 0.0
            h = len(gs) // 2
            a, b = gs[:h], gs[h:]
            wa, wb = sum(x[1] for x in a), sum(x[1] for x in b)
            tr = ((sum(x[1] * x[2] for x in b) / wb) - (sum(x[1] * x[2] for x in a) / wa)) * min(wa, wb) / (min(wa, wb) + 150) if wa and wb else 0.0
            out[(pid, y)] = (max(-10, min(10, top)), max(-10, min(10, tr)))
    return out


GS = {}


def extra(c, i, f):
    """candidate drivers for a returner's board (career c, board season i), from what was known before it."""
    if f['newcomer']:
        g = c.get('rec') or {}
        lr = [-math.log(min(x, 500)) for x in (g.get('on3rk'), g.get('rk247')) if x]
        f['rk_sd'] = float(np.std(lr)) if len(lr) > 1 else 0.0
        f['n_src'] = float(len(lr))
        return f
    prev = c['seasons'][:i]
    s = c['seasons'][i]
    G, ST, PR, CS = TM
    lines = [F.season_line(r) for r in prev]
    b = [L['bpm'] for L in lines]
    f['bpm_peak'] = max(b)
    f['bpm_first'] = b[0]
    f['slope'] = float(np.polyfit(range(len(b)), b, 1)[0]) if len(b) >= 2 else 0.0
    # age-adjusted production: BPM over the age curve (about +1.5 BPM a year of age among college players)
    f['bpm_age'] = f['bpm'] - 1.5 * (f['age'] - 20.5)
    f['bpm3_age'] = f['bpm3'] - 1.5 * (f['age'] - 20.5)
    p = prev[-1]
    f['ast_x_ht'] = (f['ast'] - 12) * f['ht_g']
    f['ast_size'] = (f['ast'] - 12) * (f['ht'] - 78)
    f['tpa_x_ht'] = (f['tpa100'] - 4) * (f['ht'] - 78)
    f['tp_x_ht'] = (f['tp'] - 0.33) * (f['ht'] - 78) * 10
    f['blk_guard'] = f['blk'] * (1 - f['big'])
    f['blk_g'] = f['blk'] * f['guard']
    f['stl_big'] = f['stl'] * f['big']
    f['stocks'] = f['stl'] + 0.5 * f['blk']
    f['usg_x_ortg'] = (f['usg'] - 20) * (f['ortg'] - 100) / 10
    mpt = max(1.0, f['mpt'])
    f['pts40'] = F.shrink((p['pts_g'] or 0) * (p['gp'] or 0) / mpt * 40, mpt, 10, 300)
    f['reb40'] = F.shrink((p['treb_g'] or 0) * (p['gp'] or 0) / mpt * 40, mpt, 6, 300)
    f['rim_rate'] = F.shrink((p['rima'] or 0) / mpt * 40, mpt, 3, 300) if p['year'] >= 2010 else None
    f['ft40'] = F.shrink((p['fta'] or 0) / mpt * 40, mpt, 4, 300)
    tg = G.get((p['team'], p['year'])) or 30
    f['avail'] = min(1.0, (p['gp'] or 0) / max(tg, 1))
    f['avail_min'] = min(min(1.0, (r['gp'] or 0) / max(G.get((r['team'], r['year'])) or 30, 1)) for r in prev)
    f['missed'] = 1.0 if f['avail'] < 0.75 else 0.0
    f['team_str'] = ST.get((p['team'], p['year']), 0.0)
    f['conf_str'] = CS.get((p['conf'], p['year']), 0.0)
    f['share'] = max(0.0, f['prpg']) / max(1e-3, PR.get((p['team'], p['year']), 1.0))
    f['bpm_x_team'] = f['bpm'] * (f['team_str'] - 0) / 10
    f['bpm_x_conf'] = f['bpm'] * f['conf_str'] / 10
    f['now_conf_str'] = CS.get((s['conf'], s['year'] - 1), f['conf_str'])
    f['lvl_up'] = f['now_conf_str'] - f['conf_str'] if f['transfer'] else 0.0
    f['rg_x_bpm'] = (f['rg_lrk'] + 4.5) * f['bpm']
    f['rg_decay'] = (f['rg_lrk'] + 4.5) / f['nprev']
    f['min_jump'] = f['min_per'] - F.season_line(prev[-2])['min_per'] if len(prev) >= 2 else 0.0
    f['orb_wing'] = f['orb'] * (1 - f['big'])
    f['age_known'] = f.get('age_known', 0.0)
    # Oct 26 2026 round: dunks as an athleticism read (Barttorvik dunk makes, 2010+), share of rim makes that are
    # dunks, foul discipline (fouls a 40) and defensive events a foul ((steal% + block%) / fouls a 40), FT makes a 40.
    # Result (`returner --cands=dunk40,dunk_rim,pf40,stocks_pf,ftm40`): none passes. Best stocks_pf +0.46 / +0.65 but
    # t 1.0 / 1.5, all of it on the star rung (the pattern that hurt the top of the board before); dunk_rim t 1.0
    dk = p['year'] >= 2010 and p['dunkm'] is not None
    f['dunk40'] = F.shrink((p['dunkm'] or 0) / mpt * 40, mpt, 0.5, 300) if dk else None
    f['dunk_rim'] = F.shrink((p['dunkm'] or 0) / p['rimm'], p['rimm'], 0.25, 30) if dk and p['rimm'] else None
    f['pf40'] = F.shrink(p['pfr'], mpt, 4.5, 300) if p['pfr'] is not None else None
    f['stocks_pf'] = (f['stl'] + f['blk']) / max(1.5, f['pf40']) if f['pf40'] is not None else None
    f['ftm40'] = F.shrink((p['ftm'] or 0) / mpt * 40, mpt, 2.5, 300)
    # second round (Oct 26): BPM against top-50 defenses over the season's, and the late-season trend (game logs).
    # Result: both fail (top50 t -1.9 / -.66, 0/5 and 3/5 folds; trendS t -.82 / -1.68)
    g = GS.get((str(c['pid']), p['year']))
    f['top50'] = g[0] if g else None
    f['trendS'] = g[1] if g else None
    return f


RET_NEW = ['bpm_peak', 'bpm_first', 'slope', 'bpm_age', 'bpm3_age', 'ast_x_ht', 'ast_size', 'tpa_x_ht', 'tp_x_ht', 'blk_guard', 'blk_g',
           'stl_big', 'stocks', 'usg_x_ortg', 'pts40', 'reb40', 'rim_rate', 'ft40', 'avail', 'avail_min', 'missed', 'team_str', 'conf_str',
           'share', 'bpm_x_team', 'bpm_x_conf', 'lvl_up', 'rg_x_bpm', 'rg_decay', 'min_jump', 'orb_wing', 'age_known', 'young', 'ht', 'usg',
           'tp', 'tpa100', 'ft', 'rg_lrk', 'prpg', 'dprpg', 'age2', 'bpm_x_age', 'obpm_rel', 'dunk40', 'dunk_rim', 'pf40', 'stocks_pf', 'ftm40', 'top50', 'trendS']
NEW_NEW = ['rk_sd', 'n_src', 'ht', 'lrank', 'grade']


def row_dev(P, y, null):
    """each row's share of cbb_fit.deviance: per rung, its deviance / (the rung's null deviance x rungs), so the rows
    sum to the mean over rungs of deviance / null that cbb_fit selects on (each rung counts the same, who becomes a
    starter or a star as much as who reaches the NBA). Returns rows x rungs."""
    out = np.zeros((len(y), len(F.LADDER)))
    for j, t in enumerate(F.LADDER):
        on = y >= (F.LADDER[j - 1] if j else -1)
        prev = P[on, j - 1] if j else np.ones(on.sum())
        c = np.clip(P[on, j] / np.maximum(prev, 1e-9), 1e-6, 1 - 1e-6)
        o = (y[on] >= t).astype(float)
        out[on, j] = -(o * np.log(c) + (1 - o) * np.log(1 - c)) / (null[j] * len(F.LADDER))
    return out


RUNGS = {}   # driver -> how many rungs (from P(NBA) up) it may move; absent = all


def fit_m(rows, X, idx, lam, cols):
    """cbb_fit.fit, with a driver limited to its first RUNGS[d] rungs: its z is 0 on the rungs above, so its weight
    there is 0 (what the live appliers read as is: a 0 weight)."""
    y = np.array([r['y'] for r in rows], float)
    std = F.Std(X[:, idx]); Z = std(X[:, idx])
    ws = []
    for j, t in enumerate(F.LADDER):
        on = y >= (F.LADDER[j - 1] if j else -1)
        Zj = Z[on].copy()
        for q, i in enumerate(idx):
            if RUNGS.get(cols[i], 9) <= j: Zj[:, q] = 0
        w = F.logit_fit(Zj, (y[on] >= t).astype(float), lam[j] * max(1.0, on.sum() / 1000))
        for q, i in enumerate(idx):
            if RUNGS.get(cols[i], 9) <= j: w[q + 1] = 0.0
        ws.append(w)
    return {'std': std, 'idx': idx, 'w': ws}


def oof(rows, X, idx, lam, folds, cols=None):
    P = np.zeros((len(rows), len(F.LADDER)))
    for k in range(F.FOLDS):
        tr, te = folds != k, folds == k
        m = fit_m([r for r, t in zip(rows, tr) if t], X[tr], idx, lam, cols)
        P[te] = F.predict(m, X[te])[1]
    return P


_S = {}


def job(j):
    rows, X, base, lam, splits, null, y, pid, bdev, cols = _S['a']
    res = {}
    for name, folds in splits.items():
        P = oof(rows, X, base + [j], lam, folds, cols)
        D2 = bdev[name] - row_dev(P, y, null)   # + = the candidate lowers deviance
        diff = D2.sum(1)
        fold = [float(diff[folds == k].sum()) for k in range(F.FOLDS)]
        # player-clustered t
        cl = defaultdict(float)
        for p, v in zip(pid, diff): cl[p] += v
        v = np.array(list(cl.values()))
        t = v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))
        res[name] = {'gain': round(float(diff.sum() * 100), 3), 'folds': sum(1 for x in fold if x > 0), 't': round(float(t), 2),
                     'rungs': [round(float(x * 100), 3) for x in D2.sum(0)]}
    return j, res


def run(rows, kept, cands, lam, label):
    import multiprocessing as mp
    cols = kept + [c for c in cands if c not in kept]
    X = F.matrix(rows, cols)
    y = np.array([r['y'] for r in rows], float)
    pid = [r['pid'] for r in rows]
    splits = {'md5': np.array([F.fold_of(p) for p in pid]),
              'salt': np.array([int(hashlib.md5(('s' + str(p)).encode()).hexdigest(), 16) % F.FOLDS for p in pid])}
    null = []
    for j, t in enumerate(F.LADDER):
        on = y >= (F.LADDER[j - 1] if j else -1)
        o = (y[on] >= t).astype(float); m = o.mean()
        null.append(-(o * np.log(m) + (1 - o) * np.log(1 - m)).sum())
    base = list(range(len(kept)))
    bdev = {n: row_dev(oof(rows, X, base, lam, f, cols), y, null) for n, f in splits.items()}
    _S['a'] = (rows, X, base, lam, splits, null, y, pid, bdev, cols)
    with mp.get_context('fork').Pool(min(4, os.cpu_count() or 1)) as pool:
        res = pool.map(job, list(range(len(kept), len(cols))))
    out = []
    for j, r in res:
        ok = all(v['gain'] > 0 and v['folds'] >= 4 and v['t'] >= 2 for v in r.values())
        out.append({'driver': cols[j], **{f'{n}_{k}': v for n, d in r.items() for k, v in d.items()}, 'pass': ok})
    out.sort(key=lambda x: -x['md5_gain'])
    print(f'{label}: {len(rows)} rows; base {kept}')
    for o in out:
        print(f"  {o['driver']:13s} md5 {o['md5_gain']:+.3f} {o['md5_folds']}/5 t {o['md5_t']:+.2f} | salt {o['salt_gain']:+.3f} {o['salt_folds']}/5 t {o['salt_t']:+.2f} rungs {o['md5_rungs']} {'PASS' if o['pass'] else ''}")
    return out


def forward(paths):
    """each cbb_fit.json fit (cbb_fit.features must compute its drivers) on the 2017-20 preseason boards, careers done by
    2022: rung deviance, AUC, RMSE of E[FV], and the realized FV of each board's top 50 / 150."""
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    thr = F.xpm_scale(careers)
    for c in careers: c['nba']['fvx'] = F.xpm_fv(c, thr)
    fs, y, yr = [], [], []
    for c in careers:
        if c['last'] > 2022: continue
        for i, s in enumerate(c['seasons']):
            if 2017 <= s['year'] <= 2020: fs.append(F.features(c, i)); y.append(c['nba']['fvx']); yr.append(s['year'])
    y, yr = np.array(y), np.array(yr)
    for p in paths:
        fit = json.load(open(p)); P = np.zeros((len(fs), 4)); e = np.zeros(len(fs))
        for grp in ('newcomer', 'returner'):
            ix = [i for i, f in enumerate(fs) if f['newcomer'] == (grp == 'newcomer')]
            m = fit['models'][grp]
            X = np.array([[fs[i].get(k) if fs[i].get(k) is not None else np.nan for k in m['kept']] for i in ix], float)
            Z = np.clip(np.nan_to_num((X - np.array(m['mean'])) / np.array(m['sd'])), -4, 4)
            A = np.hstack([np.ones((len(Z), 1)), Z])
            P[ix] = np.cumprod(np.column_stack([1 / (1 + np.exp(-np.clip(A @ np.array(w), -30, 30))) for w in m['w']]), axis=1)
            e[ix] = F.FLOOR + 10 * (P[ix, 0] + P[ix, 1] + P[ix, 2]) + (m['topMean'] - 50) * P[ix, 3]
        top = {N: round(float(np.mean([y[i] for b in range(2017, 2021) for i in np.where(yr == b)[0][np.argsort(-e[yr == b])[:N]]])), 2) for N in (50, 150)}
        print(p, {'dev': round(F.deviance(P, y), 4), 'rungs': [round(float(x), 3) for x in F.rung_dev(P, y)], 'auc_nba': round(F.auc(e, y >= 30), 4),
                  'rmse': round(float(np.sqrt(((e - y) ** 2).mean())), 4), 'corr': round(float(np.corrcoef(e, y)[0, 1]), 4), 'top': top})


def main():
    global TM
    if '--forward' in sys.argv:
        return forward(sys.argv[sys.argv.index('--forward') + 1:])
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    TM = team_maps(careers)
    GS.update(game_splits())
    thr = F.xpm_scale(careers)
    for c in careers: c['nba']['fvx'] = F.xpm_fv(c, thr)
    rows = []
    for c in careers:
        if c['last'] > 2020: continue
        for i, s in enumerate(c['seasons']):
            if s['year'] not in F.TRAIN: continue
            f = extra(c, i, F.features(c, i))
            rows.append({'pid': c['pid'], 'name': c['name'], 'year': s['year'], 'y': c['nba']['fvx'], 'f': f})
    tops = [c['nba']['fvx'] for c in careers if c['last'] in F.SCALE_CLASSES and c['nba']['fvx'] >= 60]
    F.TOP_MEAN = round(float(np.mean(tops)), 2)
    fit = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))
    only = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else None
    res = {}
    if '--hurdle' in sys.argv:
        # phase 2: on top of the forward pick, drivers that the P(NBA) rung wants and the star rungs don't, limited to
        # the first rung (or the first two)
        m = fit['models']['returner']
        rr = [r for r in rows if not r['f']['newcomer']]
        kept = list(m['kept']) + [a for a in sys.argv if a.startswith('+')]
        kept = [k.lstrip('+') for k in kept]
        out = {}
        for nr in (1, 2):
            cands = [f'{c}@{nr}' for c in ('usg', 'pts40', 'ft40', 'team_str', 'conf_str', 'rg_lrk', 'rg_decay', 'prpg', 'bpm_x_conf', 'share', 'tpa100')]
            for r in rr:
                for c in cands: r['f'][c] = r['f'][c.split('@')[0]]
            for c in cands: RUNGS[c] = nr
            ks, steps = list(kept), []
            while cands:
                o = run(rr, ks, cands, m['lam'], f'hurdle {nr} rung(s) step {len(steps) + 1}')
                steps.append({'base': list(ks), 'tests': o})
                ok = [x for x in o if x['pass']]
                if not ok: break
                b = max(ok, key=lambda x: x['md5_gain'] + x['salt_gain'])
                ks.append(b['driver']); cands = [x['driver'] for x in o if x['md5_gain'] > 0 and x['driver'] != b['driver']]
            out[nr] = {'added': ks[len(kept):], 'steps': steps}
        json.dump({'asof': __import__('datetime').date.today().isoformat(), 'hurdle': out}, open(OUT.replace('.json', '_hurdle.json'), 'w'), indent=1)
        return
    pick = next((a.split('=', 1)[1].split(',') for a in sys.argv if a.startswith('--cands=')), None)   # limit the list
    for grp, cands in (('returner', pick or RET_NEW), ('newcomer', NEW_NEW)):
        if only and grp != only: continue
        m = fit['models'][grp]
        rr = [r for r in rows if r['f']['newcomer'] == (grp == 'newcomer')]
        kept, steps = list(m['kept']), []
        # forward: add the best candidate that passes, re-test the others that still gain on top of it, until none passes
        while cands:
            out = run(rr, kept, cands, m['lam'], f'{grp} step {len(steps) + 1}')
            ok = [o for o in out if o['pass']]
            steps.append({'base': list(kept), 'tests': out})
            if not ok: break
            best = max(ok, key=lambda o: o['md5_gain'] + o['salt_gain'])
            kept.append(best['driver'])
            cands = [o['driver'] for o in out if o['md5_gain'] > 0 and o['driver'] != best['driver']]
        res[grp] = {'shipped': m['kept'], 'added': kept[len(m['kept']):], 'steps': steps}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({'asof': __import__('datetime').date.today().isoformat(), 'results': res}, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
