#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""ARKBOARD data health (Nov 2 2026): one place that notices when a product stops updating, run from GitHub Actions
(.github/workflows/data-health.yml) so it needs nothing outside the repo. It replaces the never-deployed staleness
check in ops/odds-cron/worker.js (same issue titles, so the two can coexist).

    python3 scripts/data_health.py stale [--dry]     # every feed in data/freshness.json against its limit
    python3 scripts/data_health.py run NAME CONCLUSION URL [--dry]   # a failed data workflow (workflow_run)
    python3 scripts/data_health.py runs [--dry]      # every watched workflow's latest run: close recovered red runs
    python3 scripts/data_health.py deploy [--dry]    # is arkndjl.net serving main? (Cloudflare stuck or failing)
    python3 scripts/data_health.py report            # print every feed's age and limit (no GitHub calls)
    python3 scripts/data_health.py rollover [--dry]  # season constants that the calendar has passed (ROLLOVER)
    python3 scripts/data_health.py test              # self-check, no GitHub calls

Alerts are GitHub issues (label data-alert), which notify the repo owner by mail and on the GitHub app:
  "stale data: <sport>"   one or more of the sport's feeds is past its limit. Opening it dispatches the sport's
                          workflow once; while it stays open the workflow is dispatched again at most once a day.
                          Closes itself when every feed is fresh.
  "red run: <workflow>"   a scheduled or dispatched data workflow ended in failure (or timed out, or failed to
                          start). Later failures add a comment (at most one every 6 hours). The 3-hourly check
                          (`runs`) closes it once the workflow's latest run is green, and opens one for a run a job
                          time limit cancelled (GitHub reports those as cancelled, like a replaced pending run, so the
                          check reads the run's jobs). The workflow_run job only starts for a failed run.
  "deploy stuck"          main has a commit older than 90 minutes that the live site still doesn't serve.
  "season rollover: <x>"  a season constant (ROLLOVER below) is behind the calendar. The yearly rollover carries
                          more than the constant (new draft-year URLs, frozen priors, FV weights by year), so it is
                          flagged for a build thread, not flipped blind; the data would otherwise stay fresh-looking
                          while describing last season.

Feed limits (data/freshness.json): in season inHours (36), out of season the sport's offHours, unless feedHours names
the feed (a weekly product gets 8 days). A feed's stamp is its checked, else asof, else updated. A date-only asof counts from the end of that day (UTC). A feed whose file is
missing or has no asof counts as stale, so a renamed file can't hide.
"""
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPO = os.environ.get('GITHUB_REPOSITORY', 'arkndjl/website')
SITE = 'https://arkndjl.net'
LABEL = 'data-alert'
DRY = '--dry' in sys.argv
NOW = dt.datetime.now(dt.timezone.utc)


# ---------------------------------------------------------------- feeds
def parse_at(a):
    if not isinstance(a, str) or not a:
        return None
    s = a.strip()
    if len(s) == 10:
        s += 'T23:59:59Z'
    s = s.replace('Z', '+00:00')
    if len(s) == 22 and s[13] == ':' and s[16] == '+':   # 2026-10-25T20:15+00:00
        s = s[:16] + ':00' + s[16:]
    try:
        t = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def feed_asof(name):
    p = os.path.join(ROOT, 'data', *name.split('.')) + '.json'
    try:
        d = json.load(open(p))
    except (OSError, ValueError):
        return None, None
    # checked: the last run that confirmed the content (scripts/checked.py), for files rewritten only on a change
    a = (d.get('checked') or d.get('asof') or d.get('updated')) if isinstance(d, dict) else None
    return a, parse_at(a)


def in_season(season, now=NOW):
    if not season:
        return True
    md = now.strftime('%m-%d')
    a, b = season
    return a <= md <= b if a <= b else (md >= a or md <= b)


def check_feeds(now=NOW):
    """{sport: {label, workflow, stale: [(feed, asof, hours, limit)], feeds: [...]}}"""
    fr = json.load(open(os.path.join(ROOT, 'data', 'freshness.json')))
    out = {}
    for k, s in fr['sports'].items():
        ins = in_season(s.get('season'), now)
        lim0 = fr.get('inHours', 36) if ins else s.get('offHours', 336)
        fh = s.get('feedHours', {})
        rows = []
        for name, file in s['feeds'].items():
            a, t = feed_asof(file)
            h = None if t is None else (now - t).total_seconds() / 3600
            lim = fh.get(name, lim0)
            if not ins:
                lim = max(lim, s.get('offHours', 336))
            rows.append((name, a, None if h is None else round(h, 1), lim))
        out[k] = {'label': s.get('label', k), 'workflow': s.get('workflow'), 'inSeason': ins, 'feeds': rows,
                  'stale': [r for r in rows if r[2] is None or r[2] > r[3]]}
    return out


# ---------------------------------------------------------------- GitHub
def gh(path, method='GET', body=None):
    tok = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if DRY or not tok:
        if method != 'GET':
            print(f'[dry] {method} {path} {json.dumps(body)[:300] if body else ""}')
            return None
        if not tok:
            return []
    url = path if path.startswith('http') else f'https://api.github.com/repos/{REPO}{path}'
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Authorization': f'Bearer {tok}', 'Accept': 'application/vnd.github+json',
                                          'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'arkboard-data-health',
                                          **({'Content-Type': 'application/json'} if body is not None else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            t = r.read()
            return json.loads(t) if t else {}
    except urllib.error.HTTPError as e:
        print(f'GitHub {method} {path}: {e.code} {e.read()[:200]!r}')
        return None


def ensure_label():
    gh('/labels', 'POST', {'name': LABEL, 'color': '7b5cd6', 'description': 'ARKBOARD data health (scripts/data_health.py)'})


def open_issues():
    return [i for i in (gh(f'/issues?state=open&labels={LABEL}&per_page=100') or []) if 'pull_request' not in i]


def find(issues, title):
    return next((i for i in issues if i['title'] == title), None)


def open_issue(title, body):
    ensure_label()
    return gh('/issues', 'POST', {'title': title, 'body': body, 'labels': [LABEL]})


def close_issue(i, note):
    gh(f'/issues/{i["number"]}/comments', 'POST', {'body': note})
    gh(f'/issues/{i["number"]}', 'PATCH', {'state': 'closed', 'state_reason': 'completed'})


def dispatch(workflow):
    if not workflow:
        return 'no workflow'
    r = gh(f'/actions/workflows/{workflow}/dispatches', 'POST', {'ref': 'main'})
    return 'dispatched' if r is not None else 'dispatch failed'


def hours_since(iso):
    t = parse_at(iso)
    return 1e9 if t is None else (NOW - t).total_seconds() / 3600


MARK = '<!-- last-dispatch: '


# season constants: (label, file, regex for the constant, expected value from the date)
ROLLOVER = [
    ('cfb season', 'scripts/fetch_cfb.mjs', r'const SEASON = (\d{4});', lambda d: d.year if d.month >= 8 else d.year - 1),
    ('cfb teams season', 'scripts/cfb_teams.mjs', r'const SEASON = (\d{4});', lambda d: d.year if d.month >= 8 else d.year - 1),
    ('cfb coaching season', 'scripts/cfb_coach.mjs', r'const SEASON = (\d{4});', lambda d: d.year if d.month >= 8 else d.year - 1),
    ('cbb season', 'scripts/cbb_live.py', r'^SEASON = (\d{4})', lambda d: d.year + 1 if d.month >= 10 else d.year),
    ('cbb games season', 'scripts/cbb_games_live.py', r'^SEASON = (\d{4})', lambda d: d.year + 1 if d.month >= 10 else d.year),
    ('cbb preseason board', 'scripts/fetch_cbb.py', r'^SEASON = (\d{4})', lambda d: d.year + 1 if d.month >= 8 else d.year),
    ('cbb internationals', 'scripts/cbb_intl.py', r'^SEASON = (\d{4})', lambda d: d.year + 1 if d.month >= 8 else d.year),
    ('cbb draft boards', 'scripts/cbb_boards.py', r'^YEAR = (\d{4})', lambda d: d.year + 1 if d.month >= 7 else d.year),
    ('cbb lineups season', 'scripts/cbb_lineups.py', r'^LIVE_SEASON = (\d{4})', lambda d: d.year + 1 if d.month >= 10 else d.year),
    ('cbb low divisions season', 'scripts/cbb_lowdiv.py', r'^LIVE = (\d{4})', lambda d: d.year + 1 if d.month >= 10 else d.year),
    ('cbb recruit class', 'scripts/cbb_recruit_fit.py', r'^NOW_CLASS = (\d{4})', lambda d: d.year if d.month >= 10 else d.year - 1),
    # the live draft class: past classes run to the year before it, and it turns over after the late-June draft
    ('hockey draft class', 'scripts/hockey_prospects.py', r'for y in range\(FIRST, (\d{4})\)', lambda d: d.year + 1 if d.month >= 7 else d.year),
    ('hockey draft class (rank fit)', 'scripts/hockey_prospects.py', r'for y0 in range\(FIRST, (\d{4})\)', lambda d: d.year + 1 if d.month >= 7 else d.year),
]


def check_rollover(now=NOW):
    import re
    out = []
    for label, f, rx, want in ROLLOVER:
        try:
            m = re.search(rx, open(os.path.join(ROOT, f)).read(), re.M)
        except OSError:
            continue
        if m and int(m.group(1)) < want(now):
            out.append((label, f, int(m.group(1)), want(now)))
    return out


def cmd_rollover():
    due = check_rollover()
    issues = open_issues()
    for label, f, have, want in due:
        print(f'{label}: {f} says {have}, the calendar says {want}')
        if not find(issues, f'season rollover: {label}'):
            open_issue(f'season rollover: {label}', f'`{f}` still builds the {have} season; by the calendar it is {want}. '
                       f'Roll the season over (constant, draft-year sources, frozen priors), then this issue closes itself.')
    for i in issues:
        if i['title'].startswith('season rollover: ') and i['title'][17:] not in {d[0] for d in due}:
            close_issue(i, 'Rolled over.')
    print(f'{len(due)} rollover(s) due')


# ---------------------------------------------------------------- commands
def cmd_report():
    for k, s in check_feeds().items():
        print(f'{k} ({"in season" if s["inSeason"] else "off-season"}, {s["workflow"]})')
        for name, a, h, lim in sorted(s['feeds'], key=lambda r: -(r[2] or 1e9)):
            flag = 'STALE' if h is None or h > lim else ''
            print(f'  {name:22} {str(a):28} {"-" if h is None else h:>7} h  limit {lim:>4} {flag}')


def stale_body(s, last):
    lines = '\n'.join(f'| {n} | {a or "missing"} | {"-" if h is None else round(h)} | {lim} |' for n, a, h, lim in s['stale'])
    return (f'The {s["label"]} data has feeds past their limit ({"in season" if s["inSeason"] else "off-season"}).\n\n'
            f'| feed | asof | hours | limit |\n|---|---|---|---|\n{lines}\n\n'
            f'Refresh workflow: `{s["workflow"]}` (dispatched automatically, at most once a day while this is open). '
            f'Feed rules: data/freshness.json. This issue closes itself when every feed is fresh '
            f'(scripts/data_health.py, every 3 hours).\n\n{MARK}{last} -->')


def cmd_stale():
    issues = open_issues()
    bad = 0
    for k, s in check_feeds().items():
        title = f'stale data: {k}'
        i = find(issues, title)
        if s['stale']:
            bad += 1
            print(f'{k}: stale {[(n, h) for n, _, h, _ in s["stale"]]}')
            if not i:
                d = dispatch(s['workflow'])
                open_issue(title, stale_body(s, NOW.strftime('%Y-%m-%dT%H:%M:%SZ')))
                print(f'  issue opened, {d}')
            else:
                body = i.get('body') or ''
                last = body.split(MARK, 1)[1].split(' -->')[0] if MARK in body else i['created_at']
                if hours_since(last) >= 24:
                    print(f'  still stale after {round(hours_since(last))} h: {dispatch(s["workflow"])}')
                    last = NOW.strftime('%Y-%m-%dT%H:%M:%SZ')
                gh(f'/issues/{i["number"]}', 'PATCH', {'body': stale_body(s, last)})
        elif i:
            close_issue(i, 'Every feed is fresh again: ' + ', '.join(f'{n} {a}' for n, a, _, _ in s['feeds']))
            print(f'{k}: fresh, issue #{i["number"]} closed')
    # the old Worker's issues (label stale-data) close the same way
    for i in gh('/issues?state=open&labels=stale-data&per_page=100') or []:
        k = i['title'].replace('stale data: ', '')
        if k in check_feeds() and not check_feeds()[k]['stale']:
            close_issue(i, 'Fresh again (scripts/data_health.py).')
    print(f'{bad} sport(s) with stale feeds')


# the workflows data-health.yml listens to (its workflow_run list; `test` fails when the two differ)
WATCH = ['cbb board', 'cbb boards', 'cbb recruits', 'cfb board', 'cs2', 'esea season', 'nba xpm', 'nfl', 'nhl',
         'nhl goalies', 'odds snap', 'picks refresh', 'soccer', 'soccer prospects', 'tennis', 'tennis prospects',
         'model refits', 'build gate']
RED = ('failure', 'timed_out', 'startup_failure')
RED_WORD = {'failure': 'failed', 'timed_out': 'timed out', 'startup_failure': 'failed to start',
            'cancelled': 'was cancelled by a job time limit'}
LONG_MIN = 9      # a cancelled run with a job that ran this long hit its time limit (the shortest limit is 10 minutes)
SWEEP_H = 3.5     # the 3-hourly check opens an issue only for a run that ended since its last pass


def cmd_run(name, conclusion, url):
    issues = open_issues()
    title = f'red run: {name}'
    i = find(issues, title)
    if conclusion in RED or conclusion == 'cancelled-long':
        word = RED_WORD.get(conclusion, RED_WORD['cancelled'])
        if not i:
            open_issue(title, f'The `{name}` workflow {word}: {url}\n\nThe step that failed kept the last good file, so '
                              f'the site shows older data for that product until a run passes. This issue closes once '
                              f'the workflow\'s latest run is green (scripts/data_health.py, every 3 hours).')
            print('issue opened')
        elif hours_since(i['updated_at']) >= 6:
            gh(f'/issues/{i["number"]}/comments', 'POST', {'body': f'{word.capitalize()} again: {url}'})
            print('comment added')
    elif conclusion == 'success' and i:
        close_issue(i, f'Green again: {url}')
        print(f'issue #{i["number"]} closed')
    else:
        print(f'{name}: {conclusion}, nothing to do')    # cancelled (a replaced pending run), skipped, neutral


def minutes(a, b):
    a, b = parse_at(a), parse_at(b)
    return 0 if a is None or b is None else (b - a).total_seconds() / 60


def hit_limit(run):
    """a cancelled run where a job really ran LONG_MIN minutes or more (a pending run that concurrency replaced has
    no job that started)"""
    if minutes(run.get('run_started_at') or run.get('created_at'), run.get('updated_at')) < LONG_MIN:
        return False
    jobs = gh(f'/actions/runs/{run["id"]}/jobs?per_page=50')
    jobs = jobs.get('jobs', []) if isinstance(jobs, dict) else []
    return any(j.get('conclusion') == 'cancelled' and minutes(j.get('started_at'), j.get('completed_at')) >= LONG_MIN for j in jobs)


def verdict(runs):
    """(conclusion, run) of the newest completed run on main that says something: success, a RED conclusion, or
    'cancelled-long' (a job time limit). Replaced pending runs, skipped and pull-request runs are passed over."""
    for r in runs:
        if r.get('event') == 'pull_request' or r.get('status') != 'completed':
            continue
        c = r.get('conclusion')
        if c == 'success' or c in RED:
            return c, r
        if c == 'cancelled' and hit_limit(r):
            return 'cancelled-long', r
    return None, None


def cmd_runs():
    """The 3-hourly pass over every watched workflow. Its latest run green: close the red-run issue. Its latest run
    red and ended since the last pass, with no issue open: open one (a job time limit, or a missed event)."""
    issues = open_issues()
    wfs = gh('/actions/workflows?per_page=100')
    wfs = {w['name']: w for w in (wfs.get('workflows', []) if isinstance(wfs, dict) else [])}
    names = list(WATCH) + [i['title'][9:] for i in issues if i['title'].startswith('red run: ') and i['title'][9:] not in WATCH]
    red = 0
    for name in names:
        w = wfs.get(name)
        if not w:
            print(f'{name}: workflow not found')
            continue
        rs = gh(f'/actions/workflows/{w["id"]}/runs?branch=main&status=completed&per_page=20')
        c, r = verdict(rs.get('workflow_runs', []) if isinstance(rs, dict) else [])
        i = find(issues, f'red run: {name}')
        if c == 'success':
            if i:
                close_issue(i, f'Green again: {r["html_url"]}')
                print(f'{name}: green, issue #{i["number"]} closed')
        elif c:
            red += 1
            print(f'{name}: latest run {c} {r["html_url"]}')
            if not i and hours_since(r.get('updated_at')) <= SWEEP_H:
                cmd_run(name, c, r['html_url'])
    print(f'{red} workflow(s) with a red latest run')


def cmd_test():
    """Self-check with GitHub stubbed: the workflow list against data-health.yml, each conclusion's handling, the
    3-hourly pass (close on green, open on a job time limit, leave replaced pending runs alone), rollover rules."""
    import re
    global gh
    yml = open(os.path.join(ROOT, '.github', 'workflows', 'data-health.yml')).read()
    m = re.search(r'workflow_run:\s*\n\s*workflows: \[(.*?)\]', yml, re.S)
    listed = [x.strip() for x in m.group(1).replace('\n', ' ').split(',') if x.strip()]
    assert sorted(listed) == sorted(WATCH), ('data-health.yml and WATCH differ', sorted(set(listed) ^ set(WATCH)))
    for n in WATCH:      # every watched name is a workflow in the repo
        assert any(re.search(rf'^name: {re.escape(n)}$', open(os.path.join(ROOT, '.github', 'workflows', f)).read(), re.M)
                   for f in os.listdir(os.path.join(ROOT, '.github', 'workflows'))), n
    real, calls, state = gh, [], {}

    def fake(path, method='GET', body=None):
        if method != 'GET':
            calls.append((method, path.split('?')[0], (body or {}).get('title') or (body or {}).get('state') or 'comment'))
            return {}
        if path.startswith('/issues'):
            return state.get('issues', [])
        if path.startswith('/actions/workflows?'):
            return {'workflows': [{'name': n, 'id': k} for k, n in enumerate(WATCH)]}
        if '/jobs' in path:
            return {'jobs': state['jobs'].get(int(path.split('/')[3]), [])}
        return {'workflow_runs': state['runs'].get(int(path.split('/')[3]), [])}
    gh = fake
    try:
        z = lambda h: (NOW - dt.timedelta(hours=h)).strftime('%Y-%m-%dT%H:%M:%SZ')
        issue = lambda n, name, upd=30: {'number': n, 'title': f'red run: {name}', 'updated_at': z(upd), 'created_at': z(upd)}
        # run: one conclusion at a time
        for c, had, want in (('failure', False, 'open'), ('timed_out', False, 'open'), ('startup_failure', False, 'open'),
                             ('cancelled', False, None), ('skipped', False, None), ('success', False, None),
                             ('success', True, 'close'), ('cancelled', True, None), ('failure', True, 'comment')):
            calls.clear(); state['issues'] = [issue(7, 'nfl')] if had else []
            cmd_run('nfl', c, 'https://x/1')
            got = ('open' if any(k[2] == 'red run: nfl' for k in calls) else 'close' if any(k[2] == 'closed' for k in calls)
                   else 'comment' if calls else None)
            assert got == want, (c, had, got, calls)
        # runs: nfl was red and its latest run is green (close); odds snap's latest is a replaced pending run over an
        # older green (nothing); cs2's latest was cancelled by its 30-minute limit an hour ago (open); nhl failed an
        # hour ago and no event filed it (open); soccer failed 9 hours ago with no issue (left: closed by hand)
        run = lambda i, c, end, mins=3, ev='schedule': {'id': i, 'conclusion': c, 'status': 'completed', 'event': ev, 'html_url': f'https://x/{i}',
                                                        'run_started_at': z(end + mins / 60), 'updated_at': z(end)}
        ix = WATCH.index
        state['issues'] = [issue(1, 'nfl'), issue(2, 'tennis')]
        state['runs'] = {ix('nfl'): [run(10, 'success', 1), run(9, 'failure', 5)],
                         ix('odds snap'): [run(20, 'cancelled', 0.2, 0), run(19, 'success', 0.5)],
                         ix('cs2'): [run(30, 'cancelled', 1, 30), run(29, 'success', 20)],
                         ix('nhl'): [run(40, 'failure', 1)],
                         ix('soccer'): [run(50, 'failure', 9)],
                         ix('tennis'): [run(61, 'cancelled', 0.1, 14), run(60, 'failure', 30)],
                         ix('build gate'): [run(71, 'failure', 1, ev='pull_request'), run(70, 'success', 2, ev='push')]}
        j = lambda mins: [{'conclusion': 'cancelled', 'started_at': z(1 + mins / 60), 'completed_at': z(1)}]
        state['jobs'] = {30: j(30), 61: [{'conclusion': 'cancelled', 'started_at': None, 'completed_at': z(0.1)}]}
        calls.clear(); cmd_runs()
        opened = sorted(k[2] for k in calls if str(k[2]).startswith('red run'))
        closed = sorted(k[1] for k in calls if k[2] == 'closed')
        assert opened == ['red run: cs2', 'red run: nhl'], opened
        assert closed == ['/issues/1'], closed          # nfl closed; tennis (a 14-minute wait in the queue, then replaced) stays open
    finally:
        gh = real
    # rollover rules: every constant is found, none due today, each due a year on
    for label, f, rx, want in ROLLOVER:
        assert re.search(rx, open(os.path.join(ROOT, f)).read(), re.M), (label, 'constant not found')
    assert not check_rollover(NOW), check_rollover(NOW)
    later = NOW.replace(year=NOW.year + 1)
    assert len(check_rollover(later)) == len(ROLLOVER), [x[0] for x in ROLLOVER if x[0] not in {y[0] for y in check_rollover(later)}]
    # every feed in data/freshness.json names a data file with a stamp
    for k, sp in check_feeds().items():
        for name, a, h, lim in sp['feeds']:
            assert a, (k, name, 'no asof')
    print('data_health test ok')


def cmd_deploy():
    try:
        req = urllib.request.Request(f'{SITE}/build.json?t={int(NOW.timestamp())}', headers={'User-Agent': 'arkboard-data-health', 'Cache-Control': 'no-cache'})
        live = json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception as e:
        live = {'sha': None, 'err': str(e)}
    sha = live.get('sha')
    issues = open_issues()
    i = find(issues, 'deploy stuck')
    behind = None
    if sha and sha != 'unknown':
        cmp = gh(f'/compare/{sha}...main')
        if cmp and isinstance(cmp, dict):
            commits = cmp.get('commits') or []
            if cmp.get('status') in ('ahead', 'diverged') and commits:
                oldest = commits[0]['commit']['committer']['date']
                behind = (len(commits), hours_since(oldest), oldest)
            else:
                behind = (0, 0, None)
    stuck = (behind is None and not sha) or (behind and behind[0] and behind[1] > 1.5)
    print(f'live {str(sha)[:9]} built {live.get("built")}; behind main: {behind}')
    if stuck and not i:
        why = (f'arkndjl.net/build.json did not load ({live.get("err")}).' if not sha else
               f'The live site serves {sha[:9]} (built {live.get("built")}); main is {behind[0]} commit(s) ahead, the oldest '
               f'from {behind[2]} ({round(behind[1], 1)} h ago).')
        open_issue('deploy stuck', why + '\n\nCheck the Cloudflare build log (Workers & Pages > website > Builds) and the '
                   '`build gate` workflow; README "Deploying" has the manual fallback. Closes itself once live serves main.')
    elif not stuck and i and sha:
        close_issue(i, f'Live again: {sha[:9]} built {live.get("built")}.')


if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if x != '--dry']
    c = a[0] if a else 'report'
    if c == 'report':
        cmd_report()
    elif c == 'stale':
        cmd_stale()
    elif c == 'run':
        cmd_run(*a[1:4])
    elif c == 'runs':
        cmd_runs()
    elif c == 'test':
        cmd_test()
    elif c == 'deploy':
        cmd_deploy()
    elif c == 'rollover':
        cmd_rollover()
    else:
        print(__doc__)
