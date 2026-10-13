+++
title = "College Football / NFL Draft :: ARKBOARD"
url = "/arkboard/college-football/"
description = "The College Football ARKBOARD: every graded FBS and FCS player on the 20-80 FV scale, the 2027 draft board, game projections with live scores, season odds, the transfer portal, Transfer% and team builder offseason plans, recruit projections and next season's rosters, breakouts, team talent and coaching staffs. updates automatically through the season."
keywords = ["arkboard", "college football", "nfl draft", "2027 nfl draft", "future value", "20-80 scale", "big board", "game projections", "transfer portal"]
draft = false
+++

{{< arknav >}}

{{< winpane title="college_football.exe :: CFB 2026-27" icon="football" sprite="px/hero-football" status="PFN · On3 · ESPN · CFBD · Rotoballer" class="winpane--art" />}}

{{< wintabs groups="players:all,all FBS,all FCS,draft board,WAR leaders,ARKLIST,breakouts,portal|games:games,picks,game table,top performers,projections|teams:rankings,season odds,team talent,staff,coaching jobs,coach pay,team builder|recruits:2027 class,2028 class,2029 class,class rankings,redshirts,recruit model|model & draft:mock draft,model" side="true" label="College Football views" >}}
{{< cfbboard title="CFB 2026-27 :: every graded player, FBS + FCS" tab="all" >}}
{{< cfbboard title="CFB 2026-27 :: every graded FBS player" tab="all FBS" preset="fbs" >}}
{{< cfbboard title="CFB 2026-27 :: every graded FCS player" tab="all FCS" preset="fcs" >}}
{{< cfbboard title="CFB 2026-27 :: 2027 draft board" tab="draft board" preset="d27" >}}
{{< cfbboard title="WAR leaders :: college WAR, every FBS and FCS player" tab="WAR leaders" preset="war" >}}
{{< cfbboard title="ARKLIST :: my favourite players" tab="ARKLIST" preset="star" >}}
{{< cfbbreakout title="breakout watch :: young players whose role is growing" tab="breakouts" >}}
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
{{< cfbjobs title="coaching jobs :: which open after the season, and who fills them" tab="coaching jobs" >}}
{{< cfbcoachpay title="coach pay :: market value vs public pay" tab="coach pay" >}}
{{< cfbbuilder title="team builder :: offseason plans from the NIL budget" tab="team builder" >}}
{{< cfbrecruits view="class" title="2027 class :: every commit's projected FV" tab="2027 class" >}}
{{< cfbrecruits view="future" year="2028" title="2028 class :: two years out, every listed recruit" tab="2028 class" >}}
{{< cfbrecruits view="future" year="2029" title="2029 class :: three years out, a first look" tab="2029 class" >}}
{{< cfbrecruits view="teams" title="class rankings :: the 2027 class and next season's roster" tab="class rankings" >}}
{{< cfbrecruits view="redshirts" title="redshirts :: on a roster, no snaps yet, projected for next season" tab="redshirts" >}}
{{< cfbrecruits view="model" title="recruit model :: how it works and the out-of-sample test" tab="recruit model" >}}
{{< cfbmock title="2027 NFL mock draft (model) :: all 7 rounds" tab="mock draft" >}}
{{< cfbmodel title="model report :: walk-forward backtest" tab="model" >}}
{{< /wintabs >}}

{{< desk >}}
{{< deskcol >}}
{{< wintable title="fv conversions :: football (nfl outcome)" gfx="1" icon="football" >}}
| FV | NFL outcome (measured) | Prime WAR | WAR/yr | Per class | Value of a… |
| :---: | ----- | :---: | :---: | :---: | ----- |
| 80 | 3+ time All-Pro | 1.03 | 0.32 | ~3 | top 3 pick |
| 75 | 2-time All-Pro | 0.88 | 0.24 | ~2 | top 5 pick |
| 70 | All-Pro | 0.67 | 0.18 | ~4 | top 10 pick |
| 65 | 3+ Pro Bowls | 0.49 | 0.14 | ~7 | top 15 pick |
| 60 | Pro Bowler | 0.40 | 0.12 | ~12 | 1st round |
| 55 | 6+ seasons as a starter | 0.31 | 0.10 | ~25 | late 1st / 2nd round |
| 50 | 4+ seasons as a starter | 0.18 | 0.07 | ~32 | 2nd–3rd round |
| 45 | 2+ seasons as a starter | 0.08 | 0.05 | ~43 | rounds 3–4 |
| 40 | rotational, 48+ games | 0 | 0.02 | ~64 | rounds 4–6 |
| 35 | backup, 16+ games | 0 | 0.01 | ~98 | late round |
| 30 | drafted / camp body | 0 | 0 | ~150 | late round / UDFA |
| 20 | non-NFL | — | 0 | — | — |
{{< /wintable >}}
{{< fvav title="fv to war :: each grade in the NFL and this college season" >}}
{{< wintable title="football war :: how it's built" icon="football" >}}
| | College WAR | NFL WAR |
| ----- | ----- | ----- |
| Value | snap share × (his position's line + position weight × quality), in points of margin a game over a replacement starter. The line is what a team loses when an average starter at his spot sits: 5.1 points a game at QB (5,275 FBS games, 2019-25), then RB 1.5, EDGE 1.3, WR 1.2 (slot 1.1), CB 1.2 (nickel 1.0), S 1.0, LB .9, DT .85, OT .76, TE .72, interior line .67. Away from QB, college box scores are too thin to set these alone, so each blends missed games, the NFL's tested spot values and the position's grade. Offense carries 56% of a lineup's value, the share of margin it explains. A QB keeps 1.25 points per SD of quality and his offensive teammates share the rest, since a better QB's absence costs no more than an average one's | NFL AV a season over a replacement player at his spot (QB, RB, outside or slot WR, TE, tackle, interior line, EDGE, DT, LB, outside or nickel CB, S), charged by snap share. Each line blends what teams lost when a regular sat (2,639 games), veteran contracts and AV. By FV: what drafted players (2016-21 classes) at that FV's AV a season earned a season, busts and backup years in |
| Wins | 1 point of margin a game = .0189 win% (928 FBS team seasons, 2019-25; r .91, 2026 test r .88), over 12 games | 1 AV = .091 wins (team wins on team AV, 2021-25; r .84, each season left out .087-.096) |
| WAR | share × (line + weight × quality) × .227 | (AV − line × snap share) × .091 |
| WAA | WAR less his position's line: wins over an average starter at his position (the WAR leaders tab), so players compare across positions | wins over an average regular at his spot (the NFL WAR leaders) |
| Replacement | a lineup of replacement starters wins about .18 (2 of 12); the average team's starters add up to 3.8 WAR | a team of replacements wins 3 of 17; team WAR adds up to wins less 3 (5.5 for an 8.5-win team) |
| By FV | FV 50 median .30, FV 60 .41 this season (the tier's FBS players) | WAR/yr, the expected season at the FV with busts and backup years in: FV 80 .32, 60 .12, 50 .07, 40 .02. Prime WAR, a season at the FV's outcome: All-Pro is the top 4% of regulars' seasons (.67), Pro Bowl the top 14% (.40), a 4-year starter the median regular (.18), 2021-25 |
{{< /wintable >}}
{{< /deskcol >}}
{{< deskcol >}}
{{< fvdist title="fv curve :: all FBS vs draft eligible" >}}
{{< fvnil title="fbs fv to xNIL :: what each FV tier is worth on the FBS NIL market" >}}
{{< fvnil title="fcs fv to xNIL :: the FCS market, and its discount at equal FV" div="fcs" >}}
{{< cfbfcs title="fcs translation :: FCS on the FBS scale" >}}
{{< winlist title="cfb.exe" icon="football" >}}
- [College Football ARKBOARD 2026-27 (intro)](/posts/college-football-arkboard-2026-27/) | the project | Oct 2
- [PFN impact rankings](https://www.profootballnetwork.com/cfb-hq/impact-rankings/quarterback) | production source | live
- [On3 college rankings](https://www.on3.com/college/rankings/player/football/2026/) | talent source | live
- [CollegeFootballData](https://collegefootballdata.com) | recruiting, SP+, advanced stats | live
- [PFN industry consensus big board](https://www.profootballnetwork.com/nfl-draft-hq/industry-consensus-big-board) | scouting consensus: PFN, CBS, ESPN, James Foster, NBC, The Athletic, Yahoo | live
- [Tankathon NFL big board](https://www.tankathon.com/nfl/big_board) · [PFF big board](https://www.pff.com/draft/big-board) | consensus boards 8 and 9 | live
- [Rotoballer college news](https://www.rotoballer.com/player-news?sport=cfb) · [ESPN injuries](https://www.espn.com/college-football/injuries) | availability | live
- ARKBOARD · hand-graded Big Board and Mock Draft | end of season | coming
{{< /winlist >}}
{{< /deskcol >}}
{{< /desk >}}
