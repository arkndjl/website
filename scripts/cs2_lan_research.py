#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""LAN vs online as a CS2 match-model term (research, Nov 2 2026). New information: bo3.gg tags every tournament
event_type lan / online (api.bo3.gg/api/v1/tournaments, 3.3k events; matches carry tournament_id). Roster continuity
already failed (data/cs2_fit.json), so this asks a different question: do some players/teams play to a different
level on LAN than their online-built ratings say (the classic "online warriors"), and do favourites hold up better on
LAN?
Terms on top of the shipped blend (player Elo gap x, VRS gap v, team map logit t; tiered top-50 / rest):
  lanx    lan x rating gap (favourites stronger on LAN)
  lanDev  on LAN series: mean over each five of the player's running LAN-minus-online Elo residual (s - e from the
          pre-series gap), shrunk by n_lan*n_on/(n_lan+n_on) / (that + 20); A minus B. 0 online.
  onDev   the same, on online series (the negative of LAN skill: online specialists).
Only series that join a bo3 match have a known setting (else 0). Tune: fit Aug 2024 - Jan 2025, score Feb - Jun
2025; held out: fit Aug 2024 - Jun 2025 (the house tune window), score Jul 2025 on. Paired log loss, t clustered by day.
  python3 scripts/cs2_lan_research.py [--pull]   (needs scripts/.cache/cs/vrs, the Valve repo clone)
Result (Nov 2 2026, 12.3k of 76.9k bo3 matches LAN): FAILED. lanDev tune t -1.32, held +1.99 (worse); lanx -0.74 / +1.20;
onDev ~0 both. LAN-only rows: -11 x1e-4 tune (599 series) but +17 held (4,258). Do not retest without per-map stats.
Writes data/cs2_lan_research.json."""
import json
import math
import sys
import urllib.parse
import urllib.request
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_model as M  # noqa: E402
import cs2_bo3  # noqa: E402
import harness as HH  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAN = ROOT / "scripts" / ".cache" / "cs" / "bo3_lan.json"
OUT = ROOT / "data" / "cs2_lan_research.json"


def get(path):
    url = cs2_bo3.API + urllib.parse.quote(path, safe="/?&=,%")
    for t in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": M.UA}), timeout=60) as r:
                return json.load(r)
        except Exception:  # noqa: BLE001
            time.sleep(2 ** t)
    return {"results": []}


def pull():
    q = "matches?page[offset]={}&page[limit]=100&sort=start_date&filter[matches.status][in]=finished"
    n = get(q.format(0))["total"]["count"]
    with ThreadPoolExecutor(4) as ex:
        pages = list(ex.map(lambda o: get(q.format(o))["results"], range(0, n + 100, 100)))
    m2t = {r["id"]: r["tournament_id"] for p in pages for r in p}
    tq = "tournaments?page[offset]={}&page[limit]=100&sort=start_date"
    n = get(tq.format(0))["total"]["count"]
    with ThreadPoolExecutor(4) as ex:
        tp = list(ex.map(lambda o: get(tq.format(o))["results"], range(0, n + 100, 100)))
    tt = {r["id"]: [r.get("event_type"), r.get("tier"), r.get("name")] for p in tp for r in p}
    LAN.parent.mkdir(parents=True, exist_ok=True)
    LAN.write_text(json.dumps({"m2t": m2t, "t": tt}))


def main():
    if "--pull" in sys.argv or not LAN.exists():
        pull()
    L = json.loads(LAN.read_text())
    m2t, tt = L["m2t"], L["t"]
    H = json.load(M.gzip.open(M.HIST))
    series = [r for r in H["series"] if r[6] == "vrs"]
    vrs = M.Vrs(H["vrs"])
    bo3 = cs2_bo3.Bo3()
    rows, _ = M.replay(series, vrs, dict(M.DEF), bo3=bo3)
    lanof = {}
    for i, m in bo3.joined.items():
        t = m2t.get(str(m[0]))
        et = (tt.get(str(t)) or [None])[0] if t is not None else None
        lanof[i] = 1.0 if et == "lan" else 0.0 if et == "online" else None
    # running player residuals by setting (pre-series: features read before the update)
    res = defaultdict(lambda: [0.0, 0, 0.0, 0])

    def dev(q, k=20):
        a = res[q]
        if a[1] == 0 or a[3] == 0:
            return 0.0
        ne = a[1] * a[3] / (a[1] + a[3])
        return (a[0] / a[1] - a[2] / a[3]) * ne / (ne + k)
    for r in rows:
        lan = lanof.get(r["i"])
        ra, rb = r["r"][4] or [], r["r"][5] or []
        da = np.mean([dev(q) for q in ra]) if ra else 0.0
        db = np.mean([dev(q) for q in rb]) if rb else 0.0
        r["lan"] = lan
        r["lanx"] = r["x"] * (lan or 0.0)
        r["lanDev"] = (da - db) if lan == 1.0 else 0.0
        r["onDev"] = (da - db) if lan == 0.0 else 0.0
        if lan is None:
            continue
        e = 1 / (1 + 10 ** (-r["x"]))
        for ros, sg in ((ra, 1), (rb, -1)):
            for q in ros:
                a = res[q]
                if lan:
                    a[0] += sg * (r["s"] - e); a[1] += 1
                else:
                    a[2] += sg * (r["s"] - e); a[3] += 1

    def cols(rs, extra):
        base = [[r["x"], r["v"], r.get("t", 0.0)] + [r[k] for k in extra] for r in rs]
        return np.array(base)

    def tiered(train, test, extra):
        out = np.zeros(len(test))
        for tier in (True, False):
            tr = [r for r in train if r["top"] == tier]
            idx = [i for i, r in enumerate(test) if r["top"] == tier]
            w = M.fitlog(cols(tr, extra), np.array([r["s"] for r in tr]))
            if idx:
                out[idx] = 1 / (1 + np.exp(-cols([test[i] for i in idx], extra) @ w))
        return out

    win = lambda w: [r for r in rows if w[0] <= r["d"] <= w[1]]  # noqa: E731
    splits = {"tune": (("2024-08-07", "2025-01-31"), ("2025-02-01", "2025-06-30")), "held": (M.TUNE, M.HELD)}
    out = {"note": __doc__.split("\n")[0], "lanShareJoined": round(float(np.mean([v for v in lanof.values() if v is not None])), 3)}
    for nm, extra in (("lanx", ["lanx"]), ("lanDev", ["lanDev"]), ("onDev", ["onDev"]), ("lanDev+onDev", ["lanDev", "onDev"])):
        out[nm] = {}
        for sp, (fw, tw) in splits.items():
            tr, te = win(fw), win(tw)
            s = np.array([r["s"] for r in te])
            b = M.ll(tiered(tr, te, []), s)
            n = M.ll(tiered(tr, te, extra), s)
            lanm = np.array([r["lan"] == 1.0 for r in te])
            rr = HH.paired(n, b, cluster=np.array([r["d"] for r in te]))
            out[nm][sp] = {"t": round(rr["t"], 2), "dLL_e4": round(float(rr["d"]) * 1e4, 2), "n": rr["n"],
                           "lanOnly_dLL_e4": round(float((n - b)[lanm].mean()) * 1e4, 2), "nLan": int(lanm.sum())}
        print(nm, out[nm], flush=True)
    OUT.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
