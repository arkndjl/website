# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Season rollover runner (Nov 28 2026, Noah: "auto progress between seasons/season states"). Carries out the site
transitions in data/seasons/<sport>.json on their dates, once each, and records them in data/season_state.json.
Run by .github/workflows/season-roll.yml twice a day; a run that starts hours late (GitHub schedules do) just does the
due steps then, since every step is keyed on its date and done once.

    python3 scripts/season_roll.py               # due steps today, then the state files
    python3 scripts/season_roll.py --dry         # what would happen, nothing written, no GitHub calls
    python3 scripts/season_roll.py --on 2027-05-02 --dry [--sport cfb]   # a dry run on any date (per-sport rehearsal)
    python3 scripts/season_roll.py --plan [--to 2027-12-31]   # every step from today to the date, with what it does
    python3 scripts/season_roll.py --test        # self-check on copies, nothing in the repo changes

Steps (`do`):
  key      the change lives in the calendar keys (phase, post day, class year) that the boards read through
           scripts/season.py; the runner only records the day it took effect
  archive  copies the finished season's output files to scripts/data/history/<sport>/<season>/<file>.gz (kept for good;
           the season views read their own per-season files, this is the frozen record of the boards as they ended)
  bump     moves every hard-coded constant in the step's key (`bumps`) to the calendar value. All or none: when any bump
           is marked auto 0 (it needs a refit, a freeze or new source ids first) nothing is changed and the step alerts
           with the checklist. Changed files are compiled and the step's `test` commands run; a failure puts every file
           back, alerts, and the step is tried again on the next run
  run      runs one command (e.g. a history rebuild); a failure alerts and is retried next run
  alert    a hand job (new source ids, budgets, frozen bases): a GitHub issue opens `lead` days before the date and the
           step is done when the issue is closed

Failures never break a page: a step that can't finish leaves the site on the state it was in, with an open issue
("season rollover: <step id>", label data-alert) that notifies the repo owner.
"""
import datetime as dt
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import season as S  # noqa: E402

STATE = os.path.join(ROOT, 'data', 'season_state.json')
STATIC = os.path.join(ROOT, 'static', 'data', 'seasons.json')
HIST = os.path.join(ROOT, 'scripts', 'data', 'history')
DRY = '--dry' in sys.argv
YEAR = re.compile(r'\b(20[0-9]{2})\b')
PREFIX = 'season rollover: '


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


# ---------------------------------------------------------------- bumps (pure, testable)
def read_have(text, b):
    """the constant's current value in the file text, or None when the pattern is gone"""
    m = re.search(b['rx'], text, re.M)
    if not m:
        return None
    if b.get('mode') == 'shift':
        y = YEAR.search(m.group(0))
        return int(y.group(1)) if y else None
    return int(m.group(1))


def apply_bump(text, b, want):
    """text with the constant moved to `want` (int: the one group; shift / shift-line: every year at or above the old
    value inside the match moves by the same step, so 2027-2029 class tabs become 2028-2030)"""
    m = re.search(b['rx'], text, re.M)
    if not m:
        raise ValueError(f'{b["file"]}: pattern not found')
    have = read_have(text, b)
    if have == want:
        return text
    if b.get('mode') in ('shift', 'shift-line'):
        step = want - have
        seg = YEAR.sub(lambda y: str(int(y.group(1)) + step) if int(y.group(1)) >= have else y.group(1), m.group(0))
        return text[:m.start()] + seg + text[m.end():]
    return text[:m.start(1)] + str(want) + text[m.end(1):]


def want_of(sport, b, on):
    v = S.value(sport, b['key'], on)
    return None if v is None else int(v) + int(b.get('off', 0))


def bump_plan(sport, key, on, root=ROOT):
    """[(bump, have, want)] for the key's bumps that are behind the calendar"""
    out = []
    for b in S.load()[sport].get('bumps', []):
        if b['key'] != key:
            continue
        p = os.path.join(root, b['file'])
        try:
            have = read_have(open(p).read(), b)
        except OSError:
            have = None
        w = want_of(sport, b, on)
        if have is None or w is None or have < w:
            out.append((b, have, w))
    return out


def compile_check(files, root=ROOT):
    for f in files:
        p = os.path.join(root, f)
        if f.endswith('.py'):
            cmd = [sys.executable, '-m', 'py_compile', p]
        elif f.endswith(('.mjs', '.js')):
            cmd = ['node', '--check', p]
        else:
            continue
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            return f'{f}: {(r.stderr or r.stdout).strip()[-600:]}'
    return None


def run_cmds(cmds, root=ROOT):
    for c in cmds or []:
        r = subprocess.run(c, shell=True, cwd=root, capture_output=True, text=True, timeout=1800)
        if r.returncode:
            return f'`{c}` exit {r.returncode}\n{(r.stderr or r.stdout)[-1500:]}'
    return None


def do_bump(sport, st, on, root=ROOT, dry=DRY):
    plan = bump_plan(sport, st['key'], on, root)
    if not plan:
        return 'done', 'every constant already on the calendar value'
    bad = [(b, h, w) for b, h, w in plan if not b.get('auto', 1) or h is None]
    if bad:
        lines = '\n'.join(f'- `{b["file"]}` {h} to {w}' + (f' ({b["why"]})' if b.get('why') else '') +
                          (' (pattern not found)' if h is None else '') for b, h, w in plan)
        return 'alert', f'{st["t"]}: these constants have to move together and some need a hand step first:\n{lines}'
    if dry:
        return 'dry', '; '.join(f'{b["file"]} {h} to {w}' for b, h, w in plan)
    keep = {}
    try:
        for b, h, w in plan:
            p = os.path.join(root, b['file'])
            keep.setdefault(p, open(p).read())
            new = apply_bump(open(p).read(), b, w)
            with open(p, 'w') as fh:
                fh.write(new)
        err = compile_check(sorted({b['file'] for b, _, _ in plan}), root) or run_cmds(st.get('test'), root)
    except Exception as e:  # noqa: BLE001
        err = f'{type(e).__name__}: {e}'
    if err:
        for p, t in keep.items():
            open(p, 'w').write(t)
        return 'alert', f'{st["t"]}: the bump failed its check and every file was put back.\n```\n{err}\n```'
    return 'done', '; '.join(f'{b["file"]} {h} to {w}' for b, h, w in plan)


def do_archive(sport, st, root=ROOT, dry=DRY):
    dest = os.path.join(root, 'scripts', 'data', 'history', sport, str(st['season']))
    got, miss = [], []
    for f in st.get('files', []):
        p = os.path.join(root, f)
        if not os.path.exists(p):
            miss.append(f)
            continue
        got.append(f)
        if not dry:
            os.makedirs(dest, exist_ok=True)
            with open(p, 'rb') as a, gzip.open(os.path.join(dest, os.path.basename(f) + '.gz'), 'wb') as z:
                shutil.copyfileobj(a, z)
    if not got:
        return 'alert', f'{st["t"]}: none of the files exist ({", ".join(miss)})'
    if not dry:
        json.dump({'sport': sport, 'season': st['season'], 'archived': dt.date.today().isoformat(), 'files': got,
                   'missing': miss}, open(os.path.join(dest, 'index.json'), 'w'), indent=1)
    return ('dry' if dry else 'done'), f'{len(got)} files' + (f', missing {", ".join(miss)}' if miss else '')


# ---------------------------------------------------------------- the run
def load_state():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return {'done': {}, 'log': []}


def step_rows(on, only=None):
    for sport, c in S.load().items():
        if only and sport != only:
            continue
        for st in c.get('steps', []):
            yield sport, st


def gh_issues():
    import data_health as H
    return H, H.open_issues()


def roll(on, only=None, dry=DRY, root=ROOT):
    state = load_state()
    done = state.setdefault('done', {})
    log = state.setdefault('log', [])
    H = issues = None
    if not dry:
        try:
            H, issues = gh_issues()
        except Exception as e:  # noqa: BLE001
            print('GitHub issues unavailable:', e)
    out = []

    def alert(st, sport, body):
        title = PREFIX + st['id']
        print(f'ALERT {title}: {body.splitlines()[0]}')
        if H is not None and not H.find(issues, title):
            H.open_issue(title, f'{body}\n\nCalendar: `data/seasons/{sport}.json` step `{st["id"]}` ({st["on"]}). '
                                f'The runner retries on every run; close this issue when the hand step is done.')

    for sport, st in step_rows(on, only):
        if st['id'] in done:
            continue
        when = dt.date.fromisoformat(st['on'])
        lead = int(st.get('lead', 0))
        if on < when - dt.timedelta(days=lead):
            continue
        if on < when:
            # early warning: a bump that will need a hand step, or an alert job, opens its issue `lead` days ahead
            if st['do'] == 'bump':
                res, msg = do_bump(sport, st, when, root, dry=True)
                if res == 'alert':
                    alert(st, sport, f'Due {st["on"]}. ' + msg)
                    out.append((sport, st['id'], 'warn', msg.splitlines()[0]))
            elif st['do'] == 'alert':
                alert(st, sport, f'Due {st["on"]}. {st["t"]}\n\n{st.get("body", "")}')
                out.append((sport, st['id'], 'warn', st['t']))
            continue
        if st['do'] == 'key':
            res, msg = ('dry' if dry else 'done'), 'calendar key'
        elif st['do'] == 'archive':
            res, msg = do_archive(sport, st, root, dry)
        elif st['do'] == 'bump':
            res, msg = do_bump(sport, st, on, root, dry)
        elif st['do'] == 'run':
            if dry:
                res, msg = 'dry', st['cmd']
            else:
                err = run_cmds([st['cmd']], root)
                res, msg = ('alert', f'{st["t"]} failed.\n```\n{err}\n```') if err else ('done', st['cmd'])
        elif st['do'] == 'alert':
            title = PREFIX + st['id']
            if H is not None and not H.find(issues, title) and any(e.get('id') == st['id'] for e in log):
                res, msg = 'done', 'issue closed'
            else:
                res, msg = 'alert', f'{st["t"]}\n\n{st.get("body", "")}'
                if dry:
                    res = 'dry'
        else:
            res, msg = 'alert', f'unknown step type {st["do"]}'
        if res == 'alert':
            alert(st, sport, msg)
            if not any(e.get('id') == st['id'] and e.get('res') == 'alert' for e in log[-50:]):
                log.append({'id': st['id'], 'sport': sport, 'on': on.isoformat(), 'res': 'alert'})
        elif res == 'done':
            done[st['id']] = {'on': st['on'], 'at': on.isoformat(), 'note': msg[:300]}
            log.append({'id': st['id'], 'sport': sport, 'on': on.isoformat(), 'res': 'done'})
            if H is not None:
                i = H.find(issues, PREFIX + st['id'])
                if i:
                    H.close_issue(i, f'Done {on.isoformat()}: {msg[:500]}')
        out.append((sport, st['id'], res, msg.splitlines()[0] if msg else ''))
    state['log'] = log[-400:]
    return state, out


def write_state(state, on):
    state['on'] = on.isoformat()
    state['sports'] = S.state(on)
    try:   # a run with nothing new keeps the old stamp, so the workflow has nothing to commit (and no deploy)
        old = json.load(open(STATE))
    except (OSError, ValueError):
        old = {}
    bare = lambda d: json.loads(json.dumps({k: v for k, v in d.items() if k != 'asof'}, sort_keys=True))
    same = bool(old.get('asof')) and bare(old) == bare(state)
    state['asof'] = old['asof'] if same else dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    json.dump(state, open(STATE, 'w'), indent=1, sort_keys=True)
    open(STATE, 'a').write('\n')
    # the browser copy (gfx.js season week, ARKLOG calendar filters): phases, post days and the next 400 days
    pub = {'asof': state['asof'], 'on': state['on'],
           'sports': {s: {k: v for k, v in x.items() if k in ('phase', 'season', 'post', 'next')}
                      for s, x in state['sports'].items()},
           'phases': {s: c.get('keys', {}).get('phase', []) for s, c in S.load().items()},
           'events': [{k: r[k] for k in ('d', 'to', 'k', 't', 'sport', 'kind', 'est') if k in r}
                      for r in S.events(on - dt.timedelta(days=60), ahead=460)]}
    os.makedirs(os.path.dirname(STATIC), exist_ok=True)
    json.dump(pub, open(STATIC, 'w'), separators=(',', ':'))


def plan(on, to, only=None):
    rows = []
    for sport, st in step_rows(on, only):
        d = dt.date.fromisoformat(st['on'])
        if not (on <= d <= to):
            continue
        what = st['t']
        if st['do'] == 'bump':
            p = bump_plan(sport, st['key'], d)
            what += ' | ' + ('; '.join(f'{b["file"]} {h}->{w}{"" if b.get("auto", 1) else " (hand)"}' for b, h, w in p)
                             or 'nothing behind')
        elif st['do'] == 'archive':
            what += ' | ' + ', '.join(f + ('' if os.path.exists(os.path.join(ROOT, f)) else ' (missing)') for f in st['files'])
        rows.append((st['on'], sport, st['do'], st['id'], what))
    for r in sorted(rows):
        print('  '.join(r))
    return rows


# ---------------------------------------------------------------- self-test
def _test():
    assert not S.check(), S.check()
    # pure bump logic
    b = {'file': 'x.md', 'rx': r'\{\{< wintabs tab="classes"[\s\S]*?\{\{< /wintabs >\}\}', 'mode': 'shift', 'key': 'class'}
    t = 'a\n{{< wintabs tab="classes" tabs="2027 class,2028 class,2029 class" >}}\n{{< x year="2028" >}}\n{{< /wintabs >}}\n2027'
    t2 = apply_bump(t, b, 2028)
    assert 'tabs="2028 class,2029 class,2030 class"' in t2 and 'year="2029"' in t2 and t2.endswith('2027'), t2
    b = {'file': 'y.py', 'rx': r"^YEARS = \{'cfb': \(2012, (\d{4})\), 'cbb': \(2010, \d{4}\)\}", 'mode': 'shift-line'}
    assert apply_bump("YEARS = {'cfb': (2012, 2029), 'cbb': (2010, 2029)}\n", b, 2030) == \
        "YEARS = {'cfb': (2012, 2030), 'cbb': (2010, 2030)}\n"
    b = {'file': 'z.py', 'rx': r'^SEASON = (\d{4})'}
    assert apply_bump('SEASON = 2027\nX = 2027\n', b, 2028) == 'SEASON = 2028\nX = 2027\n'
    # every bump pattern matches its file today, and no constant is ahead of the calendar
    today = S.today()
    for sport, c in S.load().items():
        for b in c.get('bumps', []):
            have = read_have(open(os.path.join(ROOT, b['file'])).read(), b)
            assert have is not None, f'{sport}: {b["file"]} {b["rx"]} not found'
            w = want_of(sport, b, today)
            assert have >= w, f'{sport}: {b["file"]} {have} behind the calendar {w} today'
    # rehearsal on a copy of the repo files: every auto step on its date applies and compiles; nothing in ROOT changes
    with tempfile.TemporaryDirectory() as tmp:
        files = {b['file'] for c in S.load().values() for b in c.get('bumps', [])}
        for f in files:
            os.makedirs(os.path.dirname(os.path.join(tmp, f)), exist_ok=True)
            shutil.copy(os.path.join(ROOT, f), os.path.join(tmp, f))
        n = 0
        for sport, st in step_rows(today):
            if st['do'] != 'bump':
                continue
            d = dt.date.fromisoformat(st['on'])
            before = bump_plan(sport, st['key'], d, tmp)
            res, msg = do_bump(sport, st, d, tmp, dry=False)
            if any(not b.get('auto', 1) for b, _, _ in before):
                assert res == 'alert', (st['id'], res, msg)
            else:
                assert res == 'done', (st['id'], res, msg)
                assert not bump_plan(sport, st['key'], d, tmp), st['id']
                n += 1
        # a step whose check fails puts the file back
        st = {'id': 't', 't': 't', 'key': 'season', 'test': ['false']}
        p = os.path.join(tmp, 'scripts/cfb_dob.py')
        shutil.copy(os.path.join(ROOT, 'scripts/cfb_dob.py'), p)
        before = open(p).read()
        res, _ = do_bump('cfb', st, dt.date(2027, 5, 2), tmp, dry=False)
        assert res == 'alert' and open(p).read() == before
    # archive in dry mode finds the files
    for sport, st in step_rows(today):
        if st['do'] == 'archive':
            res, msg = do_archive(sport, st, ROOT, dry=True)
            assert res in ('dry', 'alert'), (st['id'], res)
    print(f'season_roll ok: {n} auto bump steps rehearsed on copies')


if __name__ == '__main__':
    if '--test' in sys.argv:
        _test()
        sys.exit(0)
    on = dt.date.fromisoformat(arg('--on')) if arg('--on') else S.today()
    only = arg('--sport')
    if '--plan' in sys.argv:
        plan(on, dt.date.fromisoformat(arg('--to', (on + dt.timedelta(days=400)).isoformat())), only)
        sys.exit(0)
    errs = S.check()
    if errs:
        sys.exit('calendar: ' + '; '.join(errs))
    state, out = roll(on, only, DRY)
    for r in out:
        print(f'{r[0]:7} {r[1]:28} {r[2]:6} {r[3]}')
    if not out:
        print('nothing due')
    if not DRY and not arg('--on'):
        write_state(state, on)
    # a red run only for a broken runner; a step that alerts is not a red run (its issue is the alert)
