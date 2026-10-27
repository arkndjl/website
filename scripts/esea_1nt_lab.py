#!/usr/bin/env python3
"""1NTERLYTICS: 1NT's descriptive history book for the team tab of /laursen_111/.

Reads every official 1NT match (research/esea_1nt_history.json.gz, scripts/esea_1nt_history.mjs) plus any
finished match in data/esea.json the history has not caught yet, and writes data/esea_lab.json:

  maps     per-map record since S53: W-L, round diff, win rate shrunk toward 50% (Beta(10,10) prior),
           last 90 days, average first-half rounds won, overtime record
  halves   match record after leading (7+ of 12), level (6) or trailing (5 or fewer) at the half
  close    maps decided by 3 rounds or fewer, overtime, and by 8 or more
  seasons  ESEA league seasons: record, rounds, and team box-score rates per round
  players  each player's ESEA seasons (10+ maps in total)
  h2h      every opponent met: record and the maps

Descriptive only. Team map records and lifetime splits failed as predictors held out (PR #458), so the
match model uses players' FACEIT map splits; this file is for prep and reading the past, not for odds.
Runs in the esea season workflow after scripts/fetch_esea.mjs.
"""
import gzip
import json
import re
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "research" / "esea_1nt_history.json.gz"
LIVE = ROOT / "data" / "esea.json"
OUT = ROOT / "data" / "esea_lab.json"
PRIOR = 10  # Beta(10, 10): a map record needs ~20 maps before it moves halfway off 50%
MIN_PLAYER_MAPS = 10

# history box line order (scripts/esea_1nt_history.mjs `full`)
K, SNIP, ENTRY, FLASH, UTIL, CLU, D, A, ADR, K2, K3, K4, K5, ENTRYW, C11W, C12W, UDMG, FLASHED, MVP, FSUCC, USUCC, CLUK, PISK, HS, C11, C12 = range(26)


def league(comp):
    """(season, division) for an ESEA league competition name, else None."""
    m = re.search(r"\bS(\d{2})\b", comp or "")
    if not m or "Qualifier" in comp:
        return None
    div = next((d for d in ("Advanced", "Main", "Intermediate", "Open") if d in comp), "")
    if div == "Open" and "9-10" in comp.replace("Open9-10", "Open 9-10"):
        div = "Open 9-10"
    return int(m.group(1)), div, "Playoffs" in comp


def live_line(p):
    """data/esea.json box line -> the history line order."""
    line = [0] * 26
    for i, k in ((K, "k"), (SNIP, "snip"), (ENTRY, "entries"), (FLASH, "flashes"), (D, "d"), (A, "a"), (ADR, "adr"),
                 (K2, "k2"), (K3, "k3"), (K4, "k4"), (K5, "k5"), (ENTRYW, "entryWins"), (UDMG, "util"), (FLASHED, "flashed"),
                 (MVP, "mvp"), (FSUCC, "fsucc"), (USUCC, "usucc"), (CLUK, "clutchK"), (PISK, "pistolK"), (HS, "hs")):
        line[i] = p.get(k) or 0
    line[HS] = round((p.get("hs") or 0) * (p.get("k") or 0) / 100)  # live hs is a percentage
    line[C11], line[C12] = p.get("c11") or 0, p.get("c12") or 0
    line[CLU] = line[C11] + line[C12]
    return line


def load():
    nick = {}
    live = json.loads(LIVE.read_text()) if LIVE.exists() else {}
    for m in live.get("members", []):
        nick[m["id"]] = m["nick"]
    rows = []
    seen = set()
    if HIST.exists():
        for m in json.load(gzip.open(HIST))["matches"]:
            if m.get("status") != "FINISHED" or m.get("compName") == "Normal Competitive":
                continue
            seen.add(m["id"])
            maps = []
            for mp in m.get("maps") or []:
                us = []
                for pid, name, line in mp.get("us") or []:
                    nick.setdefault(pid, name)
                    us.append((pid, line))
                maps.append({"map": mp["map"], "rf": mp["rf"], "ra": mp["ra"], "h1": mp.get("first"), "ot": mp.get("ot") or 0, "us": us})
            rows.append({"id": m["id"], "at": m["at"], "comp": m.get("compName") or "", "opp": m["opp"]["id"], "oppName": m["opp"]["name"], "maps": maps})
    name_id = {v: k for k, v in nick.items()}
    for m in live.get("matches", []):
        if m.get("status") != "FINISHED" or m["id"] in seen:
            continue
        maps = [{"map": mp["map"], "rf": mp["rf"], "ra": mp["ra"], "h1": None, "ot": int(mp["rf"] + mp["ra"] > 24),
                 "us": [(name_id.get(p["name"], p["name"]), live_line(p)) for p in mp.get("players") or []]} for mp in m.get("maps") or []]
        rows.append({"id": m["id"], "at": m["at"], "comp": (live.get("championship") or {}).get("name", ""), "opp": m["opp"]["id"], "oppName": m["opp"]["name"], "maps": maps})
    rows.sort(key=lambda r: r["at"])
    return rows, nick, live


def rec(n, w):
    return {"n": n, "w": w, "l": n - w, "wr": round(100 * w / n) if n else None}


def rates(lines, rounds):
    """team or player rates from summed box lines over `rounds` rounds."""
    t = [sum(x[i] for x in lines) for i in range(26)]
    nmaps = len(lines)
    return {
        "kd": round(t[K] / t[D], 2) if t[D] else None,
        "kpr": round(t[K] / rounds, 2) if rounds else None,
        "adr": round(sum(x[ADR] for x in lines) / nmaps, 1) if nmaps else None,
        "hs": round(100 * t[HS] / t[K]) if t[K] else None,
        "entry": round(100 * t[ENTRYW] / t[ENTRY]) if t[ENTRY] else None,
        "clutch": round(100 * (t[C11W] + t[C12W]) / (t[C11] + t[C12])) if (t[C11] + t[C12]) else None,
        "udr": round(t[UDMG] / rounds, 1) if rounds else None,
        "fpr": round(t[FSUCC] / rounds, 2) if rounds else None,
    }


def main():
    rows, nick, live = load()
    now = time.time() * 1000
    out = {"asof": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "prior": PRIOR}
    allmaps = [(r, mp) for r in rows for mp in r["maps"]]
    out["n"] = {"matches": len(rows), "maps": len(allmaps), "since": min(r["at"] for r in rows) if rows else None}

    # ---- map book
    book = defaultdict(lambda: {"n": 0, "w": 0, "rf": 0, "ra": 0, "n90": 0, "w90": 0, "h1": [], "otn": 0, "otw": 0, "last": 0})
    for r, mp in allmaps:
        b = book[mp["map"]]
        win = mp["rf"] > mp["ra"]
        b["n"] += 1; b["w"] += win; b["rf"] += mp["rf"]; b["ra"] += mp["ra"]; b["last"] = max(b["last"], r["at"])
        if now - r["at"] < 90 * 864e5:
            b["n90"] += 1; b["w90"] += win
        if mp["h1"] is not None:
            b["h1"].append(mp["h1"])
        if mp["ot"] or mp["rf"] + mp["ra"] > 24:
            b["otn"] += 1; b["otw"] += win
    out["maps"] = sorted(({
        "map": k, **rec(b["n"], b["w"]), "rd": b["rf"] - b["ra"], "rdpm": round((b["rf"] - b["ra"]) / b["n"], 1),
        "shr": round(100 * (b["w"] + PRIOR) / (b["n"] + 2 * PRIOR)), "n90": b["n90"], "w90": b["w90"],
        "h1": round(sum(b["h1"]) / len(b["h1"]), 1) if b["h1"] else None, "otn": b["otn"], "otw": b["otw"], "last": b["last"],
    } for k, b in book.items()), key=lambda x: (-x["n"], x["map"]))

    # ---- halves and close maps (MR12: 12 rounds in the first half)
    halves = {"lead": [0, 0], "level": [0, 0], "trail": [0, 0]}
    close = {"close": [0, 0], "ot": [0, 0], "blowout": [0, 0]}
    for r, mp in allmaps:
        win = mp["rf"] > mp["ra"]
        if mp["h1"] is not None:
            k = "lead" if mp["h1"] >= 7 else "level" if mp["h1"] == 6 else "trail"
            halves[k][0] += 1; halves[k][1] += win
        ot = mp["ot"] or mp["rf"] + mp["ra"] > 24
        k = "ot" if ot else "close" if abs(mp["rf"] - mp["ra"]) <= 3 else "blowout" if abs(mp["rf"] - mp["ra"]) >= 8 else None
        if k:
            close[k][0] += 1; close[k][1] += win
    out["halves"] = {k: rec(*v) for k, v in halves.items()}
    out["close"] = {k: rec(*v) for k, v in close.items()}

    # ---- ESEA seasons: team rates, and each player's
    seas = defaultdict(lambda: {"div": "", "maps": [], "po": False})
    for r, mp in allmaps:
        lg = league(r["comp"])
        if not lg:
            continue
        s = seas[lg[0]]
        s["div"] = s["div"] or lg[1]
        s["po"] = s["po"] or lg[2]
        s["maps"].append(mp)
    out["seasons"] = []
    per = defaultdict(lambda: defaultdict(lambda: {"lines": [], "rounds": 0}))
    for sn in sorted(seas, reverse=True):
        s = seas[sn]
        lines, rounds, w = [], 0, 0
        for mp in s["maps"]:
            rr = mp["rf"] + mp["ra"]
            w += mp["rf"] > mp["ra"]
            for pid, line in mp["us"]:
                lines.append(line)
                rounds += rr
                p = per[pid][sn]; p["lines"].append(line); p["rounds"] += rr
        n = len(s["maps"])
        rf = sum(mp["rf"] for mp in s["maps"]); ra = sum(mp["ra"] for mp in s["maps"])
        out["seasons"].append({"s": sn, "div": s["div"], "playoffs": s["po"], **rec(n, w), "rd": rf - ra, "rdpm": round((rf - ra) / n, 1) if n else None,
                               "rwp": round(100 * rf / (rf + ra)) if rf + ra else None, **rates(lines, rounds)})
    players = []
    for pid, by in per.items():
        tot_lines = [x for v in by.values() for x in v["lines"]]
        if len(tot_lines) < MIN_PLAYER_MAPS:
            continue
        tot_rounds = sum(v["rounds"] for v in by.values())
        players.append({"name": nick.get(pid, pid), "maps": len(tot_lines), **rates(tot_lines, tot_rounds),
                        "seasons": [{"s": sn, "maps": len(v["lines"]), **rates(v["lines"], v["rounds"])} for sn, v in sorted(by.items(), reverse=True)]})
    out["players"] = sorted(players, key=lambda p: -p["maps"])

    # ---- head to head
    h2h = {}
    for r in rows:
        h = h2h.setdefault(r["opp"], {"name": r["oppName"], "w": 0, "l": 0, "maps": []})
        for mp in r["maps"]:
            win = mp["rf"] > mp["ra"]
            h["w" if win else "l"] += 1
            h["maps"].append([r["at"], mp["map"], mp["rf"], mp["ra"], (league(r["comp"]) or [None])[0]])
    out["h2h"] = h2h
    # keep the old stamp when nothing else changed, so the 20-minute workflow commits only real changes
    try:
        prev = json.loads(OUT.read_text())
        if {k: v for k, v in prev.items() if k != "asof"} == {k: v for k, v in out.items() if k != "asof"}:
            out["asof"] = prev["asof"]
    except (OSError, ValueError, KeyError):
        pass
    OUT.write_text(json.dumps(out, separators=(",", ":")) + "\n")
    print(f"{OUT.relative_to(ROOT)}: {len(rows)} matches, {len(allmaps)} maps, {len(out['players'])} players, {len(h2h)} opponents")


if __name__ == "__main__":
    main()
