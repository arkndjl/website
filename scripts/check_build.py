# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The build gate: what breaks a Cloudflare deploy, checked before a commit lands.

    python3 scripts/check_build.py            # strict JSON + file sizes (seconds; every bot workflow runs it before committing)
    python3 scripts/check_build.py --hugo     # also a full Hugo build into a temp folder (the build-gate workflow, PRs and main)

- every .json under data/ and static/ parses as strict JSON: a bare NaN or Infinity (Python's json.dump default) fails
  Hugo's data loader and every build with it (Oct 21)
- no file under static/ over Cloudflare Pages' 25 MiB per-file limit (warning from 23 MiB)
- static/data/cfb-all.json and cfb-detail.json carry the same dk (the board split in two, scripts/cfb_all.mjs): a
  mismatched pair leaves every scouting report off the board
- static/data/cbb-past.json carries fvg (the grade; fv and fvx at the mean outcome) and data/cbb_fit.json carries
  calibMean: both come from scripts/fv_dist.py past_at_mean, which cbb_fit.py runs after it rewrites the past boards
- data/fv_scale.json K and T match a refit from the boards' tables (scripts/fv_scale.py compute) within 0.25; hockey's
  gap is a warning until its scale is refit (`python3 scripts/fv_scale.py --fit`)
- with --hugo: data/team_alias.json (the browser's team short forms, layouts/partials/namekey.html) matches
  scripts/names.py TEAM_ALIAS; `python3 scripts/names.py --teams` rewrites it
Local hook: git config core.hooksPath .githooks (runs the fast checks on each commit). Stdlib only."""
import json, os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMIT, WARN = 25 * 2 ** 20, 23 * 2 ** 20


def bad_const(c):
    raise ValueError(f'bare {c}')


def check_json():
    errs, n = [], 0
    for top in ('data', 'static'):
        for d, _, fs in os.walk(os.path.join(ROOT, top)):
            for f in fs:
                if not f.endswith('.json'): continue
                p = os.path.join(d, f); n += 1
                try:
                    with open(p, encoding='utf-8') as fh: json.load(fh, parse_constant=bad_const)
                except Exception as e:
                    errs.append(f'{os.path.relpath(p, ROOT)}: {str(e)[:160]}')
    return errs, n


def check_sizes():
    errs, warns = [], []
    for d, _, fs in os.walk(os.path.join(ROOT, 'static')):
        for f in fs:
            p = os.path.join(d, f); s = os.path.getsize(p); r = os.path.relpath(p, ROOT)
            if s > LIMIT: errs.append(f'{r}: {s / 2 ** 20:.1f} MiB, over the 25 MiB Cloudflare limit')
            elif s > WARN: warns.append(f'{r}: {s / 2 ** 20:.1f} MiB (limit 25 MiB)')
    return errs, warns


def check_pairs():
    import re
    sd = os.path.join(ROOT, 'static', 'data')
    dk = lambda f: (re.search(r'"dk":"(\w+)"', open(os.path.join(sd, f), encoding='utf-8').read(400)) or [None, None])[1]
    if not os.path.exists(os.path.join(sd, 'cfb-detail.json')): return []
    a, b = dk('cfb-all.json'), dk('cfb-detail.json')
    return [] if a and a == b else [f'static/data/cfb-all.json dk {a} vs cfb-detail.json dk {b}: write both with scripts/cfb_all.mjs']


def check_cbb_mean():
    errs = []
    try:
        with open(os.path.join(ROOT, 'static', 'data', 'cbb-past.json'), encoding='utf-8') as fh: cols = json.load(fh)['cols']
        if 'fvg' not in cols: errs.append('static/data/cbb-past.json has no fvg (past boards on the grade): run python3 scripts/fv_dist.py --past')
    except (OSError, ValueError, KeyError):
        pass
    try:
        with open(os.path.join(ROOT, 'data', 'cbb_fit.json'), encoding='utf-8') as fh: F = json.load(fh)
        if not F.get('calibMean'): errs.append('data/cbb_fit.json has no calibMean: run python3 scripts/fv_dist.py --past')
    except (OSError, ValueError):
        pass
    return errs


def check_teams():
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    import names
    try:
        built = json.load(open(names.TEAM_FILE, encoding='utf-8'))
    except (OSError, ValueError):
        built = None
    return [] if built == names.TEAM_ALIAS else ['data/team_alias.json is behind scripts/names.py TEAM_ALIAS: run python3 scripts/names.py --teams']


def check_fv_scale(tol=0.25, warn_only=('hockey',)):
    """stored K/T against a fresh fit from the tables on disk; returns (errors, warnings)"""
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    try:
        import fv_scale
        fresh = fv_scale.compute()
        stored = json.load(open(os.path.join(ROOT, 'data', 'fv_scale.json')))['boards']
    except Exception as e:
        return [], [f'fv_scale check skipped: {type(e).__name__}: {e}']
    errs, warns = [], []
    for b, f in fresh.items():
        for k in ('K', 'T'):
            d = abs(f[k] - stored[b][k])
            if d > tol:
                (warns if b in warn_only else errs).append(
                    f'data/fv_scale.json {b} {k} {stored[b][k]} but the tables fit {f[k]}: rerun scripts/fv_scale.py --fit --restate')
    return errs, warns


def check_hugo():
    hugo = shutil.which('hugo') or os.environ.get('HUGO')
    if not hugo: return ['hugo not found (set HUGO or put it on PATH)']
    out = tempfile.mkdtemp(prefix='gate-')
    try:
        r = subprocess.run([hugo, '--quiet', '-d', out], cwd=ROOT, capture_output=True, text=True)
        return [] if r.returncode == 0 else ['hugo build failed:\n' + (r.stderr or r.stdout)[-3000:]]
    finally:
        shutil.rmtree(out, ignore_errors=True)


if __name__ == '__main__':
    errs, n = check_json()
    e2, warns = check_sizes(); errs += e2 + check_pairs() + check_cbb_mean()
    e3, w3 = check_fv_scale(); errs += e3; warns += w3
    if '--hugo' in sys.argv[1:]: errs += check_teams()
    if '--hugo' in sys.argv[1:] and not errs: errs += check_hugo()
    for w in warns: print('warning:', w)
    for e in errs: print('FAIL:', e)
    print(f'build gate: {n} JSON files, {"FAILED" if errs else "ok"}')
    sys.exit(1 if errs else 0)
