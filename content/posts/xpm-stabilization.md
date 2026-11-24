+++
title = "When Does XPM Stabilize?"
date = "2026-11-24T14:00:42-05:00"
author = "arkndjl"
authorTwitter = "ARKNDJL" #do not include @
tags = ["nba", "statistics", "arkboard"]
keywords = ["xpm", "pxpm", "stabilization", "nba", "basketball", "statistics", "arkboard"]
description = "How many games it takes for XPM, on-court plus-minus and every box score rate to stabilize, how XPM predicts next season against other metrics, and how a rebuilt pXPM became the best predictor on the board."
showFullContent = false
readingTime = false
hideComments = true
draft = false
Toc = true
+++

## Why Stabilization Matters
Every number on a stat sheet is part signal and part noise. A player's true talent is the signal; the bounces, the opponents, the hot week from three and the cold week at the rim are the noise. Early in a season the noise wins, and late in a season the signal wins. The question every analyst should be asking before they quote a number is, how many games does it take before this stat says more about the player than it does about the sample?

Baseball has had an answer to this for over a decade. Russell Carleton's work on stat reliability showed that strikeout rate tells you something real after about 60 plate appearances, while BABIP needs closer to 800 balls in play. Hockey followed with Blackport's work on shot metrics. Basketball has lagged behind, and the plus-minus family of metrics has lagged the most. LumaHoops just put out a [working paper on the stabilization of NBA plus-minus metrics](https://lumahoops.org/research/stabilization-of-nba-plus-minus-metrics) that measures this for on-court +/-, WOWY, RAPM, BPM and their own models. It is a great read, and it made me want to run the same test on XPM, the all-in-one metric behind ARKBOARD NBA.

In this article, I wanted to answer four questions:
1. How many games does XPM need before it is stable?
2. Which parts of the box score stabilize fast, and which parts are mostly noise?
3. How does XPM compare to other metrics at predicting next season?
4. Does the answer change how we shrink XPM into pXPM, and can pXPM be made the most predictive metric of all?

## The Method
I used the same split-half approach as Carleton and LumaHoops. For each team, take its first 2k games of the season. Split them into odd games and even games, so each half has k games. Compute a player's value on the odd half and on the even half, and correlate the two across every player in the league. If a stat is mostly talent, a player who is good on odd nights will also be good on even nights, and the correlation is high. If a stat is mostly noise, the two halves won't agree.

The thresholds follow the LumaHoops paper:

| r | Meaning |
| :---: | :--- |
| .50 | **Provisionally stable**: signal and noise carry equal weight |
| .75 | **Stable**: signal is three times the noise |

The .50 point has a second, more useful meaning. It is the "padding": the amount of league-average performance you add to a player's line to regress him properly. At .50, a player's own numbers and the league average deserve equal weight, so a stat should be shrunk halfway to average. That is exactly the dial that sets pXPM.

To get the number of games to .50, I used the Spearman-Brown relationship, r(k) = k / (k + M), where M is the padding in games, and took the median M across windows of 10 to 41 games per half.

The sample is every regular season from 2013-14 to 2025-26, leaving out the shortened 2019-20 and 2020-21 seasons, from ESPN box lines. A player needs 5+ minutes per team game in each half (about 10 possessions, the same bar LumaHoops uses), which gives roughly 3,400 to 4,100 player-seasons per window.

**Box XPM** is the game-level version of XPM. The published XPM blends Basketball Reference's BPM with DPM and only exists for a full season, so for single games I use a ridge fit of season XPM on per-48 box rates (relative to the league), with the weights fit only on seasons before the one being measured. Nothing in it knows the future.

## How Fast Does XPM Stabilize?

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

## The Box Score, Stat By Stat
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

## How Predictive Is XPM?
Stability is only half of the question. A stat can be perfectly stable and still not matter (a player's height is very stable), so the other half is whether the number actually predicts winning. I copied the setup of the LumaHoops paper's describe/predict test:

**Describe**: a player's season value × his share of his team's minutes (× 5), summed over the roster, against the team's net rating that same season.

**Predict**: the same thing, but with this season's values and next season's minutes, against next season's net rating. That is the real test: who you have, valued by what they did last year, against how good the team is next year. Players with no value from the year before (rookies, players coming back) get the metric's average for low-minute players.

Every metric gets the same nine season pairs (2013-14 to 2014-15 through 2024-25 to 2025-26, skipping the shortened 2019-20 and 2020-21), with raw values and no refitting. RAPM's public history stops in 2022-23, so it only has seven pairs.

| Metric | Describe R² | Predict R² (90% CI) | vs rXPM | P(better than rXPM) |
| :--- | :---: | :---: | :---: | :---: |
| **pXPM** | **.922** | **.657 (.63 to .70)** | **+.017** | **.88** |
| BPM | .988 | .644 (.61 to .69) | +.004 | .63 |
| rXPM | .963 | .640 (.59 to .69) | | |
| DPM | .875 | .623 (.58 to .67) | −.018 | .08 |
| LEBRON | .898 | .599 (.56 to .64) | −.039 | .07 |
| RAPM (1-yr) | .987 | .569 (.53 to .62) | | |
| HAPM (1-yr) | .767 | .563 (.52 to .61) | −.076 | .01 |
| On-court +/- | .994 | .481 (.42 to .55) | −.160 | .00 |
| On/off | .239 | .373 (.32 to .43) | −.268 | .00 |

*90% intervals and P(better) come from 2,000 resamples of season pairs, with every metric scored on the same resamples. pXPM is the rebuilt version (below); held out one season at a time, it scores .654. The old pXPM scored .619.*

{{< postchart "xpm-predict" >}}

A few things to note here:

**Describing is easy, predicting is not.** On-court +/- describes its own season almost perfectly (.994) because team net rating is literally the minutes-weighted sum of its players' on-court numbers. BPM is near-perfect for a similar reason: it is adjusted to add up to the team's rating. Neither of those tells you much. The predict column is the one that matters, and there on-court +/- drops to .48, behind every box-based metric.

**XPM is at the top of the board.** rXPM predicts next season's team net rating at R² .64, ahead of LEBRON, one-year RAPM, HAPM and every on/off measure. BPM ties it (+.004, better in 63% of resamples, which is a coin flip), so XPM's blend of BPM and DPM isn't buying anything at the team level.

**pXPM is now first.** The first time I ran this, the old pXPM came in at .619, behind rXPM, BPM and DPM. That bothered me, because pXPM is the one that is supposed to predict. So I rebuilt it (next section), and the new pXPM predicts next season's team net rating at **.657**, ahead of BPM and rXPM. To be honest about the size of the win: it beats rXPM in 88% of resamples and BPM in 90%, so it is the best number here, but not by a mile.

**Plus-minus metrics stabilize slowly and predict worse.** The ranking from the stabilization section carries straight through: the stats that need the most games to stabilize (on/off, on-court +/-, one-year RAPM) are also the worst at predicting. That is the same conclusion as the LumaHoops paper, from a different test and a different data set.

One caveat in XPM's favor: the LEBRON and HAPM histories were fit with later seasons available, so their past values have some hindsight baked in. XPM, BPM and DPM have none, and they still come out on top.

## From Padding To pXPM
The old pXPM was XPM shrunk by minutes:

**old pXPM** = μ + (rXPM − μ) × MP / (MP + 600)

where μ is a role mean, moving toward the player's own history when he has one. The within-season padding above is **about 230 minutes**, so why was the shrink more than twice the padding?

Because pXPM isn't predicting the other half of the same season; it predicts next season. The 230 minutes only covers sampling noise. Going from one season to the next adds real change on top: aging, role changes, new teammates, injuries. You can measure that directly. Season box XPM correlates at **r = .75** from one year to the next (2,427 player pairs, 500+ minutes in both seasons). Strip out the sampling noise, using the 230-minute padding, and the true-talent year-to-year correlation is about **.87**. Combining the two:

**shrink weight** = .87 × MP / (MP + 230)

For a full-season player at 2,000 minutes, that comes to a weight of .78, the same weight k = 600 gives (2,000 / 2,600 = .77). So the old k of 600 was the 230-minute stabilization point plus the drift of a year, all folded into one dial.

{{< postchart "xpm-shrink" >}}


## Making pXPM The Most Predictive
That last line is also the problem. One dial was doing two jobs: cleaning up sampling noise and guessing at a year of change. The year of change isn't random, though. Most of it is age, and some of it is the seasons before this one. So the new pXPM splits the jobs up:

**pXPM** = (200 × μ + MP × XPM + .35 × MP₋₁ × XPM₋₁ + .1 × MP₋₂ × XPM₋₂) / (200 + MP + .35 × MP₋₁ + .1 × MP₋₂) + aging

- **This season and the two before**, weighted by minutes at 1 / .35 / .1 (Marcel-style).
- **A shrink of 200 minutes** toward the role mean. That is right at the 230-minute padding from the split-half study: once aging and history are handled on their own, the shrink only has to cover sampling noise, which is exactly what stabilization measures.
- **Aging**: the average change in XPM from one season to the next at the player's next age, fit only on seasons before the one being projected.
- **A steeper role mean**: μ = −2 + ln(1 + MP82 / 100), so a 300-minute player starts lower than before and a 2,500-minute player a little higher.

Every setting was picked on next season's XPM with one season held out at a time (2011-26), and the team test above was never used to pick anything. Nine of 15 folds picked exactly the shipped settings, and all 15 picked k = 200 and the full aging curve.

| | Next-season RMSE | Team net R² |
| :--- | :---: | :---: |
| BPM | 1.95 | .644 |
| rXPM (raw) | 1.58 | .640 |
| DPM | 1.38 | .623 |
| old pXPM (k 600) | 1.24 | .619 |
| **new pXPM (held out)** | **1.19** | **.654** |

{{< postchart "xpm-rmse" >}}


The new pXPM beats the old one in 14 of 15 seasons (paired t = −7.3) and wins on both tests at once. Which piece is doing the work? Turning each one off:

| Without | Next-season RMSE | Team net R² |
| :--- | :---: | :---: |
| nothing (new pXPM) | 1.185 | .657 |
| aging | 1.250 | .633 |
| the two seasons before | 1.238 | .661 |
| the steeper role mean | 1.187 | .648 |
| the 200-minute shrink (k 600 instead) | 1.223 | .654 |

Aging is the biggest piece by far, on both tests. History is the piece that helps one player's projection but not the team sum (probably because the team test already knows next season's minutes, which carry a lot of the same information). The steeper role mean mostly matters for the team test, where it stops low-minute players from looking like average ones.

## What I Tested And What Failed
| Test | Result |
| :--- | :--- |
| Old pXPM: k grid extended to 2,000 | Every fold still picked **600**. A true optimum for a one-dial shrink. |
| Separate k for offense and defense | No gain: RMSE 1.2357 vs 1.2357, better in 6 of 15 seasons. **Fail.** |
| Weighting BPM above DPM inside pXPM (.4 to .7 BPM) | At most +.001 team R², with a worse player error. **Fail.** |
| Aging in hockey's projection (NHL pWAR) | Better at one player's next season, worse at next season's team goal differential. **Fail**, not shipped. |

A separate shrink for O and D doesn't hold up, because both sides of XPM are already built from a mix of fast and slow stats. The steals and TS% noise is already averaged in before the shrink happens. And the aging fix didn't carry over to hockey: NHL pWAR is fit to team goal differential, and adding an aging curve made that worse at every weight I tried.

## So, To Summarize
- XPM is **provisionally stable after about 14 games** (230 minutes, 490 possessions), twice as fast as on-court +/- (28 games) and in line with BPM in the LumaHoops paper.
- Inside one season, XPM tops out at **.71** split-half reliability: mostly signal, never fully stable, because players really do change in-season.
- **Role stats** (shot diet, assists, rebounding, scoring volume) stabilize in under a week. **Efficiency** (TS%, 31 games) and **steals** (18) are where the noise lives.
- On next season's team net rating, **rXPM (R² .64) ties BPM and beats DPM, LEBRON, RAPM, HAPM, on-court +/- and on/off**. Describing a season is easy; predicting the next one is where plus-minus falls off.
- The old pXPM's k = 600 was the 230-minute stabilization point plus a year of real change. Splitting that year out into **aging and the two seasons before** lets the shrink drop to **200 minutes**, right at the padding.
- The rebuilt **pXPM is now the most predictive metric here on both tests**: next-season player error 1.19 (old 1.24, raw 1.58) and next-season team net R² .654 held out (BPM .644, rXPM .640).

The practical rule: rXPM is what a player did. pXPM is the best guess at what he does next.

**Works Cited**
Awoyemi, A. (2026). Stabilization of NBA Plus-Minus Metrics (Working paper v1). LUMA Basketball Research. [https://lumahoops.org/research/stabilization-of-nba-plus-minus-metrics](https://lumahoops.org/research/stabilization-of-nba-plus-minus-metrics)

Carleton, R. (2012). Baseball Therapy: It's a Small Sample Size After All. *Baseball Prospectus*.

Blackport, D. (2014). Shot metric reliability. *Hockey-Graphs*.

Medvedovsky, K. (2020). On-court plus-minus padding (as cited in Awoyemi, 2026).

Data: ESPN box scores; Basketball Reference (BPM, on-court and on/off); DPM; LEBRON (BBall Index via nbarapm.com); one-year RAPM (gabriel1200); HAPM (LumaHoops, CC BY 4.0). Study scripts: `scripts/nba_xpm_stability_research.py`, `scripts/nba_xpm_predictive_research.py`, `scripts/nba_pxpm_research.py`.
