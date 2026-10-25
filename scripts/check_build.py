"""The build gate: what breaks a Cloudflare deploy, checked before a commit lands.

    python3 scripts/check_build.py            # strict JSON + file sizes (seconds; every bot workflow runs it before committing)
    python3 scripts/check_build.py --hugo     # also a full Hugo build into a temp folder (the build-gate workflow, PRs and main)

- every .json under data/ and static/ parses as strict JSON: a bare NaN or Infinity (Python's json.dump default) fails
  Hugo's data loader and every build with it (Oct 21, PR #315)
- no file under static/ over Cloudflare Pages' 25 MiB per-file limit (warning from 23 MiB: cfb-all.json lives near it)
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
    e2, warns = check_sizes(); errs += e2
    if '--hugo' in sys.argv[1:] and not errs: errs += check_hugo()
    for w in warns: print('warning:', w)
    for e in errs: print('FAIL:', e)
    print(f'build gate: {n} JSON files, {"FAILED" if errs else "ok"}')
    sys.exit(1 if errs else 0)
