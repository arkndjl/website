+++
title = "NBA :: ARKBOARD"
url = "/arkboard/nba/"
description = "NBA game projections and XPM leaderboard. games: model line, win probability and projected score against the market, with tonight's injuries; upset and favorite picks; power rankings and season odds. XPM leaderboard: XPM, the ARKBOARD's NBA impact metric (50/50 databallr DPM + Basketball-Reference BPM), ranked by VORX, wins over replacement fit to NBA team wins, with offense and defense splits. every season since 2009-10, filter by minutes, position, team and age."
keywords = ["arkboard", "nba", "nba game projections", "nba model", "nba picks", "nba power rankings", "nba playoff odds", "xpm", "dpm", "bpm", "nba leaderboard", "plus minus", "vorp", "nba impact metric"]
draft = false
+++

{{< arknav >}}

{{< winpane title="nba.exe :: NBA XPM and games" icon="hoop" sprite="px/hero-basketball" status="databallr DPM · Basketball-Reference BPM · ESPN · NBA injury report" >}}
**XPM** is the ARKBOARD's NBA impact number: points per 100 possessions over an average player, the 50/50 blend of databallr's DPM and Basketball-Reference's BPM. O-XPM and D-XPM blend each side the same way, The board ranks by **VORX**, wins over replacement: .030 x (XPM + 1.4) x MP / 48. Both constants are fit to NBA wins: -1.4 is what freely available players produce (bbref's VORP uses -2.0), and a point of XPM over a full season's minutes is worth 2.46 wins (not 2.7); each beat the old value on held-out seasons. In a test on 480 team-seasons (2011-26, ratings from earlier seasons predicting each team's margin) the blend beat DPM and BPM alone, and nothing we built beat the blend. The College Basketball board grades prospects on peak XPM.

The **game model** projects every game from Elo, net rating per 100 possessions (opponent- and home-adjusted), a market rating built from earlier closing spreads, and tonight's lineup: each player's XPM from the two seasons before at his recent minutes and his chance to play by injury status, against the lineups the ratings were built on. Days of rest and Elo in the playoffs earned a place out of sample; a back-to-back flag, travel, time zones, altitude and games in four nights did not. Weights are refit each season on the seasons before it and judged against the closing line on 2022-26, which the tuning never saw: the model trails the close (margin error 10.78 against 10.56), so the picks tab shows each rule's record and the units it would have won or lost.
{{< /winpane >}}

{{< wintabs groups="players:XPM leaders|games:games,game table,picks,model backtest|teams:power rankings,season odds" label="NBA views" >}}
{{< nbaxpm title="NBA XPM :: leaderboard" tab="XPM leaders" >}}
{{< nbagames title="games" tab="games" >}}
{{< nbagametable title="game table" tab="game table" >}}
{{< nbapicks tab="picks" >}}
{{< nbamodel title="model backtest :: walk-forward, 2015-26" tab="model backtest" >}}
{{< nbapower title="power rankings" tab="power rankings" >}}
{{< nbasim title="season odds" tab="season odds" >}}
{{< /wintabs >}}
