"""Games to watch: the week's best games across every sport, ranked by one watchability score (display only).

Reads the site's own files, no fetch: data/<sport>_games.json (ratings, win probabilities, totals, the season sims'
odds on each team's power row), data/brackets/cfb.json (CFP odds), data/cfb_rank.json, the player value files
(static/data/nfl-war.json, nba-xpm, nhl-war, data/soccer_war.json, data/cbb_players.json, the CFB game rows) and
static/data/injuries.json (PR #1129 tags). Writes data/watch.json, read by layouts/shortcodes/watch.html (Standings,
"games to watch") and the GFX card (assets/js/gfx.js buildWatch). Rerun by the odds-snap workflow every half hour.

Window: games that start within the next 7 days. A listed game that has started moves to `played` with its frozen W
and its live / final score (ESPN scoreboard by event id; tennis and CS2 from the site's own files), and drops 24 hours
after its final (or 48 hours after its start when no final is seen).

Components, each 0-1 and put on one scale inside its own sport, so no sport dominates by construction:
  Q quality    mean of the two sides' rating scores: 1 - (rank - .5) / min(N, 60) in the sport's rating order
               (power rating; CFB ARK ranking; CBB power rank), 0 past 60, so a 300-team pool and a 32-team league
               put their top teams on the same footing
  C closeness  1 - (p home - p away)^2, percentile among the sport's games in its file
  S stars      each side's top three healthy players (value x chance to play: injury tags O/IR/OFS 0, D .25,
               Q/DTD .6; game-level play chances where the model has them), weighted 1/.7/.5, scored by rank in
               the sport's team pool like Q, mean of the two sides
  L leverage   swing in the season sims' odds from one result: for a target with probability p and n games left,
               dP = phi(Phi^-1(p)) / sqrt(n/4 + 1/2) (a normal approximation of the sims, like baseball's leverage
               index); targets weighted (playoff 1, division/bye/top four .5, title or relegation 1 in soccer);
               a side's L = min(1, weighted dP / .35), an absolute scale (dP is a probability in every sport); the
               game takes .6 x the higher side + .4 x the lower; postseason = 1
  T total      projected total points/goals, percentile among the sport's games
Score = 100 x (.30 Q + .20 C + .20 S + .20 L + .10 T) + bonus (rivalry 6, division or conference game 2,
both sides ranked 4, one ranked 1), capped at 100. The list keeps the top 15 with at most 4 games a sport.
"""
import json, math, os, sys, urllib.request, datetime as D
from statistics import NormalDist
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ET = ZoneInfo('America/New_York')
N01 = NormalDist()
W = {'q': .30, 'c': .20, 's': .20, 'l': .20, 't': .10}
BONUS = {'rival': 6, 'div': 2, 'ranked2': 4, 'ranked1': 1}
TOP, PER_SPORT, DAYS, CAP, LREF = 15, 4, 7, 60, .35
AVAIL = {'O': 0, 'OFS': 0, 'IR': 0, 'PUP': 0, 'NFI': 0, 'SUSP': 0, 'D': .25, 'Q': .6, 'DTD': .6}
STATUS = {'out': 0, 'out (season)': 0, 'injured reserve': 0, 'doubtful': .25, 'questionable': .6, 'day-to-day': .6}
LABEL = {'nfl': 'NFL', 'cfb': 'CFB', 'nba': 'NBA', 'cbb': 'CBB', 'nhl': 'NHL', 'soccer': 'SOC', 'tennis': 'TEN', 'cs2': 'CS2'}
ICON = {'nfl': 'football', 'cfb': 'football', 'nba': 'basketball', 'cbb': 'basketball', 'nhl': 'hockey',
        'soccer': 'soccer', 'tennis': 'tennis', 'cs2': 'cs'}
# ESPN team codes in the game files -> the player files' codes (scripts/injury_tags.py ABBR)
NBA_CODE = {'BKN': 'BRK', 'CHA': 'CHO', 'GS': 'GSW', 'NO': 'NOP', 'NY': 'NYK', 'PHX': 'PHO', 'SA': 'SAS', 'UTAH': 'UTA', 'WSH': 'WAS'}


def load(p, default=None):
    try:
        with open(os.path.join(ROOT, p)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def ts(s):
    if not s:
        return None
    s = str(s).replace('Z', '+00:00')
    try:
        t = D.datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=D.timezone.utc)


def pctl(pool):
    """value -> mid-rank percentile in pool (ties share their middle rank)."""
    xs = sorted(v for v in pool if v is not None)
    n = len(xs)
    if not n:
        return lambda v: .5
    def f(v):
        if v is None:
            return 0.0
        lo = sum(1 for x in xs if x < v); eq = sum(1 for x in xs if x == v)
        return (lo + eq / 2) / n
    return f


def toprank(pool, cap=None):
    """value -> 1 - (rank - .5) / min(N, cap): rank 1 near 1, 0 past the cap."""
    xs = sorted((v for v in pool if v is not None), reverse=True)
    m = min(len(xs), cap or CAP) or 1
    def f(v):
        if v is None:
            return 0.0
        r = 1 + sum(1 for x in xs if x > v)
        return max(0.0, 1 - (r - .5) / m)
    return f


def rkscore(r, n, cap=None):
    return max(0.0, 1 - (float(r) - .5) / min(n, cap or CAP)) if r else 0.0


def dp(p, n):
    """Swing in P(target) from one result: normal approximation of the season sims."""
    if p is None:
        return 0.0
    p = min(max(float(p), .001), .999)
    return min(.5, N01.pdf(N01.inv_cdf(p)) / math.sqrt(max(n, 0) / 4 + .5))


def top3(vals):
    v = sorted((x for x in vals if x and x > 0), reverse=True)[:3]
    return sum(w * x for w, x in zip((1, .7, .5), v))


# ---- injuries (static/data/injuries.json: sport -> name key -> [[tag, hover, logo, team]]) ----
INJ = load('static/data/injuries.json', {}) or {}


def tag_avail(sport, name, team_hint=''):
    rows = (INJ.get(sport) or {}).get(names.key(name)) or []
    if not rows:
        return 1.0
    if len(rows) > 1 and team_hint:
        th = team_hint.lower()
        pick = [r for r in rows if th in (str(r[2]).lower() + ' ' + str(r[3]).lower())]
        rows = pick or rows
    return min(AVAIL.get(r[0], 1.0) for r in rows)


def ranked(r):
    return r is not None and 0 < int(r) <= 25


# ---- per sport: games -> common rows. Each row: sport, id, kick, a/h {n, ab, logo, rk}, ph, pa, tot,
#      qa/qh (rating pctl), sa/sh (star value), la/lh (leverage), flags; plus the sport's team pools for S and L ----
def pro(sport, nteams, targets, player_file, val_key, code_map=None, logo_dir=None):
    G = load(f'data/{sport}_games.json') or {}
    power = G.get('power') or []
    if not power:
        return [], {}
    left = float(G.get('left') or 0) * 2 / max(nteams, 1)
    order = sorted(power, key=lambda t: -float(t.get('rating') or 0))
    qp = {t['t']: rkscore(i + 1, len(order)) for i, t in enumerate(order)}
    lev = {t['t']: sum(w * dp(t.get(k), left) for k, w in targets) for t in power}
    grp = {t['t']: t.get('dv') or t.get('div') for t in power}
    P = load(player_file) or {}
    by = {}
    for p in P.get('players') or []:
        tm = p.get('tm') or p.get('t')
        if tm and '/' not in str(tm):
            by.setdefault(tm, []).append(p)
    code_map = code_map or {}

    def stars(code, inj):
        pl = by.get(code_map.get(code, code), [])
        game = {names.key(i['name']): i for i in (inj or [])}
        vals, best = [], None
        for p in pl:
            v = float(p.get(val_key) or 0)
            gi = game.get(names.key(p['n']))
            if gi is not None:
                a = gi.get('p') if gi.get('p') is not None else STATUS.get(str(gi.get('status', '')).lower(), 1.0)
            else:
                a = tag_avail(sport, p['n'], code)
            vals.append(v * a)
            if a >= .5 and (best is None or v > best[1]):
                best = (p['n'], v)
        return top3(vals), best and best[0]

    pool_s = [stars(t['t'], None)[0] for t in power]
    full = (load('data/pro_team_names.json') or {}).get(sport) or {}
    rows = []
    for g in G.get('games') or []:
        if g.get('final'):
            continue
        h, a = g['home'], g['away']
        inj = g.get('inj') or {}
        sh, bh = stars(h, inj.get('home')); sa, ba = stars(a, inj.get('away'))
        lg = logo_dir or sport
        rows.append(dict(sport=sport, id=str(g.get('espn') or g.get('id')), kick=g.get('kick') or g.get('tip'),
                         a=dict(n=full.get(a, a), ab=a, logo=f'/img/{lg}/{a.lower()}.png'), h=dict(n=full.get(h, h), ab=h, logo=f'/img/{lg}/{h.lower()}.png'),
                         ph=g.get('pHome', .5), pa=1 - g.get('pHome', .5), tot=g.get('total'),
                         qa=qp.get(a, 0), qh=qp.get(h, 0), sa=sa, sh=sh, la=lev.get(a, 0), lh=lev.get(h, 0),
                         div=bool(g.get('div')) or (grp.get(a) is not None and grp.get(a) == grp.get(h)),
                         po=bool(g.get('po')), star=[ba, bh]))
    return rows, dict(s=pool_s, l=list(lev.values()))


def nfl():
    return pro('nfl', 32, [('playoff', 1), ('div', .5), ('seed1', .5)], 'static/data/nfl-war.json', 'war')


def nba():
    cur = (load('data/nba_xpm.json') or {}).get('current', 2027)
    return pro('nba', 30, [('playoff', 1), ('top6', .5)], f'static/data/nba-xpm/{cur}.json', 'vorx', NBA_CODE)


def nhl():
    cur = (load('data/nhl_war.json') or {}).get('current', 2027)
    return pro('nhl', 32, [('playoff', 1), ('divw', .5)], f'static/data/nhl-war/{cur}.json', 'war')


def cbb():
    G = load('data/cbb_games.json') or {}
    power = G.get('power') or []
    if not power:
        return [], {}
    n = len(power)
    left = float(G.get('left') or 0) * 2 / n
    qp = {str(t['id']): rkscore(t['rk'], n) for t in power if t.get('rk')}
    lev = {str(t['id']): dp((t.get('nc') or {}).get('bid'), left) + .5 * dp((t.get('nc') or {}).get('auto'), left) for t in power}
    conf = {str(t['id']): t.get('conf') for t in power}
    # board FV by team (logo path = team id), x the chance to play: the game's player projections (pr) where the
    # projection file has the game, else the injury tags
    A = load('static/data/cbb-all.json') or {}
    ci = {c: i for i, c in enumerate(A.get('cols') or [])}
    by = {}
    for r in A.get('rows') or []:
        fv = r[ci['fv']] if 'fv' in ci else None
        if fv is not None:
            by.setdefault(r[ci['logo']], []).append((r[ci['name']], float(fv)))
    pr = {}
    for g in (load('data/cbb_players.json') or {}).get('games') or []:
        pr[str(g.get('id'))] = {names.key(p['n']): p.get('pr') for p in g.get('players') or [] if p.get('pr') is not None}

    def team_stars(logo, gid=None, team=''):
        play = pr.get(str(gid), {}) if gid else {}
        vals, best = [], None
        for nm, fv in by.get(logo, []):
            a = play.get(names.key(nm))
            a = float(a) if a is not None else tag_avail('cbb', nm, team)
            vals.append(max(0.0, fv - 20) * a)
            if a >= .5 and (best is None or fv > best[1]):
                best = (nm, fv)
        return top3(vals), best and best[0]
    pool_s = [team_stars(lg)[0] for lg in by]
    rows = []
    for g in G.get('games') or []:
        if g.get('final') or g.get('score') and g.get('st') == 'post':
            continue
        h, a = g['home'], g['away']
        st = lambda t: team_stars(t.get('logo'), g.get('id'), t.get('n') or '')
        sh, bh = st(h); sa, ba = st(a)
        rows.append(dict(sport='cbb', id=str(g['id']), kick=g.get('kick'),
                         a=dict(n=a.get('n'), ab=a.get('ab'), logo=a.get('logo'), rk=a.get('ap')),
                         h=dict(n=h.get('n'), ab=h.get('ab'), logo=h.get('logo'), rk=h.get('ap')),
                         ph=g.get('pHome', .5), pa=1 - g.get('pHome', .5), tot=g.get('total'),
                         qa=qp.get(str(a.get('id')), 0), qh=qp.get(str(h.get('id')), 0), sa=sa, sh=sh,
                         la=lev.get(str(a.get('id')), 0), lh=lev.get(str(h.get('id')), 0),
                         div=bool(g.get('confGame')), po=bool((g.get('note') or '').lower().startswith(('ncaa', "men's basketball championship"))),
                         star=[ba, bh]))
    return rows, dict(s=pool_s, l=list(lev.values()))


def cfb():
    G = load('data/cfb_games.json') or {}
    R = load('data/cfb_rank.json') or {}
    rk = R.get('rk') or {}
    n = len(rk) or 1
    qp = {str(k): rkscore(v, n) for k, v in rk.items()}
    odds = (load('data/brackets/cfb.json') or {}).get('odds') or {}
    lev = {str(k): dp(o.get('cfp'), 1.5) + .5 * dp(o.get('bye'), 1.5) for k, o in odds.items()}
    pool_l = [lev.get(str(k), dp(0, 1.5)) for k in rk]
    conf = {str(t['tid']): t.get('conf') for t in R.get('teams') or []}
    abbr = {str(t['tid']): t.get('abbr') for t in R.get('teams') or []}
    rows, pool_s = [], []
    for g in G.get('games') or []:
        if g.get('score') and isinstance(g['score'], dict) and g['score'].get('final'):
            continue
        h, a = g['home'], g['away']
        def st(t):
            vals, best = [], None
            for p in (t.get('off') or []) + (t.get('def') or []):
                fv = p.get('fv')
                if fv is None:
                    continue
                inj = str(p.get('inj') or '').lower()
                av = STATUS.get(inj, 1.0) if inj and inj != 'none' else tag_avail('cfb', p['name'], t.get('name', ''))
                vals.append(max(0, fv - 20) * av)
                if av >= .5 and (best is None or fv > best[1]):
                    best = (p['name'], fv)
            return top3(vals), best and best[0]
        sh, bh = st(h); sa, ba = st(a)
        pool_s += [sh, sa]
        tot = g.get('total') if isinstance(g.get('total'), (int, float)) else (g.get('proj') or {}).get('total')
        rows.append(dict(sport='cfb', id=str(g['id']), kick=g.get('date'),
                         a=dict(n=a.get('name'), ab=abbr.get(str(a.get('id'))), logo=a.get('logo'), rk=a.get('rank')),
                         h=dict(n=h.get('name'), ab=abbr.get(str(h.get('id'))), logo=h.get('logo'), rk=h.get('rank')),
                         ph=g.get('pHome', .5), pa=1 - (g.get('pHome') or .5), tot=tot,
                         qa=qp.get(str(a.get('id')), 0), qh=qp.get(str(h.get('id')), 0), sa=sa, sh=sh,
                         la=lev.get(str(a.get('id')), 0), lh=lev.get(str(h.get('id')), 0),
                         div=conf.get(str(a.get('id'))) is not None and conf.get(str(a.get('id'))) == conf.get(str(h.get('id'))),
                         po=False, star=[ba, bh]))
    return rows, dict(s=pool_s, l=pool_l)


def soccer():
    G = load('data/soccer_games.json') or {}
    power = G.get('power') or []
    if not power:
        return [], {}
    order = sorted(power, key=lambda t: -float(t.get('rating') or 0))
    qp = {str(t['id']): rkscore(i + 1, len(order)) for i, t in enumerate(order)}
    size = {}
    for t in power:
        size[t['lg']] = size.get(t['lg'], 0) + 1
    def lev_of(t):
        if t.get('lg') == 'x':
            return 0.0
        n = max(1, 2 * (size.get(t['lg'], 18) - 1) - int(t.get('gp') or 0))
        return dp(t.get('title'), n) + .5 * dp(t.get('top4'), n) + dp(t.get('rel'), n)
    lev = {str(t['id']): lev_of(t) for t in power}
    # UEFA league phase: P(top 24) and P(top 8) from data/brackets/<cup>.json, about three matches left
    cups = {'uefa.champions': 'ucl', 'uefa.europa': 'uel', 'uefa.europa.conf': 'uecl'}
    ulev = {}
    for lg, k in cups.items():
        for tid, o in ((load(f'data/brackets/{k}.json') or {}).get('odds') or {}).items():
            ulev[(lg, str(tid))] = dp(o.get('ko'), 3) + .5 * dp(o.get('top8'), 3)
    by = {}
    for p in (load('data/soccer_war.json') or {}).get('players') or []:
        by.setdefault(names.team_key(p.get('team') or ''), []).append(p)
    def st(name):
        pl = by.get(names.team_key(name or ''), [])
        vals, best = [], None
        for p in pl:
            a = tag_avail('soccer', p['n'], name)
            vals.append(float(p.get('gar') or 0) * a)
            if a >= .5 and (best is None or float(p.get('gar') or 0) > best[1]):
                best = (p['n'], float(p.get('gar') or 0))
        return top3(vals), best and best[0]
    pool_s = [st(t.get('n'))[0] for t in power]
    lgname = {}
    for t in power:
        lgname[str(t['id'])] = t.get('lg')
    rows = []
    for g in G.get('games') or []:
        if g.get('final'):
            continue
        p = g.get('p') or [.4, .25, .35]
        h, a, lg = str(g['h']), str(g['a']), g.get('lg', '')
        kick = ts(g.get('tip'))
        po = lg == 'usa.1' and kick is not None and kick.month in (10, 11, 12)
        if lg in cups:
            la, lh = ulev.get((lg, a), 0), ulev.get((lg, h), 0)
        else:
            la, lh = lev.get(a, 0), lev.get(h, 0)
        sh, bh = st(g.get('hn')); sa, ba = st(g.get('an'))
        rows.append(dict(sport='soccer', id=str(g['id']), kick=g.get('tip'), lg=lg,
                         a=dict(n=g.get('an'), ab=g.get('aab'), logo=f'/img/soccer/{a}.png'),
                         h=dict(n=g.get('hn'), ab=g.get('hab'), logo=f'/img/soccer/{h}.png'),
                         ph=p[0], pa=p[2], tot=sum(g.get('l') or [0, 0]) or None,
                         qa=qp.get(a, .5 if lg == 'usa.1' else 0), qh=qp.get(h, .5 if lg == 'usa.1' else 0),
                         sa=sa, sh=sh, la=la, lh=lh, div=False, po=po, star=[ba, bh]))
    return rows, dict(s=pool_s, l=list(lev.values()) + list(ulev.values()))


# hours a game stays on after its start (no live feed here; finals drop sooner when the game file marks them)
LIVE = {'nfl': 3.5, 'cfb': 3.5, 'nba': 2.5, 'cbb': 2.2, 'nhl': 2.8, 'soccer': 2, 'tennis': 3, 'cs2': 3}
TEN_RD = {'F': 1, 'SF': .8, 'QF': .6, 'R16': .4, 'RR': .5, 'R32': .3}
TEN_LV = {'G': 1, 'F': 1, 'M': .8, 'A': .6, 'P': .6, '500': .6, 'C': .2}


def tennis():
    T = load('data/tennis.json') or {}
    rows, pool_q, pool_s = [], [], []
    tours = T.get('tours') or {}
    pid = {}
    for tour, t in tours.items():
        pl = t.get('players') or []
        n = len(pl) or 1
        for i, p in enumerate(sorted(pl, key=lambda p: -float(p.get('ark') or 0))):
            pid[p['id']] = (rkscore(i + 1, n, 50), p)
    def side(x):
        q, p = pid.get(x.get('id'), (0, {}))
        r = x.get('rank') or (p or {}).get('rank')
        s = max(0, 1 - (float(r) - 1) / 100) if r else 0
        nat = x.get('nat') or (p or {}).get('nat')
        return q, s, dict(n=x.get('n'), ab=str(x.get('n') or '').split(' ')[-1], logo=f'/img/flags/{nat}.png' if nat else None, rk=r if r and r <= 25 else None)
    for m in T.get('matches') or []:
        if m.get('state') == 'post':
            continue
        qa, sa, A = side(m.get('a') or {}); qh, sh, H = side(m.get('b') or {})
        lv = TEN_RD.get(m.get('rd'), .2) * TEN_LV.get(m.get('lv'), .5)
        p = m.get('p') or .5
        rows.append(dict(sport='tennis', id=str(m['id']), kick=m.get('tip'), lg=m.get('ev'), a=A, h=H,
                         ph=1 - p, pa=p, tot=5 if m.get('bo') == 5 else 3, qa=qa, qh=qh, sa=sa, sh=sh, la=lv, lh=lv,
                         div=False, po=False, star=[None, None], at=False))
    return rows, dict(s=[1 - i / 100 for i in range(100)], l=[TEN_RD[k] * TEN_LV[v] for k in TEN_RD for v in TEN_LV])


def cs2():
    C = load('data/cs2.json') or {}
    teams = {t['k']: t for t in C.get('teams') or []}
    n = len(teams) or 1
    rows = []
    for m in C.get('matches') or []:
        ka, kb = m.get('ka'), m.get('kb')
        ta, tb = teams.get(ka, {}), teams.get(kb, {})
        q = lambda t: rkscore(t.get('rk') or n, n, 30)
        bo = str(m.get('fmt') or 'Bo3')
        lv = .3 + (.4 if 'Bo5' in bo else .2 if 'Bo3' in bo else 0) + (.3 if str(ta.get('tier') or '') in ('S', '1') else 0)
        pa = float(m.get('pa') or .5)
        rows.append(dict(sport='cs2', id=str(m.get('id') or f"{ka}-{kb}-{m.get('ts')}"),
                         kick=D.datetime.fromtimestamp(m['ts'], D.timezone.utc).isoformat() if m.get('ts') else m.get('tip'),
                         lg=m.get('event'), a=dict(n=m.get('a'), ab=m.get('a'), logo=f'/img/cs2/{ka}.png' if ta.get('logo') else None, rk=ta.get('rk') if (ta.get('rk') or 99) <= 25 else None),
                         h=dict(n=m.get('b'), ab=m.get('b'), logo=f'/img/cs2/{kb}.png' if tb.get('logo') else None, rk=tb.get('rk') if (tb.get('rk') or 99) <= 25 else None),
                         ph=1 - pa, pa=pa, tot=None, qa=q(ta), qh=q(tb), sa=q(ta), sh=q(tb), la=lv, lh=lv,
                         div=False, po=False, star=[None, None], at=False))
    return rows, dict(s=[1 - (i + .5) / n for i in range(n)], l=[.3, .5, .6, .8, 1])


SPORTS = [('nfl', nfl), ('cfb', cfb), ('nba', nba), ('cbb', cbb), ('nhl', nhl), ('soccer', soccer), ('tennis', tennis), ('cs2', cs2)]


def rivalry_set():
    R = load('data/rivalries.json', {}) or {}
    out = {}
    for sport, pairs in R.items():
        if sport.startswith('_'):
            continue
        out[sport] = {frozenset(names.team_key(x) for x in p[:2]): (p[2] if len(p) > 2 else None) for p in pairs}
    return out


def score(sport, rows, pools, now, rivals):
    if not rows:
        return []
    cp = pctl([1 - (r['ph'] - r['pa']) ** 2 for r in rows])
    tp = pctl([r['tot'] for r in rows if r['tot'] is not None])
    raw_l = sport in ('tennis', 'cs2')   # star and event-stage levels already 0-1
    sp = (lambda v: float(v or 0)) if raw_l else toprank(pools.get('s') or [])
    lp = (lambda v: float(v or 0)) if raw_l else (lambda v: min(1.0, float(v or 0) / LREF))
    out = []
    riv = rivals.get(sport, {})
    for r in rows:
        k = ts(r['kick'])
        if k is None or k > now + D.timedelta(days=DAYS) or k <= now:
            continue
        q = (r['qa'] + r['qh']) / 2
        c = cp(1 - (r['ph'] - r['pa']) ** 2)
        s = (sp(r['sa']) + sp(r['sh'])) / 2
        la, lh = lp(r['la']), lp(r['lh'])
        l = 1.0 if r['po'] else .6 * max(la, lh) + .4 * min(la, lh)
        t = tp(r['tot']) if r['tot'] is not None else .5
        tags = []
        rv = False
        for ka, kh in ((r['a'].get('ab'), r['h'].get('ab')), (r['a'].get('n'), r['h'].get('n'))):
            if ka and kh and rv is False:
                rv = riv.get(frozenset((names.team_key(ka), names.team_key(kh))), False)
        b = 0
        if rv is not False:
            b += BONUS['rival']; tags.append(rv or 'rivalry')
        elif r['div']:
            b += BONUS['div']; tags.append('conference' if sport in ('cfb', 'cbb') else 'division')
        nr = ranked(r['a'].get('rk')) + ranked(r['h'].get('rk'))
        if nr == 2:
            b += BONUS['ranked2']; tags.append('ranked')
        elif nr == 1:
            b += BONUS['ranked1']
        if r['po']:
            tags.append('postseason')
        raw = 100 * (W['q'] * q + W['c'] * c + W['s'] * s + W['l'] * l + W['t'] * t)
        out.append(dict(sport=sport, lab=LABEL[sport], icon=ICON[sport], id=r['id'], kick=k.astimezone(D.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                        et=k.astimezone(ET).strftime('%a %-m/%-d %-I:%M %p'), ets=k.astimezone(ET).strftime('%a %-I:%M%p').lower().replace(':00', '')[:-1].capitalize(), lg=r.get('lg'),
                        a={x: v for x, v in r['a'].items() if v is not None}, h={x: v for x, v in r['h'].items() if v is not None},
                        at=r.get('at', True), ph=round(r['ph'], 3), pa=round(r['pa'], 3),
                        w=round(min(100.0, raw + b), 1),
                        parts=dict(q=round(100 * q), c=round(100 * c), s=round(100 * s), l=round(100 * l), t=round(100 * t), b=b),
                        tags=tags, stars=[x for x in r['star'] if x]))
    return out


# ---- scores for listed games that have started ----
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/'
PATH = {'nfl': 'football/nfl', 'cfb': 'football/college-football', 'nba': 'basketball/nba',
        'cbb': 'basketball/mens-college-basketball', 'nhl': 'hockey/nhl'}
EXTRA = {'cfb': '&groups=80&limit=400', 'cbb': '&groups=50&limit=400'}
KEEP_H, STALE_H = 24, 48


def espn_board(path, day, cache={}):
    key = (path, day)
    if key not in cache:
        sport = path.split('/')[0] if '/' in path else 'soccer'
        url = f"{ESPN}{path}/scoreboard?dates={day}" + EXTRA.get(next((k for k, v in PATH.items() if v == path), ''), '')
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'arkndjl.net watch'})
            with urllib.request.urlopen(req, timeout=30) as r:
                ev = json.load(r).get('events') or []
        except Exception as e:
            print(f'watch: scoreboard {path} {day} failed ({e})')
            ev = None
        out = {}
        for e in ev or []:
            c = (e.get('competitions') or [{}])[0]
            side = {x.get('homeAway'): x for x in c.get('competitors') or []}
            st = ((e.get('status') or {}).get('type') or {})
            out[str(e.get('id'))] = dict(st=st.get('state'), det=st.get('shortDetail') or st.get('detail'),
                                         a=(side.get('away') or {}).get('score'), h=(side.get('home') or {}).get('score'),
                                         wa=bool((side.get('away') or {}).get('winner')), wh=bool((side.get('home') or {}).get('winner')))
        cache[key] = out if ev is not None else None
    return cache[key]


def live_score(g):
    """{st, det, a, h, wa, wh} for a started game, or None when no source has it."""
    k = ts(g['kick'])
    if g['sport'] == 'tennis':
        T = load('data/tennis.json') or {}
        for m in (T.get('matches') or []) + (T.get('results') or []):
            if str(m.get('id')) == g['id']:
                st = m.get('state'); sc = m.get('sc') or ''
                # the card's away side is the file's a, home its b
                return dict(st=st, det=m.get('detail'), a=sc, h='', wa=bool((m.get('a') or {}).get('won')), wh=bool((m.get('b') or {}).get('won')))
        return None
    if g['sport'] == 'cs2':
        C = load('data/cs2.json') or {}
        for r in C.get('results') or []:
            if g['a'].get('n') == r.get('a') and g['h'].get('n') == r.get('b') and abs((r.get('ts') or 0) - k.timestamp()) < 86400:
                return dict(st='post', det='Final', a=str(r.get('sa')), h=str(r.get('sb')), wa=r.get('sa', 0) > r.get('sb', 0), wh=r.get('sb', 0) > r.get('sa', 0))
        return None
    if g['sport'] in ('nfl', 'nhl') and not str(g['id']).isdigit():   # rows written before ESPN ids were stored
        for x in (load(f"data/{g['sport']}_games.json") or {}).get('games') or []:
            if str(x.get('id')) == str(g['id']) and x.get('espn'):
                g['id'] = str(x['espn'])
    path = PATH.get(g['sport']) or (f"soccer/{g['lg']}" if g['sport'] == 'soccer' and g.get('lg') else None)
    if not path:
        return None
    for day in {k.astimezone(ET).strftime('%Y%m%d'), k.strftime('%Y%m%d')}:
        b = espn_board(path, day)
        if b and g['id'] in b:
            return b[g['id']]
    return None


def carry(old, now):
    """Listed games that have started: keep them with their score until 24 h after the final."""
    out = []
    for g in (old.get('played') or []) + [x for x in old.get('games') or [] if ts(x['kick']) and ts(x['kick']) <= now]:
        if any(x['id'] == g['id'] and x['sport'] == g['sport'] for x in out):
            continue
        k = ts(g['kick'])
        sc = live_score(g)
        if sc:
            g['sc'] = sc
            if sc.get('st') == 'post' and not g.get('fin'):
                g['fin'] = now.strftime('%Y-%m-%dT%H:%M:%SZ')
        fin = ts(g.get('fin'))
        if fin and now - fin > D.timedelta(hours=KEEP_H):
            continue
        if not fin and now - k > D.timedelta(hours=STALE_H):
            continue
        out.append(g)
    out.sort(key=lambda g: ((g.get('sc') or {}).get('st') != 'in', g['kick']))
    return out


def main():
    now = D.datetime.now(D.timezone.utc)
    rivals = rivalry_set()
    games, counts = [], {}
    for sport, fn in SPORTS:
        try:
            rows, pools = fn()
        except Exception as e:  # one sport's file in a bad state never drops the others
            print(f'watch: {sport} skipped ({type(e).__name__}: {e})')
            continue
        g = score(sport, rows, pools, now, rivals)
        counts[sport] = len(g)
        games += g
    games.sort(key=lambda g: (-g['w'], g['kick']))
    pick, per = [], {}
    for g in games:
        if per.get(g['sport'], 0) >= PER_SPORT:
            continue
        per[g['sport']] = per.get(g['sport'], 0) + 1
        pick.append(g)
        if len(pick) >= TOP:
            break
    for i, g in enumerate(pick):
        g['rk'] = i + 1
    start, end = now.astimezone(ET), (now + D.timedelta(days=DAYS)).astimezone(ET)
    old = load('data/watch.json') or {}
    played = carry(old, now)
    out = dict(asof=now.strftime('%Y-%m-%dT%H:%M:%SZ'), span=f"{start.strftime('%b %-d')} - {end.strftime('%b %-d')}",
               weights=W, bonus=BONUS, pool=counts, games=pick, played=played)
    path = os.path.join(ROOT, 'data/watch.json')
    if {k: v for k, v in old.items() if k != 'asof'} == {k: v for k, v in out.items() if k != 'asof'}:
        print('watch: unchanged')
        return
    with open(path, 'w') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
        f.write('\n')
    print(f"watch: {len(pick)} games from {sum(counts.values())} ({counts})")
    for g in played:
        print(f"  -- {g['lab']:<4} {g['a']['n']} @ {g['h']['n']}  {g.get('sc')}  fin {g.get('fin')}")
    for g in pick:
        print(f"  {g['rk']:>2} {g['lab']:<4} {g['w']:5.1f} {g['a']['n']} @ {g['h']['n']}  {g['et']}  {g['parts']} {g['tags']} {g['stars']}")


if __name__ == '__main__':
    main()
