"""NBA referee crews: who worked each game, and the whistle it drew (team fouls, free throws, techs; player fouls).
History from ESPN game summaries (gameInfo.officials), frozen to scripts/nba_refs_hist.json.gz. Stdlib only.

    python3 scripts/nba_refs.py --pull 2013 2026     # seasons from..to (end year), adds games not yet frozen
    python3 scripts/nba_refs.py --today              # tonight's crews (official.nba.com, ~9am ET) and their lean

Research (scripts/nba_refs_research.py, data/nba_refs_research*.json, Oct 21 2026): refs' free-throw and foul
tendencies are real and stable (split-half r .5 and .65), but no crew term cleared the rule (2015-21 t <= -1.5, BH)
for the game model's total, the totals market, or player points and minutes. The one lead: the crew's extra free
throws vs the closing total (2022-26 held out every season better, MAE t -2.4; lean 1+ pt hit 55% in both blocks).
So it is logged forward, pre-registered below and untouched, to be graded on games it never saw:
    lean = B x (sum of the crew's ridge effects on free-throw attempts), refs fit on every game before tonight,
    weighted by a 365-day half-life, ridge LAM games; a lean of X+ points is an over (under when negative).
The log (scripts/data/refs/nba-YYYY-MM.jsonl): a row per game when its crew is posted or changes {t, id, d, h, a,
crew, lean}, and {id, fin: {fta, pf}, crew} once ESPN has the box score. Grade with the odds archive's lines.
"""
import datetime as dt, gzip, json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nba_espn as E

ROOT = E.ROOT
RHIST = os.path.join(ROOT, 'scripts', 'nba_refs_hist.json.gz')
CACHE = os.path.join(E.CACHE, 'refs')
LOG = os.path.join(ROOT, 'scripts', 'data', 'refs')
OFFICIAL = 'https://official.nba.com/wp-json/api/v1/get-game-officials?date={}'
LAM, HL, B, X = 80.0, 365.0, 0.50, 1.0          # pre-registered 2026-10-21; don't tune on the forward log


def _n(s):
    v = E._num(s)
    return v if v is not None else 0.0


def summary(gid, fresh=False):
    """crew (names in ESPN's order) and the whistle: per team fta, ftm, pf, tech, fga, fg3a, oreb, tov; player pf + min"""
    fn = os.path.join(CACHE, gid + '.json')
    if not fresh and os.path.exists(fn):
        return json.load(open(fn))
    j = E.get(f'{E.SITE}/summary?event={gid}')
    if j is None or 'boxscore' not in j:
        return None
    refs = [o.get('displayName') or o.get('fullName') for o in (j.get('gameInfo') or {}).get('officials') or []]
    out = {'r': [r for r in refs if r], 't': {}, 'p': {}}
    for t in j['boxscore'].get('teams', []):
        ab = E.team(t['team']['abbreviation'])
        s = {x['name']: x.get('displayValue') for x in t.get('statistics', [])}
        ft = (s.get('freeThrowsMade-freeThrowsAttempted') or '').split('-')
        fg = (s.get('fieldGoalsMade-fieldGoalsAttempted') or '').split('-')
        f3 = (s.get('threePointFieldGoalsMade-threePointFieldGoalsAttempted') or '').split('-')
        out['t'][ab] = {'ftm': _n(ft[0]) if len(ft) == 2 else None, 'fta': _n(ft[1]) if len(ft) == 2 else None,
                        'fga': _n(fg[1]) if len(fg) == 2 else None, 'fg3a': _n(f3[1]) if len(f3) == 2 else None,
                        'pf': E._num(s.get('fouls')), 'tech': E._num(s.get('totalTechnicalFouls', s.get('technicalFouls'))),
                        'oreb': E._num(s.get('offensiveRebounds')), 'tov': E._num(s.get('totalTurnovers', s.get('turnovers')))}
    for t in j['boxscore'].get('players', []):
        ab = E.team(t['team']['abbreviation'])
        rows = []
        for st in t.get('statistics', [])[:1]:
            keys = st.get('keys') or []
            for p in st.get('athletes', []):
                d = dict(zip(keys, p.get('stats', [])))
                mn = E._num(d.get('minutes'))
                if mn:
                    rows.append([(p.get('athlete') or {}).get('id'), mn, _n(d.get('fouls'))])
        out['p'][ab] = rows
    E.save(fn, out)
    return out


def load():
    try:
        with gzip.open(RHIST, 'rt') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def pull(lo, hi):
    import nba_games as N
    games, _ = N.load_hist()
    have = load()
    todo = [g['id'] for g in games if lo <= g['S'] <= hi and g.get('fin') and g['id'] not in have]
    print(len(todo), 'to pull', flush=True)
    t0, done = time.time(), 0
    with ThreadPoolExecutor(16) as ex:
        for gid, s in zip(todo, ex.map(summary, todo)):
            if s:
                have[gid] = s
            done += 1
            if done % 500 == 0:
                print(done, f'{time.time() - t0:.0f}s', flush=True)
                with gzip.open(RHIST, 'wt') as f:
                    json.dump(have, f, separators=(',', ':'))
    with gzip.open(RHIST, 'wt') as f:
        json.dump(have, f, separators=(',', ':'))
    print(len(have), 'games frozen,', sum(1 for v in have.values() if len(v['r']) >= 3), 'with a full crew', flush=True)


def official(d):
    """crews the league posted for ET date d: [{h, a, crew}] (team codes as ESPN's)"""
    req = urllib.request.Request(OFFICIAL.format(d.isoformat()), headers={'User-Agent': E.UA})
    try:
        j = json.load(urllib.request.urlopen(req, timeout=30))
    except Exception as e:
        print('official.nba.com:', e, flush=True)
        return []
    out = []
    for r in ((j.get('nba') or {}).get('Table') or {}).get('rows') or []:
        crew = [r.get(f'official{i}') for i in (1, 2, 3)]
        if all(crew):
            out.append({'h': E.team(r.get('home_team_abbr')), 'a': E.team(r.get('away_team_abbr')), 'crew': crew})
    return out


def read_log():
    rows = []
    if os.path.isdir(LOG):
        for fn in sorted(os.listdir(LOG)):
            if fn.startswith('nba-') and fn.endswith('.jsonl'):
                rows += [json.loads(l) for l in open(os.path.join(LOG, fn)) if l.strip()]
    return rows


def append(rows, when):
    os.makedirs(LOG, exist_ok=True)
    with open(os.path.join(LOG, f"nba-{when[:7]}.jsonl"), 'a') as f:
        for r in rows:
            f.write(json.dumps(r, separators=(',', ':')) + '\n')


def whistle_rows(log):
    """(date, crew keys, total fta) for every game with a crew: the frozen history plus this season's log"""
    import nba_games as N
    import names as NM
    games, _ = N.load_hist()
    tip = {g['id']: g['tip'][:10] for g in games}
    hist = load()
    out = []
    for gid, r in hist.items():
        f = [v.get('fta') for v in r['t'].values()]
        if gid in tip and len(r['r']) >= 3 and len(f) == 2 and None not in f:
            out.append((tip[gid], [NM.key(x) for x in r['r'][:3]], sum(f)))
    posted = {r['id']: r for r in log if 'crew' in r and 'fin' not in r}
    for r in log:
        if 'fin' in r and r['fin'].get('fta') is not None and len(r.get('crew') or []) >= 3 and r['id'] not in hist:
            d = (posted.get(r['id']) or {}).get('d') or r.get('d')
            if d:
                out.append((d, [NM.key(x) for x in r['crew'][:3]], r['fin']['fta']))
    return out


def effects(rows, today):
    """each ref's ridge effect on free-throw attempts (against his season's league mean), half-life weighted to today
    (stdlib: the normal equations are refs x refs, built from three refs a game)"""
    rows = [x for x in rows if x[0] < today]
    refs = sorted({k for _, c, _ in rows for k in c})
    ix = {r: i for i, r in enumerate(refs)}
    season = lambda d: int(d[:4]) + (1 if int(d[5:7]) >= 8 else 0)
    by = {}
    for d, _, f in rows:
        a = by.setdefault(season(d), [0.0, 0]); a[0] += f; a[1] += 1
    t0 = dt.date.fromisoformat(today)
    ys, ws = [], []
    for d, _, f in rows:
        a = by[season(d)]
        ys.append(f - a[0] / a[1])
        ws.append(0.5 ** ((t0 - dt.date.fromisoformat(d)).days / HL))
    mu = sum(y * w for y, w in zip(ys, ws)) / sum(ws)
    k = len(refs)
    G = [[LAM if i == j else 0.0 for j in range(k)] for i in range(k)]
    v = [0.0] * k
    for (_, c, _), y, w in zip(rows, ys, ws):
        js = [ix[x] for x in c]
        for i in js:
            v[i] += w * (y - mu)
            for j in js:
                G[i][j] += w
    # Gauss-Jordan on the (symmetric, positive definite) system
    for col in range(k):
        p = G[col][col]
        for j in range(col, k):
            G[col][j] /= p
        v[col] /= p
        for r in range(k):
            if r != col and G[r][col]:
                f = G[r][col]
                for j in range(col, k):
                    G[r][j] -= f * G[col][j]
                v[r] -= f * v[col]
    return {r: v[i] for r, i in ix.items()}


def today(now=None):
    """log tonight's posted crews with their lean, and the whistle of this season's finished games"""
    import names as NM
    now = now or dt.datetime.now(dt.timezone.utc)
    stamp = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    et = now.astimezone(ZoneInfo('America/New_York')).date()      # a flat UTC-4 read 11 pm EST as tomorrow
    log = read_log()
    new = []
    # whistle of finished games we logged a crew for
    done = {r['id'] for r in log if 'fin' in r}
    for gid in sorted({r['id'] for r in log if 'crew' in r and 'fin' not in r} - done):
        s = summary(gid)
        if s and len(s.get('t', {})) == 2 and len(s.get('r', [])) >= 3:
            v = list(s['t'].values())
            if all(x.get('fta') is not None for x in v):
                new.append({'id': gid, 'crew': s['r'][:3], 'fin': {'fta': sum(x['fta'] for x in v), 'pf': sum((x['pf'] or 0) for x in v)}})
    posted = official(et)
    if posted:
        sched = {(g['h'], g['a']): g for g in E.day(et, fresh=True)}
        eff = effects(whistle_rows(log + new), et.isoformat())
        last = {}
        for r in log:
            if 'crew' in r and 'fin' not in r:
                last[r['id']] = r['crew']
        for p in posted:
            g = sched.get((p['h'], p['a']))
            if not g or g['final'] or last.get(g['id']) == p['crew']:
                continue
            lean = B * sum(eff.get(NM.key(x), 0.0) for x in p['crew'])
            new.append({'t': stamp, 'id': g['id'], 'd': et.isoformat(), 'h': g['h'], 'a': g['a'], 'tip': g['tip'],
                        'crew': p['crew'], 'new': [x for x in p['crew'] if NM.key(x) not in eff],
                        'lean': round(lean, 2), 'side': 'over' if lean >= X else 'under' if lean <= -X else None})
    if new:
        append(new, stamp)
    print(len(posted), 'crews posted,', sum(1 for r in new if 'lean' in r), 'logged,', sum(1 for r in new if 'fin' in r), 'finals', flush=True)
    for r in new:
        if 'lean' in r:
            print(f"  {r['a']} at {r['h']}: {', '.join(r['crew'])}  lean {r['lean']:+.2f}{'  ' + r['side'] if r['side'] else ''}")


if __name__ == '__main__':
    if sys.argv[1:2] == ['--pull']:
        pull(int(sys.argv[2]), int(sys.argv[3]))
    elif sys.argv[1:2] == ['--today']:
        today()
