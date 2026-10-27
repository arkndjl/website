#!/usr/bin/env python3
"""Keep the Predictions page's picks fresh between the sport builds (Noah, Oct 27 2026: "make it so that picks auto refresh").

    python3 scripts/picks_refresh.py            # every pick sport in season (data/freshness.json windows)
    python3 scripts/picks_refresh.py nba nfl    # some sports
    python3 scripts/picks_refresh.py --dry      # say what it would do, run and dispatch nothing

Two jobs, run by the odds-snap workflow (every tick, including the ones ops/odds-cron dispatches) and by its own
picks-refresh workflow on a second schedule, since GitHub drops most of this repo's scheduled runs:

1. Light refresh: scripts/games_picks.py <sport> on the last build's model numbers with DraftKings' current lines and
   prices through ESPN (a few seconds a sport). New picks, withdrawals, line moves and finals land without a full build.
   Skipped while that sport's build is queued or running, so the two never write the same files at once.
2. Watchdog: when a sport's build workflow (freshness.json "workflow") has not succeeded for STALE_H hours in season,
   and nothing of it ran or was queued in the last RETRY_H hours, dispatch it once. That build moves the slate to the
   next week (new games and model numbers), which the light refresh cannot do.

GitHub calls use GITHUB_TOKEN (the workflow needs actions: write; a workflow_dispatch made with it does start a run).
Without a token both checks are skipped and the light refresh just runs.
"""
import datetime
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SPORTS = ('cfb', 'nfl', 'cbb', 'nba')
STALE_H = 12          # a sport build older than this in season gets dispatched
RETRY_H = 4           # ...unless one ran, started or was queued this recently
BUSY = {'queued', 'in_progress', 'waiting', 'requested', 'pending'}
REPO = os.environ.get('GITHUB_REPOSITORY', 'arkndjl/website')
TOKEN = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')


def gh(path, body=None):
    req = urllib.request.Request(f'https://api.github.com/repos/{REPO}{path}', data=json.dumps(body).encode() if body else None,
                                 method='POST' if body else 'GET',
                                 headers={'Authorization': f'Bearer {TOKEN}', 'Accept': 'application/vnd.github+json',
                                          'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'arkboard-picks-refresh'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, (json.load(r) if r.status != 204 else None)


def ts(s):
    return datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))


def in_season(season, now):
    md = now.strftime('%m-%d')
    a, b = season
    return a <= md <= b if a <= b else md >= a or md <= b


def runs(workflow):
    """the workflow's last 20 runs on main, newest first (None without a token or on an API error)"""
    if not TOKEN:
        return None
    try:
        return gh(f'/actions/workflows/{workflow}/runs?branch=main&per_page=20')[1]['workflow_runs']
    except Exception as e:
        print(f'  {workflow}: runs not read ({e})')
        return None


def main(args):
    dry = '--dry' in args
    pick = [a for a in args if a in SPORTS] or SPORTS
    fresh = json.load(open(os.path.join(ROOT, 'data', 'freshness.json')))['sports']
    now = datetime.datetime.now(datetime.timezone.utc)
    for s in pick:
        f = fresh.get(s, {})
        if f.get('season') and not in_season(f['season'], now):
            print(f'{s}: out of season')
            continue
        wf, rs = f.get('workflow'), runs(f.get('workflow')) if f.get('workflow') else None
        busy = rs is not None and any(r['status'] in BUSY for r in rs)
        if busy:
            print(f'{s}: {wf} is queued or running, picks left to it')
        elif dry:
            print(f'{s}: would run games_picks.py {s}')
        else:
            p = subprocess.run([sys.executable, os.path.join(HERE, 'games_picks.py'), s], cwd=ROOT, timeout=300)
            if p.returncode:
                print(f'{s}: games_picks.py exited {p.returncode}')
        if rs is None:
            continue
        ok = [ts(r['created_at']) for r in rs if r['conclusion'] == 'success']
        age = (now - max(ok)).total_seconds() / 3600 if ok else 1e9
        recent = [r for r in rs if (now - ts(r['created_at'])).total_seconds() < RETRY_H * 3600]
        if age <= STALE_H:
            print(f'{s}: {wf} last succeeded {age:.1f} h ago')
        elif busy or recent:
            print(f'{s}: {wf} last succeeded {age:.1f} h ago; a run is under way or was tried in the last {RETRY_H} h')
        elif dry:
            print(f'{s}: {wf} last succeeded {age:.1f} h ago, would dispatch')
        else:
            try:
                st = gh(f'/actions/workflows/{wf}/dispatches', {'ref': 'main'})[0]
            except Exception as e:
                st = e
            print(f'{s}: {wf} last succeeded {age:.1f} h ago, dispatched ({st})')


def tennis(dry):
    """tennis picks (scripts/tennis_picks.py, Oct 27 2026): the last tennis build's model chances at Novig's current
    moneylines; its own build (tennis.yml) moves the draw on"""
    if dry:
        print('tennis: would run tennis_picks.py')
        return
    p = subprocess.run([sys.executable, os.path.join(HERE, 'tennis_picks.py')], cwd=ROOT, timeout=300)
    if p.returncode:
        print(f'tennis: tennis_picks.py exited {p.returncode}')


if __name__ == '__main__':
    main(sys.argv[1:])
    if not [a for a in sys.argv[1:] if a in SPORTS] or 'tennis' in sys.argv[1:]:
        tennis('--dry' in sys.argv[1:])
