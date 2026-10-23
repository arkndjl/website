+++
title = "NBA :: ARKBOARD"
url = "/arkboard/nba/"
description = "NBA game projections and XPM leaderboard. games: model line, win probability and projected score, with tonight's injuries; power rankings and season odds. XPM leaderboard: XPM, the ARKBOARD's NBA impact metric (50/50 databallr DPM + Basketball-Reference BPM), ranked by VORX, wins over replacement fit to NBA team wins, with offense and defense splits. every season since 2009-10, filter by minutes, position, team and age."
keywords = ["arkboard", "nba", "nba game projections", "nba model", "nba power rankings", "nba playoff odds", "xpm", "dpm", "bpm", "nba leaderboard", "plus minus", "vorp", "nba impact metric"]
draft = false
+++

{{< arknav >}}

{{< winpane title="nba.exe :: NBA XPM and games" icon="hoop" sprite="px/hero-basketball" status="databallr DPM · Basketball-Reference BPM · ESPN · NBA injury report" >}}
**XPM** is the ARKBOARD's NBA impact number: points per 100 possessions over an average player, the 50/50 blend of databallr's DPM and Basketball-Reference's BPM. O-XPM and D-XPM blend each side the same way, The board ranks by **VORX**, wins over replacement: .030 x (XPM + 1.4) x MP / 48. Both constants are fit to NBA wins: -1.4 is what freely available players produce (bbref's VORP uses -2.0), and a point of XPM over a full season's minutes is worth 2.46 wins (not 2.7); each beat the old value on held-out seasons. In a test on 480 team-seasons (2011-26, ratings from earlier seasons predicting each team's margin) the blend beat DPM and BPM alone, and nothing we built beat the blend. The College Basketball board grades prospects on peak XPM.
{{< /winpane >}}

{{< wintabs groups="players:XPM leaders,backup watch,ARKLIST|games:games,game table|teams:power rankings,season odds" label="NBA views" >}}
{{< nbaxpm title="NBA XPM :: leaderboard" tab="XPM leaders" >}}
{{< backupwatch sport="nba" title="backup watch :: 2nd/3rd string producing above the starter" tab="backup watch" >}}
{{< arklist sport="nba" title="ARKLIST :: NBA" tab="ARKLIST" >}}
{{< nbagames title="games" tab="games" >}}
{{< nbagametable title="game table" tab="game table" >}}
{{< nbapower title="power rankings" tab="power rankings" >}}
{{< nbasim title="season odds" tab="season odds" >}}
{{< /wintabs >}}
