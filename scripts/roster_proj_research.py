#!/usr/bin/env python3
"""Research (Oct 28 2026): does a team strength built from the player projections (scripts/player_pctl.py: rate x
exposure, Marcel 1 / .7 / .5 shrunk with the fitted K, updated with the season to date) add to each game model, and so
to the ARK Ranking (each sport's ranking is its game model's rating)?

    python3 scripts/roster_proj_research.py nhl     # -> data/roster_proj_research.json (that sport's block)

NHL candidates, each beside the shipped inputs (elo, xg, b2b, home, rv) and in place of rv, walk-forward win log loss,
t clustered by day (the game model's own evidence(), the same gate: tune t >= 1.5 and held t > -1):
    pv      last dressed skaters at the projection's rate (WAR a minute, Marcel of the three seasons before, shrunk with
            K toward his group; newcomers at the group's newcomer rate) x his usual ice time: rv with the projection's
            rate in place of last season's projected HPM
    pvr     the season's roster instead of the last lineup: every skater who has dressed for the team this season at the
            projection's rate x his share of the team's games (to date, blended with last season's, A = 10) x usual
            ice time, so a player out for weeks fades out and comes back when he dresses again
NFL: the injury term's player value from the projection in place of the model's (see nfl()).
NBA needs no run: its lineup term already prices each player at the projection's prior (nba_xpm.prior_xpm) x minutes x
his chance to play, and the in-season update failed in the game model (scripts/nba_inseason.py, Oct 23).

Results (Oct 28 2026), nothing shipped:
    NHL pv   in place of rv: lined 2021-23 t 1.32 / 2024-26 -0.19 (rv 1.62 / 1.14); beside rv 0.65 / -1.04
    NHL pvr  in place of rv: -0.55 / -1.67; beside rv -1.41 / -1.37
    NFL      in place of inj: MAE 2017-20 +.018 (t +1.66, worse), 2021-25 +.003 (t +0.25); beside inj +.001 / +.010
"""
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'roster_proj_research.json')


def save(sport, res):
    try:
        d = json.load(open(OUT))
    except (OSError, ValueError):
        d = {}
    d[sport] = res
    json.dump(d, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


# ---------------------------------------------------------------- NHL
def nhl():
    import numpy as np
    import nhl_games as N
    import player_pctl as PP
    fit = json.load(open(PP.FIT.format('nhl')))['rates']['war']
    R = PP.Rate('value', fit['K'], fit['mu'], fit['var'])
    SV = {}

    def sv(S):
        if S not in SV:
            SV[S] = PP.season_values('nhl', S)
        return SV[S]

    RATES = {}

    def rates(S):
        """season S: {pid: (rate a minute, usual minutes a game)}, newcomer rate and minutes by group"""
        if S not in RATES:
            ids = set()
            for s in (S - 1, S - 2, S - 3):
                ids |= set(sv(s))
            w = N._war(S)
            last = w[0] if w else {}
            avg = w[2] if w else {'F': 15.0 * 60, 'D': 20.0 * 60}
            out = {}
            for pid in ids:
                hist = []
                grp = None
                for s in (S - 1, S - 2, S - 3):
                    h = sv(s).get(pid)
                    hist.append((h[0], h[1]) if h and h[1] > 0 else None)
                    grp = grp or (h[2] if h else None)
                if grp not in ('F', 'D'):
                    continue
                m0, vet = R.prior(hist, grp)
                p = last.get(pid)
                epg = min(p['toi'] * 60 / p['gp'], 1800) / 60 if p and p['gp'] else avg[grp] / 60
                out[pid] = (m0, epg)
            RATES[S] = (out, {g: R.mu.get(g + ':n', 0.0) for g in ('F', 'D')}, {g: avg[g] / 60 for g in ('F', 'D')})
        return RATES[S]

    class M(N.Model):
        def __init__(self, P):
            super().__init__(P)
            self.pv, self.seen, self.tgp, self.share0 = {}, defaultdict(lambda: defaultdict(int)), defaultdict(int), {}

        def advance(self, day, S):
            if self.S is not None and S != self.S:
                self.pv.clear(); self.seen.clear(); self.tgp.clear()
            super().advance(day, S)

        def _pvr(self, S, t):
            rt, newr, newe = rates(S)
            sv1 = sv(S - 1)
            n = self.tgp[t]
            v = 0.0
            for x, k in self.seen[t].items():
                pid, g = x[:-1], x[-1]
                r, e = rt.get(pid, (newr[g], newe[g]))
                h = sv1.get(pid)
                s0 = min(1.0, PP_GP.get((S - 1, pid), 0) / 82) if h else 0.7
                gs = (k + 10 * s0) / (n + 10)
                v += r * e * gs
            return v

        def feats(self, g, gh=None, ga=None, home=1.0):
            f = super().feats(g, gh, ga, home)
            h, a = g['h'], g['a']
            f['pv'] = self.pv[h] - self.pv[a] if h in self.pv and a in self.pv else 0.0
            f['pvr'] = self._pvr(g['S'], h) - self._pvr(g['S'], a) if self.tgp[h] and self.tgp[a] else 0.0
            return f

        def update(self, g):
            super().update(g)
            if g.get('hs') is None:
                return
            S = g['S']
            rt, newr, newe = rates(S)
            for t in (g['h'], g['a']):
                ids = N._lineups(S).get(str(g['id']), {}).get(t)
                if not ids:
                    continue
                self.pv[t] = sum(rt.get(x[:-1], (newr[x[-1]], newe[x[-1]]))[0] * rt.get(x[:-1], (newr[x[-1]], newe[x[-1]]))[1]
                                 for x in ids)
                self.tgp[t] += 1
                for x in ids:
                    self.seen[t][x] += 1

    PP_GP = {}
    for S in range(2008, 2027):
        fn = os.path.join(ROOT, 'static', 'data', 'nhl-war', f'{S}.json')
        if os.path.exists(fn):
            for p in json.load(open(fn))['players']:
                PP_GP[(S, p['id'])] = p['gp']

    N.Model = M
    F = json.load(open(N.FIT))
    hist = N.load_hist()
    _, rows, _ = N.walk(hist, F['params'])
    base = [k for k in F['feats']]
    print('base', base, flush=True)
    res = {'base': base}
    # beside the shipped inputs, on the lined seasons (rv's own split) and on every game 2017-23 / 2024-26
    res['add'] = N.evidence(rows, base, ['pv', 'pvr'])
    res['addAll'] = N.evidence(rows, base, ['pv', 'pvr'], lined_only=False, first=N.SCORE_FROM + 1,
                               tune_s=(N.SCORE_FROM + 1, N.TUNE[1]))
    nr = [k for k in base if k != 'rv']
    res['replace'] = {k: N.evidence(rows, nr, [k]) for k in ('rv', 'pv', 'pvr')}
    S = np.array([g['S'] for g, f in rows])
    for k in ('rv', 'pv', 'pvr'):
        v = np.array([f[k] for g, f in rows])
        print(k, 'sd', round(float(v[S >= 2017].std()), 4))
    res['corr'] = {f'{a}-{b}': round(float(np.corrcoef([f[a] for g, f in rows], [f[b] for g, f in rows])[0, 1]), 3)
                   for a, b in (('rv', 'pv'), ('rv', 'pvr'), ('pv', 'pvr'))}
    print(res['corr'])
    save('nhl', res)


# ---------------------------------------------------------------- NFL
def nfl_ledger(y, thru=None, maps=None):
    """nfl_war.war_ledger with snaps and group: {gsis: [WAR, games, snaps (his unit's), group]}"""
    import nfl_war as W
    b = json.load(open(W.FIT))['coef']
    by_pfr, by_name = maps or W.gsis_map(y)
    sd = W.season_data(y, False, thru)
    out = {}
    for (pfr, t), s in sd['snaps'].items():
        gsis = by_pfr.get(pfr) or by_name.get((s['name'].lower(), t))
        g, _ = W.group_of(s['pos'], '')
        if not gsis or not g:
            continue
        x = W.features(sd, pfr, gsis, t, g)
        if x is None:
            continue
        P = sd['plays'][t]
        share = ((s['off'] / P[0]) if g in W.OFFENSE else (s['def'] / P[1])) * sd['team'][t]['g'] / 17 if P[0] and P[1] else 0.0
        a = out.setdefault(gsis, [0.0, 0, 0.0, g])
        a[0] += (W.predict(b, g, x) - W.NFL_REPL[g] * share) * W.NWAR_PER_AV
        a[1] += s['g']
        a[2] += s['off'] if g in W.OFFENSE else s['def']
    return out


def nfl():
    """NFL: the injury term (each non-QB on the game status report, 1 - P(plays) x his value a game x 36) with his value
    from the projection (WAR a snap: Marcel of the three seasons before shrunk with K toward his group, updated with the
    season to date as player_pctl does, x his snaps a game) in place of the model's (last season at half weight plus
    this season, shrunk three games toward replacement). Same walk-forward OLS as nfl_games.fit, MAE on the margin,
    2017-20 tuning / 2021-25 held out, t clustered by season-week."""
    import numpy as np
    import nfl_games as G
    import nfl_war as W
    import player_pctl as PP
    import harness as H
    cp = os.path.join(G.CACHE, 'roster_proj_inj.json')
    fr = json.load(open(PP.FIT.format('nfl')))['rates']['war']
    R = PP.Rate('value', fr['K'], fr['mu'], fr['var'])
    last = 2025
    games, box, qbs = G.load(last)
    G.index_qbs(qbs, games); G.load_qb_teams(last)
    try:
        cache = json.load(open(cp))
    except (OSError, ValueError):
        cache = {}
    full = {}

    def season_full(y):
        if y not in full:
            full[y] = nfl_ledger(y, maps=W.gsis_map(y)) if y >= 2012 else {}
        return full[y]

    for y in range(G.INJ_FIRST, last + 1):
        if str(y) in cache:
            continue
        maps = W.gsis_map(y)
        prev = [season_full(y - k) for k in (1, 2, 3)]
        sg = [g for g in games if int(g['season']) == y and g['home_score'] not in ('', 'NA')]
        top = max([int(g['week']) for g in sg] + [1])
        led = {w: nfl_ledger(y, thru=w, maps=maps) for w in range(1, min(top + 1, 19) + 1)}
        rep = defaultdict(list)
        for r in G.rows(G.get(f'injuries_{y}.csv', f'{G.REL}/injuries/injuries_{y}.csv')):
            if r['report_status'] and r['position'] != 'QB':
                rep[(G.team(r['team']), int(r['week']))].append((r['gsis_id'], r['report_status']))
        last_wk, out = {}, {}

        def proj(gsis, L):
            td = L.get(gsis)
            grp = (td or [None] * 4)[3] or next((p[gsis][3] for p in prev if gsis in p), None)
            if grp is None:
                return 0.0
            hist = [(p[gsis][0], p[gsis][2]) if gsis in p and p[gsis][2] > 0 else None for p in prev]
            m0, vet = R.prior(hist, grp)
            m1 = R.post(m0, grp, vet, td[0] if td else 0.0, td[2] if td else 0.0)[0]
            h1 = prev[0].get(gsis)
            epg0 = h1[2] / h1[1] if h1 and h1[1] else (td[2] / td[1] if td and td[1] else 0.0)
            g_, sn = (td[1], td[2]) if td else (0, 0.0)
            epg = (sn + 3 * epg0) / (g_ + 3)
            return m1 * epg

        for g in sg:
            w = int(g['week'])
            row = []
            for side in ('home', 'away'):
                t = G.team(g[f'{side}_team'])
                pw = last_wk.get(t)
                c0 = c1 = 0.0
                L = led[min(w, 19, top + 1)]
                for gsis, stt in rep.get((t, w), []):
                    if pw is None or pw >= 18 or w > 18:
                        played = True
                    else:
                        played = led[pw + 1].get(gsis, (0, 0))[1] > led[pw].get(gsis, (0, 0))[1]
                    miss = 1 - G.play_prob(stt, played)
                    l0 = L.get(gsis, (0.0, 0))
                    p1 = prev[0].get(gsis, (0.0, 0))
                    c0 += miss * max(G.player_value((p1[0], p1[1]), (l0[0], l0[1])), 0.0) * G.PTS_PER_WIN
                    c1 += miss * max(proj(gsis, L), 0.0) * G.PTS_PER_WIN
                row += [round(c0, 3), round(c1, 3)]
                last_wk[t] = w
            out[g['game_id']] = row
        cache[str(y)] = out
        json.dump(cache, open(cp, 'w'))
        print('injuries', y, len(out), flush=True)
    inj = {gid: v for y in cache.values() for gid, v in y.items()}

    F = json.load(open(G.FIT))
    _, data = G.walk(games, box, qbs, F['params'])
    D = [(g, x) for g, x, _ in data if g['home_score'] not in ('', 'NA') and int(g['season']) >= 2012]
    for g, x in D:
        r = inj.get(g['game_id'], [0.0] * 4)
        x['inj'] = r[2] - r[0]                     # away minus home, the model's sign
        x['pinj'] = r[3] - r[1]
    y = np.array([G.num(g['result']) for g, _ in D]); S = np.array([int(g['season']) for g, _ in D])
    wk = np.array([f"{g['season']}-{g['week']}" for g, _ in D])
    line = np.array([G.num(g['spread_line'], np.nan) for g, _ in D])

    def wf(feats):
        X = np.array([[x[f] for f in feats] for _, x in D])
        p = np.full(len(y), np.nan)
        for s in range(2017, last + 1):
            tr, te = S < s, S == s
            p[te] = X[te] @ np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]
        return p
    feats = list(F['coef'])
    base = wf(feats)
    res = {'feats': feats}
    sets = {'inj (shipped, recomputed)': feats, 'pinj in place of inj': [f if f != 'inj' else 'pinj' for f in feats],
            'pinj beside inj': feats + ['pinj'], 'no injury term': [f for f in feats if f != 'inj']}
    for lab, fs in sets.items():
        p = wf(fs)
        out = {}
        for nm, k in (('2017-20 (tuning)', (S >= 2017) & (S <= 2020)), ('2021-25 (held out)', S >= 2021)):
            ok = k & ~np.isnan(p)
            pr = H.paired(H.ae(p[ok], y[ok]), H.ae(base[ok], y[ok]), wk[ok])
            out[nm] = {'mae': round(float(H.ae(p[ok], y[ok]).mean()), 4), 'dMae': round(pr['d'], 4), 't': round(pr['t'], 2),
                       'maeLine': round(float(np.nanmean(np.abs(line[ok] - y[ok]))), 3)}
        res[lab] = out
        print(lab, out, flush=True)
    a = np.array([x['inj'] for _, x in D]); b = np.array([x['pinj'] for _, x in D]); k = S >= 2016
    res['corr'] = round(float(np.corrcoef(a[k], b[k])[0, 1]), 3)
    res['sd'] = {'inj': round(float(a[k].std()), 3), 'pinj': round(float(b[k].std()), 3)}
    print(res['corr'], res['sd'])
    save('nfl', res)


if __name__ == '__main__':
    {'nhl': nhl, 'nfl': nfl}[sys.argv[1]]()
