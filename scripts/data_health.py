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
    python3 scripts/data_health.py rollover [--dry]  # season calendar steps past their date and not done (season_roll.py)
    python3 scripts/data_health.py injuries [report] [--dry]   # each sport's injury sources and snapshot (INJ)
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
  "stale injuries: <sport>"  in season, RotoWire's injury news for the sport, the model's injury snapshot or one of
                          its sources has gone quiet (INJ). Dispatches odds-snap (news) or the sport's workflow.
  "deploy stuck"          main has a commit older than 90 minutes that the live site still doesn't serve.
  "season rollover: <id>" a season calendar step (data/seasons/<sport>.json) is two days past its date and not
                          done: the season-roll runner failed, or the step needs a hand job (new source ids, a
                          freeze). Opened by the runner itself too; closes once the step is in data/season_state.json.

Repair (Nov 19 2026, Noah: "fix all stale feeds and set up ways to autofix them"):
  - a red run's failed log is classified first (classify): a network, rate-limit, 5xx or push-race failure reruns its
    failed jobs once; a code error is not retried, and its issue carries the traceback with label needs-fix
  - a stale sport with its issue open is redispatched by plan_redispatch: nothing while a run is going, 3 h after main
    moves past a red run (a fix landed), once a day otherwise; when the red run is on the current main and the sport
    has `fallback` inputs in data/freshness.json (cfb/nfl refresh = cached PFN/On3/CFBD), that run goes first
  - writers that keep an unchanged file stamp `checked` (scripts/checked.py) so a quiet stretch isn't stale

Feed limits (data/freshness.json): in season inHours (36), out of season the sport's offHours, unless feedHours names
the feed (a weekly product gets 8 days). A feed's stamp is its checked, else asof, else updated. A date-only asof counts from the end of that day (UTC). A feed whose file is
missing or has no asof counts as stale, so a renamed file can't hide.
"""
import datetime as dt
import http.client
import json
import os
import sys
import time
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


try:
    FRESH = json.load(open(os.path.join(ROOT, 'data', 'freshness.json')))
except (OSError, ValueError):
    FRESH = {'sports': {}}


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
    for k in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                t = r.read()
                return json.loads(t) if t else {}
        except urllib.error.HTTPError as e:
            print(f'GitHub {method} {path}: {e.code} {e.read()[:200]!r}')
            return None
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            # a dropped connection (the Nov 22 check died on RemoteDisconnected): reads are retried, writes are not
            # (a POST that did land would file the issue twice)
            print(f'GitHub {method} {path}: {type(e).__name__} {e}')
            if method != 'GET' or k == 2:
                return None
            time.sleep(3 * (k + 1))


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


def dispatch(workflow, inputs=None):
    if not workflow:
        return 'no workflow'
    r = gh(f'/actions/workflows/{workflow}/dispatches', 'POST', {'ref': 'main', **({'inputs': inputs} if inputs else {})})
    return ('dispatched' + (f' {inputs}' if inputs else '')) if r is not None else 'dispatch failed'


# ---------------------------------------------------------------- repair (Nov 19 2026, "fix all stale feeds and autofix them")
# A red run is read from its failed log before anything is retried, so a code bug doesn't burn a rerun:
#   transient  network, rate limit, 5xx, push race: the failed jobs rerun once (attempt 1 only)
#   code       a Python/Node exception that isn't a network one: no rerun; the issue carries the traceback, label needs-fix
#   unknown    no log or no exception line: one rerun, same as transient
# Time-limit stops (timed_out, cancelled-long) never rerun: a second 30-minute run costs more than the alert saves.
NET = ('URLError', 'HTTPError', 'TimeoutError', 'timeout', 'ConnectionError', 'ConnectionResetError', 'ConnectionRefusedError',
       'RemoteDisconnected', 'IncompleteRead', 'SSLError', 'ProtocolError', 'ReadTimeout', 'ConnectTimeout', 'gaierror',
       'ChunkedEncodingError', 'FetchError', 'AbortError')
NET_TEXT = ('HTTP Error 5', 'HTTP Error 429', 'Too Many Requests', 'rate limit', 'timed out', 'Temporary failure in name',
            'Could not resolve host', 'ECONNRESET', 'ETIMEDOUT', 'EAI_AGAIN', 'socket hang up', 'Connection reset',
            '[rejected]', 'fetch first', 'cannot lock ref', 'non-fast-forward', 'failed to push', '502 Bad Gateway',
            '503 Service', '504 Gateway', 'The runner has received a shutdown signal', 'Internal Server Error')
NEEDS_FIX = 'needs-fix'


def clean_log(text, keep=40):
    """the failed log's last lines without the runner's timestamps and the post-job git cleanup"""
    import re
    out = []
    for ln in (text or '').splitlines():
        ln = re.sub(r'^(\S+\t){0,2}\d{4}-\d\d-\d\dT[\d:.]+Z ?', '', ln).rstrip()
        if ln.startswith(('Post job cleanup', '[command]/usr/bin/git', 'Cleaning up orphan')):
            break
        if ln and not ln.startswith(('##[group]', '##[endgroup]')):
            out.append(ln)
    return out[-keep:]


def classify(text):
    """(kind, reason) of a failed log: transient | code | unknown"""
    import re
    lines = clean_log(text, 400)
    exc = [m.group(1) for ln in lines for m in [re.match(r'^\s*(?:Uncaught )?([A-Za-z_][\w.]*(?:Error|Exception|Interrupt)):?', ln)] if m]
    last = exc[-1] if exc else None
    if last and not any(n in last for n in NET):
        return 'code', last
    hit = next((t for t in NET_TEXT if any(t in ln for ln in lines)), None)
    if last or hit:
        return 'transient', last or hit
    return 'unknown', None


def rerun(run_id):
    r = gh(f'/actions/runs/{run_id}/rerun-failed-jobs', 'POST', {})
    return r is not None


def plan_redispatch(since_dispatch_h, latest, main_sha, fallback, since_fallback_h):
    """what the stale check does for a sport whose issue is already open:
    (action, why) with action in None | 'dispatch' | 'fallback'.
      a run queued or in progress         wait: it is the repair
      latest run red on today's main      the same code fails the same way: the fallback inputs (cached sources) once a
                                          day if the sport has them, else a plain retry once a day
      latest run red, main has moved      a fix may have landed: dispatch after 3 h
      latest run green, feeds still stale the writer ran and kept the file: a retry at most once a day"""
    if latest and latest.get('status') in ('queued', 'in_progress', 'waiting', 'requested', 'pending'):
        return None, 'a run is already going'
    red = bool(latest) and latest.get('conclusion') in RED
    if red and latest.get('head_sha') == main_sha:
        if fallback and since_fallback_h >= 24:
            return 'fallback', 'latest run red on the current main: cached-source run'
        return ('dispatch', 'latest run red on the current main, daily retry') if since_dispatch_h >= 24 else (None, 'red on the current main; waiting for a fix')
    if red:
        return ('dispatch', 'main moved since the red run') if since_dispatch_h >= 3 else (None, 'main moved; dispatched lately')
    return ('dispatch', 'daily retry') if since_dispatch_h >= 24 else (None, 'dispatched lately')


def latest_run(workflow):
    rs = gh(f'/actions/workflows/{workflow}/runs?branch=main&per_page=5') if workflow else None
    rs = [r for r in (rs.get('workflow_runs', []) if isinstance(rs, dict) else []) if r.get('event') != 'pull_request']
    return rs[0] if rs else None


def main_sha():
    c = gh('/commits/main')
    return c.get('sha') if isinstance(c, dict) else None


def hours_since(iso):
    t = parse_at(iso)
    return 1e9 if t is None else (NOW - t).total_seconds() / 3600


MARK = '<!-- last-dispatch: '


# season rollovers (Nov 28 2026): the calendar in data/seasons/<sport>.json and its runner scripts/season_roll.py
# (season-roll workflow) carry out every transition on its date and record it in data/season_state.json. This check is
# the backstop: a step two days past its date and still not done (the runner is red, or a hand step is waiting) gets
# "season rollover: <step id>", the same title the runner uses, so there is one issue per step. It closes once done.
def check_rollover(now=NOW):
    sys.path.insert(0, HERE)
    import season as SN
    try:
        done = json.load(open(os.path.join(ROOT, 'data', 'season_state.json'))).get('done', {})
    except (OSError, ValueError):
        done = {}
    day = now.date() - dt.timedelta(days=2)
    out = []
    for sport, c in SN.load().items():
        for st in c.get('steps', []):
            if st['id'] not in done and dt.date.fromisoformat(st['on']) <= day:
                out.append((st['id'], sport, st['on'], st.get('t', '')))
    return out


def cmd_rollover():
    due = check_rollover()
    issues = open_issues()
    for sid, sport, on, t in due:
        print(f'{sid}: due {on}, not done ({t})')
        if not find(issues, f'season rollover: {sid}'):
            open_issue(f'season rollover: {sid}', f'{t}: due {on} in `data/seasons/{sport}.json` and still not done. '
                       f'See the season roll workflow log (scripts/season_roll.py); this issue closes once the step is done.')
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


FMARK = '<!-- last-fallback: '


def stale_body(s, last, run=None, why=None):
    lines = '\n'.join(f'| {n} | {a or "missing"} | {"-" if h is None else round(h)} | {lim} |' for n, a, h, lim in s['stale'])
    return (f'The {s["label"]} data has feeds past their limit ({"in season" if s["inSeason"] else "off-season"}).\n\n'
            f'| feed | asof | hours | limit |\n|---|---|---|---|\n{lines}\n\n'
            f'Refresh workflow: `{s["workflow"]}`, dispatched automatically while this is open: after 3 h when main has '
            f'moved past a red run, daily otherwise, with the sport\'s cached-source fallback (data/freshness.json '
            f'`fallback`) when the red run is on the current main.'
            + (f' Latest run: {run.get("conclusion") or run.get("status")} {run.get("html_url")} ({why}).' if run else '') + ' '
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
                lastfb = body.split(FMARK, 1)[1].split(' -->')[0] if FMARK in body else '2000-01-01T00:00:00Z'
                fb = FRESH['sports'].get(k, {}).get('fallback')
                run = latest_run(s['workflow'])
                act, why = plan_redispatch(hours_since(last), run, main_sha() if run else None, fb, hours_since(lastfb))
                if act == 'fallback':
                    print(f'  {why}: {dispatch(s["workflow"], fb)}')
                    lastfb = last = NOW.strftime('%Y-%m-%dT%H:%M:%SZ')
                elif act:
                    print(f'  still stale after {round(hours_since(last))} h, {why}: {dispatch(s["workflow"])}')
                    last = NOW.strftime('%Y-%m-%dT%H:%M:%SZ')
                else:
                    print(f'  {why}')
                gh(f'/issues/{i["number"]}', 'PATCH', {'body': stale_body(s, last, run, why) + f'\n{FMARK}{lastfb} -->'})
        elif i:
            close_issue(i, 'Every feed is fresh again: ' + ', '.join(f'{n} {a}' for n, a, _, _ in s['feeds']))
            print(f'{k}: fresh, issue #{i["number"]} closed')
    # the old Worker's issues (label stale-data) close the same way
    for i in gh('/issues?state=open&labels=stale-data&per_page=100') or []:
        k = i['title'].replace('stale data: ', '')
        if k in check_feeds() and not check_feeds()[k]['stale']:
            close_issue(i, 'Fresh again (scripts/data_health.py).')
    print(f'{bad} sport(s) with stale feeds')


# ---------------------------------------------------------------- injuries
# Each sport's injury inputs, checked apart from the feeds (Nov 17 2026, after Drake Maye's injury sat at last week's
# Doubtful): a build can stay fresh while an injury source has gone quiet. In season, per sport:
#   news:  RotoWire's injury log (scripts/data/rotowire_news.json, polled every half hour by odds-snap) has an item for
#          the sport within newsH hours; a stall dispatches odds-snap.yml
#   snap:  the model's injury snapshot (file, its checked/asof) is under snapH hours old; dispatches the sport's workflow
#   srcs:  the snapshot's per-source counts (NFL: data/nfl_injuries.json srcs) are above zero for each named source
# "stale injuries: <sport>" issues open and close like the stale-data ones.
INJ = {
    'nfl': {'news': 'football', 'newsH': 12, 'snap': 'nfl_injuries', 'snapH': 16, 'srcs': ['espn', 'rotowire']},
    'cfb': {'news': 'cfootball', 'newsH': 36, 'snap': 'cfb_injuries', 'snapH': 36},
    'nba': {'news': 'basketball', 'newsH': 12, 'snap': 'nba_games', 'snapH': 16},
    'cbb': {'news': 'cbasketball', 'newsH': 24, 'snap': 'cbb_injuries', 'snapH': 12},
    'nhl': {'news': 'hockey', 'newsH': 18, 'snap': 'nhl_games', 'snapH': 20},
    'soccer': {'news': 'soccer', 'newsH': 72},
}


def check_injuries(now=NOW):
    """{sport: {label, workflow, inSeason, rows: [(check, stamp, hours, limit, ok)], bad: [...], fix: workflow}}"""
    fr = json.load(open(os.path.join(ROOT, 'data', 'freshness.json')))['sports']
    try:
        items = json.load(open(os.path.join(ROOT, 'scripts', 'data', 'rotowire_news.json'))).get('items', {}).values()
    except (OSError, ValueError, AttributeError):
        items = []
    newest = {}
    for it in items:
        if isinstance(it, dict) and it.get('sport'):
            newest[it['sport']] = max(newest.get(it['sport'], 0), it.get('ts') or 0)
    out = {}
    for k, c in INJ.items():
        f = fr.get(k, {})
        ins = in_season(f.get('season'), now)
        rows, fix = [], set()
        ts = newest.get(c['news'])
        h = None if not ts else (now.timestamp() - ts) / 3600
        rows.append(('RotoWire news', None if not ts else dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
                     None if h is None else round(h, 1), c['newsH'], h is not None and h <= c['newsH']))
        if c.get('snap'):
            a, t = feed_asof(c['snap'])
            h = None if t is None else (now - t).total_seconds() / 3600
            rows.append((f"snapshot {c['snap']}", a, None if h is None else round(h, 1), c['snapH'], h is not None and h <= c['snapH']))
            if c.get('srcs'):
                try:
                    n = json.load(open(os.path.join(ROOT, 'data', c['snap'] + '.json'))).get('srcs') or {}
                except (OSError, ValueError):
                    n = {}
                for sname in c['srcs']:
                    rows.append((f'source {sname}', str(n.get(sname, 0)) + ' items', None, None, (n.get(sname) or 0) > 0))
        bad = [r for r in rows if not r[4]] if ins else []
        for r in bad:
            fix.add('odds-snap.yml' if r[0] == 'RotoWire news' else f.get('workflow'))
        out[k] = {'label': f.get('label', k), 'workflow': f.get('workflow'), 'inSeason': ins, 'rows': rows, 'bad': bad,
                  'fix': sorted(x for x in fix if x)}
    return out


def inj_body(s, last):
    lines = '\n'.join(f'| {n} | {a or "missing"} | {"-" if h is None else round(h)} | {"-" if lim is None else lim} |'
                      for n, a, h, lim, _ in s['bad'])
    return (f'The {s["label"]} injury inputs have gone quiet in season.\n\n| check | stamp | hours | limit |\n|---|---|---|---|\n'
            f'{lines}\n\nDispatched: {", ".join(f"`{w}`" for w in s["fix"]) or "nothing"} (at most once a day while this is '
            f'open). Rules: INJ in scripts/data_health.py. Closes itself when every check passes (every 3 hours).\n\n{MARK}{last} -->')


def cmd_injuries():
    issues = open_issues()
    for k, s in check_injuries().items():
        title = f'stale injuries: {k}'
        i = find(issues, title)
        if s['bad']:
            print(f'{k}: {[(r[0], r[2]) for r in s["bad"]]}')
            if not i:
                d = [dispatch(w) for w in s['fix']]
                open_issue(title, inj_body(s, NOW.strftime('%Y-%m-%dT%H:%M:%SZ')))
                print(f'  issue opened, {d}')
            else:
                body = i.get('body') or ''
                last = body.split(MARK, 1)[1].split(' -->')[0] if MARK in body else i['created_at']
                if hours_since(last) >= 24:
                    print(f'  still quiet after {round(hours_since(last))} h: {[dispatch(w) for w in s["fix"]]}')
                    last = NOW.strftime('%Y-%m-%dT%H:%M:%SZ')
                gh(f'/issues/{i["number"]}', 'PATCH', {'body': inj_body(s, last)})
        elif i:
            close_issue(i, 'Injury inputs current again: ' + ', '.join(f'{r[0]} {r[1]}' for r in s['rows']))
            print(f'{k}: current, issue #{i["number"]} closed')


def cmd_injury_report():
    for k, s in check_injuries().items():
        print(f'{k} injuries ({"in season" if s["inSeason"] else "off-season"})')
        for n, a, h, lim, ok in s['rows']:
            print(f'  {n:24} {str(a):30} {"" if h is None else f"{h:6.1f} h"}  {"" if lim is None else f"limit {lim:4}"} {"" if ok else "STALE"}')


# the workflows data-health.yml listens to (its workflow_run list; `test` fails when the two differ)
WATCH = ['cbb board', 'cbb boards', 'cbb recruits', 'cfb board', 'cs2', 'esea season', 'nba xpm', 'nfl', 'nhl',
         'nhl goalies', 'odds snap', 'picks refresh', 'soccer', 'soccer prospects', 'tennis', 'tennis prospects',
         'model refits', 'build gate', 'wave', 'awards', 'cfb recruits', 'cs2 ark loop', 'esea research',
         'process refresh', 'recruit leans', 'recruit news', 'rotowire history', 'search index', 'site stats',
         'soccer extra', 'soccer intl', 'cbb bracket matrix', 'cs2 market log', 'darko log', 'dratings log',
         'nhl lineups log']
RED = ('failure', 'timed_out', 'startup_failure')
RED_WORD = {'failure': 'failed', 'timed_out': 'timed out', 'startup_failure': 'failed to start',
            'cancelled': 'was cancelled by a job time limit'}
LONG_MIN = 9      # a cancelled run with a job that ran this long hit its time limit (the shortest limit is 10 minutes)
SWEEP_H = 3.5     # the 3-hourly check opens an issue only for a run that ended since its last pass


def cmd_run(name, conclusion, url, run_id=None, attempt=1, log=None):
    """a red run: read its failed log, rerun a transient failure once, then file or update the issue"""
    issues = open_issues()
    title = f'red run: {name}'
    i = find(issues, title)
    if conclusion in RED or conclusion == 'cancelled-long':
        word = RED_WORD.get(conclusion, RED_WORD['cancelled'])
        kind, reason = classify(log) if conclusion == 'failure' else ('limit', conclusion)
        if run_id and int(attempt or 1) == 1 and kind in ('transient', 'unknown'):
            if rerun(run_id):
                print(f'{name}: {kind} failure ({reason}), failed jobs rerun')
                return 'rerun'
        tail = clean_log(log)
        excerpt = ('\n\n```\n' + '\n'.join(tail)[-3500:] + '\n```') if tail else ''
        what = {'code': f'a code error (`{reason}`): a rerun fails the same way, so nothing was retried',
                'transient': f'a source or network failure (`{reason}`) that failed again on its rerun',
                'unknown': 'a failure with no exception in the log, after one rerun',
                'limit': 'a job time limit (not retried)'}[kind]
        if not i:
            r = open_issue(title, f'The `{name}` workflow {word}: {url}\n\nCause: {what}.{excerpt}\n\nThe step that failed '
                                  f'kept the last good file, so the site shows older data for that product until a run passes. '
                                  f'This issue closes once the workflow\'s latest run is green (scripts/data_health.py, every 3 hours).')
            if kind == 'code' and isinstance(r, dict) and r.get('number'):
                label_fix(r['number'])
            print(f'issue opened ({kind})')
        elif hours_since(i['updated_at']) >= 6:
            gh(f'/issues/{i["number"]}/comments', 'POST', {'body': f'{word.capitalize()} again: {url}\n\nCause: {what}.{excerpt}'})
            if kind == 'code':
                label_fix(i['number'])
            print('comment added')
    elif conclusion == 'success' and i:
        close_issue(i, f'Green again: {url}')
        print(f'issue #{i["number"]} closed')
    else:
        print(f'{name}: {conclusion}, nothing to do')    # cancelled (a replaced pending run), skipped, neutral


def label_fix(n):
    gh('/labels', 'POST', {'name': NEEDS_FIX, 'color': 'd94f8a', 'description': 'a data workflow fails on a code error: rerunning will not fix it'})
    gh(f'/issues/{n}/labels', 'POST', {'labels': [NEEDS_FIX]})


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
    # repair: a failed log is read before a rerun (code errors don't rerun), and the stale redispatch plan
    soccer = ('2026-11-19T21:57:57.6655191Z injuries: refreshed 2162 players at 95 clubs\n'
              '2026-11-19T21:58:23.5591554Z Traceback (most recent call last):\n'
              '2026-11-19T21:58:23.5600985Z   File "scripts/soccer_games.py", line 2103, in <module>\n'
              "2026-11-19T21:58:23.5605622Z TypeError: type NoneType doesn't define __round__ method\n"
              '2026-11-19T21:58:24.0087012Z ##[error]Process completed with exit code 1.\n'
              '2026-11-19T21:58:24.0257785Z Post job cleanup.\n2026-11-19T21:58:24.1 [command]/usr/bin/git version\n')
    assert classify(soccer) == ('code', 'TypeError'), classify(soccer)
    assert clean_log(soccer)[-1] == '##[error]Process completed with exit code 1.', clean_log(soccer)
    assert classify('Traceback\nurllib.error.URLError: <urlopen error timed out>')[0] == 'transient'
    assert classify('Traceback\nurllib.error.HTTPError: HTTP Error 503: Service Unavailable')[0] == 'transient'
    assert classify(' ! [rejected]        main -> main (fetch first)\nerror: failed to push some refs')[0] == 'transient'
    assert classify('KeyError: \'games\'')[0] == 'code'
    assert classify('') == ('unknown', None)
    calls.clear(); state['issues'] = []
    gh = lambda path, method='GET', body=None: (calls.append((method, path)) or {}) if method != 'GET' else []
    assert cmd_run('soccer', 'failure', 'u', run_id=5, attempt=1, log=soccer) is None
    assert not any('rerun' in c[1] for c in calls) and any(c[1] == '/issues' for c in calls), calls
    calls.clear()
    assert cmd_run('nfl', 'failure', 'u', run_id=6, attempt=1, log='URLError: timed out') == 'rerun'
    calls.clear()
    assert cmd_run('nfl', 'failure', 'u', run_id=6, attempt=2, log='URLError: timed out') is None    # one rerun only
    assert cmd_run('cs2', 'timed_out', 'u', run_id=7, attempt=1) is None and not any('rerun' in c[1] for c in calls)
    gh = real
    R = lambda c, sha='m', st='completed': {'conclusion': c, 'head_sha': sha, 'status': st, 'html_url': 'u'}
    P = plan_redispatch
    assert P(30, R(None, st='in_progress'), 'm', None, 99)[0] is None
    assert P(5, R('failure'), 'm', {'refresh': 'true'}, 99)[0] == 'fallback'
    assert P(5, R('failure'), 'm', {'refresh': 'true'}, 5)[0] is None
    assert P(5, R('failure'), 'm', None, 99)[0] is None and P(25, R('failure'), 'm', None, 99)[0] == 'dispatch'
    assert P(4, R('failure', 'old'), 'm', None, 99)[0] == 'dispatch' and P(2, R('failure', 'old'), 'm', None, 99)[0] is None
    assert P(5, R('success'), 'm', None, 99)[0] is None and P(25, R('success'), 'm', None, 99)[0] == 'dispatch'
    for k, sp in FRESH['sports'].items():        # a fallback names inputs its workflow declares
        if sp.get('fallback'):
            y = open(os.path.join(ROOT, '.github', 'workflows', sp['workflow'])).read()
            assert all(re.search(rf'^\s+{re.escape(x)}:\s*$', y, re.M) for x in sp['fallback']), (k, sp['fallback'])
    # rollover backstop: reads the season calendar; a date a year on finds steps due
    later = NOW.replace(year=NOW.year + 1)
    assert len(check_rollover(later)) > len(check_rollover(NOW)), 'season calendar steps'
    # every injury check names a sport in data/freshness.json and a snapshot with a stamp
    for k, sp in check_injuries().items():
        assert k in json.load(open(os.path.join(ROOT, 'data', 'freshness.json')))['sports'], k
        for name, a, h, lim, ok in sp['rows']:
            assert a, (k, name, 'no stamp')
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
        lp = os.environ.get('RUN_LOG')
        cmd_run(*a[1:4], run_id=os.environ.get('RUN_ID'), attempt=os.environ.get('RUN_ATTEMPT') or 1,
                log=open(lp, errors='replace').read() if lp and os.path.exists(lp) else None)
    elif c == 'runs':
        cmd_runs()
    elif c == 'test':
        cmd_test()
    elif c == 'deploy':
        cmd_deploy()
    elif c == 'rollover':
        cmd_rollover()
    elif c == 'injuries':
        cmd_injury_report() if 'report' in a[1:] else cmd_injuries()
    else:
        print(__doc__)
