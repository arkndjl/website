# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Award races for every sport page's awards tab: P(win) for each candidate, written to data/awards.json.

    python3 scripts/awards.py              # every sport
    python3 scripts/awards.py nba nhl      # some (the others keep their last race)

Each race simulates the rest of the season SIMS times and scores every simulated finish with the sport's voter model
(data/awards_fit.json from scripts/awards_research.py; only awards that passed their held-out test are run):
- team finish: the board's season odds (projected wins / points and their spread), drawn once a simulation per team
- player rates over the games left: the board's predictive value (NBA shrunk XPM, NHL pWAR a minute) and box rates
  blended with last season, each with its talent and sampling noise; games left from his share of games so far
- eligibility: the NBA's 65 games for MVP and DPOY
A candidate's P(win) is the voter model's softmax averaged over the simulations. Polymarket's price (no vig, display
only) sits beside it where a market is open. Stdlib only."""
import datetime as dt, json, math, os, random, re, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import awards_engine as E
import names as NM

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
FIT = os.path.join(ROOT, 'data', 'awards_fit.json')
OUT = os.path.join(ROOT, 'data', 'awards.json')
SIMS = 3000
SHOW = 20
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
POLY = {('nba', 'mvp'): 'nba-2026-27-mvp', ('nba', 'roy'): 'nba-2026-27-rookie-of-the-year-20260624161716143',
        ('nba', 'dpoy'): 'nba-2026-27-defensive-player-of-the-year',
        ('nhl', 'hart'): 'nhl-hart-memorial-trophy-winner-2026-27',
        ('nhl', 'norris'): 'nhl-james-norris-memorial-trophy-winner-2026-27',
        ('nhl', 'vezina'): 'nhl-vezina-trophy-winner-2026-27', ('nhl', 'calder'): 'nhl-2026-27-calder-trophy-20260625172243021',
        ('cfb', 'heisman'): 'ncaa-football-2026-heisman-award-winner-20260731185656435',
        ('nfl', 'mvp'): 'pro-football-2026-mvp-winner',
        ('nfl', 'opoy'): 'pro-football-2026-27-ap-offensive-player-of-the-year-winner',
        ('nfl', 'oroy'): 'pro-football-2026-27-ap-offensive-rookie-of-the-year-winner',
        ('cbb', 'wooden'): '2026-2027-naismith-college-player-of-the-year'}   # Naismith: no Wooden market


def jload(p, d=None):
    try: return json.load(open(p))
    except (OSError, ValueError): return d


def gauss(rng, m, s):
    return m + s * rng.gauss(0, 1) if s > 0 else m


# injuries over the games left: a Poisson count of new injuries (H a game) each costing a lognormal number of games
# (median MED, sigma 1: a fat tail of long absences), on top of the share of games he has played so far
INJ = {'nba': (.012, 4.0), 'nhl': (.008, 4.5), 'cbb': (.008, 2.5), 'cfb': (.03, 1.5), 'nfl': (.035, 1.5)}


def games_left(rng, left, share, sport):
    h, med = INJ[sport]
    out = 0.0
    lam = h * left
    k = 0
    L = math.exp(-lam); p = 1.0
    while True:                                                 # Poisson draw (Knuth; lam is small)
        p *= rng.random()
        if p <= L: break
        k += 1
    for _ in range(k): out += med * math.exp(rng.gauss(0, 1))
    avail = max(left - min(out, left), 0)
    return max(0, min(left, round(gauss(rng, avail * share, math.sqrt(max(avail * share * (1 - share), 0))))))


def team_draws(teams, rng):
    """{team: final win share} for one simulation; teams: {t: (wins now, games now, mean final wins, sd, games total)}"""
    out = {}
    for t, (w, g, xw, sd, G) in teams.items():
        left = max(G - g, 0)
        wr = min(max(gauss(rng, xw - w, sd), 0), left)
        out[t] = (w + wr) / max(G, 1)
    return out


def team_sd(left, p, rsd, per_pt):
    """spread of final wins: game-by-game luck plus the rating's uncertainty (rsd points x wins a point)"""
    return math.sqrt(left * p * (1 - p) + (left * per_pt * rsd) ** 2)


def race(cands, spec, draw, rng, sims=SIMS):
    """cands: list; draw(c, tdraw, rng) -> feature dict or None (not eligible). Returns P(win) per candidate."""
    cols, b, mu, sd = spec['cols'], spec['b'], spec['mu'], spec['sd']
    acc = [0.0] * len(cands)
    for _ in range(sims):
        td = draw.teams(rng)
        F = [draw(c, td, rng) for c in cands]
        idx = [i for i, f in enumerate(F) if f is not None]
        if not idx: continue
        p = E.prob([[F[i][k] for k in cols] for i in idx], b, mu, sd)
        for i, pi in zip(idx, p): acc[i] += pi
    return [a / sims for a in acc]


def prune(cands, spec, draw, rng, keep=45):
    """the voter model at a few draws to drop candidates with no chance, so the full simulation runs on a short list"""
    p = race(cands, spec, draw, rng, sims=60)
    order = sorted(range(len(cands)), key=lambda i: -p[i])
    return [cands[i] for i in order[:keep] if p[i] > 1e-5 or i == order[0]]


def rows_out(pool, p, draw, show, rng, n=200):
    """the top SHOW candidates with their mean projected finish on the shown stats"""
    top = sorted(zip(pool, p), key=lambda t: -t[1])[:SHOW]
    acc = {}
    for _ in range(n):
        td = draw.teams(rng)
        for c, _ in top:
            f = draw(c, td, rng)
            if f is None: continue
            for k, _, _ in show: acc.setdefault((c['id'], k), []).append(f[k])
    out = []
    for c, pi in top:
        x = {k: round(sum(acc[(c['id'], k)]) / len(acc[(c['id'], k)]), 3) for k, _, _ in show if acc.get((c['id'], k))}
        r = {'n': c['n'], 'tm': c['tm'], 'p': round(pi, 4), 'x': x}
        for k in ('ph', 'logo', 'cls', 'pos', 'war'):
            if c.get(k) is not None: r[k] = c[k]
        out.append(r)
    return out


# ---------------------------------------------------------------- markets

def poly(slug):
    """{name key: no-vig probability} from Polymarket's open event (gamma API; display only)"""
    if not slug: return {}
    try:
        u = 'https://gamma-api.polymarket.com/events?slug=' + slug
        d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': UA}), timeout=30).read())
        if not d: return {}
        out = {}
        for m in d[0].get('markets', []):
            if m.get('closed') or not m.get('active') or not m.get('acceptingOrders'): continue   # placeholders
            name = m.get('groupItemTitle') or re.sub(r'^Will (.*?) win.*$', r'\1', m.get('question', ''))
            if not name or name.lower() == 'other': continue
            try:
                bb, ba = m.get('bestBid'), m.get('bestAsk')
                if bb is None or ba is None or float(ba) - float(bb) > .10: continue      # no two-sided quote
                px = (float(bb) + float(ba)) / 2
            except (ValueError, IndexError, TypeError): continue
            if name and px > 0: out[name] = px
        t = sum(out.values())
        return {k: v / t for k, v in out.items()} if t > 0 else {}
    except Exception as e:
        print('polymarket', slug, e)
        return {}


def attach_market(rows, sport, award):
    m = poly(POLY.get((sport, award)))
    if not m: return False
    keys = [(n, NM.key(n)) for n in m]
    for r in rows:
        k = NM.key(r['n'])
        hit = next((m[n] for n, kk in keys if kk == k), None)
        if hit is None: hit = next((m[n] for n, kk in keys if NM.same(n, r['n'])), None)
        if hit is not None: r['mkt'] = round(hit, 4)
    return True


# ---------------------------------------------------------------- NBA

def nba(fit, rng):
    import awards_nba as A
    t = dt.date.today()
    S = t.year + 1 if t.month >= 10 else t.year
    X = A.xpm(S)
    if not X: return None
    seen = set()
    for s in range(A.FIRST, S): seen |= set(A.xpm(s))
    pg = A.per_game(S, fresh=True)
    pg0 = A.per_game(S - 1)
    G = jload(os.path.join(ROOT, 'data', 'nba_games.json'), {})
    E2B = {'SA': 'SAS', 'GS': 'GSW', 'NY': 'NYK', 'NO': 'NOP', 'UTAH': 'UTA', 'WSH': 'WAS', 'BKN': 'BRK', 'PHX': 'PHO', 'CHA': 'CHO'}
    teams, conf = {}, {}
    for p in G.get('power', []):
        w, l = (int(x) for x in p['rec'].split('-')[:2])
        g = w + l
        t = E2B.get(p['t'], p['t'])
        teams[t] = (w, g, p['wins'], team_sd(82 - g, p['wins'] / 82, p.get('rsd', 3), .030), 82)
        conf[t] = p.get('cname')
    TAU, TAUD, K = 2.05, 0.95, 600
    prev = fit.get('_prev', {})

    def teams_draw(rng):
        td = team_draws(teams, rng)
        best = {}
        for t, v in td.items():
            c = conf.get(t)
            if c and v > best.get(c, (-1, None))[0]: best[c] = (v, t)
        td['_seed1'] = {t for _, t in best.values()}
        return td

    cands = []
    for pid, r in X.items():
        p = pg.get(pid)
        if not p or r['tm'] not in teams and '/' not in r['tm']: continue
        tm = r['tm'].split('/')[-1]
        if tm not in teams: continue
        w, g, _, _, _ = teams[tm]
        q = pg0.get(pid, {})
        cands.append({'id': pid, 'n': r['n'], 'tm': tm, 'ph': r.get('ph'), 'g': p['games'], 'tg': g, 'mp': r['mp'],
                      'xpm': r['xpm'], 'dxpm': r['dxpm'], 'sx': r.get('sxpm', r['xpm']), 'sdx': r.get('sdxpm', r['dxpm']),
                      'ppg': p['pts_per_g'], 'ppg0': q.get('pts_per_g'), 'rpg': p['trb_per_g'], 'rpg0': q.get('trb_per_g'),
                      'st': p['stl_per_g'] + p['blk_per_g'],
                      'st0': (q.get('stl_per_g', 0) + q.get('blk_per_g', 0)) if q else None,
                      'mpg': p['mp_per_g'], 'pos': r.get('pos', ''), 'rookie': pid not in seen})

    def blend(now, g, prior, g0=15):
        return (now * g + (.85 * now if prior is None else prior) * g0) / (g + g0)   # no last season: toward 85%

    def draw(c, td, rng, elig65=False):
        left = 82 - c['tg']
        av = min((c['g'] + .9 * 8) / (c['tg'] + 8), 1.0)
        gr = games_left(rng, left, av, 'nba')
        gf = c['g'] + gr
        if elig65 and gf < 65: return None
        mr = gr * c['mpg']
        mp = c['mp'] + mr
        if mp <= 0: return None
        x_rest = gauss(rng, c['sx'], TAU * math.sqrt(K / (c['mp'] + K)) + (TAU * math.sqrt(K / mr) if mr > 0 else 0))
        d_rest = gauss(rng, c['sdx'], TAUD * math.sqrt(K / (c['mp'] + K)) + (TAUD * math.sqrt(K / mr) if mr > 0 else 0))
        xpm = (c['xpm'] * c['mp'] + x_rest * mr) / mp
        dx = (c['dxpm'] * c['mp'] + d_rest * mr) / mp
        pp_r = gauss(rng, blend(c['ppg'], c['g'], c['ppg0']), 2.5 * math.sqrt(15 / (c['g'] + 15)))
        ppg = (c['ppg'] * c['g'] + pp_r * gr) / max(gf, 1)
        rp = (c['rpg'] * c['g'] + gauss(rng, blend(c['rpg'], c['g'], c['rpg0']), .8) * gr) / max(gf, 1)
        st = (c['st'] * c['g'] + gauss(rng, blend(c['st'], c['g'], c['st0']), .3) * gr) / max(gf, 1)
        return {'vorx': .030 * (xpm + 1.4) * mp / 48, 'xpm': xpm, 'dxpm': dx, 'ppg': ppg, 'rpg': rp, 'stocks': st,
                'mpg': mp / max(gf, 1), 'big': 1.0 if c['pos'] in ('C', 'PF') else 0.0, 'wp': td[c['tm']],
                'seed1': 1.0 if c['tm'] in td['_seed1'] else 0.0, 'gfrac': gf / 82,
                'prev_mvp': prev.get('mvp', {}).get(c['id'], 0), 'prev_dpoy': prev.get('dpoy', {}).get(c['id'], 0)}

    out = []
    for aw, pool_f, elig, show in (
            ('mvp', lambda c: c['mpg'] >= 20, True, [('vorx', 'VORX', '%.1f'), ('ppg', 'PPG', '%.1f'), ('wp', 'W%', 'pct'), ('gfrac', 'G', 'g82')]),
            ('dpoy', lambda c: c['mpg'] >= 20, True, [('dxpm', 'D-XPM', '%+.1f'), ('stocks', 'STL+BLK', '%.1f'), ('rpg', 'RPG', '%.1f'), ('wp', 'W%', 'pct')]),
            ('roy', lambda c: c['rookie'] and c['mpg'] >= 10, False, [('vorx', 'VORX', '%.1f'), ('ppg', 'PPG', '%.1f'), ('mpg', 'MPG', '%.1f'), ('wp', 'W%', 'pct')])):
        spec = fit.get(aw)
        if not spec or not spec['test'].get('pass'): continue
        pool = [c for c in cands if pool_f(c)]
        dr = lambda c, td, rng, e=elig: draw(c, td, rng, e)
        dr.teams = teams_draw
        pool = prune(pool, spec, dr, rng)
        p = race(pool, spec, dr, rng)
        dm = lambda c, td, rng: draw(c, td, rng, False)
        dm.teams = teams_draw
        out.append((aw, rows_out(pool, p, dm, show, rng), show))
    return {'season': f'{S - 1}-{str(S)[2:]}', 'races': out, 'logo': 'nba'}


# ---------------------------------------------------------------- NHL

def nhl(fit, rng):
    import awards_nhl as A
    W = {}
    S = max(int(f[:4]) for f in os.listdir(A.WAR) if f[:4].isdigit())
    cur, last = A.war(S), {r['id']: r for r in A.war(S - 1)}
    G = jload(os.path.join(ROOT, 'data', 'nhl_games.json'), {})
    teams = {}
    for p in G.get('power', []):
        gp = p.get('gp', 0)
        left = 82 - gp
        # points: 2 a win plus the OT loss point; spread from game luck (about 1.0 points a game sd) and the rating
        teams[p['t']] = (p.get('pts', 0), gp * 2, p.get('xpts', 82.0), math.sqrt(left * 1.0 + (left * .25 * p.get('rsd', .2)) ** 2), 164)
    hist = {}
    for s in range(A.FIRST - 1, S):
        for r in A.war(s): hist.setdefault(NM.key(r['n']), []).append(r.get('gp') or 0)
    prev = fit.get('_prev', {})
    TG = {t: v[1] / 2 for t, v in teams.items()}
    cands = []
    for r in cur:
        tm = r['tm'].split('/')[-1]
        if tm not in teams: continue
        k = NM.key(r['n'])
        past = hist.get(k, [])
        rookie = (not any(g > 25 for g in past)) and sum(g > 6 for g in past[-2:]) < 2 and (r.get('age') or 30) < 26
        q = last.get(r['id'], {})
        gp = r.get('gp') or 0
        cands.append({'id': r['id'], 'n': r['n'], 'tm': tm, 'ph': r.get('ph'), 'grp': r['grp'], 'gp': gp, 'tg': TG[tm],
                      'toi': r.get('toi') or 0, 'war': r.get('war') or 0, 'pwar': r.get('pwar') or 0, 'gd': r.get('gd') or 0,
                      'pts': r.get('pts') or 0, 'g': r.get('g') or 0, 'gsax': r.get('gsax') or 0,
                      'ppg0': (q.get('pts') or 0) / q['gp'] if q.get('gp') else None,
                      'gpg0': (q.get('g') or 0) / q['gp'] if q.get('gp') else None,
                      'gsx0': (q.get('gsax') or 0) / max(q.get('toi') or 1, 1) * 60 if q.get('gp') else None,
                      'rookie': rookie, 'key': k})

    def draw(c, td, rng):
        left = max(82 - c['tg'], 0)
        if c['grp'] == 'G':
            share = min((c['gp'] + .55 * 6) / (c['tg'] + 6), 1.0)  # starts so far, toward a 1A's share
        else:
            share = min((c['gp'] + .95 * 6) / (c['tg'] + 6), 1.0)
        gr = games_left(rng, left, share, 'nhl')
        gp = c['gp'] + gr
        tpg = c['toi'] / max(c['gp'], 1)
        tr = gr * tpg
        rate = c['pwar'] / max(c['toi'], 1)                         # predictive WAR a minute
        war_r = gauss(rng, rate * tr, abs(rate) * tr * .35 + .25 * math.sqrt(tr / 60) * (.6 if c['grp'] != 'G' else 1.5))
        war = c['war'] + war_r
        # rates toward last season (no season: 80% of the pace so far), points by 40 games, goals 50, GSAx 40 starts
        bl = lambda now, prior, g0: (now * c['gp'] + (.8 * now if prior is None else prior) * g0) / (c['gp'] + g0)
        ppg = max(gauss(rng, bl(c['pts'] / max(c['gp'], 1), c['ppg0'], 40), .12), 0)     # talent sd .12 a game
        gpg = max(gauss(rng, bl(c['g'] / max(c['gp'], 1), c['gpg0'], 50), .06), 0)
        pts = c['pts'] + max(gauss(rng, ppg * gr, math.sqrt(max(ppg * gr, 0) * 1.3)), 0)
        g = c['g'] + max(gauss(rng, gpg * gr, math.sqrt(max(gpg * gr, 0) * 1.1)), 0)
        gs_rate = c['gsax'] / max(c['toi'], 1) * 60
        gs_rate = bl(gs_rate, c['gsx0'], 40) if c['gsx0'] is not None else gs_rate * c['gp'] / (c['gp'] + 40)
        gsax = c['gsax'] + gauss(rng, gs_rate * tr / 60, 1.4 * math.sqrt(max(tr / 60, 0)))   # 1.4 goals a game
        return {'war': war, 'pts': pts, 'g': g, 'gsax': gsax, 'gp': gp, 'gfrac': gp / 82, 'toipg': tpg,
                'tpct': td[c['tm']], 'goalie': 1.0 if c['grp'] == 'G' else 0.0, 'gd': c['gd'] * gp / max(c['gp'], 1),
                'prev_hart': prev.get('hart', {}).get(c['key'], 0), 'prev_norris': prev.get('norris', {}).get(c['key'], 0),
                'prev_vezina': prev.get('vezina', {}).get(c['key'], 0)}

    def teams_draw(rng):
        out = {}
        for t, (pts, g2, xp, sd, P) in teams.items():
            out[t] = min(max(gauss(rng, xp, sd), pts), pts + (P - g2)) / P
        return out

    draw.teams = teams_draw
    out = []
    for aw, pool_f, show in (
            ('hart', lambda c: c['gp'] >= 5, [('war', 'WAR', '%.1f'), ('pts', 'PTS', '%.0f'), ('tpct', 'PTS%', 'pct')]),
            ('norris', lambda c: c['grp'] == 'D' and c['gp'] >= 5, [('war', 'WAR', '%.1f'), ('pts', 'PTS', '%.0f'), ('toipg', 'TOI', 'toi'), ('tpct', 'PTS%', 'pct')]),
            ('vezina', lambda c: c['grp'] == 'G' and c['gp'] >= 3, [('gsax', 'GSAx', '%+.1f'), ('war', 'WAR', '%.1f'), ('gp', 'GP', '%.0f'), ('tpct', 'PTS%', 'pct')]),
            ('calder', lambda c: c['rookie'] and c['gp'] >= 3, [('war', 'WAR', '%.1f'), ('pts', 'PTS', '%.0f'), ('g', 'G', '%.0f'), ('tpct', 'PTS%', 'pct')])):
        spec = fit.get(aw)
        if not spec or not spec['test'].get('pass'): continue
        pool = prune([c for c in cands if pool_f(c)], spec, draw, rng)
        p = race(pool, spec, draw, rng)
        out.append((aw, rows_out(pool, p, draw, show, rng), show))
    return {'season': f'{S - 1}-{str(S)[2:]}', 'races': out, 'logo': 'nhl'}


# ---------------------------------------------------------------- CBB

def cbb(fit, rng):
    d = jload(os.path.join(ROOT, 'static', 'data', 'cbb-all.json'))
    G = jload(os.path.join(ROOT, 'data', 'cbb_games.json'), {})
    if not d or not G.get('power'): return None
    C = d['cols']
    teams, tinfo = {}, {}
    for p in G['power']:
        w, l = (int(x) for x in p['rec'].split('-')[:2])
        tot = round(p['xW'] + p['xL'])
        teams[p['t']] = (w, w + l, p['xW'], team_sd(tot - w - l, p['xW'] / max(tot, 1), p.get('rsd', 3), .03), tot)
        tinfo[p['t']] = (p['off'] - p['def'], p.get('rsd', 3) * 1.45, p.get('conf'))
    P5 = {'ACC', 'B10', 'B12', 'BE', 'SEC'}
    K, TAU = 300, 3.5
    cands = []
    for row in d['rows']:
        r = dict(zip(C, row))
        now = r.get('now') or {}
        if not now.get('gp') or r['team'] not in teams: continue
        last = r.get('last') or {}
        # priors: last season's line (any team) for returners; the board's projected BPM for newcomers
        prior = last['bpm'] if last.get('bpm') is not None and (last.get('gp') or 0) >= 8 else \
            next((x[2] for x in (r.get('parts') or []) if x[0] == 'BPM'), now['bpm'])
        pp0 = last['ppg'] if last.get('ppg') is not None and (last.get('gp') or 0) >= 8 else None
        espn = re.search(r'/id/(\d+)', (r.get('links') or {}).get('espn', '') or '')
        w, g, _, _, tot = teams[r['team']]
        cands.append({'id': r['name'] + '|' + r['team'], 'n': r['name'], 'tm': r['team'], 'logo': r.get('logo'),
                      'ph': espn.group(1) if espn else None, 'cls': r.get('cls'), 'gp': now['gp'], 'tg': g, 'tot': tot,
                      'mpg': now.get('mpg') or 0, 'ppg': now.get('ppg') or 0, 'bpm': now.get('bpm') or 0, 'prior': prior,
                      'pp0': pp0})

    def teams_draw(rng):
        td = team_draws(teams, rng)
        for t, (eff, sd, _) in tinfo.items():
            td['_b' + t] = 1 / (1 + math.exp(-gauss(rng, eff, sd) / 9.2))      # Barttorvik's barthag from efficiency
        return td

    def draw(c, td, rng):
        left = max(c['tot'] - c['tg'], 0)
        av = min((c['gp'] + .95 * 5) / (c['tg'] + 5), 1.0)
        gr = games_left(rng, left, av, 'cbb')
        gp = c['gp'] + gr
        m0, mr = c['gp'] * c['mpg'], gr * c['mpg']
        mean = (c['bpm'] * m0 + c['prior'] * K) / (m0 + K)
        b_rest = gauss(rng, mean, TAU * math.sqrt(K / (m0 + K)) + (TAU * math.sqrt(K / mr) if mr > 0 else 0))
        bpm = (c['bpm'] * m0 + b_rest * mr) / max(m0 + mr, 1)
        pp0 = c['pp0'] if c['pp0'] is not None else .6 * c['ppg'] + 4
        p_rest = gauss(rng, (c['ppg'] * c['gp'] + pp0 * 10) / (c['gp'] + 10), 3.0 * math.sqrt(10 / (c['gp'] + 10)))
        ppg = (c['ppg'] * c['gp'] + p_rest * gr) / max(gp, 1)
        return {'bpm': bpm, 'ppg': ppg, 'wp': td[c['tm']], 'barthag': td['_b' + c['tm']], 'mpg': c['mpg'],
                'p5': 1.0 if tinfo[c['tm']][2] in P5 else 0.0}

    draw.teams = teams_draw
    spec = fit.get('wooden')
    if not spec or not spec['test'].get('pass'): return None
    show = [('bpm', 'BPM', '%+.1f'), ('ppg', 'PPG', '%.1f'), ('wp', 'W%', 'pct')]
    pool = [c for c in cands if c['mpg'] >= 20]
    pool = prune(pool, spec, draw, rng, keep=60)
    p = race(pool, spec, draw, rng)
    return {'season': G.get('season', ''), 'races': [('wooden', rows_out(pool, p, draw, show, rng), show)], 'logo': 'cbb'}


# ---------------------------------------------------------------- football (ESPN season stats)

def espn_pool(lg, S):
    import awards_football as F
    import shutil
    live = os.path.join(F.CACHE, lg, str(S))
    stamp = os.path.join(live, '.day')
    today = dt.date.today().isoformat()
    if os.path.exists(live) and (not os.path.exists(stamp) or open(stamp).read() != today):
        shutil.rmtree(live)                                       # this season's lines change every week: refetch daily
        for f in os.listdir(os.path.join(F.CACHE, lg)):
            if f.startswith(f'lead_{S}_'): os.remove(os.path.join(F.CACHE, lg, f))
    pool = F.pull(lg, [S])
    pool = F.fix_teams(lg, {str(S): pool[S]})[str(S)]
    os.makedirs(live, exist_ok=True)
    open(stamp, 'w').write(today)
    return pool


def football_draw(teams, per_left, sport):
    def teams_draw(rng):
        return team_draws(teams, rng)

    def draw(c, td, rng):
        t = teams.get(c['tid'])
        if not t: return None
        w, g, xw, sd, G = t
        left = max(G - g, 0)
        gr = games_left(rng, left, .97, sport)
        f = dict(c['f'])
        gn = max(g, 1)
        for k, kind in per_left:
            rate = c['f'][k] / gn
            mu = rate * gr
            sdv = math.sqrt(max(mu, 0)) if kind == 'count' else .3 * mu
            f[k] = c['f'][k] + max(gauss(rng, mu, sdv), 0)
        if 'rush_y' in f and 'rush_y' in dict(per_left): f['scrim'] = f['rush_y'] + f['rec_y']
        if 'ptd' in f and 'ptd' in dict(per_left):
            f['td'] = c['f']['td'] + sum(f[k] - c['f'][k] for k in ('ptd', 'rtd', 'ctd'))
        if 'yds' in f and 'pass_y' in f: f['yds'] = f['pass_y'] + f['scrim']
        f['wp'] = td[c['tid']]
        return f
    draw.teams = teams_draw
    return draw


CFB_SHOW = {
    'heisman': [('yds', 'YDS', '%.0f'), ('td', 'TD', '%.0f'), ('int', 'INT', '%.0f'), ('wp', 'W%', 'pct')],
    'obrien': [('pass_y', 'YDS', '%.0f'), ('ptd', 'TD', '%.0f'), ('int', 'INT', '%.0f'), ('wp', 'W%', 'pct')],
    'doak': [('rush_y', 'YDS', '%.0f'), ('rtd', 'TD', '%.0f'), ('ypc', 'YPC', '%.1f'), ('wp', 'W%', 'pct')],
    'bilet': [('rec_y', 'YDS', '%.0f'), ('rec', 'REC', '%.0f'), ('ctd', 'TD', '%.0f'), ('wp', 'W%', 'pct')],
    'bednarik': [('sacks', 'SACK', '%.1f'), ('tfl', 'TFL', '%.1f'), ('dint', 'INT', '%.0f'), ('tackles', 'TKL', '%.0f')],
    'butkus': [('tackles', 'TKL', '%.0f'), ('tfl', 'TFL', '%.1f'), ('sacks', 'SACK', '%.1f'), ('dint', 'INT', '%.0f')],
    'thorpe': [('dint', 'INT', '%.0f'), ('pd', 'PD', '%.0f'), ('tackles', 'TKL', '%.0f'), ('wp', 'W%', 'pct')],
    'groza': [('fgm', 'FGM', '%.0f'), ('fgpct', 'FG%', 'pct'), ('long', 'LNG', '%.0f'), ('wp', 'W%', 'pct')],
    'guy': [('gross', 'AVG', '%.1f'), ('net', 'NET', '%.1f'), ('in20', 'IN20', '%.0f'), ('punts', 'PUNTS', '%.0f')]}
for _a, _b in (('maxwell', 'heisman'), ('camp', 'heisman'), ('mackey', 'bilet'), ('nagurski', 'bednarik')):
    CFB_SHOW[_a] = CFB_SHOW[_b]
CFB_LEFT = [('pass_y', 'yds'), ('rush_y', 'yds'), ('rec_y', 'yds'), ('ptd', 'count'), ('rtd', 'count'), ('ctd', 'count'),
            ('int', 'count'), ('rec', 'count'), ('sacks', 'count'), ('dint', 'count'), ('tackles', 'yds'),
            ('tfl', 'count'), ('pd', 'count'), ('ff', 'count'), ('itd', 'count'), ('fgm', 'count'), ('fga', 'count'),
            ('fg50', 'count'), ('punts', 'count'), ('in20', 'count')]


def cfb(fit, rng):
    """the Heisman and every other modelled CFB award that passed its held-out test"""
    import awards_football as F
    M = jload(os.path.join(ROOT, 'data', 'cfb_model.json'), {})
    if not M.get('sim'): return None
    S = int(str(M.get('asof', dt.date.today().isoformat()))[:4])
    keys = [a for a in ['heisman'] + list(F.CFB_AWARDS) if fit.get(a, {}).get('test', {}).get('pass')]
    if not keys: return None
    teams, logos = {}, {}
    for t in M['sim']:
        w, l = (int(x) for x in t['rec'].split('-')[:2])
        G = w + l + t.get('left', 0)
        teams[t['tid']] = (w, w + l, t['projW'], math.sqrt(t.get('left', 0) * .22), G)
        logos[t['tid']] = (t.get('team'), t.get('logo'))
    pool = espn_pool('cfb', S)
    top5 = {NM.key(n) for n, _, _, _ in F.heisman_votes(S - 1)[:5]}
    cands = []
    for v in pool.values():
        f = F.features(v)
        if f['tid'] not in teams: continue
        f['prev_top5'] = 1.0 if NM.key(f['n']) in top5 else 0.0
        nm, logo = logos[f['tid']]
        cands.append({'id': v['id'], 'n': v['n'], 'tid': f['tid'], 'tm': nm, 'logo': logo, 'pos': f['pos'], 'ph': v['id'], 'f': f})
    for c in cands:                      # the pool rules use season-end thresholds: test them on full-season pace
        w, g, _, _, G = teams[c['tid']]
        k = G / max(g, 1)
        c['pf'] = dict(c['f'], **{x: c['f'][x] * k for x, _ in CFB_LEFT}, yds=c['f']['yds'] * k)
    draw = football_draw(teams, CFB_LEFT, 'cfb')
    big = lambda f: f['yds'] >= 300 or f['tackles'] >= 25 or f['sacks'] >= 4 or f['dint'] >= 3
    races = []
    for a in keys:
        spec = fit[a]
        if a == 'heisman': ok = big
        else:
            elig = F.CFB_AWARDS[a][2]
            ok = (lambda f, e=elig: e(f) and big(f)) if a in ('maxwell', 'camp') else elig
        sub = [c for c in cands if ok(c['pf'])]
        if not sub: continue
        sub = prune(sub, spec, draw, rng)
        p = race(sub, spec, draw, rng)
        races.append((a, rows_out(sub, p, draw, CFB_SHOW[a], rng), CFB_SHOW[a]))
    return {'season': str(S), 'races': races, 'logo': 'cfb'}


def nfl(fit, rng):
    import awards_football as F
    G = jload(os.path.join(ROOT, 'data', 'nfl_games.json'), {})
    if not G.get('power'): return None
    S = int(G.get('season'))
    tmap = {}
    try:
        u = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams'
        d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': UA}), timeout=30).read())
        for t in d['sports'][0]['leagues'][0]['teams']: tmap[t['team']['id']] = t['team']['abbreviation']
    except Exception as e:
        print('espn nfl teams', e); return None
    pw = {p['t']: p for p in G['power']}
    teams = {}
    for tid, ab in tmap.items():
        p = pw.get(ab)
        if not p: continue
        w, l = (int(x) for x in p['rec'].split('-')[:2])
        teams[tid] = (w, w + l, p['wins'], team_sd(17 - w - l, p['wins'] / 17, p.get('rsd', 3), .03), 17)
    prev = fit.get('_prev', {})
    war = {NM.key(r['n']): r for r in (jload(os.path.join(ROOT, 'data', 'nfl_war.json'), {}) or {}).get('players', [])}
    pool = espn_pool('nfl', S)
    cands = []
    for v in pool.values():
        f = F.features(v)
        if f['tid'] not in teams: continue
        f['prev_mvp'] = prev.get('mvp', {}).get(NM.key(f['n']), 0)
        f['rookie'] = f['debut'] == S
        wr = war.get(NM.key(f['n']), {})
        cands.append({'id': v['id'], 'n': v['n'], 'tid': f['tid'], 'tm': tmap[f['tid']], 'pos': f['pos'], 'ph': v['id'],
                      'war': wr.get('war'), 'f': f})
    draw = football_draw(teams, [('pass_y', 'yds'), ('scrim', 'yds'), ('td', 'count'), ('int', 'count'),
                                 ('sacks', 'count'), ('dint', 'count'), ('tfl', 'count'), ('pd', 'count'), ('ff', 'count')], 'nfl')
    out = []
    for aw, pool_f, show in (
            ('mvp', lambda c: not c['f']['def'], [('yds', 'YDS', '%.0f'), ('td', 'TD', '%.0f'), ('int', 'INT', '%.0f'), ('wp', 'W%', 'pct')]),
            ('opoy', lambda c: not c['f']['def'], [('pass_y', 'PASS', '%.0f'), ('scrim', 'SCRIM', '%.0f'), ('td', 'TD', '%.0f'), ('wp', 'W%', 'pct')]),
            ('dpoy', lambda c: c['f']['def'], [('sacks', 'SCK', '%.1f'), ('dint', 'INT', '%.0f'), ('tfl', 'TFL', '%.0f'), ('wp', 'W%', 'pct')]),
            ('oroy', lambda c: not c['f']['def'] and c['f']['rookie'], [('yds', 'YDS', '%.0f'), ('td', 'TD', '%.0f'), ('wp', 'W%', 'pct')])):
        spec = fit.get(aw)
        if not spec or not spec['test'].get('pass'): continue
        pl = prune([c for c in cands if pool_f(c)], spec, draw, rng)
        p = race(pl, spec, draw, rng)
        out.append((aw, rows_out(pl, p, draw, show, rng), show))
    return {'season': str(S), 'races': out, 'logo': 'nfl'}


# ---------------------------------------------------------------- output

NULL_LABEL = {'vorx': 'VORX', 'dxpm': 'D-XPM', 'war': 'WAR', 'gsax': 'GSAx', 'bpm': 'BPM', 'yds': 'yards',
              'td': 'TDs', 'sacks': 'sacks', 'dint': 'INTs', 'pass_y': 'pass yards', 'ptd': 'pass TDs', 'gross': 'gross average',
              'rush_y': 'rush yards', 'rtd': 'rush TDs', 'rec_y': 'receiving yards', 'ctd': 'receiving TDs', 'tackles': 'tackles',
              'fgm': 'FGs', 'fgpct': 'FG%', 'pd': 'PDs'}
BUILD = {'nba': nba, 'nhl': nhl, 'cbb': cbb, 'cfb': cfb, 'nfl': nfl}


def main(argv):
    fit = jload(FIT, {})
    cur = jload(OUT, {}) or {}
    want = [a for a in argv if a in BUILD] or list(BUILD)
    rng = random.Random(20261114)
    for sp in want:
        if sp not in fit: continue
        try:
            res = BUILD[sp](fit[sp], rng)
        except Exception as e:
            import traceback; traceback.print_exc()
            print(sp, 'failed, keeping the last race:', e); continue
        if not res or not res['races']: continue
        races = []
        for aw, rows, show in res['races']:
            spec = fit[sp][aw]
            mk = attach_market(rows, sp, aw)
            t = spec['test']
            races.append({'key': aw, 'label': spec['label'], 'rows': rows, 'mkt': mk,
                          'show': [{'k': k, 'l': l, 'f': f} for k, l, f in show],
                          'test': {'n': t['model']['n'], 'hit': t['model']['hit'], 'hit0': t['null']['hit'],
                                   'pw': t['model']['pw'], 'll': t['model']['ll'], 'll0': t['null']['ll'], 't': t['t'],
                                   'from': spec['seasons'][0], 'to': spec['seasons'][1],
                                   'null': [NULL_LABEL.get(c, c) for c in spec['null']]}})
            top = rows[0] if rows else {}
            print(sp, spec['label'], 'top:', ', '.join(f"{r['n']} {r['p']:.0%}" + (f" (mkt {r['mkt']:.0%})" if 'mkt' in r else '') for r in rows[:5]))
        cur[sp] = {'season': res['season'], 'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                   'sims': SIMS, 'logo': res['logo'], 'races': races}
    json.dump(cur, open(OUT, 'w'), indent=1, sort_keys=True)
    print('wrote', OUT)


if __name__ == '__main__':
    main(sys.argv[1:])
