#!/usr/bin/env python3
"""Backtest for the in-season College Basketball ARKBOARD (scripts/cbb_live.py): how much a season to date should move
a player's grade off his preseason grade, by minutes played. Writes data/cbb_live_fit.json.

    python3 scripts/cbb_live_backtest.py

Data: Barttorvik's game-by-game player lines ({year}_all_advgames.json.gz, 2009-10 on), cached in
scripts/.cache/cbb/games/, and the linked careers (scripts/.cache/cbb/careers.json, scripts/cbb_link.py). For every
season 2009-10 to 2025-26 and every player, his line to date is rebuilt at nine dates (Nov 20 to the end of the
regular season), as Barttorvik would have shown it that morning. Shooting splits, rates and minutes add up straight
from the games; BPM, O-BPM, D-BPM, PORPAG, D-PORPAG and ORtg are season-level Barttorvik numbers that aren't sums of
games, so they're rebuilt from the summed lines by a regression fit on full seasons (r .98 or better at 200+ minutes).

Grades, all from the board's own FV model (data/cbb_fit.json):
  pre    his preseason grade (career before the season)
  now    the grade his career gets with the line to date added (next preseason's board, if the season ended today)
  full   the same with the whole season's line: where the board lands once the season is over
The in-season grade is (1 - w) pre + w now with w = n / (n + k), n his minutes so far. k is picked by squared error
against full, which is the right target: full is the expected grade once the season is in, so the best guess of it
on any date is the best guess of the grade itself. k is fit with one season held out at a time (17 folds); one k for
newcomers, one for returners. Two readings of "now" are tested: the line to date as is (a November line reads as a
short season), and with his games projected to a full season at his rate so far (rates stand, the sample is a season).
A check on careers: on the 2009-10 to 2015-16 seasons the blended grade is scored against what each player became.
xBPM: the rest-of-season BPM is predicted by preseason xBPM and BPM to date, weighted by minutes against kb, the
BPM stability point, fit the same way.
"""
import gzip, json, math, os, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
import cbb_fit as F
import cbb_live as L

SEASONS = range(2010, 2027)
CHECK = [(11, 20), (12, 1), (12, 15), (1, 1), (1, 15), (2, 1), (2, 15), (3, 1), (3, 15)]
KGRID = [0] + sorted({round(x) for x in np.geomspace(2, 6000, 80)})
GAMES = os.path.join(D.CACHE, 'games')
OUT = os.path.join(D.ROOT, 'data', 'cbb_live_fit.json')
def games(y):
    p = os.path.join(GAMES, f'{y}.json.gz')
    if not os.path.exists(p) or os.path.getsize(p) < 10000:
        D.fetch(f'https://barttorvik.com/{y}_all_advgames.json.gz', p, 1, binary=True)
    return json.load(gzip.open(p))


def load_season(y):
    """per player: game rows by date; per team: game dates; and the official season lines."""
    by_p, team_dates = defaultdict(list), defaultdict(set)
    for r in games(y):
        by_p[str(r[L.C['pid']])].append(r)
        team_dates[r[L.C['team']]].add((r[L.C['date']], r[L.C['muid']]))
    for rs in by_p.values(): rs.sort(key=lambda r: r[L.C['date']])
    tg = {t: sorted(d for d, _ in v) for t, v in team_dates.items()}
    return by_p, tg


def to_date(rs, tg, cut):
    """his game rows through date cut (yyyymmdd) and his team's games by then."""
    sub = [r for r in rs if r[L.C['date']] <= cut]
    if not sub: return None, 0
    dates = tg.get(sub[-1][L.C['team']], [])
    return sub, sum(1 for d in dates if d <= cut)


def fit_recon(seasons):
    X, Y, W = [], {k: [] for k in L.RECON}, []
    for y in seasons:
        by_p, tg = load_season(y)
        off = {r['pid']: r for r in D.load_bt(y)}
        for pid, rs in by_p.items():
            o = off.get(pid)
            if not o or (o['mp'] or 0) * (o['gp'] or 0) < 40 or any(o[k] is None for k in L.RECON): continue
            a = L.summed(rs, len(tg.get(rs[-1][L.C['team']], [])) or 1)
            X.append(L.rx(a)); W.append(min(1000.0, (o['mp'] or 0) * (o['gp'] or 0)))
            for k in L.RECON: Y[k].append(o[k])
    X, W = np.array(X, float), np.sqrt(np.array(W))
    out = {}
    for k in L.RECON:
        b = np.linalg.lstsq(X * W[:, None], np.array(Y[k]) * W, rcond=None)[0]
        p = X @ b; z = np.array(Y[k])
        out[k] = {'w': [round(float(v), 6) for v in b], 'r': round(float(np.corrcoef(p, z)[0, 1]), 4)}
    return out


def main():
    fit = json.load(open(F.OUT))
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    by_pid = {str(c['pid']): c for c in careers}
    print('rebuilding season-level numbers from games (fit on full seasons)...')
    recon = fit_recon(list(SEASONS))
    print('  ', {k: v['r'] for k, v in recon.items()})

    team_full = []
    rows = []    # one per player season: pre, then per date (n, now as is, now projected), full; plus xBPM pieces
    for y in SEASONS:
        by_p, tg = load_season(y)
        full_games = np.median([len(v) for v in tg.values() if len(v) >= 10])
        if y != 2021: team_full.append(float(full_games))
        cuts = [f'{y - 1 if m >= 11 else y}{m:02d}{d:02d}' for m, d in CHECK]
        n0 = len(rows)
        for pid, rs in by_p.items():
            c = by_pid.get(pid)
            if not c: continue
            i = next((j for j, s in enumerate(c['seasons']) if s['year'] == y), None)
            if i is None: continue
            meta = c['seasons'][i]
            # the board season's row holds only what's known before it tips off (Barttorvik's role is the season's
            # own: a newcomer has no other)
            srow = {k: meta.get(k) for k in ('year', 'team', 'conf', 'yr', 'hti', 'role', 'rec')}
            pre_cc = dict(c, seasons=c['seasons'][:i] + [srow])
            f_pre = F.features(pre_cc, i)
            team_n = len(tg.get(rs[-1][L.C['team']], [])) or 1
            full = L.line(L.summed(rs, team_n), recon, meta)
            row = {'y': y, 'pid': pid, 'new': f_pre['newcomer'], 'out': c['nba']['fv'], 'last': c['last'], 'f_pre': f_pre,
                   'f_full': F.features(L.next_career(pre_cc, full), i + 1), 'dates': []}
            mins_all = sum(r[L.C['min']] or 0 for r in rs)
            for cut in cuts:
                sub, tgd = to_date(rs, tg, cut)
                if not sub:
                    row['dates'].append(None); continue
                a = L.summed(sub, max(1, tgd))
                ln = L.line(a, recon, meta)
                n = a['mp'] * a['gp']
                gp_full = a['gp'] * full_games / max(1, tgd) if tgd < full_games else None
                ros = [r for r in rs if r[L.C['date']] > cut]
                ros_line = L.line(L.summed(ros, max(1, team_n - tgd)), recon, meta) if ros else None
                row['dates'].append({'n': n, 'f_raw': F.features(L.next_career(pre_cc, ln), i + 1),
                                     'f_proj': F.features(L.next_career(pre_cc, ln, gp_full), i + 1),
                                     'bpm': ln['bpm'], 'ros_bpm': ros_line['bpm'] if ros_line else None, 'ros_n': mins_all - n})
            rows.append(row)
        print(f'{y}: {len(rows) - n0} player seasons')

    # score everything with the board's model
    def sc(fs):
        e, p = L.score_many(fs, fit)
        return e, p
    e_pre, _ = sc([r['f_pre'] for r in rows])
    e_full, _ = sc([r['f_full'] for r in rows])
    xb_pre = np.array([L.xbpm_of(r['f_pre'], fit) for r in rows])
    pts = []     # (row index, date index, n, e_raw, e_proj)
    fr, fp = [], []
    for i, r in enumerate(rows):
        for j, d in enumerate(r['dates']):
            if d: pts.append((i, j, d['n'])); fr.append(d['f_raw']); fp.append(d['f_proj'])
    e_raw, _ = sc(fr); e_proj, _ = sc(fp)
    I = np.array([p[0] for p in pts]); J = np.array([p[1] for p in pts]); N = np.array([p[2] for p in pts], float)
    NEW = np.array([rows[i]['new'] for i in I]); YR = np.array([rows[i]['y'] for i in I])
    T = e_full[I]; P0 = e_pre[I]

    def err(k, now, mask):
        w = N[mask] / (N[mask] + k)
        return ((1 - w) * P0[mask] + w * now[mask] - T[mask]) ** 2

    res = {}
    for grp, gm in (('newcomer', NEW), ('returner', ~NEW)):
        res[grp] = {}
        for var, now in (('as is', e_raw), ('projected', e_proj)):
            # leave one season out: k from the other 16 seasons, error on the held-out one
            oos, ks = [], []
            for y in SEASONS:
                tr, te = gm & (YR != y), gm & (YR == y)
                k = min(KGRID, key=lambda k: err(k, now, tr).mean())
                ks.append(k); oos.append(err(k, now, te))
            oos = np.concatenate(oos)
            k_all = min(KGRID, key=lambda k: err(k, now, gm).mean())
            base = ((P0[gm] - T[gm]) ** 2)
            only = ((now[gm] - T[gm]) ** 2)
            # the top of the board, where the grades matter: the 300 best full grades each season
            top = np.zeros(len(T), bool)
            for y in SEASONS:
                m_ = gm & (YR == y)
                if m_.any(): top[m_] = T[m_] >= np.sort(np.unique(T[m_]))[::-1][:300][-1]
            kt = min(KGRID, key=lambda k: err(k, now, gm & top).mean())
            res[grp][var] = {'kTop': kt, 'mseTopPre': round(float(((P0[gm & top] - T[gm & top]) ** 2).mean()), 4),
                             'mseTopBlend': round(float(err(k_all, now, gm & top).mean()), 4),'k': k_all, 'kFolds': [int(min(ks)), int(np.median(ks)), int(max(ks))], 'mseBlendOOS': round(float(oos.mean()), 4),
                             'msePre': round(float(base.mean()), 4), 'mseNowOnly': round(float(only.mean()), 4),
                             'gainVsPre': round(float(1 - oos.mean() / base.mean()), 4), 'gainVsNow': round(float(1 - oos.mean() / only.mean()), 4)}
            print(f'   top 300: k {kt}, MSE pre {res[grp][var]["mseTopPre"]} blend {res[grp][var]["mseTopBlend"]}')
            print(f'{grp:9s} {var:9s} k {k_all:5d} (folds {res[grp][var]["kFolds"]})  MSE vs full: pre {base.mean():.3f}  now only {only.mean():.3f}  '
                  f'blend OOS {oos.mean():.3f}  ({100 * res[grp][var]["gainVsPre"]:.1f}% under pre)')
    # pick the reading of "now" with the lower held-out error, per group
    pick = {g: min(res[g], key=lambda v: res[g][v]['mseBlendOOS']) for g in res}
    k_pick = {g: res[g][pick[g]]['k'] for g in res}
    now_pick = np.where(NEW, e_raw if pick['newcomer'] == 'as is' else e_proj, e_raw if pick['returner'] == 'as is' else e_proj)
    W = N / (N + np.where(NEW, k_pick['newcomer'], k_pick['returner']))
    BL = (1 - W) * P0 + W * now_pick
    by_date = []
    for j, (m, d) in enumerate(CHECK):
        mk = J == j
        b0 = ((P0[mk] - T[mk]) ** 2).mean(); b1 = ((BL[mk] - T[mk]) ** 2).mean()
        by_date.append({'date': f'{m}/{d}', 'players': int(mk.sum()), 'medMin': round(float(np.median(N[mk]))), 'medW': round(float(np.median(W[mk])), 3),
                        'rmsePre': round(math.sqrt(b0), 3), 'rmseBlend': round(math.sqrt(b1), 3), 'gain': round(float(1 - b1 / b0), 3)})
        print('  ', by_date[-1])

    # careers: 2009-10 to 2015-16 seasons, finished careers. Does the in-season grade see the NBA players sooner?
    career = []
    for j, (m, d) in enumerate(CHECK):
        mk = (J == j) & (YR <= 2016)
        y = np.array([rows[i]['out'] for i in I[mk]])
        if not mk.any(): continue
        a0 = F.auc(P0[mk], y >= 30); a1 = F.auc(BL[mk], y >= 30); a2 = F.auc(e_full[I[mk]], y >= 30)
        s0 = F.auc(P0[mk][y >= 30], y[y >= 30] >= 45); s1 = F.auc(BL[mk][y >= 30], y[y >= 30] >= 45)
        career.append({'date': f'{m}/{d}', 'aucNbaPre': round(a0, 4), 'aucNbaBlend': round(a1, 4), 'aucNbaFull': round(a2, 4),
                       'aucStarterPre': round(s0, 4), 'aucStarterBlend': round(s1, 4)})
        print('   careers', career[-1])

    # xBPM: rest of season BPM from preseason xBPM and BPM to date
    xs = [(xb_pre[i], rows[i]['dates'][j]['bpm'], rows[i]['dates'][j]['ros_bpm'], N[q], rows[i]['dates'][j]['ros_n'], rows[i]['new'], rows[i]['y'])
          for q, (i, j) in enumerate(zip(I, J)) if rows[i]['dates'][j]['ros_bpm'] is not None and rows[i]['dates'][j]['ros_n'] >= 100]
    xa = np.array([x[:5] for x in xs], float); xnew = np.array([x[5] for x in xs]); xyr = np.array([x[6] for x in xs])
    kb = {}
    for grp, gm in (('newcomer', xnew), ('returner', ~xnew)):
        def berr(k, mask):
            pr = (xa[mask, 0] * k + xa[mask, 1] * xa[mask, 3]) / (k + xa[mask, 3])
            return float((xa[mask, 4] * (pr - xa[mask, 2]) ** 2).sum() / xa[mask, 4].sum())
        k = min(KGRID, key=lambda k: berr(k, gm))
        oos = [berr(min(KGRID, key=lambda k: berr(k, gm & (xyr != y))), gm & (xyr == y)) for y in SEASONS]
        e0 = float((xa[gm, 4] * (xa[gm, 0] - xa[gm, 2]) ** 2).sum() / xa[gm, 4].sum())
        e1 = float((xa[gm, 4] * (xa[gm, 1] - xa[gm, 2]) ** 2).sum() / xa[gm, 4].sum())
        kb[grp] = {'k': k, 'rmsePre': round(math.sqrt(e0), 3), 'rmseToDate': round(math.sqrt(e1), 3), 'rmseBlendOOS': round(math.sqrt(float(np.mean(oos))), 3)}
        print(f'xBPM {grp}: kb {k} minutes; rest-of-season BPM RMSE: preseason xBPM {kb[grp]["rmsePre"]}, to date {kb[grp]["rmseToDate"]}, blend {kb[grp]["rmseBlendOOS"]} (OOS)')

    out = {'asof': __import__('datetime').date.today().isoformat(), 'seasons': f'{SEASONS[0] - 1}-{str(SEASONS[0])[2:]} to {SEASONS[-1] - 1}-{str(SEASONS[-1])[2:]}',
           'playerSeasons': len(rows), 'checkpoints': len(pts), 'k': k_pick, 'now': pick, 'variants': res, 'byDate': by_date,
           'careers': career, 'kb': kb, 'fullGames': float(np.median(team_full)) if team_full else 31.0, 'recon': recon}
    json.dump(out, open(OUT, 'w'), indent=1)
    print('wrote', OUT, '; k:', k_pick, pick)


if __name__ == '__main__':
    main()
