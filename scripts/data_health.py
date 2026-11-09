#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""ARKBOARD data health (Nov 2 2026): one place that notices when a product stops updating, run from GitHub Actions
(.github/workflows/data-health.yml) so it needs nothing outside the repo. It replaces the never-deployed staleness
check in ops/odds-cron/worker.js (same issue titles, so the two can coexist).

    python3 scripts/data_health.py stale [--dry]     # every feed in data/freshness.json against its limit
    python3 scripts/data_health.py run NAME CONCLUSION URL [--dry]   # a finished data workflow (workflow_run)
    python3 scripts/data_health.py deploy [--dry]    # is arkndjl.net serving main? (Cloudflare stuck or failing)
    python3 scripts/data_health.py report            # print every feed's age and limit (no GitHub calls)
    python3 scripts/data_health.py rollover [--dry]  # season constants that the calendar has passed (ROLLOVER)

Alerts are GitHub issues (label data-alert), which notify the repo owner by mail and on the GitHub app:
  "stale data: <sport>"   one or more of the sport's feeds is past its limit. Opening it dispatches the sport's
                          workflow once; while it stays open the workflow is dispatched again at most once a day.
                          Closes itself when every feed is fresh.
  "red run: <workflow>"   a scheduled or dispatched data workflow ended in failure. Later failures add a comment
                          (at most one every 6 hours); the next green run closes it.
  "deploy stuck"          main has a commit older than 90 minutes that the live site still doesn't serve.
  "season rollover: <x>"  a season constant (ROLLOVER below) is behind the calendar. The yearly rollover carries
                          more than the constant (new draft-year URLs, frozen priors, FV weights by year), so it is
                          flagged for a build thread, not flipped blind; the data would otherwise stay fresh-looking
                          while describing last season.

Feed limits (data/freshness.json): in season inHours (36), out of season the sport's offHours, unless feedHours names
the feed (a weekly product gets 8 days). A date-only asof counts from the end of that day (UTC). A feed whose file is
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
    a = (d.get('asof') or d.get('updated')) if isinstance(d, dict) else None
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


def cmd_run(name, conclusion, url):
    issues = open_issues()
    title = f'red run: {name}'
    i = find(issues, title)
    if conclusion == 'failure':
        if not i:
            open_issue(title, f'The `{name}` workflow failed: {url}\n\nThe step that failed kept the last good file, so '
                              f'the site shows older data for that product until a run passes. This issue closes on the '
                              f'next green run (scripts/data_health.py).')
            print('issue opened')
        elif hours_since(i['updated_at']) >= 6:
            gh(f'/issues/{i["number"]}/comments', 'POST', {'body': f'Failed again: {url}'})
            print('comment added')
    elif conclusion == 'success' and i:
        close_issue(i, f'Green again: {url}')
        print(f'issue #{i["number"]} closed')


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
    elif c == 'deploy':
        cmd_deploy()
    elif c == 'rollover':
        cmd_rollover()
    else:
        print(__doc__)
