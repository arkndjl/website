+++
title = "College Football / NFL Draft :: ARKBOARD"
url = "/arkboard/college-football/"
description = "College Football ARKBOARD: FBS + FCS players graded on the 20-80 FV scale; 2027 draft board; game projections, live scores; season odds; transfer portal, Transfer%; team builder offseason plans; recruit projections, next-season rosters; breakouts; team talent; coaching staffs. auto-updated in season."
keywords = ["arkboard", "college football", "nfl draft", "2027 nfl draft", "future value", "20-80 scale", "big board", "game projections", "transfer portal"]
draft = false
+++

{{< arknav >}}

{{< winpane title="college_football.exe :: CFB 2026-27" icon="football" sprite="px/hero-football" status="PFN · On3 · ESPN · CFBD · Rotoballer" class="winpane--art" />}}

{{< wintabs groups="players:all,all FBS,all FCS,draft board,WAR leaders,ARKLIST,past seasons,breakouts,portal|games:games,picks,game table,top performers,projections|teams:rankings,season odds,team talent,staff,coaching jobs,coach pay,team builder|recruits:2027 class,2028 class,2029 class,class rankings,redshirts,recruit model|model & draft:predictive mock,blended mock,conviction mock,udfa signings,model" side="true" label="College Football views" >}}
{{< cfbboard title="CFB 2026-27 :: every graded player, FBS + FCS" tab="all" >}}
{{< cfbboard title="CFB 2026-27 :: every graded FBS player" tab="all FBS" preset="fbs" >}}
{{< cfbboard title="CFB 2026-27 :: every graded FCS player" tab="all FCS" preset="fcs" >}}
{{< cfbboard title="CFB 2026-27 :: 2027 draft board" tab="draft board" preset="d27" >}}
{{< cfbboard title="WAR leaders :: college WAR, FBS + FCS" tab="WAR leaders" preset="war" >}}
{{< cfbboard title="ARKLIST :: starred players" tab="ARKLIST" preset="star" >}}
{{< cfbboard title="past seasons :: FV after each FBS season" tab="past seasons" preset="past" >}}
{{< cfbbreakout title="breakout watch :: 1st-2nd yr QB/RB/WR/TE, touches + targets up" tab="breakouts" >}}
{{< cfbportal title="transfer portal :: 2026 moves" tab="portal" >}}
{{< cfbgames title="games" tab="games" >}}
{{< cfbpicks title="picks" tab="picks" >}}
{{< cfbgametable title="game table" tab="game table" >}}
{{< cfbtop title="top performers" tab="top performers" >}}
{{< cfbproj title="projections" tab="projections" >}}
{{< cfbrank title="team rankings :: ARK, AP and Coaches Top 25" tab="rankings" >}}
{{< cfbsim title="season odds :: 10,000 simulated seasons" tab="season odds" >}}
{{< cfbteams title="team talent :: talent, Elo, TvE, xNIL" tab="team talent" >}}
{{< cfbstaff title="staff :: head coaches and coordinators" tab="staff" >}}
{{< cfbjobs title="coaching jobs :: projected openings and hires" tab="coaching jobs" >}}
{{< cfbcoachpay title="coach pay :: market value vs public pay" tab="coach pay" >}}
{{< cfbbuilder title="team builder :: offseason plan per team, NIL budget" tab="team builder" >}}
{{< cfbrecruits view="class" title="2027 class :: projected FV, every commit" tab="2027 class" >}}
{{< cfbrecruits view="future" year="2028" title="2028 class :: projected FV, every listed recruit" tab="2028 class" >}}
{{< cfbrecruits view="future" year="2029" title="2029 class :: projected FV, listed recruits" tab="2029 class" >}}
{{< cfbrecruits view="teams" title="class rankings :: 2027 class + next-season roster" tab="class rankings" >}}
{{< cfbrecruits view="redshirts" title="redshirts :: rostered, 0 snaps, next-season projection" tab="redshirts" >}}
{{< cfbrecruits view="model" title="recruit model :: method + out-of-sample test" tab="recruit model" >}}
{{< cfbmock src="cfb_mock_pred" mode="pred" title="predictive mock :: consensus + model, 7 rounds" tab="predictive mock" >}}
{{< cfbmock mode="blend" title="blended mock :: predictive/conviction midpoint, 7 rounds" tab="blended mock" >}}
{{< cfbmock src="cfb_mock_conv" mode="conv" title="conviction mock :: model board + team fit, 7 rounds" tab="conviction mock" >}}
{{< cfbudfa src="cfb_mock_pred" title="udfa signings :: predictive mock, after round 7" tab="udfa signings" >}}
{{< cfbmodel title="model report :: walk-forward backtest" tab="model" >}}
{{< /wintabs >}}

{{< desk >}}
{{< deskcol >}}
{{< wintable title="fv conversions :: football (nfl outcome)" gfx="1" icon="football" >}}
| FV | NFL outcome (measured) | Prime WAR | WAR/yr | Per class | Draft value |
| :---: | ----- | :---: | :---: | :---: | ----- |
| 80 | 3+ time All-Pro | 1.04 | 0.32 | ~3 | top 3 pick |
| 75 | 2-time All-Pro | 0.89 | 0.25 | ~2 | top 5 pick |
| 70 | All-Pro | 0.67 | 0.19 | ~4 | top 10 pick |
| 65 | 3+ Pro Bowls | 0.49 | 0.15 | ~7 | top 15 pick |
| 60 | Pro Bowler | 0.40 | 0.13 | ~12 | 1st round |
| 55 | 6+ seasons as a starter | 0.31 | 0.10 | ~25 | late 1st / 2nd round |
| 50 | 4+ seasons as a starter | 0.19 | 0.07 | ~32 | 2nd–3rd round |
| 45 | 2+ seasons as a starter | 0.09 | 0.05 | ~43 | rounds 3–4 |
| 40 | rotation, 48+ games | 0 | 0.02 | ~64 | rounds 4–6 |
| 35 | backup, 16+ games | 0 | 0.01 | ~98 | late round |
| 30 | drafted / camp roster | 0 | 0 | ~150 | late round / UDFA |
| 20 | non-NFL | — | 0 | — | — |
{{< /wintable >}}
{{< fvav title="fv to war :: NFL expected, college this season" >}}
{{< wintable title="football war :: how it's built" icon="football" >}}
| | College WAR | NFL WAR |
| ----- | ----- | ----- |
| Value | snap share × (line + weight × quality); points of margin a game over a replacement starter. line = margin lost when an average starter at the spot sits: QB 2.7 (missed-game estimate 2.65, 4,995 regular-season FBS games 2019-25, games not played; bowls excluded: opt-outs), RB 1.7, EDGE 1.4, WR 1.35 (slot 1.2), CB 1.3 (nickel 1.1), S 1.1, DT 1.0, LB 1.0, OT .9, TE .8, interior OL .8. non-QB lines: blend of missed games, NFL spot values, position grade (box scores too thin alone). QB share of college WAR 13%; NFL 14%. QB own slope 1.25 pts per SD of quality; remainder to offensive teammates by snap share (QB absence costs .97 pts a game more per SD) | NFL AV a season over a replacement at the spot (QB, RB, outside / slot WR, TE, OT, IOL, EDGE, DT, LB, outside / nickel CB, S) × snap share. defense AV: pressures (sacks repeat less), stops, plays on the ball, each at play-by-play EPA. line: blend of margin lost when a regular sat (2,639 games), veteran contracts, AV. by FV: WAR a season of drafted players (2016-21 classes) at the FV's AV a season; busts and backup years in |
| Wins | 1 pt of margin a game = .0189 win% (928 FBS team seasons 2019-25, r .91; 2026 test r .88); × 12 games | 1 AV = .091 wins (team wins on team AV, 160 team seasons 2021-25; r .86; leave-one-season-out .091-.099) |
| WAR | share × (line + weight × quality) × .227 | (AV − line × snap share) × .091 |
| WAA | WAR − share × line: wins over an average starter at the position (WAR leaders tab); comparable across positions | wins over an average regular at the spot (NFL WAR leaders) |
| Replacement | replacement-starter lineup: .18 win% (2 of 12); average team's starters: 3.8 WAR | replacement team: 3 of 17 wins; team WAR = wins − 3 (5.5 at 8.5 wins) |
| By FV | FBS tier median, this season: FV 50 .33, FV 60 .43 | WAR/yr = expected season at the FV, busts and backup years in: FV 80 .32, 60 .13, 50 .07, 40 .02. Prime WAR = season at the FV's outcome: All-Pro = top 4% of regulars' seasons (.67), Pro Bowl top 14% (.40), 4-year starter = median regular (.19), 2021-25 |
{{< /wintable >}}
{{< /deskcol >}}
{{< deskcol >}}
{{< fvdist title="fv curve :: all FBS vs draft eligible" >}}
{{< fvnil title="fbs fv to xNIL :: xNIL by FV tier, FBS market" >}}
{{< fvnil title="fcs fv to xNIL :: xNIL by FV tier, FCS market; discount vs FBS at equal FV" div="fcs" >}}
{{< cfbfcs title="fcs translation :: FCS on the FBS scale" >}}
{{< winlist title="cfb.exe" icon="football" >}}
- [How the Football ARKBOARD Works](/posts/football-arkboard-every-feature/) | method | Oct 14
- [PFN impact rankings](https://www.profootballnetwork.com/cfb-hq/impact-rankings/quarterback) | production source | live
- [On3 college rankings](https://www.on3.com/college/rankings/player/football/2026/) | talent source | live
- [CollegeFootballData](https://collegefootballdata.com) | recruiting, SP+, advanced stats | live
- [PFN industry consensus big board](https://www.profootballnetwork.com/nfl-draft-hq/industry-consensus-big-board) | scouting consensus: PFN, CBS, ESPN, James Foster, NBC, The Athletic, Yahoo | live
- [Tankathon NFL big board](https://www.tankathon.com/nfl/big_board) · [PFF big board](https://www.pff.com/draft/big-board) · [Kiper big board](https://www.espn.com/nfl/draft2027/story/_/id/50182998/2027-nfl-draft-rankings-kiper-big-board-top-prospects) | consensus boards 8, 9 and 10 | live
- [Rotoballer college news](https://www.rotoballer.com/player-news?sport=cfb) · [ESPN injuries](https://www.espn.com/college-football/injuries) | availability | live
- ARKBOARD · hand-graded Big Board and Mock Draft | end of season | coming
{{< /winlist >}}
{{< /deskcol >}}
{{< /desk >}}
