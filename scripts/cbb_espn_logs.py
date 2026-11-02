#!/usr/bin/env python3
"""ESPN box scores as a stand-in for Barttorvik's college basketball game logs ({season}_all_advgames.json.gz) when
Barttorvik's site answers with a page instead of the file (it serves GitHub's runners a browser check). Nothing here
touches that check: when the pull fails, the season's games come from ESPN's public summaries instead.

    python3 scripts/cbb_espn_logs.py --fit       # fit the per-game BPM/ORtg proxy on Barttorvik's 2022-26 logs, check held out
    python3 scripts/cbb_espn_logs.py --check     # ESPN-built rows vs Barttorvik's own on a sample of 2025-26 games
    python3 scripts/cbb_espn_logs.py 2027 PATH   # fill PATH (a Barttorvik-shaped log file) with ESPN rows for games it lacks

The rows are Barttorvik's 53 columns in his order (cbb_live.GCOLS), so cbb_live.py, cbb_games.py and cbb_players.py
read them unchanged. Box-score columns (minutes, points, shooting, rebounds, assists, turnovers, steals, blocks, fouls)
come straight from ESPN; rim and dunk attempts from ESPN's play-by-play shot types (layups, tips, dunks); the rates
(usage, rebound, assist, turnover, steal, block %) by the standard formulas on the team and opponent box. Barttorvik's
per-game O-BPM, D-BPM and ORtg aren't box arithmetic: they are rebuilt by a regression on the box rates fit on his own
logs (data/cbb_espn_fit.json: tune 2022-23, held out 2024-26), where the box rows are built from his logs exactly as
from ESPN's. An ESPN row carries a 54th column, the ESPN event id, so a later fill (or Barttorvik's own file) replaces it.

Players get Barttorvik's id when the shared name matcher (scripts/names.py) finds them on the same team, among this
season's Barttorvik rows already cached, last season's at the school and the board's careers (scripts/cbb_prior.json.gz),
with the board's current team; anyone else gets
'e<ESPN id>', which cbb_live.py matches to the board by name and team like any newcomer.
"""
import gzip, json, math, os, sys, time, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as NM

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BOX = os.path.join(HERE, '.cache', 'cbb', 'espn_box')            # one summary per game (kept by the workflow cache)
BTLOG = os.path.join(HERE, '.cache', 'cbb', 'games_bt')
FIT = os.path.join(ROOT, 'data', 'cbb_espn_fit.json')
HIST = os.path.join(HERE, 'data', 'cbb_games_hist.json.gz')
SUMMARY = 'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event={}'
GCOLS = ['date', 'dtext', 'opstyle', 'quality', 'win1', 'opp', 'muid', 'win2', 'min', 'ortg', 'usg', 'efg', 'ts', 'orb', 'drb', 'ast',
         'to', 'dunkm', 'dunka', 'rimm', 'rima', 'midm', 'mida', 'twopm', 'twopa', 'tpm', 'tpa', 'ftm', 'fta', 'bpm_rd', 'obpm', 'dbpm',
         'bpm_net', 'pts', 'orb_n', 'drb_n', 'ast_n', 'tov', 'stl_n', 'blk_n', 'stl', 'blk', 'pf', 'poss', 'gbpm', 'sbpm', 'loc', 'team',
         'name', 'inches', 'cls', 'pid', 'year']
C = {k: i for i, k in enumerate(GCOLS)}
BOXK = ('min', 'pts', 'fgm', 'fga', 'tpm', 'tpa', 'ftm', 'fta', 'orb', 'drb', 'ast', 'tov', 'stl', 'blk', 'pf', 'rimm', 'rima', 'dunkm', 'dunka')
TARGETS = ('obpm', 'dbpm', 'ortg', 'sbpm')
TUNE, HOLD = (2022, 2023), (2024, 2025, 2026)


def et_date(iso):
    """the game day Barttorvik keys a game by (cbb_games.et_date: UTC minus 8 h)"""
    return (datetime.fromisoformat(iso.replace('Z', '+00:00')) - timedelta(hours=8)).strftime('%Y%m%d')


# ---------------------------------------------------------------- one game's box, from either source
def box_from_bt(rows):
    """Barttorvik rows of one game -> {team: {'opp', 'loc', 'players': [dict]}}"""
    g = {}
    for r in rows:
        t = g.setdefault(r[C['team']], {'opp': r[C['opp']], 'loc': r[C['loc']], 'poss': r[C['poss']], 'players': []})
        f = lambda k: float(r[C[k]] or 0)
        t['players'].append({'pid': r[C['pid']], 'name': r[C['name']], 'min': f('min'), 'pts': f('pts'),
                             'fgm': f('twopm') + f('tpm'), 'fga': f('twopa') + f('tpa'), 'tpm': f('tpm'), 'tpa': f('tpa'),
                             'ftm': f('ftm'), 'fta': f('fta'), 'orb': f('orb_n'), 'drb': f('drb_n'), 'ast': f('ast_n'),
                             'tov': f('tov'), 'stl': f('stl_n'), 'blk': f('blk_n'), 'pf': f('pf'), 'rimm': f('rimm'),
                             'rima': f('rima'), 'dunkm': f('dunkm'), 'dunka': f('dunka'),
                             'y': {k: r[C[k]] for k in TARGETS + ('usg', 'orb', 'drb', 'ast', 'to', 'stl', 'blk', 'ts', 'efg')}})
    return g


def _mk(s):
    try:
        a, b = s.split('-'); return float(a), float(b)
    except (ValueError, AttributeError):
        return 0.0, 0.0


def box_from_espn(summ, names):
    """an ESPN summary -> {team (Barttorvik name): {...}} as box_from_bt; names: ESPN team id -> Barttorvik name.
    None when the box is missing or a team isn't D-I (Barttorvik keeps no rows for those games)."""
    try:
        comp = summ['header']['competitions'][0]
        side = {c['team']['id']: c for c in comp['competitors']}
        neutral = comp.get('neutralSite', False)
        teams = summ['boxscore']['players']
    except (KeyError, IndexError, TypeError):
        return None
    if len(teams) != 2 or any(t['team']['id'] not in names for t in teams):
        return None
    shots = defaultdict(lambda: [0, 0, 0, 0])                    # athlete -> rim made, rim att, dunk made, dunk att
    for p in summ.get('plays') or []:
        ty = (p.get('type') or {}).get('text', '')
        if not p.get('shootingPlay') or not p.get('participants') or p.get('pointsAttempted') == 1 or 'FreeThrow' in ty:
            continue
        rim, dunk = ty in ('LayUpShot', 'TipShot', 'DunkShot'), ty == 'DunkShot'
        if not rim: continue
        a = p['participants'][0]['athlete']['id']
        made = bool(p.get('scoringPlay'))
        shots[a][0] += made; shots[a][1] += 1
        if dunk: shots[a][2] += made; shots[a][3] += 1
    g = {}
    ids = [t['team']['id'] for t in teams]
    for t in teams:
        tid = t['team']['id']
        oid = ids[1 - ids.index(tid)]
        st = t['statistics'][0]
        ks = st['keys']
        loc = 'N' if neutral else ('H' if side.get(tid, {}).get('homeAway') == 'home' else 'A')
        pl = []
        for a in st['athletes']:
            if a.get('didNotPlay') or not a.get('stats'): continue
            v = dict(zip(ks, a['stats']))
            try:
                mn = float(v.get('minutes') or 0)
            except ValueError:
                mn = 0.0
            if mn <= 0: continue
            fgm, fga = _mk(v.get('fieldGoalsMade-fieldGoalsAttempted'))
            tpm, tpa = _mk(v.get('threePointFieldGoalsMade-threePointFieldGoalsAttempted'))
            ftm, fta = _mk(v.get('freeThrowsMade-freeThrowsAttempted'))
            n = lambda k: float(v.get(k) or 0) if str(v.get(k) or '0').lstrip('-').isdigit() else 0.0
            s = shots.get(a['athlete']['id'], [0, 0, 0, 0])
            pl.append({'pid': None, 'espn': a['athlete']['id'], 'name': a['athlete']['displayName'], 'min': mn, 'pts': n('points'),
                       'fgm': fgm, 'fga': fga, 'tpm': tpm, 'tpa': tpa, 'ftm': ftm, 'fta': fta, 'orb': n('offensiveRebounds'),
                       'drb': n('defensiveRebounds'), 'ast': n('assists'), 'tov': n('turnovers'), 'stl': n('steals'),
                       'blk': n('blocks'), 'pf': n('fouls'), 'rimm': float(s[0]), 'rima': float(s[1]),
                       'dunkm': float(s[2]), 'dunka': float(s[3])})
        g[names[tid]] = {'opp': names[oid], 'loc': loc, 'players': pl}
    if any(not t['players'] for t in g.values()):
        return None
    return g


# ---------------------------------------------------------------- rates and the proxy's features
def tot(pl):
    return {k: sum(p[k] for p in pl) for k in BOXK}


def game_poss(g):
    """possessions per team in the game, the mean of the two sides' FGA - ORB + TO + .475 FTA"""
    ps = [T['fga'] - T['orb'] + T['tov'] + 0.475 * T['fta'] for T in (tot(t['players']) for t in g.values())]
    return sum(ps) / len(ps)


def oliver(p, T, O):
    """Dean Oliver's individual offensive rating (points produced per 100 individual possessions), the box formula
    Barttorvik's ORtg follows; None when the player used no possessions"""
    try:
        G = T['min'] / 5
        fg, fga, ft, fta, tp, pts, ast, orb, tov, mp = (p[k] for k in ('fgm', 'fga', 'ftm', 'fta', 'tpm', 'pts', 'ast', 'orb', 'tov', 'min'))
        if fga + fta + tov <= 0: return None
        tfg, tfga, tft, tfta, ttp, tpts, tast, torb = (T[k] for k in ('fgm', 'fga', 'ftm', 'fta', 'tpm', 'pts', 'ast', 'orb'))
        sh = mp / G
        q1 = sh * 1.14 * ((tast - ast) / tfg) if tfg else 0.0
        den = (tfg / T['min']) * mp * 5 - fg
        q2 = (((tast / T['min']) * mp * 5 - ast) / den) * (1 - sh) if den > 0 else 0.0
        qast = q1 + q2
        fgr = (pts - ft) / (2 * fga) if fga else 0.0
        fg_part = fg * (1 - 0.5 * fgr * qast)
        oth = 2 * (tfga - fga)
        ast_part = 0.5 * (((tpts - tft) - (pts - ft)) / oth) * ast if oth > 0 else 0.0
        ftp = ft / fta if fta else 0.0
        ft_part = (1 - (1 - ftp) ** 2) * 0.4 * fta
        tftp = tft / tfta if tfta else 0.0
        tsc = tfg + (1 - (1 - tftp) ** 2) * tfta * 0.4
        torbp = torb / (torb + O['drb']) if torb + O['drb'] else 0.0
        tplay = tsc / (tfga + tfta * 0.4 + T['tov']) if tfga + tfta + T['tov'] else 0.0
        dw = (1 - torbp) * tplay + torbp * (1 - tplay)
        orbw = (1 - torbp) * tplay / dw if dw else 0.0
        adj = 1 - (torb / tsc) * orbw * tplay if tsc else 1.0
        scposs = (fg_part + ast_part + ft_part) * adj + orb * orbw * tplay
        totposs = scposs + (fga - fg) * (1 - 1.07 * torbp) + (1 - ftp) ** 2 * 0.4 * fta + tov
        pp_fg = 2 * (fg + 0.5 * tp) * (1 - 0.5 * fgr * qast)
        ofg = tfg - fg
        pp_ast = 2 * ((ofg + 0.5 * (ttp - tp)) / ofg) * ast_part if ofg > 0 else 0.0
        pp_orb = orb * orbw * tplay * (tpts / tsc) if tsc else 0.0
        pprod = (pp_fg + pp_ast + ft) * adj + pp_orb
        return 100 * pprod / totposs if totposs > 0 else None
    except ZeroDivisionError:
        return None


def rates(g, R=None):
    """per player: Barttorvik-style rates (usg, orb, drb, ast, to, stl, blk, efg, ts) and the proxy's features.
    R: team -> net rating per 100 possessions (opponent-adjusted, centred on D-I); Barttorvik's game BPM is adjusted
    for the opponent and the team, which a box score alone can't see (held out 2024-26, season BPM r .86 without, .97 with)"""
    R = R or {}
    poss = game_poss(g)
    out = []
    for team, t in g.items():
        o = g[t['opp']]
        T, O = tot(t['players']), tot(o['players'])
        G = max(T['min'] / 5, 1.0)                                # game length in minutes (OT included)
        tposs = T['fga'] - T['orb'] + T['tov'] + 0.475 * T['fta']
        net = (T['pts'] - O['pts']) / max(poss, 1) * 100
        tor, dr = T['pts'] / max(poss, 1) * 100, O['pts'] / max(poss, 1) * 100
        rt, ro = R.get(team, 0.0), R.get(t['opp'], 0.0)
        loc = {'H': 1.0, 'A': -1.0}.get(t['loc'], 0.0)
        for p in t['players']:
            m = p['min']
            share = m / G
            on = share * poss                                     # team possessions while he played
            u = p['fga'] + 0.475 * p['fta'] + p['tov']
            r = {'usg': 100 * u / max(share * tposs, 1e-9),
                 'orb': 100 * p['orb'] / max(share * (T['orb'] + O['drb']), 1e-9),
                 'drb': 100 * p['drb'] / max(share * (T['drb'] + O['orb']), 1e-9),
                 'ast': 100 * p['ast'] / max(share * T['fgm'] - p['fgm'], 1e-9) if share * T['fgm'] - p['fgm'] > 0.5 else 0.0,
                 'to': 100 * p['tov'] / u if u else 0.0,
                 'stl': 100 * p['stl'] / max(share * poss, 1e-9),
                 'blk': 100 * p['blk'] / max(share * (O['fga'] - O['tpa']), 1e-9),
                 'efg': 100 * (p['fgm'] + 0.5 * p['tpm']) / p['fga'] if p['fga'] else 0.0,
                 'ts': 100 * p['pts'] / (2 * (p['fga'] + 0.475 * p['fta'])) if p['fga'] + p['fta'] else 0.0}
            ol = oliver(p, T, O)
            r['oliver'] = ol
            h = 100 / max(on, 1.0)                                # per 100 of his possessions
            two_m, two_a = p['fgm'] - p['tpm'], p['fga'] - p['tpa']
            x = [p['pts'] * h, two_m * h, two_a * h, p['tpm'] * h, p['tpa'] * h, p['ftm'] * h, p['fta'] * h, p['orb'] * h,
                 p['drb'] * h, p['ast'] * h, p['tov'] * h, p['stl'] * h, p['blk'] * h, p['pf'] * h, p['rimm'] * h,
                 p['rima'] * h, net, tor, dr, share, r['usg'], r['orb'], r['drb'], r['ast'], r['stl'], r['blk'],
                 (ol if ol is not None else 100.0) - 100, float(ol is None), ro, rt, loc]
            out.append((team, p, r, x, poss))
    return out


FEATS = ['pts', '2pm', '2pa', '3pm', '3pa', 'ftm', 'fta', 'orb', 'drb', 'ast', 'tov', 'stl', 'blk', 'pf', 'rimm', 'rima',
         'net', 'tortg', 'drtg', 'share', 'usg%', 'orb%', 'drb%', 'ast%', 'stl%', 'blk%', 'oliver', 'no_poss', 'opp_r', 'team_r', 'loc']
CLIP = 60.0                                                       # per-100 counts capped (a 2-minute stint inflates them)


def design(x, share):
    """features with a shrink toward zero for short stints: each per-100 rate times share/(share+.15), plus raw"""
    x = np.clip(np.array(x, float), -CLIP * 3, CLIP * 3)
    w = share / (share + 0.15)
    return np.concatenate([[1.0], x[:26] * w, x[26:28] * w, x[28:], [w, share * x[16], share * x[17], share * x[18]],
                           share * x[28:]])


def predict(fit, x, share):
    z = design(x, share)
    return {k: float(z @ np.array(fit['w'][k])) for k in fit['w']}


# ---------------------------------------------------------------- fit on Barttorvik's own logs
def bt_rows(season):
    p = os.path.join(BTLOG, f'{season}.json.gz')
    if not os.path.exists(p) or os.path.getsize(p) < 100000:
        os.makedirs(BTLOG, exist_ok=True)
        urllib.request.urlretrieve(f'https://barttorvik.com/{season}_all_advgames.json.gz', p)
    return json.load(gzip.open(p))


def bt_games(season):
    by = defaultdict(list)
    for r in bt_rows(season):
        if len(r) >= 53:
            by[(r[C['date']], r[C['muid']])].append(r)
    return {k: v for k, v in by.items() if len({r[C['team']] for r in v}) == 2}


def season_ratings(season):
    """team -> net points per 100 possessions, opponent- and site-adjusted (ridge on the season's game margins from
    Barttorvik's logs), centred on D-I: the history stand-in for the live game model's off - def"""
    idx, rows = {}, []
    for rs in bt_games(season).values():
        g = box_from_bt(rs)
        a, b = list(g)
        pa, pb = (sum(p['pts'] for p in g[t]['players']) for t in (a, b))
        for t in (a, b): idx.setdefault(t, len(idx))
        rows.append((idx[a], idx[b], {'H': 1, 'A': -1}.get(g[a]['loc'], 0), (pa - pb) / game_poss(g) * 100))
    n = len(idx)
    X, y = np.zeros((len(rows), n + 1)), np.zeros(len(rows))
    for i, (a, b, l, m) in enumerate(rows):
        X[i, a], X[i, b], X[i, n], y[i] = 1, -1, l, m
    w = np.linalg.solve(X.T @ X + np.eye(n + 1) * 2, X.T @ y)
    r = w[:n] - w[:n].mean()
    return {t: float(r[i]) for t, i in idx.items()}


_RATE = {}


def ratings_for(season):
    if season not in _RATE: _RATE[season] = season_ratings(season)
    return _RATE[season]


def matrix(seasons, lag=0):
    """lag 1: last season's ratings in place of this season's (a pessimistic stand-in for early-season ratings)"""
    X, Y, W, key = [], [], [], []
    for s in seasons:
        R = ratings_for(s - lag)
        for (d, mu), rows in bt_games(s).items():
            g = box_from_bt(rows)
            for team, p, r, x, poss in rates(g, R):
                if any(p['y'][k] is None for k in TARGETS): continue
                X.append(design(x, x[19])); Y.append([float(p['y'][k]) for k in TARGETS]); W.append(p['min'])
                key.append((s, p['pid'], d, p['min']))
    return np.array(X), np.array(Y), np.array(W), key


def wcorr(a, b, w):
    c = np.cov(np.vstack([a, b]), aweights=w)
    return round(float(c[0, 1] / math.sqrt(max(1e-12, c[0, 0] * c[1, 1]))), 4)


def ridge(X, Y, W, lam=1.0):
    A = X.T @ (X * W[:, None]) + lam * np.eye(X.shape[1]) * W.sum() / len(W)
    A[0, 0] -= lam * W.sum() / len(W)
    return np.linalg.solve(A, X.T @ (Y * W[:, None]))


def season_err(key, y, yh, mins_cut):
    """per player season: minute-weighted mean of the game values, actual vs proxy, for players past mins_cut minutes
    (the to-date number avail() and cbb_live read): RMSE and r"""
    acc = defaultdict(lambda: [0.0, 0.0, 0.0])
    for (s, pid, d, m), a, b in zip(key, y, yh):
        z = acc[(s, pid)]; z[0] += m; z[1] += a * m; z[2] += b * m
    v = np.array([(z[1] / z[0], z[2] / z[0]) for z in acc.values() if z[0] >= mins_cut])
    if len(v) < 10: return None
    return {'n': len(v), 'rmse': round(float(np.sqrt(((v[:, 0] - v[:, 1]) ** 2).mean())), 3),
            'r': round(float(np.corrcoef(v[:, 0], v[:, 1])[0, 1]), 4), 'sd': round(float(v[:, 0].std()), 3)}


def to_date_err(key, y, yh, cut_games):
    """the same at a player's first cut_games games (early-season to-date numbers)"""
    by = defaultdict(list)
    for (s, pid, d, m), a, b in zip(key, y, yh):
        by[(s, pid)].append((d, m, a, b))
    v = []
    for rs in by.values():
        rs.sort()
        rs = rs[:cut_games]
        if len(rs) < cut_games: continue
        m = sum(r[1] for r in rs)
        if m < 40: continue
        v.append((sum(r[1] * r[2] for r in rs) / m, sum(r[1] * r[3] for r in rs) / m))
    v = np.array(v)
    return {'n': len(v), 'rmse': round(float(np.sqrt(((v[:, 0] - v[:, 1]) ** 2).mean())), 3),
            'r': round(float(np.corrcoef(v[:, 0], v[:, 1])[0, 1]), 4), 'sd': round(float(v[:, 0].std()), 3)}


RATES = ('usg', 'orb', 'drb', 'ast', 'to', 'stl', 'blk')


def calibrate(seasons):
    """Barttorvik's rates and possessions as a line in the box-formula ones (his denominators count team rebounds and
    turnovers no player is credited with, which neither source's player rows carry): minute-weighted least squares"""
    xs, ys, ws, px, py = defaultdict(list), defaultdict(list), defaultdict(list), [], []
    for s in seasons:
        for rows in bt_games(s).values():
            g = box_from_bt(rows)
            px.append(game_poss(g)); py.append(float(rows[0][C['poss']] or 0))
            for team, p, r, x, poss in rates(g):
                if p['min'] < 5: continue
                for k in RATES:
                    if p['y'][k] is None: continue
                    xs[k].append(r[k]); ys[k].append(float(p['y'][k])); ws[k].append(p['min'])
    out = {}
    for k in RATES:
        X = np.column_stack([np.ones(len(xs[k])), xs[k]]); w = np.array(ws[k]); y = np.array(ys[k])
        b = np.linalg.lstsq(X * np.sqrt(w)[:, None], y * np.sqrt(w), rcond=None)[0]
        out[k] = [round(float(b[0]), 4), round(float(b[1]), 5)]
    X = np.column_stack([np.ones(len(px)), px])
    b = np.linalg.lstsq(X, np.array(py), rcond=None)[0]
    out['poss'] = [round(float(b[0]), 4), round(float(b[1]), 5)]
    return out


def cal(fit, k, v):
    a, b = fit.get('cal', {}).get(k, (0.0, 1.0))
    return 0.0 if v == 0 else max(0.0, a + b * v)


def fit():
    Xt, Yt, Wt, _ = matrix(TUNE)
    Xh, Yh, Wh, kh = matrix(HOLD)
    best = None
    X1, Y1, W1, _ = matrix(TUNE[:1])
    X2, Y2, W2, _ = matrix(TUNE[1:])
    for lam in (0.001, 0.01, 0.1, 1.0, 10.0):
        # the ridge penalty: fit on the first tune season, scored on the second
        W = ridge(X1, Y1, W1, lam)
        e = float((((X2 @ W - Y2) ** 2) * W2[:, None]).sum())
        if best is None or e < best[0]: best = (e, lam)
    lam = best[1]
    W = ridge(Xt, Yt, Wt, lam)
    P = Xh @ W
    rep = {'tune': list(TUNE), 'held': list(HOLD), 'lam': lam, 'rows_tune': int(len(Yt)), 'rows_held': int(len(Yh)), 'held_out': {}}
    gb = (Yh[:, 0] + Yh[:, 1], P[:, 0] + P[:, 1])
    cols = {k: (Yh[:, i], P[:, i]) for i, k in enumerate(TARGETS)}
    cols['gbpm'] = gb
    for k, (a, b) in cols.items():
        wgt = Wh / Wh.sum()
        rep['held_out'][k] = {
            'game_r_minw': wcorr(a, b, Wh),
            'game_rmse_minw': round(float(np.sqrt(((a - b) ** 2 * wgt).sum())), 3),
            'season_200min': season_err(kh, a, b, 200), 'first5_games': to_date_err(kh, a, b, 5), 'first10_games': to_date_err(kh, a, b, 10)}
    # ratings known only from last season (a newcomer team gets 0): the floor for early-season ratings
    Xl, Yl, Wl, kl = matrix(HOLD, lag=1)
    Pl = Xl @ W
    a, b = Yl[:, 0] + Yl[:, 1], Pl[:, 0] + Pl[:, 1]
    rep['held_out_last_season_ratings'] = {'gbpm': {'game_r_minw': wcorr(a, b, Wl), 'season_200min': season_err(kl, a, b, 200),
                                                    'first5_games': to_date_err(kl, a, b, 5)}}
    # refit on every season for the shipped weights
    Xa, Ya, Wa = np.vstack([Xt, Xh]), np.vstack([Yt, Yh]), np.concatenate([Wt, Wh])
    Wall = ridge(Xa, Ya, Wa, lam)
    out = {'asof': time.strftime('%Y-%m-%d'), 'feats': FEATS, 'targets': list(TARGETS), 'report': rep, 'cal': calibrate(TUNE),
           'w': {k: [round(float(v), 6) for v in Wall[:, i]] for i, k in enumerate(TARGETS)}}
    json.dump(out, open(FIT, 'w'), indent=1)
    print(json.dumps(rep, indent=1))


# ---------------------------------------------------------------- ESPN -> Barttorvik rows
def espn_summary(eid, final=True):
    p = os.path.join(BOX, f'{eid}.json.gz')
    if os.path.exists(p):
        try:
            return json.load(gzip.open(p))
        except Exception:  # noqa: BLE001
            pass
    for i in range(3):
        try:
            req = urllib.request.Request(SUMMARY.format(eid), headers={'User-Agent': 'Mozilla/5.0'})
            d = json.load(urllib.request.urlopen(req, timeout=30))
            break
        except Exception:  # noqa: BLE001
            time.sleep(2 * (i + 1))
    else:
        return None
    keep = {'header': d.get('header'), 'boxscore': d.get('boxscore'),
            'plays': [{k: p.get(k) for k in ('type', 'shootingPlay', 'scoringPlay', 'pointsAttempted', 'participants')}
                      for p in d.get('plays') or [] if p.get('shootingPlay')]}
    if final and (d.get('boxscore') or {}).get('players'):
        os.makedirs(BOX, exist_ok=True)
        with gzip.open(p, 'wt') as fh:
            json.dump(keep, fh, separators=(',', ':'))
    return keep


def team_names(*game_lists):
    """ESPN team id -> Barttorvik name, from the game files that carry both (the possessions join's hb/ab)"""
    m = defaultdict(lambda: defaultdict(int))
    for games in game_lists:
        for g in games:
            if 'hb' in g:
                m[g['home']][g['hb']] += 1; m[g['away']][g['ab']] += 1
    return {t: max(c, key=c.get) for t, c in m.items()}


def rows_for(g, eid, date, season, fit, pick_pid, R=None):
    out = []
    dtext = f'{int(date[4:6])}-{int(date[6:8])}'
    teams = list(g)
    muid = ''.join(sorted(teams)) + dtext
    pts = {t: sum(p['pts'] for p in g[t]['players']) for t in teams}
    for team, p, r, x, poss in rates(g, R):
        y = predict(fit, x, x[19])
        ob, db = y['obpm'], y['dbpm']
        win = int(pts[team] > pts[g[team]['opp']])
        pid = pick_pid(team, p)
        row = [None] * len(GCOLS)
        v = {'date': date, 'dtext': dtext, 'opstyle': 0, 'quality': 0, 'win1': win, 'opp': g[team]['opp'], 'muid': muid, 'win2': win,
             'min': p['min'], 'ortg': round(y['ortg'], 1), 'usg': round(cal(fit, 'usg', r['usg']), 1), 'efg': round(r['efg'], 1), 'ts': round(r['ts'], 1),
             'orb': round(cal(fit, 'orb', r['orb']), 1), 'drb': round(cal(fit, 'drb', r['drb']), 1), 'ast': round(cal(fit, 'ast', r['ast']), 1), 'to': round(cal(fit, 'to', r['to']), 1),
             'dunkm': p['dunkm'], 'dunka': p['dunka'], 'rimm': p['rimm'], 'rima': p['rima'],
             'midm': p['fgm'] - p['tpm'] - p['rimm'], 'mida': p['fga'] - p['tpa'] - p['rima'],
             'twopm': p['fgm'] - p['tpm'], 'twopa': p['fga'] - p['tpa'], 'tpm': p['tpm'], 'tpa': p['tpa'], 'ftm': p['ftm'], 'fta': p['fta'],
             'bpm_rd': round(ob + db, 1), 'obpm': ob, 'dbpm': db, 'bpm_net': round(y['sbpm'], 1), 'pts': p['pts'], 'orb_n': p['orb'],
             'drb_n': p['drb'], 'ast_n': p['ast'], 'tov': p['tov'], 'stl_n': p['stl'], 'blk_n': p['blk'], 'stl': round(cal(fit, 'stl', r['stl']), 1),
             'blk': round(cal(fit, 'blk', r['blk']), 1), 'pf': p['pf'], 'poss': round(cal(fit, 'poss', poss), 3), 'gbpm': ob + db, 'sbpm': y['sbpm'], 'loc': g[team]['loc'],
             'team': team, 'name': p['name'], 'inches': None, 'cls': None, 'pid': pid, 'year': season}
        for k, val in v.items(): row[C[k]] = val
        out.append(row + [eid])
    return out


class Pids:
    """Barttorvik ids by team for this season: his rows already cached, last season's at the school, the board's careers"""
    def __init__(self, season, bt_rows):
        pool = defaultdict(dict)
        for r in bt_rows:
            pool[r[C['team']]][r[C['pid']]] = r[C['name']]
        try:                                                      # last season's players at the same school (returners)
            for r in json.load(gzip.open(os.path.join(BTLOG, f'{season - 1}.json.gz'))):
                pool[r[C['team']]].setdefault(r[C['pid']], r[C['name']])
        except Exception:  # noqa: BLE001
            pass
        try:
            d = json.load(gzip.open(os.path.join(HERE, 'cbb_prior.json.gz')))
            ni = d['cols'].index('name')
            for row, c in zip(d['rows'], d['careers']):
                if c.get('bt') and c.get('pid'):
                    pool[c['bt']].setdefault(int(c['pid']) if str(c['pid']).isdigit() else c['pid'], row[ni])
        except Exception as e:  # noqa: BLE001
            print('cbb espn logs: no board careers for the id match:', e)
        self.m = {t: NM.Matcher([{'pid': p, 'name': n} for p, n in v.items()], team=None, pos=None, sport='basketball')
                  for t, v in pool.items()}
        self.hit = self.miss = 0

    def __call__(self, team, p):
        m = self.m.get(team)
        r, _ = m.find(p['name']) if m else (None, None)
        if r:
            self.hit += 1; return r['pid']
        self.miss += 1
        return f"e{p['espn']}"


def live_ratings(names):
    """Barttorvik team -> the live game model's net rating (off - def per 100, data/cbb_games.json power), centred"""
    try:
        pw = json.load(open(os.path.join(ROOT, 'data', 'cbb_games.json')))['power']
        v = {names[x['id']]: x['off'] - x['def'] for x in pw if x.get('id') in names and x.get('off') is not None}
        m = sum(v.values()) / len(v)
        return {t: r - m for t, r in v.items()}
    except Exception as e:  # noqa: BLE001
        print('cbb espn logs: no live team ratings, BPM unadjusted for opponent:', e)
        return {}


def d1_ids(names):
    """ESPN ids of D-I teams (Barttorvik logs only D-I vs D-I games): the live game model's power list, else the
    teams in last season's Barttorvik logs"""
    try:
        ids = {x['id'] for x in json.load(open(os.path.join(ROOT, 'data', 'cbb_games.json')))['power']}
        if len(ids) > 300: return ids & set(names)
    except Exception:  # noqa: BLE001
        pass
    seen = set()
    for f in sorted(os.listdir(BTLOG)) if os.path.isdir(BTLOG) else []:
        try:
            seen = {r[C['team']] for r in json.load(gzip.open(os.path.join(BTLOG, f)))}
        except Exception:  # noqa: BLE001
            continue
    return {i for i, n in names.items() if n in seen}


def fill(season, path, games_file=None, limit=None):
    """PATH keeps Barttorvik's rows; every finished D-I game it lacks (by team and date) is added from ESPN, and ESPN
    rows from an earlier fill are rebuilt. Returns the number of ESPN games in the file."""
    fit = json.load(open(FIT))
    games_file = games_file or os.path.join(HERE, 'data', f'cbb_games_{season}.json.gz')
    games = json.load(gzip.open(games_file))
    names = team_names(json.load(gzip.open(HIST)), games)
    try:
        old = json.load(gzip.open(path))
    except Exception:  # noqa: BLE001
        old = []
    bt = [r for r in old if len(r) == len(GCOLS) and r[C['year']] == season]
    have = {(r[C['team']], r[C['date']]) for r in bt}
    pick = Pids(season, bt)
    R = live_ratings(names)
    rows, n, skip = [], 0, 0
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
    d1 = d1_ids(names)
    todo = [g for g in games if g.get('season') == season and g.get('state') == 'post' and g['date'] < now
            and g.get('home') in d1 and g.get('away') in d1]
    for g in sorted(todo, key=lambda g: g['date'])[:limit]:
        d = et_date(g['date'])
        if (names[g['home']], d) in have or (names[g['away']], d) in have:
            continue
        s = espn_summary(g['id'])
        b = box_from_espn(s, names) if s else None
        if not b:
            skip += 1; continue
        rows += rows_for(b, g['id'], d, season, fit, pick, R)
        n += 1
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path + '.tmp', 'wt') as fh:
        json.dump(bt + rows, fh, separators=(',', ':'))
    os.replace(path + '.tmp', path)
    print(f'cbb espn logs: {len(bt)} Barttorvik rows kept, {n} games ({len(rows)} player rows) from ESPN box scores'
          f'{f", {skip} without a usable box" if skip else ""}; Barttorvik id matched {pick.hit}, new {pick.miss}')
    return n


def pull(season, path, ua='Mozilla/5.0', tries=1):
    """Barttorvik's file for the season into PATH; when he answers with a page, the ESPN fill instead.
    Returns 'bt', 'espn' or None."""
    import subprocess
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for i in range(0 if os.environ.get('CBB_BT_BLOCKED') else tries):      # CBB_BT_BLOCKED=1: test the fallback
        subprocess.run(['curl', '-s', '-m', '300', '-A', ua, f'https://barttorvik.com/{season}_all_advgames.json.gz', '-o', path + '.new'], check=False)
        try:
            with open(path + '.new', 'rb') as fh:
                if fh.read(2) == b'\x1f\x8b':
                    json.load(gzip.open(path + '.new'))
                    os.replace(path + '.new', path)
                    return 'bt'
        except Exception:  # noqa: BLE001
            pass
        if i + 1 < tries: time.sleep(30)
    print(f'barttorvik {season} game logs: got a page, not the file; filling from ESPN box scores')
    try:
        fill(season, path)
        return 'espn'
    except Exception as e:  # noqa: BLE001
        print('cbb espn logs failed:', e)
        return None


# ---------------------------------------------------------------- end-to-end check on a past season
def check(season=2026, n=400):
    """ESPN-built rows (box from ESPN, proxy BPM) vs Barttorvik's rows for the same players, on n games of the season"""
    fit = json.load(open(FIT))
    hist = json.load(gzip.open(HIST))
    names = team_names(hist)
    bt = defaultdict(dict)
    for r in bt_rows(season):
        bt[(r[C['team']], r[C['date']])][NM.key(r[C['name']])] = r
    gs = [g for g in hist if g['season'] == season and g['home'] in names and g['away'] in names]
    R = ratings_for(season)
    rng = np.random.default_rng(7)
    gs = [gs[i] for i in rng.choice(len(gs), min(n, len(gs)), replace=False)]
    pairs, miss, games = [], 0, 0
    for g in gs:
        d = et_date(g['date'])
        s = espn_summary(g['id'])
        b = box_from_espn(s, names) if s else None
        if not b: continue
        rows = rows_for(b, g['id'], d, season, fit, lambda t, p: None, R)
        hit = False
        for r in rows:
            o = bt.get((r[C['team']], r[C['date']]), {}).get(NM.key(r[C['name']]))
            if o is None:
                miss += 1; continue
            hit = True
            pairs.append((r, o))
        games += hit
    rep = {'season': season, 'games': games, 'rows': len(pairs), 'unmatched_rows': miss}
    for k in ('min', 'pts', 'twopa', 'tpa', 'fta', 'orb_n', 'drb_n', 'ast_n', 'tov', 'stl_n', 'blk_n', 'rima', 'dunka', 'usg', 'orb', 'drb',
              'ast', 'to', 'stl', 'blk', 'poss', 'ortg', 'obpm', 'dbpm', 'gbpm'):
        a = np.array([float(o[C[k]] or 0) for r, o in pairs]); b = np.array([float(r[C[k]] or 0) for r, o in pairs])
        w = np.array([float(o[C['min']] or 0) for r, o in pairs])
        rep[k] = {'r_minw': wcorr(a, b, w),
                  'mean_bt': round(float(np.average(a, weights=w)), 2), 'mean_espn': round(float(np.average(b, weights=w)), 2)}
    # the season-level check that matters: each player's minute-weighted game BPM over these games
    acc = defaultdict(lambda: [0.0, 0.0, 0.0])
    for r, o in pairs:
        z = acc[o[C['pid']]]; m = float(o[C['min']]); z[0] += m; z[1] += m * float(o[C['gbpm']]); z[2] += m * float(r[C['gbpm']])
    v = np.array([(z[1] / z[0], z[2] / z[0]) for z in acc.values() if z[0] >= 60])
    rep['player_gbpm_60min'] = {'n': len(v), 'r': round(float(np.corrcoef(v[:, 0], v[:, 1])[0, 1]), 4),
                                'rmse': round(float(np.sqrt(((v[:, 0] - v[:, 1]) ** 2).mean())), 3)}
    print(json.dumps(rep, indent=1))
    f = json.load(open(FIT)); f['espn_check'] = rep; json.dump(f, open(FIT, 'w'), indent=1)


if __name__ == '__main__':
    if '--fit' in sys.argv:
        fit()
    elif '--check' in sys.argv:
        check()
    elif len(sys.argv) >= 3:
        fill(int(sys.argv[1]), sys.argv[2])
    else:
        print(__doc__)
