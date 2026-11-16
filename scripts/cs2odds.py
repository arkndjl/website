#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Counter-Strike bookmaker closes from CS2Odds (https://cs2odds.com/results) and the market rating built on them.

    python3 scripts/cs2odds.py            # pull the last 3 days' result pages (all days from Sep 19 2026 when empty)

Each finished series with a close from a book seen within 2 h of the start goes to scripts/data/cs2odds_closes.json.gz
as [day, team A key, team B key, consensus de-vigged logit for A, books]. rating() fits a ridge Bradley-Terry on those
closes (half-life 30 days, ridge 1): the market rating term in the series chance (research/cs2_market_prereg.md H2,
scripts/cs2_market_research.py). Page reads: one per UTC day, robots.txt allows all.
"""
import datetime as dt
import gzip
import json
import math
import re
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cs2_data import key  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "scripts" / "data" / "cs2odds_closes.json.gz"
SITE = "https://cs2odds.com"
UA = "Mozilla/5.0 (compatible; arkndjl-research)"
FIRST = "2026-09-19"
FRESH, HL, RIDGE = 2.0, 30.0, 1.0


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def page_matches(s):
    """Series objects from one results page (the page's Next.js payload)."""
    dec, out = json.JSONDecoder(), []
    raw = "".join(json.loads('"' + c + '"') for c in re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', s, re.S))
    for m in re.finditer(r'\{"match":\{"id"', raw):
        try:
            out.append(dec.raw_decode(raw, m.start() + 9)[0])
        except ValueError:
            continue
    return out


def ts(x):
    return dt.datetime.fromisoformat(x.replace("Z", "+00:00"))


def lg(p):
    p = min(max(p, .005), .995)
    return math.log(p / (1 - p))


def close_row(m):
    """-> [day, key A, key B, consensus logit A, books] or None (unfinished, or no book seen within FRESH h)."""
    res = m.get("result") or {}
    if m.get("status") not in ("completed", "completed_provisional") or res.get("winnerSide") not in ("team_a", "team_b"):
        return None
    c = m.get("closing") or {}
    qa, qb = ({q["bookmakerSlug"]: q for q in (c.get(s) or {}).get("quotes", []) if q.get("closeStatus") == "captured"}
              for s in ("teamA", "teamB"))
    st, v = ts(m["scheduledStartAt"]), []
    for bk in set(qa) & set(qb):
        if (st - ts(qa[bk]["observedAt"])).total_seconds() / 3600 <= FRESH:
            a, b = 1 / qa[bk]["decimalOdds"], 1 / qb[bk]["decimalOdds"]
            v.append(lg(a / (a + b)))
    if not v:
        return None
    return [m["scheduledStartAt"][:10], key(m["teamA"]["name"]), key(m["teamB"]["name"]), round(float(np.mean(v)), 4),
            len(v), m["id"]]


def load():
    return json.loads(gzip.decompress(STORE.read_bytes())) if STORE.exists() else {"rows": []}


def pull(days=3):
    S = load()
    rows = {r[5]: r for r in S["rows"]}
    today = dt.date.today()
    have = {r[0] for r in S["rows"]}
    want = [(today - dt.timedelta(days=i)).isoformat() for i in range(days + 1)]
    if not have:
        d0 = dt.date.fromisoformat(FIRST)
        want = [(d0 + dt.timedelta(days=i)).isoformat() for i in range((today - d0).days + 1)]
    for d in sorted(set(want)):
        try:
            for m in page_matches(get(f"{SITE}/results/{d}")):
                r = close_row(m)
                if r:
                    rows[r[5]] = r
        except Exception as ex:  # noqa: BLE001
            print("cs2odds", d, "skipped:", ex)
        time.sleep(1.5)
    S["rows"] = sorted(rows.values())
    STORE.write_bytes(gzip.compress(json.dumps(S, separators=(",", ":")).encode()))
    print(f"cs2odds: {len(S['rows'])} closes, last {S['rows'][-1][0] if S['rows'] else '-'}")


def rating(rows=None, asof=None):
    """team key -> market rating (logit vs the field), ridge Bradley-Terry on closes before asof (default: all)."""
    rows = load()["rows"] if rows is None else rows
    if asof:
        rows = [r for r in rows if r[0] < asof]
    if not rows:
        return {}
    teams = sorted({r[1] for r in rows} | {r[2] for r in rows})
    ix = {k: j for j, k in enumerate(teams)}
    X = np.zeros((len(rows), len(teams)))
    for j, r in enumerate(rows):
        X[j, ix[r[1]]], X[j, ix[r[2]]] = 1, -1
    y = np.array([r[3] for r in rows])
    ref = dt.date.fromisoformat(asof).toordinal() if asof else max(dt.date.fromisoformat(r[0]).toordinal() for r in rows) + 1
    w = 0.5 ** ((ref - np.array([dt.date.fromisoformat(r[0]).toordinal() for r in rows])) / HL)
    rt = np.linalg.solve(X.T @ (X * w[:, None]) + RIDGE * np.eye(len(teams)), X.T @ (w * y))
    return {k: float(rt[ix[k]]) for k in teams}


if __name__ == "__main__":
    pull()
