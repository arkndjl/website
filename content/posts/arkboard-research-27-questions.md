+++
title = "27 Strategy Questions, Answered"
date = "2026-11-02T18:00:00-05:00"
author = "arkndjl"
authorTwitter = "ARKNDJL" #do not include @
tags = ["arkboard", "research", "nfl", "nba", "cbb", "nhl", "mlb", "soccer", "tennis", "cs2"]
keywords = ["arkboard", "research", "4th down", "two-point conversion", "qb sneak", "onside kick", "foul up 3", "2-for-1", "free throw icing", "goalie pull", "stolen bases", "intentional walk", "sacrifice bunt", "times through the order", "xg", "game state", "second serve", "serve direction", "pistol round", "cs2 economy", "win probability"]
description = "Every study on the ARKBOARD Reference page: 27 strategy questions in the NFL, NBA, college basketball, NHL, MLB, soccer, tennis and CS2. The question, the answer, the key number with its 95% CI and sample, and how it was tested."
showFullContent = false
readingTime = false
hideComments = true
Toc = true
draft = false
+++

{{< card url="/arkboard/reference/" title="ARKBOARD Reference" >}}
Research, glossary and methodology, data sources.
{{< /card >}}

The Research tab on [Reference](/arkboard/reference/) answers one strategy question per study with play-by-play data. This post collects all 27 as of November 2, 2026: the question, the answer, the key number with its 95% confidence interval and sample size, and a link to the study on Reference, where each one has its chart.

Each study compares decisions from the same game state (score, time, field position, count, economy), so the teams that choose an option aren't just better teams. Every number carries its n, and CIs are clustered by game or match where plays repeat. Each result is also checked on two halves of the sample, usually earlier and later seasons. Five of the 27 don't pass that check or have a CI that includes zero; they're marked below and kept, since a null answer is still an answer.

Every study has a **GFX card** button that draws a 16:9 card for X, and a **link** button. The short link for any study is arkndjl.net/reference#rq-&lt;id&gt;.


## Summary

Robust = the main CI excludes zero and the result holds in both halves of the sample.

| Study | Answer | Key number | Robust |
|---|---|---|---|
| [NFL 4th downs](/arkboard/reference/#rq-nfl-fourth-down) | In states where going gains 1+ WP point, teams went 25% of the time in 2015-16 and 45% in 2024-25. | 3.4 WP pts lost per team-game, 2024-25 | yes |
| [NFL down 14: go for two first](/arkboard/reference/#rq-nfl-down-14-go-for-two) | Yes. With two TDs and a stop, going for 2 first wins 59% vs 47% kicking. Teams went for 2 54% of the time in 2025-26. | +12.1 pts win chance, given two TDs | yes |
| [NFL surprise onside kicks](/arkboard/reference/#rq-nfl-onside-surprise) | Yes, 25% vs 9% (2015-23), but below the ~32% break-even for an early onside. Net WPA not different from zero. | 25% surprise onside recovered, 2015-23 | yes |
| [NFL QB sneak](/arkboard/reference/#rq-nfl-qb-sneak) | Yes. Sneaks convert 82%, other runs 69%, passes 56%. Sneak share of these plays was 8% in 2015, 14% in 2025. | +12.5 pts conversion, sneak vs other runs | yes |
| [NFL two-point tries](/arkboard/reference/#rq-nfl-two-point) | No clear edge. 2-pt tries score 0.96 points per try, XPs 0.94; difference +0.02 (-0.03 to +0.07). | +0.02 pts per try, 2-pt minus XP | no |
| [NBA up 3: foul or defend](/arkboard/reference/#rq-nba-foul-up-3) | No clear edge: leader wins 92.7% fouling, 91.4% defending; +2.3 pp at equal time (CI -2.4 to +6.4). | +2.3 pp leader win, foul minus defend | no |
| [NBA timeout after a run](/arkboard/reference/#rq-nba-timeout-after-run) | No: after an 8+ pt run, a timeout nets -0.31 pts over the next 2:00 vs playing on (CI -0.40 to -0.23). | -0.31 pts next 2:00, timeout vs play on | yes |
| [NBA 2-for-1](/arkboard/reference/#rq-nba-two-for-one) | Yes: quick shot nets +0.33 pts per quarter-end vs a full possession (CI +0.26 to +0.39). | +0.33 pts per quarter end, quick vs full | yes |
| [CBB up 3: foul or defend](/arkboard/reference/#rq-cbb-foul-up-3) | Foul: leader wins 93.6% fouling, 92.4% defending; +2.8 pp at equal time (CI +0.8 to +4.6). | +2.8 pp leader win, foul minus defend | yes |
| [CBB icing the shooter](/arkboard/reference/#rq-cbb-ft-icing) | Icing does not work: iced shooters +2.3 pp vs un-iced, relative to own FT% (CI +0.0 to +4.6). | +2.3 pp vs own FT%, iced minus not iced | yes |
| [NHL goalie pull](/arkboard/reference/#rq-nhl-goalie-pull) | Pull at 3:18 down one, 6:27 down two. Teams pull at 1:52 and 2:39. | 3:18 optimal pull, down 1 | yes |
| [NHL goalie pull on a power play](/arkboard/reference/#rq-nhl-pp-goalie-pull) | Yes with 3:00 or less left: 6v4 adds 8 pts of tie chance at 2:00. Past 4:00 the gain is not clear. | +8 pts tie chance, 6v4 at 2:00 | yes |
| [MLB stolen bases](/arkboard/reference/#rq-mlb-stolen-bases) | Slightly. Steals of 2nd succeed 75.9% vs 71.7% break-even, +2.6 runs per team-season. At 1 out, no edge. | 75.9% steal of 2nd success, 2023-25 | yes |
| [MLB intentional walks](/arkboard/reference/#rq-mlb-ibb) | Mostly no. Runner on 2nd, 1 out: IBB costs the defense 2.0 win-prob pts. Other states: no gain distinguishable from 0. | -2.0 WP pts, runner on 2nd, 1 out | yes |
| [MLB times through the order](/arkboard/reference/#rq-mlb-tto) | For an average starter, yes. 3rd time: +.022 wOBA vs 1st (same pitcher), .339 vs relievers .323. | +.022 wOBA, 3rd time vs 1st | yes |
| [MLB sacrifice bunts](/arkboard/reference/#rq-mlb-sac-bunt) | No. Bunt tries cost 0.3 to 0.9 win-prob pts per try vs swinging; late and close, up to 1.9. | -0.3 WP pts per try, runner on 1st | yes |
| [Soccer protecting a lead](/arkboard/reference/#rq-soccer-protecting-lead) | Yes after 75': xG share 46% vs 53% expected. Costs 0.05 xPts from 75', but actual points held. | 46% leader xG share after 75', expected 53% | yes |
| [Soccer after a goal](/arkboard/reference/#rq-soccer-after-conceding) | No momentum swing. Team that just conceded scores 0.95x baseline in the next 10 min; scorer 1.06x. Restart dips the first 3 min. | 0.95x goals by the conceding team, next 10 min | no |
| [Soccer first sub timing](/arkboard/reference/#rq-soccer-first-sub-timing) | Trailing teams sub first by 60', level and leading by 65'. A first sub before 60' adds +0.04 xG diff; no goal effect found. | +0.04 xG diff, first sub before 60' | no |
| [Tennis first serve on second serve](/arkboard/reference/#rq-tennis-second-serve-first-serve) | No. 6 of 188 men and 4 of 112 women would gain. Median player loses 6.8 pts (men), 5.3 (women) per 100. | 6 of 188 men who would gain | yes |
| [Tennis hold after breaking](/arkboard/reference/#rq-tennis-hold-after-break) | No. Same player and match: hold rate after breaking is +0.7 pts (men), +0.5 (women) vs after opponent holds. | +0.7 pts hold rate after breaking, men | yes |
| [Tennis serve direction](/arkboard/reference/#rq-tennis-serve-direction-mix) | Wide and T: yes, within 1 pt for the same server. Body: no, 4.2 pts lower (men), 4.1 (women). | -4.2 pts, body vs wide and T, men | yes |
| [CS2 pistol round](/arkboard/reference/#rq-cs2-pistol-value) | First pistol winner takes the map 59.5%: 57.1% on CT, 61.9% on T. | 61.9% map win, pistol 1 won on T | yes |
| [CS2 buy after losing the pistol](/arkboard/reference/#rq-cs2-pistol-loser-buy) | Buying on round 2: +26.8 pp in round 2, -16.5 pp in round 3, map win -0.8 pp (not different from 0). | -0.8 pp map win, buy vs save | no |
| [CS2 equipment gap](/arkboard/reference/#rq-cs2-equipment-gap) | Full buy vs full buy: CT wins 51.7%. At equal dollar value CT wins 48.5%; an eco beats a full buy 5.6%. | 51.7% CT round win, full buy vs full buy | yes |
| [CS2 losing streaks](/arkboard/reference/#rq-cs2-loss-streak) | No tilt. After 3+ straight losses a team wins +0.9 pp vs an economy and score model. | +1.1 pp vs model after 3 straight losses | yes |
| [CS2 starting side](/arkboard/reference/#rq-cs2-side-first) | Start T. T-first teams win 52.4% of maps; 55.8% on overpass, 50.0% on anubis. | 52.4% map win, T-first team | yes |

## Football

### NFL 4th downs

{{< rq id="nfl-fourth-down" sport="NFL" date="2026-11-02" q="When going for it on 4th down gains win probability, how often do NFL teams go?" a="In states where going gains 1+ WP point, teams went 25% of the time in 2015-16 and 45% in 2024-25." n="3.4" nl="WP pts lost per team-game, 2024-25" bars="2015:24.7|2017:24.7|2018:30.9|2020:40.3|2021:41.1|2023:39.9|2024:41.9|2026:42.9" unit="%" note="n = 44,765 · go % by season (going gains 1+ WP pt)" >}}
**Key number.** 3.4 WP pts lost per team-game to clear go errors in 2024-25 (95% CI 3.2 to 3.7), down from 4.6 in 2015-16 (4.3 to 4.9). n = 44,765 4th-down plays, 3,148 games.

**Method.** Per play, expected WPA of go (pooled conversion rate x WPA if converted/failed) vs best of punt/FG, each from boosted models of nflverse WPA on the same pre-snap state, cross-fit by game. Teams' own choice does not set the rate. WP-lost CIs exclude model error.

**Holds up?** Model checks out of sample: realized WPA in go states, goers +1.3 vs kickers -1.3 pts (n=4,866/8,682); rise in go rate holds every season.

**Data.** nflverse play-by-play, 2015 to 2026 wk 8, Q1-Q4 4th downs (no penalties/kneels), 44,765 plays, 3,148 games.

[On Reference](/arkboard/reference/#rq-nfl-fourth-down)
{{< /rq >}}

### NFL down 14: go for two first

{{< rq id="nfl-down-14-go-for-two" sport="NFL" date="2026-11-02" q="Down 14 in the 4th, should a team go for two after the first touchdown?" a="Yes. With two TDs and a stop, going for 2 first wins 59% vs 47% kicking. Teams went for 2 54% of the time in 2025-26." n="+12.1" nl="pts win chance, given two TDs" bars="2015-16:0.0|2017-18:5.4|2019-20:27.8|2021-22:28.0|2023-24:36.1|2025-26:54.2" unit="%" note="n = 193 · go-for-2 % by seasons" >}}
**Key number.** +12.1 pts of win chance given two TDs and a stop (95% CI +9.7 to +14.4). n = 1,458 two-point tries, 14,618 extra points, 193 Q4 PATs at down 8.

**Method.** Closed-form win chance given two TDs and no opponent score, with pooled 2-pt and XP rates; CI from Beta draws of both rates. Go-for-2 share counts Q4 tries at down 8, Wilson CIs.

**Holds up?** Gain holds with 2015-20 rates (+11.7 pts) and 2021-26 rates (+12.3 pts).

**Data.** nflverse play-by-play, 2015 to 2026 wk 8; 193 Q4 PATs at down 8; 1,458 2-pt tries.

[On Reference](/arkboard/reference/#rq-nfl-down-14-go-for-two)
{{< /rq >}}

### NFL surprise onside kicks

{{< rq id="nfl-onside-surprise" sport="NFL" date="2026-11-02" q="Do surprise onside kicks get recovered more than expected late-game onside kicks?" a="Yes, 25% vs 9% (2015-23), but below the ~32% break-even for an early onside. Net WPA not different from zero." n="25%" nl="surprise onside recovered, 2015-23" bars="surprise 2015-17:32.1|surprise 2018-23:17.9|late, trailing 2015-17:10.9|late, trailing 2018-23:7.8|late, trailing 2024-26:6.3" unit="%" note="n = 691 · recovered % by seasons" >}}
**Key number.** 25.0% recovered (95% CI 15.5 to 37.7, n = 56) against 8.9% for expected onsides (6.7 to 11.6, n = 508). Break-even is about 32%. n = 691 onside kicks.

**Method.** Onside = kickoff described as onside. Expected = Q4 with the kicker trailing; surprise = all others. WPA compared with normal Q1-Q3 kickoffs within 14 points, game bootstrap CIs. Teams pick spots, so rates are upper bounds.

**Holds up?** Surprise recovery 28% in 2015-18 (n=32), 21% in 2019-23 (n=24); expected stays near 9%.

**Data.** nflverse play-by-play, 2015 to 2026 wk 8, 691 onside kicks.

[On Reference](/arkboard/reference/#rq-nfl-onside-surprise)
{{< /rq >}}

### NFL QB sneak

{{< rq id="nfl-qb-sneak" sport="NFL" date="2026-11-02" q="On 3rd or 4th and 1, does the QB sneak convert more often than other plays?" a="Yes. Sneaks convert 82%, other runs 69%, passes 56%. Sneak share of these plays was 8% in 2015, 14% in 2025." n="+12.5" nl="pts conversion, sneak vs other runs" bars="2015:79.7|2017:92.4|2018:89.4|2020:83.5|2021:78.2|2023:74.7|2024:82.7|2026:84.3" unit="%" note="n = 10,488 · converted % by season (QB sneak)" >}}
**Key number.** +12.5 pts conversion over other runs (95% CI +10.1 to +14.9). Sneaks 81.7% (79.5 to 83.7, n = 1,296). n = 10,488 3rd/4th-and-1 plays.

**Method.** Conversion = first down or TD. Same down and distance; reweighted to the sneak's mix of down and goal-line state gives 82/69/57%. Yards to go of 1 hides inches, so sneaks may get the shortest spots.

**Holds up?** 2015-20: sneak 85% (n=457) vs other run 68%; 2021-26: 80% (n=839) vs 70%.

**Data.** nflverse play-by-play, 2015 to 2026 wk 8, 3rd/4th-and-1 runs and passes, WP 5-95%, 10,488 plays.

[On Reference](/arkboard/reference/#rq-nfl-qb-sneak)
{{< /rq >}}

### NFL two-point tries

{{< rq id="nfl-two-point" sport="NFL" date="2026-11-02" q="Is a two-point try worth more than an extra point on average?" a="No clear edge. 2-pt tries score 0.96 points per try, XPs 0.94; difference +0.02 (-0.03 to +0.07)." n="+0.02" nl="pts per try, 2-pt minus XP" bars="2015:0.98|2017:0.813|2018:1.029|2020:0.923|2021:0.988|2023:1.106|2024:0.811|2026:1.123" unit="" note="n = 16,076 · points per try by season (two-point try)" >}}
**Key number.** +0.02 points per try for two-point tries over extra points (95% CI -0.03 to +0.07). n = 1,458 two-point tries, 14,618 extra points.

**Method.** Wilson 95% CIs on success rates; expected points = 2 x 2-pt rate vs XP rate. Tries in Q1-Q4, all game states; selection is small since 2-pt tries are mostly score-driven.

**Holds up?** 2-pt rate 47.6% in 2015-20 (n=706), 48.5% in 2021-26 (n=752); XP edge within noise in both.

**Data.** nflverse play-by-play, 2015 to 2026 wk 8, 1,458 two-point tries and 14,618 extra points.

[On Reference](/arkboard/reference/#rq-nfl-two-point)
{{< /rq >}}

## Basketball

### NBA up 3: foul or defend

{{< rq id="nba-foul-up-3" sport="NBA" date="2026-11-02" q="Up 3 in the last 12 seconds, should the leader foul or defend?" a="No clear edge: leader wins 92.7% fouling, 91.4% defending; +2.3 pp at equal time (CI -2.4 to +6.4)." n="+2.3" nl="pp leader win, foul minus defend" bars="2 s:100.0|6 s:94.0|10 s:89.9|14 s:93.2" unit="%" note="n = 1,804 · leader win % by seconds left at possession start (bin middle; 14 = started earlier, live at 12) (foul)" >}}
**Key number.** +2.3 pp for fouling at equal time (95% CI -2.4 to +6.4). n = 1,804 games, 219 fouls.

**Method.** First trailer possession per game that is live with 12 s or less, final regulation period, down 3. Foul = leader's non-shooting foul sending trailer to the line before any shot. Compared within possession-start bins (4-8, 8-12, 12+ s); outcome = game win incl. OT.

**Holds up?** Foul minus defend: -0.4 pp in 2012-19 (CI -10.0 to +7.4), +2.8 in 2020-26 (CI -2.9 to +7.7).

**Data.** ESPN play-by-play via sportsdataverse, NBA, 2011-12 to 2025-26, 1,804 games.

[On Reference](/arkboard/reference/#rq-nba-foul-up-3)
{{< /rq >}}

### NBA timeout after a run

{{< rq id="nba-timeout-after-run" sport="NBA" date="2026-11-02" q="Does a timeout stop an opponent run?" a="No: after an 8+ pt run, a timeout nets -0.31 pts over the next 2:00 vs playing on (CI -0.40 to -0.23)." n="-0.31" nl="pts next 2:00, timeout vs play on" bars="Q1:0.461|Q2:0.595|Q3:0.386|Q4:0.614" unit="" note="n = 33,103 · net points, next 2:00 by quarter (timeout)" >}}
**Key number.** -0.31 pts over the next 2:00 for a timeout after an 8+ pt run (95% CI -0.40 to -0.23). n = 33,103 runs, 16,242 games.

**Method.** Trigger = score making an unanswered run 8+ pts, >= 2:30 left in quarter, margin within 20. Timeout in that dead ball vs no timeout in next 60 s; net points next 120 s; matched on run size and quarter.

**Holds up?** Timeout minus none: -0.32 pts in 2012-19 (CI -0.44 to -0.22), -0.31 in 2020-26 (CI -0.42 to -0.19).

**Data.** ESPN play-by-play via sportsdataverse, NBA 2011-12 to 2025-26, 16,242 games, 33,103 runs.

[On Reference](/arkboard/reference/#rq-nba-timeout-after-run)
{{< /rq >}}

### NBA 2-for-1

{{< rq id="nba-two-for-one" sport="NBA" date="2026-11-02" q="With 25-40 seconds left in a quarter, does a quick shot for a 2-for-1 pay?" a="Yes: quick shot nets +0.33 pts per quarter-end vs a full possession (CI +0.26 to +0.39)." n="+0.33" nl="pts per quarter end, quick vs full" bars="2 s:0.897|5 s:0.749|9 s:0.442|11 s:0.35|13 s:0.347|15 s:0.323|19 s:0.413|22 s:0.327" unit="" note="n = 19,944 · net points (own minus opponent) by seconds used before first shot" >}}
**Key number.** +0.33 pts per quarter end for a quick shot (95% CI +0.26 to +0.39). n = 19,944 inbound possessions, 19,166 games.

**Method.** Q1-Q3, first possession starting 25-40 s left. Outcome = own minus opponent points to quarter end. Main sample = inbound after opponent score (no transition); quick vs full compared within 5 s start-time bins, game-clustered bootstrap.

**Holds up?** Quick minus full: +0.32 pts in 2012-19 (CI +0.24 to +0.41), +0.34 in 2020-26 (CI +0.24 to +0.43).

**Data.** ESPN play-by-play via sportsdataverse, NBA 2011-12 to 2025-26, 19,166 games, 19,944 inbound possessions.

[On Reference](/arkboard/reference/#rq-nba-two-for-one)
{{< /rq >}}

### CBB up 3: foul or defend

{{< rq id="cbb-foul-up-3" sport="CBB" date="2026-11-02" q="Up 3 in the last 12 seconds, should the leader foul or defend?" a="Foul: leader wins 93.6% fouling, 92.4% defending; +2.8 pp at equal time (CI +0.8 to +4.6)." n="+2.8" nl="pp leader win, foul minus defend" bars="2 s:93.4|6 s:94.3|10 s:92.6|14 s:93.7" unit="%" note="n = 7,116 · leader win % by seconds left at possession start (bin middle; 14 = started earlier, live at 12) (foul)" >}}
**Key number.** +2.8 pp for fouling at equal time (95% CI +0.8 to +4.6). n = 7,116 games, 1,063 fouls.

**Method.** First trailer possession per game that is live with 12 s or less, final regulation period, down 3. Foul = leader's non-shooting foul sending trailer to the line before any shot. Compared within possession-start bins (4-8, 8-12, 12+ s); outcome = game win incl. OT.

**Holds up?** Foul minus defend: +2.2 pp in 2012-19 (CI -0.6 to +4.8), +3.3 in 2020-26 (CI +0.7 to +5.8).

**Data.** ESPN play-by-play via sportsdataverse, CBB, 2011-12 to 2025-26, 7,116 games.

[On Reference](/arkboard/reference/#rq-cbb-foul-up-3)
{{< /rq >}}

### CBB icing the shooter

{{< rq id="cbb-ft-icing" sport="CBB" date="2026-11-02" q="Does a timeout before a late free throw make the shooter miss?" a="Icing does not work: iced shooters +2.3 pp vs un-iced, relative to own FT% (CI +0.0 to +4.6)." n="+2.3" nl="pp vs own FT%, iced minus not iced" bars="<65%:62.3|65-75%:71.3|75-85%:74.6|85%+:77.1" unit="%" note="n = 61,420 · made % by shooter FT% (other attempts) (iced)" >}}
**Key number.** +2.3 pp for iced shooters against their own FT% (95% CI +0.0 to +4.6). n = 61,420 late first free throws, 1,567 iced.

**Method.** First FT of a trip, last 2:00 of regulation or OT, margin within 3. Iced = defense timeout between foul and FT. Outcome = made minus shooter's leave-one-out FT% (min 20 other FTs); game-clustered bootstrap.

**Holds up?** Iced minus not iced: +2.0 pp in 2012-19 (CI -1.0 to +4.8), +2.5 in 2020-26 (CI -0.8 to +6.1).

**Data.** ESPN play-by-play via sportsdataverse, CBB, 2011-12 to 2025-26, 61,420 first free throws.

[On Reference](/arkboard/reference/#rq-cbb-ft-icing)
{{< /rq >}}

## Hockey

### NHL goalie pull

{{< rq id="nhl-goalie-pull" sport="NHL" date="2026-11-02" q="When should a trailing team pull its goalie?" a="Pull at 3:18 down one, 6:27 down two. Teams pull at 1:52 and 2:39." n="3:18" nl="optimal pull, down 1" bars="0 min:24.8|1 min:27.6|2 min:29.0|3 min:29.5|4 min:29.4|5 min:28.8|6 min:28.1|7 min:27.0" unit="%" note="n = 5,248 · level at 60:00 % by minutes left when pulled (down 1)" >}}
**Key number.** Optimum 3:18 left down 1 (95% CI 2:42 to 3:57), 6:27 down 2 (4:42 to 9:04). n = 5,248 games.

**Method.** Outcome: level or ahead at 60:00. Per-second Markov model on goal rates by state (6v5, 5v5 down 1/2, tied), game-cluster bootstrap CIs. Model matches observed: down 1 at 6:00, 22.5% predicted vs 24.4% observed (n=1,523).

**Holds up?** Optimum down 1: 3:10 in 2021-23, 3:26 in 2023-25. Median actual pull: 1:47 (2021-22) to 1:58 (2024-25).

**Data.** NHL API play-by-play + shift charts, regular seasons 2021-22 to 2024-25, 5,248 games; pull times from goalie shifts.

[On Reference](/arkboard/reference/#rq-nhl-goalie-pull)
{{< /rq >}}

### NHL goalie pull on a power play

{{< rq id="nhl-pp-goalie-pull" sport="NHL" date="2026-11-02" q="Should a team down one late pull its goalie on a power play?" a="Yes with 3:00 or less left: 6v4 adds 8 pts of tie chance at 2:00. Past 4:00 the gain is not clear." n="+8" nl="pts tie chance, 6v4 at 2:00" bars="1 min:19.2|2 min:31.2|3 min:34.2|4 min:35.9|5 min:37.0|6 min:37.6" unit="%" note="n = 5,248 · level at 60:00 % by minutes left when power play starts (6v4, goalie out)" >}}
**Key number.** 31% level at 60:00 with 6v4 against 24% at 5v4, minor at 2:00 left (difference 95% CI 3 to 12 pts). At 4:00, +3.7 (-0.4 to 7.6). n = 5,248 games, 464 min of 6v4.

**Method.** Outcome: level or ahead at 60:00. Markov model, 2:00 minor: 6v4 vs 5v4 then optimal even-strength pull; rates from trailing teams in the 3rd period. 6v4 time is chosen late, so its rates carry selection.

**Holds up?** Gain at 2:00 left: +9 pts in 2021-23, +6 pts in 2023-25.

**Data.** NHL API play-by-play + shift charts, regular seasons 2021-22 to 2024-25, 5,248 games.

[On Reference](/arkboard/reference/#rq-nhl-pp-goalie-pull)
{{< /rq >}}

## Baseball

### MLB stolen bases

{{< rq id="mlb-stolen-bases" sport="MLB" date="2026-11-02" q="After the 2023 base and pickoff rules, do runners still steal too little?" a="Slightly. Steals of 2nd succeed 75.9% vs 71.7% break-even, +2.6 runs per team-season. At 1 out, no edge." n="75.9%" nl="steal of 2nd success, 2023-25" bars="2nd, 0 out:73.2|2nd, 1 out:70.0|2nd, 2 out:74.0|3rd, 0 out:86.8|3rd, 1 out:71.0|3rd, 2 out:84.6" unit="%" note="n = 15,011 · success % by base stolen, outs (2021-22)" >}}
**Key number.** 75.9% success on steals of 2nd (95% CI 75.0 to 76.7, n = 9,265) against 71.7% break-even. Run value +0.022 per attempt (+0.017 to +0.027). n = 15,011 attempts, 2021-25.

**Method.** Steal attempts from clean states (runner on 1st only, or 2nd only), incl. pickoff-CS and K+CS. Break-even from era RE24 (innings 1-8). Run value uses the steal outcome only. Average success above break-even does not prove the marginal try pays.

**Holds up?** Success above break-even in each season 2023, 2024, 2025 for steals of 2nd; gap shrinks from +4.1% to +3.3%.

**Data.** Retrosheet play-by-play, 2021-2025 regular season, 15,011 steal attempts in clean states. Retrosheet: the information used here was obtained free of charge from and is copyrighted by Retrosheet (www.retrosheet.org).

[On Reference](/arkboard/reference/#rq-mlb-stolen-bases)
{{< /rq >}}

### MLB intentional walks

{{< rq id="mlb-ibb" sport="MLB" date="2026-11-02" q="Do intentional walks gain win probability for the defense?" a="Mostly no. Runner on 2nd, 1 out: IBB costs the defense 2.0 win-prob pts. Other states: no gain distinguishable from 0." n="-2.0" nl="WP pts, runner on 2nd, 1 out" bars="2nd, 1 out:-1.97|2nd, 2 out:-0.15|3rd, 1 out:0.37|3rd, 2 out:0.01|2nd+3rd, 1 out:0.29|2nd+3rd, 2 out:-0.33" unit="" note="n = 6,129 · win-prob pts by runners, outs (to end of inning)" >}}
**Key number.** -2.0 WP pts for the defense with a runner on 2nd and 1 out (95% CI -3.3 to -0.7, n = 545). n = 6,129 intentional walks.

**Method.** Defense-view change in empirical WE, from the PA start to the end of the half-inning (main) and over the PA. OLS with batter and on-deck season wOBA, inning x score x season cells; SE clustered by game. Compared with pitching to the batter in the same state.

**Holds up?** Runner on 2nd, 1 out: -2.0 pts 2015-19, -1.9 2020-25 (SE 0.8, 1.2).

**Data.** Retrosheet play-by-play, 2015-2025 regular season, 6,129 intentional walks to non-pitchers in innings 1-9. Retrosheet: the information used here was obtained free of charge from and is copyrighted by Retrosheet (www.retrosheet.org).

[On Reference](/arkboard/reference/#rq-mlb-ibb)
{{< /rq >}}

### MLB times through the order

{{< rq id="mlb-tto" sport="MLB" date="2026-11-02" q="Does the times-through-the-order penalty justify pulling starters before the 3rd time?" a="For an average starter, yes. 3rd time: +.022 wOBA vs 1st (same pitcher), .339 vs relievers .323." n="+.022" nl="wOBA, 3rd time vs 1st" bars="2:0.319|5:0.324|8:0.32|11:0.329|17:0.333|20:0.338|23:0.348|26:0.342" unit="" note="n = 1,109,963 · wOBA allowed by batters faced (3-batter bins)" >}}
**Key number.** +.022 wOBA the 3rd time through against the 1st, same pitcher-season (95% CI +.020 to +.025). n = 1,109,963 starter PAs.

**Method.** OLS on PA wOBA with pitcher-season fixed effects, batter-season wOBA, platoon and home; SE clustered by game. Survivors to the 3rd time are pitchers having better days, so the penalty is if anything understated.

**Holds up?** 3rd-time penalty +.024 in 2015-19 and +.020 in 2020-25; discrete jumps only in 2015-19.

**Data.** Retrosheet play-by-play, 2015-2025 regular season, 1,109,963 starter PAs (1st-3rd time), 24,958 games. Retrosheet: the information used here was obtained free of charge from and is copyrighted by Retrosheet (www.retrosheet.org).

[On Reference](/arkboard/reference/#rq-mlb-tto)
{{< /rq >}}

### MLB sacrifice bunts

{{< rq id="mlb-sac-bunt" sport="MLB" date="2026-11-02" q="Do sacrifice-bunt tries with nobody out gain win probability?" a="No. Bunt tries cost 0.3 to 0.9 win-prob pts per try vs swinging; late and close, up to 1.9." n="-0.3" nl="WP pts per try, runner on 1st" bars="1st, all:-0.26|1st, late:-0.72|2nd, all:-0.7|2nd, late:-0.85|1st+2nd, all:-0.85|1st+2nd, late:-1.88" unit="" note="n = 158,989 · win-prob pts by runners, game state (over the PA)" >}}
**Key number.** -0.3 WP pts per bunt try with a runner on 1st (95% CI -0.4 to -0.1, n = 5,068 tries); 1st and 2nd -0.9 (-1.1 to -0.6). n = 158,989 PAs, 9,669 tries.

**Method.** Non-pitcher PAs, 0 out, innings 1-9. Bunt try = bunt in play or foul/missed bunt. Outcome: change in empirical WE over the PA. OLS with batter and on-deck season wOBA, inning x score x season cells; SE clustered by game.

**Holds up?** PA-level loss in both eras for 2nd and 1st+2nd; runner on 1st: -0.5 pts 2015-19, -0.0 2020-25 (n.s.).

**Data.** Retrosheet play-by-play, 2015-2025 regular season, 158,989 PAs with runners on and 0 out, 9,669 bunt tries. Retrosheet: the information used here was obtained free of charge from and is copyrighted by Retrosheet (www.retrosheet.org).

[On Reference](/arkboard/reference/#rq-mlb-sac-bunt)
{{< /rq >}}

## Soccer

### Soccer protecting a lead

{{< rq id="soccer-protecting-lead" sport="soccer" date="2026-11-02" q="Does a team leading by one goal lose the xG battle late, and does it cost points?" a="Yes after 75': xG share 46% vs 53% expected. Costs 0.05 xPts from 75', but actual points held." n="46%" nl="leader xG share after 75', expected 53%" bars="7.5':52.2|22.5':56.9|37.5':55.5|52.5':54.0|67.5':50.7|85':45.9" unit="%" note="n = 2,856 · xG share by minute (band midpoint) (leading by 1, actual)" >}}
**Key number.** Leader xG share 45.9% after 75' (95% CI 43.2 to 48.4) against 52.7% expected, 1,434 matches. Points: 2.60 actual against 2.60 baseline (gap 0.00). n = 2,856 matches.

**Method.** 11v11 minutes only, split by score state and 15-min band. Expected share from leave-one-out season xG for/against of both teams, home factor, and league xG volume by band. xPts from Poisson on remaining xG; CIs bootstrap by match.

**Holds up?** From-75' xPts gap: 2015/16 men's leagues -0.08 (n=401), other comps -0.04 (n=640); both CIs exclude 0.

**Data.** StatsBomb open data, 23 full seasons/tournaments (2015/16 EPL, Serie A, Ligue 1; men's WC/Euro/Copa/AFCON; ISL; women's leagues and tournaments), 2,856 matches with clean event data.

[On Reference](/arkboard/reference/#rq-soccer-protecting-lead)
{{< /rq >}}

### Soccer after a goal

{{< rq id="soccer-after-conceding" sport="soccer" date="2026-11-02" q="Do teams score more or less in the minutes after a goal?" a="No momentum swing. Team that just conceded scores 0.95x baseline in the next 10 min; scorer 1.06x. Restart dips the first 3 min." n="0.95x" nl="goals by the conceding team, next 10 min" bars="1.5 min:0.743|4.5 min:0.965|8 min:1.068|12.5 min:1.04|17.5 min:1.049" unit="" note="n = 2,856 · observed / expected xG by minutes since goal (team that conceded)" >}}
**Key number.** Conceding team scores 0.95x baseline in the next 10 min (95% CI 0.88 to 1.02); scoring team 1.06x (0.99 to 1.12). n = 2,856 matches, 527,256 team-minutes.

**Method.** Team-minutes (11v11) by time since last goal. Baseline: league rate for the same 15-min band and score state, scaled by pre-match strength (leave-one-out season xG). Observed/expected; CIs bootstrap by match.

**Holds up?** Conceding team 0-10 min goals: 1.09x in 2015/16 leagues, 0.88x elsewhere; direction flips, so no stable effect.

**Data.** StatsBomb open data, 23 full seasons/tournaments (2015/16 EPL, Serie A, Ligue 1; men's WC/Euro/Copa/AFCON; ISL; women's leagues and tournaments), 2,856 matches, 527,256 team-minutes.

[On Reference](/arkboard/reference/#rq-soccer-after-conceding)
{{< /rq >}}

### Soccer first sub timing

{{< rq id="soccer-first-sub-timing" sport="soccer" date="2026-11-02" q="When do teams make their first sub by score state, and does an early first sub pay off?" a="Trailing teams sub first by 60', level and leading by 65'. A first sub before 60' adds +0.04 xG diff; no goal effect found." n="+0.04" nl="xG diff, first sub before 60'" bars="46':34.4|50':35.4|60':59.9|65':78.0|70':88.4|75':93.8|85':96.9|90':97.2" unit="%" note="n = 4,853 · teams subbed by minute (trailing)" >}}
**Key number.** +0.041 xG difference from 60' for a first sub before 60' (95% CI +0.005 to +0.078); goals +0.045 (-0.02 to +0.11). n = 4,853 team-matches.

**Method.** Timing: discrete hazard of first tactical sub per minute by current state. Effect: landmark at 60' (and HT), OLS with match-clustered SE on score state, strength, home, prior xG diff and xG diff in the 15 min before the landmark (the trigger window), opponent early sub. Injury subs and red cards before the landmark excluded.

**Holds up?** xG-diff effect +0.028 in 2015/16 leagues, +0.048 elsewhere; same sign, neither CI excludes 0 alone.

**Data.** StatsBomb open data, 23 full seasons/tournaments (2015/16 EPL, Serie A, Ligue 1; men's WC/Euro/Copa/AFCON; ISL; women's leagues and tournaments), 2,659 matches, 4,853 team-matches at the 60' landmark.

[On Reference](/arkboard/reference/#rq-soccer-first-sub-timing)
{{< /rq >}}

## Tennis

### Tennis first serve on second serve

{{< rq id="tennis-second-serve-first-serve" sport="tennis" date="2026-11-02" q="Should players hit a first serve on second serve?" a="No. 6 of 188 men and 4 of 112 women would gain. Median player loses 6.8 pts (men), 5.3 (women) per 100." n="6 of 188" nl="men who would gain" bars="-16 to -14:1.1|-14 to -12:3.2|-10 to -8:17.5|-8 to -6:24.5|-6 to -4:16.0|-4 to -2:13.3|0 to +2:1.6|+2 to +4:1.6" unit="%" note="n = 300 · share of players by points won per 100 second-serve points (men (188))" >}}
**Key number.** 152 of 188 men and 80 of 112 women lose with a 95% CI below zero; 1 man and no women gain with a CI above zero. n = 300 players, 11,785 charted matches.

**Method.** Per server: P(1st in) x P(win | 1st in) minus P(2nd in) x P(win | 2nd in). Bootstrap 95% CI resampling matches. Assumes first-serve in-rate and win rate hold on second-serve points.

**Holds up?** Gainers by era (250+ 2nd serves), pre-2015 / 2015+: men 4 of 104 / 14 of 193, women 3 of 42 / 7 of 169.

**Data.** Match Charting Project points, 1960-2026 (71% of matches 2015+), 11,785 matches; servers with 500+ second serves.

[On Reference](/arkboard/reference/#rq-tennis-second-serve-first-serve)
{{< /rq >}}

### Tennis hold after breaking

{{< rq id="tennis-hold-after-break" sport="tennis" date="2026-11-02" q="Do players drop serve more often right after breaking?" a="No. Same player and match: hold rate after breaking is +0.7 pts (men), +0.5 (women) vs after opponent holds." n="+0.7" nl="pts hold rate after breaking, men" bars="after opponent held:79.4|after breaking:82.0" unit="%" note="n = 249,107 · hold % by previous game (men)" >}}
**Key number.** +0.7 pts hold rate after breaking, men (95% CI +0.2 to +1.2, n = 11,796 player-matches); women +0.5 (-0.2 to +1.2, n = 7,616). n = 249,107 service games.

**Method.** Hold (non-tiebreak games) by whether the server broke in the previous game. Within player-match difference, weighted; bootstrap CI resampling matches. Form swings within a match bias this upward.

**Holds up?** Pre-2015 / 2015+: men +1.0 / +0.6 pts, women +0.2 / +0.6 pts.

**Data.** Match Charting Project points, 11,270 matches, 249,107 service games.

[On Reference](/arkboard/reference/#rq-tennis-hold-after-break)
{{< /rq >}}

### Tennis serve direction

{{< rq id="tennis-serve-direction-mix" sport="tennis" date="2026-11-02" q="Do first serves wide, body and T win at equal rates, as mixed-strategy theory predicts?" a="Wide and T: yes, within 1 pt for the same server. Body: no, 4.2 pts lower (men), 4.1 (women)." n="-4.2" nl="pts, body vs wide and T, men" bars="Deuce wide:65.2|Deuce body:59.9|Deuce T:64.9|Ad wide:64.0|Ad body:59.3|Ad T:64.0" unit="%" note="n = 1,857,004 · server points won by court side and target (men)" >}}
**Key number.** Body serves win 4.2 pts less than wide and T for the same server, men (95% CI -4.6 to -3.8); women -4.1 (-4.5 to -3.7). T minus wide, men -0.1 (-0.3 to +0.1). n = 1,857,004 first serves.

**Method.** Outcome: server wins the point, given the first serve was aimed at that target (faults count). Within-player test compares wide and T for each server and court side (150+ serves each).

**Holds up?** Wide vs T within 0.4 pts in both eras (pre-2015, 2015+), men and women.

**Data.** Match Charting Project points, 11,785 charted matches, 1,857,004 first serves with a direction.

[On Reference](/arkboard/reference/#rq-tennis-serve-direction-mix)
{{< /rq >}}

## Counter-Strike

### CS2 pistol round

{{< rq id="cs2-pistol-value" sport="CS2" date="2026-11-02" q="How much is the first pistol round worth, and does the side matter?" a="First pistol winner takes the map 59.5%: 57.1% on CT, 61.9% on T." n="61.9%" nl="map win, pistol 1 won on T" bars="P1 won on CT:57.1|P1 won on T:61.9|P2 won on CT:62.1|P2 won on T:57.9|both pistols:69.2|split, won P1:49.5" unit="%" note="n = 17,525 · map win % by pistol result" >}}
**Key number.** 61.9% map win after winning pistol 1 on T (95% CI 60.9 to 63.0, n = 8,716); 57.1% on CT (56.1 to 58.2, n = 8,809). Elo-adjusted, +17.2 pp (+16.0 to +18.6). n = 17,525 maps.

**Method.** Map win % for pistol round winners (rounds 1 and 13), Wilson CIs. Team strength: logistic model with pre-map Elo; pistol effects as average marginal change, map-clustered CIs.

**Holds up?** P1 winner map win: early 59.3% (n=8,762), late 59.7% (n=8,763).

**Data.** bo3.gg round data, S/A/B-tier pro maps, 2023-10-16 to 2026-11-02, 17,525 maps

[On Reference](/arkboard/reference/#rq-cs2-pistol-value)
{{< /rq >}}

### CS2 buy after losing the pistol

{{< rq id="cs2-pistol-loser-buy" sport="CS2" date="2026-11-02" q="After losing the pistol round, should the team save or buy on round 2?" a="Buying on round 2: +26.8 pp in round 2, -16.5 pp in round 3, map win -0.8 pp (not different from 0)." n="-0.8" nl="pp map win, buy vs save" bars="CT R2:2.6|CT R3:50.0|CT map:39.8|T R2:3.1|T R3:50.4|T map:39.5" unit="%" note="n = 34,640 · win % by side and outcome (save round 2)" >}}
**Key number.** Map win, buy vs save: CT -1.1 pp (95% CI -2.6 to +0.3), T -0.8 pp (-2.2 to +0.7). Round 2 +25.0 / +28.3 pp, round 3 -17.0 / -16.0 pp. n = 34,640 pistol-loss halves.

**Method.** Pistol loser's round-2 buy class from bo3.gg equipment value (save = eco, buy = half/force). Logistic models adjust for side, team Elo, winner's round-2 equipment, loser's pistol kills and half; cluster-robust CIs by map.

**Holds up?** Map effect early/late: CT -1.1 pp / -1.1 pp, T +0.9 pp / -2.6 pp.

**Data.** bo3.gg round data, S/A/B-tier pro maps, 2023-10-16 to 2026-11-02, 17,525 maps, 34,640 pistol-loss halves (16,992 CT)

[On Reference](/arkboard/reference/#rq-cs2-pistol-loser-buy)
{{< /rq >}}

### CS2 equipment gap

{{< rq id="cs2-equipment-gap" sport="CS2" date="2026-11-02" q="How much does an equipment gap change round win chances on CT and T?" a="Full buy vs full buy: CT wins 51.7%. At equal dollar value CT wins 48.5%; an eco beats a full buy 5.6%." n="51.7%" nl="CT round win, full buy vs full buy" bars="-24:5.4|-16:18.3|-12:28.4|-4:43.7|4:53.2|12:65.0|16:75.1|24:91.0" unit="%" note="n = 327,073 · round win % by own minus opponent equipment ($k) (CT)" >}}
**Key number.** CT wins 51.7% of full-buy rounds (95% CI 51.4 to 52.0, n = 154,499); a CT eco wins 5.9% (5.5 to 6.4, n = 11,243). n = 327,073 rounds.

**Method.** Non-pistol regulation rounds; equipment value at round start per team from bo3.gg, binned by CT minus T in $4k steps (ends capped at $24k). Round win rate with map-clustered CIs.

**Holds up?** Full vs full CT win %: early 51.7% (n=76,815), late 51.7% (n=77,684).

**Data.** bo3.gg round data, S/A/B-tier pro maps, 2023-10-16 to 2026-11-02, 17,525 maps, 327,073 rounds

[On Reference](/arkboard/reference/#rq-cs2-equipment-gap)
{{< /rq >}}

### CS2 losing streaks

{{< rq id="cs2-loss-streak" sport="CS2" date="2026-11-02" q="Does a losing streak hurt the next round beyond economy (the no-timeout baseline)?" a="No tilt. After 3+ straight losses a team wins +0.9 pp vs an economy and score model." n="+1.1" nl="pp vs model after 3 straight losses" bars="1:-0.004|2:-0.001|3:0.011|4:0.008|5:0.008|6:0.006" unit="" note="n = 327,073 · actual minus expected by rounds lost in a row" >}}
**Key number.** +1.1 pp above the economy and score model after 3 straight losses (95% CI +0.7 to +1.5, n = 51,700). n = 327,073 rounds.

**Method.** Logistic baseline on buy-class matchup by side, equipment values, score gap, Elo and round in half; actual minus predicted win rate by current losing streak in the half, map-clustered CIs.

**Holds up?** 3+ streak gap: early +0.9 pp (n=55,017), late +0.9 pp (n=55,026).

**Data.** bo3.gg round data, S/A/B-tier pro maps, 2023-10-16 to 2026-11-02, 17,525 maps, 327,073 rounds

[On Reference](/arkboard/reference/#rq-cs2-loss-streak)
{{< /rq >}}

### CS2 starting side

{{< rq id="cs2-side-first" sport="CS2" date="2026-11-02" q="Which side should a team start on, map by map?" a="Start T. T-first teams win 52.4% of maps; 55.8% on overpass, 50.0% on anubis." n="52.4%" nl="map win, T-first team" bars="anubis:50.0|mirage:50.0|ancient:50.4|cache:51.0|train:53.4|nuke:54.1|dust2:55.2|overpass:55.8" unit="%" note="n = 17,525 · T-first map win % by map" >}}
**Key number.** T-first teams win 52.4% of maps (95% CI 51.6 to 53.1). Elo-adjusted, -2.5 pp for CT-first. n = 17,525 maps.

**Method.** Map win % of the team that started CT, Wilson CIs. Side choice is not random (pick/veto), so Elo-expected wins are subtracted as a check on team strength.

**Holds up?** CT-first win %: early 47.8% (n=8,762), late 47.5% (n=8,763).

**Data.** bo3.gg round data, S/A/B-tier pro maps, 2023-10-16 to 2026-11-02, 17,525 maps

[On Reference](/arkboard/reference/#rq-cs2-side-first)
{{< /rq >}}

## Across sports

Three patterns show up in more than one sport.

- **Late-game decisions are too conservative, and the gap is closing at different speeds.** NFL teams go for it in 45% of clear go states, up from 25% in 2015-16. Down 8 at a Q4 PAT, they went for two in 2 of 72 tries in 2015-18 and 13 of 24 in 2025-26. NHL teams pull the goalie down one at a median of 1:58 left in 2024-25 against an optimum of 3:18, up from 1:47 in 2021-22.
- **Giving up an out or a base costs win probability.** Sacrifice bunts lose 0.3 to 0.9 WP pts per try and intentional walks lose 2.0 in the most common spot. Both have fallen: bunt tries from 9.1% to 6.5% of these PAs since 2015, intentional walks from 826 to 393 a season.
- **There is no momentum or tilt to manage.** Tennis players hold slightly more often right after breaking (+0.7 pts), soccer teams that just conceded score at 0.95x their baseline, and CS2 teams after three straight round losses win 1.1 pp more than the economy model. An NBA timeout after an 8+ point run nets 0.31 pts less over the next two minutes than playing on.

New studies go on [Reference](/arkboard/reference/) first. I'll add them here as they're published.
