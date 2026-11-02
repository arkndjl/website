#!/usr/bin/env python3
"""Scheduled model refits (Nov 2 2026, "every ARKBOARD model auto-updates"). Before this, each model's fit
(`--fit`, `--refit`) ran only when a thread ran it by hand; the daily workflows only score with the committed fit.
.github/workflows/model-refits.yml runs this every Monday:

    python3 scripts/refit.py plan [--all | NAME ...]   # the due jobs, as a JSON matrix (GITHUB_OUTPUT)
    python3 scripts/refit.py run NAME                  # one refit with its gate; leaves only its kept files changed
    python3 scripts/refit.py collect DIR               # merge the legs' results into data/refits.json
    python3 scripts/refit.py status                    # print every job, its cadence and last result

A job is due when its season months include this month and its last success is at least `every` days old (a
failed or never-run job is due every week in its months). Same specification, more data: a refit never adds or drops
a candidate input by itself (inputs are chosen by the selection rules each fit already runs, on the same tuning and
held-out seasons). The gate, per job:
  1. the fit exits 0 within its time limit;
  2. every file it changed parses as strict JSON (no NaN or Infinity: a bare NaN breaks the Hugo build);
  3. the job's check passes, when it has one (the daily build run on the new fit);
  4. only the job's `keep` files are kept (the check's own outputs are thrown away; the daily workflow owns them).
A job that fails any step leaves the committed fit as it was and shows "failed" in data/refits.json, which the
data-health check (scripts/data_health.py) turns into a GitHub issue through the red run.

After the fits commit, the workflow's picks job reruns games_picks.py --fit then --rules and units.py --fit (the
project rule: any game model change reruns --fit then --rules).
"""
import datetime as dt
import glob
import json
import math
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'refits.json')
ALL = list(range(1, 13))

# name: cmd (shell), months (season months when it refits), every (days between refits), keep (files kept; globs,
# repo-relative), check (shell, optional), timeout (minutes), cache (Actions cache key prefixes to restore), py (pip)
JOBS = {
    # ---- game models: walk-forward backtest against the close + refit, monthly in season
    'nba_games':     dict(cmd='python3 scripts/nba_games.py --fit', months=[11, 12, 1, 2, 3, 4, 5], every=28,
                          keep=['data/nba_games_fit.json', 'scripts/data/games_wf/nba.json.gz'], timeout=150, sport='nba'),
    'nhl_games':     dict(cmd='python3 scripts/nhl_games.py --fit', months=[11, 12, 1, 2, 3, 4, 5], every=28,
                          keep=['data/nhl_games_fit.json', 'scripts/data/games_wf/nhl.json.gz'], timeout=150, sport='nhl'),
    'nfl_games':     dict(cmd='python3 scripts/nfl_games.py --fit', months=[10, 11, 12, 1], every=28,
                          keep=['data/nfl_games_fit.json', 'scripts/data/games_wf/nfl.json.gz'], timeout=150, sport='nfl'),
    'cbb_games':     dict(cmd='python3 scripts/cbb_games.py --fit', months=[12, 1, 2, 3], every=28,
                          keep=['data/cbb_games_fit.json', 'scripts/data/games_wf/cbb.json.gz'], timeout=240, sport='cbb'),
    'soccer_games':  dict(cmd='python3 scripts/soccer_games.py --fit', months=[10, 11, 12, 1, 2, 3, 4, 5], every=28,
                          keep=['data/soccer_games_fit.json', 'scripts/data/games_wf/soccer.json.gz', 'scripts/data/soccer_team_ratings.json.gz'], timeout=150, sport='soccer'),
    'tennis_model':  dict(cmd='python3 scripts/tennis_data.py --offline && python3 scripts/tennis_model.py --fit', cache=['tennis-'], months=[2, 4, 6, 8, 10], every=56,
                          keep=['data/tennis_fit.json'], timeout=150, sport='tennis'),
    'cs2_model':     dict(cmd='python3 scripts/cs2_model.py --fit', months=ALL, every=42,
                          keep=['data/cs2_fit.json'], timeout=90, sport='cs2', cache=['cs2-vrs-v1']),
    # ---- player projections / props (game-level)
    'nba_players':   dict(cmd='python3 scripts/nba_players.py --fit', months=[12, 1, 2, 3, 4], every=28,
                          keep=['data/nba_players_fit.json'], timeout=60, sport='nba'),
    'cbb_players':   dict(cmd='python3 scripts/cbb_players.py --fit', months=[12, 1, 2, 3], every=28,
                          keep=['data/cbb_players_fit.json'], timeout=60, sport='cbb'),
    'cbb_espn_logs': dict(cmd='python3 scripts/cbb_espn_logs.py --fit && python3 scripts/cbb_espn_logs.py --check', months=[12, 2], every=56,
                          keep=['data/cbb_espn_fit.json'], timeout=40, sport='cbb', cache=['cbb-bt-']),
    # ---- the pricing layer the picks read: the close, the margin/total spread around it, cover, rating sd
    'close_model':   dict(cmd='python3 scripts/close_model.py --fit', months=ALL, every=28,
                          keep=['data/close_fit.json'], timeout=60, sport='predictions'),
    'clv':           dict(cmd='python3 scripts/clv.py --fit', months=ALL, every=28,
                          keep=['data/clv_fit.json'], timeout=60, sport='predictions'),
    'cover':         dict(cmd='python3 scripts/cover.py --fit', months=ALL, every=28,
                          keep=['data/cover_fit.json'], timeout=60, sport='predictions'),
    'rank_odds':     dict(cmd='python3 scripts/rank_odds.py --fit', months=ALL, every=56,
                          keep=['data/rank_sd.json'], timeout=60, sport='predictions'),
    'tennis_picks':  dict(cmd='python3 scripts/tennis_data.py --offline && python3 scripts/tennis_picks.py --fit', cache=['tennis-'], months=[2, 4, 6, 8, 10], every=56,
                          keep=['data/tennis_picks_fit.json'], timeout=60, sport='tennis'),
    # ---- season-level models: once a year, after the season they learn from. Not here (Nov 2 2026 local test): soccer_mv,
# hockey_provisional, hockey_prospects, soccer_prospects, tennis_prospects, cfb_transfer_fit, cs2_poly, soccer_players and
# nfl_xv need download caches no runner keeps (or hours of pulls); they stay frozen-by-design yearly rebuilds
    'nba_proj':      dict(cmd='python3 scripts/nba_proj.py --fit', months=[7], every=300,
                          keep=['data/nba_proj_fit.json'], timeout=60, sport='nba'),
    'nfl_fantasy':   dict(cmd='python3 scripts/nfl_fantasy.py --fit', months=[3], every=300,
                          keep=['data/nfl_fantasy_fit.json'], timeout=90, sport='nfl'),
    'nfl_war':       dict(cmd='python3 scripts/nfl_war.py --fit', months=[3], every=300,
                          keep=['data/nfl_war_fit.json'], timeout=90, sport='nfl'),
    'nhl_players':   dict(cmd='python3 scripts/nhl_players.py --fit', months=[7], every=300,
                          keep=['data/nhl_war_fit.json'], timeout=90, sport='nhl'),
    'pctl_nba':      dict(cmd='python3 scripts/player_pctl.py --fit nba', months=[7], every=300,
                          keep=['data/pctl_fit_nba.json', 'scripts/data/pctl_hist_nba.json.gz'], timeout=60, sport='nba'),
    'pctl_nhl':      dict(cmd='python3 scripts/player_pctl.py --fit nhl', months=[7], every=300,
                          keep=['data/pctl_fit_nhl.json', 'scripts/data/pctl_hist_nhl.json.gz'], timeout=60, sport='nhl'),
    'pctl_nfl':      dict(cmd='python3 scripts/player_pctl.py --fit nfl', months=[3], every=300,
                          keep=['data/pctl_fit_nfl.json', 'scripts/data/pctl_hist_nfl.json.gz'], timeout=60, sport='nfl'),
    'cbb_tourney':   dict(cmd='python3 scripts/cbb_tourney.py --fit', months=[5], every=300,
                          keep=['data/cbb_tourney_fit.json'], timeout=200, sport='cbb'),
    'cbb_boards':    dict(cmd='python3 scripts/cbb_boards.py --fit', months=[7], every=300,
                          keep=['scripts/data/cbb_board_att.json'], timeout=30, sport='cbb'),
}


def now():
    return dt.datetime.now(dt.timezone.utc)


def load():
    try:
        return json.load(open(OUT))
    except (OSError, ValueError):
        return {'asof': None, 'jobs': {}}


def is_due(name, j, state, t=None):
    t = t or now()
    if t.month not in j['months']:
        return False
    last = (state.get('jobs', {}).get(name) or {})
    ok = last.get('lastOk')
    if not ok:
        return True
    age = (t - dt.datetime.fromisoformat(ok.replace('Z', '+00:00'))).days
    return age >= j['every'] - 1   # a weekly schedule: a 28-day job reruns on the 4th Monday


def strict_json(path):
    def bad(x):
        raise ValueError(f'{x} in {path}')
    try:
        json.load(open(path), parse_constant=bad)
        return None
    except Exception as e:
        return str(e)[:200]


def git(*a):
    return subprocess.run(['git', *a], cwd=ROOT, capture_output=True, text=True).stdout


def changed_files():
    out = []
    for line in git('status', '--porcelain', '--untracked-files=all').splitlines():
        p = line[3:].strip()
        if ' -> ' in p:
            p = p.split(' -> ')[1]
        if p.startswith('scripts/.cache') or p.startswith('scripts/.refit') or '__pycache__' in p:
            continue
        out.append(p)
    return out


def revert(paths):
    for p in paths:
        if git('ls-files', p).strip():
            subprocess.run(['git', 'checkout', '--', p], cwd=ROOT)
        elif os.path.exists(os.path.join(ROOT, p)):
            os.remove(os.path.join(ROOT, p))


def kept(p, keep):
    import fnmatch
    return any(fnmatch.fnmatch(p, k) for k in keep)


def cmd_run(name):
    j = JOBS[name]
    os.makedirs(os.path.join(ROOT, 'scripts', '.refit'), exist_ok=True)
    res = {'job': name, 'at': now().strftime('%Y-%m-%dT%H:%M:%SZ'), 'status': 'failed', 'note': ''}
    t0 = time.time()
    try:
        p = subprocess.run(j['cmd'], shell=True, cwd=ROOT, timeout=j['timeout'] * 60,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        tail = (p.stdout or '').strip().splitlines()[-12:]
        print('\n'.join((p.stdout or '').splitlines()[-200:]))
        if p.returncode != 0:
            res['note'] = f'exit {p.returncode}: ' + ' | '.join(tail[-3:])[:300]
    except subprocess.TimeoutExpired:
        res['note'] = f'timed out after {j["timeout"]} min'
        p = None
    res['secs'] = round(time.time() - t0)
    ch = changed_files()
    keep = [c for c in ch if kept(c, j['keep'])]
    if not res['note']:
        bad = [f'{c}: {e}' for c in keep if c.endswith('.json') and (e := strict_json(os.path.join(ROOT, c)))]
        if bad:
            res['note'] = 'bad JSON: ' + '; '.join(bad)[:300]
    if not res['note'] and j.get('check'):
        c = subprocess.run(j['check'], shell=True, cwd=ROOT, timeout=3600, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if c.returncode != 0:
            res['note'] = 'check failed: ' + ' | '.join((c.stdout or '').strip().splitlines()[-3:])[:300]
    if res['note']:
        revert(ch)
        keep = []
    else:
        revert([c for c in ch if c not in keep])
        res['status'] = 'ok' if keep else 'unchanged'
    res['changed'] = keep
    json.dump(res, open(os.path.join(ROOT, 'scripts', '.refit', f'{name}.json'), 'w'), indent=1)
    print(f'{name}: {res["status"]} in {res["secs"]}s {res["note"]} kept {keep}')
    return 0


def cmd_plan(args):
    st = load()
    names = list(JOBS) if '--all' in args else [a for a in args if a in JOBS] or [n for n, j in JOBS.items() if is_due(n, j, st)]
    inc = [{'job': n, 'timeout': JOBS[n]['timeout'] + 15, 'cache': ' '.join(JOBS[n].get('cache', []))} for n in names]
    m = json.dumps({'include': inc})
    print(m)
    gh = os.environ.get('GITHUB_OUTPUT')
    if gh:
        with open(gh, 'a') as f:
            f.write(f'matrix={m}\nany={"true" if inc else "false"}\n')


def cmd_collect(d):
    st = load()
    st.setdefault('jobs', {})
    for p in sorted(glob.glob(os.path.join(d, '**', '*.json'), recursive=True)):
        try:
            r = json.load(open(p))
        except ValueError:
            continue
        if r.get('job') not in JOBS:
            continue
        j = st['jobs'].setdefault(r['job'], {})
        j.update({'last': r['at'], 'status': r['status'], 'secs': r.get('secs'), 'note': r.get('note', ''), 'changed': r.get('changed', [])})
        if r['status'] in ('ok', 'unchanged'):
            j['lastOk'] = r['at']
    for n, jb in JOBS.items():
        e = st['jobs'].setdefault(n, {})
        e['cmd'], e['months'], e['every'], e['sport'] = jb['cmd'], jb['months'], jb['every'], jb.get('sport')
    st['asof'] = now().strftime('%Y-%m-%dT%H:%M:%SZ')
    st['about'] = ('Scheduled model refits (scripts/refit.py, .github/workflows/model-refits.yml, Mondays): each job refits '
                   'its model on the data to date in its season months every `every` days, kept only if it exits clean, '
                   'writes strict JSON and passes its check; lastOk is the last kept (or unchanged) refit.')
    with open(OUT, 'w') as f:
        json.dump(st, f, indent=1, sort_keys=False)
        f.write('\n')
    print(f'{OUT}: {sum(1 for j in st["jobs"].values() if j.get("status") == "failed")} failed')
    return 1 if any(json.load(open(p)).get('status') == 'failed' for p in glob.glob(os.path.join(d, '**', '*.json'), recursive=True)) else 0


def cmd_status():
    st = load()
    for n, j in JOBS.items():
        s = st.get('jobs', {}).get(n, {})
        print(f'{n:20} months {",".join(map(str, j["months"])):28} every {j["every"]:>3}d  due {is_due(n, j, st)!s:5}  '
              f'last {s.get("last")} {s.get("status")} {s.get("note", "")[:60]}')


if __name__ == '__main__':
    a = sys.argv[1:]
    c = a[0] if a else 'status'
    if c == 'run':
        sys.exit(cmd_run(a[1]))
    if c == 'plan':
        sys.exit(cmd_plan(a[1:]))
    if c == 'collect':
        sys.exit(cmd_collect(a[1]))
    cmd_status()
