#!/usr/bin/env python3
"""Wait until arkndjl.net serves a build of origin/main (or a later commit).

The Hugo build writes the commit it built to https://arkndjl.net/build.json (layouts/index.buildinfo.json).
Run this after a merge:  python3 scripts/check_live.py [--sha SHA] [--timeout 1200] [--interval 30] [--site URL]
Exit 0 once live serves SHA or a descendant of it, 1 on timeout. Needs the repo's git history (git fetch origin main).
"""
import argparse, json, subprocess, sys, time, urllib.request

def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True)

def live(site):
    req = urllib.request.Request(f"{site.rstrip('/')}/build.json?t={int(time.time())}", headers={"Cache-Control": "no-cache", "User-Agent": "check-live"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode()), None
    except Exception as e:  # 404 before the first stamped build, network blips
        return None, str(e)

def landed(target, got):
    if got == target:
        return True
    if not got or got == "unknown":
        return False
    return git("merge-base", "--is-ancestor", target, got).returncode == 0

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
