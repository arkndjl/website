+++
title = "NBA :: ARKBOARD"
url = "/arkboard/nba/"
description = "NBA game projections and XPM leaderboard. games: model line, win probability and projected score, with tonight's injuries; power rankings and season odds. XPM leaderboard: XPM, the ARKBOARD's NBA impact metric (50/50 databallr DPM + Basketball-Reference BPM), ranked by VORX, wins over replacement fit to NBA team wins, with offense and defense splits, and XPM (proj), the season to date blended with a preseason prior. contract value: projected wins x the market $ per win against salary, this season and over the contract. every season since 2009-10, filter by minutes, position, team and age."
keywords = ["arkboard", "nba", "nba game projections", "nba model", "nba power rankings", "nba playoff odds", "xpm", "dpm", "bpm", "nba leaderboard", "plus minus", "vorp", "nba impact metric"]
draft = false
cover = "/og/nba.png"
+++

{{< arknav >}}

{{< winpane title="nba.exe :: NBA XPM and games" icon="hoop" sprite="px/hero-basketball" status="databallr DPM · Basketball-Reference BPM · ESPN · NBA injury report" class="winpane--art" />}}

{{< wintabs groups="players:XPM leaders,contract value,rookies,backup watch,ARKLIST|games:games,game table|teams:power rankings,season odds" label="NBA views" >}}
{{< nbaxpm title="NBA XPM :: leaderboard" tab="XPM leaders" >}}
{{< nbasurplus title="contract value :: surplus over salary" tab="contract value" >}}
{{< rookies sport="nba" icon="hoop" title="rookies :: VORX, XPM and surplus against draft slot and FV" tab="rookies" >}}
{{< backupwatch sport="nba" title="backup watch :: 2nd/3rd string producing above the starter" tab="backup watch" >}}
{{< arklist sport="nba" title="ARKLIST :: NBA" tab="ARKLIST" >}}
{{< nbagames title="games" tab="games" >}}
{{< nbagametable title="game table" tab="game table" >}}
{{< nbapower title="power rankings" tab="power rankings" >}}
{{< nbasim title="season odds" tab="season odds" >}}
{{< /wintabs >}}
