# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Award races for every sport page's awards tab: P(win) for each candidate, written to data/awards.json.

    python3 scripts/awards.py              # every sport
    python3 scripts/awards.py nba nhl      # some (the others keep their last race)

Each race simulates the rest of the season SIMS times and scores every simulated finish with the sport's voter model
(data/awards_fit.json from scripts/awards_research.py; only awards that passed their held-out test are run):
- team finish: the board's season odds (projected wins / points and their spread), drawn once a simulation per team
- player rates over the games left: the board's predictive value (NBA shrunk XPM, NHL Marcel WAR a minute) and box rates
  blended with last season, each with its talent and sampling noise; games left from his share of games so far
- eligibility: the NBA's 65 games for MVP and DPOY
A candidate's P(win) is the voter model's softmax averaged over the simulations. Where Polymarket has an open, liquid
market for the award the shown P(win) is the log-linear blend model^(1 - w) x market^w, w = MKT_W (Noah, Nov 19 2026:
on the 2025-26 races the model's winner log loss was 2.32 against the market's 1.12, the blend 1.13 at w .95, t -2.26
by race; scripts/research/sweep_nov19/markets/a1_award_market.py). The model's own number stays on the row (pm) and
the market's (mkt, no vig) beside it.

Two views a sport (Noah, Nov 20 2026): "races" = predictive (who the voters will pick, above); "conv" = conviction (who
leads the award's pool on this season's value alone: P(lead), no voter model and no market; lead()). Noah, Nov 20:
conviction rests on SV / SVAR, nothing that leans on other seasons. So its draws run the games left at this season's
own rates (SEASON_ONLY: no last-season blend, no shrunk or predictive rate), and football's pools are the SV boards
(war_lead: SVAR by position; covers awards whose voter model failed, leaves out positions with no SV). Soccer's pool
is the season's best by SVAR (scripts/soccer_sv.py: GAR rebuilt from this season alone), run out at this season's rate
a match. Stdlib only."""
import datetime as dt, json, math, os, random, re, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import awards_engine as E
import names as NM

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
FIT = os.path.join(ROOT, 'data', 'awards_fit.json')
OUT = os.path.join(ROOT, 'data', 'awards.json')
TEMP = os.path.join(ROOT, 'data', 'awards_temp.json')
SIMS = 3000
PACE_GP = False          # football: rest-of-season rate per game the player appeared in (False = per team game)
LEFT_K = 0               # football: games of the player's last-season rate the rest-of-season rate is shrunk with (c['prev']; 0 = raw)
AV_ACT = 0.0             # availability floor of a candidate who is playing now (0 = off)
MKT_W = 0.95             # the market's weight in the shown P(win) (log-linear blend), where a liquid market is open
# a liquid market: this many two-sided quotes, raw prices summing inside this range (the test's rule), and this much
# traded on the event (thin books quote the field near flat and leave the favourite without a two-sided price)
MKT_MIN, MKT_SUM, MKT_VOL = 3, (0.75, 1.25), 50000
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
INJ = {'nba': (.012, 4.0), 'nhl': (.008, 4.5), 'cbb': (.008, 2.5), 'cfb': (.03, 1.5), 'nfl': (.035, 1.5), 'soccer': (.012, 3.0)}


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


def race_k(cands, spec, draw, rng, k, sims=SIMS):
    """a top-k race (k named): P(named) per candidate = the share of simulations in which he is in a Plackett-Luce
    draw of k from the voter utilities of the simulated finish (the k largest of utility + Gumbel noise)"""
    cols, b, mu, sd = spec['cols'], spec['b'], spec['mu'], spec['sd']
    acc = [0] * len(cands)
    for _ in range(sims):
        td = draw.teams(rng)
        z = []
        for i, c in enumerate(cands):
            f = draw(c, td, rng)
            if f is None: continue
            u = sum(bk * ((f[x] - m) / v) for bk, x, m, v in zip(b, cols, mu, sd))
            z.append((u - math.log(-math.log(max(rng.random(), 1e-300))), i))
        z.sort(reverse=True)
        for _, i in z[:k]: acc[i] += 1
    return [a / sims for a in acc]


def temper(p, T):
    """the in-season temperature: p_i ^ (1 / T), renormalised (scripts/awards_asof.py fits T's slope a sport)"""
    if not T or abs(T - 1) < 1e-9: return p
    q = [max(v, 1e-300) ** (1 / T) for v in p]
    t = sum(q)
    return [v / t for v in q]


def season_T(sport, share):
    """T = 1 + a x (1 - share of the season played); a = 0 where the as-of backtest did not pass"""
    a = ((jload(TEMP, {}) or {}).get(sport) or {}).get('a') or 0.0
    return 1 + a * (1 - min(max(share, 0.0), 1.0))


def prune(cands, spec, draw, rng, keep=45):
    """the voter model at a few draws to drop candidates with no chance, so the full simulation runs on a short list"""
    p = race(cands, spec, draw, rng, sims=60)
    order = sorted(range(len(cands)), key=lambda i: -p[i])
    return [cands[i] for i in order[:keep] if p[i] > 1e-5 or i == order[0]]


CONV = None             # main sets {}: each race function then records its conviction race here (award -> Rows)
SEASON_ONLY = False     # on inside lead(): the draws run the games left at this season's own rates (no last season,
                        # no predictive or shrunk rate), so conviction rests on this season's value alone


def lead(aw, pool, draw, metric, show, rng, k=1, sims=SIMS, keep=60, top=SHOW):
    """the conviction race: P(lead) = the share of simulations in which the candidate leads the award's eligible pool
    (is in its top k) on our own value metric, from the same simulated finishes as the voter race. No voter model, no
    market. The pool is cut to the `keep` best by mean metric at a few draws first. Recorded in CONV[aw]."""
    if CONV is None or not pool: return
    global SEASON_ONLY
    SEASON_ONLY = True
    try: _lead(aw, pool, draw, metric, show, rng, k, sims, keep, top)
    finally: SEASON_ONLY = False


def _lead(aw, pool, draw, metric, show, rng, k, sims, keep, top):
    acc = {}
    for _ in range(40):
        td = draw.teams(rng)
        for i, c in enumerate(pool):
            f = draw(c, td, rng)
            if f is not None: acc.setdefault(i, []).append(f[metric])
    order = sorted(acc, key=lambda i: -sum(acc[i]) / len(acc[i]))[:max(keep, 4 * k)]
    cands = [pool[i] for i in order]
    win = [0] * len(cands)
    tot = [[0.0] * len(show) for _ in cands]
    cnt = [0] * len(cands)
    for _ in range(sims):
        td = draw.teams(rng)
        z = []
        for i, c in enumerate(cands):
            f = draw(c, td, rng)
            if f is None: continue
            z.append((f[metric], i))
            cnt[i] += 1
            for j, (x, _, _) in enumerate(show): tot[i][j] += f[x]
        z.sort(reverse=True)
        for _, i in z[:k]: win[i] += 1
    out = []
    for i, c in enumerate(cands):
        r = bare(c, win[i] / sims)
        if cnt[i]: r['x'] = {x: round(tot[i][j] / cnt[i], 3) for j, (x, _, _) in enumerate(show)}
        out.append(r)
    out.sort(key=lambda r: (-r['p'], -(r['x'].get(metric) or -1e9)))
    rows = Rows(out[:top if k == 1 else max(top, 2 * k)])
    rows.rest = out[len(rows):]
    rows.show, rows.metric = show, metric
    if k > 1: rows.k = k
    CONV[aw] = rows


def first(show, metric):
    """the shown stats with the conviction metric first"""
    return [t for t in show if t[0] == metric] + [t for t in show if t[0] != metric]


class Rows(list):
    """the shown rows; rest = the pool's other candidates as full rows, for a market name below the cut"""
    rest = ()


ROSTER = {}              # sport -> every candidate line of the build (name, team, position, photo), for market names


def bare(c, p=0.0):
    r = {'n': c['n'], 'tm': c['tm'], 'p': round(p, 4), 'x': {}}
    for k in ('ph', 'phu', 'logo', 'cls', 'pos', 'war'):
        if c.get(k) is not None: r[k] = c[k]
    return r


def board(sport):
    """the site's own board lines for the sport as candidate lines (name, team, position, photo): where a market name
    that the award's stat pool does not hold is looked up"""
    if sport in board.c: return board.c[sport]
    import glob
    out = []
    try:
        if sport == 'nfl':
            for r in jload(os.path.join(ROOT, 'static', 'data', 'nfl-war.json'), {}).get('players', []):
                out.append({'n': r['n'], 'tm': NFLV_TEAM.get(r['tm'], r['tm']), 'pos': r.get('pos'),
                            'phu': 'https://static.www.nfl.com/image/upload/f_auto,q_auto,w_96/league/' + r['ph'] if r.get('ph') else None})
        elif sport == 'nhl':
            fs = sorted(glob.glob(os.path.join(ROOT, 'static', 'data', 'nhl-war', '*.json')))
            for r in (jload(fs[-1], {}) if fs else {}).get('players', []):
                out.append({'n': r['n'], 'tm': r['tm'].split('/')[-1], 'pos': r.get('pos'), 'ph': r.get('ph')})
            H = jload(os.path.join(ROOT, 'data', 'hockey.json'), {})
            for r in H.get('pipe', []) + H.get('board', []):
                if r.get('name') and r.get('team'): out.append({'n': r['name'], 'tm': r['team'], 'pos': r.get('pos')})
        elif sport == 'cfb':
            d = jload(os.path.join(ROOT, 'static', 'data', 'cfb-all.json'), {})
            ix = {c: i for i, c in enumerate(d.get('cols', []))}
            for r in d.get('rows', []):
                m = re.search(r'/id/(\d+)', r[ix['espnl']] or '')
                out.append({'n': r[ix['name']], 'tm': r[ix['team']], 'logo': r[ix['logo']], 'pos': r[ix['pos']],
                            'ph': m.group(1) if m else None})
    except Exception as e:
        print('board lines', sport, e)
    board.c[sport] = [r for r in out if r.get('n') and r.get('tm')]
    return board.c[sport]


board.c = {}


def rows_out(pool, p, draw, show, rng, n=200, top=SHOW):
    """the top candidates with their mean projected finish on the shown stats"""
    order = sorted(zip(pool, p), key=lambda t: -t[1])
    acc = {}
    for _ in range(n):
        td = draw.teams(rng)
        for c, _ in order:
            f = draw(c, td, rng)
            if f is None: continue
            for k, _, _ in show: acc.setdefault((c['id'], k), []).append(f[k])
    out = []
    for c, pi in order:
        r = bare(c, pi)
        r['x'] = {k: round(sum(acc[(c['id'], k)]) / len(acc[(c['id'], k)]), 3) for k, _, _ in show if acc.get((c['id'], k))}
        out.append(r)
    rows = Rows(out[:top])
    rows.rest = out[top:]
    return rows


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
        poly.raw = (len(out), t, float(d[0].get('volume') or 0))
        return {k: v / t for k, v in out.items()} if t > 0 else {}
    except Exception as e:
        print('polymarket', slug, e)
        return {}


def find(name, rows):
    """the row of rows that is this market name (shared matcher), or None"""
    k = NM.key(name)
    return next((r for r in rows if NM.key(r['n']) == k), None) or next((r for r in rows if NM.same(name, r['n'])), None)


def blend(rows, m, w=None, sport=None):
    """the shown P(win): model^(1 - w) x market^w over the union of candidates, renormalised (the tested form, B1).
    A model row with no market price takes the smallest listed price split across such rows. A market name outside
    the shown rows joins as the pool's own row for him (below the cut), else as his line from the build's candidates
    or the site's board at model 1e-3 (mo); a name the build has no player for is left out. Rows are re-sorted; each keeps its model
    number as pm."""
    w = MKT_W if w is None else w
    lo = min(m.values())
    un = sum(1 for r in rows if 'mkt' not in r)
    used = {r['_mk'] for r in rows if '_mk' in r}
    rest, have = list(getattr(rows, 'rest', ())), {NM.key(r['n']) for r in rows}
    for n, v in m.items():
        if n in used: continue
        r = find(n, rest)
        if r is None:
            c = find(n, ROSTER.get(sport, [])) or find(n, board(sport))
            if c is None: print('  market name with no player on the build, left out:', n, round(v, 4)); continue
            r = dict(bare(c, 1e-3), mo=True)
        if NM.key(r['n']) in have: continue
        have.add(NM.key(r['n']))
        rows.append(dict(r, mkt=round(v, 4)))
    z = [max(r['p'], 1e-6) ** (1 - w) * max(r.get('mkt') or lo / max(un, 1), 1e-6) ** w for r in rows]
    t = sum(z)
    for r, v in zip(rows, z):
        r['pm'] = None if r.get('mo') else r['p']
        r['p'] = round(v / t, 4)
    rows.sort(key=lambda r: -r['p'])
    rows[:] = [r for r in rows if not (r.get('mo') and r['p'] < 0.005)]


def attach_market(rows, sport, award):
    """the market's price on each row (mkt); True when the market is liquid enough to blend (then the rows are blended)"""
    poly.raw = (0, 0.0, 0.0)
    m = poly(POLY.get((sport, award)))
    if not m: return False, False
    for n in m:
        r = find(n, [r for r in rows if '_mk' not in r])
        if r is not None: r['mkt'] = round(m[n], 4); r['_mk'] = n
    n, t, vol = poly.raw
    liquid = n >= MKT_MIN and MKT_SUM[0] <= t <= MKT_SUM[1] and vol >= MKT_VOL
    if liquid: blend(rows, m, sport=sport)
    for r in rows: r.pop('_mk', None)
    return True, liquid


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
    X0 = A.xpm(S - 1)
    G = jload(os.path.join(ROOT, 'data', 'nba_games.json'), {})
    E2B = {'SA': 'SAS', 'GS': 'GSW', 'NY': 'NYK', 'NO': 'NOP', 'UTAH': 'UTA', 'WSH': 'WAS', 'BKN': 'BRK', 'PHX': 'PHO', 'CHA': 'CHO'}
    teams, conf = {}, {}
    for p in G.get('power', []):
        w, l = (int(x) for x in p['rec'].split('-')[:2])
        g = w + l
        t = E2B.get(p['t'], p['t'])
        teams[t] = (w, g, p['wins'], team_sd(82 - g, p['wins'] / 82, p.get('rsd', 3), .030), 82)
        conf[t] = p.get('cname')
    cands = []
    for pid, r in X.items():
        p = pg.get(pid)
        if not p or r['tm'] not in teams and '/' not in r['tm']: continue
        tm = r['tm'].split('/')[-1]
        if tm not in teams: continue
        w, g, _, _, _ = teams[tm]
        q = pg0.get(pid, {})
        cands.append({'id': pid, 'n': r['n'], 'tm': tm, 'ph': r.get('ph'), 'g': p['games'], 'tg': g, 'mp': r['mp'],
                      'xpm': r['xpm'], 'dxpm': r['dxpm'], 'ta': r.get('txpm', r['xpm']) - r['xpm'], 'tad': r.get('tdxpm', r['dxpm']) - r['dxpm'],
                      'pre_rvorx': (X0.get(pid) or {}).get('vorx') or 0.0, 'sx': r.get('sx0', r['xpm']), 'sdx': r.get('sdx0', r['dxpm']),
                      'ppg': p['pts_per_g'], 'ppg0': q.get('pts_per_g'), 'rpg': p['trb_per_g'], 'rpg0': q.get('trb_per_g'),
                      'apg': p['ast_per_g'], 'apg0': q.get('ast_per_g'), 'st': p['stl_per_g'] + p['blk_per_g'],
                      'st0': (q.get('stl_per_g', 0) + q.get('blk_per_g', 0)) if q else None,
                      'mpg': p['mp_per_g'], 'pos': r.get('pos', ''), 'rookie': pid not in seen,
                      'gs': p.get('games_started', 0), 'has_pre': pid in X0 and bool(q),
                      'pre_vorx': (X0.get(pid) or {}).get('vorx0', (X0.get(pid) or {}).get('vorx')) or 0.0, 'mpg0': q.get('mp_per_g') or 0.0})
    ROSTER['nba'] = cands
    out = []
    T = season_T('nba', sum(v[1] for v in teams.values()) / max(82 * len(teams), 1))
    for aw, pool, p, dm, show in nba_races(fit, rng, cands, teams, conf, coy=nba_coy_teams(S, teams)):
        if fit[aw].get('k'): out.append((aw, rows_out(pool, p, dm, show, rng, top=30 if aw == 'allnba' else 20), show))
        else: out.append((aw, rows_out(pool, temper(p, T), dm, show, rng), show))
    return {'season': f'{S - 1}-{str(S)[2:]}', 'races': out, 'logo': 'nba', 'T': T}


def nba_coy_teams(S, teams):
    """COY candidates: one a team (its coach), with last season's win share and the preseason over/under"""
    import awards_nba as A
    st0, ou = A.standings(S - 1), A.preseason_ou(S)
    names = A.coaches(S)
    return [{'id': t, 'n': names.get(t, t), 'tm': t, 'wp0': st0.get(t, {}).get('wp', .5),
             'ou': ou[t] / 82 if t in ou else st0.get(t, {}).get('wp', .5)} for t in teams]


SHOWN = {'vorx': 'rvorx', 'dxpm': 'rdxpm', 'd_vorx': 'rd_vorx'}   # conviction + shown stats: the team-adjusted XPM the site shows


def nba_races(fit, rng, cands, teams, conf, G=82, min_g=65, sims=SIMS, coy=()):
    """yields (award, pool, P(win), draw for the shown stats, shown stats) for each passing NBA award. cands: to-date
    lines; teams: {t: (wins, games, mean final wins, sd, G)}; conf: {t: conference}; min_g: the games rule (0 = none)"""
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

    def blend(now, g, prior, g0=15):
        if SEASON_ONLY: return now
        return (now * g + (.85 * now if prior is None else prior) * g0) / (g + g0)   # no last season: toward 85%

    def draw(c, td, rng, elig65=False):
        left = max(G - c['tg'], 0)
        av = min((c['g'] + .9 * 8) / (c['tg'] + 8), 1.0)
        if AV_ACT and c.get('act'): av = max(av, AV_ACT)
        gr = games_left(rng, left, av, 'nba')
        gf = c['g'] + gr
        if elig65 and gf < min_g: return None
        mr = gr * c['mpg']
        mp = c['mp'] + mr
        if mp <= 0: return None
        x_rest = gauss(rng, c['xpm'] if SEASON_ONLY else c['sx'], TAU * math.sqrt(K / (c['mp'] + K)) + (TAU * math.sqrt(K / mr) if mr > 0 else 0))
        d_rest = gauss(rng, c['dxpm'] if SEASON_ONLY else c['sdx'], TAUD * math.sqrt(K / (c['mp'] + K)) + (TAUD * math.sqrt(K / mr) if mr > 0 else 0))
        xpm = (c['xpm'] * c['mp'] + x_rest * mr) / mp
        dx = (c['dxpm'] * c['mp'] + d_rest * mr) / mp
        pp_r = gauss(rng, blend(c['ppg'], c['g'], c['ppg0']), 2.5 * math.sqrt(15 / (c['g'] + 15)))
        ppg = (c['ppg'] * c['g'] + pp_r * gr) / max(gf, 1)
        rp = (c['rpg'] * c['g'] + gauss(rng, blend(c['rpg'], c['g'], c['rpg0']), .8) * gr) / max(gf, 1)
        st = (c['st'] * c['g'] + gauss(rng, blend(c['st'], c['g'], c['st0']), .3) * gr) / max(gf, 1)
        ap = (c['apg'] * c['g'] + blend(c['apg'], c['g'], c.get('apg0')) * gr) / max(gf, 1) if 'apg' in c else 0.0
        # rxpm / rdxpm / rvorx: the team-adjusted XPM (the to-date team adjustment carried over the rest) the site shows;
        # MVP and DPOY are fit on them, the other races on the box blend (xpm / dxpm / vorx)
        rx, rdx = xpm + c.get('ta', 0.0), dx + c.get('tad', 0.0)
        rv = .030 * (rx + 1.4) * mp / 48
        return {'apg': ap, 'prev_allnba': prev.get('allnba', {}).get(c['id'], 0), 'rxpm': rx, 'rdxpm': rdx, 'rvorx': rv,
                'rd_vorx': rv - c.get('pre_rvorx', c.get('pre_vorx', 0)),
                'vorx': .030 * (xpm + 1.4) * mp / 48, 'xpm': xpm, 'dxpm': dx, 'ppg': ppg, 'rpg': rp, 'stocks': st,
                'mpg': mp / max(gf, 1), 'big': 1.0 if c['pos'] in ('C', 'PF') else 0.0, 'wp': td[c['tm']],
                'seed1': 1.0 if c['tm'] in td['_seed1'] else 0.0, 'gfrac': gf / G,
                'prev_mvp': prev.get('mvp', {}).get(c['id'], 0), 'prev_dpoy': prev.get('dpoy', {}).get(c['id'], 0),
                'prev_alldef': prev.get('alldef', {}).get(c['id'], 0),
                'd_vorx': .030 * (xpm + 1.4) * mp / 48 - c.get('pre_vorx', 0), 'd_ppg': ppg - (c.get('ppg0') or 0),
                'd_mpg': mp / max(gf, 1) - c.get('mpg0', 0)}

    for aw, pool_f, elig, show in (
            ('mvp', lambda c: c['mpg'] >= 20, True, [('rvorx', 'VORX', '%.1f'), ('ppg', 'PPG', '%.1f'), ('wp', 'W%', 'pct'), ('gfrac', 'G', 'g82')]),
            ('dpoy', lambda c: c['mpg'] >= 20, True, [('rdxpm', 'D-XPM', '%+.1f'), ('stocks', 'STL+BLK', '%.1f'), ('rpg', 'RPG', '%.1f'), ('wp', 'W%', 'pct')]),
            ('roy', lambda c: c['rookie'] and c['mpg'] >= 10, False, [('rvorx', 'VORX', '%.1f'), ('ppg', 'PPG', '%.1f'), ('mpg', 'MPG', '%.1f'), ('wp', 'W%', 'pct')])):
        spec = fit.get(aw)
        if not spec or not spec['test'].get('pass'): continue
        pool = [c for c in cands if pool_f(c)]
        dr = lambda c, td, rng, e=elig: draw(c, td, rng, e)
        dr.teams = teams_draw
        m = SHOWN.get(spec['null'][0], spec['null'][0])
        lead(aw, pool, dr, m, first(show, m), rng)
        pool = prune(pool, spec, dr, rng)
        p = race(pool, spec, dr, rng, sims)
        dm = lambda c, td, rng: draw(c, td, rng, False)
        dm.teams = teams_draw
        yield aw, pool, p, dm, show
    spec = fit.get('allnba')
    if spec and spec['test'].get('pass'):
        dr = lambda c, td, rng: draw(c, td, rng, True)
        dr.teams = teams_draw
        show = [('rvorx', 'VORX', '%.1f'), ('ppg', 'PPG', '%.1f'), ('wp', 'W%', 'pct'), ('gfrac', 'G', 'g82')]
        lead('allnba', [c for c in cands if c['mpg'] >= 20], dr, SHOWN.get(spec['null'][0], spec['null'][0]), show, rng, k=spec.get('k', 15))
        pool = prune([c for c in cands if c['mpg'] >= 20], spec, dr, rng, keep=60)
        dm = lambda c, td, rng: draw(c, td, rng, False)
        dm.teams = teams_draw
        yield 'allnba', pool, race_k(pool, spec, dr, rng, spec.get('k', 15), sims), dm, show
    # Nov 23 2026: Sixth Man (bench: started under half his games, bbref's rule), Most Improved (VORX gain on last
    # season's published VORX), All-Defensive and All-Rookie (10 named), Coach of the Year (a team's coach)
    for aw, pool_f, elig, metric, show in (
            ('smoy', lambda c: c['gs'] < c['g'] / 2 and c['mpg'] >= 12, False, 'rvorx',
             [('rvorx', 'VORX', '%.1f'), ('ppg', 'PPG', '%.1f'), ('mpg', 'MPG', '%.1f'), ('wp', 'W%', 'pct')]),
            ('mip', lambda c: c['has_pre'] and c['mpg'] >= 20, False, 'rd_vorx',
             [('rd_vorx', '+VORX', '%+.1f'), ('rvorx', 'VORX', '%.1f'), ('d_ppg', '+PPG', '%+.1f'), ('ppg', 'PPG', '%.1f')]),
            ('alldef', lambda c: c['mpg'] >= 20, True, 'rdxpm',
             [('rdxpm', 'D-XPM', '%+.1f'), ('stocks', 'STL+BLK', '%.1f'), ('rpg', 'RPG', '%.1f'), ('gfrac', 'G', 'g82')]),
            ('allrookie', lambda c: c['rookie'] and c['mpg'] >= 10, False, 'rvorx',
             [('rvorx', 'VORX', '%.1f'), ('ppg', 'PPG', '%.1f'), ('mpg', 'MPG', '%.1f'), ('wp', 'W%', 'pct')])):
        spec = fit.get(aw)
        if not spec or not spec['test'].get('pass'): continue
        pool = [c for c in cands if pool_f(c)]
        dr = lambda c, td, rng, e=elig: draw(c, td, rng, e)
        dr.teams = teams_draw
        k = spec.get('k')
        lead(aw, pool, dr, metric, first(show, metric), rng, k=k or 1)
        pool = prune(pool, spec, dr, rng, keep=60 if k else 45)
        dm = lambda c, td, rng: draw(c, td, rng, False)
        dm.teams = teams_draw
        yield aw, pool, (race_k(pool, spec, dr, rng, k, sims) if k else race(pool, spec, dr, rng, sims)), dm, show
    spec = fit.get('coy')
    if coy and spec and spec['test'].get('pass'):
        def cdraw(c, td, rng):
            wp = td[c['tm']]
            return {'wp': wp, 'd_wp': wp - c['wp0'], 'ovr': wp - c['ou'], 'seed1': 1.0 if c['tm'] in td['_seed1'] else 0.0,
                    'dw': (wp - c['wp0']) * G, 'ovw': (wp - c['ou']) * G}
        cdraw.teams = teams_draw
        yield 'coy', list(coy), race(list(coy), spec, cdraw, rng, sims), cdraw, [
            ('wp', 'W%', 'pct'), ('ovw', 'vs O/U', '%+.1f'), ('dw', 'vs LY', '%+.1f')]


# ---------------------------------------------------------------- NHL

NHL_MW, NHL_MW_K = (1.0, 0.7, 0.5), 1600.0     # Marcel WAR: season weights, shrink minutes (scripts/player_pctl.py MARCEL, data/pctl_fit_nhl.json)


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
    hist, mu = {}, {}
    for s in range(A.FIRST - 1, S):
        for r in A.war(s):
            hist.setdefault(NM.key(r['n']), []).append(r.get('gp') or 0)
            if r.get('war') is not None and r.get('toi'):
                m = mu.setdefault(r['grp'], [0.0, 0.0]); m[0] += r['war']; m[1] += r['toi']
    last2 = {r['id']: r for r in A.war(S - 2)}

    def marcel_war(r):
        """Marcel WAR a minute: this season to date and the two before at 1 / .7 / .5 by ice time, shrunk with
        NHL_MW_K minutes to his group's WAR a minute over the seasons before (the projections tab's form). The
        games left run at this rate: pWAR sits on its own replacement scale (goalies near 0) and misses next-season
        WAR by more (scripts/research/ctx_nov27/nhl: MSE 1.81 -> 1.47, t 10.7, 15 of 15 seasons)"""
        m = mu.get(r['grp'])
        num, den = NHL_MW_K * (m[0] / m[1] if m and m[1] else 0.0), NHL_MW_K
        for w, q in zip(NHL_MW, (r, last.get(r['id']), last2.get(r['id']))):
            if q and q.get('war') is not None and q.get('toi'):
                num += w * q['war']; den += w * q['toi']
        return num / den
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
                      'toi': r.get('toi') or 0, 'war': r.get('war') or 0, 'mwr': marcel_war(r), 'gd': r.get('gd') or 0,
                      'pts': r.get('pts') or 0, 'g': r.get('g') or 0, 'gsax': r.get('gsax') or 0,
                      'ppg0': (q.get('pts') or 0) / q['gp'] if q.get('gp') else None,
                      'gpg0': (q.get('g') or 0) / q['gp'] if q.get('gp') else None,
                      'gsx0': (q.get('gsax') or 0) / max(q.get('toi') or 1, 1) * 60 if q.get('gp') else None,
                      'rookie': rookie, 'key': k})

    nhl_lines(cands, S)
    ROSTER['nhl'] = cands
    out = []
    T = season_T('nhl', sum(TG.values()) / max(82 * len(TG), 1))
    for aw, pool, p, draw, show in nhl_races(fit, rng, cands, teams):
        if aw == 'allstar': out.append((aw, rows_out(pool, p, draw, show, rng, top=30), show))        # P(team): no temper
        else: out.append((aw, rows_out(pool, temper(p, T), draw, show, rng), show))
    for aw, pool, p, draw, show in nhl_titles(fit, rng, cands, nhl_draw(fit, teams)):
        out.append((aw, rows_out(pool, p, draw, show, rng), show))                                 # stat titles: no temper
    return {'season': f'{S - 1}-{str(S)[2:]}', 'races': out, 'logo': 'nhl', 'T': T}


def nhl_lines(cands, S):
    """+/- (scaled by games in the draws), PIM a game, faceoff share over .5 (centres: 5+ draws a game), takeaways a
    game: NHL stats API skater reports for the season (the Selke and Lady Byng voter models' inputs)"""
    import urllib.parse
    q = urllib.parse.quote(f'seasonId={S - 1}{S} and gameTypeId=2')
    srt = urllib.parse.quote('[{"property":"playerId","direction":"ASC"}]')
    rep = {}
    for r in ('summary', 'realtime', 'faceoffwins'):
        start = 0
        try:
            while True:                                   # 100 rows a call at most (limit=-1 included): page through
                d = json.loads(urllib.request.urlopen(urllib.request.Request(
                    f'https://api.nhle.com/stats/rest/en/skater/{r}?limit=100&start={start}&sort={srt}&cayenneExp={q}',
                    headers={'User-Agent': UA}), timeout=60).read())
                for x in d.get('data', []): rep.setdefault(str(x['playerId']), {}).update(x)
                start += len(d.get('data', []))
                if not d.get('data') or start >= (d.get('total') or 0): break
        except Exception as e:
            print('nhl stats api', r, e)
    for c in cands:
        x = rep.get(str(c['id']))
        if not x or c['grp'] == 'G': continue
        gp = max(c['gp'], 1)
        fo = (x.get('totalFaceoffWins') or 0) + (x.get('totalFaceoffLosses') or 0)
        c.update(pm=x.get('plusMinus') or 0, pimpg=(x.get('penaltyMinutes') or 0) / gp, tk=(x.get('takeaways') or 0) / gp,
                 fo=((x.get('totalFaceoffWins') or 0) / fo - .5) if fo >= 5 * gp else 0.0)


def nhl_draw(fit, teams, G=82):
    """one simulated finish of a candidate (draw(c, td, rng) -> features) and draw.teams(rng) -> team points %"""
    prev = fit.get('_prev', {})

    def draw(c, td, rng):
        left = max(G - c['tg'], 0)
        if c['grp'] == 'G':
            share = min((c['gp'] + .55 * 6) / (c['tg'] + 6), 1.0)  # starts so far, toward a 1A's share
        else:
            share = min((c['gp'] + .95 * 6) / (c['tg'] + 6), 1.0)
        gr = games_left(rng, left, share, 'nhl')
        gp = c['gp'] + gr
        tpg = c['toi'] / max(c['gp'], 1)
        tr = gr * tpg
        rate = c['war'] / max(c['toi'], 1) if SEASON_ONLY else c['mwr']   # Marcel WAR a minute (conviction: this season's own)
        war_r = gauss(rng, rate * tr, abs(rate) * tr * .35 + .25 * math.sqrt(tr / 60) * (.6 if c['grp'] != 'G' else 1.5))
        war = c['war'] + war_r
        # rates toward last season (no season: 80% of the pace so far), points by 40 games, goals 50, GSAx 40 starts
        bl = lambda now, prior, g0: now if SEASON_ONLY else (now * c['gp'] + (.8 * now if prior is None else prior) * g0) / (c['gp'] + g0)
        ppg = max(gauss(rng, bl(c['pts'] / max(c['gp'], 1), c['ppg0'], 40), .12), 0)     # talent sd .12 a game
        gpg = max(gauss(rng, bl(c['g'] / max(c['gp'], 1), c['gpg0'], 50), .06), 0)
        pts = c['pts'] + max(gauss(rng, ppg * gr, math.sqrt(max(ppg * gr, 0) * 1.3)), 0)
        g = c['g'] + max(gauss(rng, gpg * gr, math.sqrt(max(gpg * gr, 0) * 1.1)), 0)
        gs_rate = c['gsax'] / max(c['toi'], 1) * 60
        if not SEASON_ONLY: gs_rate = bl(gs_rate, c['gsx0'], 40) if c['gsx0'] is not None else gs_rate * c['gp'] / (c['gp'] + 40)
        gsax = c['gsax'] + gauss(rng, gs_rate * tr / 60, 1.4 * math.sqrt(max(tr / 60, 0)))   # 1.4 goals a game
        # defensive goals (WAR's gd) run out with his WAR; +/- by games; PIM, faceoffs, takeaways at this season's rates
        gd = c['gd'] + (c['gd'] / c['war'] * war_r if c['grp'] != 'G' and abs(c['war']) > .5 else c['gd'] / max(c['gp'], 1) * gr)
        k = c.get('key')
        return {'war': war, 'pts': pts, 'g': g, 'gsax': gsax, 'gp': gp, 'gfrac': gp / G, 'toipg': tpg,
                'tpct': td[c['tm']], 'goalie': 1.0 if c['grp'] == 'G' else 0.0, 'gd': gd, 'dman': 1.0 if c['grp'] == 'D' else 0.0,
                'pm': c.get('pm', 0.0) * gp / max(c['gp'], 1), 'pimpg': c.get('pimpg', 0.0), 'fo': c.get('fo', 0.0), 'tk': c.get('tk', 0.0),
                'prev_hart': prev.get('hart', {}).get(k, 0), 'prev_norris': prev.get('norris', {}).get(k, 0),
                'prev_vezina': prev.get('vezina', {}).get(k, 0), 'prev_selke': prev.get('selke', {}).get(k, 0),
                'prev_byng': prev.get('byng', {}).get(k, 0), 'prev_allstar': prev.get('allstar', {}).get(k, 0),
                'prev_lindsay': prev.get('lindsay', {}).get(k, 0)}

    def teams_draw(rng):
        out = {}
        for t, (pts, g2, xp, sd, P) in teams.items():
            out[t] = min(max(gauss(rng, xp, sd), pts), pts + (P - g2)) / P
        return out

    draw.teams = teams_draw
    return draw


NHL_AS_K = {'F': 6, 'D': 4, 'G': 2}       # All-Star: first and second team by group (C/LW/RW, D, G)


def nhl_races(fit, rng, cands, teams, G=82, sims=SIMS):
    """yields (award, pool, P(win), draw, shown stats) for each passing NHL award. cands: to-date lines; teams:
    {t: (points, 2 x games, mean final points, sd, 2 x G)}. Conviction (lead()) also runs for Selke and the All-Star
    teams (their own value metric: WAR's defensive goals, WAR)"""
    draw = nhl_draw(fit, teams, G)
    for aw, pool_f, show in (
            ('hart', lambda c: c['gp'] >= 5, [('war', 'WAR', '%.1f'), ('pts', 'PTS', '%.0f'), ('tpct', 'PTS%', 'pct')]),
            ('norris', lambda c: c['grp'] == 'D' and c['gp'] >= 5, [('war', 'WAR', '%.1f'), ('pts', 'PTS', '%.0f'), ('toipg', 'TOI', 'toi'), ('tpct', 'PTS%', 'pct')]),
            ('vezina', lambda c: c['grp'] == 'G' and c['gp'] >= 3, [('gsax', 'GSAx', '%+.1f'), ('war', 'WAR', '%.1f'), ('gp', 'GP', '%.0f'), ('tpct', 'PTS%', 'pct')]),
            ('calder', lambda c: c['rookie'] and c['gp'] >= 3, [('war', 'WAR', '%.1f'), ('pts', 'PTS', '%.0f'), ('g', 'G', '%.0f'), ('tpct', 'PTS%', 'pct')]),
            ('selke', lambda c: c['grp'] == 'F' and c['gp'] >= 5, [('gd', 'DEF', '%+.1f'), ('war', 'WAR', '%.1f'), ('pts', 'PTS', '%.0f'), ('pm', '+/-', '%+.0f')]),
            ('byng', lambda c: c['grp'] != 'G' and c['gp'] >= 5, [('pimpg', 'PIM/G', '%.2f'), ('pts', 'PTS', '%.0f'), ('war', 'WAR', '%.1f')])):
        spec = fit.get(aw)
        if not spec: continue
        if aw == 'selke': lead(aw, [c for c in cands if pool_f(c)], draw, 'gd', show, rng)
        if not spec['test'].get('pass'): continue
        if aw not in ('selke', 'byng'):          # Byng: no value metric of ours for sportsmanship, so no conviction race
            lead(aw, [c for c in cands if pool_f(c)], draw, spec['null'][0], first(show, spec['null'][0]), rng)
        pool = prune([c for c in cands if pool_f(c)], spec, draw, rng)
        p = race(pool, spec, draw, rng, sims)
        yield aw, pool, p, draw, show
    # All-Star teams: a top-k race in each group (first and second team), one table
    spec = fit.get('allstar')
    if spec:
        show = [('war', 'WAR', '%.1f'), ('pts', 'PTS', '%.0f'), ('gsax', 'GSAx', '%+.1f'), ('tpct', 'PTS%', 'pct')]
        grp = lambda g: [c for c in cands if c['grp'] == g and c['gp'] >= (3 if g == 'G' else 5)]
        conv = []
        for g, k in NHL_AS_K.items():
            lead('allstar', grp(g), draw, 'war', show, rng, k=k)
            if CONV is not None and 'allstar' in CONV: conv.append(CONV.pop('allstar'))
        if conv:
            rows = Rows(sorted([r for x in conv for r in x], key=lambda r: -r['p'])[:30])
            rows.rest = [r for x in conv for r in x.rest] + sorted([r for x in conv for r in x], key=lambda r: -r['p'])[30:]
            rows.show, rows.metric, rows.k = show, 'war', sum(NHL_AS_K.values())
            rows.about = (f"P(team): the share of {SIMS:,} simulated rests of the season in which he is in his group's top "
                          "two on WAR (forwards top six, defencemen top four), the games left at this season's own rate. "
                          "No voter model, no market.")
            CONV['allstar'] = rows
        if spec['test'].get('pass'):
            pool, p = [], []
            for g, k in NHL_AS_K.items():
                pl = prune(grp(g), spec, draw, rng, keep=max(30, 5 * k))
                pool += pl; p += race_k(pl, spec, draw, rng, k, sims)
            yield 'allstar', pool, p, draw, show


def nhl_titles(fit, rng, cands, draw, sims=SIMS):
    """Art Ross (points, goals break ties) and Rocket Richard (goals): stat titles, so P(lead) is the race itself.
    Predictive = the live draw (rates blended toward last season); conviction = this season's own rate (lead()).
    The predictive table is written only where the as-of test (data/awards_fit.json, stat: true) passed."""
    sk = [c for c in cands if c['grp'] != 'G' and c['gp'] >= 1]
    for aw, metric, tie, show in (('artross', 'pts', 'g', [('pts', 'PTS', '%.0f'), ('g', 'G', '%.0f'), ('gp', 'GP', '%.0f')]),
                                  ('richard', 'g', None, [('g', 'G', '%.0f'), ('pts', 'PTS', '%.0f'), ('gp', 'GP', '%.0f')])):
        spec = fit.get(aw)
        if not spec: continue
        pool = title_pool(sk, metric, tie)
        lead(aw, pool, draw, metric, show, rng)
        if spec['test'].get('pass'):
            yield aw, pool, title_p(pool, draw, metric, tie, rng, sims), draw, show


def title_pool(sk, metric, tie, n=60):
    """the n best on the metric so far and the n best on pace (a short list for the stat-title simulation)"""
    by_now = sorted(sk, key=lambda c: -(c[metric] + 1e-3 * (c[tie] if tie else 0)))[:n]
    by_pace = sorted(sk, key=lambda c: -c[metric] / max(c['gp'], 1) * min(c['gp'], 10) / 10)[:n]
    seen, out = set(), []
    for c in by_now + by_pace:
        if c['id'] not in seen: seen.add(c['id']); out.append(c)
    return out


def title_p(pool, draw, metric, tie, rng, sims=SIMS):
    """P(lead the league) per candidate over simulated finishes (a tie in the metric broken by `tie`, then shared)"""
    win = [0.0] * len(pool)
    for _ in range(sims):
        td = draw.teams(rng)
        z = []
        for i, c in enumerate(pool):
            f = draw(c, td, rng)
            if f is not None: z.append((round(f[metric]) + (round(f[tie]) / 1000 if tie else 0), i))
        if not z: continue
        m = max(v for v, _ in z)
        top = [i for v, i in z if v == m]
        for i in top: win[i] += 1 / len(top)
    return [w / sims for w in win]


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
    K, KPX, TAU = 300, 600, 3.5
    cands = []
    try:
        import awards_cbb as AC
        S = int(str(G.get('season', ''))[:4] or dt.date.today().year) + 1
        cbb_ap = {k: 26.0 - v for k, v in AC.ap_pre(S).items()}        # the team's preseason AP rank (Erving's term)
    except Exception as e:
        print('cbb preseason AP', e); cbb_ap = {}
    # XPM (rXPM) = BPM + the team's shift per side (scripts/cbb_tabs.py writes this season's from the game logs): the value
    # the conviction race and the shown stats use. The voter models stay on BPM: with rXPM in its place every race's
    # held-out log P(winner) was level or worse (scripts/research/xpm_swap_nov26/awards.py, t -1.5 to .4)
    try:
        sh = json.load(open(os.path.join(ROOT, 'scripts', 'data', 'cbb_xpm_shift.json')))
        xshift = sh['teams'] if str(sh.get('season')) == str(S) else {}
    except (OSError, ValueError, KeyError, NameError):
        xshift = {}
    for row in d['rows']:
        r = dict(zip(C, row))
        now = r.get('now') or {}
        if not now.get('gp') or r['team'] not in teams: continue
        last = r.get('last') or {}
        xo, xd = xshift.get(r['team'], (0.0, 0.0))
        # priors: his preseason pXPM (the board's frozen column: the predictive pick, on the voter value's BPM scale) with
        # KPX minutes; without one, last season's line (any team) or the board's projected BPM for newcomers with K.
        # scripts/research/ctx_nov27/cbb/r1_awards_rate.py, game logs 2017-26, rest-of-season game BPM of 20+ minute
        # players at the 5th to 20th team game: last season's BPM at K 300 MSE 7.35 -> pXPM at K 300 6.54 (t 17.2, 10/10
        # seasons), at K 600 (the walk's pick every season) 6.35; the top 100 by BPM to date 7.35 -> 6.11 (t 8.6, 10/10)
        prior = last['bpm'] if last.get('bpm') is not None and (last.get('gp') or 0) >= 8 else \
            next((x[2] for x in (r.get('parts') or []) if x[0] == 'BPM'), now['bpm'])
        pk = K
        if r.get('pxpm') is not None: prior, pk = r['pxpm'], KPX
        elif not (last.get('bpm') is not None and (last.get('gp') or 0) >= 8) and r.get('xb0') is not None:
            # a newcomer: his preseason xXPM. The board part this line looked for ('BPM') is gone, so his prior had been
            # his own BPM to date, no shrink at all (r1b_newcomers.py: no shrink MSE 12.52, a flat prior at K 300 8.92, 9/9)
            prior = r['xb0']
        pp0 = last['ppg'] if last.get('ppg') is not None and (last.get('gp') or 0) >= 8 else None
        espn = re.search(r'/id/(\d+)', (r.get('links') or {}).get('espn', '') or '')
        w, g, _, _, tot = teams[r['team']]
        cands.append({'id': r['name'] + '|' + r['team'], 'n': r['name'], 'tm': r['team'], 'logo': r.get('logo'),
                      'ph': espn.group(1) if espn else None, 'cls': r.get('cls'), 'gp': now['gp'], 'tg': g, 'tot': tot,
                      'mpg': now.get('mpg') or 0, 'ppg': now.get('ppg') or 0, 'bpm': now.get('bpm') or 0, 'prior': prior, 'pk': pk,
                      'pp0': pp0, 'dbpm': now.get('dbpm') or 0, 'blk': now.get('blk') or 0, 'stl': now.get('stl') or 0,
                      'drb': now.get('drb'), 'yr': now.get('yr') or r.get('cls'),
                      'dprior': last['dbpm'] if last.get('dbpm') is not None and (last.get('gp') or 0) >= 8 else .5 * (now.get('dbpm') or 0),
                      'role': now.get('role') or r.get('role') or {'G': 'Combo G', 'C': 'PF/C'}.get(r.get('pos'), 'Wing F'),
                      'ap_pre': cbb_ap.get(NM.team_key(r['team']), 0.0), 'ta': xo + xd, 'tad': xd})

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
        pk = K if SEASON_ONLY else c['pk']       # conviction: this season's own rate, the noise as before
        mean = c['bpm'] if SEASON_ONLY else (c['bpm'] * m0 + c['prior'] * pk) / (m0 + pk)
        b_rest = gauss(rng, mean, TAU * math.sqrt(pk / (m0 + pk)) + (TAU * math.sqrt(K / mr) if mr > 0 else 0))
        bpm = (c['bpm'] * m0 + b_rest * mr) / max(m0 + mr, 1)
        pp0 = c['pp0'] if c['pp0'] is not None else .6 * c['ppg'] + 4
        p_rest = gauss(rng, c['ppg'] if SEASON_ONLY else (c['ppg'] * c['gp'] + pp0 * 10) / (c['gp'] + 10), 3.0 * math.sqrt(10 / (c['gp'] + 10)))
        ppg = (c['ppg'] * c['gp'] + p_rest * gr) / max(gp, 1)
        dmean = c['dbpm'] if SEASON_ONLY else (c['dbpm'] * m0 + c['dprior'] * K) / (m0 + K)
        d_rest = gauss(rng, dmean, 1.5 * math.sqrt(K / (m0 + K)) + (1.5 * math.sqrt(K / mr) if mr > 0 else 0))
        dbpm = (c['dbpm'] * m0 + d_rest * mr) / max(m0 + mr, 1)
        return {'bpm': bpm, 'xpm': bpm + c['ta'], 'dxpm': dbpm + c['tad'], 'ppg': ppg, 'wp': td[c['tm']], 'barthag': td['_b' + c['tm']], 'mpg': c['mpg'],
                'p5': 1.0 if tinfo[c['tm']][2] in P5 else 0.0, 'dbpm': dbpm, 'blk': c['blk'], 'stl': c['stl'],
                'drb': c['drb'] if c['drb'] is not None else DRB_MU, 'ap_pre': c['ap_pre']}

    draw.teams = teams_draw
    # the board's line has no DR% yet on older builds: the DPOY race then holds it at the fit's mean (no effect)
    dsp = fit.get('dpoy') or {}
    DRB_MU = dsp['mu'][dsp['cols'].index('drb')] if 'drb' in dsp.get('cols', []) else 0.0
    if not fit.get('wooden', {}).get('test', {}).get('pass'): return None
    show = [('xpm', 'XPM', '%+.1f'), ('ppg', 'PPG', '%.1f'), ('wp', 'W%', 'pct')]
    dshow = [('dxpm', 'D-XPM', '%+.1f'), ('blk', 'BLK%', '%.1f'), ('stl', 'STL%', '%.1f'), ('wp', 'W%', 'pct')]
    CSHOWN = {'bpm': 'xpm', 'dbpm': 'dxpm'}
    import awards_cbb as AC
    role = lambda aw: (lambda c: c['mpg'] >= 20 and c['role'] in AC.ROLE_POOL[aw])
    races = []
    # Wooden, then the races added Nov 23 2026 (scripts/awards_bball.py): Naismith, AP, DPOY (NABC), Freshman
    # (USBWA), the five position awards; pools by this season's class and Barttorvik role
    for aw, pool_f, sh in (('wooden', None, show), ('naismith', None, show), ('ap', None, show), ('dpoy', None, dshow),
                           ('frosh', lambda c: c['mpg'] >= 15 and c['yr'] == 'Fr', show),
                           ('cousy', role('cousy'), show), ('west', role('west'), show), ('erving', role('erving'), show),
                           ('malone', role('malone'), show), ('kareem', role('kareem'), show)):
        spec = fit.get(aw)
        if not spec or not spec['test'].get('pass'): continue
        pool = [c for c in cands if (pool_f or (lambda c: c['mpg'] >= 20))(c)]
        cm = CSHOWN.get(spec['null'][0], spec['null'][0])
        lead(aw, pool, draw, cm, first(sh, cm), rng)
        pool = prune(pool, spec, draw, rng, keep=60)
        p = race(pool, spec, draw, rng)
        races.append((aw, rows_out(pool, p, draw, sh, rng), sh))
    return {'season': G.get('season', ''), 'races': races, 'logo': 'cbb'}


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


LEFT_BLEND, LEFT_G0 = ('pass_y', 'scrim', 'td', 'sacks'), 8


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
        if PACE_GP and c['f'].get('gp'): gn = max(min(c['f']['gp'], gn), 1)
        for k, kind in per_left:
            rate = c['f'][k] / gn
            if LEFT_K and (c.get('prev') or {}).get(k) is not None: rate = (c['f'][k] + LEFT_K * c['prev'][k]) / (gn + LEFT_K)
            if not SEASON_ONLY and k in LEFT_BLEND and 'p17' in c['f']:
                # games left at the predictive rate: this season's rate a team game blended with last season's by
                # LEFT_G0 games, no last season = 85% of this one (held out 2016-25 from week 9: t -9.4, 10 of 10
                # seasons, each of the four stats better; scripts/research/ctx_nov27/nfl/r4_awards.py). Conviction
                # (SEASON_ONLY) and the college draw keep this season's own rate
                prior = c['f'].get('p17_' + k) if c['f']['p17'] else None
                rate = (rate * gn + (.85 * rate if prior is None else prior) * LEFT_G0) / (gn + LEFT_G0)
            mu = rate * gr
            sdv = math.sqrt(max(mu, 0)) if kind == 'count' else .3 * mu
            f[k] = c['f'][k] + (gauss(rng, mu, abs(sdv)) if k == 'svar' else max(gauss(rng, mu, sdv), 0))
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
    for a in ('bilet', 'butkus'):                      # Nov 23 2026: the v2 retries (+ p5, ap_end, prev_top5) that passed
        if fit.get(a + '2', {}).get('test', {}).get('pass'): fit[a] = dict(fit[a + '2'], label=fit[a]['label'])
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
    ROSTER['cfb'] = cands
    cfb_enrich(cands, S)
    for c in cands:                      # the pool rules use season-end thresholds: test them on full-season pace
        w, g, _, _, G = teams[c['tid']]
        k = G / max(g, 1)
        c['pf'] = dict(c['f'], **{x: c['f'][x] * k for x, _ in CFB_LEFT}, yds=c['f']['yds'] * k)
    war_lead.logos = {k: (v[1], v[0]) for k, v in logos.items()}
    war_lead('cfb', teams, rng)
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


def cfb_enrich(cands, S):
    """p5 (power-conference team-season, ESPN groups) and ap_end (the latest AP poll, (26 - rank) / 25, 0 unranked):
    the Nov 23 2026 terms of the Heisman, Walter Camp, O'Brien, Biletnikoff and Butkus models"""
    import awards_football as F
    import awards_football_more as FM
    import concurrent.futures as cf
    tids = {c['tid'] for c in cands}
    try:
        with cf.ThreadPoolExecutor(8) as ex:
            conf = dict(zip(tids, ex.map(lambda t: FM.cfb_conf(S, t), tids)))
    except Exception as e:
        print('cfb conferences', e); conf = {}
    ap = {}
    try:
        wk = F.get(f'{FM.CORE}/seasons/{S}/types/2/weeks')
        for w in range(int(wk.get('count') or 16), 0, -1):
            d = F.get(f'{FM.CORE}/seasons/{S}/types/2/weeks/{w}/rankings/1')
            if d.get('ranks'):
                for x in d['ranks']:
                    m = re.search(r'/teams/(\d+)', x['team']['$ref'])
                    if m: ap[m.group(1)] = (26 - x['current']) / 25
                break
    except Exception as e:
        print('cfb AP poll', e)
    for c in cands:
        c['f']['p5'] = FM.is_p5(conf.get(c['tid']), S, c['tid'])
        c['f']['ap_end'] = ap.get(str(c['tid']), 0.0)


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
    ROSTER['nfl'] = cands
    try: nfl_enrich(fit, cands, tmap, S)
    except Exception as e: print('nfl prior-season inputs skipped:', e)
    war_lead.tmap = tmap
    war_lead('nfl', teams, rng)
    out = []
    T = season_T('nfl', sum(v[1] for v in teams.values()) / max(17 * len(teams), 1))
    for aw, pl, p, draw, show in nfl_races(fit, rng, cands, teams): out.append((aw, rows_out(pl, temper(p, T), draw, show, rng), show))
    try:
        r = nfl_droy(fit, rng, teams, tmap, S)
        if r: out.append((r[0], rows_out(r[1], temper(r[2], T), r[3], r[4], rng), r[4]))
    except Exception as e:
        print('nfl droy skipped:', e)
    try:
        for aw, pl, p, draw, show in nfl_more(fit, rng, cands, teams, tmap, S): out.append((aw, rows_out(pl, temper(p, T), draw, show, rng), show))
    except Exception as e:
        import traceback; traceback.print_exc()
        print('nfl cpoy / coy / all-pro skipped:', e)
    return {'season': str(S), 'races': out, 'logo': 'nfl', 'T': T}


def nfl_enrich(fit, cands, tmap, S):
    """the Nov 23 inputs every candidate line carries: his ESPN line the season before (prev_gp, prev_yds, prev_def),
    AP first-team All-Pro selections and DPOY wins before this season (the fit's _prev), and his team's points-allowed
    rank so far (drank: 32 = fewest a game; nflverse games)"""
    import awards_football as F
    import awards_nflverse as V
    import concurrent.futures as cf
    prev = fit.get('_prev', {})
    ap, dpw = prev.get('allpro', {}), prev.get('dpoy_wins', {})
    with cf.ThreadPoolExecutor(8) as ex:
        pv = dict(zip([c['id'] for c in cands], ex.map(lambda c: F.athlete_stats('nfl', S - 1, c['id']), cands)))
    G = V.nfl_file('games.csv', 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv', fresh=True)
    nfl_enrich.games = G
    pa = {}
    for x in G:
        if x['game_type'] != 'REG' or int(x['season']) != S or x['home_score'] in ('', 'NA'): continue
        for tm, op in ((x['home_team'], x['away_score']), (x['away_team'], x['home_score'])):
            tm = V.TEAM_FIX.get(tm, tm)
            a = pa.setdefault(tm, [0, 0]); a[0] += int(op); a[1] += 1
    rk = {t: 32 - i for i, t in enumerate(sorted(pa, key=lambda t: pa[t][0] / max(pa[t][1], 1)))}
    for c in cands:
        f = c['f']
        q = F.features({'id': c['id'], 'n': c['n'], 'st': pv.get(c['id']) or {}, 'pos': c['pos']})
        ab = ESPN_NFLV.get(tmap.get(c['tid']), tmap.get(c['tid']))
        f.update(prev_gp=float((pv.get(c['id']) or {}).get('gene.gamesPlayed') or 0), prev_yds=q['yds'],
                 prev_def=q['sacks'] + q['dint'], prev_ap=float(ap.get(NM.key(c['n']), 0)),
                 prev_dpoy=float(dpw.get(NM.key(c['n']), 0)), drank=float(rk.get(ab, 16)))
        f['p17'] = 1.0 if f['prev_gp'] > 0 else 0.0          # last season's line a team game, for the games-left rate
        for k in LEFT_BLEND: f['p17_' + k] = q[k] / 17


nfl_enrich.games = []
NFL_MORE_LEFT = [('pass_y', 'yds'), ('rush_y', 'yds'), ('rec_y', 'yds'), ('ptd', 'count'), ('rtd', 'count'), ('ctd', 'count'),
                 ('int', 'count'), ('rec', 'count'), ('sacks', 'count'), ('dint', 'count'), ('tackles', 'yds'), ('tfl', 'count'),
                 ('pd', 'count'), ('ff', 'count'), ('itd', 'count'), ('qbh', 'count')]
ESPN_NFLV = {'WSH': 'WAS', 'LAR': 'LA'}
AFC = {'BAL', 'BUF', 'CIN', 'CLE', 'DEN', 'HOU', 'IND', 'JAX', 'KC', 'LV', 'LAC', 'MIA', 'NE', 'NYJ', 'PIT', 'TEN'}


def nfl_more(fit, rng, cands, teams, tmap, S, sims=SIMS):
    """the Nov 23 2026 races (scripts/awards_football_more.py): Comeback Player, Coach of the Year, the All-Pro position
    races (top k), each run only if it passed; prior-season inputs from the fit's _prev and the ESPN line the season
    before. yields (award, pool, P, draw, shown stats)"""
    import awards_football as F
    prev = fit.get('_prev', {})
    base = football_draw(teams, NFL_MORE_LEFT, 'nfl')

    def draw(c, td, rng):
        f = base(c, td, rng)
        if f is not None: f['rec_td'] = f['rtd'] + f['ctd']
        return f
    draw.teams = base.teams
    spec = fit.get('cpoy')
    if spec and spec['test'].get('pass'):
        big = lambda f: (not f['def'] and f['yds'] * 17 / max(teams[f['tid']][1], 1) >= 400) or (f['def'] and max(f['tackles'], 0) * 17 / max(teams[f['tid']][1], 1) >= 30) or f['sacks'] >= 3 or f['dint'] >= 2
        pl = prune([c for c in cands if not c['f']['rookie'] and big(c['f'])], spec, draw, rng)
        yield 'cpoy', pl, race(pl, spec, draw, rng, sims), draw, [('yds', 'YDS', '%.0f'), ('td', 'TD', '%.0f'), ('sacks', 'SCK', '%.1f'), ('prev_gp', 'GP LY', '%.0f')]
    ap_spec = fit.get('allpro')
    if ap_spec and ap_spec['test'].get('pass'):
        for g, (rule, _, _, _) in F.AP_GROUPS.items():
            sp = dict(ap_spec['races'][g], label='All-Pro ' + {'FRONT': 'DL/LB'}.get(g, g), k=ap_spec['k'][g])
            aw = 'allpro_' + g.lower()
            fit[aw] = sp                                    # in memory: main() reads the race's spec from the fit
            pl = [c for c in cands if rule(dict(c['f'], pos=c['pos']))]
            if not pl: continue
            show = {'QB': [('yds', 'YDS', '%.0f'), ('td', 'TD', '%.0f'), ('wp', 'W%', 'pct')],
                    'RB': [('scrim', 'SCRIM', '%.0f'), ('rec_td', 'TD', '%.0f'), ('wp', 'W%', 'pct')],
                    'WR': [('rec_y', 'YDS', '%.0f'), ('ctd', 'TD', '%.0f'), ('rec', 'REC', '%.0f')],
                    'TE': [('rec_y', 'YDS', '%.0f'), ('ctd', 'TD', '%.0f'), ('rec', 'REC', '%.0f')],
                    'FRONT': [('sacks', 'SCK', '%.1f'), ('qbh', 'QBH', '%.0f'), ('tackles', 'TKL', '%.0f')],
                    'DB': [('dint', 'INT', '%.0f'), ('pd', 'PD', '%.0f'), ('tackles', 'TKL', '%.0f')]}[g]
            pl = sorted(pl, key=lambda c: -sum(b * ((c['f'][x] - m) / v) for b, x, m, v in zip(sp['b'], sp['cols'], sp['mu'], sp['sd'])))[:60]
            yield aw, pl, race_k(pl, sp, draw, rng, sp['k'], sims), draw, show
    spec = fit.get('coy')
    if spec and spec['test'].get('pass'):
        import awards_nflverse as V
        G = nfl_enrich.games
        co, w25 = {}, {}
        for x in G:
            if x['game_type'] != 'REG' or int(x['season']) not in (S - 1, S): continue
            for tm, c, me, op in ((x['home_team'], x['home_coach'], x['home_score'], x['away_score']), (x['away_team'], x['away_coach'], x['away_score'], x['home_score'])):
                tm = V.TEAM_FIX.get(tm, tm)
                co.setdefault((int(x['season']), tm), {}).setdefault(c, 0)
                if me not in ('', 'NA'): co[(int(x['season']), tm)][c] += 1
                if int(x['season']) == S - 1 and me not in ('', 'NA'):
                    w25[tm] = w25.get(tm, 0) + (1 if int(me) > int(op) else .5 if me == op else 0)
        top = lambda d: max(d, key=d.get) if d else None
        tot = (prev.get('wintot') or {}).get(str(S), {})
        cc = []
        for tid, ab in tmap.items():
            if tid not in teams: continue
            nv = ESPN_NFLV.get(ab, ab)
            now = top(co.get((S, nv), {}))
            if not now: continue
            cc.append({'id': 'coach' + tid, 'n': now, 'tid': tid, 'tm': ab, 'logo': f'/img/nfl/{ab.lower()}.png', 'afc': nv in AFC,
                       'tot': tot.get(nv, 8.5), 'wprev': w25.get(nv, 8.5), 'first': 0.0 if top(co.get((S - 1, nv), {})) == now else 1.0})

        def cdraw(c, td, rng):
            G_ = teams[c['tid']][4]
            w = td[c['tid']] * G_
            conf = sorted((v for t, v in td.items() if (tmap.get(t) and (ESPN_NFLV.get(tmap[t], tmap[t]) in AFC) == c['afc'])), reverse=True)
            return {'w': w, 'dtot': w - c['tot'], 'dprev': w - c['wprev'], 'first': c['first'], 'bye': 1.0 if td[c['tid']] >= conf[min(1, len(conf) - 1)] else 0.0,
                    'tot': c['tot']}
        cdraw.teams = base.teams
        yield 'coy', cc, race(cc, spec, cdraw, rng, sims), cdraw, [('w', 'W', '%.1f'), ('dprev', '+/- LY', '%+.1f')]


NFLV_TEAM = {'LA': 'LAR', 'WAS': 'WSH'}
OFF, DEF = ('QB', 'RB', 'WR', 'TE'), ('DL', 'LB', 'DB')
SV_SHOW = [('svar', 'SVAR', '%.2f'), ('sv', 'SV', '%.1f')]
# football's conviction pools: the season value boards (SV / SVAR: this season only) by the award's position rule,
# every award a position with SV can win, voter model or not. No SV: OL, K, P (NFL); OL, defence, K, P (CFB).
NFL_CONV = [('mvp', lambda c: True), ('opoy', lambda c: c['pos'] in OFF), ('dpoy', lambda c: c['pos'] in DEF),
            ('oroy', lambda c: c['rookie'] and c['pos'] in OFF), ('droy', lambda c: c['rookie'] and c['pos'] in DEF)]
CFB_CONV = [('heisman', lambda c: True), ('obrien', lambda c: c['pos'] == 'QB'), ('doak', lambda c: c['pos'] == 'RB'),
            ('bilet', lambda c: c['pos'] == 'WR'), ('mackey', lambda c: c['pos'] == 'TE'),
            ('unitas', lambda c: c['pos'] == 'QB' and c.get('cls') in UNITAS_CLS)]
UNITAS_CLS = {'Sr', 'RS-Sr', 'Gr', 'RS-Gr', 'RS-Jr'}      # Unitas Golden Arm: seniors and fourth-year juniors


def war_lead(sport, teams, rng):
    """football's conviction races: SVAR to date (scripts/nfl_qb.py, nfl_season_value.py, cfb_season_value.py) run
    out over the team's games left at its pace so far (the box stats' own draw: spread 30% of the rest), P(lead) by
    pool. teams: {tid: (wins, games, mean final wins, sd, G)}."""
    if CONV is None: return
    cands = []
    V = jload(os.path.join(ROOT, 'data', f'{sport}_season_value.json'), {}) or {}
    if sport == 'nfl':
        tid = {v: k for k, v in war_lead.tmap.items()}
        rook = {NM.key(r['n']) for r in (jload(os.path.join(ROOT, 'static', 'data', 'nfl-war.json'), {}) or {}).get('players', []) if r.get('rook')}
        Q = [dict(r, pos='QB', pts=r.get('spts'), ph=r.get('photo')) for r in (jload(os.path.join(ROOT, 'data', 'nfl_qb.json'), {}) or {}).get('rows', [])]
        for r in Q + V.get('skill', []) + V.get('defense', []):
            ab = (r.get('t') or '').split('/')[-1]
            ab = NFLV_TEAM.get(ab, ab)
            if r.get('svar') is None or ab not in tid: continue
            cands.append({'id': len(cands), 'n': r['n'], 'tid': tid[ab], 'tm': ab, 'pos': r.get('pos'), 'phu': r.get('ph') or None,
                          'rookie': NM.key(r['n']) in rook, 'f': {'svar': r['svar'], 'sv': r.get('pts') or 0}})
    else:
        tid = {v[1]: k for k, v in war_lead.logos.items()}
        for r in [dict(r, pos='QB') for r in V.get('qbs', [])] + V.get('skill', []):
            if r.get('svar') is None or r.get('t') not in tid: continue
            cands.append({'id': len(cands), 'n': r['n'], 'tid': tid[r['t']], 'tm': r['t'], 'logo': r.get('lo'), 'pos': r.get('pos'),
                          'ph': r.get('id'), 'cls': r.get('cls'), 'f': {'svar': r['svar'], 'sv': r.get('pts') or 0}})
    draw = football_draw(teams, [('svar', 'yds')], sport)
    for aw, ok in (NFL_CONV if sport == 'nfl' else CFB_CONV):
        lead(aw, [c for c in cands if ok(c)], draw, 'svar', SV_SHOW, rng)
    if sport == 'nfl': nfl_conv_more(cands, rook, draw, rng)


# Nov 23 2026: Comeback Player of the Year = SV players (not rookies) with fewer than CPOY_GP games last season (nflverse
# weekly lines of the finished season); All-Pro = the AP first team's position groups, top k on SVAR (k = the fewest
# the AP named in a season 2005-25, scripts/awards_football_more.py)
CPOY_GP = 9
ALLPRO_CONV = [('allpro_qb', 'All-Pro QB', ('QB',), 1), ('allpro_rb', 'All-Pro RB', ('RB',), 1),
               ('allpro_wr', 'All-Pro WR', ('WR',), 2), ('allpro_te', 'All-Pro TE', ('TE',), 1),
               ('allpro_front', 'All-Pro DL/LB', ('DL', 'LB'), 7), ('allpro_db', 'All-Pro DB', ('DB',), 4)]


def nfl_conv_more(cands, rook, draw, rng):
    try:
        import awards_nflverse as V
        S = int((jload(os.path.join(ROOT, 'data', 'nfl_season_value.json'), {}) or {}).get('season') or dt.date.today().year)
        gp = {}
        for x in V.nfl_weekly(S - 1):
            gp.setdefault(x['id'], {'n': x['n'], 'pos': x['grp'], 'g': 0})['g'] += 1
        m = NM.Matcher(list(gp.values()), name='n', team=None, pos='pos')
        pool = [c for c in cands if not c['rookie'] and ((m.find(c['n'], pos=c['pos'])[0] or {}).get('g', 0) < CPOY_GP)]
        lead('cpoy', pool, draw, 'svar', SV_SHOW, rng)
        if 'cpoy' in CONV: CONV['cpoy'].label = 'CPOY'
    except Exception as e:
        print('nfl cpoy conviction skipped:', e)
    for aw, lab, ps, k in ALLPRO_CONV:
        lead(aw, [c for c in cands if c['pos'] in ps], draw, 'svar', SV_SHOW, rng, k=k)
        if aw in CONV: CONV[aw].label = lab


war_lead.tmap, war_lead.logos = {}, {}
DROY_LEFT = [('sacks', 'count'), ('dint', 'count'), ('tfl', 'count'), ('pd', 'count'), ('ff', 'count'), ('tackles', 'yds'),
             ('dtd', 'count')]


def nfl_droy(fit, rng, teams, tmap, S, sims=SIMS):
    """Defensive Rookie of the Year: the rookie defenders of nflverse's weekly lines (the ESPN leader lists hold a handful)"""
    spec = fit.get('droy')
    if not spec or not spec['test'].get('pass'): return None
    import awards_nflverse as V
    W = V.nfl_weekly(S, fresh=True)
    if not W: return None
    RK = V.rookies()
    espn = {r['gsis_id']: r.get('espn_id') for r in V.nfl_file('players.csv', '')}
    tid = {ab: t for t, ab in tmap.items()}
    cands = []
    for r in V.nfl_totals(W, 99, {k: v[0] for k, v in RK.items()}, S).values():
        t = tid.get(NFLV_TEAM.get(r['tid'], r['tid']))
        if not (r['rookie'] and r['def']) or t not in teams: continue
        f = dict(r, tid=t, r1=1.0 if RK.get(r['id'], (0, None))[1] == 1 else 0.0)
        cands.append({'id': r['id'], 'n': r['n'], 'tid': t, 'tm': tmap[t], 'pos': r['pos'], 'ph': espn.get(r['id']) or None, 'f': f})
    if not cands: return None
    draw = football_draw(teams, DROY_LEFT, 'nfl')
    pool = prune(cands, spec, draw, rng)
    return 'droy', pool, race(pool, spec, draw, rng, sims), draw, [
        ('sacks', 'SCK', '%.1f'), ('tackles', 'TKL', '%.0f'), ('tfl', 'TFL', '%.0f'), ('dint', 'INT', '%.0f')]


def nfl_races(fit, rng, cands, teams, sims=SIMS):
    """yields (award, pool, P(win), draw, shown stats) for each passing NFL award. cands: to-date lines ('f' = features,
    'tid' = team key); teams: {tid: (wins, games, mean final wins, sd, G)}"""
    draw = football_draw(teams, [('pass_y', 'yds'), ('scrim', 'yds'), ('td', 'count'), ('int', 'count'),
                                 ('sacks', 'count'), ('dint', 'count'), ('tfl', 'count'), ('pd', 'count'), ('ff', 'count'),
                                 ('qbh', 'count')], 'nfl')
    if fit.get('dpoy2', {}).get('test', {}).get('pass') and all('drank' in c['f'] for c in cands):          # Nov 23 2026: DPOY v2 replaces the failed Nov 14 model
        fit['dpoy'] = dict(fit['dpoy2'], label='DPOY')
    for aw, pool_f, show in (
            ('mvp', lambda c: not c['f']['def'], [('yds', 'YDS', '%.0f'), ('td', 'TD', '%.0f'), ('int', 'INT', '%.0f'), ('wp', 'W%', 'pct')]),
            ('opoy', lambda c: not c['f']['def'], [('pass_y', 'PASS', '%.0f'), ('scrim', 'SCRIM', '%.0f'), ('td', 'TD', '%.0f'), ('wp', 'W%', 'pct')]),
            ('dpoy', lambda c: c['f']['def'], [('sacks', 'SCK', '%.1f'), ('dint', 'INT', '%.0f'), ('tfl', 'TFL', '%.0f'), ('wp', 'W%', 'pct')]),
            ('oroy', lambda c: not c['f']['def'] and c['f']['rookie'], [('yds', 'YDS', '%.0f'), ('td', 'TD', '%.0f'), ('wp', 'W%', 'pct')])):
        spec = fit.get(aw)
        if not spec or not spec['test'].get('pass'): continue
        pl = prune([c for c in cands if pool_f(c)], spec, draw, rng)
        p = race(pl, spec, draw, rng, sims)
        yield aw, pl, p, draw, show


# ---------------------------------------------------------------- soccer

def pick(rng, pairs):
    """one key from [(key, weight)]"""
    t = sum(max(w, 0) for _, w in pairs)
    if t <= 0: return None
    x = rng.random() * t
    for k, w in pairs:
        x -= max(w, 0)
        if x <= 0: return k
    return pairs[-1][0]


def soccer(fit, rng):
    """the Ballon d'Or for the season in progress: big-five players by GAR to date, run out to the season; each
    simulation draws every league's champion and the Champions League finalists from the season odds"""
    import awards_soccer as SO
    spec = fit.get('ballon')
    G = jload(os.path.join(ROOT, 'data', 'soccer_games.json'), {})
    if not spec or not spec['test'].get('pass') or not G.get('leagues'): return None
    S = int(G['season'])
    rows, _ = SO.season_rows(S)
    lg_t, tinfo = {}, {}
    for lg, L in G['leagues'].items():
        n = len(L['teams'])
        lg_t[lg] = [(t['id'], t.get('title') or 0) for t in L['teams']]
        for t in L['teams']: tinfo[t['id']] = (t.get('gp') or 0, 2 * (n - 1))
    U = (G.get('uefa') or {}).get('uefa.champions', {}).get('teams', [])
    uw = [(t['id'], t.get('win') or 0) for t in U]
    ul = {t['id']: max((t.get('fin') or 0) - (t.get('win') or 0), 0) for t in U}
    prev = fit.get('_prev', {}).get('ballon', {})
    def cand(r):
        return {'id': r['id'], 'n': r['n'], 'tid': r['tid'], 'tm': r['team'], 'lg': r['lg'], 'pos': r.get('pos'),
                'logo': f"/img/soccer/{r['tid']}.png", 'gar': r['gar'], 'svar': r.get('svar') or 0.0, 'ga': r['g'] + r['a'],
                'prev': prev.get(NM.key(r['n']), 0)}
    cands = [cand(r) for r in sorted(rows, key=lambda r: -r['gar'])[:SO.POOL_N] if r['tid'] in tinfo]
    # conviction pool: the season's best by SVAR (season value over replacement, scripts/soccer_sv.py)
    conv = [cand(r) for r in sorted((r for r in rows if r.get('svar') is not None), key=lambda r: -r['svar'])[:SO.POOL_N] if r['tid'] in tinfo]
    ph = {r['p']: r.get('ph') for r in (jload(os.path.join(SO.WAR, f'{S}.json'), {}) or {}).get('players', [])}
    for c in cands + conv:
        if ph.get(c['id']): c['phu'] = 'https://img.a.transfermarkt.technology/portrait/medium/' + ph[c['id']]

    def teams_draw(rng):
        td = {'champ': {pick(rng, v) for v in lg_t.values()}}
        w = pick(rng, uw)
        td['uw'], td['ul'] = w, pick(rng, [(t, x) for t, x in ul.items() if t != w])
        return td

    def draw(c, td, rng):
        gp, tot = tinfo[c['tid']]
        gr = games_left(rng, max(tot - gp, 0), .93, 'soccer')
        out = {}
        for k, kind in (('gar', 'yds'), ('svar', 'yds'), ('ga', 'count')):
            mu = c[k] / max(gp, 1) * gr
            out[k] = c[k] + (gauss(rng, mu, .3 * abs(mu)) if kind == 'yds' else max(gauss(rng, mu, math.sqrt(max(mu, 0))), 0))
        out.update(lgw=1.0 if c['tid'] in td['champ'] else 0.0, ucl=1.0 if c['tid'] == td['uw'] else .5 if c['tid'] == td['ul'] else 0.0,
                   natw=0.0, prev=c['prev'], uclw=1.0 if c['tid'] == td['uw'] else 0.0)
        return out

    draw.teams = teams_draw
    show = [('gar', 'GAR', '%.1f'), ('ga', 'G+A', '%.0f'), ('lgw', 'LG', 'pct'), ('uclw', 'UCL', 'pct')]
    lead('ballon', conv, draw, 'svar', [('svar', 'SVAR', '%.1f'), ('ga', 'G+A', '%.0f'), ('lgw', 'LG', 'pct'), ('uclw', 'UCL', 'pct')], rng)
    pool = prune(cands, spec, draw, rng)
    p = race(pool, spec, draw, rng)
    out = [('ballon', rows_out(pool, p, draw, show, rng), show)]
    out += soccer_more(fit, rng, S, rows, G, tinfo, ph, teams_draw)
    return {'season': f'{S - 1}-{str(S)[2:]}', 'races': out, 'logo': 'soccer'}


def soccer_more(fit, rng, S, rows, G, tinfo, ph, teams_draw):
    """the league player-of-the-season awards, Golden Boy, Kopa, Yashin (scripts/awards_soccer_more.py) and each league's
    Golden Boot. Predictive where the voter model passed; conviction (P(lead) on SVAR, Golden Boot on goals, the games
    left at this season's own rate) for every one"""
    import awards_soccer_more as SM
    xp = {}
    for lg, L in G['leagues'].items():
        n = len(L['teams'])
        for t in L['teams']:
            left = max(2 * (n - 1) - (t.get('gp') or 0), 0)
            xp[t['id']] = (t.get('xpts') or 0, 1.2 * math.sqrt(left), 3 * 2 * (n - 1), t.get('pts') or 0)
    today = dt.date.today()
    to_end = (dt.date(S, 7, 1) - today).days / 365.25            # the file's age is today's; the rules read July 1
    age = {r['p']: (r.get('age') or 30) + to_end for r in (jload(os.path.join(SO_WAR(), f'{S}.json'), {}) or {}).get('players', [])}

    def cand(r, aw):
        c = {'id': r['id'], 'n': r['n'], 'tid': r['tid'], 'tm': r['team'], 'lg': r['lg'], 'pos': r.get('pos'),
             'logo': f"/img/soccer/{r['tid']}.png", 'gar': r['gar'], 'svar': r.get('svar') or 0.0, 'ga': r['g'] + r['a'],
             'g': r['g'], 'min': r['min'], 'age': age.get(r['id'], 30), 'prev': fit.get('_prev', {}).get(aw, {}).get(NM.key(r['n']), 0)}
        if ph.get(r['id']): c['phu'] = 'https://img.a.transfermarkt.technology/portrait/medium/' + ph[r['id']]
        return c

    def draw(c, td, rng):
        gp, tot = tinfo[c['tid']]
        gr = games_left(rng, max(tot - gp, 0), .93, 'soccer')
        o = {}
        for k, kind in (('gar', 'yds'), ('svar', 'yds'), ('ga', 'count'), ('g', 'count')):
            mu = c[k] / max(gp, 1) * gr
            o[k] = c[k] + (gauss(rng, mu, .3 * abs(mu)) if kind == 'yds' else max(gauss(rng, mu, math.sqrt(max(mu, 0))), 0))
        x0, sd, P, now = xp.get(c['tid'], (0, 0, 1, 0))
        o.update(lgw=1.0 if c['tid'] in td['champ'] else 0.0, ucl=1.0 if c['tid'] == td['uw'] else .5 if c['tid'] == td['ul'] else 0.0,
                 natw=0.0, prev=c['prev'], age=c['age'], tppg=max(gauss(rng, x0, sd), now) / P,
                 uclw=1.0 if c['tid'] == td['uw'] else 0.0)
        return o

    draw.teams = teams_draw
    live = [r for r in rows if r['tid'] in tinfo]
    out = []
    for aw, (lab, _, lg, depth) in SM.AWARDS.items():
        spec = fit.get(aw)
        if not spec: continue
        if lg: P = [cand(r, aw) for r in live if r['lg'] == lg]
        elif aw == 'yashin': P = [cand(r, aw) for r in live if r.get('pos') == 'GK']
        else: P = [c for c in (cand(r, aw) for r in live) if c['age'] < 20.5]
        if not P: continue
        top = sorted(P, key=lambda c: -c['svar'])[:80]
        cshow = [('svar', 'SVAR', '%.1f'), ('ga', 'G+A', '%.0f'), ('lgw', 'LG', 'pct')]
        lead(aw, top, draw, 'svar', cshow, rng)
        if not spec['test'].get('pass'): continue
        show = [('gar', 'GAR', '%.1f'), ('ga', 'G+A', '%.0f'), ('lgw', 'LG', 'pct'), ('tppg', 'PTS%', 'pct')]
        pool = prune(sorted(P, key=lambda c: -c['gar'])[:120], spec, draw, rng)
        out.append((aw, rows_out(pool, race(pool, spec, draw, rng), draw, show, rng), show))
    # Golden Boot: the league's top scorer (a stat title; conviction only: there is no to-date archive of big-five
    # scorers to test a projection on)
    for lg, nm in SM.LEAGUES.items():
        aw = 'boot_' + lg.split('.')[0]
        if aw not in fit: continue
        P = sorted([cand(r, aw) for r in live if r['lg'] == lg], key=lambda c: -c['g'])[:60]
        lead(aw, P, draw, 'g', [('g', 'G', '%.0f'), ('ga', 'G+A', '%.0f')], rng)
    return out


def SO_WAR():
    import awards_soccer as SO
    return SO.WAR


# ---------------------------------------------------------------- output

NULL_LABEL = {'svar': 'SVAR', 'vorx': 'VORX', 'dxpm': 'D-XPM', 'war': 'WAR', 'gsax': 'GSAx', 'bpm': 'BPM', 'yds': 'yards',
              'td': 'TDs', 'sacks': 'sacks', 'dint': 'INTs', 'pass_y': 'pass yards', 'ptd': 'pass TDs', 'gross': 'gross average',
              'rush_y': 'rush yards', 'rtd': 'rush TDs', 'rec_y': 'receiving yards', 'ctd': 'receiving TDs', 'tackles': 'tackles',
              'fgm': 'FGs', 'fgpct': 'FG%', 'pd': 'PDs', 'gar': 'GAR', 'pts': 'points', 'g': 'goals', 'gd': 'defensive goals (WAR)'}
NULL_LABEL.update({'d_vorx': 'VORX gain', 'dbpm': 'DBPM', 'rvorx': 'VORX', 'rdxpm': 'D-XPM', 'rd_vorx': 'VORX gain', 'xpm': 'XPM'})     # NBA / CBB races added Nov 23 2026
POLY[('cbb', 'naismith')] = POLY[('cbb', 'wooden')]              # the market is on the Naismith
BUILD = {'nba': nba, 'nhl': nhl, 'cbb': cbb, 'cfb': cfb, 'nfl': nfl, 'soccer': soccer}


def main(argv):
    fit = jload(FIT, {})
    cur = jload(OUT, {}) or {}
    want = [a for a in argv if a in BUILD] or list(BUILD)
    rng = random.Random(20261114)
    global CONV
    for sp in want:
        if sp not in fit: continue
        CONV = {}
        try:
            res = BUILD[sp](fit[sp], rng)
        except Exception as e:
            import traceback; traceback.print_exc()
            print(sp, 'failed, keeping the last race:', e); continue
        if not res or not res['races']: continue
        races = []
        for aw, rows, show in res['races']:
            spec = fit[sp][aw]
            if spec.get('stat'):                   # a stat title: P(lead) is the race; its as-of test is the about
                races.append({'key': aw, 'label': spec['label'], 'rows': rows, 'mkt': False, 'stat': True, 'about': spec['about'],
                              'show': [{'k': k, 'l': l, 'f': f} for k, l, f in show]})
                print(sp, spec['label'], 'top:', ', '.join(f"{r['n']} {r['p']:.0%}" for r in rows[:5]))
                continue
            mk, bl = (False, False) if spec.get('k') else attach_market(rows, sp, aw)
            t = spec['test']
            races.append({'key': aw, 'label': spec['label'], 'rows': rows, 'mkt': mk,
                          'show': [{'k': k, 'l': l, 'f': f} for k, l, f in show],
                          'test': {'n': t['model']['n'], 'hit': t['model']['hit'], 'hit0': t['null']['hit'],
                                   'pw': t['model']['pw'], 'll': t['model']['ll'], 'll0': t['null']['ll'], 't': t['t'],
                                   'from': spec['seasons'][0], 'to': spec['seasons'][1],
                                   'null': [NULL_LABEL.get(c, c) for c in spec['null']]}})
            if spec.get('k'): races[-1]['k'] = spec['k']
            if bl: races[-1]['blend'] = MKT_W
            top = rows[0] if rows else {}
            print(sp, spec['label'], 'top:', ', '.join(f"{r['n']} {r['p']:.0%}" + (f" (mkt {r['mkt']:.0%}, model {r['pm']:.0%})" if r.get('pm') is not None and 'mkt' in r else '') for r in rows[:5]))
        # conviction: P(lead) on our own metric; each side's rows carry the other's number (pc / pp) where he is on both
        conv = []
        pred = {r['key']: {NM.key(x['n']): x['p'] for x in r['rows']} for r in races}
        for aw, rows in CONV.items():
            allp = {NM.key(x['n']): x['p'] for x in list(rows) + list(rows.rest)}
            for r in races:
                if r['key'] == aw:
                    for x in r['rows']:
                        if NM.key(x['n']) in allp: x['pc'] = allp[NM.key(x['n'])]
            for x in rows:
                if NM.key(x['n']) in pred.get(aw, {}): x['pp'] = pred[aw][NM.key(x['n'])]
            lab = getattr(rows, 'label', None) or fit[sp][aw]['label']
            conv.append({'key': aw, 'label': lab, 'rows': list(rows), 'pred': aw in pred,
                         'metric': NULL_LABEL.get(rows.metric, rows.metric),
                         'show': [{'k': k, 'l': l, 'f': f} for k, l, f in rows.show]})
            if getattr(rows, 'k', None): conv[-1]['k'] = rows.k
            if getattr(rows, 'about', None): conv[-1]['about'] = rows.about
            print(sp, lab, 'conviction:', ', '.join(f"{r['n']} {r['p']:.0%}" for r in rows[:5]))
        cur[sp] = {'season': res['season'], 'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                   'sims': SIMS, 'logo': res['logo'], 'races': races, 'conv': conv}
        if abs(res.get('T', 1) - 1) > 1e-9: cur[sp]['temp'] = round(res['T'], 3)
    json.dump(cur, open(OUT, 'w'), indent=1, sort_keys=True)
    print('wrote', OUT)


if __name__ == '__main__':
    main(sys.argv[1:])
