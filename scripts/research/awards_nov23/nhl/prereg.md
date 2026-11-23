# NHL awards, Nov 23 2026: pre-registration (written before any of these tests ran)

Engine, gate and history as scripts/awards_research.py / awards_more.py: rank-ordered logit, L2 1, leave one season
out, held-out log P(winner) (or log-likelihood of the named k for a top-k race), one-sided paired t against the null,
Holm at .05 over the NHL's whole list (Hart, Norris, Vezina, Calder p-values in data/awards_fit.json + the new races),
gain > 0 and most seasons won. Seasons 2010-2026 (Hockey-Reference voting pages; skater lines from Hockey-Reference
NHL_<S>_skaters.html for PIM, +/-, faceoffs, takeaways, blocks, hits, shorthanded TOI is not on the page).

## A. New races (one voter model each, fixed here)

| race | pool | depth | voter model cols | null |
|---|---|---|---|---|
| selke | forwards, 40+ GP | 3 | gd (WAR's defensive goals), war, pts, pm, fow share x centre (fo), tk (takeaways/gp), tpct, prev_selke | gd |
| byng | skaters, 40+ GP | 3 | pimpg (PIM a game), pts, war, gfrac, tpct, d, prev_byng | war |
| allstar | F 40+ GP (6 named), D 40+ GP (4), G 25+ GP (2): one race per group a season, test summed by season | top-k by group | war, pts, g, gsax, tpct, gfrac, prev_allstar | war |
| lindsay | Hart pool (30+ GP) | 1 (winner; finalists are not ordered) | war, pts, g, tpct, gfrac, goalie, prev_lindsay | war |
| adams | the 32 teams (a coach stands for his team; mid-season hires: team of record on the Wikipedia list) | 1 | tpct, dexp = tpct - last season's tpct, gd a game, prev_adams (coach name) | tpct |

History: Selke, Byng, All-Star votes from Hockey-Reference; Lindsay and Adams winners from Wikipedia.
Jack Adams expectation = last season's points % (the only free point-in-time preseason expectation for every season
2010-2026; no archived preseason market totals or our own preseason ratings for the history).

Stat titles (deterministic leaders, no voter gate): Art Ross (points, goals break ties) and Rocket Richard (goals).
Test with the as-of machinery (scripts/awards_asof.py nhl_skaters checkpoints at 25 / 50 / 75% of 2011-2026): P(lead)
from the live draw with (P) the predictive rates (blended toward last season, as the live layer) and (C) this season's
own rate only (conviction). Score: held-out log loss of the actual leader, favourite hit rate vs mean favourite P
(calibration). Predictive is shown when it is no worse than C (paired t over season-checkpoints) and its favourite P is
within 2 se of the hit rate; else only the conviction view.

Conviction views (P(lead) on this season's own rate): Selke on gd, All-Star on war (top k by group), Lindsay on war,
Art Ross on points, Rocket Richard on goals. Byng and Adams: no own value metric for sportsmanship / coaching (none).

## B. Driver add-ons to the existing four (each one model = current cols + the driver; paired held-out t vs the
current model; Holm over every driver test below together, at .05; ship = Holm pass + gain > 0 + most seasons won)

Calder:
1. lslot: ln(overall draft pick), undrafted = 225
2. dfv: draft-time FV, the hockey prospects draft model's out-of-class grade (classes 2008-19) or its grade from the
   fit for later classes (not in the fit), undrafted = 25 (point-in-time: the draft is before the rookie season)
3. bo: next up BO% for that season from the NHL breakout model's held-out (leave-target-season-out) predictions,
   0 + flag when he has no breakout row (most rookies) — run only if the breakout pull rebuilds
4. age (age on the season file)
5. pwar0: last season's published WAR (preseason value prior; 0 for none)

Hart, Norris, Vezina (each):
6. pwar0: last season's published WAR (Vezina: last season's GSAx)
7. pm: plus/minus (Hockey-Reference)
8. prevvote: last season's vote share in the same award (votes / max votes, 0 if none)
9. title: stat-title leader dummy (Hart: Art Ross or Rocket Richard leader; Norris: points leader among D;
   Vezina: wins leader among goalies)
10. trank: team points % rank in the league (1 = best), the team-success variant
11. gp share for Norris and Vezina (gfrac; Hart already has it)

Calder also takes 7, 10.

FV and BO% are point-in-time only (draft grade from before the season, BO% predicted from the season before without
refitting on the tested season's outcomes). Nothing from after the vote.

## C. Awards -> FV (hockey prospects)

Driver: the Calder voter model's held-out P(win) is not available before a prospect's NHL season; the testable
award-model output for prospects is a junior-award signal. Hockey prospects drafted players' CHL award wins (CHL
Player / Rookie of the Year from the HockeyTech feeds) are not in the frozen rows, so the test is: the Calder model's
season-end P(top 3) for a pick in his first NHL season as an extra input to the stage-k FV of picks still on the
pipeline (class-out rule of scripts/hockey_fv_drivers.py: t >= 2, 8/12 classes, top-64 and forward checks). Run only if
the stage rows rebuild from scripts/data/hockey_rows.json.gz.
