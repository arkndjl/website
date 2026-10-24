+++
title = "Soccer :: ARKBOARD"
url = "/arkboard/soccer/"
description = "Soccer match projections, power rankings and season odds for the Premier League, La Liga, Bundesliga, Serie A, Ligue 1, the Champions League, Europa League and Conference League: home, draw and away chances from ratings on goals, Understat expected goals and the market's earlier prices; one power ranking across every league; title, top-four and relegation odds and UEFA knockout odds from 10,000 simulated seasons."
keywords = ["arkboard", "soccer", "football", "premier league", "la liga", "bundesliga", "serie a", "ligue 1", "champions league", "europa league", "conference league", "soccer power rankings", "soccer model", "title odds", "relegation odds", "champions league odds", "expected goals", "xg"]
draft = false
+++

{{< arknav >}}

{{< winpane title="soccer.exe :: Europe's big five and the UEFA cups" icon="soccer" sprite="px/hero-soccer" status="ESPN · Understat xG · football-data.co.uk" >}}
Each club has an **attack** and a **defence** within its league, and each league a **strength**, set by its clubs' results against other leagues: the European cups and their qualifiers, and cup ties between divisions. A club carries its strength with it when it is promoted or relegated. Attack and defence blend three ratings, each kept on walk-forward evidence from 2012-13 to 2021-22 and checked on the seasons since: the goals implied by **earlier matches' closing prices**, **Understat's expected goals** (big five), and, for clubs with neither, **goals**. Home, draw and away come from a Dixon-Coles score matrix. Rest days, shots on target and a summer pull to the mean were tested and didn't help. Season odds: 10,000 simulated seasons, each club's strength drawn once a season around its rating; the UEFA cups run the 36-club league phase and the seeded knockout bracket.
{{< /winpane >}}

{{< wintabs groups="matches:matches,match table|leagues:Premier League,La Liga,Bundesliga,Serie A,Ligue 1|europe:Champions League,Europa League,Conference League|clubs:power rankings" label="Soccer views" >}}
{{< soccergames title="matches" tab="matches" >}}
{{< soccergametable title="match table" tab="match table" >}}
{{< soccerleague lg="eng.1" title="Premier League" tab="Premier League" >}}
{{< soccerleague lg="esp.1" title="La Liga" tab="La Liga" >}}
{{< soccerleague lg="ger.1" title="Bundesliga" tab="Bundesliga" >}}
{{< soccerleague lg="ita.1" title="Serie A" tab="Serie A" >}}
{{< soccerleague lg="fra.1" title="Ligue 1" tab="Ligue 1" >}}
{{< socceruefa lg="uefa.champions" title="Champions League" tab="Champions League" >}}
{{< socceruefa lg="uefa.europa" title="Europa League" tab="Europa League" >}}
{{< socceruefa lg="uefa.europa.conf" title="Conference League" tab="Conference League" >}}
{{< soccerpower title="power rankings :: every league, one scale" tab="power rankings" >}}
{{< /wintabs >}}
