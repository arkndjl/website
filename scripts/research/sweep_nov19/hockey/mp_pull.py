# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""MoneyPuck pregame prediction files for lined games, one polite GET a game.

usage: mp_pull.py <out_dir>   (resumable; writes <id>.csv and index.jsonl with Last-Modified)
Seasons S 2020-2026 only (2026-27 is never requested).
"""
import gzip, json, os, sys, time, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
UA = "arkndjl.net-arkboard/1.0 (https://arkndjl.net)"


def main(out):
    os.makedirs(out, exist_ok=True)
    rows = json.load(gzip.open(os.path.join(ROOT, "scripts/data/games_wf/nhl.json.gz")))
    ids = [g["id"] for g in rows if 2020 <= g["S"] <= 2026 and g.get("c")]
    # interleave seasons so a partial pull still covers every season evenly
    by = {}
    for g in rows:
        if 2020 <= g["S"] <= 2026 and g.get("c"):
            by.setdefault(g["S"], []).append(g["id"])
    order = []
    i = 0
    while any(by.values()):
        for s in sorted(by):
            if by[s]:
                # deterministic spread inside a season
                order.append(by[s].pop((i * 7919) % len(by[s])))
        i += 1
    assert len(order) == len(ids)
    idx = os.path.join(out, "index.jsonl")
    done = set()
    if os.path.exists(idx):
        for ln in open(idx):
            done.add(json.loads(ln)["id"])
    f = open(idx, "a")
    for n, gid in enumerate(order):
        if gid in done:
            continue
        url = "https://moneypuck.com/moneypuck/predictions/%d.csv" % gid
        t0 = time.time()
        rec = {"id": gid}
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30)
            body = r.read()
            rec["code"] = r.status
            rec["lm"] = r.headers.get("Last-Modified")
            open(os.path.join(out, "%d.csv" % gid), "wb").write(body)
        except urllib.error.HTTPError as e:
            rec["code"] = e.code
        except Exception as e:
            rec["code"] = 0
            rec["err"] = str(e)[:80]
            time.sleep(10)
        if rec["code"] != 0:
            f.write(json.dumps(rec) + "\n")
            f.flush()
        time.sleep(max(0.0, 1.0 - (time.time() - t0)) + 0.02)


if __name__ == "__main__":
    main(sys.argv[1])
