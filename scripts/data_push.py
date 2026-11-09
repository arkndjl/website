#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Commit a bot workflow's data files and push them to main without losing what another run pushed meanwhile.

    python3 scripts/data_push.py -m "Update the NBA games (2026-11-05)" \
        --rebuild data/games_picks_nba.json --rebuild data/rule_monitor.json \
        --regen "python3 scripts/games_picks.py nba; python3 scripts/rule_monitor.py" -- <paths...>
    python3 scripts/data_push.py --test       # self-check on a throwaway remote

The sport builds, odds snap and picks refresh all write data/games_picks_<sport>.json, the odds archives
(scripts/data/odds/*.jsonl) and data/rule_monitor.json, and runs overlap. Before Nov 5 2026 a rejected push either
rebased with -X theirs (a line-level merge of JSON: the snap's hunks won and the build's new picks rows vanished) or
took this run's files whole on the new main (the build's copy, made from a checkout 20+ minutes old, dropped the picks
the snaps had flagged since). 5 races, 12 picks rows dropped Nov 1-4 (cbb 3, cfb 3, nba 6), each re-flagged later
with a new stamp.

A push is an atomic compare-and-swap on main, so on a rejection this rebuilds the commit on the new main:
- files this run changed and nobody else did since its checkout: taken whole from this run
- --rebuild files (the picks logs, the rule monitor, the paper book) that main changed meanwhile: left as main has
  them, then --regen reruns the step that writes them, which reads the newest committed log and appends to it
  (scripts/games_picks.py keeps every logged row), so both runs' rows stay. A failed regen keeps main's file.
- .jsonl archives: main's lines plus the lines this run appended, in time order when every row has a "t"
- files this run deleted: deleted
then commits (the build gate first) and pushes again, up to --tries times.
Stdlib only."""
import argparse
import fnmatch
import glob
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(*a, check=True, cwd=None):
    p = subprocess.run(['git', *a], cwd=cwd or ROOT, capture_output=True, text=True)
    if check and p.returncode:
        raise RuntimeError(f"git {' '.join(a)}: {p.stderr.strip()}")
    return p


def blob(rev, path, cwd=None):
    p = git('rev-parse', '-q', '--verify', f'{rev}:{path}', check=False, cwd=cwd)
    return p.stdout.strip() if p.returncode == 0 else None


def show(rev, path, cwd=None):
    p = git('show', f'{rev}:{path}', check=False, cwd=cwd)
    return p.stdout if p.returncode == 0 else ''


def stage(paths, cwd=None):
    """git add -A each path (a file, a folder or a glob: new, changed and deleted files) that exists or is tracked"""
    for p in paths:
        here = glob.glob(os.path.join(cwd or ROOT, p))
        if here or git('ls-files', '--', p, cwd=cwd).stdout.strip():
            git('add', '-A', '--', p, cwd=cwd)


def staged(cwd=None, paths=()):
    return git('diff', '--cached', '--name-only', '--', *paths, cwd=cwd).stdout.split()


def merge_jsonl(theirs, base, ours):
    """main's lines, then the lines this run appended (ours minus base) that main lacks; sorted by "t" when every row
    has one and main's file already was (the odds archives: a game's close is its last row before the start)"""
    have = set(theirs.splitlines())
    left = {}
    for ln in base.splitlines():
        left[ln] = left.get(ln, 0) + 1
    add = []
    for ln in ours.splitlines():
        if left.get(ln):
            left[ln] -= 1
        elif ln.strip() and ln not in have:
            add.append(ln)
            have.add(ln)
    lines = [ln for ln in theirs.splitlines() if ln.strip()] + add
    try:
        ts = [json.loads(ln)['t'] for ln in lines]
        main_ts = ts[:len(lines) - len(add)]
        if all(isinstance(t, str) for t in ts) and all(a <= b for a, b in zip(main_ts, main_ts[1:])):
            lines = [ln for _, ln in sorted(zip(ts, lines), key=lambda x: x[0])]
    except (ValueError, KeyError, TypeError):
        pass
    return '\n'.join(lines) + '\n' if lines else ''


def check_build(cwd):
    gate = os.path.join(cwd, 'scripts', 'check_build.py')
    if not os.path.exists(gate):
        return True
    return subprocess.run([sys.executable, gate], cwd=cwd).returncode == 0


def commit(msg, site, cwd):
    skip = site and not staged(cwd, site)
    git('commit', '-q', '-m', msg + (' [skip ci]' if skip else ''), cwd=cwd)


def run(a, cwd=None):
    cwd = cwd or ROOT
    if not git('config', 'user.name', check=False, cwd=cwd).stdout.strip():
        git('config', 'user.name', 'arkboard-bot', cwd=cwd)
        git('config', 'user.email', 'actions@users.noreply.github.com', cwd=cwd)
    stage(a.paths, cwd)
    if not staged(cwd):
        print('no changes')
        return 0
    if not check_build(cwd):
        return 1
    base = git('rev-parse', 'HEAD', cwd=cwd).stdout.strip()
    commit(a.message, a.site, cwd)
    data = git('rev-parse', 'HEAD', cwd=cwd).stdout.strip()
    diff = git('diff', '--name-status', '--no-renames', base, data, cwd=cwd).stdout.splitlines()
    changed = [ln.split('\t', 1)[1] for ln in diff if not ln.startswith('D')]
    gone = [ln.split('\t', 1)[1] for ln in diff if ln.startswith('D')]
    rebuild = lambda f: any(fnmatch.fnmatch(f, g) for g in a.rebuild)
    for i in range(1, a.tries + 1):
        p = git('push', 'origin', f'HEAD:refs/heads/{a.branch}', check=False, cwd=cwd)
        if p.returncode == 0:
            print(f'pushed (try {i})')
            return 0
        why = [ln for ln in p.stderr.splitlines() if 'rejected' in ln or 'error' in ln] or p.stderr.strip().splitlines()[-1:]
        print(f'push rejected (try {i}):', why[0].strip() if why else '')
        if i == a.tries:
            break
        time.sleep(a.wait * i + random.uniform(0, a.wait))
        git('fetch', '-q', 'origin', a.branch, cwd=cwd)
        main = git('rev-parse', 'FETCH_HEAD', cwd=cwd).stdout.strip()
        git('reset', '-q', '--hard', main, cwd=cwd)
        regen, kept, merged = False, [], []
        for f in changed:
            moved = blob(main, f, cwd) != blob(base, f, cwd)
            if moved and rebuild(f):
                regen = True
                kept.append(f)
            elif moved and f.endswith('.jsonl') and blob(main, f, cwd):
                with open(os.path.join(cwd, f), 'w') as fh:
                    fh.write(merge_jsonl(show(main, f, cwd), show(base, f, cwd), show(data, f, cwd)))
                merged.append(f)
            else:
                git('checkout', data, '--', f, cwd=cwd)
        if gone:
            git('rm', '-q', '--ignore-unmatch', '--', *gone, cwd=cwd)
        if merged:
            print('  archives merged with main:', ' '.join(merged))
        if regen:
            print('  main changed', ' '.join(kept), '- rebuilding them on it')
            if a.regen and subprocess.run(a.regen, shell=True, cwd=cwd).returncode:
                print('  the rebuild failed; main\'s copies kept')
        stage(a.paths, cwd)
        if not staged(cwd):
            print('no changes on the new main')
            return 0
        if not check_build(cwd):
            return 1
        commit(a.message, a.site, cwd)
    print('push failed')
    return 1


def parse(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('-m', '--message', required=True)
    ap.add_argument('--rebuild', action='extend', nargs='+', default=[], help='glob: a file rebuilt on the new main by --regen, not copied')
    ap.add_argument('--regen', default='', help='shell command that rewrites the --rebuild files from the checkout')
    ap.add_argument('--site', action='extend', nargs='+', default=[], help='path on the site; "[skip ci]" when none of them changed')
    ap.add_argument('--branch', default=os.environ.get('GITHUB_REF_NAME') or 'main')
    ap.add_argument('--tries', type=int, default=6)
    ap.add_argument('--wait', type=float, default=5.0)
    ap.add_argument('paths', nargs='*')
    return ap.parse_args(argv)


def test():
    """two runs from the same checkout: B pushes first, A's push is rejected and rebuilt on B's commit"""
    tmp = tempfile.mkdtemp()
    try:
        env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t')
        os.environ.update(env)
        remote, a, b = (os.path.join(tmp, x) for x in ('remote.git', 'a', 'b'))
        git('init', '-q', '--bare', '-b', 'main', remote, cwd=tmp)
        git('clone', '-q', remote, a, cwd=tmp)
        os.makedirs(os.path.join(a, 'data'))
        os.makedirs(os.path.join(a, 'arch'))
        picks = os.path.join('data', 'picks.json')
        arch = os.path.join('arch', 'odds.jsonl')
        with open(os.path.join(a, picks), 'w') as f:
            json.dump({'log': [{'id': 'g0'}]}, f)
        with open(os.path.join(a, arch), 'w') as f:
            f.write('{"t":"01"}\n')
        with open(os.path.join(a, 'data', 'old.json'), 'w') as f:
            f.write('{}')
        # the regen: append this run's pick to whatever log the checkout has (games_picks.py keeps the logged rows)
        with open(os.path.join(a, 'regen.py'), 'w') as f:
            f.write('import json,sys\nfn="data/picks.json"\nd=json.load(open(fn))\nids={e["id"] for e in d["log"]}\n'
                    'd["log"]+=[{"id":sys.argv[1]}] if sys.argv[1] not in ids else []\njson.dump(d,open(fn,"w"))\n')
        git('add', '-A', cwd=a)
        git('commit', '-q', '-m', 'init', cwd=a)
        git('push', '-q', 'origin', 'HEAD:main', cwd=a)
        git('clone', '-q', remote, b, cwd=tmp)
        for r, pid, t in ((a, 'gA', '03'), (b, 'gB', '02')):
            subprocess.run([sys.executable, 'regen.py', pid], cwd=r, check=True)
            with open(os.path.join(r, arch), 'a') as f:
                f.write('{"t":"%s"}\n' % t)
        with open(os.path.join(b, 'data', 'b_only.json'), 'w') as f:
            f.write('{"b":1}')
        os.makedirs(os.path.join(b, 'extra'))
        with open(os.path.join(b, 'extra', 'x-1.json'), 'w') as f:
            f.write('{"x":1}')
        with open(os.path.join(a, 'data', 'a_only.json'), 'w') as f:
            f.write('{"a":1}')
        os.remove(os.path.join(a, 'data', 'old.json'))
        paths = ['data', 'arch', 'data/missing-*.json', 'extra/x-*.json']
        assert run(parse(['-m', 'B', '--wait', '0', *paths]), cwd=b) == 0
        assert run(parse(['-m', 'A', '--wait', '0', '--rebuild', 'data/picks.json', '--regen',
                          f'{sys.executable} regen.py gA', *paths]), cwd=a) == 0
        top = git('rev-parse', 'origin/main', cwd=a).stdout.strip()
        log = [e['id'] for e in json.loads(show(top, picks, a))['log']]
        assert log == ['g0', 'gB', 'gA'], log
        assert show(top, arch, a) == '{"t":"01"}\n{"t":"02"}\n{"t":"03"}\n', show(top, arch, a)
        assert show(top, 'data/b_only.json', a) == '{"b":1}', 'B\'s file kept'
        assert show(top, 'extra/x-1.json', a) == '{"x":1}', 'a new file under a glob staged'
        assert show(top, 'data/a_only.json', a) == '{"a":1}', 'A\'s file taken whole'
        assert not blob(top, 'data/old.json', a), 'A\'s delete kept'
        merged = merge_jsonl('{"t":"1"}\n{"t":"3"}\n', '{"t":"1"}\n', '{"t":"1"}\n{"t":"2"}\n{"t":"3"}\n')
        assert merged == '{"t":"1"}\n{"t":"2"}\n{"t":"3"}\n', merged
        assert merge_jsonl('{"x":2}\n', '', '{"x":1}\n') == '{"x":2}\n{"x":1}\n'
        print('data_push: ok')
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['--test']:
        sys.exit(test())
    sys.exit(run(parse(sys.argv[1:])))
