#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Wait until arkndjl.net serves a build of origin/main (or a later commit).

The Hugo build writes the commit it built to https://arkndjl.net/build.json (layouts/index.buildinfo.json).
Run this after a merge:  python3 scripts/check_live.py [--sha SHA] [--timeout 1200] [--interval 30] [--site URL]
Exit 0 once live serves SHA or a descendant of it, 1 on timeout. Ancestry comes from the local git history when the clone
is complete, else from GitHub's compare API (GITHUB_TOKEN if set), so a one-commit checkout is enough.
"""
import argparse, json, os, subprocess, sys, time, urllib.request

def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True)

def live(site):
    req = urllib.request.Request(f"{site.rstrip('/')}/build.json?t={int(time.time())}", headers={"Cache-Control": "no-cache", "User-Agent": "check-live"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode()), None
    except Exception as e:  # 404 before the first stamped build, network blips
        return None, str(e)

def shallow():
    return git("rev-parse", "--is-shallow-repository").stdout.strip() == "true"

def api_ahead(target, got):
    """Is `got` at or ahead of `target` on GitHub (compare API)? None when the API cannot say. Lets the deploy check run on
    a one-commit sparse checkout: the full history is 3 GB and took the workflow 4 minutes to clone on every push."""
    repo = os.environ.get("GITHUB_REPOSITORY") or "arkndjl/website"
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/compare/{target}...{got}",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "check-live"})
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok: req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode()).get("status") in ("ahead", "identical")
    except Exception as e:
        print(f"compare API failed for {target[:9]}...{got[:9]}: {e}", flush=True)
        return None

def landed(target, got):
    if got == target or got.startswith(target) or target.startswith(got) and len(got) >= 7:
        return True
    if not got or got == "unknown":
        return False
    if git("cat-file", "-e", got + "^{commit}").returncode != 0:
        git("fetch", "-q", "origin", "main")  # the live build is newer than our clone
    rc = git("merge-base", "--is-ancestor", target, got).returncode
    if rc == 0:
        return True
    if rc == 1 and not shallow():
        return False
    return bool(api_ahead(target, got))  # a shallow clone cannot tell (history cut, or the commit is missing): ask GitHub

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", help="commit to wait for (default: origin/main)")
    ap.add_argument("--site", default="https://arkndjl.net")
    ap.add_argument("--timeout", type=int, default=1200)
    ap.add_argument("--interval", type=int, default=30)
    a = ap.parse_args()
    if not a.sha:
        git("fetch", "-q", "origin", "main")
        a.sha = git("rev-parse", "origin/main").stdout.strip()
    git("fetch", "-q", "origin", "main")
    t0 = time.time()
    print(f"waiting for {a.site} to serve {a.sha[:9]} (timeout {a.timeout}s)", flush=True)
    last = None
    while True:
        b, err = live(a.site)
        got = (b or {}).get("sha", "")
        if b and landed(a.sha, got):
            print(f"LIVE after {int(time.time()-t0)}s: build {got[:9]} built {b.get('built')} (hugo {b.get('hugo')})")
            return 0
        state = f"serving {got[:9] or '?'} built {b.get('built')}" if b else f"no stamp ({err})"
        if state != last:
            print(f"[{int(time.time()-t0)}s] {state}", flush=True)
            last = state
        if time.time() - t0 + a.interval > a.timeout:
            print(f"NOT LIVE after {a.timeout}s: wanted {a.sha[:9]}, site {state}. Read the Cloudflare build log (Workers & Pages > website > Builds).")
            return 1
        time.sleep(a.interval)

sys.exit(main())
