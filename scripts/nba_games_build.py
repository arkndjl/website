"""The NBA game model's daily build (python3 scripts/nba_games.py; stdlib): the next two slates' projections, power
rankings, a simulated rest of the season, and the picks. Writes data/nba_games.json and data/nba_picks.json.

Tonight's lineups come from ESPN's rosters and the NBA's latest official injury report (pdftotext), with ESPN's
injury list for anyone the report doesn't cover (day-to-day read as questionable). Lines are the median of ESPN's
books at build time; a game's projection is logged each run until tip, so the season's record against the line is
graded on the last projection made before the game.

Season odds: 10,000 simulated rests of the season, seeded by the NBA's tiebreakers (Table), then the play-in and the
playoffs. The NBA Cup final is on the schedule but out of the standings.
"""
import datetime as dt
import json
import math
import os
import random
import re
import subprocess
import sys
import urllib.request
from collections import defaultdict
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_espn as E
import nba_games as N
import cover as CV

ET = ZoneInfo('America/New_York')
EAST = {'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DET', 'IND', 'MIA', 'MIL', 'NY', 'ORL', 'PHI', 'TOR', 'WSH'}
WEST = set(E.TEAMS) - EAST
DIV = {'BOS': 'Atl', 'BKN': 'Atl', 'NY': 'Atl', 'PHI': 'Atl', 'TOR': 'Atl', 'CHI': 'Cen', 'CLE': 'Cen', 'DET': 'Cen',
       'IND': 'Cen', 'MIL': 'Cen', 'ATL': 'SE', 'CHA': 'SE', 'MIA': 'SE', 'ORL': 'SE', 'WSH': 'SE',
       'DEN': 'NW', 'MIN': 'NW', 'OKC': 'NW', 'POR': 'NW', 'UTAH': 'NW', 'GS': 'Pac', 'LAC': 'Pac', 'LAL': 'Pac',
       'PHX': 'Pac', 'SAC': 'Pac', 'DAL': 'SW', 'HOU': 'SW', 'MEM': 'SW', 'NO': 'SW', 'SA': 'SW'}
SIMS = 10000
# uncertainty in a team's true rating, points, drawn once a simulated season: opening-night ratings missed teams'
# seasons by sd 3.7 beyond game noise (2016-26); it narrows with the share of the season left (floor 1.5)
RATING_SD0, RATING_FLOOR = 3.7, 1.5
ESPN_STATUS = {'Out': 'Out', 'Doubtful': 'Doubtful', 'Questionable': 'Questionable', 'Day-To-Day': 'Questionable',
               'Probable': 'Probable', 'Suspension': 'Out', 'Available': 'Available'}
REPORT = 'https://ak-static.cms.nba.com/referee/injury/Injury-Report_{d}_{t}.pdf'

DIVS = {d: frozenset(t for t in DIV if DIV[t] == d) for d in set(DIV.values())}
EAST, WEST = frozenset(EAST), frozenset(WEST)


def cup_final(cur):
    """the NBA Cup final's id: a regular-season game on ESPN's schedule that doesn't count in the standings (the
    last neutral game of the Cup's Las Vegas week in December, alone on its day; from 2023-24)"""
    days = defaultdict(list)
    for g in cur:
        if g['n'] and g['t'] == 2 and g['S'] >= 2024:
            d = N.tipdt(g).astimezone(ET).date()
            if d.month == 12 and 7 <= d.day <= 21:
                days[d].append(g)
    last = max(days, default=None)
    return days[last][0]['id'] if last and len(days[last]) == 1 else None


def current_season(today=None):
    t = today or dt.date.today()
    return t.year + 1 if t.month >= 8 else t.year


# ---------------------------------------------------------------- tonight's lineups
def official_report(now):
    """the latest official report today (ET): {(away, home): {name key: status}}, its time, or ({}, None)"""
    try:
        import nba_inj_hist as I
    except Exception:          # noqa: BLE001
        return {}, None
    for back in range(0, 14 * 4):
        t = now - dt.timedelta(minutes=15 * back)
        h12 = t.hour % 12 or 12
        ap = 'AM' if t.hour < 12 else 'PM'
        mm = t.minute // 15 * 15
        names = [f'{h12:02d}_{mm:02d}{ap}'] + ([f'{h12:02d}{ap}'] if mm == 0 else [])
        for nm in names:
            try:
                req = urllib.request.Request(REPORT.format(d=t.date().isoformat(), t=nm), headers={'User-Agent': E.UA})
                pdf = urllib.request.urlopen(req, timeout=20).read()
                txt = subprocess.run(['pdftotext', '-layout', '-', '-'], input=pdf, capture_output=True, timeout=60).stdout.decode('utf-8', 'replace')
                rep = {(E.team(I.ABBR.get(a, a)), E.team(I.ABBR.get(h, h))): {N.norm(k): v for k, v in d.items()}
                       for (a, h), d in I.parse(txt).items()}
                if rep:
                    return rep, t.isoformat(timespec='seconds')     # with its ET offset (Hugo needs seconds)
            except Exception:  # noqa: BLE001
                continue
    return {}, None


def espn_injuries():
    """{espn athlete id: status} from ESPN's league injury list"""
    j = E.get(f'{E.SITE}/injuries') or {}
    out = {}
    for t in j.get('injuries', []):
        for i in t.get('injuries', []):
            a = i.get('athlete') or {}
            m = None
            for l in a.get('links', []):
                m = m or re.search(r'/id/(\d+)', l.get('href', ''))
            st = ESPN_STATUS.get(i.get('status'))
            if m and st:
                out[m.group(1)] = st
    return out


def rosters():
    """{team: {espn id: name}} from ESPN's team rosters"""
    out = {}
    for t in sorted(E.TEAMS):
        j = E.get(f'{E.SITE}/teams/{t.lower()}/roster')
        if j and j.get('athletes'):
            out[t] = {a['id']: a.get('displayName', '') for a in j['athletes']}
    return out


# ---------------------------------------------------------------- build
def build():
    F = json.load(open(N.FIT))
    feats, b, tb, sd, tsd = F['feats'], F['coef'], F['tcoef'], F['sd'], F['tsd']
    P = F['P']
    now = dt.datetime.now(dt.timezone.utc)
    S = current_season()
    hist, names = N.load_hist()
    have = {g['S'] for g in hist}
    games = list(hist)
    cur = []
    for s in range(max(have) + 1, S + 1):
        for r in N.season_games(s, live=(s == S)):
            names.update(r.pop('nm', {}))
            if s < S and not r['fin']:
                continue
            (cur if s == S else games).append(r)
    if not cur:
        return print('nba games: no schedule yet for', S)
    games += [g for g in cur if g['fin']]
    upcoming = [g for g in cur if not g['fin']]
    # live: rosters and today's statuses
    ros = rosters()
    for t, ps in ros.items():
        names.update(ps)
    if F['params'].get('rk') and S - 1 not in N.draft():
        N.write_draft(S - 1, S - 1)                 # the summer's draft, once (rookie priors)
        N._DR.clear()
    m = N.Model(names, P, **F['params'])
    for g in games:
        m.feats(g); m.update(g)
    if m.season != S:
        m.new_season(S)
    for t, ps in ros.items():                       # tonight's rosters replace the ones the walk inferred
        for p in list(m.members[t]):
            if p not in ps:
                m.members[t].discard(p); m.team.pop(p, None)
        for p in ps:
            m.set_team(p, t)
    rep, rep_at = official_report(now.astimezone(ET))
    espn = espn_injuries()
    nowiso = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    days = sorted({N.tipdt(g).astimezone(ET).date() for g in upcoming})
    slate = set(days[:2])
    try:
        old = json.load(open(N.OUT))
    except (OSError, ValueError):
        old = {}
    log = old.get('log', {}) if old.get('season') == S else {}
    rows, proj = [], {}
    today = now.astimezone(ET).date()
    show = [g for g in cur if N.tipdt(g).astimezone(ET).date() in slate or (g['fin'] and N.tipdt(g).astimezone(ET).date() == today)]
    show_ids = {g['id'] for g in show}
    for g in upcoming:
        d = N.tipdt(g).astimezone(ET).date()
        st, src = {}, {}
        if d in slate:
            r_ = rep.get((g['a'], g['h'])) if d == today else None
            for t in (g['h'], g['a']):
                for p in m.roster(t):
                    k = N.norm(names.get(p, ''))
                    s_ = (r_ or {}).get(k) or espn.get(p)
                    if s_:
                        st[k] = s_; src[p] = 'NBA' if (r_ or {}).get(k) else 'ESPN'
            m.inj[g['id']] = st
        x, tx = m.feats(g)
        if g['id'] in show_ids:
            Vc = m._ctx
            inj = {}
            for side, t in (('home', g['h']), ('away', g['a'])):
                lst = []
                for p in m.roster(t):
                    k = N.norm(names.get(p, ''))
                    s_ = st.get(k)
                    if not s_ or s_ == 'Available':
                        continue
                    w_, n_ = m.role[p]
                    R = w_ / n_ if n_ else 0
                    pr = N.play_prob(P, s_, m.streak[p], True)
                    pts = b.get('lin', 0.0) * (1 - pr) * R * (m.v(p) - N.REPL) / 48
                    if R >= 5:
                        lst.append({'name': names.get(p, ''), 'status': s_, 'p': round(pr, 2), 'min': round(R, 1),
                                    'xpm': round(m.v(p), 1), 'pts': round(pts, 1), 'src': src.get(p)})
                lst.sort(key=lambda z: -z['pts'])
                inj[side] = lst
            proj[g['id']] = (x, tx, inj, Vc)
        m.update(g)
    # rows for the page
    rec = defaultdict(lambda: [0, 0])
    cupf = cup_final(cur)
    for g in cur:
        if g['fin'] and g['t'] == 2 and g['id'] != cupf:
            w = g['hs'] > g['as']
            rec[g['h']][0 if w else 1] += 1; rec[g['a']][1 if w else 0] += 1
    for g in show:
        if g['id'] not in proj:
            lg = log.get(g['id'])
            if not lg:
                continue
            r = dict(lg['row']); r['final'] = {'home': g['hs'], 'away': g['as']}
            rows.append(r)
            continue
        x, tx, inj, (Vh, Va, pace) = proj[g['id']]
        mar = sum(b[f] * x[f] for f in feats)
        tot = sum(tb[f] * tx[f] for f in N.TFEATS)
        tip = N.tipdt(g).astimezone(ET)
        r = {'id': g['id'], 'tip': g['tip'], 'day': tip.date().isoformat(), 'time': tip.strftime('%-I:%M'),
             'home': g['h'], 'away': g['a'], 'neutral': bool(g['n']), 'po': g['t'] == 3,
             'margin': round(mar, 1), 'pHome': round(N.phi(mar / sd), 3), 'total': round(tot, 1),
             'hs': round((tot + mar) / 2, 1), 'as': round((tot - mar) / 2, 1),
             'parts': {f: round(b[f] * x[f], 1) for f in feats if f != 'home' or True},
             'elo': {'home': round(m.elo[g['h']]), 'away': round(m.elo[g['a']])},
             'rest': {'home': None, 'away': None},
             'line': g.get('L'), 'tline': g.get('T'), 'ml': {'home': g.get('mlH'), 'away': g.get('mlA')}, 'inj': inj}
        if 'b2b' in x:
            r['b2b'] = {'home': x['b2b'] > 0 or (x['b2b'] == 0 and False), 'away': x['b2b'] < 0}
        if r['line'] is not None:
            e = mar - r['line']
            r['edge'] = round(e, 1)
            # the chance as the line leaves it (scripts/cover.py), not the model as the truth
            cv = CV.chance('nba', 'spread', e)
            r['cover'] = round(cv if cv is not None else N.phi(abs(e) / sd), 3)
        if r['tline']:
            ov = CV.chance('nba', 'total', tot - r['tline'])
            r['over'] = round(ov if ov is not None else N.phi((tot - r['tline']) / tsd), 3)
        rows.append(r)
        if g['tip'] > nowiso:
            log[g['id']] = {'m': r['margin'], 'L': r['line'], 'tip': g['tip'], 'row': {k: v for k, v in r.items() if k != 'inj'}}
    rows.sort(key=lambda r: (r['tip'], r['id']))
    # the season against the line: the last projection logged before each game
    G = {g['id']: g for g in cur if g['fin']}
    w = l = p = 0
    for gid, lg in log.items():
        g = G.get(gid)
        if not g or lg.get('L') is None or lg['m'] == lg['L']:
            continue
        res = g['hs'] - g['as'] - lg['L']
        if res == 0:
            p += 1
        elif (res > 0) == (lg['m'] > lg['L']):
            w += 1
        else:
            l += 1
    res = {'season': S, 'label': f'{S - 1}-{str(S)[2:]}', 'asof': nowiso, 'days': [d.isoformat() for d in sorted(slate)],
           'games': rows, 'rec': {t: f'{v[0]}-{v[1]}' for t, v in rec.items()}, 'ats': {'w': w, 'l': l, 'p': p},
           'sd': sd, 'tsd': tsd, 'coef': b, 'test': F['test'], 'calib': F.get('calib'), 'P': P, 'report': rep_at,
           'log': log}
    res.update(season_views(m, F, cur, rec, proj, S, slate))
    try:
        import nba_picks
        nba_picks.live([r for r in rows if not r.get('final')], cur, sd, S, min(slate).isoformat() if slate else None)
    except Exception as e:      # noqa: BLE001
        print('nba picks: failed', repr(e))
    if {k: v for k, v in old.items() if k != 'asof'} == json.loads(json.dumps({k: v for k, v in res.items() if k != 'asof'})):
        return print('nba games: no change')
    with open(N.OUT, 'w') as f:
        json.dump(res, f, separators=(',', ':'))
    print(f'nba games: {S}, {len(rows)} games on {", ".join(res["days"])}; report {rep_at}; model ATS {w}-{l}-{p}')


# ---------------------------------------------------------------- standings
class Table:
    """A season's standings under the NBA's tiebreakers, from every game's margin (T.M, home minus away; set per
    simulated season). Two teams: head-to-head, division leader, division record (same division), conference
    record, record against the conference's playoff teams, against the other conference's, point differential.
    Three or more: division leader, head-to-head among the tied, division record (all one division), conference
    record, against the conference's playoff teams, point differential; any teams a step separates are ranked
    by it and each group still tied starts over (two-team rules for two). Division leaders are found first, by
    the same rules. Playoff teams: the top 10 by record in each conference (play-in included), ties at 10th in.
    Whatever is still tied after point differential: a coin flip."""
    def __init__(self, reg, rng):
        self.rng = rng
        self.M = [float(g['hs'] - g['as']) if g['fin'] else 0.0 for g in reg]
        self.tg = defaultdict(list)                  # team -> (game, opponent, +1 home / -1 away)
        self.pg = defaultdict(list)                  # (team, opponent) -> (game, sign)
        for i, g in enumerate(reg):
            self.tg[g['h']].append((i, g['a'], 1)); self.tg[g['a']].append((i, g['h'], -1))
            self.pg[g['h'], g['a']].append((i, 1)); self.pg[g['a'], g['h']].append((i, -1))

    def pct(self, t, opp):
        w = n = 0
        M = self.M
        for i, o, sg in self.tg[t]:
            if o in opp:
                n += 1
                w += M[i] * sg > 0
        return w / n if n else 0.5

    def ranked(self, group, lead, elig):
        if len(group) < 2:
            return list(group)
        M, pg = self.M, self.pg
        conf = EAST if group[0] in EAST else WEST
        one_div = len({DIV[t] for t in group}) == 1

        def h2h(t):
            w = n = 0
            for o in group:
                if o != t:
                    for i, sg in pg.get((t, o), ()):
                        n += 1
                        w += M[i] * sg > 0
            return w / n if n else 0.5
        crit = {'h2h': h2h,
                'lead': (lambda t: t in lead) if lead is not None else None,
                'div': (lambda t: self.pct(t, DIVS[DIV[t]])) if one_div else None,
                'conf': lambda t: self.pct(t, conf),
                'own': lambda t: self.pct(t, elig & conf),
                'other': lambda t: self.pct(t, elig - conf),
                'pd': lambda t: sum(M[i] * sg for i, _, sg in self.tg[t])}
        steps = ('h2h', 'lead', 'div', 'conf', 'own', 'other', 'pd') if len(group) == 2 else ('lead', 'h2h', 'div', 'conf', 'own', 'pd')
        for k in steps:
            c = crit[k]
            if c is None:
                continue
            v = {t: c(t) for t in group}
            vals = sorted(set(v.values()), reverse=True)
            if len(vals) > 1:
                out = []
                for x in vals:
                    out += self.ranked([t for t in group if v[t] == x], lead, elig)
                return out
        g = list(group)
        self.rng.shuffle(g)
        return g

    def order(self, teams, w, lead, elig):
        out = []
        for x in sorted({w[t] for t in teams}, reverse=True):
            grp = [t for t in teams if w[t] == x]
            out += self.ranked(grp, lead, elig) if len(grp) > 1 else grp
        return out

    def standings(self, w):
        """(East 1-15, West 1-15)"""
        elig = set()
        for conf in (EAST, WEST):
            cut = sorted((w[t] for t in conf), reverse=True)[9]
            elig |= {t for t in conf if w[t] >= cut}
        lead = {self.order(ts, w, None, elig)[0] for ts in DIVS.values()}
        return self.order(EAST, w, lead, elig), self.order(WEST, w, lead, elig)


# ---------------------------------------------------------------- power rankings and season odds
def season_views(m, F, cur, rec, proj, S, slate):
    b, sd = F['coef'], F['sd']
    teams = sorted(E.TEAMS)
    Lg = m.lg[0] / m.lg[1]
    pace = m.lgp[0] / m.lgp[1]
    net = lambda t: m.rate(m.off, t) - m.rate(m.dfn, t)
    mk = sum(m.mkt[t] for t in teams) / len(teams)

    def comp(t, injured=True):
        V = m.lineup(t)                              # every listed player at his chance to play, no report: norep
        c = {'elo': (m.elo[t] - 1505) / 28, 'eff': net(t) * (pace + m.rate(m.pace, t)) / 100, 'mkt': m.mkt[t] - mk,
             'lin': V - m.rate(m.base, t, 1.0), 'roster': V}
        return sum(b.get(f, 0.0) * v for f, v in c.items())
    R = {t: comp(t) for t in teams}
    avg = sum(R.values()) / len(R)
    R = {t: v - avg for t, v in R.items()}
    hfa = b.get('home', 0.0)
    wins0 = {t: rec[t][0] if t in rec else 0 for t in teams}
    cupf = cup_final(cur)
    reg = [g for g in cur if g['t'] == 2 and g['id'] != cupf]
    rng = random.Random(7)
    T = Table(reg, rng)
    mus = []
    for i, g in enumerate(reg):
        if g['fin']:
            continue
        if g['id'] in proj:                          # the slate: its full projection (injuries, rest)
            x = proj[g['id']][0]
            mu = sum(b[f] * x[f] for f in F['feats'])
        else:
            mu = R[g['h']] - R[g['a']] + (0 if g['n'] else hfa)
        mus.append((i, g['h'], g['a'], mu))
    left = mus
    rsd = max(RATING_FLOOR, RATING_SD0 * math.sqrt(min(1.0, len(left) / 1230)))
    keys = ('playoff', 'playin', 'top6', 'conf', 'title')
    cnt = {t: dict.fromkeys(keys, 0) for t in teams}
    wsum = dict.fromkeys(teams, 0.0)

    def series(hi, lo, shock, need=4):
        """best of seven, the higher seed at home in games 1, 2, 5, 7"""
        wh = wl = 0
        for i in range(7):
            home = hi if i in (0, 1, 4, 6) else lo
            away = lo if home == hi else hi
            mu = R[home] - R[away] + shock[home] - shock[away] + hfa
            if rng.gauss(mu, sd) > 0:
                if home == hi: wh += 1
                else: wl += 1
            else:
                if away == hi: wh += 1
                else: wl += 1
            if wh == need or wl == need:
                break
        return hi if wh == need else lo

    def one(h, a, shock):
        return h if rng.gauss(R[h] - R[a] + shock[h] - shock[a] + hfa, sd) > 0 else a
    M0 = T.M
    for _ in range(SIMS):
        shock = {t: rng.gauss(0, rsd) for t in teams}
        w = dict(wins0)
        M = list(M0)                                 # every game's margin, home minus away: played, then simulated
        for i, h, a, mu in mus:
            d = rng.gauss(mu + shock[h] - shock[a], sd)
            M[i] = d
            w[h if d > 0 else a] += 1
        for t in teams:
            wsum[t] += w[t]
        T.M = M
        seeded = T.standings(w)
        tbk = {t: w[t] + rng.random() * 1e-3 for t in teams}       # Finals home court: record, then a coin flip
        champs = []
        for conf in (EAST, WEST):
            order = seeded[conf is WEST]
            for t in order[:6]:
                cnt[t]['top6'] += 1
            for t in order[6:10]:
                cnt[t]['playin'] += 1
            # play-in: 7 v 8, winner the 7 seed; 9 v 10, winner plays the 7-8 loser for the 8 seed
            s7, s8, s9, s10 = order[6:10]
            w78 = one(s7, s8, shock); l78 = s8 if w78 == s7 else s7
            w910 = one(s9, s10, shock)
            eighth = one(l78, w910, shock)
            seeds = order[:6] + [w78, eighth]
            for t in seeds:
                cnt[t]['playoff'] += 1
            r1 = [series(seeds[i], seeds[7 - i], shock) for i in range(4)]
            r2 = [series(*sorted((r1[0], r1[3]), key=seeds.index), shock), series(*sorted((r1[1], r1[2]), key=seeds.index), shock)]
            cf = series(*sorted(r2, key=seeds.index), shock)
            cnt[cf]['conf'] += 1
            champs.append(cf)
        hi, lo = sorted(champs, key=lambda t: -tbk[t])
        cnt[series(hi, lo, shock)]['title'] += 1
    power = []
    for t in teams:
        power.append({'t': t, 'conf': 'East' if t in EAST else 'West', 'rating': round(R[t], 1), 'elo': round(m.elo[t]),
                      'off': round(m.rate(m.off, t), 1), 'dfn': round(m.rate(m.dfn, t), 1),
                      'pace': round(pace + m.rate(m.pace, t), 1), 'mkt': round(m.mkt[t] - mk, 1),
                      'lineup': round(m.lineup(t), 1),
                      'rec': f'{rec[t][0]}-{rec[t][1]}' if t in rec else '0-0', 'wins': round(wsum[t] / SIMS, 1),
                      **{k: round(cnt[t][k] / SIMS, 3) for k in keys}})
    power.sort(key=lambda r: -r['rating'])
    for i, r in enumerate(power):
        r['rk'] = i + 1
    return {'power': power, 'sims': SIMS, 'ratingSd': round(rsd, 2), 'left': len(left)}
