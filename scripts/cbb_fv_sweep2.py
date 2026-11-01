#!/usr/bin/env python3
"""CBB FV constructed-proxy sweep (Nov 1 2026, research only): new returner drivers on top of the shipped ladder.

    python3 scripts/cbb_careers_kit.py      # once: scripts/.cache/cbb/careers.json
    python3 scripts/cbb_fv_sweep2.py --pull # Barttorvik getgamestats (head coach per team-season, 2008-26) and the
                                            # player game logs ({y}_all_advgames.json.gz, 2010-25) into scripts/.cache/cbb
    python3 scripts/cbb_fv_sweep2.py [cand,cand,...]   # -> scripts/data/cbb_fv_sweep2.json

Candidates (each added alone to data/cbb_fit.json's returner kept set; 'swap' ones replace kept drivers):
  coach development, ROLLING (only seasons before the board; the player's own seasons left out; E refit each year):
    co_lvl_last  his last-season head coach's effect on players' BPM over expectation (recruit -ln rank, class, height,
                 season), minutes-weighted, empirical-Bayes shrunk, any school (school_dev cbb-coach, as of the board)
    co_lvl       the same over every prior season's coach, minutes-weighted (career exposure to BPM-inflating systems)
    co_dev_last  last coach's year-over-year BPM gain over expectation (prior BPM, class, rank) = development, not level
    co_dev_next  the coming season's head coach's development effect (hire known by Nov 1)
    swap:bpmc    bpm and bpm3 net of the coach level effect (bpm - co_lvl_last, bpm3 - co_lvl)
  shooting touch: ft_car (FT% pooled over every prior season, shrunk to .69 by 40 attempts; last season's ft failed),
    touch = ft_car x log(1 + career 3PA a 40) (touch where he shoots)
  durability from game logs (2010+): streak (longest run of team games missed after his first game last season,
    season-ending absence included, log1p), inj_car (career share of team games missed between his first game and
    the team's last), inj_any (a 5+ game absence in any prior season)
  role trajectory: usg_gain (usage last season - the season before), traj (usage gain + ortg gain, each in SDs)
  skills unusual for size (z within 2-inch height bands, prior-season lines): ast_hz, blk_hz (guards' height, <= 6-6),
    stl_hz (bigs' height, >= 6-9), odd_skill = sum of the positive parts
Gate: (1) the board's fold rule on 2009-16 boards: whole college classes out (cbb_fit.nested folds) plus the two
player splits, clustered t >= 2, >= 4/5 folds; (2) top of board: fit 2009-16, held 2017-19 boards on the horizon
outcome (cbb_fit.ledger): top 10 / 25 / 50 realized and top-300 corr not worse; (3) forward: the same fit graded on the
2020-23 boards (newer classes). All rows from the shipped feature code (cbb_fit.features)."""
import csv, gzip, hashlib, json, math, os, sys, subprocess
from collections import defaultdict, Counter
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
import cbb_fit as F
import cbb_fv_drivers as H

CA = os.path.join(D.CACHE, 'gamestats'); ADV = os.path.join(D.CACHE, 'advgames')
OUT = os.path.join(D.ROOT, 'scripts', 'data', 'cbb_fv_sweep2.json')
UA = 'Mozilla/5.0'


def pull():
    os.makedirs(CA, exist_ok=True); os.makedirs(ADV, exist_ok=True)
    for y in range(2008, 2027):
        p = os.path.join(CA, f'{y}.csv')
        if not os.path.exists(p):
            subprocess.run(['curl', '-sS', '-m', '120', '-A', UA, f'https://barttorvik.com/getgamestats.php?year={y}&tvalue=All&csv=1', '-o', p])
    for y in range(2010, 2026):
        p = os.path.join(ADV, f'{y}_all_advgames.json.gz')
        if not os.path.exists(p):
            subprocess.run(['curl', '-sS', '-m', '300', '-A', UA, f'https://barttorvik.com/{y}_all_advgames.json.gz', '-o', p])


def coach_map():
    """(year, Barttorvik team) -> the head coach who coached most of its games (getgamestats col 25)"""
    out = {}
    for fn in sorted(os.listdir(CA)):
        y = int(fn[:4]); cnt = defaultdict(Counter)
        for r in csv.reader(open(os.path.join(CA, fn), newline='', encoding='utf-8', errors='replace')):
            if len(r) > 26 and r[25].strip(): cnt[r[2]][r[25].strip()] += 1
        for t, c in cnt.items(): out[(y, t)] = c.most_common(1)[0][0]
    return out


# ---- coach effects, rolling ----------------------------------------------------------------------------------------
def coach_rows(careers, CM):
    """one row per player-season (100+ minutes): level residual inputs and the year-over-year development inputs"""
    R = []
    for c in careers:
        prevL = None
        for i, s in enumerate(c['seasons']):
            L = F.season_line(s)
            co = CM.get((s['year'], s['team']))
            if L['mpt'] >= 100 and co:
                rf = F.rec_feats(c, s['year'])
                x = [1.0, rf['rg_lrk'], max(0.0, rf['rg_lrk'] + math.log(50)), rf['unranked2'], (s['hti'] or 77) - 77] + \
                    [1.0 if F.CLS.get(s['yr'], 1) == k else 0.0 for k in (2, 3, 4)]
                d = None
                if prevL is not None and prevL['mpt'] >= 100:
                    d = [1.0, prevL['bpm'], rf['rg_lrk'], rf['unranked2']] + [1.0 if F.CLS.get(s['yr'], 1) == k else 0.0 for k in (2, 3, 4)]
                R.append({'pid': c['pid'], 'year': s['year'], 'coach': co, 'w': min(L['mpt'], 1200) / 1200, 'bpm': L['bpm'],
                          'x': x, 'd': d, 'dy': (L['bpm'] - prevL['bpm']) if d else None})
            prevL = L
    return R


def coach_effects(R, years, k_lvl=None, k_dev=None):
    """board year Y -> coach -> (level sum, level weight, dev sum, dev weight) over seasons <= Y-1, residuals from an E
    refit on those seasons only, plus each player's own contribution (to leave himself out), and the shrink k"""
    out = {}
    yr = np.array([r['year'] for r in R]); W = np.array([r['w'] for r in R])
    X = np.array([r['x'] for r in R]); yb = np.array([r['bpm'] for r in R])
    hasd = np.array([r['d'] is not None for r in R])
    Dx = np.array([r['d'] if r['d'] is not None else [0.0] * 7 for r in R]); dy = np.array([r['dy'] if r['dy'] is not None else 0.0 for r in R])
    yfe = sorted(set(yr))
    for Y in years:
        on = yr <= Y - 1
        if on.sum() < 500: continue
        # season fixed effects inside the window
        Ys = [v for v in yfe if v <= Y - 1]
        FE = np.column_stack([(yr == v).astype(float) for v in Ys[1:]]) if len(Ys) > 1 else np.zeros((len(R), 0))
        XX = np.hstack([X, FE]); DD = np.hstack([Dx, FE])
        sw = np.sqrt(W[on])
        b = np.linalg.lstsq(XX[on] * sw[:, None], yb[on] * sw, rcond=None)[0]
        rl = yb - XX @ b
        od = on & hasd
        if od.sum() >= 500:
            bd = np.linalg.lstsq(DD[od] * np.sqrt(W[od])[:, None], dy[od] * np.sqrt(W[od]), rcond=None)[0]
            rd = dy - DD @ bd
        else:   # no year-over-year pairs yet (the 2009 board): no development read
            od = np.zeros(len(R), bool); rd = np.zeros(len(R))
        C = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]); P = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
        for j in np.where(on)[0]:
            r = R[j]; g = C[r['coach']]; p = P[(r['pid'], r['coach'])]
            g[0] += W[j] * rl[j]; g[1] += W[j]; p[0] += W[j] * rl[j]; p[1] += W[j]
            if od[j]:
                g[2] += W[j] * rd[j]; g[3] += W[j]; p[2] += W[j] * rd[j]; p[3] += W[j]
        s2d = float(np.average(rd[od] ** 2, weights=W[od])) if od.any() else 1.0
        out[Y] = (dict(C), dict(P), float(np.average(rl[on] ** 2, weights=W[on])), s2d)
    return out


def tau_k(CE, Y):
    """shrink k = s2 / tau2 by method of moments on coach means (weights in 1200-minute seasons)"""
    C, _, s2l, s2d = CE[Y]
    ks = []
    for a, b, s2 in ((0, 1, s2l), (2, 3, s2d)):
        S = [(v[a] / v[b], v[b]) for v in C.values() if v[b] >= 2]
        if len(S) < 20: ks.append(1e9); continue
        m = np.array([x for x, _ in S]); w = np.array([x for _, x in S])
        mu = (w * m).sum() / w.sum()
        Q = (w * (m - mu) ** 2).sum() / s2
        tau2 = max(1e-3, (Q - (len(S) - 1)) * s2 / (w.sum() - (w ** 2).sum() / w.sum()))
        ks.append(s2 / tau2)
    return ks


def ceff(CE, KS, Y, coach, pid, dev=False):
    if Y not in CE or coach is None: return 0.0
    C, P, _, _ = CE[Y]
    g = C.get(coach); p = P.get((pid, coach), [0.0] * 4)
    if not g: return 0.0
    a, b = (2, 3) if dev else (0, 1)
    k = KS[Y][1 if dev else 0]
    return (g[a] - p[a]) / (g[b] - p[b] + k)


# ---- game-log availability ----------------------------------------------------------------------------------------
def absences():
    """(pid, year) -> (longest run of team games missed after his first game, incl. season-ending; missed share of team
    games between his first game and the team's last); from Barttorvik player game logs, 2010+"""
    out = {}
    if not os.path.isdir(ADV): return out
    for fn in sorted(os.listdir(ADV)):
        if not fn.endswith('.json.gz'): continue
        y = int(fn[:4])
        tg = defaultdict(set); pg = defaultdict(set); pt = {}
        for g in json.load(gzip.open(os.path.join(ADV, fn))):
            t, gid, pid = g[47], g[6], str(g[51])   # g[5] is the opponent
            tg[t].add((g[0], gid))
            try:
                if float(g[8] or 0) > 0: pg[(pid, t)].add((g[0], gid))
            except (TypeError, ValueError):
                pass
        for (pid, t), gs in pg.items():
            T = sorted(tg[t]); first = min(gs)
            T = [x for x in T if x >= first]
            run = best = miss = 0
            for x in T:
                if x in gs: run = 0
                else:
                    run += 1; miss += 1; best = max(best, run)
            o = out.get((pid, y))
            v = (best, miss / max(1, len(T)), len(T))
            if not o or v[2] > o[2]: out[(pid, y)] = v
    return out


def band_stats(careers):
    """per 2-inch height band: mean / sd of prior-season ast, blk, stl (season lines with 300+ minutes, 2008-16)"""
    acc = defaultdict(lambda: defaultdict(list))
    for c in careers:
        for s in c['seasons']:
            if s['year'] > 2016: continue
            L = F.season_line(s)
            if L['mpt'] < 300 or not s['hti']: continue
            b = int((s['hti'] - 70) // 2)
            for k in ('ast', 'blk', 'stl'): acc[b][k].append(L[k])
    return {b: {k: (float(np.mean(v)), float(np.std(v)) or 1.0) for k, v in d.items()} for b, d in acc.items() if len(d['ast']) >= 50}


CTX = {}


def extra(c, i, f):
    """the candidate drivers for a returner's board season i (from seasons before it)"""
    s = c['seasons'][i]; prev = c['seasons'][:i]; Y = s['year']; pid = c['pid']
    CM, CE, KS, AB, BS = CTX['cm'], CTX['ce'], CTX['ks'], CTX['ab'], CTX['bs']
    p = prev[-1]
    cl = CM.get((p['year'], p['team']))
    f['co_lvl_last'] = ceff(CE, KS, Y, cl, pid)
    f['co_dev_last'] = ceff(CE, KS, Y, cl, pid, dev=True)
    f['co_dev_next'] = ceff(CE, KS, Y, CM.get((Y, s['team'])), pid, dev=True)
    num = den = 0.0
    for r in prev:
        w = (r['mp'] or 0) * (r['gp'] or 0)
        num += w * ceff(CE, KS, Y, CM.get((r['year'], r['team'])), pid); den += w
    f['co_lvl'] = num / den if den else 0.0
    f['bpmc'] = f['bpm'] - f['co_lvl_last']; f['bpm3c'] = f['bpm3'] - f['co_lvl']
    # touch
    ftm = sum((r['ftm'] or 0) for r in prev); fta = sum((r['fta'] or 0) for r in prev)
    f['ft_car'] = (ftm + 0.69 * 40) / (fta + 40)
    mpt = sum((r['mp'] or 0) * (r['gp'] or 0) for r in prev); tpa = sum((r['tpa'] or 0) for r in prev)
    f['touch'] = (f['ft_car'] - 0.69) * math.log1p(tpa / max(mpt, 40) * 40)
    # availability (game logs from 2010)
    # only seasons as a regular (15+ minutes a game where he played): a bench player's DNPs are coaching decisions
    reg = lambda r: (r['mp'] or 0) >= 15 and (str(pid), r['year']) in AB
    if p['year'] >= 2010:
        a = AB.get((str(pid), p['year']))
        f['streak'] = math.log1p(a[0]) if a and reg(p) else 0.0
        sh = [AB[(str(pid), r['year'])][1] for r in prev if r['year'] >= 2010 and reg(r)]
        f['inj_car'] = float(np.mean(sh)) if sh else 0.0
        f['inj_any'] = 1.0 if any(reg(r) and AB[(str(pid), r['year'])][0] >= 5 for r in prev if r['year'] >= 2010) else 0.0
    else:
        f['streak'] = f['inj_car'] = f['inj_any'] = None
    # role trajectory
    if len(prev) >= 2:
        L0 = F.season_line(prev[-2])
        f['usg_gain'] = f['usg'] - L0['usg']
        f['traj'] = (f['usg'] - L0['usg']) / 4.0 + (f['ortg'] - L0['ortg']) / 10.0
    else:
        f['usg_gain'] = f['traj'] = 0.0
    # skills unusual for size
    b = int(((p['hti'] or f['ht']) - 70) // 2); bs = BS.get(b) or BS.get(max(min(b, max(BS)), min(BS)))
    z = {k: (f[k] - bs[k][0]) / bs[k][1] for k in ('ast', 'blk', 'stl')}
    f['ast_hz'] = z['ast']
    f['blk_hz'] = z['blk'] if f['ht'] <= 78 else 0.0
    f['stl_hz'] = z['stl'] if f['ht'] >= 81 else 0.0
    f['odd_skill'] = max(0.0, f['blk_hz']) + max(0.0, f['stl_hz']) + (max(0.0, z['ast']) if f['ht'] >= 80 else 0.0)
    return f


CANDS = ['co_lvl_last', 'co_lvl', 'co_dev_last', 'co_dev_next', 'swap:bpmc', 'ft_car', 'touch', 'streak', 'inj_car', 'inj_any',
         'usg_gain', 'traj', 'ast_hz', 'blk_hz', 'stl_hz', 'odd_skill']


def colset(kept, cand):
    if cand.startswith('swap:'):
        return [{'bpm': 'bpmc', 'bpm3': 'bpm3c'}.get(k, k) for k in kept]
    return kept + [cand]


def ctstat(diff, cl):
    g = defaultdict(float)
    for p, v in zip(cl, diff): g[p] += v
    v = np.array(list(g.values()))
    return float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v))))


def cv(rows, kept, lam, cand, cache):
    """OOS rung deviance change on 2009-16 boards, three fold rules, clustered by player"""
    y = np.array([r['y'] for r in rows], float); pid = [r['pid'] for r in rows]
    splits = {'cls': np.array([r['cls'] for r in rows]), 'md5': np.array([F.fold_of(p) for p in pid]),
              'salt': np.array([int(hashlib.md5(('s' + str(p)).encode()).hexdigest(), 16) % F.FOLDS for p in pid])}
    res = {}
    cols = colset(kept, cand)
    for n, fo in splits.items():
        if n not in cache:
            X0 = F.matrix(rows, kept); cache[n] = F.row_dev(H.oof(rows, X0, list(range(len(kept))), lam, fo, kept), y)
        X = F.matrix(rows, cols)
        RD = cache[n] - F.row_dev(H.oof(rows, X, list(range(len(cols))), lam, fo, cols), y)
        d = RD.sum(1)
        res[n] = {'gain': round(float(d.sum() * 100), 3), 'folds': int(sum(d[fo == k].sum() > 0 for k in range(F.FOLDS))),
                  't': round(ctstat(d, pid), 2), 'rungs': [round(float(x * 100), 3) for x in RD.sum(0)]}
    return res


def board_tops(rs, E, yv):
    yrs = np.array([r['year'] for r in rs]); out = defaultdict(list)
    for Y in sorted(set(yrs)):
        ix = np.where(yrs == Y)[0]; o = ix[np.argsort(-E[ix])]
        for N in (10, 25, 50): out[f'top{N}'].append(yv[o[:N]].mean())
        out['corr300'].append(np.corrcoef(E[o[:300]], yv[o[:300]])[0, 1])
    return {k: np.array(v) for k, v in out.items()}


def held(rows, hr, kept, lam, cand, base_cache):
    """fit on 2009-16, grade the held boards (2017-19 'held', 2020-23 'fwd') on the horizon outcome"""
    out = {}
    for tag, lo, hi in (('held', 2017, 2019), ('fwd', 2020, 2023)):
        sub = [r for r in hr if lo <= r['year'] <= hi]
        yh = np.array([r['yh'] for r in sub], float)
        if tag not in base_cache:
            m = F.fit(rows, F.matrix(rows, kept), list(range(len(kept))), lam)
            P = F.predict(m, F.matrix(sub, kept))[1]
            base_cache[tag] = (P, board_tops(sub, F.expected(P), yh))
        P0, T0 = base_cache[tag]
        cols = colset(kept, cand)
        m = F.fit(rows, F.matrix(rows, cols), list(range(len(cols))), lam)
        P1 = F.predict(m, F.matrix(sub, cols))[1]
        T1 = board_tops(sub, F.expected(P1), yh)
        d = F.row_dev(P0, yh).sum(1) - F.row_dev(P1, yh).sum(1)
        yrs = np.array([r['year'] for r in sub])
        o = {'gain': round(float(d.sum() * 100), 3), 't': round(ctstat(d, [r['pid'] for r in sub]), 2),
             'years': f"{sum(d[yrs == Y].sum() > 0 for Y in sorted(set(yrs)))}/{len(set(yrs))}"}
        for k in T0:
            o[k] = (round(float(T0[k].mean()), 3), round(float(T1[k].mean()), 3), int((T1[k] > T0[k]).sum()), int((T1[k] < T0[k]).sum()))
        out[tag] = o
    return out


def main():
    if '--pull' in sys.argv:
        return pull()
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    thr = F.xpm_scale(careers)
    for c in careers: c['nba']['fvx'] = F.xpm_fv(c, thr)
    F.horizon_fv(careers)
    CM = coach_map()
    R = coach_rows(careers, CM)
    CE = coach_effects(R, range(2009, 2024))
    KS = {Y: tau_k(CE, Y) for Y in CE}
    print('coach shrink k (level, dev) by board year', {Y: [round(x, 1) for x in v] for Y, v in KS.items()})
    CTX.update(cm=CM, ce=CE, ks=KS, ab=absences(), bs=band_stats(careers))
    fitj = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))
    M = fitj['models']['returner']; F.TOP_MEAN = M['topMean']
    rows, hr = [], []
    for c in careers:
        for i, s in enumerate(c['seasons']):
            if not (2009 <= s['year'] <= 2023) or i == 0: continue
            f = extra(c, i, F.features(c, i))
            r = {'pid': c['pid'], 'name': c['name'], 'year': s['year'], 'y': c['nba']['fvx'], 'yh': c['nba']['fvh'], 'last': c['last'],
                 'cls': (c['last'] - 2009) % F.FOLDS, 'f': f}
            if s['year'] in F.TRAIN and c['last'] <= 2020: rows.append(r)
            elif s['year'] >= 2017 and c['nba']['fvh'] is not None: hr.append(r)
    seen = {r['pid'] for r in rows}
    hr = [r for r in hr if r['pid'] not in seen]
    print(f'returner rows: train {len(rows)}, held 2017-19 {sum(r["year"] <= 2019 for r in hr)}, fwd 2020-23 {sum(r["year"] >= 2020 for r in hr)}')
    pick = sys.argv[1].split(',') if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else CANDS
    for cnd in pick:
        k = cnd.replace('swap:', '').rstrip('c') if cnd.startswith('swap') else cnd
        v = np.array([r['f'].get(cnd if not cnd.startswith('swap') else 'bpm3c') for r in rows], dtype=float)
        nba = np.array([r['y'] >= 30 for r in rows])
        print(f'  {cnd}: sd {np.nanstd(v):.3f}, mean NBA {np.nanmean(v[nba]):+.3f} vs non {np.nanmean(v[~nba]):+.3f}, missing {int(np.isnan(v).sum())}')
    res = {}; cvc = {}; hc = {}
    prev = json.load(open(OUT)) if os.path.exists(OUT) else {}
    res.update(prev.get('results', {}))
    for cnd in pick:
        a = cv(rows, M['kept'], M['lam'], cnd, cvc)
        b = held(rows, hr, M['kept'], M['lam'], cnd, hc)
        res[cnd] = {'cv': a, **b}
        print(cnd, json.dumps(res[cnd]))
        sys.stdout.flush()
    json.dump({'asof': __import__('datetime').date.today().isoformat(), 'results': res}, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
