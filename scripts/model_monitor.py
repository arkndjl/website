#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Live accuracy of each game model against its own walk-forward record (audit item #28, Oct 25 2026). Stdlib only.

    python3 scripts/model_monitor.py nba            # one sport (each sport's workflow runs its own): log, score, report
    python3 scripts/model_monitor.py --backfill nba # also rebuild this season's log from git history of the games file
    python3 scripts/model_monitor.py --test         # self-check

The log (scripts/data/model_monitor/<sport>.json) keeps the last projection published before each game, read from the
sport's games file every run (data/<sport>_games.json), and the result once ESPN's scoreboard has it. Each scored game's
loss (abs margin error for NBA, NFL, CBB and CFB; win log loss for NHL; 1X2 log loss for soccer) is compared with what
the walk-forward backtest (scripts/data/games_wf/<sport>.json.gz) lost on the same calendar month over its last five
seasons: z = (expected - loss) / sd, so a model doing worse than its own backtest runs negative.

Tennis and CS2 (win log loss; data/tennis.json, data/cs2.json, whose results carry the chance given before each match)
have no walk-forward file and a slate whose mix of mismatches moves week to week, so each match is held to the model's
own chance instead: expected = the loss the chance itself implies, -p ln p - (1-p) ln(1-p), sd = sqrt(p(1-p)) x
|ln(p/(1-p))|. z is then +-the standardised result on the favourite's side: negative when favourites win less often
than priced (an over-confident model), which is how the CS2 model failed in the months after a roster break.

Line: the market's loss on the same games where a price was logged: mean |result - line| for the margin models, the
log loss of the no-vig price for the chance models (NHL pMkt, soccer's three-way price, Novig's tennis moneyline).

The test is rule_monitor.decide(), the one the pick rules use (scripts/monitor_rules.json, pre-registered): with 50+
games scored, an alarm when the last 300 are worth clustered t below -1 (game day clusters) or the one-sided CUSUM
S = max(0, S - z - .25) crosses 10. A model alarm is a flag to look at the model, not a switch: nothing stops.
The report, data/model_monitor/<sport>.json, shows on the Predictions page (game models tab) beside the ledger.
Every run also lists the ledger's models past their one-year re-test (data/model_ledger.json, the same check as
`scripts/harness.py --stale`, which needs numpy), as a warning in the workflow log.
"""
import datetime as dt
import gzip
import json
import math
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import rule_monitor as RM

LOG = os.path.join(HERE, 'data', 'model_monitor')
OUT = os.path.join(ROOT, 'data', 'model_monitor')
WF = os.path.join(HERE, 'data', 'games_wf')
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/'
LEAGUE = {'nba': 'basketball/nba', 'cbb': 'basketball/mens-college-basketball', 'nhl': 'hockey/nhl', 'nfl': 'football/nfl',
          'cfb': 'football/college-football'}
EXTRA = {'cbb': '&groups=50&limit=500', 'cfb': '&groups=80&limit=500'}
LOSS = {'nba': 'abs margin error', 'nfl': 'abs margin error', 'cbb': 'abs margin error', 'cfb': 'abs margin error',
        'nhl': 'win log loss', 'soccer': '1X2 log loss', 'tennis': 'win log loss', 'cs2': 'win log loss'}
SPORTS = tuple(LOSS)
OWN = ('tennis', 'cs2')              # held to the model's own chances (no walk-forward file)
WIN = ('nhl',) + OWN                 # p = the home (first-listed) side's chance
GAMES = {'tennis': 'data/tennis.json', 'cs2': 'data/cs2.json'}
EXPECT_SEASONS = 5
# soccer's walk-forward (the expectation) scores only the big five and UEFA (soccer_games.SCORED); live games from the
# other leagues on the board (Sweden, MLS, Scotland...) run at a different base loss, so they stay out of the test.
# The walk-forward file holds 90-minute results only, so a cup match that went to extra time (its ESPN score counts
# the extra-time goals) stays out too (`et` on its log entry)
SOCCER_LGS = {'eng.1', 'esp.1', 'ger.1', 'ita.1', 'fra.1', 'uefa.champions', 'uefa.europa', 'uefa.europa.conf'}
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo('America/New_York')
except Exception:          # pragma: no cover
    ET = dt.timezone(dt.timedelta(hours=-5))


def iso(t):
    return dt.datetime.fromisoformat(str(t).replace('Z', '+00:00')) if 'T' in str(t) else dt.datetime.fromisoformat(str(t) + 'T12:00:00+00:00')


def stamp(t):
    return t.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def season_of(sport, kick):
    """the season label a game belongs to: the year it ends (NBA/NHL/CBB/soccer 2027 = 2026-27), the year it starts (NFL/CFB)"""
    d = iso(kick).astimezone(ET)
    if sport in OWN:
        return d.year
    if sport in ('nfl', 'cfb'):
        return d.year if d.month >= 3 else d.year - 1
    return d.year + 1 if d.month >= 7 else d.year


def clip(p):
    return min(max(p, 1e-4), 1 - 1e-4)


def loss(sport, g):
    """one scored game's loss, or None"""
    r = g.get('res')
    if r is None:
        return None
    if sport in WIN:
        return -math.log(clip(g['p'])) if r > 0 else -math.log(clip(1 - g['p']))
    if sport == 'soccer':
        i = 0 if r > 0 else 1 if r == 0 else 2
        return -math.log(clip(g['p'][i]))
    return abs(r - g['m'])


def line_loss(sport, g):
    """the market's loss on a scored game at the line logged with it, or None: the same loss as the model's"""
    L = g.get('L')
    if L is None or g.get('res') is None:
        return None
    if sport in WIN or sport == 'soccer':
        try:
            return loss(sport, {'p': L, 'res': g['res']})
        except (TypeError, IndexError, ValueError):
            return None
    return abs(g['res'] - L) if 'm' in g else None


def own_expect(p):
    """(mean, sd) of the win log loss a chance p expects of itself"""
    p = clip(p)
    return -p * math.log(p) - (1 - p) * math.log(1 - p), math.sqrt(p * (1 - p)) * abs(math.log(p / (1 - p)))


def three_way(dk):
    """no-vig [home, draw, away] from American three-way prices {h, d, a} (shared out in proportion), or None"""
    try:
        iv = [100 / (x + 100) if x > 0 else -x / (100 - x) for x in (float(dk[k]) for k in ('h', 'd', 'a'))]
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    t = sum(iv)
    return [round(x / t, 4) for x in iv] if 1.0 <= t <= 1.2 else None


# ---------------------------------------------------------------- what the games file says before each game
def predictions(sport, D):
    """{id: entry} for every game in a games file that has a projection: k (kick), m (home margin) or p, L (line), espn, lg"""
    out = {}
    if sport == 'cfb':
        for g in D.get('games', []):
            m = (g.get('proj') or {}).get('margin')
            if m is not None and g.get('date'):
                out[str(g['id'])] = {'k': stamp(iso(g['date'])), 'm': m, 'espn': str(g['id'])}
        return out
    if sport == 'soccer':
        for g in D.get('games', []):
            if g.get('p') and g.get('tip'):
                out[str(g['id'])] = {'k': g['tip'], 'p': g['p'], 'espn': str(g['id']), 'lg': g.get('lg'),
                                     'L': three_way(g.get('dk')),
                                     **({'res': g['final'][0] - g['final'][1]} if g.get('final') else {}),
                                     **({'et': 1} if g.get('et') else {})}
        return out
    if sport == 'tennis':
        # matches still to start, then the results (each carries the chance given before it; walkovers never played)
        for g in D.get('matches', []):
            if g.get('p') is not None and g.get('tip') and g.get('state') == 'pre':
                out[f"{g.get('tour')}{g['id']}"] = {'k': g['tip'], 'p': g['p'], 'L': (g.get('nv') or {}).get('p')}
        for g in D.get('results', []):
            won = ((g.get('a') or {}).get('won'), (g.get('b') or {}).get('won'))
            if g.get('p') is None or not g.get('tip') or won[0] == won[1] or 'walk' in str(g.get('detail', '')).lower():
                continue
            out[f"{g.get('tour')}{g['id']}"] = {'k': g['tip'], 'p': g['p'], 'L': None, 'pre': True, 'res': 1 if won[0] else -1}
        return out
    if sport == 'cs2':
        # finished series with the chance the model gave before each (cs2_model.py results)
        for g in D.get('results', []):
            if g.get('pa') is None or g.get('sa') is None or g.get('sb') is None or g['sa'] == g['sb']:
                continue
            k = stamp(dt.datetime.fromtimestamp(g['ts'], dt.timezone.utc))
            out[f"{g['ts']}:{g.get('ka')}:{g.get('kb')}"] = {'k': k, 'p': g['pa'], 'L': None, 'pre': True,
                                                           'res': 1 if g['sa'] > g['sb'] else -1}
        return out
    if sport == 'nhl':
        for g in D.get('games', []):
            if g.get('pHome') is not None and g.get('tip'):
                out[str(g['id'])] = {'k': g['tip'], 'p': g['pHome'], 'espn': str(g.get('espn') or ''), 'L': g.get('pMkt')}
        return out
    rows = [(g, False) for g in D.get('games', [])]
    if sport == 'nfl':           # the build's record of each played game: its last projection before kickoff, with the final
        rows += [(g, True) for g in D.get('past', [])]
    for g, pre in rows:
        k = g.get('tip') or g.get('kick')
        if g.get('margin') is None or not k:
            continue
        e = {'k': k, 'm': g['margin'], 'L': g.get('line'), 'espn': str(g.get('espn') or g['id']), **({'pre': True} if pre else {})}
        f = g.get('final')
        if isinstance(f, dict) and f.get('home') is not None:
            e['res'] = f['home'] - f['away']
        out[str(g['id'])] = e
    if sport == 'nba':          # the build's own log: the last projection before each tip, this season
        for gid, lg in (D.get('log') or {}).items():
            if lg.get('m') is not None and str(gid) not in out:
                out[str(gid)] = {'k': lg['tip'], 'm': lg['m'], 'L': lg.get('L'), 'espn': str(gid), 'pre': True}
    return out


def merge(log, preds, asof, src='live'):
    """keep the last projection published before each kick (asof < kick, or one the file keeps as pre-game: pre);
    results always kept"""
    for gid, e in preds.items():
        cur = log.get(gid)
        res, pre, et = e.pop('res', None), e.pop('pre', False), e.pop('et', None)
        if (asof < e['k'] or (pre and cur is None)) and (cur is None or cur.get('at', '') <= asof):
            if e.get('L') is None and cur and cur.get('L') is not None:
                e['L'] = cur['L']                 # a later run without a price keeps the last one logged
            log[gid] = {**e, 'at': asof, 'src': src, **({'res': cur['res']} if cur and cur.get('res') is not None else {})}
            cur = log[gid]
        if res is not None and cur is not None and cur.get('res') is None:
            cur['res'] = res
        if et and cur is not None:
            cur['et'] = 1
    return log


def git_versions(path, since):
    r = subprocess.run(['git', '-C', ROOT, 'log', '--format=%H', f'--since={since}', '--', path], capture_output=True, text=True)
    for h in reversed(r.stdout.split()):
        s = subprocess.run(['git', '-C', ROOT, 'show', f'{h}:{path}'], capture_output=True, text=True)
        if s.returncode == 0:
            try:
                yield json.loads(s.stdout)
            except ValueError:
                pass


def file_asof(D, fallback):
    a = D.get('asof') or fallback
    return stamp(iso(a)) if 'T' in str(a) else str(a) + 'T00:00:00Z'


# ---------------------------------------------------------------- results from ESPN's scoreboard
def fetch(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 arkboard-model-monitor'})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception:
            time.sleep(2 * (i + 1))
    return None


ET_STATUS = ('STATUS_FINAL_AET', 'STATUS_FINAL_PEN', 'STATUS_END_OF_EXTRATIME', 'STATUS_FINAL_ET')


def finals(sport, day, lg=None, et=None):
    """{espn id: home minus away} for the completed games on an ET date. et: a set that takes the ids of soccer
    matches that went to extra time (their score is not a 90-minute result)"""
    path = f'soccer/{lg}' if sport == 'soccer' else LEAGUE[sport]
    d = fetch(f"{ESPN}{path}/scoreboard?dates={day.replace('-', '')}{EXTRA.get(sport, '')}")
    out = {}
    for ev in (d or {}).get('events', []):
        c = (ev.get('competitions') or [{}])[0]
        if not ((c.get('status') or ev.get('status') or {}).get('type') or {}).get('completed'):
            continue
        sc = {t.get('homeAway'): t.get('score') for t in c.get('competitors', [])}
        try:
            out[str(ev['id'])] = float(sc['home']) - float(sc['away'])
        except (KeyError, TypeError, ValueError):
            continue
        if et is not None and sport == 'soccer' and ((c.get('status') or ev.get('status') or {}).get('type') or {}).get('name') in ET_STATUS:
            et.add(str(ev['id']))
    return out


def score(sport, log, now, limit=60):
    """fills res for games that should be over (kick 4+ h ago), one scoreboard call per date (and league)"""
    want = {}
    for gid, e in log.items():
        if e.get('res') is None and e.get('espn') and iso(e['k']) < now - dt.timedelta(hours=4) and iso(e['k']) > now - dt.timedelta(days=21):
            day = iso(e['k']).astimezone(ET).date().isoformat()
            want.setdefault((day, e.get('lg')), []).append(gid)
    for (day, lg), ids in sorted(want.items())[-limit:]:
        et = set()
        F = finals(sport, day, lg, et)
        for gid in ids:
            r = F.get(log[gid]['espn'])
            if r is not None:
                log[gid]['res'] = r
                if log[gid]['espn'] in et:
                    log[gid]['et'] = 1
    return log


# ---------------------------------------------------------------- the walk-forward expectation
def wf_rows(sport):
    p = os.path.join(WF, sport + '.json.gz')
    if not os.path.exists(p):
        return []
    out = []
    for r in json.load(gzip.open(p)):
        k = r.get('date') or r.get('day')
        if sport == 'nhl':
            if r.get('p') is None or r.get('hs') is None:
                continue
            g = {'k': k, 'p': r['p'], 'res': r['hs'] - r['as']}
        elif sport == 'soccer':
            if not r.get('p') or r.get('hs') is None:
                continue
            g = {'k': k, 'p': r['p'], 'res': r['hs'] - r['as']}
        else:
            if r.get('m') is None or r.get('res') is None:
                continue
            g = {'k': k, 'm': r['m'], 'res': r['res'], 'L': r.get('L')}
        g['S'] = r['S']
        out.append(g)
    return out


def expectation(sport, season, rows=None):
    """{month: (mean loss, sd, n)} over the walk-forward's last five seasons before this one, plus 'all'"""
    rows = rows if rows is not None else wf_rows(sport)
    seasons = sorted({r['S'] for r in rows if r['S'] < season})[-EXPECT_SEASONS:]
    by = {}
    for r in rows:
        if r['S'] in seasons:
            x = loss(sport, r)
            by.setdefault(iso(r['k']).month, []).append(x)
            by.setdefault('all', []).append(x)
    out = {}
    for k, xs in by.items():
        n = len(xs)
        m = sum(xs) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in xs) / max(n - 1, 1))
        out[k] = (m, sd, n)
    return out, seasons


def report(sport, log, season, now, E=None, seasons=None):
    if sport in OWN:
        E, seasons = {}, None
    elif E is None:
        E, seasons = expectation(sport, season)
    games = sorted([dict(e, id=gid) for gid, e in log.items() if e.get('res') is not None and season_of(sport, e['k']) == season
                    and (sport != 'soccer' or e.get('lg') in SOCCER_LGS and not e.get('et'))],
                   key=lambda e: e['k'])
    rows, by = [], {}
    for g in games:
        x = loss(sport, g)
        mo = iso(g['k']).month
        if sport in OWN:
            m, sd = own_expect(g['p'])
            sd = sd if sd > 1e-6 else None        # a coin flip loses ln 2 either way: nothing to test
        else:
            m, sd, n = E.get(mo) if E.get(mo) and E[mo][2] >= 30 else E.get('all', (None, None, 0))
        if m is None or not sd:
            continue
        z = (m - x) / sd
        rows.append({'k': g['k'], 'clvRet': z, 'loss': x, 'exp': m, 'line': line_loss(sport, g)})
        b = by.setdefault(mo, {'n': 0, 'loss': 0.0, 'exp': 0.0})
        b['n'] += 1; b['loss'] += x; b['exp'] += m
    P = RM.params()
    D = RM.decide(rows, sd=1.0, P=P) if rows else None
    n = len(rows)
    out = {'asof': stamp(now), 'sport': sport, 'season': season, 'loss': LOSS[sport], 'n': n, 'logged': sum(1 for e in log.values() if season_of(sport, e['k']) == season),
           'expectFrom': "the model's own chances" if sport in OWN else
           f'walk-forward {seasons[0]}-{seasons[-1]}, same calendar month' if seasons else None}
    if n:
        lines = [r['line'] for r in rows if r['line'] is not None]
        out.update({'model': round(sum(r['loss'] for r in rows) / n, 4), 'expected': round(sum(r['exp'] for r in rows) / n, 4),
                    'z': round(sum(r['clvRet'] for r in rows) / n, 3),
                    'line': round(sum(lines) / len(lines), 4 if sport in WIN or sport == 'soccer' else 3) if lines else None,
                    'lineN': len(lines),
                    # the model on the games that carry a line (the like-for-like figure beside `line`)
                    'modelAtLine': round(sum(r['loss'] for r in rows if r['line'] is not None) / len(lines), 4) if lines else None,
                    'byMonth': [{'month': dt.date(2000, mo, 1).strftime('%b').lower(), 'n': b['n'], 'model': round(b['loss'] / b['n'], 4),
                                 'expected': round(b['exp'] / b['n'], 4)} for mo, b in sorted(by.items(), key=lambda kv: (kv[0] < 7, kv[0]))],
                    'test': D})
    status = 'collecting' if n < P['minN'] else 'alarm' if D['stop'] else 'watch' if (D['cusum'] >= P['cusum']['h'] / 2 or (D['t'] or 0) < 0) else 'ok'
    out['status'] = status
    out['why'] = (D or {}).get('why') or ''
    return out


# ---------------------------------------------------------------- run
def run(sport, backfill=False, now=None, offline=False):
    now = now or dt.datetime.now(dt.timezone.utc)
    os.makedirs(LOG, exist_ok=True); os.makedirs(OUT, exist_ok=True)
    lp = os.path.join(LOG, sport + '.json')
    st = json.load(open(lp)) if os.path.exists(lp) else {'log': {}}
    log = st['log']
    gpath = GAMES.get(sport, f'data/{sport}_games.json')
    if backfill:
        since = (now - dt.timedelta(days=200)).date().isoformat()
        for D in git_versions(gpath, since):
            merge(log, predictions(sport, D), file_asof(D, since))
        if sport in ('cfb', 'nfl'):          # the walk-forward's current season stands in where nothing was logged
            cur = season_of(sport, stamp(now))
            for r in json.load(gzip.open(os.path.join(WF, sport + '.json.gz'))):
                if r['S'] == cur and r.get('m') is not None and str(r['id']) not in log:
                    k = r['date'] if 'T' in r['date'] else r['date'] + 'T18:00:00Z'
                    log[str(r['id'])] = {'k': stamp(iso(k)), 'm': r['m'], 'L': r.get('L'), 'espn': str(r['id']), 'src': 'wf',
                                         **({'res': r['res']} if r.get('res') is not None else {})}
    D = json.load(open(os.path.join(ROOT, gpath)))
    merge(log, predictions(sport, D), file_asof(D, stamp(now)))
    if not offline:
        score(sport, log, now)
    season = season_of(sport, stamp(now))
    # keep this season and the last one only
    st['log'] = {k: v for k, v in log.items() if season_of(sport, v['k']) >= season - 1}
    with open(lp, 'w') as f:
        json.dump(st, f, separators=(',', ':'), sort_keys=True)
    R = report(sport, st['log'], season, now)
    with open(os.path.join(OUT, sport + '.json'), 'w') as f:
        json.dump(R, f, indent=1)
    print(sport, R['status'], R.get('n'), 'scored', R.get('model'), 'vs', R.get('expected'), R.get('why', ''))
    return R


def stale_ledger(today=None):
    """the ledger's models past their re-validation date (harness.REVALIDATE_DAYS after their test)"""
    p = os.path.join(ROOT, 'data', 'model_ledger.json')
    if not os.path.exists(p):
        return []
    today = today or dt.date.today().isoformat()
    return sorted(k for k, m in json.load(open(p))['models'].items() if str(m.get('revalidate', '9999')) <= today)


def test():
    now = dt.datetime(2026, 12, 15, tzinfo=dt.timezone.utc)
    E = {12: (10.0, 8.0, 500), 'all': (10.0, 8.0, 5000)}
    def lg(err, n):
        return {f'g{i}': {'k': stamp(now - dt.timedelta(days=60) + dt.timedelta(hours=8 * i)), 'm': 0.0, 'res': err} for i in range(n)}
    ok = report('nba', lg(10.0, 120), 2027, now, E, [2022, 2026])
    bad = report('nba', lg(13.5, 120), 2027, now, E, [2022, 2026])
    few = report('nba', lg(30.0, 10), 2027, now, E, [2022, 2026])
    assert ok['status'] == 'ok', ok
    assert bad['status'] == 'alarm' and 'CUSUM' in bad['why'], bad
    assert few['status'] == 'collecting', few
    # merge keeps the last projection before the kick and never one made after it
    log = {}
    merge(log, {'a': {'k': '2026-10-01T23:00:00Z', 'm': 1.0}}, '2026-10-01T10:00:00Z')
    merge(log, {'a': {'k': '2026-10-01T23:00:00Z', 'm': 2.0}}, '2026-10-01T20:00:00Z')
    merge(log, {'a': {'k': '2026-10-01T23:00:00Z', 'm': 9.0, 'res': 3.0}}, '2026-10-02T10:00:00Z')
    assert log['a']['m'] == 2.0 and log['a']['res'] == 3.0, log
    assert loss('soccer', {'p': [0.5, 0.3, 0.2], 'res': 0}) == -math.log(0.3)
    assert season_of('nba', '2026-10-25T23:00:00Z') == 2027 and season_of('cfb', '2027-01-10T00:00:00Z') == 2026
    # chance models: the line's loss is the log loss of the logged price, on the model's own scale
    assert abs(line_loss('nhl', {'p': 0.6, 'L': 0.5, 'res': 2}) - math.log(2)) < 1e-9
    assert line_loss('nba', {'m': 3.0, 'L': 5.0, 'res': 1.0}) == 4.0 and line_loss('nhl', {'p': 0.6, 'res': 1}) is None
    tw = three_way({'h': -120, 'd': 280, 'a': 320})
    assert abs(sum(tw) - 1) < 1e-3 and tw[0] > tw[1] > tw[2] and three_way({'h': -120}) is None
    assert abs(line_loss('soccer', {'p': [.5, .3, .2], 'L': [.5, .25, .25], 'res': 0}) + math.log(.25)) < 1e-9
    nh = report('nhl', {f'g{i}': {'k': stamp(now - dt.timedelta(days=30) + dt.timedelta(hours=8 * i)), 'p': 0.6, 'L': 0.55,
                                 'res': 1 if i % 5 < 3 else -1} for i in range(60)}, 2027, now, {'all': (0.67, 0.2, 5000)}, [2022, 2026])
    assert nh['lineN'] == 60 and abs(nh['line'] - (-0.6 * math.log(.55) - 0.4 * math.log(.45))) < 1e-3, nh
    # tennis / CS2: held to the model's own chances; favourites priced .70 that win .70 pass, .55 alarms
    m0, s0 = own_expect(0.7)
    assert abs(m0 - 0.6109) < 1e-3 and abs(-(-math.log(0.7) - m0) / s0 - math.sqrt(3 / 7)) < 1e-9
    def cs(win, n=400):
        return {f's{i}': {'k': stamp(now - dt.timedelta(days=40) + dt.timedelta(hours=2 * i)), 'p': 0.7 if i % 2 else 0.3,
                          'res': (1 if i % 2 else -1) * (1 if (i * 7919 % 100) < win else -1)} for i in range(n)}
    good, over = report('cs2', cs(70), 2026, now), report('cs2', cs(55), 2026, now)
    assert good['status'] in ('ok', 'watch') and abs(good['expected'] - m0) < 1e-3, good
    assert over['status'] == 'alarm' and over['model'] > over['expected'], over
    pt = predictions('tennis', {'matches': [{'id': '1', 'tour': 'atp', 'tip': '2026-11-09T13:00:00Z', 'state': 'pre', 'p': 0.4, 'nv': {'p': 0.42}},
                                            {'id': '2', 'tour': 'atp', 'tip': '2026-11-09T13:00:00Z', 'state': 'in', 'p': 0.4}],
                                'results': [{'id': '3', 'tour': 'wta', 'tip': '2026-11-08T13:00:00Z', 'p': 0.7, 'detail': 'Final',
                                             'a': {'won': False}, 'b': {'won': True}},
                                            {'id': '4', 'tour': 'wta', 'tip': '2026-11-08T13:00:00Z', 'p': 0.7, 'detail': 'Walkover',
                                             'a': {'won': True}, 'b': {'won': False}}]})
    assert set(pt) == {'atp1', 'wta3'} and pt['atp1']['L'] == 0.42 and pt['wta3']['res'] == -1 and pt['wta3']['pre'], pt
    lg2 = merge(merge({}, {'atp1': dict(pt['atp1'])}, '2026-11-09T10:00:00Z'), {'atp1': {'k': '2026-11-09T13:00:00Z', 'p': 0.41, 'L': None}}, '2026-11-09T12:00:00Z')
    assert lg2['atp1']['p'] == 0.41 and lg2['atp1']['L'] == 0.42, lg2
    # a soccer match that went to extra time is logged with its result but never scored
    ps = predictions('soccer', {'games': [{'id': 9, 'tip': '2026-12-01T20:00:00Z', 'p': [.5, .3, .2], 'lg': 'uefa.champions', 'final': [2, 1], 'et': 1},
                                          {'id': 8, 'tip': '2026-12-01T20:00:00Z', 'p': [.5, .3, .2], 'lg': 'uefa.champions', 'final': [1, 1]}]})
    lg3 = merge({'9': {'k': '2026-12-01T20:00:00Z', 'p': [.5, .3, .2], 'lg': 'uefa.champions', 'at': '2026-12-01T10:00:00Z'},
                 '8': {'k': '2026-12-01T20:00:00Z', 'p': [.5, .3, .2], 'lg': 'uefa.champions', 'at': '2026-12-01T10:00:00Z'}}, ps, '2026-12-02T10:00:00Z')
    assert lg3['9'].get('et') == 1 and lg3['9']['res'] == 1 and not lg3['8'].get('et'), lg3
    assert report('soccer', lg3, 2027, now, {'all': (0.95, 0.4, 5000)}, [2022, 2026])['n'] == 1
    pc = predictions('cs2', {'results': [{'ts': 1794232800, 'ka': 'a', 'kb': 'b', 'sa': 1, 'sb': 2, 'pa': 0.4}]})
    assert list(pc.values())[0]['res'] == -1 and season_of('cs2', list(pc.values())[0]['k']) == 2026, pc
    print('model_monitor.py: all tests pass')


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--test' in a:
        test()
    else:
        for s in [x for x in a if not x.startswith('--')] or SPORTS:
            run(s, backfill='--backfill' in a, offline='--offline' in a)
        due = stale_ledger()
        if due:
            print(f"::warning::model ledger: {len(due)} model(s) past their one-year re-test: {', '.join(due)} (scripts/harness_rescore.py)")
        else:
            print('model ledger: every model inside its re-test year')
