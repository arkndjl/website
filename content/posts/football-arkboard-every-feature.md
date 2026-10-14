+++
title = "How the Football ARKBOARD Works"
date = "2026-10-14T10:30:00-05:00"
author = "arkndjl"
authorTwitter = "ARKNDJL" #do not include @
tags = ["cfb", "nfl", "football", "draft", "arkboard"]
keywords = ["arkboard", "college football", "nfl", "future value", "football war", "mock draft", "nil", "transfer portal", "team builder", "recruiting", "game projections", "fantasy projections", "upset picks"]
description = "The College Football and NFL ARKBOARD pages: FV, Stat+, WAR, badges, Draft%, the mock draft, xNIL, Transfer%, the team builder, recruit stars, the game model, upset picks, NFL WAR, NFL games and fantasy projections. How each one is calculated and how it tested."
showFullContent = false
readingTime = false
hideComments = true
Toc = true
aliases = ["/posts/college-football-arkboard-2026-27/"]
draft = false
+++

{{< card url="/arkboard/college-football/" title="College Football / NFL Draft :: ARKBOARD" >}}
Players, games, teams, recruits, the mock draft and the model report.
{{< /card >}}

{{< card url="/arkboard/nfl/" title="NFL :: ARKBOARD" >}}
NFL WAR, games, power rankings, season odds and fantasy projections.
{{< /card >}}

This post covers the College Football and NFL ARKBOARD pages: what each tab shows, how it's calculated, and how it tested on seasons it wasn't fit on.

An input only gets weight if it improves predictions on data the model didn't see. I list the inputs that failed that test too.

The screenshots are from the live pages on October 14. Tap one for the full size.

## Grading players

### FV, the 20-80 scale

FV (Future Value) is the main grade on the board. It's the same 20-80 scale I use for [MLB](https://eephus.io) and [the NBA](/posts/nba-future-value-grading-system/), tied to what a player is expected to become in the NFL:

| FV | NFL outcome | Per draft class |
| :---: | ----- | :---: |
| 80 | 3+ time All-Pro | ~3 |
| 70 | All-Pro | ~4 |
| 60 | Pro Bowler | ~12 |
| 55 | 6+ seasons as a starter | ~25 |
| 50 | 4+ seasons as a starter | ~32 |
| 45 | 2+ seasons as a starter | ~43 |
| 40 | rotational, 48+ games | ~64 |
| 30 | drafted / camp body | ~150 |
| 20 | non-NFL | |

All FBS and FCS players get a grade, not just the players on the board, so a grade is a rank against the whole population. It's built in two steps.

**Step 1, the composite.** Each input becomes a z-score (standard deviations above or below the average player at his position), and the composite is a weighted sum:

- **Production, 40%.** PFN's all-in-one score at his position, for each of the last three seasons, blended 5/4/3 by snaps and pulled toward average:

  production z = Σ(weight × snaps × z) / (Σ(weight × snaps) + 3000)

  The 3000 means a player needs about 600 snaps this season (5 × 600 = 3000) before his own numbers count for half.
- **Talent, 40%.** On3's college grade, as a percentile at his position.
- **Pedigree, 15%.** His 247 recruiting composite (half that when On3 grades him, since On3's grade already includes it).
- **Team strength, 5%.** Last season's SP+ for his team.

On top of those sit smaller, capped terms: an age curve (a producing 18-year-old gains about .8, a 24-year-old loses about .9), his frame projected to age 22, class runway, snap share, strength of schedule, ESPN's QBR for quarterbacks, six of the trait badges (below), and combine testing once the draft-year combine is published in February.

**Step 2, scarcity.** Within each position, the composite ranks players per draft class, and that rank is compared to how many players a class actually produces at each NFL outcome. If a class produces about 12 Pro Bowlers and safeties hold 2 of the 22 starting spots, about one Pro Bowl safety comes out of each class, so the best safety composite in a class lands near 60.

**Consensus.** For draft-eligible players, FV moves toward the grade implied by their median rank across nine industry big boards (PFN, CBS, ESPN, James Foster, NBC, The Athletic, Yahoo, Tankathon and PFF), up to 50% of the way when all nine rank him. Consensus rank was the single strongest predictor of NFL outcome in the backtest, which is why it gets that much. A **riser** (↗) is a prospect the model grades 6+ FV above what his consensus rank implies, or a 55+ that no board ranks.

**How it tested.** I rebuilt the 2019-22 boards and refit every driver at once, holding out one draft class at a time. The full refit didn't beat the existing weights out of sample, so most stayed. Three changes did hold up: the old-age penalty was cut in half (it was double counting years in college), snap share was cut to 40% of its weight, and combine testing went up 60%. Within each position, FV's correlation with NFL AV went from .507 to .525, and with draft slot from .586 to .610. Linebackers and tight ends got their own weights after a position-by-position refit (LB .423 to .471).

[![The 2027 draft board on a phone, with rank, position, school, position-change and riser chips](/img/football-arkboard/draft-board.webp)](/img/football-arkboard/draft-board.webp)

The board views are **all**, **all FBS**, **all FCS**, **draft board** (2027 eligible only) and **WAR leaders**. Ranks and position ranks (WR1, DT2) are computed within whatever tab and filters you have on.

### Stat+

Stat+ is production on an OPS+-style scale:

Stat+ = 100 + 25 × z

So 100 is the average player at his position (snap-weighted, within FBS or FCS), 125 is a good regular, 150+ is elite and 75 is well below average. It's built on PFN's score at each position (QB+, WR+, EDGE+, and so on). I tested how well that score predicts NFL AV at each position, and it's strongest at TE (r .52) and WR (.50), then QB and RB (.48), EDGE and LB (.40) and DT (.37). FV leans on production a little more at the positions where it predicts better.

### College WAR and WAA

WAR is wins over a replacement-level starter across a 12-game season:

WAR = snap share × (position line + position weight × quality) × .227

The pieces:

- **Points to wins.** One point of scoring margin per game is worth .0189 in win percentage (928 FBS team seasons, 2019-25). Over 12 games that's .0189 × 12 = .227 wins, so about 4.4 points a game is one win.
- **The position line** is what a team loses when an average starter at that spot sits. At QB it's 2.7 points a game, measured from 4,995 regular-season games where the starter didn't play (bowls are out because of opt-outs). The rest run from 1.7 at RB down to .8 at TE and interior line.
- **Quality** is Stat+, badges and FV combined. A QB keeps 1.25 points per SD of quality and the rest is shared with his offensive teammates by snap share, because a better QB's absence only costs about one more point a game per SD.

Example: a full-time, average starting QB is 1 × 2.7 × .227 = .61 WAR. A team of replacement starters wins about 2 of 12, and an average team's starters add up to about 3.8 WAR. Team WAR tracks actual margin with r .88 on this season, which the weights were not fit on.

**WAA** is WAR less the position line: wins over an average starter at his position. Sort by it to compare players across positions.

[![WAR leaders tab with college WAR and WAA](/img/football-arkboard/cfb-war.webp)](/img/football-arkboard/cfb-war.webp)

### Badges and archetypes

Badges run bronze, silver, gold and platinum (Blocker, Pass Rusher, Ballhawk, Route Runner, Deep Threat and so on). Each badge is one stat, regressed toward the position average by volume:

v' = m + (v − m) × n / (n + k)

where m is the position mean, n is his volume and k is the volume at which the stat is half signal, measured from how well it repeats year to year in PFN's 2019-25 lines. The tiers are percentiles among players with 100+ snaps at the position: bronze at the 75th, silver 90th, gold 97th, platinum 99th. Stats that barely repeat (QB interception rate, linebacker coverage, single coverage stats for DBs) are left out entirely, and corners and safeties get a coverage composite instead.

Six badges passed the test for predicting NFL AV beyond production (t ≥ 2 and better out of sample), so they feed FV: QB Deep Ball (.20) and Accurate (.13), RB Pass Catcher (.13), TE Pass Catcher (.24), DT Run Stopper (.07) and LB Tackler (.10). Nothing at WR or EDGE passed.

**Archetypes** are built from the badges. Each archetype lists badge groups and scores tier points (bronze 1 to platinum 4). A player needs a badge in every group, and the highest score of 2+ wins. Anyone short of that gets his position's base archetype.

### Position changes and versatility

A ⇄ chip flags a player whose weight at 22 and production fit a different NFL spot. Weight is projected along each position's age-weight slope, and the line between a DT and an edge is the lightest NFL DTs' weight, about 282 lb.

The odds are a logistic model fit on the 2020-26 combines against where the NFL actually played each player: a term for each move, the size fit (how far he is from the norm at his spot vs the new one) and whether he already played the new spot in college. That cut log loss from .170 to .140 and raised AUC from .79 to .90. A player is flagged at 50%+. Before this, 13 of 53 flags were right. Now it's 23 of 35. Some moves I had as rules never happened in the data (light receiving tight ends, small receiving backs, tall corners), so those flags are gone.

I also tested versatility: players graded at two position groups, listed somewhere else by ESPN, recruited at another spot, or recruited as an athlete. None of it predicted NFL value (t −.44), so it's display only, a dashed +POS chip.

### Running back roles

Every Down Back, Early Down Back, 3rd Down Back or committee. No public college source has snaps by down, so I estimate them: a back's snap share, split between standard downs and passing downs (2nd and 8+, 3rd or 4th and 5+) by how his share of carries and targets tilts between the two. Every-down is 50%+ on both. Early-down is 30%+ on standard downs and 10+ points less on passing downs. 3rd-down is the reverse. I calibrated it on the 2024 NFL season, where the real snaps by down are public, and it matched the true role for 82% of backs without ever mixing up an early-down back with a 3rd-down back.

### Draft% and FBS%

**Draft%** is the chance a player is picked in the 2027 draft:

Draft% = P(declares) × P(selected)

P(selected) = Φ((ln cut − ln xPick) / sd)

xPick is his expected pick from the mock draft. In the fall the cut is 344 and the spread is 1.28, and both tighten as the draft gets closer. Declaring is 94% for ranked underclassmen, about 70% for true seniors (4th-years with eligibility left often stay) and 100% for redshirt seniors and grad students.

Example: a ranked junior with an xPick of 100 in October gets Φ((ln 344 − ln 100) / 1.28) = Φ(.97) = .83, times .94 to declare, so 78%. Draft% is fit on PFF's dated big boards for the 2020-26 drafts. Leaving one draft out at a time, its log loss is .506 against .825 for the version it replaced. All Draft% values sum to a full 257-pick draft.

**FBS%** is on the FCS tab: the chance an FCS player is on an FBS roster next season, fit on every FCS-to-FBS move from 2023 to 2026. AUC .731. 2nd- through 4th-year players move up the most, 5th-years only 2.7%, and FBS% is capped at 1 − Draft%.

### NIL: yNIL, xNIL and zNIL

Three numbers, all priced off On3's valuations:

- **yNIL** is what a player was likely paid going into the season: his share of his program's budget (about $20M at a Power 4 school, $3M in the Group of Five, $0.4M in the FCS), split by what was known before the season (earlier production, On3 grade, recruiting, position).
- **xNIL** is what he's worth on the open market now, from his FV, position and role. A G5 player good enough to start at a P4 school is priced in the P4 market. An FCS player good enough to start higher up gets 40% of that price, since he only collects it by transferring. The median FBS player is worth $181K and the median FCS player $13K.
- **zNIL = xNIL − yNIL**, the value a player gained or lost this season. Summed by team it's a development number for programs, and it's 20% of every coach's score on the staff tab, as log((xNIL + $250K) / (yNIL + $250K)) ranked within role and P4/G5.

### Transfer%

The chance a player is on another FBS or FCS roster next season. It's a ridge logistic regression on every FBS and FCS player in the 2024 and 2025 cycles, followed to the next year's rosters. NIL-era data only. Inputs: class, recruiting rank, playing time, production, team record, head-coach change odds, level, distance from home, position, and a couple of interactions I found along the way. Players at loaded programs stay home (8.5% of top-quarter producers at programs 1+ SD above average moved), and a receiver whose quarterback transfers is likelier to go too.

10.6% of players within 50 miles of home transferred, against 19% of players 600 to 1,200 miles away. Tested out of time on the 2025-26 cycle, AUC is .738, and the top 10% of players by Transfer% moved at 39.7% against a 15.3% base rate. Transfer% + stay + exit (draft or eligibility) = 100%.

### ARKLIST, breakouts and the portal

**ARKLIST** is my favourites, marked with ★ on the board tabs. **Breakouts** lists first- and second-year skill players whose touches and targets jumped over their last two games. **Portal** lists this season's transfers with FV, and each team's net NFL value in minus out.

## The mock draft

The mock is a projection of how the 2027 draft will actually go, not my board. Three parts:

**Expected pick.** Each prospect's xPick is a geometric blend of his consensus rank and his rank by our draft value:

ln xPick = w × ln(consensus rank) + (1 − w) × ln(model rank), with w = .55 + .3 × √(boards ranking him / 9)

So a player on all nine boards is 85% market. The rank-to-pick curve was fit on 2020-25 final boards, and on those, position, class, conference and size added nothing once a board ranked a player. Only a missing combine invite and the 40 time did.

**Needs.** Every NFL position room is graded from ESPN rosters and contracts. A player's quality is the better of his draft capital on a rookie deal (1 − .13 × ln(pick)) or his pay against the top of the position's market, cut for age and an expiring deal. A room's need is half (1 − its starters' quality) and half its rank among the 32 teams. Teams pick on −ln(xPick) + need weight × need, with penalties for doubling up, for a set QB, and for runs on a position. Real traded picks are pulled from Wikipedia, and the order follows the full NFL tiebreaker rules (191 of 191 first-round slots right on 2020-25).

**Trades.** In rounds 1 and 2, a team up to 20 slots back trades up when a player is worth more to it than its best option at its own pick and a team picking in between might take him, valued on Massey and Thaler's pick value curve:

value(pick) = e^(−.148 × (pick − 1)^.698)

That makes pick 10 worth half of pick 1 and pick 32 about a fifth. The team pays its pick plus the smallest later picks that cover the gap plus 5%. Deals inside a division count at about half, since teams made those trades 18 times in 2010-25 against 45 expected. The live mock has 6 first-round trade-ups, against about 5 a year in real drafts.

A **value** chip marks a pick whose FV is a tier above our board at that slot and who goes 2.5x+ later than his board rank. **Reach** is the mirror. Clicking any pick opens a report: need, slot against projection, consensus and our board, position change, type and badges, and the strengths and concerns, all built from the numbers.

[![Mock draft with the first pick's report open: need, slot, type, badges, strengths and concerns](/img/football-arkboard/mock-report.webp)](/img/football-arkboard/mock-report.webp)

Replaying the 2020-25 drafts in real order, this setup beats taking the board in order on position-by-round counts (35.0 vs 37.3 error), and the positional adjustment cut the round 1-3 error against 2015-25 from 33.6 to 29.6.

## Recruits

**Projected FV.** Each recruit gets an expected FV:

xFV = P(on the field) × FV if on the field + (1 − P) × 20

Fit on ESPN's 2023-26 classes against this season's board, holding out whole programs. The inputs that passed are his grade, the 247 composite and how far it sits from ESPN's grade, and offer quality (the strength of the programs recruiting him). AUC .652 for making the field, r .40 for FV. The xFVs look low next to the board because most recruits never play much. FV if on the field is the number to compare with players.

**ARK stars.** Our 1 to 5 stars cut each recruit's projected year-3 FV at outcome bands: 5 stars is the top 3% of the board, 4 the top 10%, 3 above the median, 2 on the board, 1 off it. That predicted outcomes better than cutting at the industry's star shares (R² .146 vs .137, ESPN's own stars .112). ARK names about 3% of recruits five-stars against the industry's 0.6%.

**5-star+** is the top six recruits in a class by projected FV. I swept 3 to 40 per class, and elite outcomes (top 0.5% of the board) hit about 20% of the time up to 20 a class, so I took the rarest cut. **Half stars** (1.5 to 4.5) split each tier where the expected FV passes the midpoint between that tier and the next. A ▲ marks where we're above the industry.

[![2027 class with ARK stars, 5-star+ and industry stars side by side](/img/football-arkboard/cfb-class.webp)](/img/football-arkboard/cfb-class.webp)

The other recruit tabs are the 2028 and 2029 classes (2029 is a first look), class rankings, and redshirts, where the only driver that passed is playing in 1 to 4 games (t 4.35).

## Teams

### Rankings and season odds

The ARK Top 25 ranks teams by the game model's neutral-field rating, shown next to the AP and Coaches polls. Each rating is broken into Elo, efficiency, special teams and situational points. This season it has picked winners at 85%, the same as the AP. **Season odds** runs 10,000 simulated seasons for projected wins, conference title game, title, playoff and bowl odds.

[![ARK Top 25 next to the AP and Coaches polls](/img/football-arkboard/cfb-rank.webp)](/img/football-arkboard/cfb-rank.webp)

### Team talent, staff and the coaching market

**Team talent** has each team's projected starting talent, Elo, TvE and team xNIL. **Staff** scores every head coach and coordinator, with scheme fingerprints (4th-down go rate, tempo, run rate, havoc) as FBS percentiles.

The **coaching market** prices each coach and projects the carousel. Pay comes from USA Today's salary database (head coaches 2006-25, assistants 2009-24). Value is log(pay) fit on the program and results: for head coaches it explains 87% of pay out of sample, for coordinators 75%. Elo, TvE, zNIL and the staff score add nothing to pay once those are in, which means the market doesn't price them. That gap is where a coach's surplus comes from.

**Coaching jobs** gives each job's chance of opening (a model on 2010-25 school seasons, tested on 2020-25 with AUC .72) and who's likely to fill it. P4 openings went to a sitting FBS head coach 42% of the time, a coordinator 25%, and someone else 33%. When a head coach stays, 72% of his coordinators come back. When he's hired away, 43% follow him.

[![Coaching jobs tab with each job's odds and likely hires](/img/football-arkboard/cfb-jobs.webp)](/img/football-arkboard/cfb-jobs.webp)

### Team builder

The team builder plans each FBS program's offseason from its NIL budget:

1. **Budget** = the sum of its roster's yNIL, up 4%.
2. Hold back money for the incoming class.
3. **Keep** returners at their market price × the chance they stay, best value per dollar first.
4. **Sign** targets: likely transfers and FCS move-ups who would start, ranked by

   WAR per dollar × need × Transfer% × landing odds

   Landing odds are the chance he picks this school if he moves, from a model fit on 7,027 transfers in 2024-25 (level step, program talent, open playing time at his position, distance from home). A receiver is 7.2x likelier to land where his QB signs. 39% of 2025-26 transfers from programs whose head coach left went with him.
5. **Let walk** up to two returners when their cost could sign someone worth at least twice their edge over the next man up.

The budget is a soft target. Each dollar past it costs more, as Φ((spend − budget) / (.25 × budget)), so a program goes over only when the player is worth it. Next season's FV gives each returner a development step, scaled so the league's total talent next season matches this season's.

[![Team builder plan in brief for LSU: reload, money, keep, move, sign, next season](/img/football-arkboard/cfb-builder.webp)](/img/football-arkboard/cfb-builder.webp)

## Games

### The game model

Each team's rating is Elo plus opponent-adjusted EPA per play (garbage time removed), solved as a ridge regression shrunk toward a preseason prior: last season's SP+, this season's talent and returning production. On top of that come home field (2.4 points), rest, time zones, travel, altitude, and a P4 term (about 5.7 points for a P4 school against a G5 one, which the model had been missing). Totals are plays × points per play plus wind, rain, cold and an FCS term. Win, cover and over chances come from a normal distribution around the model margin and total.

An input only stays if it lowers log loss in both the fit season and the test season. Success rate made it. Explosiveness, red-zone points per trip, byes, short weeks, body clock and market ratings from earlier lines all failed.

Fit on 2025 and scored on 2026, the full model's log loss is .389 against .420 for Elo alone. The model's margin misses by 13.2 points on average and the closing line by 11.8, so the closing line is more accurate than the model.

[![Ohio State at Indiana game card: win probability, model vs market, projected score and each side's top players](/img/football-arkboard/cfb-games.webp)](/img/football-arkboard/cfb-games.webp)

### Projections and injuries

**Projections** are the week's top 300 offensive players by PPR points, from this season's per-game lines scaled by the opponent. Every injury status carries a chance of playing: out 0, doubtful .25, questionable .6, probable .9. With no status, a starter who played last week plays 89% of the time, 51% after missing one game, 31% after two and 16% after three or more. When a teammate is out, his volume goes to the players still there. In 2024-26 holdout tests that cut the error for starters from 9.50 to 9.16 points, and for players who missed the last game from 6.73 to 5.54. A season-ending injury costs 1 FV (2 for an ACL or Achilles).

### Upset picks and units

The picks tab runs one rule every week: when the model has the market underdog winning outright and is more than 4 points off the line, it's a pick.

Across 116 flagged games in 2025 and 2026, the underdog won 40% of the time. On the moneyline at the close it went 47-69, −9.1%. Against the opening spread it went 58-54, −1.1%, with the line moving our way by 1.5 points on average.

Units scale with the Kelly stake at the model's win chance:

Kelly = (b × p − q) / b

where b is the payout per unit, p the model's chance and q = 1 − p. That's scaled so picks run 0.25 to 3 units and average 1. Sizing made the moneyline worse in the backtest (−11.7%), because the biggest edges did the worst. Both numbers are on the tab.

[![Week 7 upset picks with units, and the backtest table](/img/football-arkboard/picks.webp)](/img/football-arkboard/picks.webp)

## NFL

### NFL WAR

NFL WAR is built from AV (approximate value), rebuilt from nflverse play data since PFR only posts AV after a season:

WAR = (AV − position line × snap share) × .091

.091 is wins per team AV (2021-25, r .86). The position line is replacement AV at each spot (QB, RB, outside and slot WR, TE, tackle, interior line, EDGE, DT, LB, outside and nickel CB, S), blended from what teams lost when a regular sat (2,639 games), veteran contracts and AV. A team of replacements wins 3 of 17, so team WAR adds up to wins minus 3.

On defense, AV credits pressures instead of sacks, since pressures repeat much better year to year. That moved EDGE season-to-season stability from .25 to .45. The NFL page also has **team WAR** by position group and **QB value**, the QB term in points a game over a replacement.

[![NFL WAR leaders](/img/football-arkboard/nfl-war.webp)](/img/football-arkboard/nfl-war.webp)

### NFL games, power rankings and season odds

Margin = Elo + opponent-adjusted EPA per play (half-life of 12 games) + the starting QB against the team's recent QB play + rest + home field + injuries.

The injury cost for each player on the report is his WAR per game × 36 points per win × the chance he misses. Measured on 2016-25: out 1, doubtful .98, questionable .25 (.5 if he missed the last game), probable .05. A questionable QB is blended 60/40 with the next healthy one.

Held out on 2021-25, the model misses by 10.13 points a game and the closing line by 9.76. The model has no edge on the close, so there are no NFL picks. **Power rankings** are neutral-field points with the current QB, and **season odds** come from 10,000 simulated seasons.

[![NFL game cards with the model line, win probability and projected score](/img/football-arkboard/nfl-games.webp)](/img/football-arkboard/nfl-games.webp)

### Fantasy projections, rankings and breakouts

Projections are stat lines (attempts, targets, yards, touchdowns and so on) from a ridge regression per stat and position, scored in PPR, half PPR or standard, this week and rest of season, with K and DST. Two context inputs passed: volume left over when teammates are out, and a short 1.5-game memory for role changes alongside the long one.

Held out on 2021-25, the average PPR miss per game, against the backtest's baseline projection:

| | Model | Baseline |
| :---: | :---: | :---: |
| QB | 6.11 | 6.51 |
| RB | 5.08 | 5.40 |
| WR | 5.26 | 5.56 |
| TE | 4.61 | 4.99 |

**Rankings** break players into tiers (natural breaks in projected points, about one tier per six players) and rank overall by VOR, points over the first non-starter at the position in a 12-team league (QB13, RB30, WR31, TE13). **Breakouts** are players below a starter's line with 20%+ odds of reaching it over the next four games. Held out, flagged players hit 22-30% of the time against 3-8% for everyone else. Each one also shows his points if he got the starting job.

[![NFL fantasy rankings with tiers and VOR](/img/football-arkboard/nfl-rank.webp)](/img/football-arkboard/nfl-rank.webp)

### Injuries

NFL statuses come from the league's practice and game report, ESPN and Rotoballer, with the newest item winning. Once a team's report for the week is out, a player who's off it, practicing in full, or without a designation on the final report is cleared. Before the report, last week's tag carries over at the rate it actually carried in 2021-25 (questionable .84, doubtful .55, out .38). It refreshes twice a day.

## GFX

Most views have a **GFX** button that draws a 4:5 card: the board, game previews, the mock draft by round with its trades listed, the upset picks, the Top 25, recruit classes and team builder plans. They use the site's palette (purple, teal, lilac) and pixel font, with pixel-art icons for badges and stars.

[![GFX card for Ohio State at Indiana](/img/football-arkboard/gfx-game.webp)](/img/football-arkboard/gfx-game.webp)

[![GFX card for LSU's 2027 offseason plan](/img/football-arkboard/gfx-builder.webp)](/img/football-arkboard/gfx-builder.webp)
