# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Write the study JSON cards from pull_results.json and other_results.json.
usage: python3 -I build_json.py <scratch_dir> <out_dir>"""
import json, os, sys
S, OUT = sys.argv[1], sys.argv[2]
P = json.load(open(os.path.join(S, "pull_results.json")))
O = json.load(open(os.path.join(S, "other_results.json")))
ms = lambda s: f"{int(round(s)) // 60}:{int(round(s)) % 60:02d}"
r3 = lambda x: round(float(x), 4)
DATA = "NHL API play-by-play + shift charts, regular seasons 2021-22 to 2024-25, 5,248 games"
NG = P["n_games"]
def w(id_, d): json.dump(d, open(os.path.join(OUT, id_ + ".json"), "w"), indent=2); print("wrote", id_)

# ---- 1. goalie pull
R, C = P["rates"], P["rate_ci"]; X = P["expo"]; A = P["actual"]
g1, g1ci, _ = P["gain"]["1"]
grid = [i * 0.5 for i in range(15)]
vc1 = P["val_checkpoint"][0]
from_opt = None
w("nhl-goalie-pull", {
  "id": "nhl-goalie-pull", "sport": "NHL",
  "question": "When should a trailing team pull its goalie?",
  "answer": f"Pull at {ms(P['opt1'])} down one, {ms(P['opt2'])} down two. Teams pull at {ms(A['1']['median'])} and {ms(A['2']['median'])}.",
  "findings": [
    f"Down 1, 6v5: {R['a6']['1']:.1f} GF/60 ({C['a61'][0]:.1f}-{C['a61'][1]:.1f}), {R['b6']['1']:.1f} GA/60 ({C['b61'][0]:.1f}-{C['b61'][1]:.1f}); {X['6v5_d1']['min']:,.0f} min.",
    f"Down 1, 5v5 last 10 min: {R['a5']['1']:.2f} GF/60 ({C['a51'][0]:.2f}-{C['a51'][1]:.2f}), {R['b5']['1']:.2f} GA/60; {X['5v5_d1']['min']:,.0f} min.",
    f"Optimum CI: {ms(P['opt1_ci'][0])}-{ms(P['opt1_ci'][1])} down 1, {ms(P['opt2_ci'][0])}-{ms(P['opt2_ci'][1])} down 2. {A['1']['share_at_or_before_opt']*100:.0f}% of down-1 pulls (n={A['1']['n']:,}) come that early.",
    f"Gain vs actual timing from 10:00 left, down 1: +{g1*100:.1f} pts tie chance ({g1ci[0]*100:.1f} to {g1ci[1]*100:.1f}).",
  ],
  "method": ("Outcome: level or ahead at 60:00. Per-second Markov model on goal rates by state (6v5, 5v5 down 1/2, tied), "
             "game-cluster bootstrap CIs. Model matches observed: down 1 at 6:00, "
             f"{vc1[4]*100:.1f}% predicted vs {vc1[3][0]*100:.1f}% observed (n={vc1[2]:,})."),
  "data": DATA + "; pull times from goalie shifts.", "n": NG, "robust": True, "interest": 4,
  "split_check": (f"Optimum down 1: {ms(P['splits']['early'][0])} in 2021-23, {ms(P['splits']['late'][0])} in 2023-25. "
                  f"Median actual pull: {ms(A['1']['by_season']['20212022'])} (2021-22) to {ms(A['1']['by_season']['20242025'])} (2024-25)."),
  "chart": {"type": "line", "title": "Tie chance by pull time, from 10:00 left",
            "x_label": "minutes left when pulled", "y_label": "level at 60:00 %", "y_fmt": "pct", "x_reverse": False,
            "ref": None, "mark": {"x": round(P["opt1"] / 60, 2), "label": "optimum, down 1"},
            "series": [
              {"name": "down 1", "points": [{"x": x, "y": r3(P["curve1"][i]), "lo": r3(P["curve1_ci"][i][0]), "hi": r3(P["curve1_ci"][i][1]), "n": NG} for i, x in enumerate(grid)]},
              {"name": "down 2", "points": [{"x": x, "y": r3(P["curve2"][i]), "lo": r3(P["curve2_ci"][i][0]), "hi": r3(P["curve2_ci"][i][1]), "n": NG} for i, x in enumerate(grid)]}]}})

# ---- 2. power-play pull
pp = O["pp"]; pr = pp["rates"]; pc = pp["rates_ci"]; ex = pp["expo"]
m64 = sum(v[0] for k, v in ex.items() if k.startswith("6v4")); g64 = sum(v[1] + v[2] for k, v in ex.items() if k.startswith("6v4"))
m54 = sum(v[0] for k, v in ex.items() if k.startswith("5v4"))
i2 = pp["starts"].index(120); i4 = pp["starts"].index(240)
w("nhl-pp-goalie-pull", {
  "id": "nhl-pp-goalie-pull", "sport": "NHL",
  "question": "Should a team down one late pull its goalie on a power play?",
  "answer": f"Yes with 3:00 or less left: 6v4 adds {pp['diff'][i2]*100:.0f} pts of tie chance at 2:00. Past 4:00 the gain is not clear.",
  "findings": [
    f"6v4: {pr['a64']:.1f} GF/60 ({pc['a64'][0]:.1f}-{pc['a64'][1]:.1f}), {pr['b64']:.1f} GA/60 ({pc['b64'][0]:.1f}-{pc['b64'][1]:.1f}); {m64:.0f} min, {g64} goals.",
    f"5v4 trailing, 3rd period: {pr['a54']:.1f} GF/60 ({pc['a54'][0]:.1f}-{pc['a54'][1]:.1f}), {pr['b54']:.1f} GA/60; {m54:,.0f} min.",
    f"Minor at 2:00 left, down 1: {pp['pull'][i2]*100:.0f}% level at 60:00 with 6v4 vs {pp['nopull'][i2]*100:.0f}% at 5v4 (diff CI {pp['diff_ci'][i2][0]*100:.0f} to {pp['diff_ci'][i2][1]*100:.0f} pts).",
    f"Minor at 4:00 left: +{pp['diff'][i4]*100:.1f} pts ({pp['diff_ci'][i4][0]*100:.1f} to {pp['diff_ci'][i4][1]*100:.1f}), not distinguishable from zero.",
  ],
  "method": ("Outcome: level or ahead at 60:00. Markov model, 2:00 minor: 6v4 vs 5v4 then optimal even-strength pull; "
             "rates from trailing teams in the 3rd period. 6v4 time is chosen late, so its rates carry selection."),
  "data": DATA + ".", "n": NG, "robust": True, "interest": 4,
  "split_check": (f"Gain at 2:00 left: +{pp['split_early']['diff'][i2]*100:.0f} pts in 2021-23, +{pp['split_late']['diff'][i2]*100:.0f} pts in 2023-25."),
  "chart": {"type": "line", "title": "Tie chance, down 1, minor called at time t",
            "x_label": "minutes left when power play starts", "y_label": "level at 60:00 %", "y_fmt": "pct", "x_reverse": False,
            "ref": None, "mark": None,
            "series": [
              {"name": "6v4, goalie out", "points": [{"x": s / 60, "y": r3(pp["pull"][i]), "lo": r3(pp["pull_ci"][i][0]), "hi": r3(pp["pull_ci"][i][1]), "n": NG} for i, s in enumerate(pp["starts"])]},
              {"name": "5v4, then pull", "points": [{"x": s / 60, "y": r3(pp["nopull"][i]), "lo": r3(pp["nopull_ci"][i][0]), "hi": r3(pp["nopull_ci"][i][1]), "n": NG} for i, s in enumerate(pp["starts"])]}]}})

# ---- 3. pull on an offensive-zone faceoff
fz = O["fz"]; oz, fly, nd = fz["1|OZ faceoff"], fz["1|on the fly"], fz["1|NZ/DZ faceoff"]; dd = fz["diff_d1"]; d12 = fz["diff_d12"]
cats = [("OZ draw, down 1", oz), ("on the fly, down 1", fly), ("OZ draw, down 2", fz["2|OZ faceoff"]), ("on the fly, down 2", fz["2|on the fly"])]
w("nhl-pull-oz-faceoff", {
  "id": "nhl-pull-oz-faceoff", "sport": "NHL",
  "question": "Does pulling the goalie at an offensive-zone faceoff tie more games?",
  "answer": f"No clear effect. After model adjustment, OZ-draw pulls tie {dd['diff']*100:+.1f} pts vs other pulls (CI {dd['ci'][0]*100:.1f} to {dd['ci'][1]*100:.1f}).",
  "findings": [
    f"Down 1, OZ draw: {oz['obs'][0]*100:.1f}% level at 60:00 vs {oz['pred']*100:.1f}% expected (n={oz['n']}, median {ms(oz['med_tl'])} left).",
    f"Down 1, on the fly: {fly['obs'][0]*100:.1f}% vs {fly['pred']*100:.1f}% expected (n={fly['n']:,}, median {ms(fly['med_tl'])} left).",
    f"Goal for before the goalie returns: {oz['gf_spell'][0]*100:.0f}% after OZ draw, {fly['gf_spell'][0]*100:.0f}% on the fly.",
    f"Down 1 and 2 pooled: {d12['diff']*100:+.1f} pts ({d12['ci'][0]*100:.1f} to {d12['ci'][1]*100:.1f}), n={d12['n_oz'] + d12['n_other']:,}.",
  ],
  "method": ("Outcome: level or ahead at 60:00, minus Markov-model expectation for the pull time (stay pulled). "
             "First even-strength pull per team-game; zone from a faceoff within 2 s of the goalie leaving. Bootstrap CIs."),
  "data": DATA + f"; {dd['n_oz'] + dd['n_other']:,} pulls down 1.", "n": dd["n_oz"] + dd["n_other"], "robust": False, "interest": 2,
  "split_check": f"OZ-draw residual down 1: {oz['early']*100:+.1f} pts in 2021-23, {oz['late']*100:+.1f} pts in 2023-25.",
  "chart": {"type": "bar", "title": "Level at 60:00 after a pull, by how it started",
            "x_label": "pull start", "y_label": "level at 60:00 %", "y_fmt": "pct", "x_reverse": False, "ref": None, "mark": None,
            "series": [
              {"name": "observed", "points": [{"x": c, "y": r3(v["obs"][0]), "lo": r3(v["obs"][1]), "hi": r3(v["obs"][2]), "n": v["n"]} for c, v in cats]},
              {"name": "model expected", "points": [{"x": c, "y": r3(v["pred"]), "n": v["n"]} for c, v in cats]}]}})

# ---- 4. score effects
se = O["se"]; lab = {"-3": "down 3+", "-2": "down 2", "-1": "down 1", "0": "tied", "1": "up 1", "2": "up 2", "3": "up 3+"}
ks = ["-3", "-2", "-1", "0", "1", "2", "3"]
d1, d3 = se["-1"], se["-3"]
w("nhl-score-effects", {
  "id": "nhl-score-effects", "sport": "NHL",
  "question": "How much do score effects tilt 5v5 shots, and do goals follow?",
  "answer": f"Trailing teams take {d1['fen_share']*100:.1f}% of unblocked attempts down 1, {d3['fen_share']*100:.1f}% down 3+. Goal share: {d1['goal_share']*100:.1f}% and {d3['goal_share']*100:.1f}%.",
  "findings": [
    f"Down 1: {d1['fen_share']*100:.1f}% attempt share ({d1['fen_ci'][0]*100:.1f}-{d1['fen_ci'][1]*100:.1f}), {d1['goal_share']*100:.1f}% goal share ({d1['goal_ci'][0]*100:.1f}-{d1['goal_ci'][1]*100:.1f}).",
    f"Down 1 shooting: {d1['sh_for']*100:.2f}% ({d1['sh_for_ci'][0]*100:.2f}-{d1['sh_for_ci'][1]*100:.2f}) for vs {d1['sh_against']*100:.2f}% against.",
    f"Down 3+: {d3['fen_share']*100:.1f}% of attempts, {d3['goal_share']*100:.1f}% of goals ({d3['goal_ci'][0]*100:.1f}-{d3['goal_ci'][1]*100:.1f}); n={d3['n_att']:,} attempts.",
  ],
  "method": "Unblocked 5v5 attempts (shots, misses, goals), periods 1-3, by score before the attempt. Game-cluster bootstrap CIs.",
  "data": DATA + f"; {O['n_fen']:,} attempts.", "n": NG, "robust": True, "interest": 2,
  "split_check": (f"Down-1 attempt share {se['split_early']['-1'][0]*100:.1f}% in 2021-23, {se['split_late']['-1'][0]*100:.1f}% in 2023-25."),
  "chart": {"type": "bar", "title": "5v5 share by score state", "x_label": "score state", "y_label": "share %",
            "y_fmt": "pct", "x_reverse": False, "ref": {"y": 0.5, "label": "even"}, "mark": None,
            "series": [
              {"name": "unblocked attempts", "points": [{"x": lab[k], "y": r3(se[k]["fen_share"]), "lo": r3(se[k]["fen_ci"][0]), "hi": r3(se[k]["fen_ci"][1]), "n": se[k]["n_att"]} for k in ks]},
              {"name": "goals", "points": [{"x": lab[k], "y": r3(se[k]["goal_share"]), "lo": r3(se[k]["goal_ci"][0]), "hi": r3(se[k]["goal_ci"][1]), "n": se[k]["n_goals"]} for k in ks]}]}})
