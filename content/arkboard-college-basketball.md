+++
title = "Basketball Prospects / CBB :: ARKBOARD"
url = "/arkboard/college-basketball/"
description = "Basketball Prospects (CBB) ARKBOARD: game projections (model line, win probability, projected score), ARK Ranking (power rankings), season odds and NCAA tournament odds (bids, seeds, Final Four, title) for every D-I team; every 2026-27 D-I player, the international prospects and NCAA D-II and D-III players (with D-1%, the chance of a D-I roster next season) graded on the 20-80 FV scale (peak NBA XPM), updated daily in season; 2027 NBA mock drafts (predictive, blended, conviction); HS recruit boards for the 2027-2029 classes on the FV value scale, with class rankings; FV drivers backtested against NBA careers (On3, 247, Barttorvik); past preseason boards with outcomes; ARKBOARD NBA 2026 final top 30."
keywords = ["arkboard", "ark ranking", "college basketball", "college basketball model", "ARK Ranking", "nba draft", "2027 nba draft", "future value", "20-80 scale", "big board", "barttorvik", "on3"]
draft = false
cover = "/og/college-basketball.png"
+++

{{< arknav >}}

{{< winpane title="basketball_prospects.exe :: CBB 2026-27" icon="basketball" sprite="px/hero-basketball" status="daily in season · Barttorvik · On3 · 247 · ESPN" class="winpane--art" />}}

{{< wintabs groups="players:all,draft board,WAR leaders,stats,true freshmen,breakouts,ARKLIST|rosters:depth chart,returning,lineups,on/off,lineup leaders,backup watch|games:games,game table,top performers|teams:ARK Ranking,season odds,tournament odds,team talent,development,offense,defense|market:portal,NIL,team NIL,team builder,staff,coaching jobs,coach pay|recruits:2027 class,2028 class,2029 class,class rankings|mock draft:predictive mock,blended mock,conviction mock|model:fv model,recruit model,past boards,all-time FV" side="true" label="College Basketball views" >}}
{{< cbbboard title="CBB 2026-27 :: all players" tab="all" >}}
{{< lazytab tab="draft board" >}}
{{< rookies sport="cbb" src="data/cbb/draft.json" icon="basketball" title="draft board :: 2027 draft, predictive mock order" tab="draft board" >}}
{{< /lazytab >}}
{{< lazytab tab="WAR leaders" >}}
{{< rookies sport="cbb" src="data/cbb/war.json" icon="basketball" title="WAR leaders :: wins over replacement" tab="WAR leaders" >}}
{{< /lazytab >}}
{{< lazytab tab="stats" >}}
{{< rookies sport="cbb" src="data/cbb/stats.json" icon="basketball" title="stats :: season lines, Stat+" tab="stats" >}}
{{< /lazytab >}}
{{< rookies sport="cbb" icon="basketball" title="true freshmen :: FV and xBPM against recruiting rank" tab="true freshmen" >}}
{{< lazytab tab="breakouts" >}}
{{< rookies sport="cbb" src="data/cbb/breakouts.json" icon="basketball" title="breakout watch :: 1st-2nd yr, over the preseason projection" tab="breakouts" >}}
{{< /lazytab >}}
{{< arklist sport="college-basketball" title="ARKLIST :: college basketball + internationals" tab="ARKLIST" >}}
{{< backupwatch sport="cbb" title="backup watch :: 2nd/3rd string out-producing a starter (BPM)" tab="backup watch" >}}
{{< cbbmock mode="pred" title="predictive mock :: where they go, 2 rounds" tab="predictive mock" >}}
{{< cbbmock mode="blend" title="blended mock :: predictive/conviction midpoint, 2 rounds" tab="blended mock" >}}
{{< cbbmock mode="conv" title="conviction mock :: slot + what the market misprices, 2 rounds" tab="conviction mock" >}}
{{< cbbgames title="games" tab="games" >}}
{{< cbbgametable title="game table" tab="game table" >}}
{{< lazytab tab="top performers" >}}
{{< rookies sport="cbb" src="data/cbb/top.json" icon="basketball" title="top performers :: best single games, Game Score" tab="top performers" >}}
{{< /lazytab >}}
{{< cbbpower title="ARK Ranking" tab="ARK Ranking" >}}
{{< cbbsim title="season odds" tab="season odds" >}}
{{< cbbtourney title="ncaa tournament odds" tab="tournament odds" >}}
{{< lazytab tab="offense" >}}
{{< teamunits sport="cbb" view="offense" title="offense :: adjusted efficiency, four factors" tab="offense" >}}
{{< /lazytab >}}
{{< lazytab tab="defense" >}}
{{< teamunits sport="cbb" view="defense" title="defense :: adjusted efficiency allowed, four factors" tab="defense" >}}
{{< /lazytab >}}
{{< desk tab="fv model" >}}
{{< deskcol >}}
{{< cbbfv title="fv conversions :: basketball (peak XPM, measured)" >}}
{{< cbbfv view="calib" title="fv calibration :: what the grades became (2009-16 boards)" >}}
{{< fvcard sport="cbb" title="fv scorecard :: tier odds vs what happened, held out" >}}
{{< /deskcol >}}
{{< deskcol >}}
{{< cbbfv view="model" title="fv model :: drivers kept, out-of-sample evidence" >}}
{{< cbbfv view="intl" title="internationals :: league strength, what each input adds" >}}
{{< cbblive title="in season :: this season vs the preseason grade" >}}
{{< /deskcol >}}
{{< /desk >}}
{{< lazytab tab="team talent" >}}
{{< teamunits sport="cbb" feed="cbb_teamtabs" view="talent" title="team talent :: roster FV against the ARK rating" tab="team talent" >}}
{{< /lazytab >}}
{{< lazytab tab="returning" >}}
{{< teamunits sport="cbb" feed="cbb_teamtabs" view="returning" title="returning :: last season's minutes and WAR back" tab="returning" >}}
{{< /lazytab >}}
{{< lazytab tab="portal" >}}
{{< rookies sport="cbb" src="data/cbb/portal.json" icon="basketball" title="transfer portal :: 2026 moves, last season's WAR" tab="portal" >}}
{{< /lazytab >}}
{{< lazytab tab="development" >}}
{{< schooldev sport="cbb" title="development :: college BPM over On3 rank, by school and coach" tab="development" >}}
{{< /lazytab >}}
{{< lazytab tab="NIL" >}}
{{< cbbnil title="NIL :: xNIL, yNIL, zNIL, top 400" tab="NIL" >}}
{{< /lazytab >}}
{{< lazytab tab="team NIL" >}}
{{< cbbnil view="teams" title="team NIL :: every D-I roster" tab="team NIL" >}}
{{< /lazytab >}}
{{< cbbbuilder title="team builder :: offseason plan per team, NIL budget" tab="team builder" >}}
{{< lazytab tab="staff" >}}
{{< cbbstaff title="staff :: head coaches" tab="staff" >}}
{{< /lazytab >}}
{{< lazytab tab="coaching jobs" >}}
{{< cbbjobs title="coaching jobs :: projected openings and hires" tab="coaching jobs" >}}
{{< /lazytab >}}
{{< lazytab tab="coach pay" >}}
{{< cbbcoachpay title="coach pay :: market value vs public pay" tab="coach pay" >}}
{{< /lazytab >}}
{{< cbblineups view="units" title="lineups :: 5-man units, per 100 possessions" tab="lineups" >}}
{{< cbblineups view="onoff" title="on/off :: team net with each player on and off" tab="on/off" >}}
{{< lineupleaders sport="cbb" title="lineup leaders" tab="lineup leaders" >}}
{{< depthchart sport="cbb" title="depth chart :: every team" tab="depth chart" >}}
{{< lazytab tab="2027 class" >}}
{{< cbbrecruits view="class" year="2027" title="2027 class :: projected FV, every ranked recruit" tab="2027 class" >}}
{{< /lazytab >}}
{{< lazytab tab="2028 class" >}}
{{< cbbrecruits view="class" year="2028" title="2028 class :: projected FV, every ranked recruit" tab="2028 class" >}}
{{< /lazytab >}}
{{< lazytab tab="2029 class" >}}
{{< cbbrecruits view="class" year="2029" title="2029 class :: projected FV, ranked recruits" tab="2029 class" >}}
{{< /lazytab >}}
{{< lazytab tab="class rankings" >}}
{{< cbbrecruits view="teams" title="class rankings :: 2027 commits by expected NBA value" tab="class rankings" >}}
{{< /lazytab >}}
{{< lazytab tab="recruit model" >}}
{{< cbbrecruits view="model" title="recruit model :: target, drivers, held-out test" tab="recruit model" >}}
{{< /lazytab >}}
{{< lazytab tab="all-time FV" >}}
{{< fvalltime sport="cbb" tab="all-time FV" >}}
{{< /lazytab >}}
{{< desk tab="past boards" >}}
{{< deskcol >}}
{{< wintable title="ARKBOARD NBA 2026 :: final top 30 (jun 19)" icon="basketball" filter="FV,Team" >}}
| RK | Player | FV | Team |
| :---: | ----- | :---: | ----- |
| 1 | [Caleb Wilson](https://barttorvik.com/playerstat.php?year=2026&p=Caleb%20Wilson&t=North%20Carolina) | 65 | [North Carolina](https://barttorvik.com/team.php?team=North%20Carolina&year=2026) |
| 2 | [Darryn Peterson](https://barttorvik.com/playerstat.php?year=2026&p=Darryn%20Peterson&t=Kansas) | 65 | [Kansas](https://barttorvik.com/team.php?team=Kansas&year=2026) |
| 3 | [Cameron Boozer](https://barttorvik.com/playerstat.php?year=2026&p=Cameron%20Boozer&t=Duke) | 65 | [Duke](https://barttorvik.com/team.php?team=Duke&year=2026) |
| 4 | [AJ Dybantsa](https://barttorvik.com/playerstat.php?year=2026&p=AJ%20Dybantsa&t=BYU) | 60 | [BYU](https://barttorvik.com/team.php?team=BYU&year=2026) |
| 5 | [Aday Mara](https://barttorvik.com/playerstat.php?year=2026&p=Aday%20Mara&t=Michigan) | 55 | [Michigan](https://barttorvik.com/team.php?team=Michigan&year=2026) |
| 6 | [Yaxel Lendeborg](https://barttorvik.com/playerstat.php?year=2026&p=Yaxel%20Lendeborg&t=Michigan) | 55 | [Michigan](https://barttorvik.com/team.php?team=Michigan&year=2026) |
| 7 | [Brayden Burries](https://barttorvik.com/playerstat.php?year=2026&p=Brayden%20Burries&t=Arizona) | 50 | [Arizona](https://barttorvik.com/team.php?team=Arizona&year=2026) |
| 8 | [Dailyn Swain](https://barttorvik.com/playerstat.php?year=2026&p=Dailyn%20Swain&t=Texas) | 50 | [Texas](https://barttorvik.com/team.php?team=Texas&year=2026) |
| 9 | [Allen Graves](https://barttorvik.com/playerstat.php?year=2026&p=Allen%20Graves&t=Santa%20Clara) | 50 | [Santa Clara](https://barttorvik.com/team.php?team=Santa%20Clara&year=2026) |
| 10 | [Bennett Stirtz](https://barttorvik.com/playerstat.php?year=2026&p=Bennett%20Stirtz&t=Iowa) | 50 | [Iowa](https://barttorvik.com/team.php?team=Iowa&year=2026) |
| 11 | [Mikel Brown Jr.](https://barttorvik.com/playerstat.php?year=2026&p=Mikel%20Brown%20Jr.&t=Louisville) | 45+ | [Louisville](https://barttorvik.com/team.php?team=Louisville&year=2026) |
| 12 | [Jayden Quaintance](https://barttorvik.com/playerstat.php?year=2026&p=Jayden%20Quaintance&t=Kentucky) | 45+ | [Kentucky](https://barttorvik.com/team.php?team=Kentucky&year=2026) |
| 13 | [Darius Acuff Jr.](https://barttorvik.com/playerstat.php?year=2026&p=Darius%20Acuff%20Jr.&t=Arkansas) | 45+ | [Arkansas](https://barttorvik.com/team.php?team=Arkansas&year=2026) |
| 14 | [Karim Lopez](https://www.basketball-reference.com/international/players/karim-lopez-1.html) | 45 | International |
| 15 | [Labaron Philon](https://barttorvik.com/playerstat.php?year=2026&p=Labaron%20Philon&t=Alabama) | 45 | [Alabama](https://barttorvik.com/team.php?team=Alabama&year=2026) |
| 16 | [Hannes Steinbach](https://barttorvik.com/playerstat.php?year=2026&p=Hannes%20Steinbach&t=Washington) | 45 | [Washington](https://barttorvik.com/team.php?team=Washington&year=2026) |
| 17 | [Keaton Wagler](https://barttorvik.com/playerstat.php?year=2026&p=Keaton%20Wagler&t=Illinois) | 45 | [Illinois](https://barttorvik.com/team.php?team=Illinois&year=2026) |
| 18 | [Kingston Flemings](https://barttorvik.com/playerstat.php?year=2026&p=Kingston%20Flemings&t=Houston) | 45 | [Houston](https://barttorvik.com/team.php?team=Houston&year=2026) |
| 19 | [Isaiah Evans](https://barttorvik.com/playerstat.php?year=2026&p=Isaiah%20Evans&t=Duke) | 45 | [Duke](https://barttorvik.com/team.php?team=Duke&year=2026) |
| 20 | [Morez Johnson Jr.](https://barttorvik.com/playerstat.php?year=2026&p=Morez%20Johnson%20Jr.&t=Michigan) | 45 | [Michigan](https://barttorvik.com/team.php?team=Michigan&year=2026) |
| 21 | [Henri Veesaar](https://barttorvik.com/playerstat.php?year=2026&p=Henri%20Veesaar&t=North%20Carolina) | 45 | [North Carolina](https://barttorvik.com/team.php?team=North%20Carolina&year=2026) |
| 22 | [Joshua Jefferson](https://barttorvik.com/playerstat.php?year=2026&p=Joshua%20Jefferson&t=Iowa%20St.) | 45 | [Iowa St.](https://barttorvik.com/team.php?team=Iowa%20St.&year=2026) |
| 23 | [Chris Cenac Jr.](https://barttorvik.com/playerstat.php?year=2026&p=Chris%20Cenac%20Jr.&t=Houston) | 40+ | [Houston](https://barttorvik.com/team.php?team=Houston&year=2026) |
| 24 | [Ebuka Okorie](https://barttorvik.com/playerstat.php?year=2026&p=Ebuka%20Okorie&t=Stanford) | 40+ | [Stanford](https://barttorvik.com/team.php?team=Stanford&year=2026) |
| 25 | [Christian Anderson](https://barttorvik.com/playerstat.php?year=2026&p=Christian%20Anderson&t=Texas%20Tech) | 40+ | [Texas Tech](https://barttorvik.com/team.php?team=Texas%20Tech&year=2026) |
| 26 | [Nate Ament](https://barttorvik.com/playerstat.php?year=2026&p=Nate%20Ament&t=Tennessee) | 40+ | [Tennessee](https://barttorvik.com/team.php?team=Tennessee&year=2026) |
| 27 | [Sergio de Larrea](https://www.basketball-reference.com/international/players/sergio-de-larrea-1.html) | 40 | International |
| 28 | [Cameron Carr](https://barttorvik.com/playerstat.php?year=2026&p=Cameron%20Carr&t=Baylor) | 40 | [Baylor](https://barttorvik.com/team.php?team=Baylor&year=2026) |
| 29 | [Koa Peat](https://barttorvik.com/playerstat.php?year=2026&p=Koa%20Peat&t=Arizona) | 35+ | [Arizona](https://barttorvik.com/team.php?team=Arizona&year=2026) |
| 30 | Tobias Jensen | 35+ | International |
{{< /wintable >}}
{{< winlist title="nba.exe" icon="basketball" >}}
- [ARKBOARD NBA 2026 (final)](https://x.com/ARKNDJL/status/2067982251699126724) | top 30 + FV, posted on X | Jun 19
- [ARKBOARD NBA 2026 v3](/posts/arkboard-nba-2026-v3/) | top 50 | Feb 15
- [ARKBOARD NBA 2026 v2](/posts/arkboard-nba-2026-v2/) | top 40 ranked, 118 graded | Feb 8
- [Creating An NBA Future Value Grading System](/posts/nba-future-value-grading-system/) | the 20–80 scale, ARKBOARD NBA 2026 v1: top 30 + 13 unranked | Jan 31
- everything tagged | [#arkboard](/tags/arkboard/) |
{{< /winlist >}}
{{< /deskcol >}}
{{< deskcol >}}
{{< wintabs tabs="v3,v2,v1" label="ARKBOARD NBA 2026 versions" >}}
{{< board post="arkboard-nba-2026-v3" n="1" title="ARKBOARD NBA 2026 v3 :: top 50 (feb 15)" tab="v3" icon="basketball" filter="FV,Team" >}}
{{< board post="arkboard-nba-2026-v2" n="0" title="ARKBOARD NBA 2026 v2 :: top 40 ranked, 118 graded (feb 8)" tab="v2" icon="basketball" filter="FV,Class,Team" >}}
{{< board post="nba-future-value-grading-system" n="1" title="ARKBOARD NBA 2026 v1 :: top 30 + 13 unranked (jan 31)" tab="v1" icon="basketball" filter="FV,Team" >}}
{{< /wintabs >}}
{{< /deskcol >}}
{{< /desk >}}
{{< /wintabs >}}
