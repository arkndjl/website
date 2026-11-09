# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Write the study JSON cards from the result files produced by the study_*.py scripts."""
import json, sys, os
SCR = sys.argv[1]; OUT = os.path.dirname(os.path.abspath(__file__))
DATA = "StatsBomb open data, 23 full seasons/tournaments (2015/16 EPL, Serie A, Ligue 1; men's WC/Euro/Copa/AFCON; ISL; women's leagues and tournaments), "
N = sum(1 for _ in open(SCR + "/compact.jsonl"))
def pct(x): return f"{100 * x:.0f}%"
def p1(x): return f"{100 * x:.1f}%"
def f2(x): return f"{x:+.2f}"

# ---- lead protection ----
L = json.load(open(SCR + "/lead_results.json")); b = L["bands"]; p = L["points"]; p75 = p["75"]
lead = {
 "id": "soccer-protecting-lead", "sport": "soccer",
 "question": "Does a team leading by one goal lose the xG battle late, and does it cost points?",
 "answer": f"Yes after 75': xG share {pct(b[5]['lead_share'])} vs {pct(b[5]['exp_share'])} expected. Costs {abs(p75['cost']):.2f} xPts from 75', but actual points held.",
 "findings": [
  f"Leading by 1, 75-90+: xG share {p1(b[5]['lead_share'])} (CI {p1(b[5]['lo'])}-{p1(b[5]['hi'])}), expected {p1(b[5]['exp_share'])}, {b[5]['n_matches']} matches.",
  f"Leader xG/90 75-90+: {b[5]['lead_xgf90']:.2f} for, {b[5]['lead_xga90']:.2f} against. 15-45': share {pct(b[1]['lead_share'])} and {pct(b[2]['lead_share'])}, expected {pct(b[1]['exp_share'])}.",
  f"Up 1 at 75' (n={p75['n']}): xPts {p75['x_real']:.2f} from realized xG vs {p75['x_exp']:.2f} at strength rates; gap {f2(p75['cost'])} (CI {f2(p75['cost_lo'])} to {f2(p75['cost_hi'])}).",
  f"Actual points {p75['pts']:.2f} (CI {p75['pts_lo']:.2f}-{p75['pts_hi']:.2f}), vs {p75['x_exp']:.2f} baseline (gap {abs(p75['act_minus_exp']):.2f}). Late xG lost does not show up in results.",
 ],
 "method": "11v11 minutes only, split by score state and 15-min band. Expected share from leave-one-out season xG for/against of both teams, home factor, and league xG volume by band. xPts from Poisson on remaining xG; CIs bootstrap by match.",
 "data": DATA + f"{L['n_matches']:,} matches with clean event data.",
 "n": L["n_matches"], "robust": True, "interest": 4,
 "split_check": f"From-75' xPts gap: 2015/16 men's leagues {f2(p['split_2015/16 men\'s leagues']['cost'])} (n={p['split_2015/16 men\'s leagues']['n']}), other comps {f2(p['split_other']['cost'])} (n={p['split_other']['n']}); both CIs exclude 0.",
 "chart": {"type": "line", "title": "xG share of team leading by 1, by minute band", "x_label": "minute (band midpoint)",
  "y_label": "xG share", "y_fmt": "pct", "x_reverse": False, "ref": {"y": 0.5, "label": "even"}, "mark": {"x": 75, "label": "75'"},
  "series": [
   {"name": "leading by 1, actual", "points": [{"x": r["x"], "y": round(r["lead_share"], 4), "lo": round(r["lo"], 4), "hi": round(r["hi"], 4), "n": r["n_matches"]} for r in b]},
   {"name": "same teams, expected", "points": [{"x": r["x"], "y": round(r["exp_share"], 4), "n": r["n_matches"]} for r in b]}]}}

# ---- subs ----
Sb = json.load(open(SCR + "/subs_results.json")); c = Sb["curves"]; l60 = Sb["landmark_60"]; l45 = Sb["landmark_45"]; ht = Sb["ht"]
def at(st, x): return next(q["y"] for q in c[st] if q["x"] == x)
subs = {
 "id": "soccer-first-sub-timing", "sport": "soccer",
 "question": "When do teams make their first sub by score state, and does an early first sub pay off?",
 "answer": f"Trailing teams sub first by 60', level and leading by 65'. A first sub before 60' adds {l60['xgd'][0]:+.2f} xG diff; no goal effect found.",
 "findings": [
  f"First tactical sub at HT: trailing {p1(ht['-1'][1] / ht['-1'][0])} (n={ht['-1'][0]}), level {p1(ht['0'][1] / ht['0'][0])} (n={ht['0'][0]}), leading {p1(ht['1'][1] / ht['1'][0])} (n={ht['1'][0]}).",
  f"Subbed by 60' if state held: trailing {pct(at('-1', 60))}, level {pct(at('0', 60))}, leading {pct(at('1', 60))}.",
  f"Sub before 60' vs none, 60' to end: xG diff {l60['xgd'][0]:+.3f} (CI {l60['xgd'][1]:+.3f} to {l60['xgd'][2]:+.3f}), goal diff {l60['gd'][0]:+.3f} (CI {l60['gd'][1]:+.2f} to {l60['gd'][2]:+.2f}); n={l60['n']:,}.",
  f"Trailing at 60': {l60['xgd_trailing'][0]:+.3f} xG diff (CI {l60['xgd_trailing'][1]:+.3f} to {l60['xgd_trailing'][2]:+.3f}, n={l60['xgd_trailing'][3]}). HT subs vs none: {l45['xgd'][0]:+.3f} (CI {l45['xgd'][1]:+.3f} to {l45['xgd'][2]:+.3f}).",
 ],
 "method": "Timing: discrete hazard of first tactical sub per minute by current state. Effect: landmark at 60' (and HT), OLS with match-clustered SE on score state, strength, home, prior xG diff and xG diff in the 15 min before the landmark (the trigger window), opponent early sub. Injury subs and red cards before the landmark excluded.",
 "data": DATA + f"{l60['matches']:,} matches, {l60['n']:,} team-matches at the 60' landmark.",
 "n": l60["n"], "robust": False, "interest": 3,
 "split_check": f"xG-diff effect {Sb['landmark_60']['split_2015/16'][0]:+.3f} in 2015/16 leagues, {Sb['landmark_60']['split_other'][0]:+.3f} elsewhere; same sign, neither CI excludes 0 alone.",
 "chart": {"type": "line", "title": "Share of teams with first tactical sub made, state held", "x_label": "minute", "y_label": "teams subbed",
  "y_fmt": "pct", "x_reverse": False, "ref": {"y": 0.5, "label": "half"}, "mark": {"x": 60, "label": "60'"},
  "series": [{"name": nm, "points": [{"x": q["x"], "y": round(q["y"], 4), "n": q["n"]} for q in c[k]]} for k, nm in (("-1", "trailing"), ("0", "level"), ("1", "leading"))]}}

# ---- momentum ----
M = json.load(open(SCR + "/momentum_results.json")); ca = M["conceded_0_10_all"]; sa = M["scored_0_10_all"]
mom = {
 "id": "soccer-after-conceding", "sport": "soccer",
 "question": "Do teams score more or less in the minutes after a goal?",
 "answer": f"No momentum swing. Team that just conceded scores {ca['g'][0]:.2f}x baseline in the next 10 min; scorer {sa['g'][0]:.2f}x. Restart dips the first 3 min.",
 "findings": [
  f"Team that conceded, 0-10 min: xG {ca['xg'][0]:.2f}x baseline (CI {ca['xg'][1]:.2f}-{ca['xg'][2]:.2f}), goals {ca['g'][0]:.2f}x (CI {ca['g'][1]:.2f}-{ca['g'][2]:.2f}).",
  f"Team that scored, 0-10 min: xG {sa['xg'][0]:.2f}x (CI {sa['xg'][1]:.2f}-{sa['xg'][2]:.2f}), goals {sa['g'][0]:.2f}x (CI {sa['g'][1]:.2f}-{sa['g'][2]:.2f}).",
  f"First 3 min after a goal both teams sit below baseline (xG {M['conceded'][0]['y']:.2f}x and {M['scored'][0]['y']:.2f}x): restart time.",
  f"No sign a team is most vulnerable just after scoring: its opponent's goals 0-10 min are {ca['g'][0]:.2f}x baseline.",
 ],
 "method": "Team-minutes (11v11) by time since last goal. Baseline: league rate for the same 15-min band and score state, scaled by pre-match strength (leave-one-out season xG). Observed/expected; CIs bootstrap by match.",
 "data": DATA + f"{M['matches']:,} matches, {M['team_minutes']:,} team-minutes.",
 "n": M["matches"], "robust": False, "interest": 3,
 "split_check": f"Conceding team 0-10 min goals: {M['conceded_0_10_2015/16']['g'][0]:.2f}x in 2015/16 leagues, {M['conceded_0_10_other']['g'][0]:.2f}x elsewhere; direction flips, so no stable effect.",
 "chart": {"type": "line", "title": "xG rate after a goal vs matched baseline", "x_label": "minutes since goal", "y_label": "observed / expected xG",
  "y_fmt": "num", "x_reverse": False, "ref": {"y": 1.0, "label": "baseline"}, "mark": None,
  "series": [{"name": nm, "points": [{"x": q["x"], "y": round(q["y"], 3), "lo": round(q["lo"], 3), "hi": round(q["hi"], 3), "n": q["n"]} for q in M[k]]}
             for k, nm in (("conceded", "team that conceded"), ("scored", "team that scored"))]}}

# ---- penalties ----
P = json.load(open(SCR + "/penalty_results.json"))
cats = [("left low", "left_low"), ("left high", "left_high"), ("centre", "centre"), ("right low", "right_low"), ("right high", "right_high")]
pen = {
 "id": "soccer-penalty-placement", "sport": "soccer",
 "question": "Where should a penalty taker aim?",
 "answer": f"Placement barely matters: high {pct(P['all_high'][0])}, low {pct(P['all_low'][0])}, centre {pct(P['centre'][0])}; CIs overlap. Shootout kicks {pct(P['shootout'][0])} vs {pct(P['ingame'][0])} in play.",
 "findings": [
  f"Upper half of goal: {p1(P['all_high'][0])} scored (CI {p1(P['all_high'][1])}-{p1(P['all_high'][2])}, n={P['all_high'][3]}); lower half {p1(P['all_low'][0])} (n={P['all_low'][3]}). Misses over the bar included.",
  f"Centre third: {p1(P['centre'][0])} (CI {p1(P['centre'][1])}-{p1(P['centre'][2])}, n={P['centre'][3]}); chosen on {pct(P['share_centre'][0] / P['share_centre'][1])} of kicks.",
  f"Kicking foot's natural side {p1(P['natural side'][0])} (n={P['natural side'][3]}) vs open side {p1(P['open-foot side'][0])} (n={P['open-foot side'][3]}).",
  f"Shootout {p1(P['shootout'][0])} (CI {p1(P['shootout'][1])}-{p1(P['shootout'][2])}, n={P['shootout'][3]}) vs in-game {p1(P['ingame'][0])} (CI {p1(P['ingame'][1])}-{p1(P['ingame'][2])}, n={P['ingame'][3]}).",
 ],
 "method": "Every penalty with an end location. Thirds of the goal mouth (posts at y 36 and 44), high = end height 1 m or more. Outcome = scored; Wilson 95% CIs. Keeper dive direction is not in the open data.",
 "data": DATA + f"{P['n']:,} penalties incl. {P['shootout'][3]} shootout kicks.",
 "n": P["n"], "robust": False, "interest": 2,
 "split_check": f"High vs low: men {pct(P['M_high'][0])} vs {pct(P['M_low'][0])}, women {pct(P['W_high'][0])} vs {pct(P['W_low'][0])}; edge not consistent. Shootout gap holds (CIs apart).",
 "chart": {"type": "bar", "title": "Penalty conversion by placement", "x_label": "placement (taker's view)", "y_label": "scored", "y_fmt": "pct",
  "x_reverse": False, "ref": {"y": round(sum(P[k][0] * P[k][3] for _, k in cats) / sum(P[k][3] for _, k in cats), 4), "label": "all"}, "mark": None,
  "series": [{"name": "conversion", "points": [{"x": lbl, "y": round(P[k][0], 4), "lo": round(P[k][1], 4), "hi": round(P[k][2], 4), "n": P[k][3]} for lbl, k in cats]}]}}

for d in (subs, lead, mom, pen):
    assert len(d["answer"]) <= 140, (d["id"], len(d["answer"]), d["answer"])
    for f in d["findings"]:
        if len(f) > 120: print("LONG", d["id"], len(f), f)
    json.dump(d, open(os.path.join(OUT, d["id"] + ".json"), "w"), indent=1)
    print(d["id"], "|", d["answer"])
