"""Download StatsBomb open-data events for selected competitions and keep a compact per-match record.
Output: <scratch>/soccer/compact.jsonl (one line per match). Raw event JSON is not kept."""
import json, os, subprocess, sys, glob
from concurrent.futures import ThreadPoolExecutor

SCR = sys.argv[1]  # scratch soccer dir
BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
# full-season leagues and full tournaments only (single-team samples excluded)
KEEP = ["1238_108", "1267_107", "12_27", "131_281", "135_281", "182_281", "223_282", "2_27", "37_281", "37_4",
        "37_42", "37_90", "43_106", "43_3", "49_107", "49_3", "53_106", "53_315", "55_282", "55_43", "72_107",
        "72_30", "7_27"]
OUT = os.path.join(SCR, "compact.jsonl")

def cardname(e):
    for k in ("foul_committed", "bad_behaviour"):
        c = e.get(k, {}).get("card")
        if c: return c["name"]
    return None

def extract(m):
    mid = m["match_id"]
    r = subprocess.run(["curl", "-sS", "--fail", "--retry", "3", f"{BASE}/events/{mid}.json"], capture_output=True)
    if r.returncode: return None
    ev = json.loads(r.stdout)
    home, away = m["home_team"]["home_team_name"], m["away_team"]["away_team_name"]
    rec = {"id": mid, "comp": m["competition"]["competition_name"], "season": m["season"]["season_name"],
           "date": m["match_date"], "home": home, "away": away, "hs": m["home_score"], "as": m["away_score"],
           "stage": m.get("competition_stage", {}).get("name"), "shots": [], "subs": [], "cards": [], "og": [],
           "corners": [], "half_end": {}}
    for e in ev:
        p = e["period"]; t = e["type"]["name"]; tm = e.get("team", {}).get("name")
        mi, se = e["minute"], e["second"]
        if t == "Shot":
            s = e["shot"]
            rec["shots"].append({"p": p, "m": mi, "s": se, "team": tm, "xg": s.get("statsbomb_xg", 0),
                                 "goal": s["outcome"]["name"] == "Goal", "type": s["type"]["name"],
                                 "pp": e["play_pattern"]["name"], "loc": e.get("location"),
                                 "end": s.get("end_location"), "out": s["outcome"]["name"],
                                 "foot": s.get("body_part", {}).get("name"), "pl": e.get("player", {}).get("name")})
        elif t == "Substitution":
            rec["subs"].append({"p": p, "m": mi, "s": se, "team": tm,
                                "why": e["substitution"].get("outcome", {}).get("name")})
        elif t == "Own Goal Against":
            rec["og"].append({"p": p, "m": mi, "s": se, "team": tm})  # team = conceding team
        elif t == "Pass" and e["pass"].get("type", {}).get("name") == "Corner":
            rec["corners"].append({"p": p, "m": mi, "s": se, "team": tm})
        elif t == "Half End":
            rec["half_end"][str(p)] = max(rec["half_end"].get(str(p), 0), mi + se / 60)
        elif t in ("Goal Keeper",) and e["goalkeeper"]["type"]["name"] in ("Penalty Saved", "Penalty Conceded", "Penalty Saved To Post"):
            rec.setdefault("gkpen", []).append({"p": p, "m": mi, "s": se, "team": tm,
                "type": e["goalkeeper"]["type"]["name"], "pos": e["goalkeeper"].get("position", {}).get("name"),
                "tech": e["goalkeeper"].get("technique", {}).get("name"), "loc": e.get("location")})
        c = None
        if t in ("Foul Committed", "Bad Behaviour"):
            c = cardname(e)
        if c in ("Red Card", "Second Yellow"):
            rec["cards"].append({"p": p, "m": mi, "s": se, "team": tm, "card": c})
    return rec

def main():
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT): done.add(json.loads(l)["id"])
    ms = []
    for k in KEEP:
        ms += [m for m in json.load(open(os.path.join(SCR, "raw/matches", k + ".json"))) if m["match_id"] not in done]
    print("todo", len(ms), flush=True)
    with open(OUT, "a") as f, ThreadPoolExecutor(6) as ex:
        for i, rec in enumerate(ex.map(extract, ms)):
            if rec: f.write(json.dumps(rec) + "\n")
            if i % 200 == 0: print(i, flush=True)

if __name__ == "__main__":
    main()
