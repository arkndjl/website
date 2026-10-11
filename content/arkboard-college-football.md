+++
title = "College Football / NFL Draft :: ARKBOARD"
url = "/arkboard/college-football/"
description = "The College Football ARKBOARD: every graded FBS and FCS player on the 20-80 FV scale, the 2027 draft board, game projections with live scores, season odds, the transfer portal, Transfer% and team builder offseason plans, recruit projections and next season's rosters, breakouts, team talent and coaching staffs. updates automatically through the season."
keywords = ["arkboard", "college football", "nfl draft", "2027 nfl draft", "future value", "20-80 scale", "big board", "game projections", "transfer portal"]
draft = false
+++

{{< arknav >}}

{{< winpane title="college_football.exe :: CFB 2026-27" icon="football" sprite="px/hero-football" status="PFN · On3 · ESPN · CFBD · Rotoballer" class="winpane--art" />}}

{{< wintabs groups="players:all,all FBS,all FCS,draft board,ARKLIST,breakouts,portal|games:games,game table,top performers,projections|teams:rankings,season odds,team talent,staff,coaching jobs,coach pay,team builder|recruits:2027 class,class rankings,redshirts,recruit model|model & draft:mock draft,model" side="true" label="College Football views" >}}
{{< cfbboard title="CFB 2026-27 :: every graded player, FBS + FCS" tab="all" >}}
{{< cfbboard title="CFB 2026-27 :: every graded FBS player" tab="all FBS" preset="fbs" >}}
{{< cfbboard title="CFB 2026-27 :: every graded FCS player" tab="all FCS" preset="fcs" >}}
{{< cfbboard title="CFB 2026-27 :: 2027 draft board" tab="draft board" preset="d27" >}}
{{< cfbboard title="ARKLIST :: my favourite players" tab="ARKLIST" preset="star" >}}
{{< cfbbreakout title="breakout watch :: young players whose role is growing" tab="breakouts" >}}
{{< cfbportal title="transfer portal :: 2026 moves" tab="portal" >}}
{{< cfbgames title="games" tab="games" >}}
{{< cfbgametable title="game table" tab="game table" >}}
{{< cfbtop title="top performers" tab="top performers" >}}
{{< cfbproj title="projections" tab="projections" >}}
{{< cfbrank title="team rankings :: AP, Coaches and ARK Top 25" tab="rankings" >}}
{{< cfbsim title="season odds :: 10,000 simulated seasons" tab="season odds" >}}
{{< cfbteams title="team talent :: talent, Elo, TvE, xNIL" tab="team talent" >}}
{{< cfbstaff title="staff :: head coaches and coordinators" tab="staff" >}}
{{< cfbjobs title="coaching jobs :: which open after the season, and who fills them" tab="coaching jobs" >}}
{{< cfbcoachpay title="coach pay :: market value vs public pay" tab="coach pay" >}}
{{< cfbbuilder title="team builder :: offseason plans from the NIL budget" tab="team builder" >}}
{{< cfbrecruits view="class" title="2027 class :: every commit's projected FV" tab="2027 class" >}}
{{< cfbrecruits view="teams" title="class rankings :: the 2027 class and next season's roster" tab="class rankings" >}}
{{< cfbrecruits view="redshirts" title="redshirts :: on a roster, no snaps yet, projected for next season" tab="redshirts" >}}
{{< cfbrecruits view="model" title="recruit model :: how it works and the out-of-sample test" tab="recruit model" >}}
{{< cfbmock title="2027 NFL mock draft (model) :: all 7 rounds" tab="mock draft" >}}
{{< cfbmodel title="model report :: walk-forward backtest" tab="model" >}}
{{< /wintabs >}}

{{< desk >}}
{{< deskcol >}}
{{< wintable title="fv conversions :: football (nfl outcome)" gfx="1" icon="football" >}}
| FV | NFL outcome (measured) | NFL WAR/yr | Per class | Value of a… |
| :---: | ----- | :---: | :---: | ----- |
| 80 | 3+ time All-Pro | 0.84 | ~3 | top 3 pick |
| 75 | 2-time All-Pro | 0.74 | ~2 | top 5 pick |
| 70 | All-Pro | 0.64 | ~4 | top 10 pick |
| 65 | 3+ Pro Bowls | 0.56 | ~7 | top 15 pick |
| 60 | Pro Bowler | 0.48 | ~12 | 1st round |
| 55 | 6+ seasons as a starter | 0.41 | ~25 | late 1st / 2nd round |
| 50 | 4+ seasons as a starter | 0.34 | ~32 | 2nd–3rd round |
| 45 | 2+ seasons as a starter | 0.24 | ~43 | rounds 3–4 |
| 40 | rotational, 48+ games | 0.13 | ~64 | rounds 4–6 |
| 35 | backup, 16+ games | 0.07 | ~98 | late round |
| 30 | drafted / camp body | 0.00 | ~150 | late round / UDFA |
| 20 | non-NFL | −0.04 | — | — |
{{< /wintable >}}
{{< fvav title="fv to war :: each grade in the NFL and this college season" >}}
{{< wintable title="football war :: how AV becomes wins" icon="football" >}}
| | College WAR | NFL WAR |
| :--- | ----- | ----- |
| Measures | what he has been worth to his team this season | what his FV grade is worth a season in the NFL |
| Built from | season AV: snap share × position weight × (quality + 1 SD), quality = Stat+ with badges and FV | expected NFL AV a season at his FV (2010-19 drafts) |
| Replacement | a starter 1 SD below an average starter | FV 30: a camp body or undrafted player, 0.4 AV |
| AV to points | 1 AV = 0.42 points of margin a game (fit on 2024-25 team margin) | 1 AV ≈ 3.7 points (PFR gives an average offense 100 AV for ~369 points) |
| Points to wins | 0.0184 wins per point of margin a game (FBS 2019-25, r .91) | 35.7 points a win (NFL 2010-24, r .91) |
| Formula | season AV × 0.42 × 12 games × 0.0184 = **0.093 WAR per AV** | (AV − 0.4) × 3.7 / 35.7 = **0.10 WAR per AV** |
| Example | top QB this season ≈ 3 WAR, top WR ≈ 0.6 | FV 80 ≈ 0.84 a season, FV 50 ≈ 0.34 |
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
