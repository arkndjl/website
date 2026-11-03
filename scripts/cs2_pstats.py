#!/usr/bin/env python3
"""Per-map player stats for the Counter-Strike players section, from bo3.gg's public API (no key).

    python3 scripts/cs2_pstats.py            # maps finished since the last run (and any earlier gaps), ~1-2 min a run
    python3 scripts/cs2_pstats.py --full     # every finished map since START (~80k calls, ~1.5 h at 8 threads)
    python3 scripts/cs2_pstats.py --players  # bo3.gg's player directory (birthdays, country, photo), ~210 calls

Reads the map list from scripts/data/cs2_bo3.json.gz (scripts/cs2_bo3.py) and calls games/{id}/players_stats once per
finished map. Writes monthly shards scripts/data/cs2_pstats/YYYY-MM.json.gz (one row per player per map, so a run only
rewrites the current month), columns in COLS; maps bo3.gg has no stats for go in "none" and are retried for 3 days.
Odds and money fields are not read.
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
from cs2_data import UA  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "scripts" / "data" / "cs2_pstats"
PDIR = ROOT / "scripts" / "data" / "cs2_pdir.json.gz"
START = "2024-01-01"
# one row per player per map: game, player id, team id, kills, deaths, assists, headshots, first kills, first deaths,
# trade kills, traded deaths, KAST x1000, ADR x10, bo3 rating x100, clutches, 3k+ rounds, nickname, damage taken (Nov 3),
# utility $ bought (Nov 3)
COLS = ["g", "p", "t", "k", "d", "a", "hs", "fk", "fd", "tk", "td", "kast", "adr", "rt", "cl", "mk", "nick", "gd", "ut"]


def get(path):
    for t in range(5):
        try:
            req = urllib.request.Request(cs2_bo3.API + path, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if t == 4:
                print("bo3", path[:60], e, file=sys.stderr)
                return None
            time.sleep(2 ** t)


def row(x):
    sp = x.get("steam_profile") or {}
    pl = sp.get("player") or {}
    tc = x.get("team_clan") or {}
    mk = x.get("multikills") or {}
    pid = pl.get("id") or (-sp["id"] if sp.get("id") else None)
    if pid is None:
        return None
    return [x["game_id"], pid, tc.get("team_id"), x.get("kills") or 0, x.get("death") or 0, x.get("assists") or 0,
            x.get("headshots") or 0, x.get("first_kills") or 0, x.get("first_death") or 0, x.get("trade_kills") or 0,
            x.get("trade_death") or 0, round((x.get("kast") or 0) * 1000), round((x.get("adr") or 0) * 10),
            round((x.get("player_rating") or 0) * 100), x.get("clutches") or 0,
            sum(int(v or 0) for k, v in mk.items() if k in ("3", "4", "5")), pl.get("nickname") or sp.get("nickname"),
            x.get("got_damage") or 0, x.get("utility_value") or 0]


def shard(month):
    f = DIR / f"{month}.json.gz"
    try:
        with gzip.open(f, "rt") as fh:
            return json.load(fh)
    except (FileNotFoundError, OSError, ValueError):
        return {"cols": COLS, "rows": [], "none": {}}


def save(month, d):
    DIR.mkdir(parents=True, exist_ok=True)
    d["rows"].sort(key=lambda r: (r[0], r[2] or 0, r[1]))
    with gzip.open(DIR / f"{month}.json.gz", "wt") as fh:
        json.dump(d, fh, separators=(",", ":"))


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
        have = {r[0] for r in d["rows"]}
        for g in by_m[mo]:
            if g[0] in have:
                continue
            seen = d["none"].get(str(g[0]))
            # bo3.gg posts stats a little after a map ends; give up on a map 3 days after it was played
            if seen and seen > (dt.datetime.fromisoformat(g[2]) + dt.timedelta(days=3)).isoformat():
                continue
            todo.append(g)
    todo.sort(key=lambda g: g[2], reverse=True)
    if limit:
        todo = todo[:limit]
    print(f"pstats: {len(todo)} maps to pull")
    t0, done = time.time(), 0

    def one(g):
        return g, get(f"games/{g[0]}/players_stats")
    dirty = set()
    with ThreadPoolExecutor(8) as ex:
        for g, res in ex.map(one, todo):
            mo = g[2][:7]
            done += 1
            if res is None:
                continue
            rows = [r for r in map(row, res) if r]
            if len(rows) >= 8:
                shards[mo]["rows"] += rows
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
    print(f"pstats: {done} pulled in {time.time() - t0:.0f}s")


def players():
    """bo3.gg's player directory: id -> [slug, nickname, birthday, country code, team id, photo]."""
    first = get("players?page[limit]=100&page[offset]=0")
    n = first["total"]["count"]
    with ThreadPoolExecutor(4) as ex:
        pages = list(ex.map(lambda o: get(f"players?page[limit]=100&page[offset]={o}&with=country"),
                            range(0, n + 100, 100)))
    out = {}
    for p in pages:
        for r in (p or {}).get("results", []):
            c = r.get("country") or {}
            out[str(r["id"])] = [r.get("slug"), r.get("nickname"), r.get("birthday"), c.get("code"), r.get("team_id"),
                                 (r.get("image_versions") or {}).get("150x150") or r.get("image_url")]
    if len(out) > 1000:
        with gzip.open(PDIR, "wt") as fh:
            json.dump(out, fh, separators=(",", ":"))
    print(f"players: {len(out)}")


if __name__ == "__main__":
    if "--players" in sys.argv:
        players()
    else:
        lim = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), None)
        sync("--full" in sys.argv, lim)
