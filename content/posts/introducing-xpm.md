+++
title = "Introducing XPM: Predictiveness, Stability, & Formulation Process"
date = "2026-11-24T14:00:42-05:00"
author = "arkndjl"
authorTwitter = "ARKNDJL" #do not include @
tags = ["nba", "statistics"]
keywords = ["xpm", "rxpm", "pxpm", "stabilization", "plus-minus", "nba", "basketball", "statistics"]
description = "How XPM is built from BPM and DPM, how fast it stabilizes, and how rXPM (descriptive) and pXPM (predictive) compare with BPM, DPM, LEBRON, RAPM, HAPM and on/off."
showFullContent = false
readingTime = false
hideComments = true
draft = false
aliases = ["/posts/xpm-stabilization/"]
Toc = true
+++

XPM (Cross Plus-Minus) is an all-in-one NBA impact metric in points per 100 possessions over an average player. It comes in two versions, because "how good was he" and "how good will he be" are different questions:

- **rXPM** is descriptive: what a player did this season.
- **pXPM** is predictive: what he will do next season.

This piece covers how XPM is built, how fast it stabilizes, and how it compares with the public metrics. Among the metrics tested here (BPM, DPM, LEBRON, one-year RAPM, HAPM, on-court +/- and on/off), rXPM tracks a team's same-season net rating most closely, and pXPM best predicts next season, both for teams and for individual players.

## Formulation
### Inputs
XPM starts from two published metrics:

- **BPM** (Basketball Reference): a regression of plus-minus on box-score rates, team-adjusted so a team's players add up to its rating.
- **DPM** (databallr): a plus-minus model with a RAPM backbone and box-score priors.

They miss in different places. BPM only sees the box score, so it misses defense and off-ball value that never shows up in a stat line. DPM sees the lineup data, so it carries more of the noise that comes with plus-minus. Blending the two cancels some of each.

### Why a 50/50 blend
I tested the blend against each input alone, and against everything I could build on top of it, on 480 team-seasons (2011-26). Each player's rating from earlier seasons, times his actual minutes this season, predicts the team's net rating. Every metric gets the same calibration (scale, a replacement value and a rookie value), fit on training seasons only.

| Metric | Net rating RMSE (forward, 1-yr prior) | Net rating RMSE (leave one season out, 2-yr prior) | r with W% |
| :--- | :---: | :---: | :---: |
| **BPM/DPM 50/50 blend** | **3.016** | 2.931 | **.811** |
| Blend + box-score ridge correction | 3.028 | 2.915 | .807 |
| Blend with team-anchored defense | 3.027 | 2.927 | .806 |
| BPM | 3.033 | 2.947 | .805 |
| DPM | 3.106 | 2.960 | .800 |
| Own box + on/off ridge model | 3.214 | 2.963 | .777 |

*Points per 100 possessions. Head-to-heads use a season-block bootstrap (4,000 draws).*

- **The blend beats both inputs.** The chance DPM alone is better is .005 to .007, and for BPM alone .08 to .29.
- **Nothing built on top of it holds up.** A ridge model on box stats and on/off is clearly worse, because box and on/off data alone can't match DPM's RAPM backbone. A box-score correction on top of the blend shrinks to almost nothing. Freely fitted weights on OBPM, ODPM, DBPM and DDPM are noisier than a fixed 50/50. The two closest candidates are coin flips against the blend (P better .30 to .67).
- **The split itself.** On next-season player values, the blend that best predicts both next-season BPM and next-season DPM is 40 to 50% BPM (average r .757 at 40%, .756 at 50%). DPM is better at predicting a player's own next season; BPM is better at matching team totals; 50/50 is where they meet.

Offense and defense are blended the same way: **O-XPM = .5 OBPM + .5 ODPM** and **D-XPM = .5 DBPM + .5 DDPM**. A player with no DPM row gets BPM alone.

### rXPM: the team adjustment
**rXPM** = the blend + a team adjustment, the same idea BPM uses. Every player on a team moves by one amount on offense and one on defense, so that:

- 5 × (minutes-weighted O-XPM) = team ORtg − league ORtg
- 5 × (minutes-weighted D-XPM) = league DRtg − team DRtg

A player traded mid-season takes each team's adjustment in proportion to his minutes there. The adjustment moves credit toward players on teams that really were better than their box scores, and it improves next-season prediction as well as same-season fit (below).

### pXPM: from rXPM to a projection
**pXPM** = (200 × μ + MP × XPM + .35 × MP₋₁ × XPM₋₁ + .1 × MP₋₂ × XPM₋₂) / (200 + MP + .35 × MP₋₁ + .1 × MP₋₂) + aging

- **This season and the two before**, weighted by minutes at 1 / .35 / .1.
- **A shrink of 200 minutes** toward a role mean, μ = −2 + ln(1 + MP82 / 100), where MP82 is minutes on an 82-game pace. A 300-minute player starts well below average and a 2,500-minute player a little above it.
- **Aging**: the average change in XPM from one season to the next at the player's next age, a quadratic in age weighted by the harmonic mean of the two seasons' minutes, fit only on seasons before the one being projected.

pXPM is built on the blend before the team adjustment. Putting the adjustment inside pXPM raises its team R² (.657 to .670) but worsens its next-season player error (1.185 to 1.198), and the player error is the target pXPM is fit to. Every pXPM setting was picked on next season's player XPM, one season held out at a time (2011-26). Why the shrink is 200 minutes comes out of the stability study, in "From Padding To pXPM" below.

## Stability
Every number on a stat sheet is part signal and part noise. A player's true talent is the signal; the bounces, the opponents, the hot week from three and the cold week at the rim are the noise. Early in a season the noise wins, and late in a season the signal wins. So before quoting any number, the question is how many games it takes before it says more about the player than about the sample.

Baseball has had an answer to this for over a decade. Russell Carleton's work on stat reliability showed that strikeout rate tells you something real after about 60 plate appearances, while BABIP needs closer to 800 balls in play. Hockey followed with Blackport's work on shot metrics. Basketball has lagged behind, and the plus-minus family of metrics has lagged the most. LumaHoops just put out a [working paper on the stabilization of NBA plus-minus metrics](https://lumahoops.org/research/stabilization-of-nba-plus-minus-metrics) that measures this for on-court +/-, WOWY, RAPM, BPM and their own models. The stability sections below run the same tests on XPM.

### The Method
I used the same split-half approach as Carleton and LumaHoops. For each team, take its first 2k games of the season. Split them into odd games and even games, so each half has k games. Compute a player's value on the odd half and on the even half, and correlate the two across every player in the league. If a stat is mostly talent, a player who is good on odd nights will also be good on even nights, and the correlation is high. If a stat is mostly noise, the two halves won't agree.

The thresholds follow the LumaHoops paper:

| r | Meaning |
| :---: | :--- |
| .50 | **Provisionally stable**: signal and noise carry equal weight |
| .75 | **Stable**: signal is three times the noise |

The .50 point has a second, more useful meaning. It is the "padding": the amount of league-average performance you add to a player's line to regress him properly. At .50, a player's own numbers and the league average deserve equal weight, so a stat should be shrunk halfway to average. It is also the natural shrink for a projection, which is where pXPM comes in.

To get the number of games to .50, I used the Spearman-Brown relationship, r(k) = k / (k + M), where M is the padding in games, and took the median M across windows of 10 to 41 games per half.

The sample is every regular season from 2013-14 to 2025-26, leaving out the shortened 2019-20 and 2020-21 seasons, from ESPN box lines. A player needs 5+ minutes per team game in each half (about 10 possessions, the same bar LumaHoops uses), which gives roughly 3,400 to 4,100 player-seasons per window.

**Box XPM** is the game-level version of XPM. The published XPM blends Basketball Reference's BPM with DPM and only exists for a full season, so for single games I use a ridge fit of season XPM on per-48 box rates (relative to the league), with the weights fit only on seasons before the one being measured. Nothing in it knows the future.
### How Fast Does XPM Stabilize?

| Metric | Games to .50 (90% CI) | Minutes | Possessions | Games to .75 |
| :--- | :---: | :---: | :---: | :---: |
| **Box XPM** | **14** (13 to 14) | 230 | 490 | 41 |
| On-court +/- | 28 (25 to 32) | 480 | 1,000 | 84 |

*Intervals come from 2,000 resamples of seasons. Possessions use the league's 2.07 possessions per player-minute.*

XPM is provisionally stable after about 14 games, or roughly 230 minutes. Raw on-court +/- needs twice that, 28 games, because it carries the noise of nine other players on the floor on top of the player's own.

The on-court number is also a check on the method. LumaHoops found 30 games (1,320 possessions) for on-court +/- on almost the same seasons, and I get 28. For box metrics they found BPM stable at 10 games and 450 possessions, and box XPM lands at 14 games and 490 possessions, right next to it. Two different pipelines, the same answer.

Here is the split-half correlation by window:

| Games per half | 5 | 10 | 15 | 20 | 25 | 30 | 41 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Box XPM** | .30 | .46 | .54 | .60 | .64 | .68 | .71 |
| On-court +/- | .20 | .31 | .37 | .43 | .46 | .50 | .56 |

{{< postchart "xpm-splithalf" >}}


One thing jumps out. Spearman-Brown says XPM should reach .75 at 41 games per half, which is a full 82-game season, but it actually tops out at .71. The implied padding creeps up as the window grows (12 games at k = 10, 17 at k = 41). That is not noise; that is real change. Players get hurt, change roles, get traded and get better inside a single season, so the halves drift apart a little faster than pure sampling would predict. Within one season, XPM never quite reaches "stable." It gets to "mostly signal."
### The Box Score, Stat By Stat
XPM is a weighted sum of box score rates, so the next question is, which of those rates are carrying the signal?

| Stat | Games to .50 | Minutes | Games to .75 |
| :--- | :---: | :---: | :---: |
| 3PA rate (3PA / FGA) | 1 | 10 | 2 |
| AST/48 | 2 | 30 | 6 |
| PTS/48 | 3 | 50 | 9 |
| OREB/48 | 3 | 50 | 9 |
| DREB/48 | 3 | 50 | 9 |
| BLK/48 | 5 | 80 | 14 |
| TOV/48 | 8 | 140 | 25 |
| PF/48 | 8 | 140 | 25 |
| **Box XPM** | **14** | **230** | **41** |
| STL/48 | 18 | 310 | 53 |
| On-court +/- | 28 | 480 | 84 |
| TS% | 31 | 540 | 93 |

{{< postchart "xpm-stats" >}}


The box score splits cleanly into two groups.

**Role stats stabilize almost immediately.** Shot diet (3PA rate), assists, scoring volume and rebounding are mostly decided by what a coach asks a player to do, so they are stable inside a week. A center rebounds like a center from game one.

**Skill-in-outcome stats take months.** Steals need 18 games, and shooting efficiency (TS%) needs 31, more than raw on-court +/-. That is the basketball version of BABIP: whether the ball goes in is a real skill, but it is buried under a lot of variance in a small sample.

XPM sits in between, at 14 games, because it combines both groups. It gets its early stability from the role stats and its value from the efficiency stats. That is also why one hot shooting month can move a player's rXPM a lot, and why pXPM exists.
## How Descriptive And Predictive Is XPM?
Stability is only half of the question. A stat can be perfectly stable and still not matter (a player's height is very stable), so the other half is whether the number actually tracks winning. I copied the setup of the LumaHoops paper's describe/predict test:

**Describe**: a player's season value × his share of his team's minutes (× 5), summed over the roster, against the team's net rating that same season.

**Predict**: the same thing, but with this season's values and next season's minutes, against next season's net rating. That is the real test: who you have, valued by what they did last year, against how good the team is next year. Players with no value from the year before (rookies, players coming back) get the metric's average for low-minute players.

Every metric gets the same nine season pairs (2013-14 to 2014-15 through 2024-25 to 2025-26, skipping the shortened 2019-20 and 2020-21), with no refitting. RAPM's public history stops in 2022-23, so it only has seven pairs.

| Metric | Describe R² | Predict R² (90% CI) | P(better than rXPM) |
| :--- | :---: | :---: | :---: |
| **pXPM** | .922 | **.657 (.63 to .70)** | .75 |
| **rXPM** | **.999** | .647 (.60 to .70) | |
| BPM | .988 | .644 (.61 to .69) | .38 |
| DPM | .875 | .623 (.58 to .67) | .03 |
| LEBRON | .898 | .599 (.56 to .64) | .03 |
| RAPM (1-yr) | .987 | .569 (.53 to .62) | |
| HAPM (1-yr) | .767 | .563 (.52 to .61) | .00 |
| On-court +/- | .994 | .481 (.42 to .55) | .00 |
| On/off | .239 | .373 (.32 to .43) | .00 |

*90% intervals and P(better) come from 2,000 resamples of season pairs, with every metric scored on the same resamples. pXPM's settings were picked on next season's player XPM and never on this test; with its settings refit on the other seasons, it scores .654.*

{{< postchart "xpm-predict" >}}

A few things to note here:

**rXPM is the best descriptive metric.** It describes its own season at .999, ahead of on-court +/- (.994), one-year RAPM (.987) and BPM (.988). Be clear about why: the team adjustment makes a team's rXPM add up to its net rating, so a near-perfect describe score is built in, the same way it is for BPM and on-court +/-. Without the adjustment, the BPM/DPM blend describes at .963. A high describe score on its own proves nothing, which is why the predict column matters.

**The adjustment also predicts better.** Adding it moves rXPM's next-season R² from .640 to .647, better in 97% of resamples. So the adjustment isn't just forcing the sum to match; it moves credit toward the players on teams that really were better than their box scores. That puts rXPM above BPM (.644) and DPM (.623), though rXPM vs BPM is still close to a coin flip (BPM wins 38% of resamples).

**pXPM is the best predictive metric.** At .657 it is first in the table, ahead of rXPM, BPM, DPM, LEBRON, RAPM, HAPM and every on/off measure. It isn't a blowout at the team level (it beats rXPM in 75% of resamples), but on its own target, one player's next season, the gap is large (below).

**Describing is easy, predicting is not.** On-court +/- describes its own season almost perfectly (.994) because team net rating is literally the minutes-weighted sum of its players' on-court numbers, and then it drops to .48 predicting the next one, behind every box-based metric. The stats that need the most games to stabilize (on/off, on-court +/-, one-year RAPM) are also the worst at predicting. That is the same conclusion as the LumaHoops paper, from a different test and a different data set.

One caveat in XPM's favor: the LEBRON and HAPM histories were fit with later seasons available, so their past values have some hindsight baked in. XPM, BPM and DPM have none.
## From Padding To pXPM
pXPM shrinks by 200 minutes because that is what stabilization says the noise is worth.

The within-season padding above is **about 230 minutes**: at that point a player's own XPM and the average deserve equal weight. That covers sampling noise and nothing else. Going from one season to the next adds real change on top: aging, role changes, new teammates, injuries. You can measure that too. Season box XPM correlates at **r = .75** from one year to the next (2,427 player pairs, 500+ minutes in both seasons). Strip out the sampling noise, using the 230-minute padding, and the true-talent year-to-year correlation is about **.87**.

If you squeeze both of those into a single shrink, you get **.87 × MP / (MP + 230)**, which for a full-season player at 2,000 minutes is a weight of .78. A one-dial shrink with k = 600 gives the same weight (2,000 / 2,600 = .77), and that is exactly what a one-dial pXPM picks when you fit it: 600 in every held-out fold.

{{< postchart "xpm-shrink" >}}

But one dial is doing two jobs there, cleaning up noise and guessing at a year of change. The year of change isn't random. Most of it is age, and some of it shows up in the seasons before. Give aging and history their own pieces, and the shrink only has to cover sampling noise again. Fit that way, it lands at **200 minutes**, right at the 230-minute padding. All 15 held-out folds picked 200 and the full aging curve, and 9 of 15 picked every setting exactly as shipped.

| | Next-season RMSE | Next-season team R² |
| :--- | :---: | :---: |
| BPM | 1.95 | .644 |
| XPM box blend | 1.58 | .640 |
| DPM | 1.38 | .623 |
| One-dial pXPM (k 600) | 1.24 | .619 |
| **pXPM** | **1.19** | **.654** |

*Next season's XPM, 2011-26, leave one season out. Team R² for pXPM is held out.*

{{< postchart "xpm-rmse" >}}


pXPM beats the one-dial version in 14 of 15 seasons (paired t = −7.3), on both tests at once. The gap is biggest for small samples: a player under 100 minutes has a raw next-season error above 7 points.

Which piece is doing the work? Turning each one off:

| Without | Next-season RMSE | Next-season team R² |
| :--- | :---: | :---: |
| nothing (pXPM) | 1.185 | .657 |
| aging | 1.250 | .633 |
| the two seasons before | 1.238 | .661 |
| the steeper role mean | 1.187 | .648 |
| the 200-minute shrink (600 instead) | 1.223 | .654 |

Aging is the biggest piece by far, on both tests. History helps one player's projection but not the team sum, probably because the team test already knows next season's minutes, which carry a lot of the same information. The steeper role mean mostly matters for the team test, where it stops low-minute players from looking like average ones.
## What Doesn't Work
| Test | Result |
| :--- | :--- |
| Separate shrink for offense and defense | RMSE 1.2357 vs 1.2357, better in 6 of 15 seasons. **Fail.** |
| More BPM in the blend (rXPM) | Next-season player r peaks at 40 to 50% BPM (.757 vs .756 at 50/50). More BPM only helps the team test, by .001. **Fail.** |
| More BPM inside pXPM (.4 to .7) | At most +.001 team R², with a worse player error. **Fail.** |
| Team adjustment inside pXPM | Team R² .657 to .670, but next-season player error 1.185 to 1.198. **Fail** on pXPM's own target, so pXPM stays on the box blend. |

A separate shrink for O and D doesn't hold up, because both sides of XPM are already built from a mix of fast and slow stats. The steals and TS% noise is averaged in before the shrink happens. And 50/50 really is the right blend: DPM is better at predicting a player's own next season, BPM is better at matching team totals, and the even split is where the two meet.
## Summary
- **Formulation**: rXPM is a 50/50 BPM/DPM blend, offense and defense blended the same way, plus BPM's team adjustment. The blend beat each input and every stack, box model and fitted weighting built on top of it, on 480 team-seasons.
- **pXPM** is three seasons of the blend, weighted 1 / .35 / .1 by minutes, shrunk 200 minutes toward a role mean, plus aging.
- XPM is **provisionally stable after about 14 games** (230 minutes, 490 possessions), twice as fast as on-court +/- (28 games) and in line with BPM in the LumaHoops paper. Inside one season it tops out at **.71** split-half reliability.
- **Role stats** (shot diet, assists, rebounding, scoring volume) stabilize in under a week. **Efficiency** (TS%, 31 games) and **steals** (18) are where the noise lives.
- **rXPM is the most descriptive of the metrics tested** (same-season team net R² .999, ahead of on-court +/- .994 and BPM .988), and it predicts next season better than BPM, DPM, LEBRON, RAPM and HAPM.
- **pXPM is the most predictive of the metrics tested**: next-season team net R² .657 (.654 held out) and next-season player error 1.19, against 1.38 for DPM, 1.58 for the raw blend and 1.95 for BPM.
- pXPM's **200-minute shrink matches the 230-minute stabilization point**. Aging and the two seasons before carry the year-to-year change, and aging is the biggest single piece.

**Works Cited**
Awoyemi, A. (2026). Stabilization of NBA Plus-Minus Metrics (Working paper v1). LUMA Basketball Research. [https://lumahoops.org/research/stabilization-of-nba-plus-minus-metrics](https://lumahoops.org/research/stabilization-of-nba-plus-minus-metrics)

Carleton, R. (2012). Baseball Therapy: It's a Small Sample Size After All. *Baseball Prospectus*.

Blackport, D. (2014). Shot metric reliability. *Hockey-Graphs*.

Medvedovsky, K. (2020). On-court plus-minus padding (as cited in Awoyemi, 2026).

Data: ESPN box scores; Basketball Reference (BPM, on-court and on/off); DPM; LEBRON (BBall Index via nbarapm.com); one-year RAPM (gabriel1200); HAPM (LumaHoops, CC BY 4.0). Code ([github.com/arkndjl/website](https://github.com/arkndjl/website)): `scripts/nba_xpm_stability_research.py`, `scripts/nba_xpm_predictive_research.py`, `scripts/nba_rxpm_research.py`, `scripts/nba_pxpm_research.py`.
