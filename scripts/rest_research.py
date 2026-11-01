#!/usr/bin/env python3
"""Days of rest in every game model (thread "Measure rest-day effects in each sport", Noah Nov 1 2026: "Can we check how
days of rest impact each sport?"). Builds on [[schedule-effects]] (Oct 21: NBA night-two lineup factors shipped; travel,
body clock, time slots failed) and spots_research.py (letdown / look-ahead). Research script; results in
data/rest_research.json.

Pre-registered before any outcome was looked at. d = days between a team's previous game and this one (same season;
season openers get no flags). Flags, team view, x = flag(home) - flag(away):
  NBA, NHL  B2B   second night of a back-to-back (d = 1)                     expected -
            R3IN4 third game in four nights                                   expected -
            REST2 two or more days off (d >= 3), baseline one day off          expected +
            B2BKM B2B x km travelled since the last game / 1000               expected -
  NFL       SHORT d <= 5 (Thursday after Sunday)                              expected -
            MNF6  d = 6 (Sunday after Monday night)                           expected -
            MINI  d 9-12 (off a Thursday game)                                expected +
            BYE   d >= 13                                                     expected +
            SHKM  SHORT x km travelled to this game / 1000                    expected -
  CFB       SHORT d <= 5,  BYE d >= 13 (baseline 6-12)                        expected - / +
  CBB       D1 d = 1 (consecutive days), D2 d = 2, D5 d 5-7, LONG d >= 8 (baseline 3-4)   - / - / + / +
            (rest from the full D-I schedule, scripts/data/cbb_games_hist.json.gz, not just lined games)
  soccer    CONG d <= 3, D45 d 4-5, LONG d >= 10 (baseline 6-9)              - / - / +
            (leagues in the file: big five + UEFA; domestic cups and internationals are missing, so d is long-biased)
Outcomes (regular season and playoffs, every game with a close):
  size       margin on the flags with team-season fixed effects + home (home minus away, points / goals): the raw effect
  priced     the close (margin scale) on the same design: how much the market moves for it
  vs close   result minus close on the flags (no FE needed: the close carries strength)
  vs model   result minus the walk-forward model (does the shipped model already hold it?)
NHL market scale: win prob (result - close prob); soccer: (home win - away win) minus the close's (cH - cA); margins
for size use goals. Errors clustered by game day. Tune / held as spots_research (NFL, NBA 2015-21 / 2022-26; CBB 2016-21
/ 2022-26; CFB 2017-22 / 2023-26; NHL 2017-21 / 2022-26; soccer 2013-20 / 2021-26).
Pass (for a pick or model term): tune t >= 1.5 in the expected direction AND held-out squared error of base + b x (b
from tune) below the base at paired t <= -1.5, one BH family over every flag x {close, model} at q <= .10.

Result (Nov 1 2026; size = raw effect with team-season FE, priced = the close's move for it, home-minus-away flag):
  NFL    bye +1.05 pts (close +1.15), Sunday after MNF -0.6 (close -0.3), off a Thursday +0.6 (close +0.1); Thursday
         games are short for both teams (10 games with a gap). Nothing beats the close or the model in both splits.
  CFB    bye +0.8 (close +0.6); short week n 43. Nothing.
  NBA    B2B -1.7 (close -1.8), 3-in-4 -0.5 (close -0.2). The model read rest off UTC dates (38% of its B2Bs were not;
         nba_games.gday). Vs the model B2B -0.8 / -1.4 (t -3.1 / -4.3) before the fix. SHIPPED the date fix: walk
         2015-21 MAE 9.897 -> 9.891 (t -1.54), 2022-26 10.714 -> 10.712, log loss .6026 -> .6022; rest coef .71 -> .81.
         Nothing vs the close (B2B tune +0.3, held -0.5).
  CBB    played yesterday -1.4 (close -1.3); vs the wf model -1.2 / -2.2, but in the model (cbb_games candidate b2bd)
         2016-20 t -0.03, 2021-26 t -2.2: held-out only, not shipped. Vs close tune t -1.0, held t -2.3: re-score.
  NHL    B2B -0.30 goals (close prices -3.3 pts of win chance); held 2022-26 B2B teams under the close 4.3 pts
         (t -3.3, held SE t -2.6), tune (closes 2020-21 only) -1.8 (t -0.6): fails tune, re-score after 2026-27.
  soccer 4-5 days off -0.085 goals (close ~0): passes vs close and model; SHIPPED soccer_games r45 -.02 (both
         lambdas; in-model log loss tune t -2.2, held t -1.7, big five held t -2.1). <= 3 days: raw 0, close -.02:
         clubs on <= 3 days beat the close (tune t +2.2, held +3.3), the model has no penalty there (r3 fails).
         wf-file rest misses domestic cups; the model's own (r45) counts every competition.
  tennis played the day before / 30+ day layoff: close prices both (held t +0.5 / +0.2). The model's CR term
         (log days since last match, -.078 logit) is rust, not fatigue.
  CS2    no closing-line history; inactivity decay failed before (cs2_model docstring).

    python3 scripts/rest_research.py            # -> data/rest_research.json
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
from nba_games import ARENA as NBA_AR, hav  # noqa: E402

WF = os.path.join(HERE, 'data', 'games_wf', '{}.json.gz')
OUT = os.path.join(ROOT, 'data', 'rest_research.json')

NHL_LL = {'ANA': (33.808, -117.877), 'ARI': (33.532, -112.261), 'UTA': (40.768, -111.901), 'BOS': (42.366, -71.062),
          'BUF': (42.875, -78.876), 'CAR': (35.803, -78.722), 'CBJ': (39.969, -83.006), 'CGY': (51.037, -114.052),
          'CHI': (41.881, -87.674), 'COL': (39.749, -105.008), 'DAL': (32.790, -96.810), 'DET': (42.341, -83.055),
          'EDM': (53.547, -113.498), 'FLA': (26.158, -80.326), 'LAK': (34.043, -118.267), 'MIN': (44.945, -93.101),
          'MTL': (45.496, -73.569), 'NJD': (40.734, -74.171), 'NSH': (36.159, -86.779), 'NYI': (40.712, -73.726),
          'NYR': (40.751, -73.994), 'OTT': (45.297, -75.927), 'PHI': (39.901, -75.172), 'PIT': (40.439, -79.989),
          'SEA': (47.622, -122.354), 'SJS': (37.333, -121.901), 'STL': (38.627, -90.203), 'TBL': (27.943, -82.452),
          'TOR': (43.643, -79.379), 'VAN': (49.278, -123.109), 'VGK': (36.103, -115.178), 'WPG': (49.893, -97.144),
          'WSH': (38.898, -77.021)}
NFL_LL = {'ARI': (33.528, -112.263), 'ATL': (33.755, -84.401), 'BAL': (39.278, -76.623), 'BUF': (42.774, -78.787),
          'CAR': (35.226, -80.853), 'CHI': (41.862, -87.617), 'CIN': (39.095, -84.516), 'CLE': (41.506, -81.700),
          'DAL': (32.748, -97.093), 'DEN': (39.744, -105.020), 'DET': (42.340, -83.046), 'GB': (44.501, -88.062),
          'HOU': (29.685, -95.411), 'IND': (39.760, -86.164), 'JAX': (30.324, -81.637), 'KC': (39.049, -94.484),
          'LA': (33.953, -118.339), 'LAC': (33.953, -118.339), 'SD': (32.783, -117.120), 'STL': (38.633, -90.188),
          'LV': (36.091, -115.184), 'OAK': (37.751, -122.201), 'MIA': (25.958, -80.239), 'MIN': (44.974, -93.258),
          'NE': (42.091, -71.264), 'NO': (29.951, -90.081), 'NYG': (40.814, -74.074), 'NYJ': (40.814, -74.074),
          'PHI': (39.901, -75.168), 'PIT': (40.447, -80.016), 'SEA': (47.595, -122.332), 'SF': (37.403, -121.970),
          'TB': (27.976, -82.503), 'TEN': (36.166, -86.771), 'WAS': (38.908, -76.864)}

SPEC = {
    'nfl': dict(tune=range(2015, 2022), flags={'SHORT': -1, 'MNF6': -1, 'MINI': 1, 'BYE': 1, 'SHKM': -1}),
    'cfb': dict(tune=range(2017, 2023), flags={'SHORT': -1, 'BYE': 1}),
    'nba': dict(tune=range(2015, 2022), flags={'B2B': -1, 'R3IN4': -1, 'REST2': 1, 'B2BKM': -1}),
    'cbb': dict(tune=range(2016, 2022), flags={'D1': -1, 'D2': -1, 'D5': 1, 'LONG': 1}),
    'nhl': dict(tune=range(2017, 2022), flags={'B2B': -1, 'R3IN4': -1, 'REST2': 1, 'B2BKM': -1}),
    'soccer': dict(tune=range(2013, 2021), flags={'CONG': -1, 'D45': -1, 'LONG': 1}),
}


def when(s):
    s = str(s).replace('Z', '')
    return datetime.datetime.fromisoformat(s[:16] if 'T' in s else s[:10] + 'T12:00')


def days(a, b):
    """calendar days between two tips by local US date (UTC tips minus 7 h: noon-11 pm local all land on their own day)"""
    k = datetime.timedelta(hours=7)
    return ((b - k).date() - (a - k).date()).days


def _f(v):
    return math.nan if v is None else float(v)


# ---- games (every played game, so rest counts all of them; tests use those with a close): y margin, C close (market scale), Cm close margin (for "priced"), M model (market scale)
def games(sport):
    G = []
    for r in json.load(gzip.open(WF.format(sport))):
        if sport in ('nfl', 'nba', 'cbb', 'cfb'):
            if r.get('res') is None:
                continue
            nt = bool(r.get('neutral'))
            G.append(dict(id=str(r['id']), S=r['S'], t=when(r['date']), h=r['home'], a=r['away'], home=0.0 if nt else 1.0,
                          y=float(r['res']), C=_f(r.get('L')), Cm=_f(r.get('L')), M=float(r['m']), Y=float(r['res'])))
        elif sport == 'nhl':
            if r.get('hs') is None:
                continue
            c = (r.get('c') or {}).get('p')
            G.append(dict(id=str(r['id']), S=r['S'], t=when(r['day']), h=r['h'], a=r['a'], home=1.0,
                          y=float(r['hs'] - r['as']), Y=float(r['hs'] > r['as']), C=_f(c), Cm=_f(c), M=r['p']))
        else:
            if r.get('hs') is None:
                continue
            c, p = r.get('c') or [math.nan] * 3, r['p']
            G.append(dict(id=str(r['id']), S=r['S'], t=when(r['day']), h=r['h'], a=r['a'], home=1.0, lg=r['lg'],
                          y=float(r['hs'] - r['as']), Y=float((r['hs'] > r['as']) - (r['as'] > r['hs'])),
                          C=c[0] - c[2], Cm=c[0] - c[2], M=p[0] - p[2]))
    G.sort(key=lambda g: g['t'])
    return G


def cbb_rest():
    """days since each team's last D-I game, from the full schedule: {(game id, team name): d}"""
    out, last = {}, {}
    rows = sorted(json.load(gzip.open(os.path.join(HERE, 'data', 'cbb_games_hist.json.gz'))), key=lambda r: r['date'])
    for r in rows:
        t = when(r['date'])
        for tid, nm in ((r['home'], r['hn']), (r['away'], r['an'])):
            p = last.get(tid)
            out[(str(r['id']), nm)] = days(p[0], t) if p and p[1] == r['season'] else None
            last[tid] = (t, r['season'])
    return out


def loc(sport, team, venue_team):
    tbl = {'nba': NBA_AR, 'nhl': NHL_LL, 'nfl': NFL_LL}.get(sport)
    return tbl.get(venue_team) if tbl else None


def flags(sport, G):
    sch = collections.defaultdict(list)
    for g in G:
        sch[g['h']].append(g)
        sch[g['a']].append(g)
    CR = cbb_rest() if sport == 'cbb' else None
    F = {}
    for team, es in sch.items():
        for i, g in enumerate(es):
            f = dict.fromkeys(SPEC[sport]['flags'], 0.0)
            F[(g['id'], team)] = f
            if sport == 'cbb':
                d = CR.get((g['id'], team))
            else:
                p = es[i - 1] if i else None
                d = days(p['t'], g['t']) if p and p['S'] == g['S'] else None
            f['_d'] = d
            if d is None:
                continue
            if sport in ('nba', 'nhl'):
                p = es[i - 1]
                f['B2B'] = float(d == 1)
                f['REST2'] = float(d >= 3)
                f['R3IN4'] = float(i >= 2 and es[i - 2]['S'] == g['S'] and days(es[i - 2]['t'], g['t']) <= 3)
                a, b = loc(sport, team, p['h']), loc(sport, team, g['h'])
                f['B2BKM'] = f['B2B'] * (hav(a, b) / 1000 if a and b else 0.0)
            elif sport == 'nfl':
                f['SHORT'] = float(d <= 5)
                f['MNF6'] = float(d == 6)
                f['MINI'] = float(9 <= d <= 12)
                f['BYE'] = float(d >= 13)
                a, b = loc(sport, team, team), loc(sport, team, g['h'])
                f['SHKM'] = f['SHORT'] * (hav(a, b) / 1000 if a and b else 0.0)
            elif sport == 'cfb':
                f['SHORT'] = float(d <= 5)
                f['BYE'] = float(d >= 13)
            elif sport == 'cbb':
                f['D1'], f['D2'] = float(d == 1), float(d == 2)
                f['D5'], f['LONG'] = float(5 <= d <= 7), float(d >= 8)
            else:
                f['CONG'], f['D45'], f['LONG'] = float(d <= 3), float(4 <= d <= 5), float(d >= 10)
    return F


def ols_cl(X, y, c):
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    XtXi = np.linalg.pinv(X.T @ X)
    _, inv = np.unique(c, return_inverse=True)
    S = np.zeros((inv.max() + 1, X.shape[1]))
    np.add.at(S, inv, X * e[:, None])
    n, k = X.shape
    G = inv.max() + 1
    V = XtXi @ (S.T @ S) @ XtXi * G / (G - 1) * (n - 1) / (n - k)
    return b, np.sqrt(np.maximum(np.diag(V), 0))


def fe_resid(v, hi, ai, home, n_fe, it=400):
    """v minus its least-squares fit on home + team-season effects (+1 home team, -1 away team), by conjugate gradient"""
    def A(th):
        return home * th[0] + th[1:][hi] - th[1:][ai]

    def At(r):
        o = np.zeros(n_fe + 1)
        o[0] = home @ r
        np.add.at(o[1:], hi, r)
        np.add.at(o[1:], ai, -r)
        return o
    eps = 1e-6
    b = At(v)
    x = np.zeros(n_fe + 1)
    r = b.copy()
    p = r.copy()
    rs = r @ r
    for _ in range(it):
        Ap = At(A(p)) + eps * p
        al = rs / (p @ Ap)
        x += al * p
        r -= al * Ap
        rn = r @ r
        if rn < 1e-12 * (b @ b + 1e-12):
            break
        p = r + rn / rs * p
        rs = rn
    return v - A(x)


def sport_run(sport):
    sp = SPEC[sport]
    G = games(sport)
    F = flags(sport, G)
    G = [g for g in G if not math.isnan(g['C'])]
    keys = list(sp['flags'])
    X = np.array([[F[(g['id'], g['h'])][k] - F[(g['id'], g['a'])][k] for k in keys] for g in G])
    S = np.array([g['S'] for g in G])
    day = np.array([g['t'].date().isoformat() for g in G])
    tune = np.isin(S, list(sp['tune']))
    home = np.array([g['home'] for g in G])
    ts = {}
    hi = np.array([ts.setdefault((g['S'], g['h']), len(ts)) for g in G])
    ai = np.array([ts.setdefault((g['S'], g['a']), len(ts)) for g in G])
    y, Y, C, Cm, M = (np.array([g[k] for g in G], float) for k in ('y', 'Y', 'C', 'Cm', 'M'))
    # distribution of d (team-games)
    ds = [F[(g['id'], t)]['_d'] for g in G for t in (g['h'], g['a'])]
    dist = collections.Counter(min(d, 15) if d is not None else 'first' for d in ds)
    out = {'n': len(G), 'counts': {k: int((np.abs(X[:, j]) > 0).sum()) for j, k in enumerate(keys)},
           'restDays': {str(k): v for k, v in sorted(dist.items(), key=lambda kv: (isinstance(kv[0], str), kv[0]))}}
    # size and priced: team-season FE, joint on all flags, all seasons
    Xr = np.c_[[fe_resid(X[:, j], hi, ai, home, len(ts)) for j in range(len(keys))]].T
    for nm, v in (('size', y), ('priced', Cm)):
        b, s = ols_cl(Xr, fe_resid(v, hi, ai, home, len(ts)), day)
        out[nm] = {k: [round(float(b[j]), 3), round(float(b[j] / s[j]), 2)] for j, k in enumerate(keys)}
    # vs close and vs model, one flag at a time (pre-registered single-term tests) + joint
    out['tests'] = {}
    for base, nm in ((C, 'close'), (M, 'model')):
        r = Y - base
        for j, k in enumerate(keys):
            x = X[:, j]
            Xc = np.c_[np.ones(len(x)), x]
            d = {}
            for part, mk in (('tune', tune), ('held', ~tune)):
                b, s = ols_cl(Xc[mk], r[mk], day[mk])
                d[part] = [round(float(b[1]), 4), round(float(b[1] / s[1]), 2)]
            bt = ols_cl(Xc[tune], r[tune], day[tune])[0]
            new, old = base + bt[0] + bt[1] * x, base + r[tune].mean()
            pr = H.paired(H.se(new[~tune], Y[~tune]), H.se(old[~tune], Y[~tune]), cluster=day[~tune])
            d['seHeld'] = [round(float(pr['d']), 6), round(pr['t'], 2)]
            d['pass'] = bool(sp['flags'][k] * d['tune'][1] >= 1.5 and d['seHeld'][1] <= -1.5)
            out['tests'][f'{k}|{nm}'] = d
    return out


def tennis():
    """tennis (feed with closes, 2025 tune / 2026 held): T1 played the day before (d <= 1, expected -), LONG first match
    after 30+ days (expected -: the model's CR term says rust). Side by match id parity; win - close prob."""
    import zlib
    import tennis_data as T
    rows = []
    for r in T.mm_rows(refresh=False):
        try:
            pc, t = float(r['winner_close_prob']), when(r['start_time_utc'])
        except (ValueError, KeyError):
            continue
        rows.append(dict(id=r['match_id'], t=t, w=r['_tour'] + r['winner_id'], l=r['_tour'] + r['loser_id'], pc=pc if 0 < pc < 1 else math.nan))
    rows.sort(key=lambda g: g['t'])
    last, F = {}, {}
    for g in rows:
        for me in ('w', 'l'):
            p = last.get(g[me])
            d = (g['t'] - p).total_seconds() / 864e2 if p else None
            F[(g['id'], me)] = {'T1': float(d is not None and d <= 1.5), 'LONG': float(d is not None and d >= 30)}
            last[g[me]] = g['t']
    rows = [g for g in rows if not math.isnan(g['pc'])]
    side = [('w', 'l') if zlib.crc32(g['id'].encode()) % 2 == 0 else ('l', 'w') for g in rows]
    Y = np.array([float(a == 'w') for a, _ in side])
    C = np.array([g['pc'] if a == 'w' else 1 - g['pc'] for g, (a, _) in zip(rows, side)])
    tune = np.array([g['t'].year == 2025 for g in rows])
    day = np.array([g['t'].date().isoformat() for g in rows])
    out = {'n': len(rows), 'tests': {}}
    for k, sg in (('T1', -1), ('LONG', -1)):
        x = np.array([F[(g['id'], a)][k] - F[(g['id'], b)][k] for g, (a, b) in zip(rows, side)])
        Xc = np.c_[np.ones(len(x)), x]
        d = {'flagged': int((x != 0).sum())}
        for part, mk in (('tune', tune), ('held', ~tune)):
            b, s_ = ols_cl(Xc[mk], (Y - C)[mk], day[mk])
            d[part] = [round(float(b[1]), 4), round(float(b[1] / s_[1]), 2)]
        bt = ols_cl(Xc[tune], (Y - C)[tune], day[tune])[0]
        new, old = C + bt[0] + bt[1] * x, C + (Y - C)[tune].mean()
        pr = H.paired(H.se(new[~tune], Y[~tune]), H.se(old[~tune], Y[~tune]), cluster=day[~tune])
        d['seHeld'] = [round(float(pr['d']), 6), round(pr['t'], 2)]
        d['pass'] = bool(sg * d['tune'][1] >= 1.5 and d['seHeld'][1] <= -1.5)
        out['tests'][f'{k}|close'] = d
    return out


def family(res):
    N = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))
    tests = []
    for sport, o in res.items():
        for key, d in o['tests'].items():
            k = key.split('|')[0]
            sg = SPEC[sport]['flags'][k] if sport in SPEC else -1
            z = H.stouffer([sg * d['tune'][1], sg * d['held'][1]])
            d['z'] = round(z, 2)
            tests.append((d, 1 - N(z)))        # one-sided in the expected direction
    for (d, p), q in zip(tests, H.bh([p for _, p in tests])):
        d['p'], d['q'] = round(p, 5), round(float(q), 4)


if __name__ == '__main__':
    only = sys.argv[1:] or list(SPEC)
    res = {s: sport_run(s) for s in only if s in SPEC}
    if 'tennis' in only or not sys.argv[1:]:
        res['tennis'] = tennis()
    family(res)
    clean = lambda o: ({k: clean(v) for k, v in o.items()} if isinstance(o, dict) else [clean(v) for v in o] if isinstance(o, list)
                       else None if isinstance(o, float) and math.isnan(o) else o)
    json.dump(clean({'asof': datetime.date.today().isoformat(), 'sports': res}), open(OUT, 'w'), indent=1, allow_nan=False)
    for s, o in res.items():
        if s == 'tennis':
            print('== tennis', o)
            continue
        print(f"== {s}  n {o['n']}  counts {o['counts']}")
        print('   rest days', o['restDays'])
        for k in SPEC[s]['flags']:
            c, m = o['tests'][f'{k}|close'], o['tests'][f'{k}|model']
            print(f"   {k:6} size {o['size'][k]} priced {o['priced'][k]} | close tune {c['tune']} held {c['held']} seH {c['seHeld'][1]} q {c['q']}"
                  f" | model tune {m['tune']} held {m['held']} seH {m['seHeld'][1]} q {m['q']} {'PASS-C' if c['pass'] else ''}{'PASS-M' if m['pass'] else ''}")
