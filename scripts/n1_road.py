#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""1NT Road to Pro (data/n1_road.json, /1nt/#road): the LAURSEN_111 / 1NT path-to-pro prize model.

    python3 scripts/n1_road.py

Same model, inputs and seed as the "1NT Path to Pro" plan (project file laursen-earnings/model.py + inputs.csv, Nov 24
2026): Markov chain over NA ESEA states (Int, Main, Adv, T3 Pro, Out), 3 seasons a year, 10 years, 20,000 runs, seed 111.
Inputs: scripts/data/n1_road_inputs.csv (copy of the plan's inputs.csv; change both together, then rerun this).
Adds, read-only (no extra random draws, so EV/quantiles match the plan's results.csv exactly):
  states[sc][y] = share of runs in each state at the start of year y's first season;
  ladder = per-season EV per player by state (closed form from the same inputs) and move-up rates.
Live numbers (world rank, record, bracket) are read by layouts/shortcodes/n1road.html from data/esea*.json.
"""
import csv
import json
import random
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
P = {r["key"]: float(r["value"]) for r in csv.DictReader(open(ROOT / "scripts/data/n1_road_inputs.csv"))}
SPLIT = P["split_players"]
SF_PRIZE = [250, 500, 1000, 2000, 7500, 15000]
SF_MIX = {"Main": [.45, .30, .17, .06, .015, .005], "Adv": [.25, .25, .25, .15, .06, .04]}
MAJ = [0]
SC = "base"


def trans(sc):
    up_ma, up_ap = P[f"{sc}_main_to_adv"], P[f"{sc}_adv_to_pro"]
    return {
        "Int": {"Main": P["int_to_main"], "Out": P["quit"]},
        "Main": {"Adv": up_ma, "Int": P["main_to_int"], "Out": P["quit"]},
        "Adv": {"Pro": up_ap, "Main": P["adv_to_main"], "Out": P["quit"]},
        "Pro": {"Adv": P["pro_to_adv"], "Out": P["quit"] * .5},
        "Out": {},
    }


def step(s, T, rng):
    u, acc = rng.random(), 0.0
    for t, p in T[s].items():
        acc += p
        if u < acc:
            return t
    return s


def prize(s, rng, first):
    team = 0.0
    if rng.random() < P["cup_cash_p"]:
        team += P["cup_cash_team"]
    if s == "Int" and rng.random() < P["int_cash_p"]:
        team += P["int_cash_team"]
    if s in ("Main", "Adv"):
        p = P["s59_sf_p"] if (first and s == "Main") else P[f"{s.lower()}_sf_p"]
        if rng.random() < p:
            team += rng.choices(SF_PRIZE, SF_MIX[s])[0]
    if s in ("Main", "Adv"):
        for _ in range(int(P["oq_entries"])):
            if rng.random() < P[f"oq_cash_p_{s.lower()}"]:
                team += P["oq_cash_team"]
    if s == "Pro":
        if rng.random() < P["pro_cash_p"]:
            team += rng.lognormvariate(P["pro_ln_mu"], P["pro_ln_sd"])
        if rng.random() < P[f"{SC}_major_p"]:
            stage = rng.choices([1, 2, 3], [P["major_mix_s1"], P["major_mix_s2"], P["major_mix_s3"]])[0]
            team += P[f"sticker_s{stage}_team"] * rng.lognormvariate(0, P["sticker_sd"]) * P["sticker_regime"] + P["major_prize_team"]
            MAJ[0] += 1
    return team / SPLIT * (1 - P["org_cut"])


def run(sc, n=20000, years=10, seed=111):
    global SC
    SC = sc
    rng, T = random.Random(seed), trans(sc)
    if sc == "amateur":
        T["Main"] = {"Int": P["main_to_int"], "Out": P["quit"]}
        T["Int"]["Main"] = P["int_to_main"]
    yearly = [[] for _ in range(years)]
    cum = [[] for _ in range(years)]
    reach = {"Adv": 0, "Pro": 0, "Major": 0}
    states = [{k: 0 for k in ("Int", "Main", "Adv", "Pro", "Out")} for _ in range(years + 1)]
    for _ in range(n):
        s, tot, seen = "Main", 0.0, set()
        MAJ[0] = 0
        for y in range(years):
            states[y][s] += 1
            yr = 0.0
            for k in range(3):
                if s == "Out":
                    break
                yr += prize(s, rng, y == 0 and k == 0)
                seen.add(s)
                s = step(s, T, rng)
            tot += yr
            yearly[y].append(yr)
            cum[y].append(tot)
        states[years][s] += 1
        for r in reach:
            reach[r] += r in seen
        reach["Major"] = reach.get("Major", 0) + (MAJ[0] > 0)

    def q(xs, p):
        return sorted(xs)[int(p * (len(xs) - 1))]

    rows = [{"year": 2027 + y if y else "2026-27", "ev": round(statistics.mean(yearly[y]), 2),
             "p10": round(q(yearly[y], .1)), "p50": round(q(yearly[y], .5)), "p90": round(q(yearly[y], .9)),
             "p99": round(q(yearly[y], .99)), "pCash": round(sum(v > 0 for v in yearly[y]) / n, 3),
             "cum": round(statistics.mean(cum[y]), 2), "cumP10": round(q(cum[y], .1)), "cumP50": round(q(cum[y], .5)),
             "cumP90": round(q(cum[y], .9)), "cumP99": round(q(cum[y], .99))} for y in range(years)]
    st = [{k: round(v / n, 4) for k, v in d.items()} for d in states]
    return rows, {k: round(v / n, 3) for k, v in reach.items()}, st


def season_ev():
    """Per-season EV per player by state, closed form from the same inputs (base Major odds)."""
    cup = P["cup_cash_p"] * P["cup_cash_team"]
    sf = {s: sum(a * b for a, b in zip(SF_PRIZE, SF_MIX[s])) for s in SF_MIX}
    oq = lambda s: P["oq_entries"] * P[f"oq_cash_p_{s}"] * P["oq_cash_team"]
    from math import exp
    pro_cash = P["pro_cash_p"] * exp(P["pro_ln_mu"] + P["pro_ln_sd"] ** 2 / 2)
    mix = [(P[f"major_mix_s{i}"], P[f"sticker_s{i}_team"]) for i in (1, 2, 3)]   # Major stage exit mix
    sticker = sum(w * v for w, v in mix) * exp(P["sticker_sd"] ** 2 / 2) * P["sticker_regime"] + P["major_prize_team"]
    team = {
        "Open": 0.0,
        "Int": cup + P["int_cash_p"] * P["int_cash_team"],
        "Main": cup + P["main_sf_p"] * sf["Main"] + oq("main"),
        "Adv": cup + P["adv_sf_p"] * sf["Adv"] + oq("adv"),
        "Pro": cup + pro_cash + P["base_major_p"] * sticker,
    }
    return {k: round(v / SPLIT, 2) for k, v in team.items()}, round(sticker / SPLIT), round(sticker)


def main():
    out = {"asof": "2026-11-24", "runs": 20000, "seasonsPerYear": 3, "years": 10, "split": int(SPLIT),
           "orgCut": P["org_cut"], "scenarios": {}}
    for sc in ("amateur", "base", "climb"):
        rows, reach, st = run(sc)
        out["scenarios"][sc] = {"years": rows, "reach": reach, "states": st}
    ev, major_pp, major_team = season_ev()
    rng = random.Random(111)  # one Major's money per player: sticker share by stage exit + Stage 1 prize, 20,000 draws
    mj = []
    for _ in range(20000):
        st = rng.choices([1, 2, 3], [P["major_mix_s1"], P["major_mix_s2"], P["major_mix_s3"]])[0]
        mj.append((P[f"sticker_s{st}_team"] * rng.lognormvariate(0, P["sticker_sd"]) * P["sticker_regime"] + P["major_prize_team"]) / SPLIT)
    mj.sort()
    q = lambda p: round(mj[int(p * len(mj))])
    out["major"] = {"perPlayer": major_pp, "team": major_team, "p10": q(.1), "p50": q(.5), "p90": q(.9),
                    "prizeTeam": P["major_prize_team"], "regime": P["sticker_regime"],
                    "stages": [{"s": i, "mix": P[f"major_mix_s{i}"],
                                "pp": round((P[f"sticker_s{i}_team"] * P["sticker_regime"] + P["major_prize_team"]) / SPLIT)}
                               for i in (1, 2, 3)]}
    out["ladder"] = {
        "ev": ev,
        "up": {"Open": None, "Int": P["int_to_main"], "Main": [P["base_main_to_adv"], P["climb_main_to_adv"]],
               "Adv": [P["base_adv_to_pro"], P["climb_adv_to_pro"]], "Pro": [P["base_major_p"], P["climb_major_p"]]},
        "down": {"Main": P["main_to_int"], "Adv": P["adv_to_main"], "Pro": P["pro_to_adv"]},
    }
    out["s59"] = {"top2": P["s59_sf_p"], "top4": 0.02}
    out["prizes"] = [[a, b] for a, b in zip(["13-16", "9-12", "5-8", "3-4", "2nd", "1st"], SF_PRIZE)]
    out["sfMix"] = SF_MIX
    out["checkpoints"] = [
        {"by": "S59", "target": "top 4 Main A", "k": "top4"},
        {"by": "S60", "target": "top 16 seed", "k": "seed"},
        {"by": "S61", "target": "Advanced", "k": "div"},
        {"by": "2027", "target": "ARK world top 200", "k": "world", "v": 200},
        {"by": "2027", "target": "6 open qualifiers", "k": "oq", "now": "2", "v": 6},
        {"by": "2027", "target": "Twitch 500", "k": "twitch", "v": 500},
        {"by": "2028", "target": "T3 closed stage", "k": "t3"},
    ]
    (ROOT / "data/n1_road.json").write_text(json.dumps(out, separators=(",", ":")) + "\n")
    b = out["scenarios"]["base"]
    print("base 10y EV", b["years"][-1]["cum"], "reach", b["reach"], "ladder", ev, "major", out["major"])


if __name__ == "__main__":
    main()
