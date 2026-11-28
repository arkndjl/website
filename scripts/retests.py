# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Scheduled retests (Nov 28 2026): every failed or deferred test with a future retest date, run on its date.

    python3 scripts/retests.py            check every test, run what is due, write data/retests_state.json
    python3 scripts/retests.py --dry      print what is due, change nothing
    python3 scripts/retests.py --due      the hand retests that are due now (the monthly retest task reads this)
    python3 scripts/retests.py --test     self-check

The registry is data/retests.json "tests" (added to by hand the day a test fails or is deferred). Each test has a date:
`after` = "sport:kind:year", the first event of that kind ending in that year in data/seasons/<sport>.json, plus `lag`
days (so a league date that moves takes the retest with it); else `due`. Then by `how`:
  watch  a workflow already reruns the test (esea-research.yml, the soccer runs): its output file is read here,
         watch {file, key, pass, fail?}. A pass is recorded once; the pipeline that reruns it ships it by itself.
  auto   run [commands] here once the date has come and `ready` holds; verdict {file, key, pass} decides, and
         ship [commands] run only on a pass. A fail is recorded with the date; nothing ships.
  hand   needs data or a kit that a runner does not have: on its date (and once `ready` holds) a GitHub issue opens
         (label retest) with the trigger, the gate and how to run it; the monthly retest task runs it. The issue
         closes when the test's `result` {d, v, e, tt, pr} is in data/retests.json.
Conditions (`pass`, `fail`, `ready.pass`): eq:X, ge:N, le:N, len:N (a list at least N long), empty, nonempty.

Writes data/retests_state.json: one row a test with its resolved date and state (waiting, data, due, watching, done,
shipped, failed, part shipped), and the results the runner recorded itself (watch and auto). ARKLOG > retests and the
Process overview read it; scripts/arklog.py logs the runner's own results as rows (k = 'retest'). A retest run by hand
is logged by its pull request (its ARKLOG line), not twice.
"""
import datetime as dt
import glob
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, 'data', 'retests.json')
OUT = os.path.join(ROOT, 'data', 'retests_state.json')
CAL = os.path.join(ROOT, 'data', 'seasons')
LABEL = 'retest'
PREFIX = 'retest due: '
VNAME = {'s': 'shipped', 'f': 'failed', 'm': 'part shipped'}
DRY = '--dry' in sys.argv


def today():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo('America/New_York')).date()
    except Exception:            # pragma: no cover
        return dt.date.today()


def load(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def calendar():
    out = {}
    for f in glob.glob(os.path.join(CAL, '*.json')):
        c = load(f, {}) or {}
        out[os.path.basename(f)[:-5]] = c.get('events') or []
    return out


def resolve(t, cal):
    """(date, est) of a test: `after` through the calendar, else `due`"""
    if t.get('after'):
        sp, k, yr = t['after'].split(':')
        for e in sorted(cal.get(sp, []), key=lambda e: e['d']):
            end = e.get('to') or e['d']
            if e.get('k') == k and end[:4] == yr:
                d = dt.date.fromisoformat(end) + dt.timedelta(days=int(t.get('lag') or 0))
                return d, int(bool(e.get('est') or t.get('est')))
    return dt.date.fromisoformat(t['due']), int(bool(t.get('est')))


def pick(file, key):
    d = load(os.path.join(ROOT, file))
    if d is None:
        return None, False
    for p in (key or '').split('.') if key else []:
        if not isinstance(d, dict) or p not in d:
            return None, True
        d = d[p]
    return d, True


def holds(v, spec):
    if not spec:
        return False
    op, _, x = spec.partition(':')
    if op == 'empty':
        return v is not None and not v
    if op == 'nonempty':
        return bool(v)
    if op == 'eq':
        return str(v) == x
    if op == 'len':
        return isinstance(v, (list, dict)) and len(v) >= int(x)
    try:
        if op == 'ge':
            return float(v) >= float(x)
        if op == 'le':
            return float(v) <= float(x)
    except (TypeError, ValueError):
        return False
    raise ValueError(f'unknown condition {spec!r}')


def ready(t):
    r = t.get('ready')
    if not r:
        return True
    v, ok = pick(r['file'], r.get('key'))
    return ok and holds(v, r['pass'])


def run_cmds(cmds):
    for c in cmds or []:
        print('  $', c, flush=True)
        p = subprocess.run(c, shell=True, cwd=ROOT, timeout=1200)
        if p.returncode:
            return False
    return True


def brief(t, d):
    lines = [f'**{t["t"]}** ({", ".join(t.get("sp") or [])}), due {d.isoformat()}.', '']
    for lab, k in (('Last result', 'was'), ('Trigger', 'trigger'), ('Gate', 'gate'), ('Run', 'run_hint'), ('Ledger family', 'ledger')):
        if t.get(k):
            lines.append(f'- {lab}: {t[k]}')
    if t.get('pr'):
        lines.append(f'- Earlier test: #{t["pr"]}')
    lines += ['', f'Registry key `{t["key"]}` in `data/retests.json`. Run it once with the gate above; only a pass ships. '
              'In the pull request that runs it, add `result` {d, v (s / f / m), e, tt, pr} to the test and end the '
              'description with its ARKLOG line. This issue closes itself once the result is in the registry.']
    return '\n'.join(lines)


class Issues:
    """GitHub issues through scripts/data_health.py's client (GITHUB_TOKEN); does nothing without a token"""
    def __init__(self):
        self.H, self.open = None, []
        if DRY or not os.environ.get('GITHUB_TOKEN'):
            return
        try:
            sys.path.insert(0, os.path.join(ROOT, 'scripts'))
            import data_health as H
            self.H = H
            self.open = [i for i in (H.gh(f'/issues?state=open&labels={LABEL}&per_page=100') or []) if 'pull_request' not in i]
        except Exception as e:   # the API is down: the state still writes, issues wait for the next run
            print('GitHub issues unavailable:', e)
            self.H = None

    def find(self, t):
        return next((i for i in self.open if i['title'] == PREFIX + t['t']), None)

    def ensure(self, t, d):
        i = self.find(t)
        if i or self.H is None:
            return i and i['number']
        self.H.gh('/labels', 'POST', {'name': LABEL, 'color': '43b5a0', 'description': 'a scheduled retest is due (scripts/retests.py)'})
        i = self.H.gh('/issues', 'POST', {'title': PREFIX + t['t'], 'body': brief(t, d), 'labels': [LABEL]})
        return i and i.get('number')

    def close(self, t, note):
        i = self.find(t)
        if i and self.H is not None:
            self.H.gh(f'/issues/{i["number"]}/comments', 'POST', {'body': note})
            self.H.gh(f'/issues/{i["number"]}', 'PATCH', {'state': 'closed', 'state_reason': 'completed'})


def check(reg, prev, on, issues=None):
    """the state of every test on date `on`; runs auto tests and opens / closes issues as a side effect"""
    cal = calendar()
    runs = dict((prev or {}).get('runs') or {})
    rows = []
    for t in reg['tests']:
        d, est = resolve(t, cal)
        res = t.get('result') or runs.get(t['key'])
        row = {k: t[k] for k in ('key', 't', 'sp', 'ar', 'kind', 'how', 'was', 'pr', 'trigger', 'gate', 'ledger') if t.get(k) not in (None, '')}
        row.update(due=d.isoformat(), est=est)
        if res:
            st = 'done' if t.get('kind') == 'data' else VNAME.get(res.get('v'), 'done')
            row['result'] = res
            if issues is not None:
                issues.close(t, f'Done {res.get("d", on.isoformat())}: {st}.')
        elif t['how'] == 'watch':
            v, ok = pick(t['watch']['file'], t['watch'].get('key'))
            if ok and holds(v, t['watch'].get('pass')):
                res = {'d': on.isoformat(), 'v': 's', 'by': 'watch'}
                runs[t['key']] = res
                row['result'] = res
                st = 'done' if t.get('kind') == 'data' else 'shipped'
            else:
                st = 'watching' if on >= d else 'waiting'
        elif on < d:
            st = 'waiting'
        elif not ready(t):
            st = 'data'
        elif t['how'] == 'auto':
            st = 'due'
            if not DRY and issues is not None:
                print(f'retest {t["key"]}: running', flush=True)
                ok = run_cmds(t.get('run'))
                v, have = pick(t['verdict']['file'], t['verdict'].get('key')) if ok else (None, False)
                passed = have and holds(v, t['verdict']['pass'])
                if ok:
                    shipped = passed and run_cmds(t.get('ship'))
                    res = {'d': on.isoformat(), 'v': 's' if shipped else 'f', 'by': 'auto'}
                    for k in ('e', 'tt'):
                        x, h = pick(t['verdict']['file'], t['verdict'].get(k)) if t['verdict'].get(k) else (None, False)
                        if h and x is not None:
                            res[k] = x
                    runs[t['key']] = res
                    row['result'] = res
                    st = VNAME[res['v']]
                else:
                    st = 'due'
                    issues.ensure(t, d)          # a run that breaks becomes a hand job
        else:
            st = 'due'
            if issues is not None:
                n = issues.ensure(t, d)
                if n:
                    row['issue'] = n
        row['state'] = st
        rows.append(row)
    rows.sort(key=lambda r: (r['due'], r['t']))
    count = {}
    for r in rows:
        count[r['state']] = count.get(r['state'], 0) + 1
    nxt = [r['key'] for r in rows if r['state'] in ('waiting', 'data', 'due', 'watching')]
    return {'asof': on.isoformat(), 'n': len(rows), 'count': count, 'next': nxt[:6], 'rows': rows, 'runs': runs}


def write(state):
    old = load(OUT, {}) or {}
    same = {k: v for k, v in old.items() if k != 'asof'} == {k: v for k, v in state.items() if k != 'asof'}
    if same:
        print('retests: no change')
        return False
    with open(OUT, 'w') as f:
        json.dump(state, f, ensure_ascii=False, indent=0, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    return True


def _test():
    reg = {'tests': [
        {'key': 'a', 't': 'A', 'how': 'hand', 'due': '2027-01-01'},
        {'key': 'b', 't': 'B', 'how': 'hand', 'after': 'cfb:champ:2027', 'lag': 14, 'due': '2030-01-01'},
        {'key': 'c', 't': 'C', 'how': 'hand', 'due': '2026-01-01', 'result': {'d': '2026-02-01', 'v': 'f'}},
        {'key': 'd', 't': 'D', 'how': 'hand', 'due': '2026-01-01', 'ready': {'file': 'data/retests.json', 'key': 'tests', 'pass': 'len:100000'}},
        {'key': 'e', 't': 'E', 'how': 'watch', 'due': '2026-01-01', 'watch': {'file': 'data/retests.json', 'key': 'rule', 'pass': 'nonempty'}},
    ]}
    s = check(reg, {}, dt.date(2026, 12, 1))
    st = {r['key']: r for r in s['rows']}
    assert st['a']['state'] == 'waiting' and st['c']['state'] == 'failed', st
    assert st['b']['due'] == '2027-02-08', st['b']            # CFP final Jan 25 2027 + 14
    assert st['d']['state'] == 'data' and st['e']['state'] == 'shipped' and s['runs']['e']['by'] == 'watch'
    assert {r['key']: r for r in check(reg, {}, dt.date(2027, 1, 2))['rows']}['a']['state'] == 'due'
    assert holds([], 'empty') and not holds(None, 'empty') and holds(2027, 'ge:2027') and holds([1, 2], 'len:2') and holds('pass', 'eq:pass')
    real = load(REG)
    keys = [t['key'] for t in real['tests']]
    assert len(keys) == len(set(keys)), 'duplicate keys'
    cal = calendar()
    for t in real['tests']:
        assert t['how'] in ('hand', 'watch', 'auto') and t.get('t') and t.get('sp'), t
        assert t['how'] != 'watch' or t.get('watch'), t
        assert t['how'] != 'auto' or (t.get('run') and t.get('verdict')), t
        resolve(t, cal)                                            # every date resolves
    print(f'retests: tests pass ({len(keys)} in the registry)')


def main():
    if '--test' in sys.argv:
        _test()
        return
    reg = load(REG)
    on = today()
    if '--on' in sys.argv:
        on = dt.date.fromisoformat(sys.argv[sys.argv.index('--on') + 1])
    if '--due' in sys.argv:
        s = check(reg, load(OUT, {}), on)
        due = [r for r in s['rows'] if r['state'] in ('due', 'data') and r['how'] == 'hand']
        for r in due:
            print(f'{r["due"]}  {r["key"]:<22} {r["state"]:<5} {r["t"]}')
        print(f'{len(due)} hand retests due')
        return
    issues = None if DRY else Issues()
    s = check(reg, load(OUT, {}), on, issues)
    for r in s['rows']:
        if r['state'] in ('due', 'data') or (r.get('result') or {}).get('d') == on.isoformat():
            print(f'{r["due"]}  {r["key"]:<22} {r["state"]}')
    print('retests:', ', '.join(f'{v} {k}' for k, v in sorted(s['count'].items())))
    if not DRY:
        write(s)


if __name__ == '__main__':
    main()
