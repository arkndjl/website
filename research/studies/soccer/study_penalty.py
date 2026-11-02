"""Study: penalty placement (StatsBomb end location) and conversion, in-game and shootouts."""
import json, sys
from collections import defaultdict
from common import *

SCR = sys.argv[1]
recs = load(SCR + "/compact.jsonl")
pens = []
for r in recs:
    for s in r["shots"]:
        if s["type"] != "Penalty" or not s["end"]: continue
        y = s["end"][1]; z = s["end"][2] if len(s["end"]) > 2 else None
        foot = s["foot"]
        # StatsBomb: attacking toward x=120, y grows to the shooter's right
        side = "centre" if 38.67 <= y <= 41.33 else ("left" if y < 38.67 else "right")
        nat = None
        if foot in ("Right Foot", "Left Foot") and side != "centre":
            nat = (side == "left") == (foot == "Right Foot")   # cross-body side for the kicking foot
        pens.append({"id": r["id"], "goal": s["goal"], "side": side, "y": y, "z": z, "foot": foot, "nat": nat,
                     "so": s["p"] == 5, "out": s["out"], "gender": "W" if "Women" in r["comp"] or r["comp"] in
                     ("FA Women's Super League", "NWSL", "Frauen Bundesliga", "Liga F", "Serie A Women",
                      "Women's World Cup", "UEFA Women's Euro") else "M", "season": r["season"]})
print("penalties", len(pens), "shootout", sum(p["so"] for p in pens))
from collections import Counter
print(Counter(p["out"] for p in pens))
def rate(ps):
    k = sum(p["goal"] for p in ps); n = len(ps); lo, hi = wilson(k, n); return (k / n if n else float("nan"), lo, hi, n)
res = {"n": len(pens)}
# height: low z<=0.9 (roughly below keeper's hip), mid, high z>1.8 (of 2.67 crossbar); only on-frame + saved shots have z reliable
for nm, f in (("left", lambda p: p["side"] == "left"), ("centre", lambda p: p["side"] == "centre"), ("right", lambda p: p["side"] == "right"),
              ("natural side", lambda p: p["nat"] is True), ("open-foot side", lambda p: p["nat"] is False)):
    res[nm] = rate([p for p in pens if f(p)]); print(nm, res[nm])
cells = []
for side in ("left", "centre", "right"):
    for h, f in (("low", lambda z: z is not None and z < 1.0), ("high", lambda z: z is not None and z >= 1.0)):
        ps = [p for p in pens if p["side"] == side and f(p["z"])]
        res[side + "_" + h] = rate(ps); print(side, h, res[side + "_" + h])
for h, f in (("low", lambda z: z is not None and z < 1.0), ("high", lambda z: z is not None and z >= 1.0)):
    res["all_" + h] = rate([p for p in pens if f(p["z"])]); print("all", h, res["all_" + h])
    res["side_" + h] = rate([p for p in pens if f(p["z"]) and p["side"] != "centre"]); print("side", h, res["side_" + h])
res["shootout"] = rate([p for p in pens if p["so"]]); res["ingame"] = rate([p for p in pens if not p["so"]])
res["men"] = rate([p for p in pens if p["gender"] == "M"]); res["women"] = rate([p for p in pens if p["gender"] == "W"])
print({k: res[k] for k in ("shootout", "ingame", "men", "women")})
# share choosing centre
res["share_centre"] = (sum(p["side"] == "centre" for p in pens), len(pens))
res["share_high"] = (sum(1 for p in pens if p["z"] is not None and p["z"] >= 1.0), sum(1 for p in pens if p["z"] is not None))
print(res["share_centre"], res["share_high"])
# split: men vs women for high vs low
for g in ("M", "W"):
    for h, f in (("low", lambda z: z is not None and z < 1.0), ("high", lambda z: z is not None and z >= 1.0)):
        res[f"{g}_{h}"] = rate([p for p in pens if p["gender"] == g and f(p["z"])]); print(g, h, res[f"{g}_{h}"])
json.dump(res, open(SCR + "/penalty_results.json", "w"), indent=1)
