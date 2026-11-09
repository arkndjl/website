#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Round-level CS2 data from bo3.gg (api.bo3.gg/api/v1/games/<id>/rounds, no key) for the ARKBOARD CS2 studies.

Game list: scripts/data/cs2_bo3.json.gz (repo), CS2 era (from 2023-10-01), finished maps with a score, match tier
s/a first, then b (newest first). One request per map, 8 in flight. Writes one slim JSON line per map to
$SCRATCH/cs2/raw/rounds.jsonl (resumable). Odds are not read.

    python3 research/studies/cs2/fetch_rounds.py [max_maps]
"""
import gzip
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRATCH = Path(os.environ.get("CS2_RAW", "/tmp/claude-0/-home-user-website/74038a8a-b0f9-507c-bb0a-47f7b7c402f2/scratchpad/cs2/raw"))
OUT = SCRATCH / "rounds.jsonl"
UA = "Mozilla/5.0 (arkndjl.net research)"
API = "https://api.bo3.gg/api/v1/games/{}/rounds"
TEAM_KEYS = ("clan_name", "team_side", "win", "equipment_value", "economy_level", "money_spent", "money_save",
             "loss_bonus_streak", "lose_streak", "win_streak", "pistol_round", "kills", "death")


def get(gid):
    for t in range(4):
        try:
            req = urllib.request.Request(API.format(gid), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if t == 3:
                print("fail", gid, e, file=sys.stderr)
                return None
            time.sleep(2 ** t)


def slim(g, meta):
    rounds = []
    for r in sorted(g.get("game_rounds") or [], key=lambda r: r["round_number"]):
        rounds.append([r["round_number"], r["end_reason"], r["winner_clan_side"], r["winner_clan_name"],
                       [[t.get(k) for k in TEAM_KEYS] for t in r.get("game_round_team_clans") or []]])
    return {"id": g["id"], "match": g["match_id"], "begin": g["begin_at"], "map": g["map_name"], "num": g["number"],
            "winner": g["winner_clan_name"], "loser": g["loser_clan_name"], "ws": g["winner_clan_score"],
            "ls": g["loser_clan_score"], "wid": meta[0], "lid": meta[1], "tier": meta[2], "rounds": rounds}


def main():
    cap = int(sys.argv[1]) if len(sys.argv) > 1 else 10 ** 9
    d = json.load(gzip.open(ROOT / "scripts/data/cs2_bo3.json.gz", "rt"))
    tier = {m[0]: m[10] for m in d["matches"]}
    games = [g for g in d["games"] if g[2] and g[2] >= "2023-10-01" and g[7] is not None and g[5] is not None
             and tier.get(g[1]) in ("s", "a", "b")]
    rank = {"s": 0, "a": 0, "b": 1}
    games.sort(key=lambda g: (rank[tier[g[1]]], g[2]), reverse=False)
    games = sorted(games, key=lambda g: (rank[tier[g[1]]], -int(g[2][:10].replace("-", ""))))[:cap]
    SCRATCH.mkdir(parents=True, exist_ok=True)
    done = set()
    if OUT.exists():
        for line in OUT.open():
            try:
                done.add(json.loads(line)["id"])
            except ValueError:
                pass
    todo = [g for g in games if g[0] not in done]
    print(f"{len(games)} maps, {len(done)} done, {len(todo)} to fetch", flush=True)
    meta = {g[0]: (g[5], g[6], tier[g[1]]) for g in todo}
    n = 0
    with OUT.open("a") as f, ThreadPoolExecutor(8) as ex:
        for g in ex.map(get, [g[0] for g in todo]):
            n += 1
            if g and g.get("game_rounds") is not None:
                f.write(json.dumps(slim(g, meta[g["id"]]), separators=(",", ":")) + "\n")
            if n % 500 == 0:
                f.flush()
                print(n, flush=True)


if __name__ == "__main__":
    main()
