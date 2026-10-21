#!/usr/bin/env python3
"""Pace matchups and coaching as inputs to the NBA game model (scripts/nba_games.py). Research only.

    python3 scripts/nba_coach_research.py      # writes data/nba_coach_research.json (numpy; ~3 min)

Needs scripts/nba_coaches.json (scripts/nba_coaches.py), the injury history (scripts/nba_inj_hist.py) and, for the
timeout and challenge traits, ESPN play-by-play counts for a sample of games (scripts/nba_coach_pbp.json, from
scripts/nba_coaches.py --pbp).
Same walk-forward and rule as the fit (scripts/nba_games_fit.py): each season 2015-26 scored by weights fit on the
seasons before it, on the live model's settings and inputs. A candidate passes when it cuts 2015-21 loss at t <= -1.5
(game day x home team-season clustered, scripts/harness.py) and 2022-26 (held out) is not worse.
Already tried elsewhere and not redone here: pace and efficiency split, pace as a product, Elo K, points Elo, rest,
travel (scripts/nba_games_research.py, nba_games_fit.py).

    pace     pace gap as a margin input, efficiency at the slower team's pace, pace gap and slower-pace totals,
             win, cover and over sd scaled by expected possessions
    coach    first season with the team, tenure, career games, a mid-season change (and its first 20 games), the
             coach's running residual against the close and against the model (margin and total), a coach's own
             home edge, rotation tightness (top-7 minutes share; with back-to-backs and in the playoffs), early
             timeouts and challenge success (ESPN play-by-play, every sixth game 2016-26)
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_games as N
import nba_games_fit as Fit
import nba_coaches as C
import harness as H

OUT = os.path.join(N.ROOT, 'data', 'nba_coach_research.json')


class PaceModel(N.Model):
    """the live model, also reporting each team's pace ratings and the league's pace before the game"""
    def feats(self, g):
        x, tx = super().feats(g)
        P = self.lgp[0] / self.lgp[1]
        x.update({'_P': P, '_pH': self.rate(self.pace, g['h']), '_pA': self.rate(self.pace, g['a']),
                  '_tpH': self.rate(self.tpace, g['h']), '_tpA': self.rate(self.tpace, g['a'])})
        return x, tx


class CoachModel(PaceModel):
    """a coaching change discounts what the ratings carry: at a new season (fc: factor on the carried efficiency
    and pace weights, fe: on the Elo gap kept) and at a mid-season change (fm: factor on the weights so far)"""
    def __init__(self, names, P, fc=1.0, fe=1.0, fm=1.0, coaches=None, **kw):
        super().__init__(names, P, **kw)
        self.fc, self.fe, self.fm, self.cb, self.cur = fc, fe, fm, coaches or {}, {}
        self.cj = json.load(open(C.OUT))

    def new_season(self, S):
        super().new_season(S)
        last, now = self.cj.get(str(S - 1), {}), self.cj.get(str(S), {})
        for t in now:
            if last.get(t) and now[t][0]['id'] != last[t][-1]['id']:
                for d in (self.off, self.dfn, self.pace):
                    d[t][0] *= self.fc; d[t][1] *= self.fc
                self.elo[t] = 1505 + (self.elo[t] - 1505) * self.fe
        self.cur = {}

    def feats(self, g):
        if g['S'] != self.season:
            self.new_season(g['S'])
        for t, c in zip((g['h'], g['a']), self.cb.get(g['id']) or ()):
            if c and self.cur.get(t) and self.cur[t] != c['id'] and self.fm != 1.0:
                for d in (self.off, self.dfn, self.pace):
                    d[t][0] *= self.fm; d[t][1] *= self.fm
            if c:
                self.cur[t] = c['id']
        return super().feats(g)


def walk(games, names, P, params, inj, cls=PaceModel, **kw):
    m = cls(names, P, inj=inj, **params, **kw)
    out = []
    for g in games:
        x, tx = m.feats(g)
        out.append((g, x, tx))
        m.update(g)
    return [(g, x, tx) for g, x, tx in out if g.get('fin') and g['S'] >= N.FIRST + 1]


def shrunk(acc, k, n0, prior=0.0):
    s, n = acc.get(k, (0.0, 0))
    return (s + prior * n0) / (n + n0)


def r4(v):
    return None if v is None or v != v else round(float(v), 4)


def main():
    games, names = N.load_hist()
    inj = Fit.load_inj()
    F = json.load(open(N.FIT))
    P, feats, params = F['P'], list(F['feats']), dict(F['params'])
    D = walk(games, names, P, params, inj)
    n = len(D)
    G = [g for g, _, _ in D]
    X = {f: np.array([x[f] for _, x, _ in D], float) for f in D[0][1]}
    TX = {f: np.array([tx[f] for _, _, tx in D], float) for f in D[0][2]}
    y = np.array([g['hs'] - g['as'] for g in G], float)
    ty = np.array([g['hs'] + g['as'] for g in G], float)
    S = np.array([g['S'] for g in G])
    line = np.array([g['L'] if g.get('L') is not None else np.nan for g in G])
    tline = np.array([g['T'] if g.get('T') else np.nan for g in G])
    day = np.array([g['tip'][:10] for g in G])
    hts = np.array([f"{g['h']}|{g['S']}" for g in G])
    k1 = (S >= N.SCORE_FROM) & (S < N.HOLD_FROM)
    k2 = S >= N.HOLD_FROM
    mat = lambda XX, fs: np.column_stack([XX[f] for f in fs])
    base = Fit.wf(mat(X, feats), y, S)
    tbase = Fit.wf(mat(TX, N.TFEATS), ty, S)
    ok = ~np.isnan(base)
    res = {'base': {'feats': feats, 'mae2015_21': r4(np.mean(np.abs(base[k1] - y[k1]))), 'mae2022_26': r4(np.mean(np.abs(base[k2] - y[k2]))),
                    'totalMae2015_21': r4(np.mean(np.abs(tbase[k1] - ty[k1]))), 'totalMae2022_26': r4(np.mean(np.abs(tbase[k2] - ty[k2]))),
                    'shipped2022_26': F['test']['2022-26 (held out)']['maeModel']}}
    print('base', res['base'], flush=True)

    def judge(new, old, yy, loss='ae'):
        """2015-21 and 2022-26 paired loss change, clustered t (and the plain per-game t)"""
        if loss == 'ae':
            a, b = np.abs(new - yy), np.abs(old - yy)
        else:
            a, b = new, old
        out = {}
        for nm, k in (('2015_21', k1 & ok), ('2022_26', k2 & ok)):
            k = k & ~np.isnan(a) & ~np.isnan(b)
            p = H.paired(a[k], b[k], [day[k], hts[k]])
            out[nm] = {'d': r4(p['d']), 't': round(p['t'], 2), 'tPlain': round(Fit.paired_t(a[k], b[k]), 2) if np.any(a[k] != b[k]) else 0.0}
        out['pass'] = out['2015_21']['t'] <= -1.5 and out['2022_26']['d'] <= 0
        return out

    # ------------------------------------------------------------------ candidate inputs, all known before tip
    Pl, pH, pA = X['_P'], X['_pH'], X['_pA']
    net = X['eff'] / np.maximum(Pl + pH + pA, 1) * 100               # net rating gap per 100
    cand = {
        'pgap': pH - pA,                                              # faster team minus slower, possessions
        'pgapEff': X['eff'] * np.abs(pH - pA) / 3,                    # efficiency edge when the paces clash
        'effSlow': net * 2 * (Pl + np.minimum(pH, pA)) / 100,         # efficiency at the slower team's pace (swap)
        'effFast': net * 2 * (Pl + np.maximum(pH, pA)) / 100,
    }
    tcand = {
        'tgap': np.abs(X['_tpH'] - X['_tpA']),
        'ptsSlow': TX['pts'] * 2 * (Pl + np.minimum(X['_tpH'], X['_tpA'])) / np.maximum(Pl + X['_tpH'] + X['_tpA'], 1),
    }

    # coaches by game
    CB = C.by_game(G)
    newf = lambda c, s: 0.0 if not c else float(c['fr'] < s)
    for s_, nm in ((82, 'newc'), (41, 'newcHalf')):
        cand[nm] = np.array([newf(CB[g['id']][0], s_) - newf(CB[g['id']][1], s_) for g in G])
    cand['ten'] = np.array([math.log1p(CB[g['id']][0]['fr']) - math.log1p(CB[g['id']][1]['fr']) for g in G])
    cand['exp'] = np.array([math.log1p(CB[g['id']][0]['car']) - math.log1p(CB[g['id']][1]['car']) for g in G])
    midf = lambda c, lim: float(c['mid'] and c['since'] < lim)
    cand['midc'] = np.array([midf(CB[g['id']][0], 9999) - midf(CB[g['id']][1], 9999) for g in G])
    cand['midc20'] = np.array([midf(CB[g['id']][0], 20) - midf(CB[g['id']][1], 20) for g in G])
    # a new coach this season x the ratings carried from last season (do carried ratings mean less after a change?)
    early = np.clip(1 - X['gpn'] / 20, 0, 1)
    cand['newcEarly'] = cand['newc'] * early
    cand['effNewc'] = X['eff'] * early * np.array([newf(CB[g['id']][0], 82) + newf(CB[g['id']][1], 82) for g in G])

    # running residuals by coach, in tip order: against the close (margin, total) and against the model's margin
    # (walk-forward, so every earlier game's prediction is known before tonight); a coach's home edge
    order = np.argsort([g['tip'] for g in G], kind='stable')
    for n0 in (100, 300):
        ats, ou, mres, hres = {}, {}, {}, {}
        c_ats, c_ou, c_mres, c_home = (np.zeros(n) for _ in range(4))
        for i in order:
            g = G[i]
            ch, ca = CB[g['id']][0]['id'], CB[g['id']][1]['id']
            c_ats[i] = shrunk(ats, ch, n0) - shrunk(ats, ca, n0)
            c_ou[i] = shrunk(ou, ch, n0) + shrunk(ou, ca, n0)
            c_mres[i] = shrunk(mres, ch, n0) - shrunk(mres, ca, n0)
            hh = lambda c: (shrunk(hres, (c, 1), n0) - shrunk(hres, (c, 0), n0)) / 2
            c_home[i] = X['home'][i] * (hh(ch) + hh(ca))
            for c, s, hm in ((ch, 1, 1), (ca, -1, 0)):
                if not np.isnan(line[i]):
                    a = ats.setdefault(c, [0.0, 0]); a[0] += s * (y[i] - line[i]); a[1] += 1
                if not np.isnan(tline[i]):
                    a = ou.setdefault(c, [0.0, 0]); a[0] += ty[i] - tline[i]; a[1] += 1
                if not np.isnan(base[i]):
                    r = s * (y[i] - base[i])
                    a = mres.setdefault(c, [0.0, 0]); a[0] += r; a[1] += 1
                    if not g['n']:
                        a = hres.setdefault((c, hm), [0.0, 0]); a[0] += r; a[1] += 1
        cand[f'cats{n0}'] = c_ats
        cand[f'cres{n0}'] = c_mres
        cand[f'chome{n0}'] = c_home
        tcand[f'cou{n0}'] = c_ou

    # rotation tightness: share of minutes to a team's top 7 in each game, exponentially weighted (half-life 20
    # games, half carried into a new season)
    tight, tval = defaultdict(lambda: [0.0, 0.0]), np.zeros((n, 2))
    a20 = 0.5 ** (1 / 20)
    cur_s = None
    for i in order:
        g = G[i]
        if g['S'] != cur_s:
            for v in tight.values():
                v[0] *= 0.5; v[1] *= 0.5
            cur_s = g['S']
        for j, t in enumerate((g['h'], g['a'])):
            v = tight[t]
            tval[i, j] = v[0] / v[1] if v[1] > 0.5 else np.nan
        for t in (g['h'], g['a']):
            rows = (g.get('pl') or {}).get(t)
            if rows:
                m = sorted((mn for _, mn in rows), reverse=True)
                v = tight[t]; v[0] = v[0] * a20 + sum(m[:7]) / max(sum(m), 1); v[1] = v[1] * a20 + 1
    lg = np.nanmean(tval)
    tval = np.where(np.isnan(tval), lg, tval) - lg
    b2bH = (X['b2b'] > 0).astype(float); b2bA = (X['b2b'] < 0).astype(float)    # b2b = home b2b minus away b2b
    po = np.array([1.0 if g['t'] == 3 else 0.0 for g in G])
    cand['tight'] = (tval[:, 0] - tval[:, 1]) * 10
    cand['tightB2b'] = (tval[:, 0] * b2bH - tval[:, 1] * b2bA) * 10
    cand['tightPo'] = cand['tight'] * po
    tcand['tightSum'] = (tval[:, 0] + tval[:, 1]) * 10

    # timeouts before the 4th and challenges overturned, per game, by coach, from the sampled play-by-play
    samp = json.load(open(C.PBP)) if os.path.exists(C.PBP) else {}
    to_acc, ch_acc = {}, {}
    c_to, c_ch = np.zeros(n), np.zeros(n)
    have = [r for r in samp.values() if r.get('_n', 0) > 200]
    to_lg = np.mean([v['to13'] for r in have for k, v in r.items() if k != '_n']) if have else 0.0
    ch_lg = np.mean([v['chOv'] for r in have for k, v in r.items() if k != '_n']) if have else 0.0
    for i in order:
        g = G[i]
        ch, ca = CB[g['id']][0]['id'], CB[g['id']][1]['id']
        c_to[i] = shrunk(to_acc, ch, 20, to_lg) - shrunk(to_acc, ca, 20, to_lg)
        c_ch[i] = shrunk(ch_acc, ch, 30, ch_lg) - shrunk(ch_acc, ca, 30, ch_lg)
        r = samp.get(g['id'])
        if r and r.get('_n', 0) > 200:
            for c, t in ((ch, g['h']), (ca, g['a'])):
                v = r.get(t)
                if not v:
                    continue
                a = to_acc.setdefault(c, [0.0, 0]); a[0] += v['to13']; a[1] += 1
                if g['S'] >= 2020:                                      # coach's challenge from 2019-20
                    a = ch_acc.setdefault(c, [0.0, 0]); a[0] += v['chOv']; a[1] += 1
    cand['timeouts'] = c_to
    cand['challenge'] = c_ch
    res['pbpSample'] = {'games': len(have), 'timeoutsBefore4thLg': r4(to_lg), 'overturnsPerGameLg': r4(ch_lg)}

    # ------------------------------------------------------------------ margin (abs error; win log loss at the fit's sd)
    win = (y > 0).astype(float)
    ll = lambda p, w: -(w * np.log(np.clip(p, 1e-6, 1 - 1e-6)) + (1 - w) * np.log(1 - np.clip(p, 1e-6, 1 - 1e-6)))
    Phi = lambda z: 0.5 * (1 + np.vectorize(math.erf)(z / math.sqrt(2)))
    wll = lambda pr: np.where(np.isnan(pr), np.nan, ll(Phi(np.nan_to_num(pr) / F['sd']), win))
    base_ll = wll(base)
    Xa = {**X, **cand}
    swaps = {'effSlow': 'eff', 'effFast': 'eff'}
    mar = {}
    for c in cand:
        fs = [c if f == swaps.get(c) else f for f in feats] if c in swaps else feats + [c]
        pr = Fit.wf(mat(Xa, fs), y, S)
        mar[c] = judge(pr, base, y)
        mar[c]['logloss'] = judge(wll(pr), base_ll, None, loss='ll')
        mar[c]['coef'] = r4(np.linalg.lstsq(mat(Xa, fs)[k1 & ok], y[k1 & ok], rcond=None)[0][fs.index(c)])
        print('margin', c, mar[c], flush=True)
    res['margin'] = mar

    # ------------------------------------------------------------------ totals
    TXa = {**TX, **tcand}
    tot = {}
    for c in tcand:
        fs = ['ptsSlow' if f == 'pts' else f for f in N.TFEATS] if c == 'ptsSlow' else N.TFEATS + [c]
        pr = Fit.wf(mat(TXa, fs), ty, S)
        tot[c] = judge(pr, tbase, ty)
        print('total', c, tot[c], flush=True)
    res['totals'] = tot

    # ------------------------------------------------------------------ variance: sd scaled by expected possessions
    pace_r = (Pl + pH + pA) / Pl                                        # expected possessions over league
    tpace_r = (Pl + X['_tpH'] + X['_tpA']) / Pl
    var = {}

    def sd_fit(score, r, s0s):
        """best (s0, a) on 2015-21 for sd = s0 x r^a, scored by score(sd vector) per game"""
        best = None
        for a in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, -1.0):
            for s0 in s0s:
                l = np.nanmean(score(s0 * r ** a)[k1 & ok])
                if best is None or l < best[0]:
                    best = (l, s0, a)
        return best[1], best[2]
    s0s = np.arange(F['sd'] - 2.0, F['sd'] + 8.01, 0.25)
    wscore = lambda sd: ll(Phi(np.nan_to_num(base) / sd), win)
    s0, a = sd_fit(wscore, pace_r, s0s)
    flat = min(s0s, key=lambda s: np.nanmean(wscore(np.full(n, s))[k1 & ok]))
    var['win'] = {'s0': r4(s0), 'a': a, 'flatSd': r4(flat), **judge(wscore(s0 * pace_r ** a), wscore(np.full(n, flat)), None, loss='ll')}
    # covers: P(home covers) against the close
    kl = ~np.isnan(line) & (y != line)
    cov = (y > line).astype(float)
    cscore = lambda sd: np.where(kl, ll(Phi((np.nan_to_num(base) - np.nan_to_num(line)) / sd), cov), np.nan)
    s0, a = sd_fit(cscore, pace_r, s0s)
    flat = min(s0s, key=lambda s: np.nanmean(cscore(np.full(n, s))[k1 & ok]))
    var['cover'] = {'s0': r4(s0), 'a': a, 'flatSd': r4(flat), **judge(cscore(s0 * pace_r ** a), cscore(np.full(n, flat)), None, loss='ll')}
    # totals: over against the close, and the CRPS of the total itself
    kt = ~np.isnan(tline) & (ty != tline) & ~np.isnan(tbase)
    over = (ty > tline).astype(float)
    ts0s = np.arange(F['tsd'] - 3.0, F['tsd'] + 12.01, 0.5)
    oscore = lambda sd: np.where(kt, ll(Phi((np.nan_to_num(tbase) - np.nan_to_num(tline)) / sd), over), np.nan)
    def sd_fit_t(score, r):
        best = None
        for a in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, -1.0):
            for s0 in ts0s:
                l = np.nanmean(score(s0 * r ** a)[k1 & kt])
                if best is None or l < best[0]:
                    best = (l, s0, a)
        return best[1], best[2]
    s0, a = sd_fit_t(oscore, tpace_r)
    flat = min(ts0s, key=lambda s: np.nanmean(oscore(np.full(n, s))[k1 & kt]))
    var['over'] = {'s0': r4(s0), 'a': a, 'flatSd': r4(flat), **judge(oscore(s0 * tpace_r ** a), oscore(np.full(n, flat)), None, loss='ll')}
    crps = lambda sd: np.where(np.isnan(tbase), np.nan, H.crps_normal(np.nan_to_num(tbase), sd, ty))
    s0, a = sd_fit_t(crps, tpace_r)
    flat = min(ts0s, key=lambda s: np.nanmean(crps(np.full(n, s))[k1 & kt]))
    var['totalCrps'] = {'s0': r4(s0), 'a': a, 'flatSd': r4(flat), **judge(crps(s0 * tpace_r ** a), crps(np.full(n, flat)), None, loss='ll')}
    # residual sd by pace quintile (2015-26), margin and total
    q = np.quantile(pace_r[ok & (S >= N.SCORE_FROM)], [0.2, 0.4, 0.6, 0.8])
    bins = np.digitize(pace_r, q)
    var['byPaceQuintile'] = [{'q': int(b + 1), 'pace': r4(np.mean(pace_r[(bins == b) & ok] * 1)),
                              'marginResSd': r4(np.std((base - y)[(bins == b) & ok & (S >= N.SCORE_FROM)])),
                              'totalResSd': r4(np.std((tbase - ty)[(bins == b) & ok & (S >= N.SCORE_FROM)]))} for b in range(5)]
    print('variance', json.dumps(var), flush=True)
    res['variance'] = var

    # ------------------------------------------------------------------ a coaching change discounts carried ratings
    CBall = C.by_game(games)
    carry = {}
    for nm, kw in (('new coach: carry x.5', {'fc': 0.5}), ('new coach: carry x0', {'fc': 0.0}),
                   ('new coach: Elo kept x.67', {'fe': 0.67}), ('new coach: carry x.5, Elo x.67', {'fc': 0.5, 'fe': 0.67}),
                   ('mid-season change: weights x.5', {'fm': 0.5}), ('mid-season change: weights x.25', {'fm': 0.25})):
        Dv = walk(games, names, P, params, inj, cls=CoachModel, coaches=CBall, **kw)
        Xv = {f: np.array([x[f] for _, x, _ in Dv], float) for f in feats}
        TXv = {f: np.array([tx[f] for _, _, tx in Dv], float) for f in N.TFEATS}
        pr = Fit.wf(mat(Xv, feats), y, S)
        tpr = Fit.wf(mat(TXv, N.TFEATS), ty, S)
        carry[nm] = {'margin': judge(pr, base, y), 'logloss': judge(wll(pr), base_ll, None, loss='ll'), 'total': judge(tpr, tbase, ty)}
        print('carry', nm, carry[nm], flush=True)
    res['coachChangeCarry'] = carry

    res['passed'] = {'margin': [c for c, v in mar.items() if v['pass']], 'totals': [c for c, v in tot.items() if v['pass']],
                     'variance': [c for c, v in var.items() if isinstance(v, dict) and v.get('pass')],
                     'carry': [c for c, v in carry.items() if v['margin']['pass']]}
    print('passed', res['passed'], flush=True)
    json.dump(res, open(OUT, 'w'), indent=1)
    return res


if __name__ == '__main__':
    main()
