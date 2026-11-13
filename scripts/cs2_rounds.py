#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Round-by-round results for the Counter-Strike section, from bo3.gg's public API (no key).

    python3 scripts/cs2_rounds.py            # maps finished since the last run (and any earlier gaps)
    python3 scripts/cs2_rounds.py --full     # every finished map since START (~80k calls, ~1 h at 8 threads)

Reads the map list from scripts/data/cs2_bo3.json.gz (scripts/cs2_bo3.py) and calls games/{id} once per finished map
(its game_rounds: side, pistol flag, equipment value, end reason, kills per team per round). Writes monthly shards
scripts/data/cs2_rounds/YYYY-MM.json.gz: {"cols", "games": {game id: [round rows]}, "none": {game id: first seen}}.
A round row is from the MAP WINNER's view (W = the team that won the map, L = the other), columns in COLS.
Maps bo3.gg has no rounds for (about a third of tier-c maps) go in "none" and are retried for 3 days.
"""
import datetime as dt
import gzip
import json
import sys
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_bo3  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "scripts" / "data" / "cs2_rounds"
START = "2024-01-01"
UA = "arkndjl.net-arkboard/1.0 (https://arkndjl.net)"
# W's side (0 T, 1 CT), W won the round, pistol round, equipment value W, L (after the buy), end reason (END index),
# W got the first kill, kills W, L, bomb planted, money spent W, L
COLS = ["ct", "win", "pistol", "eqW", "eqL", "end", "fk", "kW", "kL", "plant", "spW", "spL"]
END = ["TerroristsWin", "TargetBombed", "CTWin", "BombDefused", "TargetSaved"]


def get(path):
    for t in range(5):
        try:
            req = urllib.request.Request(cs2_bo3.API + path, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=60) as r:
                b = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    b = gzip.decompress(b)
                return json.loads(b)
        except Exception as e:  # noqa: BLE001
            if t == 4:
                print("bo3", path[:60], e, file=sys.stderr)
                return None
            time.sleep(2 ** t)


def rounds(x):
    """games/{id} -> round rows in order, or None when the map has no usable rounds."""
    wname = x.get("winner_clan_name")
    out = []
    for r in sorted(x.get("game_rounds") or [], key=lambda r: r.get("round_number") or 0):
        tc = r.get("game_round_team_clans") or []
        if len(tc) != 2:
            return None
        w = next((c for c in tc if c.get("clan_name") == wname), None)
        if w is None:
            return None
        lo = tc[1] if tc[0] is w else tc[0]
        if w.get("team_side") not in ("T", "CT") or w.get("win") not in (0, 1):
            return None
        end = END.index(r["end_reason"]) if r.get("end_reason") in END else 5
        out.append([int(w["team_side"] == "CT"), w["win"], int(bool(w.get("pistol_round"))),
                    w.get("equipment_value") or 0, lo.get("equipment_value") or 0, end, int(bool(w.get("first_kills"))),
                    w.get("kills") or 0, lo.get("kills") or 0,
                    int(bool((w.get("bomb_plants") or 0) + (lo.get("bomb_plants") or 0))),
                    w.get("money_spent") or 0, lo.get("money_spent") or 0])
    return out or None


def shard(month):
    try:
        with gzip.open(DIR / f"{month}.json.gz", "rt") as fh:
            return json.load(fh)
    except (FileNotFoundError, OSError, ValueError):
        return {"cols": COLS, "games": {}, "none": {}}


def save(month, d):
    DIR.mkdir(parents=True, exist_ok=True)
    d["games"] = dict(sorted(d["games"].items(), key=lambda kv: int(kv[0])))
    with gzip.open(DIR / f"{month}.json.gz", "wt") as fh:
        json.dump(d, fh, separators=(",", ":"))


def load():
    """-> {game id: round rows} over every shard."""
    out = {}
    for f in sorted(DIR.glob("*.json.gz")):
        with gzip.open(f, "rt") as fh:
            out.update({int(k): v for k, v in json.load(fh)["games"].items()})
    return out


def klass(eq):
    return 0 if eq < 5000 else 1 if eq < 20000 else 2


def cell(r, w):
    """A round's situation for one team (w: the map winner's view or the other's): pistol, or own buy x their buy."""
    if r[2]:
        return 9
    a, b = (r[3], r[4]) if w else (r[4], r[3])
    return klass(a) * 3 + klass(b)


def adjusted(bo3, cfg, rd=None):
    """-> {game id: the map winner's adjusted round share}. Each round counts as win minus (p - .5), p = the chance a
    team in that round's situation wins it, from every round in earlier months (expanding; maps before WF use the
    first half of 2024), by map shrunk toward all maps with SHR rounds.
      cfg["mode"] "side": situation = side;  "econ": side x buy matchup (pistol, eco / force / full each way)
      cfg["wp"], cfg["wm"]: weights of pistol rounds and of rounds where either team is short of a full buy (1 = even)
    """
    rd = rd if rd is not None else load()
    WF, SHR = "2024-07", 500.0
    econ = cfg.get("mode") == "econ"
    wp, wm = cfg.get("wp", 1.0), cfg.get("wm", 1.0)
    games = sorted((g for g in bo3["games"] if g[0] in rd), key=lambda g: g[2])
    cnt = defaultdict(lambda: [0.0, 0.0])   # (map, cell, side) -> [wins, n], rounds before the current month
    pend, cur, out = [], None, {}

    def kk(mp, r, w):
        side = r[0] if w else 1 - r[0]
        return (mp, cell(r, w) if econ else 0, side)

    def flush():
        for mp, rr in pend:
            for r in rr:
                for w in (1, 0):
                    win = r[1] if w else 1 - r[1]
                    for m_ in (mp, None):
                        c = cnt[kk(m_, r, w)]
                        c[0] += win
                        c[1] += 1
        pend.clear()

    def p_of(mp, r):
        a, b = cnt[kk(None, r, 1)], cnt[kk(mp, r, 1)]
        pa = a[0] / a[1] if a[1] else 0.5
        return (b[0] + SHR * pa) / (b[1] + SHR)
    for g in games:               # burn-in: the first half of 2024 is its own baseline
        if g[2][:7] < WF:
            pend.append((g[3], rd[g[0]]))
    flush()
    for g in games:
        mo = g[2][:7]
        if mo >= WF and mo != cur:
            flush()
            cur = mo
        rr = rd[g[0]]
        num = den = 0.0
        for r in rr:
            w = wp if r[2] else (1.0 if r[3] >= 20000 and r[4] >= 20000 else wm)
            num += w * (r[1] - (p_of(g[3], r) - 0.5))
            den += w
        out[g[0]] = num / den if den else g[7] / (g[7] + g[8])
        if mo >= WF:
            pend.append((g[3], rr))
    return out


def sync(full=False, limit=None):
    bo3 = cs2_bo3.load()
    games = [g for g in bo3["games"] if g[2] and g[2] >= START and g[5] is not None and g[7] is not None]
    by_m = defaultdict(list)
    for g in games:
        by_m[g[2][:7]].append(g)
    now = dt.datetime.now(dt.timezone.utc)
    todo, shards = [], {}
    for mo in sorted(by_m):
        d = shards[mo] = shard(mo)
        for g in by_m[mo]:
            if str(g[0]) in d["games"]:
                continue
            seen = d["none"].get(str(g[0]))
            if seen and (full or seen > (dt.datetime.fromisoformat(g[2]) + dt.timedelta(days=3)).isoformat()):
                continue
            todo.append(g)
    todo.sort(key=lambda g: g[2], reverse=True)
    if limit:
        todo = todo[:limit]
    print(f"rounds: {len(todo)} maps to pull")
    t0, done = time.time(), 0

    def one(g):
        return g, get(f"games/{g[0]}")
    dirty = set()
    with ThreadPoolExecutor(8) as ex:
        for g, res in ex.map(one, todo):
            mo = g[2][:7]
            done += 1
            if res is None:
                continue
            rr = rounds(res)
            # keep a map only when its rounds add up to the final score
            if rr and len(rr) == g[7] + g[8] and sum(r[1] for r in rr) == g[7]:
                shards[mo]["games"][str(g[0])] = rr
                shards[mo]["none"].pop(str(g[0]), None)
            else:
                shards[mo]["none"][str(g[0])] = now.isoformat()[:19]
            dirty.add(mo)
            if done % 2000 == 0:
                print(f"  {done}/{len(todo)} {time.time() - t0:.0f}s", flush=True)
                for m in dirty:
                    save(m, shards[m])
                dirty = set()
    for m in dirty:
        save(m, shards[m])
    print(f"rounds: {done} pulled in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    lim = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), None)
    sync("--full" in sys.argv, lim)
