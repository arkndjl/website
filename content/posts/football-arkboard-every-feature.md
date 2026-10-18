+++
title = "How the Football ARKBOARD Works"
date = "2026-10-14T10:30:00-05:00"
author = "arkndjl"
authorTwitter = "ARKNDJL" #do not include @
tags = ["cfb", "nfl", "football", "draft", "arkboard"]
keywords = ["arkboard", "college football", "nfl", "future value", "football war", "mock draft", "nil", "transfer portal", "team builder", "recruiting", "game projections", "fantasy projections", "upset picks"]
description = "College Football and NFL ARKBOARD method: FV, Stat+, WAR, badges, Draft%, mock draft, xNIL, Transfer%, team builder, recruit stars, game model, upset and favorite picks, NFL WAR, NFL games, fantasy projections. Formulas, inputs, out-of-sample tests."
showFullContent = false
readingTime = false
hideComments = true
Toc = true
aliases = ["/posts/college-football-arkboard-2026-27/"]
draft = false
+++

{{< card url="/arkboard/college-football/" title="College Football / NFL Draft :: ARKBOARD" >}}
players · games · teams · recruits · mock draft · model report
{{< /card >}}

{{< card url="/arkboard/nfl/" title="NFL :: ARKBOARD" >}}
NFL WAR · games · power rankings · season odds · fantasy projections
{{< /card >}}

- input rule: weight only if it improves prediction out of sample; failed inputs listed per section
- screenshots: live pages, 2026-10-14

## Grading players

### FV, the 20-80 scale

FV (Future Value): 20-80 scale tied to expected NFL outcome; same scale as [MLB](https://eephus.io) and [NBA](/posts/nba-future-value-grading-system/).

| FV | NFL outcome | Per class |
| :---: | ----- | :---: |
| 80 | 5+ time All-Pro (generational) | ~1 |
| 70 | 2-time All-Pro | ~3 |
| 60 | Pro Bowler | ~16 |
| 55 | 6+ seasons as a starter | ~25 |
| 50 | 4+ seasons as a starter | ~32 |
| 45 | 2+ seasons as a starter | ~43 |
| 40 | rotational, 48+ games | ~64 |
| 30 | drafted / camp body | ~150 |
| 20 | non-NFL | |

- population: every FBS and FCS player; FV = rank against the whole population

**Step 1, composite** (each input a z-score vs the position mean):

```
composite = .40 prod + .40 talent
          + .15 pedigree + .05 team

prod z = Σ(w × snaps × z)
         / (Σ(w × snaps) + 3000)
w = 5/4/3 (last three seasons)
```

- production: PFN all-in-one score at the position; 3000 = ~600 snaps this season (5 × 600) for half weight on own numbers
- talent: On3 college grade, percentile at the position
- pedigree: 247 composite; x.5 when On3 grades the player (On3 grade already includes it)
- team: last season's SP+ for the player's team
- capped terms: age curve (producing 18-year-old +.8, 24-year-old −.9), frame projected to age 22, class runway, snap share, strength of schedule, QBR (QB), six badges (below), combine testing (draft-year combine, from February)

**Step 2, scarcity**:

- within position, composite rank per draft class -> NFL outcome counts per class x position share of the 22 starting spots
- e.g. ~12 Pro Bowlers per class, S = 2 of 22 spots -> ~1 Pro Bowl S per class -> top S composite in a class ≈ 60

**Consensus**:

- draft-eligible: FV moves toward the FV implied by median rank on ten big boards (PFN, CBS, ESPN, James Foster, NBC, The Athletic, Yahoo, Tankathon, PFF, Kiper's top 25); up to 50% at 9+ boards
- consensus rank: strongest single predictor of NFL outcome in the backtest
- riser (↗): model FV ≥ consensus FV + 6, or FV 55+ with no board rank

**Backtest** (2019-22 boards rebuilt, all drivers refit jointly, one draft class held out at a time):

- full refit did not beat existing weights out of sample; kept: old-age penalty x.5 (double counted college years), snap share x.4, combine testing x1.6
- r with NFL AV within position .507 -> .525; with draft slot .586 -> .610
- LB and TE: own weights from position-by-position refit (LB .423 -> .471)

[![The 2027 draft board on a phone, with rank, position, school, position-change and riser chips](/img/football-arkboard/draft-board.webp)](/img/football-arkboard/draft-board.webp)

- views: all · all FBS · all FCS · draft board (2027 eligible) · WAR leaders
- rank and position rank (WR1, DT2): within the active tab and filters

### Stat+

```
Stat+ = 100 + 25 z
```

- z: PFN position score (QB+, WR+, EDGE+ ...) vs snap-weighted position mean, FBS or FCS
- 100 = position average · 125 = good regular · 150+ = top · 75 = well below average
- r with NFL AV: TE .52 · WR .50 · QB .48 · RB .48 · EDGE .40 · LB .40 · DT .37
- FV production weight by position: higher where r is higher

### College WAR and WAA

```
WAR = snap share
      × (line
         + pos weight × quality)
      × .227
```

- wins over a replacement-level starter, 12-game season
- .0189 win% per point of margin a game (928 FBS team seasons, 2019-25; r .91; 2026 test r .88); .0189 × 12 = .227 wins; ~4.4 points a game = 1 win
- line: points a game lost when an average starter at the spot sits; QB 2.7 (4,995 regular-season games where the starter did not play; bowls out, opt-outs); RB 1.7 down to TE and interior line .8
- quality: Stat+, badges and FV combined
- QB keeps 1.25 points per SD of quality; rest shared with offensive teammates by snap share (QB absence costs ~1 point a game more per SD)
- e.g. full-time average QB: 1 × 2.7 × .227 = .61 WAR
- replacement-starter team: ~2 of 12 wins; average team's starters: ~3.8 WAR
- WAA = WAR − position line: wins over an average starter at the position; compares across positions

[![WAR leaders tab with college WAR and WAA](/img/football-arkboard/cfb-war.webp)](/img/football-arkboard/cfb-war.webp)

### Badges and archetypes

```
v' = m + (v − m) × n / (n + k)
```

- badge = one stat (Blocker, Pass Rusher, Ballhawk, Route Runner, Deep Threat ...), regressed by volume
- m = position mean · n = volume · k = volume at which the stat is half signal (year-to-year repeat, PFN 2019-25)
- tiers: percentile among 100+ snap players at the position; bronze 75th · silver 90th · gold 97th · platinum 99th
- left out (barely repeat): QB INT rate, LB coverage, single DB coverage stats; CB and S: coverage composite
- in FV (NFL AV beyond production, t ≥ 2 and better out of sample): QB Deep Ball .20, Accurate .13 · RB Pass Catcher .13 · TE Pass Catcher .24 · DT Run Stopper .07 · LB Tackler .10; none at WR or EDGE
- also in FV, from XV's stat parts (same test, badges held fixed; no badge shown): LB coverage (passer rating allowed, by targets) .08 · EDGE sack rate .07; capped ±.2 together. LB coverage barely repeats year to year but tracks NFL careers (t 3.2)
- archetype: badge groups, tier points bronze 1 to platinum 4; badge required in every group; top score 2+ wins; else position base archetype

### Position changes and versatility

- ⇄ chip: weight at 22 and production fit a different NFL spot
- weight projected along the position's age-weight slope; DT/EDGE line ≈ 282 lb (lightest NFL DTs)
- odds: logistic on 2020-26 combines vs NFL usage; terms: move, size fit (distance from norm at current vs new spot), college history at the new spot
- log loss .170 -> .140 · AUC .79 -> .90 · flag at 50%+
- flags right: 13 of 19 (logistic) vs 17 of 37 (rules alone); rule paths before: 23 of 35 vs 13 of 53
- removed (never in the data): light receiving TE, small receiving RB, tall CB moves
- versatility (two position groups graded, ESPN listing elsewhere, recruited at another spot or as ATH): no NFL value signal (t −.44); display only, dashed +POS chip

### Running back roles

- labels: Every Down · Early Down · 3rd Down · committee
- snaps by down estimated: snap share split between standard and passing downs (2nd and 8+, 3rd/4th and 5+) by tilt in carry and target share
- every-down: 50%+ both · early-down: 30%+ standard, 10+ points lower on passing · 3rd-down: the reverse
- calibration: 2024 NFL season (true snaps by down); 82% of backs matched; no early-down / 3rd-down mix-ups

### Draft% and FBS%

```
Draft% = P(declares) × P(selected)

P(selected) =
  Φ((ln cut − ln xPick) / sd)

P(declares) =
  1 / (1 + (xPick / mid)^b)
  underclass: mid 973, b 1.1
  senior:     mid 829, b .40
```

- xPick: expected pick from the mock draft
- fall: cut 344, sd 1.28; Dec-Feb: 260, .72; final month: 265, .56
- declare rates: ranked underclassmen 94% · true seniors 69% (4th-years with eligibility often stay) · redshirt seniors and grads 100%
- e.g. ranked junior, xPick 100, October: Φ((ln 344 − ln 100) / 1.28) = Φ(.97) = .83; × .92 declare = 77%
- fit: PFF dated big boards, 2020-26 drafts
- leave one draft out (2021-25 fall boards, n = 701): log loss .506 vs .825 for the previous version
- board total: 246 picks (257 less ~3% to D2, D3 and abroad, less ~3.8 K/P) + K 1.83, P 2.0
- FBS% (FCS tab): P(on an FBS roster next season); fit on FCS-to-FBS moves 2023-26; AUC .731
- FBS% by class: 2nd- to 4th-years highest; 5th-years 2.7%; capped at 1 − Draft%

### NIL: yNIL, xNIL and zNIL

```
zNIL = xNIL − yNIL
```

- source: On3 valuations
- yNIL: likely pay entering the season = share of program budget (P4 ~$20M · G5 $3M · FCS $0.4M), split by preseason information (prior production, On3 grade, recruiting, position)
- xNIL: current open-market value from FV, position, role
- G5 player at P4 starter level: priced in the P4 market; FCS player at higher-level starter level: 40% of that price (collected only by transferring)
- median xNIL: FBS $177K · FCS $14K (2026-10-14)
- zNIL: value gained or lost this season; team sum = program development measure
- staff score: 20% zNIL, as log((xNIL + $250K) / (yNIL + $250K)), ranked within role and P4/G5

### Transfer%

- P(on another FBS or FCS roster next season)
- ridge logistic regression; every FBS and FCS player, 2024 and 2025 cycles, followed to next-year rosters (NIL era only)
- inputs: class, recruiting rank, playing time, production, team record, head-coach change odds, level, distance from home, position, interactions
- top-quarter producers at programs 1+ SD above average: 8.5% moved
- WR whose QB transfers: higher Transfer%
- moved by distance from home: 10.6% within 50 miles · 19% at 600-1,200 miles
- out of time, 2025-26 cycle: AUC .738; top 10% by Transfer% moved 40.6% vs 15.3% base rate
- Transfer% + stay + exit (draft or eligibility) = 100%

### ARKLIST, breakouts and the portal

- ARKLIST: ★ on the board tabs; starred players
- breakouts: first- and second-year skill players; touches and targets up over the last two games
- portal: this season's transfers with FV; team net NFL value, in minus out

## The mock draft

Projection of the actual 2027 draft, not the ARK board.

**Expected pick**:

```
ln xPick = w ln(consensus rank)
         + (1 − w) ln(model rank)
w = .55 + .3 √(boards ranking / 9)
```

- 9/9 boards: w = .85 (85% market)
- rank-to-pick curve: 2020-25 final boards; position, class, conference, size add nothing once ranked; missing combine invite and 40 time do

**Needs**:

```
q = max(1 − .13 ln(pick),
        pay / top pay)
need = ½ (1 − starters' q)
     + ½ rank(room) / 31
u = −ln xPick + need weight × need
```

- position rooms: ESPN rosters and contracts
- q: draft capital on a rookie deal, or pay vs top of position market; cut for age and expiring deal
- penalties: doubling up, set QB, positional runs
- traded picks: Wikipedia; order: full NFL tiebreakers (191 of 191 R1 slots, 2020-25)

**Trades** (rounds 1-2):

```
value(pick) =
  e^(−.148 × (pick − 1)^.698)
```

- Massey-Thaler pick value curve; pick 10 ≈ ½ pick 1; pick 32 ≈ ⅕
- trade-up: team up to 20 slots back; player worth more than its best option at its own pick; a team picking in between might take the player
- price: own pick + smallest later picks covering the gap + 5%
- same division: ~x.5 (2010-25: 18 trades vs 45 expected)
- calibrated to ~5 first-round trade-ups a year (real drafts)
- value chip: FV a tier above the ARK board at that slot and drafted 2.5x+ later than board rank · reach: the mirror
- pick report: need, slot vs projection, consensus and ARK board, position change, type and badges, strengths and concerns from the numbers

[![Mock draft with the first pick's report open: need, slot, type, badges, strengths and concerns](/img/football-arkboard/mock-report.webp)](/img/football-arkboard/mock-report.webp)

- replay 2020-25 drafts in real order: position-by-round count error 35.0 vs 37.3 board order
- positional adjustment, R1-3 error 2015-25: 33.6 -> 29.6

## Recruits

```
xFV = P(on field) × FV if on field
    + (1 − P) × 20
```

- fit: ESPN 2023-26 classes vs this season's board, whole programs held out
- inputs passed: ESPN grade, 247 composite and its gap to ESPN's grade, offer quality (strength of programs recruiting)
- AUC .652 (on field) · r .40 (FV)
- xFV runs low (most recruits never play much); compare players on FV if on field
- ARK stars, projected year-3 FV bands: 5 = top 3% of the board · 4 = top 10% · 3 = above median · 2 = on board · 1 = off it
- R² .148 vs .131 at industry star shares, .111 ESPN stars
- 5-star share: ARK ~3% vs industry 0.6%
- 5-star+: top six per class by projected FV; sweep 3-40 per class, elite outcomes (top 0.5% of board) ~20% up to 20 a class; rarest cut kept
- half stars (1.5-4.5): tier split where xFV passes the midpoint to the next tier
- ▲: ARK above industry

[![2027 class with ARK stars, 5-star+ and industry stars side by side](/img/football-arkboard/cfb-class.webp)](/img/football-arkboard/cfb-class.webp)

- other tabs: 2028 class · 2029 class (first look) · class rankings · redshirts
- redshirts: only driver passed = played in 1-4 games (t 4.47)

## Teams

### Rankings and season odds

- ARK Top 25: game model neutral-field rating; AP and Coaches polls alongside
- rating components: Elo · efficiency · special teams · situational
- winners picked, 2026 (out of sample, games with a ranked team): ARK 85.5%, AP 85.5%
- season odds: 10,000 simulated seasons; projected wins, conference title game, title, playoff, bowl

[![ARK Top 25 next to the AP and Coaches polls](/img/football-arkboard/cfb-rank.webp)](/img/football-arkboard/cfb-rank.webp)

### Team talent, staff and the coaching market

- team talent: projected starting talent, Elo, TvE, team xNIL
- staff: score for every head coach and coordinator; scheme fingerprints (4th-down go rate, tempo, run rate, havoc) as FBS percentiles
- coaching market: pay from USA Today salary database (HC 2006-25, assistants 2009-24)
- value = log(pay) fit on program and results; out-of-sample R² HC .87, coordinators .75
- Elo, TvE, zNIL, staff score: no pay signal once those are in (not priced by the market); surplus = that gap
- coaching jobs: P(job opens), model on 2010-25 school seasons, test 2020-25 AUC .72; likely hires
- P4 openings filled by: sitting FBS HC 42% · coordinator 25% · other 33%
- coordinators retained: HC stays 72% · HC hired away 43% follow

[![Coaching jobs tab with each job's odds and likely hires](/img/football-arkboard/cfb-jobs.webp)](/img/football-arkboard/cfb-jobs.webp)

### Team builder

Offseason plan per FBS program from its NIL budget:

1. budget = Σ roster yNIL × 1.04
2. hold back money for the incoming class
3. keep: returners at market price × P(stay), best value per dollar first
4. sign: likely transfers and FCS move-ups who would start, ranked by

   ```
   WAR per $ × need × Transfer%
     × landing odds
   ```

   - landing odds: P(this school | moves); fit on 7,027 transfers, 2024-25 (level step, program talent, open playing time at the position, distance from home)
   - WR landing at the departed QB's new school: 7.2x chance
   - 2025-26: 39% of transfers from programs whose HC took another FBS job followed the HC
5. let walk: up to two returners, when their cost signs a player worth 2x+ their edge over the next man up

```
cost per $ = Φ((spend − budget)
              / (.25 × budget))
```

- budget: soft target; program goes over only when the player is worth the cost
- next-season FV: development step per returner, scaled so league total talent next season = this season

[![Team builder plan in brief for LSU: reload, money, keep, move, sign, next season](/img/football-arkboard/cfb-builder.webp)](/img/football-arkboard/cfb-builder.webp)

## Games

### The game model

```
rating = Elo + adj. EPA/play
margin = Δrating + home 2.4 + rest
       + time zones + travel
       + altitude
       + P4 vs G5 5.9
total  = plays × points/play
       + wind + rain + cold + FCS
```

- EPA: opponent-adjusted, garbage time out; ridge regression shrunk toward a preseason prior (last season's SP+, this season's talent, returning production)
- win, cover, over: normal distribution around model margin and total
- input kept only if it lowers log loss in both fit and test season; passed: success rate; failed: explosiveness, red-zone points per trip, byes, short weeks, body clock, market ratings from earlier lines
- also failed (Oct 18): conversion rates by down and distance over the league's rate from the same distance (3rd and short, medium, long; 4th downs), 3rd and medium raw (helps alone, t -1.7, nothing on top of the kept inputs), kicking over expected by distance, kicker range (50+)
- fit 2025, test 2026: log loss .388 vs .420 Elo alone
- margin MAE: model 13.2 · closing line 11.8 (closing line more accurate)

[![Ohio State at Indiana game card: win probability, model vs market, projected score and each side's top players](/img/football-arkboard/cfb-games.webp)](/img/football-arkboard/cfb-games.webp)

### Projections and injuries

- projections: top 300 offensive players by PPR points; this season's per-game lines scaled by opponent
- P(plays) by status: out 0 · doubtful .02 · questionable .56 (.47 if missed last game) · probable .95; NFL 2016-25 rates updated by logged college statuses
- no status, starter: played last week .89 · missed 1 .51 · missed 2 .31 · missed 3+ .16
- teammate out: volume moves to the players still active
- 2024-26 holdout RMSE: starters 9.50 -> 9.16 · missed last game 6.73 -> 5.54
- season-ending injury: −1 FV (−2 ACL or Achilles)

### Upset and favorite picks, units

- rule: model has the market underdog winning outright and is 4+ points off the line
- backtest 2025-26 (as of 2026-10-14): moneyline at close 53-68 (n = 121), −1.2%; underdog won 43.8%
- vs opening spread: 67-50 (n = 117), +9.3%; line moved toward the pick 1.7 points on average
- favorite rule: model favorite at −200 to −105 on the moneyline, model margin 4+ points past the line
- favorite backtest (as of 2026-10-14): moneyline at close 36-8 (n = 44), +35.7%; 2025 +43.4% (n = 37), 2026 −5.2% (n = 7)

```
Kelly = (b × p − q) / b
```

- b = payout per unit · p = model win chance · q = 1 − p
- units: scaled to 0.25-3, mean 1
- sized moneyline: −5.5% (largest edges did worst); both on the tab

[![Week 7 upset picks with units, and the backtest table](/img/football-arkboard/picks.webp)](/img/football-arkboard/picks.webp)

## NFL

### NFL WAR

```
WAR    = .6 × AV WAR + .4 × XV
AV WAR = (AV − line × snap share)
         × .091
```

- XV: our own value from the stat line (EPA, CPOE, pressures, stops, missed tackles, coverage allowed, penalties), each part weighted by how much it moves team margin (2018-25)
- the blend: when a regular sits, a point of blended value costs the team a point of margin (2,127 games, held-out seasons); AV WAR alone explains less than half as much of those swings, and next-season and contract tests are a tie
- AV rebuilt from nflverse play data (PFR posts AV only after a season)
- .091 = wins per team AV (2021-25, r .86)
- line: replacement AV by spot (QB, RB, outside and slot WR, TE, tackle, interior line, EDGE, DT, LB, outside and nickel CB, S); blend of games a regular sat (2,639), veteran contracts, AV
- replacement team: 3 of 17 wins; team WAR sums to wins − 3
- defense: AV credits pressures, not sacks (pressures repeat); EDGE season-to-season r .25 -> .45
- team WAR by position group; QB value = QB term, points a game over replacement

[![NFL WAR leaders](/img/football-arkboard/nfl-war.webp)](/img/football-arkboard/nfl-war.webp)

### NFL games, power rankings and season odds

```
margin = Elo + adj. EPA/play
       + QB vs team's recent QB play
       + rest + home + injuries
       + market rating (earlier closing spreads)
total  = points + EPA + dome
       + market total (earlier closing totals)
```

- EPA half-life: 12 games
- injury cost per listed player = WAR per game × 36 points per win × P(miss)
- P(miss), 2016-25: out 1 · doubtful .98 · questionable .25 (.5 if missed last game) · probable .05
- questionable QB: 60/40 blend with the next healthy QB
- held out 2021-25: margin MAE model 10.06 (10.13 before market ratings) · closing line 9.76; totals 10.50 (10.63) · line 10.31; no edge on the close, no NFL picks
- tested and not kept (Oct 2026): success rate, garbage-time-free EPA, early downs, 3rd down, red zone, explosiveness, stuff rate, line yards, field position, CPOE, special teams EPA, 4th-down aggressiveness, pass rate over expected, coach cover record, first-year coach, wind, recent form, roster WAR, QB draft prior, injuries by unit; none beat the model out of sample once market ratings and Elo are in; nor did travel, time zones, cold games, altitude, byes, short weeks or referees
- also not kept (Oct 18): 3rd-down conversion by distance (short, medium, long, over the league's rate from the same distance), 4th-down conversion, goal-to-go, two-minute offense, no-huddle rate, penalty yards, 2-point tries, the kicker over expected by distance and range (50+), kicker x close game, kicker x wind or cold, 4th-down conversion x aggressiveness. 3rd-down conversion over expected fits a negative weight: it regresses, and EPA already counts it
- picks: the college board's two fixed rules. upset = model has the market underdog winning, 4+ pts off the line; favorite = moneyline favorite -105 to -200 the model likes by 4+ more. Kelly units, mean 1u; logged at the line when flagged, graded with CLV
- picks backtest, 2015-25 at the close: upsets 83-103 on the moneyline, +6.6% (2021-25: -7.0%); favorites 41-20, +11.4% (2021-25: +5.1%)
- power rankings: neutral-field points with the current QB
- season odds: 10,000 simulated seasons

[![NFL game cards with the model line, win probability and projected score](/img/football-arkboard/nfl-games.webp)](/img/football-arkboard/nfl-games.webp)

### Fantasy projections, rankings and breakouts

- stat lines (attempts, targets, yards, TDs ...): ridge regression per stat and position
- scoring: PPR · half PPR · standard; this week and rest of season; K and DST
- context inputs passed: volume left by teammates out; 1.5-game half-life role term beside the long one

PPR MAE per game, held out 2021-25:

| | Model | Baseline |
| :---: | :---: | :---: |
| QB | 6.11 | 6.51 |
| RB | 5.08 | 5.40 |
| WR | 5.26 | 5.56 |
| TE | 4.61 | 4.99 |

- tiers: natural breaks in projected points, ~1 tier per 6 players
- VOR = points over first non-starter at the position, 12-team league (QB13, RB30, WR31, TE13)
- breakouts: below a starter's line, 20%+ odds of reaching it over the next four games; held out hit rate 22-30% flagged vs 3-8% rest; points at the starting job shown

[![NFL fantasy rankings with tiers and VOR](/img/football-arkboard/nfl-rank.webp)](/img/football-arkboard/nfl-rank.webp)

### Injuries

- sources: league practice and game report, ESPN, Rotoballer; newest item wins
- after the team's weekly report: off the report, full practice, or no designation on the final report = cleared
- before the report: last week's tag carries at the 2021-25 rate (questionable .84 · doubtful .55 · out .38)
- refresh: twice a day, plus Sunday afternoon for late-game inactives

## GFX

- GFX button: 4:5 card
- views: board · game previews · mock draft by round with trades · upset picks · Top 25 · recruit classes · team builder plans
- site palette (purple, teal, lilac), pixel font, pixel-art badge and star icons

[![GFX card for Ohio State at Indiana](/img/football-arkboard/gfx-game.webp)](/img/football-arkboard/gfx-game.webp)

[![GFX card for LSU's 2027 offseason plan](/img/football-arkboard/gfx-builder.webp)](/img/football-arkboard/gfx-builder.webp)
