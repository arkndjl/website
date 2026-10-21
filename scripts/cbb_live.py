#!/usr/bin/env python3
"""The College Basketball ARKBOARD in season: each player's preseason grade blended with what his stats this season
say, by how many minutes he has played. Run daily from November to April by .github/workflows/cbb-board.yml.

    python3 scripts/cbb_live.py            # pull Barttorvik's season-to-date lines and rebuild the board
    python3 scripts/cbb_live.py --offline  # rebuild from the cached pull

Two grades per player, both from the board's own FV model (data/cbb_fit.json, fit by scripts/cbb_fit.py):
  pre   the preseason grade: his career before this season (what scripts/fetch_cbb.py graded)
  now   the grade his career would get with this season's line to date added, as next preseason's board would see it
E[FV] = (1 - w) x pre + w x now, with w = n / (n + k): n his minutes this season, k the minutes at which this season
weighs as much as everything known before it. k is fit by scripts/cbb_live_backtest.py on 2010-2026 game logs, one k
for newcomers and one for returners (data/cbb_live_fit.json). The drivers move the same way: each driver's share is
(1 - w) x its preseason share + w x its share in the "now" grade. P(NBA) blends the same way, and xBPM becomes the
rest-of-season BPM: his preseason projection and his BPM to date, weighted by minutes against the BPM stability point.

Inputs: scripts/cbb_prior.json.gz, the preseason board frozen by fetch_cbb.py (each player's board row and his career as the
model reads it), and Barttorvik's 2026-27 season-to-date lines (getadvstats.php?year=2027), matched by Barttorvik id,
then by name and team for newcomers. Before the first game nobody has minutes, so the board is the preseason board.
"""
import json, math, os, re, sys, time
from collections import Counter, defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
import cbb_fit as F

SEASON = 2027
OFFLINE = '--offline' in sys.argv
PRIOR = os.path.join(D.HERE, 'cbb_prior.json.gz')   # outside data/: Hugo would load it on every build
LIVE_FIT = os.path.join(D.ROOT, 'data', 'cbb_live_fit.json')
NEXT_YR = {'Fr': 'So', 'So': 'Jr', 'Jr': 'Sr', 'Sr': 'Sr'}
# the Barttorvik columns the FV model reads from a season (cbb_fit.py features and season_line), plus a few more it
# could take up (A/TO, the per-game lines); the prior keeps only these
KEEP = ['team', 'conf', 'yr', 'year', 'hti', 'role', 'rec', 'gp', 'mp', 'min_per', 'ortg', 'usg', 'ts', 'orb', 'drb', 'ast', 'to',
        'ftm', 'fta', 'ft', 'tpm', 'tpa', 'tp', 'twopa', 'blk', 'stl', 'ftr', 'porpag', 'ast_tov', 'rimm', 'rima', 'rim', 'dunkm', 'dunka',
        'dporpag', 'bpm', 'obpm', 'dbpm', 'treb_g', 'ast_g', 'pts_g', 'tpa100']


# Barttorvik's game rows (no header), in order
GCOLS = ['date', 'dtext', 'opstyle', 'quality', 'win1', 'opp', 'muid', 'win2', 'min', 'ortg', 'usg', 'efg', 'ts', 'orb', 'drb', 'ast',
         'to', 'dunkm', 'dunka', 'rimm', 'rima', 'midm', 'mida', 'twopm', 'twopa', 'tpm', 'tpa', 'ftm', 'fta', 'bpm_rd', 'obpm', 'dbpm',
         'bpm_net', 'pts', 'orb_n', 'drb_n', 'ast_n', 'tov', 'stl_n', 'blk_n', 'stl', 'blk', 'pf', 'poss', 'gbpm', 'sbpm', 'loc', 'team',
         'name', 'inches', 'cls', 'pid', 'year']
C = {k: i for i, k in enumerate(GCOLS)}
RECON = ['bpm', 'obpm', 'dbpm', 'porpag', 'dporpag', 'ortg']


def summed(rs, team_games):
    """a line to date from game rows: sums, rates weighted by the possessions they're rates of."""
    g = np.array([[r[C[k]] or 0 for k in ('min', 'poss', 'usg', 'ortg', 'to', 'orb', 'drb', 'ast', 'stl', 'blk', 'obpm', 'dbpm', 'gbpm')] for r in rs], float)
    mins, poss = g[:, 0], g[:, 1]
    on = mins / 40 * poss                       # team possessions while he was on the floor
    used = g[:, 2] / 100 * on                   # possessions he used
    wavg = lambda x, w: float((x * w).sum() / w.sum()) if w.sum() > 0 else 0.0
    s = lambda k: float(sum(r[C[k]] or 0 for r in rs))
    gp = sum(1 for r in rs if (r[C['min']] or 0) > 0)
    m = float(mins.sum())
    fga = s('twopa') + s('tpa')
    o = {'gp': gp, 'mp': m / max(1, gp), 'min_per': m / (40 * max(1, team_games)) * 100, 'usg': wavg(g[:, 2], on), 'ortg_g': wavg(g[:, 3], used),
         'to': wavg(g[:, 4], used), 'orb': wavg(g[:, 5], on), 'drb': wavg(g[:, 6], on), 'ast': wavg(g[:, 7], on), 'stl': wavg(g[:, 8], on),
         'blk': wavg(g[:, 9], on), 'ogb': wavg(g[:, 10], mins), 'dgb': wavg(g[:, 11], mins), 'gbpm': wavg(g[:, 12], mins),
         'ftm': s('ftm'), 'fta': s('fta'), 'tpm': s('tpm'), 'tpa': s('tpa'), 'twopm': s('twopm'), 'twopa': s('twopa'),
         'rimm': s('rimm'), 'rima': s('rima'), 'dunkm': s('dunkm'), 'dunka': s('dunka'), 'pts': s('pts'), 'on': float(on.sum())}
    o['ft'] = o['ftm'] / o['fta'] if o['fta'] else 0.0
    o['tp'] = o['tpm'] / o['tpa'] if o['tpa'] else 0.0
    o['ftr'] = o['fta'] / fga * 100 if fga else 0.0
    o['tpa100'] = o['tpa'] / o['on'] * 100 if o['on'] else 0.0
    o['rim'] = o['rimm'] / o['rima'] if o['rima'] else None
    o['pts_g'] = o['pts'] / max(1, gp); o['treb_g'] = (s('orb_n') + s('drb_n')) / max(1, gp); o['ast_g'] = s('ast_n') / max(1, gp)
    o['ts'] = o['pts'] / (2 * (fga + 0.44 * o['fta'])) * 100 if fga + o['fta'] else 0.0
    return o


def rx(o):
    """the regressors for the season-level numbers (BPM's box terms, PORPAG's ORtg x usage x minutes)."""
    u, r, mp = o['usg'], o['ortg_g'], o['min_per']
    return [1, o['ogb'], o['dgb'], u, r, o['to'], o['orb'], o['drb'], o['ast'], o['stl'], o['blk'], o['ftr'], o['tpa100'], o['tp'], o['ft'],
            (r - 88) * u / 100, (r - 88) * u * mp / 1e4, mp, o['ogb'] * mp / 100, o['dgb'] * mp / 100, o['stl'] * mp / 100,
            o['blk'] * mp / 100, o['drb'] * mp / 100]


def line(a, recon, meta):
    """a Barttorvik-shaped season line from a summed line."""
    x = np.array(rx(a))
    s = {k: v for k, v in a.items() if k in KEEP}
    for k in RECON: s[k] = float(x @ np.array(recon[k]['w']))
    for k in ('team', 'conf', 'yr', 'hti', 'role', 'rec', 'year'): s[k] = meta.get(k)
    return s


def next_career(cc, line, gp_full=None):
    """career cc (its last season the board season, still unplayed) with that season's line to date filled in and
    next season's board row after it: what next preseason's board would read if the season ended on this line."""
    *prev, srow = cc['seasons']
    s = dict(srow)
    for k in KEEP:
        if k in line and k not in ('year', 'yr', 'team', 'hti', 'rec'): s[k] = line[k]
    if line.get('role'): s['role'] = line['role']
    if line.get('conf'): s['conf'] = line['conf']
    if gp_full and s.get('gp'): s['gp'] = max(s['gp'], gp_full)
    nxt = {'year': s['year'] + 1, 'team': s['team'], 'conf': s.get('conf'), 'yr': NEXT_YR.get(s['yr'], 'Sr'), 'hti': s['hti'], 'rec': None, 'role': s.get('role')}
    return dict(cc, seasons=prev + [s, nxt])


def score(f, fit):
    """E[FV], P(NBA) and each driver's share for a feature dict, by the board's model (the same arithmetic as
    fetch_cbb.py's)."""
    m = fit['models']['newcomer' if f['newcomer'] else 'returner']
    mu, sd, W = np.array(m['mean']), np.array(m['sd']), [np.array(w) for w in m['w']]
    x = np.array([f.get(k) if f.get(k) is not None else np.nan for k in m['kept']], float)
    z = np.clip(np.nan_to_num((x - mu) / sd), -4, 4)
    top = m.get('topMean', F.TOP_MEAN)

    def ev(z):
        cs = [1 / (1 + math.exp(-max(-30, min(30, w[0] + w[1:] @ z)))) for w in W]
        ps = list(np.cumprod(cs))
        return ps[0], F.FLOOR + 10 * (ps[0] + ps[1] + ps[2]) + (top - 50) * ps[3]
    p, e = ev(z)
    parts = []
    for j, k in enumerate(m['kept']):
        z0 = z.copy(); z0[j] = 0
        parts.append((k, e - ev(z0)[1], x[j]))
    return e, p, parts


def score_many(fs, fit):
    """E[FV] and P(NBA) for many feature dicts at once (the backtest)."""
    e = np.zeros(len(fs)); p = np.zeros(len(fs))
    for grp in ('newcomer', 'returner'):
        ix = [i for i, f in enumerate(fs) if f['newcomer'] == (grp == 'newcomer')]
        if not ix: continue
        m = fit['models'][grp]
        X = np.array([[fs[i].get(k) if fs[i].get(k) is not None else np.nan for k in m['kept']] for i in ix], float)
        Z = np.clip(np.nan_to_num((X - np.array(m['mean'])) / np.array(m['sd'])), -4, 4)
        A = np.hstack([np.ones((len(Z), 1)), Z])
        P = np.cumprod(np.column_stack([1 / (1 + np.exp(-np.clip(A @ np.array(w), -30, 30))) for w in m['w']]), axis=1)
        e[ix] = F.FLOOR + 10 * (P[:, 0] + P[:, 1] + P[:, 2]) + (m.get('topMean', F.TOP_MEAN) - 50) * P[:, 3]
        p[ix] = P[:, 0]
    return e, p


def xbpm_of(f, fit):
    xb = fit['xbpm']['newcomer' if f['newcomer'] else 'returner']
    xx = np.array([f.get(k) if f.get(k) is not None else np.nan for k in xb['cols']], float)
    zz = np.clip(np.nan_to_num((xx - np.array(xb['mean'])) / np.array(xb['sd'])), -4, 4)
    return float(xb['w'][0] + np.array(xb['w'][1:]) @ zz)


def weight(n, k):
    return n / (n + k) if n and n > 0 else 0.0


# ---------------------------------------------------------------- the preseason board, frozen for the season
def pack(seasons):
    rnd = lambda v: round(v, 5) if isinstance(v, float) else v
    return [[rnd(s.get(k)) for k in KEEP] for s in seasons]


def write_prior(rows, cols, out):
    """fetch_cbb.py's hook: each board row with the career the model graded him on (data/cbb_prior.json)."""
    meta = []
    for r in rows:
        cc = r['cc']
        meta.append({'pid': r['c']['pid'] if r['c'] else None, 'key': r['p']['key'], 'bt': r['t'].get('bt'), 'dob': cc.get('dob'),
                     'rec': cc.get('rec'), 'seasons': pack(cc['seasons'])})
    import gzip
    with gzip.open(PRIOR, 'wt') as fh:
        json.dump({'asof': time.strftime('%Y-%m-%d'), 'season': SEASON, 'keep': KEEP, 'cols': cols, 'rows': out, 'careers': meta}, fh, separators=(',', ':'))


# ---------------------------------------------------------------- this season so far
def season_to_date(prior):
    """Barttorvik's 2026-27 lines and game logs. Returns {pid: line}, {(name key, team): pid}, {team: games played}.
    Only players with a game this season count: before the opener the 2026-27 file still carries last season's lines."""
    adv = os.path.join(D.CACHE, 'bt', f'adv{SEASON}.csv')
    gz = os.path.join(D.CACHE, 'games', f'{SEASON}.json.gz')
    if not OFFLINE:
        D.fetch(f'https://barttorvik.com/getadvstats.php?year={SEASON}&csv=1', adv, 1)
        D.fetch(f'https://barttorvik.com/{SEASON}_all_advgames.json.gz', gz, 1)
    try:
        import gzip
        games = json.load(gzip.open(gz))
    except Exception as e:
        # a missing file before the opener is expected; once games are on, a failed pull (Barttorvik's browser check,
        # an outage) fails the run so it shows in the Actions tab instead of leaving the board quietly stale
        if time.strftime('%Y-%m-%d') >= '2026-11-04':
            sys.exit(f'no 2026-27 game logs from Barttorvik ({e})')
        print('no game logs for this season yet:', e)
        return {}, {}, {}, None
    by_p, team_dates = defaultdict(list), defaultdict(set)
    for g in games:
        if g[C['year']] != SEASON: continue
        by_p[str(g[C['pid']])].append(g)
        team_dates[g[C['team']]].add((g[C['date']], g[C['muid']]))
    tg = {t: len(v) for t, v in team_dates.items()}
    last = max((g[C['date']] for g in games), default=None)
    official = {r['pid']: r for r in D.load_bt(SEASON)} if os.path.exists(adv) else {}
    recon = json.load(open(LIVE_FIT))['recon']
    lines, keys = {}, {}
    for pid, rs in by_p.items():
        rs.sort(key=lambda g: g[C['date']])
        team = rs[-1][C['team']]
        a = summed(rs, tg.get(team, 1))
        if a['mp'] * a['gp'] <= 0: continue
        o = official.get(pid)
        # Barttorvik's own line when it covers the same games (his two files update at their own times); else the
        # line rebuilt from the games (scripts/cbb_live_backtest.py's regression for BPM, PORPAG and ORtg)
        if o and o['gp'] and abs(o['gp'] - a['gp']) <= 1 and o['team'] == team:
            ln = {k: o.get(k) for k in KEEP}
        else:
            ln = line(a, recon, {'team': team, 'conf': o['conf'] if o else None, 'role': o['role'] if o else None})
        ln['n'] = a['mp'] * a['gp']
        ln['team_g'] = tg.get(team, 1)
        ln['name'] = rs[-1][C['name']]
        lines[pid] = ln
        keys[(D.norm(rs[-1][C['name']]), team)] = pid
    return lines, keys, tg, last


def show_line(L, season_label, seasons):
    return {'season': season_label, 'team': L['team'], 'gp': int(L['gp'] or 0), 'mpg': round(L['mp'] or 0, 1),
            'ppg': round(L['pts_g'] or 0, 1) if L.get('pts_g') is not None else None, 'rpg': round(L['treb_g'] or 0, 1) if L.get('treb_g') is not None else None,
            'apg': round(L['ast_g'] or 0, 1) if L.get('ast_g') is not None else None,
            'bpm': round(L['bpm'] or 0, 1), 'obpm': round(L['obpm'] or 0, 1), 'dbpm': round(L['dbpm'] or 0, 1),
            'ortg': round(L['ortg'] or 0, 1), 'usg': round(L['usg'] or 0, 1), 'ts': round(L['ts'] or 0, 1) if L.get('ts') is not None else None,
            'tp': round((L['tp'] or 0) * 100, 1), 'tpa': int(L['tpa'] or 0), 'ft': round((L['ft'] or 0) * 100, 1),
            'ast': round(L['ast'] or 0, 1), 'stl': round(L['stl'] or 0, 1), 'blk': round(L['blk'] or 0, 1), 'role': L.get('role'),
            'to': round(L['to'] or 0, 1), 'ftr': round(L['ftr'] or 0, 1), 'orb': round(L['orb'] or 0, 1),
            'prpg': round((L['porpag'] or 0) * (L['min_per'] or 0) / 100, 1), 'conf': L.get('conf'), 'seasons': seasons}


POWER = {'ACC', 'B10', 'B12', 'SEC', 'BE'}
PROV = ['ht', 'wt', 'bmi', 'wt_known', 'elig', 'age_cls', 'rg_lrk', 'power', 'team8', 'newcomer']
PROV_LABEL = {'ht': 'height', 'wt': 'weight', 'bmi': 'BMI', 'wt_known': 'weight listed', 'elig': 'class', 'age_cls': 'age for class',
              'rg_lrk': 'recruiting rank', 'power': 'power conference', 'team8': "team's top-8 FV", 'newcomer': 'newcomer'}


def inches(h):
    try:
        a, b = str(h).split('-'); return int(a) * 12 + int(b)
    except (ValueError, AttributeError):
        return None


def prov_fit(prior, ci, lam=5.0):
    """the provisional grade's drivers, calibrated on the board itself (the football board's ESPN backups, PR #268, are
    the template): a ridge of board FV less the 20 floor on what's known about a player with no D-I line to grade,
    among the board's low-information players (newcomers no recruiting service ranks, returners under 10% of minutes
    last season). Returns the model, its 5-fold R2 and the per-team inputs."""
    keep = prior['keep']
    team = defaultdict(list)
    for row in prior['rows']:
        team[row[ci['team']]].append(row[ci['fvx']])
    team8 = {t: float(np.mean(sorted(v, reverse=True)[:8])) for t, v in team.items()}
    X, y, ages = [], [], defaultdict(list)
    for row, m in zip(prior['rows'], prior['careers']):
        cc = {'pid': m['pid'], 'name': row[ci['name']], 'dob': m['dob'], 'rec': m['rec'], 'seasons': [dict(zip(keep, q)) for q in m['seasons']]}
        f = F.features(cc, len(cc['seasons']) - 1)
        last = cc['seasons'][-2] if len(cc['seasons']) > 1 else None
        if not ((f['newcomer'] and not f.get('rated')) or (last and (last.get('min_per') or 0) < 10)):
            continue
        ht = inches(row[ci['ht']]) or f.get('ht') or 77
        wt = row[ci['wt']]
        if row[ci['age']]: ages[row[ci['elig']]].append(row[ci['age']])
        X.append({'ht': ht, 'wt': wt, 'elig': row[ci['elig']] or 1, 'age': row[ci['age']] or row[ci['ageEst']], 'rg_lrk': f['rg_lrk'],
                  'power': 1.0 if row[ci['conf']] in POWER else 0.0, 'team8': team8[row[ci['team']]], 'newcomer': 1.0 if f['newcomer'] else 0.0})
        y.append(row[ci['fvx']] - F.FLOOR)
    age_cls = {k: float(np.median(v)) for k, v in ages.items()}
    raw = lambda d: [d['ht'], d['wt'] or np.nan, 703 * d['wt'] / d['ht'] ** 2 if d['wt'] else np.nan, 1.0 if d['wt'] else 0.0, d['elig'],
                     (d['age'] or age_cls.get(d['elig'], 20.0)) - age_cls.get(d['elig'], 20.0), d['rg_lrk'], d['power'], d['team8'], d['newcomer']]
    R = np.array([raw(d) for d in X], float); y = np.array(y)
    mu, sd = np.nanmean(R, 0), np.nanstd(R, 0); sd[sd == 0] = 1
    Z = lambda R: np.nan_to_num((R - mu) / sd)
    A = np.column_stack([np.ones(len(y)), Z(R)])
    I = np.eye(A.shape[1]) * lam; I[0, 0] = 0
    fold, pred = np.random.RandomState(0).randint(0, 5, len(y)), np.zeros(len(y))
    for k in range(5):
        tr = fold != k
        pred[~tr] = A[~tr] @ np.linalg.solve(A[tr].T @ A[tr] + I, A[tr].T @ y[tr])
    r2 = 1 - float(((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum())
    w = np.linalg.solve(A.T @ A + I, A.T @ y)
    return {'w': w, 'mu': mu, 'sd': sd, 'raw': raw, 'Z': Z, 'r2': r2, 'n': len(y), 'team8': team8, 'age_cls': age_cls}


def espn_sizes(team_ids):
    """weight and age from ESPN's current rosters (a player added after the preseason pull): name key -> (wt, age)"""
    import fetch_cbb as B
    out = {}
    for tid in team_ids:
        try:
            d = B.espn_get(f'{B.ESPN}/teams/{tid}/roster', os.path.join(D.CACHE, 'espn', 'live', f'r{tid}-{time.strftime("%Y%m%d")}.json'))
        except Exception:
            continue
        for a in d.get('athletes', []):
            out[(tid, D.norm(a.get('displayName') or a.get('fullName') or ''))] = (a.get('weight'), a.get('age'))
    return out


def unboarded(lines, used, prior, ci, fit, lf, full_games, season_label, emap):
    """players in this season's box scores the preseason board doesn't have (a walk-on, a mid-year arrival, a player
    ESPN's roster missed). Each starts at the 20 floor and takes the board-calibrated drivers we have on him (prov_fit:
    height, weight and BMI, class, age for class, Barttorvik's recruiting rank, conference, his team's top-8 FV): his
    provisional grade. As he plays, his line's grade by the board's own model (on the board's FV scale through emap,
    the boarded players' E[FV] -> FV) takes over by minutes, the same blend as everyone else. Placed on the board in FV
    order, but scored against it, never added to its pools, so no boarded player's grade moves. src 'bt'."""
    teams = {}
    for row, m in zip(prior['rows'], prior['careers']):
        if m.get('bt') and m['bt'] not in teams:
            teams[m['bt']] = (row[ci['team']], row[ci['logo']], row[ci['conf']])
    todo = [(pid, ln) for pid, ln in lines.items() if pid not in used and ln.get('n') and (ln.get('gp') or 0) >= 3 and ln['team'] in teams]
    if not todo:
        return []
    pf = prov_fit(prior, ci)
    tid = lambda logo: (re.search(r'/(\d+)\.png', logo or '') or [None, None])[1]
    sizes = espn_sizes({tid(teams[ln['team']][1]) for _, ln in todo} - {None})
    out = []
    for pid, ln in todo:
        tname, logo, conf = teams[ln['team']]
        yr = ln.get('yr') if ln.get('yr') in NEXT_YR else 'Fr'
        elig = {'Fr': 1, 'So': 2, 'Jr': 3, 'Sr': 4}.get(yr, 1)
        hti = int(ln.get('hti') or 77)
        wt, age = sizes.get((tid(logo), D.norm(ln['name'])), (None, None))
        bt = ln.get('rec')
        d = {'ht': hti, 'wt': wt, 'elig': elig, 'age': age, 'rg_lrk': -math.log(min(round((100 - bt) / 0.2) + 1, 500)) if bt else -math.log(600),
             'power': 1.0 if conf in POWER else 0.0, 'team8': pf['team8'].get(tname, 20.0), 'newcomer': 1.0}
        z = pf['Z'](np.array([pf['raw'](d)], float))[0]
        contrib = pf['w'][1:] * z
        pre = max(float(F.FLOOR), F.FLOOR + float(pf['w'][0] + contrib.sum()))
        # this season's line, graded by the board's model as next preseason's board would see it
        srow = {'year': SEASON, 'team': ln['team'], 'conf': ln.get('conf') or conf, 'yr': yr, 'hti': hti, 'rec': bt, 'role': None}
        cc = {'pid': pid, 'name': ln['name'], 'dob': None, 'rec': None, 'seasons': [srow]}
        grp = 'newcomer'
        proj = lf['now'][grp] == 'projected'
        gp_full = ln['gp'] * full_games / max(1, ln['team_g']) if proj and ln['team_g'] < full_games else None
        f_now = F.features(next_career(cc, ln, gp_full), 1)
        e1, p1, parts1 = score(f_now, fit)
        w = weight(ln['n'], lf['k'][grp])
        fvx = (1 - w) * pre + w * emap(e1)
        # each input's move above the 20 floor: the provisional drivers, then this season's line pulling toward its own grade
        nan = float('nan')
        parts = [('typical low-information player', float(pf['w'][0]), nan)]
        parts += [(PROV_LABEL[k], float(c), pf['raw'](d)[j]) for j, (k, c) in enumerate(zip(PROV, contrib)) if abs(c) >= 0.005]
        parts += [('this season', w * (emap(e1) - pre), nan)]
        kb = lf['kb'][grp]['k']
        xb0 = xbpm_of(F.features(cc, 0), fit)
        rate = (xb0 * kb + ln['bpm'] * ln['n']) / (kb + ln['n'])
        n_ros = (ln['mp'] or 0) * max(0.0, full_games - ln['team_g']) * min(1.0, ln['gp'] / max(1, ln['team_g']))
        row = [None] * len(prior['cols'])
        for c, v in (('name', ln['name']), ('team', tname), ('logo', logo), ('conf', conf), ('pos', 'G' if hti <= 76 else 'F' if hti <= 80 else 'C'),
                     ('cls', yr), ('elig', elig), ('ht', f'{hti // 12}-{hti % 12}'), ('wt', wt), ('age', age), ('new', 1),
                     ('links', {'bt': f"https://barttorvik.com/playerstat.php?year={SEASON}&p={ln['name'].replace(' ', '%20')}&t={ln['team'].replace(' ', '%20')}"})):
            if c in ci: row[ci[c]] = v
        out.append({'row': row, 'e': e1, 'p': w * p1, 'parts': parts, 'fvx': max(float(F.FLOOR), min(80.0, fvx)), 'prov': pre,
                    'xbpm': (ln['bpm'] * ln['n'] + rate * n_ros) / (ln['n'] + n_ros) if ln['n'] + n_ros > 0 else rate,
                    'w': w, 'f': f_now, 'cc': cc, 'now': show_line(ln, season_label, 0), 'src': 'bt'})
    print(f"{len(out)} players in this season's box scores are not on the preseason board: graded from the 20 floor "
          f"(drivers fit on {pf['n']} low-information board players, 5-fold R2 {pf['r2']:.3f}), then on their lines")
    return out


def main():
    import fetch_cbb as B
    import gzip
    prior = json.load(gzip.open(PRIOR))
    fit = json.load(open(F.OUT))
    lf = json.load(open(LIVE_FIT))
    F.VALIDITY = fit.get('validity', 1.0)
    keep = prior['keep']
    lines, keys, tg, last = season_to_date(prior)
    cols = prior['cols']
    ci = {c: j for j, c in enumerate(cols)}
    if not lines and not (fit.get('boards') or {}).get('keep'):
        print('no games yet this season: the board stays the preseason board')
        return
    full_games = lf.get('fullGames', 31.0)
    season_label = f'{SEASON - 1}-{str(SEASON)[2:]}'
    recs, used = [], set()
    for row, m in zip(prior['rows'], prior['careers']):
        cc = {'pid': m['pid'], 'name': row[ci['name']], 'dob': m['dob'], 'rec': m['rec'], 'seasons': [dict(zip(keep, s)) for s in m['seasons']]}
        i = len(cc['seasons']) - 1
        f_pre = F.features(cc, i)
        e0, p0, parts0 = score(f_pre, fit)
        xb0 = xbpm_of(f_pre, fit)
        pid = m['pid'] if m['pid'] in lines else keys.get((m['key'], m['bt']))
        if pid in used: pid = None          # two board rows can't share one Barttorvik player
        ln = lines.get(pid) if pid else None
        rec = {'row': list(row), 'e': e0, 'p': p0, 'parts': parts0, 'xbpm': xb0, 'w': 0.0, 'f': f_pre, 'cc': cc, 'now': None}
        if ln:
            used.add(pid)
            grp = 'newcomer' if f_pre['newcomer'] else 'returner'
            proj = lf['now'][grp] == 'projected'
            gp_full = ln['gp'] * full_games / max(1, ln['team_g']) if proj and ln['team_g'] < full_games else None
            cn = next_career(cc, ln, gp_full)
            f_now = F.features(cn, i + 1)
            e1, p1, parts1 = score(f_now, fit)
            w = weight(ln['n'], lf['k'][grp])
            mix = defaultdict(lambda: [0.0, None])
            for k, v, x in parts0: mix[k][0] += (1 - w) * v; mix[k][1] = x
            for k, v, x in parts1: mix[k][0] += w * v; mix[k][1] = x       # the driver's value now: this season's
            kb = lf['kb'][grp]['k']
            rate = (xb0 * kb + ln['bpm'] * ln['n']) / (kb + ln['n'])
            n_ros = (ln['mp'] or 0) * max(0.0, full_games - ln['team_g']) * min(1.0, ln['gp'] / max(1, ln['team_g']))
            rec.update(e=(1 - w) * e0 + w * e1, p=(1 - w) * p0 + w * p1, parts=[(k, v, x) for k, (v, x) in mix.items()],
                       xbpm=(ln['bpm'] * ln['n'] + rate * n_ros) / (ln['n'] + n_ros) if ln['n'] + n_ros > 0 else rate,
                       w=w, f=f_now if w >= 0.5 else f_pre, now=show_line(ln, season_label, len(cc['seasons'])))
        recs.append(rec)
    # the board stage: where the draft boards have him (cbb_fit.board_stage), on top of the blended E[FV]
    lrs = F.live_consensus([(r['row'][ci['name']], r['row'][ci['team']]) for r in recs])
    for r, lr in zip(recs, lrs):
        e2, p2 = F.board_e(r['e'], lr, fit.get('boards'))
        if p2 is None: continue
        r['parts'] = list(r['parts']) + [('boards', e2 - r['e'], lr if lr is not None else float('nan'))]
        r['e'], r['p'] = e2, p2
    sc = np.array([r['e'] for r in recs])
    fv, plus, fvx = F.grade(sc, {int(k): v for k, v in fit['cuts'].items()})
    for r, a, b, c in zip(recs, fv, plus, fvx): r['fv'], r['plus'], r['fvx'] = int(a), bool(b), round(float(c), 2)
    # the board's E[FV] -> FV, for players graded against it without joining it
    es = np.array([r['e'] for r in recs]); o = np.argsort(es)
    emap = lambda e: float(np.interp(e, es[o], fvx[o]))
    for r in unboarded(lines, used, prior, ci, fit, lf, full_games, season_label, emap):
        r['fv'], r['plus'], r['fvx'] = int(math.floor(r['fvx'] + 1e-9)), False, round(r['fvx'], 2)
        recs.append(r)
    recs.sort(key=lambda r: (-r['fvx'], -r['e']))
    posrk = Counter()
    out_cols = cols + ['now', 'w', 'src']
    out = []
    for k, r in enumerate(recs, 1):
        row = r['row']
        pos = row[ci['pos']]; posrk[pos] += 1
        L0 = row[ci['last']]
        L1 = r['now'] if r['now'] and r['w'] >= 0.5 else L0
        rep = B.report({'parts': r['parts'], 'cc': r['cc'], 'p': {'ht': row[ci['ht']], 'cls': row[ci['cls']], 'pos': pos}}, r['f'], L1 or r['now'])
        row[ci['ovr']], row[ci['posRank']], row[ci['fv']], row[ci['plus']], row[ci['fvx']] = k, posrk[pos], r['fv'], r['plus'], r['fvx']
        row[ci['nbaP']], row[ci['xbpm']] = round(r['p'], 4), round(r['xbpm'], 1)
        row[ci['parts']] = [[B.LABEL.get(k2, k2), round(float(v), 2), None if x is None or x != x else round(float(x), 3)] for k2, v, x in r['parts']]
        row[ci['report']] = rep
        out.append(row + [r['now'], round(r['w'], 3), r.get('src')])
    played = sum(1 for r in recs if r['now'])
    path = os.path.join(D.ROOT, 'static', 'data', 'cbb-all.json')
    body = json.dumps({'cols': out_cols, 'rows': out}, separators=(',', ':'))
    if os.path.exists(path) and open(path).read() == body:
        print('no new games: the board is unchanged'); return
    open(path, 'w').write(body)
    if not played:
        print('no games yet: the preseason board, regraded'); return
    # the in-season summary sits in its own file: data/cbb.json stays fetch_cbb.py's (preseason) and isn't rewritten daily
    tiers = Counter(r['fv'] for r in recs)
    json.dump({'asof': time.strftime('%Y-%m-%d'), 'through': f'{last[:4]}-{last[4:6]}-{last[6:]}' if last else None, 'played': played,
               'population': len(recs), 'tiers': {str(k): v for k, v in sorted(tiers.items(), reverse=True)},
               'top': [[o[ci['name']], o[ci['team']], o[ci['fv']]] for o in out[:30]], 'k': lf['k'], 'kb': {g: v['k'] for g, v in lf['kb'].items()},
               'now': lf['now'], 'byDate': lf['byDate'], 'careers': lf['careers'], 'seasons': lf['seasons']},
              open(os.path.join(D.ROOT, 'data', 'cbb_live.json'), 'w'), indent=1)
    print(f'{played} of {len(recs)} players have played; games through {last}')
    for o in out[:20]:
        print(f"{o[ci['ovr']]:3d} {o[ci['name']]:24s} {o[ci['team']]:18s} FV {o[ci['fv']]} w {o[-1]:.2f} NBA {o[ci['nbaP']]:.2f} xBPM {o[ci['xbpm']]}")


if __name__ == '__main__':
    main()
