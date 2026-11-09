# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Compact extraction of NHL play-by-play into one JSON-lines file (run with python3 -I).
usage: extract.py <pbp_dir> <out.jsonl>"""
import gzip, json, os, sys
KEEP = {"goal", "shot-on-goal", "missed-shot", "blocked-shot", "faceoff", "penalty",
        "delayed-penalty", "stoppage", "period-end", "period-start"}
src, out = sys.argv[1], sys.argv[2]
n = 0
with open(out, "w") as fo:
    for fn in sorted(os.listdir(src)):
        try:
            d = json.load(gzip.open(os.path.join(src, fn)))
        except Exception:
            continue
        if d.get("gameType") != 2 or d.get("gameState") not in ("OFF", "FINAL"):
            continue
        home, away = d["homeTeam"]["id"], d["awayTeam"]["id"]
        goalies = [r["playerId"] for r in d.get("rosterSpots", []) if r.get("positionCode") == "G"]
        team_of = {r["playerId"]: r["teamId"] for r in d.get("rosterSpots", [])}
        ev = []
        for p in d["plays"]:
            k = p.get("typeDescKey")
            if k not in KEEP:
                continue
            pd = p.get("periodDescriptor", {})
            mm, ss = p.get("timeInPeriod", "0:0").split(":")
            det = p.get("details", {}) or {}
            owner = det.get("eventOwnerTeamId")
            if k == "blocked-shot":   # attribute to shooting team
                owner = team_of.get(det.get("shootingPlayerId"), None)
            ev.append([pd.get("number"), int(mm) * 60 + int(ss), p.get("situationCode") or "", k, owner,
                       det.get("zoneCode"), det.get("homeScore"), det.get("awayScore"),
                       det.get("reason") or det.get("typeCode") or det.get("secondaryReason")])
        go = d.get("gameOutcome", {}) or {}
        fo.write(json.dumps({"gid": d["id"], "season": d["season"], "home": home, "away": away,
                             "goalies": goalies, "last": go.get("lastPeriodType"),
                             "hs": d["homeTeam"].get("score"), "as": d["awayTeam"].get("score"),
                             "ev": ev}) + "\n")
        n += 1
print("games", n)
