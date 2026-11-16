+++
title = "NBA :: ARKBOARD"
url = "/arkboard/nba/"
description = "NBA game projections and XPM leaderboard. games: model line, win probability and projected score, with tonight's injuries; ARK Ranking (power rankings) and season odds. XPM leaderboard: XPM, the ARKBOARD's NBA impact metric (50/50 databallr DPM + Basketball-Reference BPM), ranked by VORX, wins over replacement fit to NBA team wins, with offense and defense splits, and XPM (proj), the season to date blended with a preseason prior. contract value: projected wins x the market $ per win against salary, this season and over the contract. every season since 2009-10, filter by minutes, position, team and age. projections: 20th, 50th and 80th percentile VORX, points, rebounds, assists, 3s, steals and blocks, full season and rest of season."
keywords = ["arkboard", "ark ranking", "nba", "nba game projections", "nba model", "nba power rankings", "nba playoff odds", "xpm", "dpm", "bpm", "nba leaderboard", "plus minus", "vorp", "nba impact metric"]
draft = false
cover = "/og/nba.png"
+++

{{< arknav >}}

{{< winpane title="nba.exe :: 2026-27" icon="basketball" sprite="px/hero-basketball" status="databallr DPM · Basketball-Reference BPM · LUMA ARC (CC BY 4.0) · ESPN · NBA injury report" class="winpane--art" />}}

{{< wintabs groups="players:VORX/XPM leaders,projections,rookies,awards,ARKLIST|rosters:depth chart,lineups,transactions|games:games,game table|teams:ARK Ranking,season odds,units,all-time coaches|market:contract value" side="true" label="NBA views" >}}
{{< nbaxpm title="NBA XPM" tab="VORX/XPM leaders" >}}
{{< pctl sport="nba" icon="basketball" title="projections" tab="projections" >}}
{{< nbasurplus title="contract value" tab="contract value" >}}
{{< rookies sport="nba" icon="basketball" title="rookies" tab="rookies" >}}
{{< awards sport="nba" tab="awards" >}}
{{< arklist sport="nba" title="ARKLIST" tab="ARKLIST" >}}
{{< nbagames title="games" tab="games" >}}
{{< nbagametable title="game table" tab="game table" >}}
{{< nbapower title="ARK Ranking" tab="ARK Ranking" >}}
{{< lazytab tab="transactions" >}}
{{< transactions sport="nba" title="transactions" tab="transactions" >}}
{{< /lazytab >}}
{{< wintabs tab="depth chart" tabs="depth chart,backup watch" sub="true" label="depth chart views" >}}
{{< depthchart sport="nba" title="depth chart" tab="depth chart" >}}
{{< backupwatch sport="nba" title="backup watch" tab="backup watch" >}}
{{< /wintabs >}}
{{< wintabs tab="lineups" tabs="lineups,on/off,lineup leaders" sub="true" label="lineups views" >}}
{{< nbalineups title="lineups" tab="lineups" >}}
{{< nbalineups title="on/off" tab="on/off" view="onoff" >}}
{{< lineupleaders sport="nba" title="lineup leaders" tab="lineup leaders" >}}
{{< /wintabs >}}
{{< wintabs tab="season odds" tabs="season odds,bracket" sub="true" label="season odds views" >}}
{{< nbasim title="season odds" tab="season odds" >}}
{{< lazytab tab="bracket" >}}{{< bracket k="nba" title="projected bracket" tab="bracket" icon="basketball" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="units" tabs="offense,defense" sub="true" label="units views" >}}
{{< lazytab tab="offense" >}}
{{< teamunits sport="nba" view="offense" title="offense" tab="offense" >}}
{{< /lazytab >}}
{{< lazytab tab="defense" >}}
{{< teamunits sport="nba" view="defense" title="defense" tab="defense" >}}
{{< /lazytab >}}
{{< /wintabs >}}
{{< lazytab tab="all-time coaches" >}}
{{< coachalltime sport="nba" title="all-time coaches" tab="all-time coaches" >}}
{{< /lazytab >}}
{{< /wintabs >}}
