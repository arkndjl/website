#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Tennis player value, held out -> data/tennis_value_research.json

    python3 scripts/tennis_value_research.py

One replay of every match (scripts/tennis_model.py Model on the fit params). Per player and match, before the update:
  pa   points won over what an average player (serve / return ratings 0) wins against this opponent, serve + return
  n    points played (both sides of the ball)
  rp   P(a replacement-level player beats this opponent): Elo (surface blend), replacement = the median pre-match
       Elo of players ranked 101-150 at the match, by tour
Metrics at a date T:
  rPA  raw rate: 100 x sum pa / sum n, the 52 weeks before T
  pPA  predictive rate: 100 x sum w pa / (sum w n + K), w = .5 ** (days before T / H), all history
  WAR  wins - sum rp, the 52 weeks before T, every level

Pre-registered (Nov 14 2026; Holm over the batch at .05):
  R1  pPA forecasts the next 52 weeks' rPA (players 1,000+ points then, weighted by points) better than rPA and
      than the points filter's own serve + return ratings (Model.pt). H, K picked leaving each target year out.
      Paired t by player (negative = pPA better), years better.
  C1  WAR at Dec 31 tracks the year-end ranking (rank at the player's first match of the next year) better than
      52-week wins and than W - L (Spearman, players with 20+ matches): paired difference of Spearman by year.
  C2  WAR at Dec 31 forecasts the next year-end ranking better than 52-week wins (same form).
  G1  game model: pPA gap (A - B, / 10) as an extra blend term, tune 2012-22, held 2023-26 log loss on tour-level
      main draws, t by tournament (negative = better); pass = held t < -1.96 after Holm and tune not worse. The
      H / K variant is the one best on tune; the others are reported, not tested.
  G2  game model: WAR a match (52 weeks) gap as an extra blend term, same gate.
"""
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tennis_model as M
import tennis_data as TD

OUT = os.path.join(os.path.dirname(HERE), 'data', 'tennis_value_research.json')
HS = [90, 180, 365, 730]
KS = [100, 300, 1000, 3000, 10000]


def sig(x):
    return 1 / (1 + math.exp(-x))


def replay(rows, P):
    """per-player match records and the game-model records (tour main draws 2012+) with the pPA / WAR state"""
    m = M.Model(P, M.CM_LAG)
    M.mark_two_week(rows)
    recs = defaultdict(list)       # pid -> [(day, yyyymmdd, tour, lv, won, ro, bo, pa, n, s, r)]
    band = defaultdict(list)       # tour -> pre-match Elo of players ranked 101-150
    game = []
    # online pPA state per H: pid -> [num, den, day]
    st = {h: {} for h in HS}

    def decay(h, pid, day):
        x = st[h].get(pid)
        if x is None:
            x = st[h][pid] = [0.0, 0.0, day]
        elif day > x[2]:
            f = 0.5 ** ((day - x[2]) / h); x[0] *= f; x[1] *= f; x[2] = day
        return x
    for r in rows:
        m.release(r[0])
        d, tour, lv, sf, rd, bo, tid, w, l, score, ws, ls = r[:12]
        day = M.dnum(d, rd, lv, tid)
        ew, el = m._e(w), m._e(l)
        sw = m.P['SW']
        bw = (1 - sw) * ew[0] + sw * ew[2][sf][0]
        bl = (1 - sw) * el[0] + sw * el[2][sf][0]
        for pid, rk, b in ((w, r[12], bw), (l, r[13], bl)):
            if rk and 101 <= rk <= 150 and m._e(pid)[1] >= 20:
                band[tour].append((d, b))
        if M.scored(r, 2012, 2100):
            pb, pe, pp, gx, cx = m.predict(w, l, tour, sf, day, bo)
            extra = {}
            for h in (180, 365):
                a, c = decay(h, w, day), decay(h, l, day)
                extra[h] = [(a[0] / (a[1] + K) - c[0] / (c[1] + K)) * 10 for K in (300, 1000, 3000)]
            game.append(((r, pe, pp, gx, cx), extra, w, l, day))
        mu = m.mu_of(tour, sf)
        pw, pl = m.pt.get(w, [0.0, 0, 0.0]), m.pt.get(l, [0.0, 0, 0.0])
        gw, gl, ret = M.games(score)
        if ws and ls and not ret and ws[0] and ls[0]:
            # winner serve: won ws[2]+ws[3] of ws[0]; winner return: won ls[0] - (ls[2]+ls[3]) of ls[0]
            pa_w = (ws[2] + ws[3] - ws[0] * sig(mu - pl[2])) + ((ls[0] - ls[2] - ls[3]) - ls[0] * (1 - sig(mu + pl[0])))
            pa_l = (ls[2] + ls[3] - ls[0] * sig(mu - pw[2])) + ((ws[0] - ws[2] - ws[3]) - ws[0] * (1 - sig(mu + pw[0])))
            n = ws[0] + ls[0]
        else:
            pa_w = pa_l = n = None
        for pid, won, ro, pa, x in ((w, 1, bl, pa_w, pw), (l, 0, bw, pa_l, pl)):
            recs[pid].append((day, d, tour, lv, won, ro, bo, pa, n, x[0], x[2]))
            if pa is not None:
                for h in HS:
                    s_ = decay(h, pid, day); s_[0] += pa; s_[1] += n
        m.update(r)
    return recs, band, game


def repl_line(band):
    out = {}
    for t, xs in band.items():
        v = sorted(b for _, b in xs)
        out[t] = v[len(v) // 2]
    return out


def p_repl(ro, rr, bo):
    p = 1 / (1 + 10 ** ((ro - rr) / 400))
    return M.bo5(p) if bo == 5 else p


def spearman(a, b):
    def rk(x):
        o = sorted(range(len(x)), key=lambda i: x[i]); r = [0] * len(x)
        for j, i in enumerate(o): r[i] = j
        return r
    ra, rb = rk(a), rk(b); n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    return num / math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))


def tstat(d):
    n = len(d); m = sum(d) / n; sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
    return m / (sd / math.sqrt(n)) if sd else 0.0


def ymd_day(y, mth=1, dd=1):
    return M.dnum(y * 10000 + mth * 100 + dd)


def snapshot(recs, rr, T):
    """per player at day T: rPA (52w), the pPA sums per H, WAR and wins (52w, every level), last s / r, matches"""
    out = {}
    for pid, xs in recs.items():
        a = [x for x in xs if T - 364 <= x[0] < T]
        if not a:
            continue
        tour = a[-1][2]
        pa = sum(x[7] for x in a if x[7] is not None); n = sum(x[8] for x in a if x[7] is not None)
        sums = {}
        for h in HS:
            num = den = 0.0
            for x in xs:
                if x[0] >= T: break
                if x[7] is None: continue
                f = 0.5 ** ((T - x[0]) / h); num += f * x[7]; den += f * x[8]
            sums[h] = (num, den)
        war = sum(x[4] - p_repl(x[5], rr[tour], x[6]) for x in a)
        wins = sum(x[4] for x in a)
        last = [x for x in xs if x[0] < T][-1]
        out[pid] = {'tour': tour, 'pa': pa, 'n': n, 'sums': sums, 'war': war, 'w': wins, 'l': len(a) - wins,
                    'm': len(a), 'sr': last[9] + last[10]}
    return out


def main():
    rows, players, tn = TD.load()
    fit = json.load(open(M.FIT))
    P = dict(M.DEFAULT, **fit.get('params', {}))
    print('replaying', len(rows), flush=True)
    recs, band, game = replay(rows, P)
    rr = repl_line(band)
    print('replacement Elo', rr, flush=True)
    # first-match ranking per player-year (for C1 / C2)
    rank0 = {}
    for r in rows:
        y = r[0] // 10000
        for pid, rk in ((r[7], r[12]), (r[8], r[13])):
            if rk and (pid, y) not in rank0:
                rank0[(pid, y)] = rk
    res = {'replacementElo': rr}
    years = list(range(2010, 2027))
    snaps = {y: snapshot(recs, rr, ymd_day(y)) for y in years}
    # R1: forecast next-52-week rPA from the snapshot at Jan 1 of year y (target = snapshot at Jan 1 of y+1)
    cases = []
    for y in years[:-1]:
        a, b = snaps[y], snaps[y + 1]
        for pid, s in a.items():
            t = b.get(pid)
            if not t or t['n'] < 1000 or s['n'] < 200:
                continue
            cases.append({'y': y + 1, 'pid': pid, 's': s, 'tgt': 100 * t['pa'] / t['n'], 'w': t['n'] / 1000})

    def wfit(xs, ys, ws):
        sw = sum(ws); mx = sum(w * x for x, w in zip(xs, ws)) / sw; my = sum(w * y for y, w in zip(ys, ws)) / sw
        sxx = sum(w * (x - mx) ** 2 for x, w in zip(xs, ws)); sxy = sum(w * (x - mx) * (y - my) for x, y, w in zip(xs, ys, ws))
        b = sxy / sxx if sxx else 0; return my - b * mx, b

    def ppa(c, h, K):
        num, den = c['s']['sums'][h]; return 100 * num / (den + K)
    cand = {'raw': lambda c: 100 * c['s']['pa'] / c['s']['n'], 'kalman': lambda c: c['s']['sr']}
    err = {k: {} for k in ('raw', 'kalman', 'ppa')}
    picks = {}
    tys = sorted({c['y'] for c in cases})
    for T in tys:
        tr = [c for c in cases if c['y'] != T]; te = [i for i, c in enumerate(cases) if c['y'] == T]

        def sse(f):
            a, b = wfit([f(c) for c in tr], [c['tgt'] for c in tr], [c['w'] for c in tr])
            return sum(c['w'] * (c['tgt'] - a - b * f(c)) ** 2 for c in tr), a, b
        best = min(((h, K) for h in HS for K in KS), key=lambda hk: sse(lambda c: ppa(c, *hk))[0])
        picks[T] = best
        fs = dict(cand, ppa=lambda c: ppa(c, *best))
        for k, f in fs.items():
            _, a, b = sse(f)
            for i in te:
                c = cases[i]; err[k][i] = c['w'] * (c['tgt'] - a - b * f(c)) ** 2
    W = sum(c['w'] for c in cases)
    r1 = {'n': len(cases), 'years': tys, 'picks': {str(k): v for k, v in picks.items()}}
    for k in err:
        r1[k] = round(sum(err[k].values()) / W, 4)
    for k in ('raw', 'kalman'):
        d = [err['ppa'][i] - err[k][i] for i in err['ppa']]
        yb = sum(1 for T in tys if sum(err['ppa'][i] for i, c in enumerate(cases) if c['y'] == T) <
                 sum(err[k][i] for i, c in enumerate(cases) if c['y'] == T))
        r1['ppa_vs_' + k] = {'t': round(tstat(d), 2), 'yearsBetter': yb, 'of': len(tys)}
    res['R1'] = r1
    print('R1', json.dumps(r1), flush=True)
    # C1 / C2
    for key, lag in (('C1', 1), ('C2', 2)):
        diffs = {'wins': [], 'wl': [], 'elo': []}
        per = {}
        for y in years[:-lag]:
            s = snaps[y + 1]       # Dec 31 of year y = Jan 1 of y+1
            for tour in ('atp', 'wta'):
                ids = [p for p, v in s.items() if v['tour'] == tour and v['m'] >= 20 and (p, y + lag) in rank0]
                if len(ids) < 50:
                    continue
                tgt = [-math.log(rank0[(p, y + lag)]) for p in ids]
                rw = spearman([s[p]['war'] for p in ids], tgt)
                rws = spearman([s[p]['w'] for p in ids], tgt)
                rwl = spearman([s[p]['w'] - s[p]['l'] for p in ids], tgt)
                per[f'{tour}{y}'] = {'war': round(rw, 3), 'wins': round(rws, 3), 'wl': round(rwl, 3), 'n': len(ids)}
                diffs['wins'].append(rw - rws); diffs['wl'].append(rw - rwl)
        res[key] = {'byYear': per, **{f'war_vs_{k}': {'meanDiff': round(sum(v) / len(v), 3), 't': round(tstat(v), 2),
                                                       'better': sum(1 for x in v if x > 0), 'of': len(v)}
                                       for k, v in diffs.items() if v}}
        print(key, json.dumps({k: v for k, v in res[key].items() if k != 'byYear'}), flush=True)
    # G1 / G2: extra blend terms
    def ll_of(recs_, wts, extra_idx):
        out = []
        for x, ex, z in recs_:
            f = M.feats(x) + ([z] if extra_idx is not None else [])
            s_ = sum(wts[j] * f[j] for j in range(len(f)))
            out.append(-math.log(max(sig(s_), 1e-9)))
        return out

    def fitlog(F):
        import numpy as np
        F = np.array(F); X = np.vstack([F, -F]); y = np.r_[np.ones(len(F)), np.zeros(len(F))]
        w = np.zeros(F.shape[1]); w[0] = 1
        for _ in range(30):
            p = 1 / (1 + np.exp(-(X @ w))); g = X.T @ (y - p); H = (X * (p * (1 - p))[:, None]).T @ X
            w = w + np.linalg.solve(H + 1e-3 * np.eye(len(w)), g - 1e-3 * w)
        return list(w)
    # WAR a match gap from recs: per game record compute 52-week WAR / matches for both (before the match)
    idx = {pid: [x[0] for x in xs] for pid, xs in recs.items()}
    import bisect

    def war_rate(pid, day):
        xs = recs[pid]; ds = idx[pid]
        j = bisect.bisect_left(ds, day); i = bisect.bisect_left(ds, day - 364)
        a = xs[i:j]
        if not a: return 0.0
        return sum(x[4] - p_repl(x[5], rr[x[2]], x[6]) for x in a) / (len(a) + 10)
    variants = {'G1_h180_k300': lambda g: g[1][180][0], 'G1_h180_k1000': lambda g: g[1][180][1],
                'G1_h365_k1000': lambda g: g[1][365][1], 'G1_h365_k3000': lambda g: g[1][365][2],
                'G2_war': lambda g: war_rate(g[2], g[4]) - war_rate(g[3], g[4])}
    tune = [g for g in game if g[0][0][0] // 10000 <= 2022]
    held = [g for g in game if g[0][0][0] // 10000 >= 2023]
    base_w = fitlog([M.feats(g[0]) for g in tune])
    res['G'] = {}
    for name, f in variants.items():
        wv = fitlog([M.feats(g[0]) + [f(g)] for g in tune])
        out = {}
        for lab, part in (('tune', tune), ('held', held)):
            b = ll_of([(g[0], g[1], 0) for g in part], base_w, None)
            c = ll_of([(g[0], g[1], f(g)) for g in part], wv, 0)
            by = defaultdict(float)
            for g, x, y in zip(part, b, c):
                by[g[0][0][6]] += y - x
            out[lab] = {'dll_x1e4': round(1e4 * (sum(c) - sum(b)) / len(b), 2), 't': round(tstat(list(by.values())), 2),
                        'n': len(b)}
        out['coef'] = round(wv[-1], 3)
        res['G'][name] = out
        print(name, json.dumps(out), flush=True)
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
