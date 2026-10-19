+++
title = "Games :: ARKBOARD"
url = "/arkboard/games/"
description = "Every game on one page: college football, NFL, college basketball and NBA projections from the ARKBOARD game models against the market, one game table across all four sports, and picks ranked by expected return, with Kelly units and each market's held-out backtest."
keywords = ["arkboard", "game projections", "picks", "college football picks", "nfl picks", "college basketball picks", "nba picks", "expected value", "kelly criterion", "betting model", "game model"]
draft = false
+++

{{< arknav >}}

{{< winpane title="games.exe :: every sport" icon="calendar" sprite="px/hero-football" status="CFB · NFL · CBB · NBA" />}}

{{< wintabs groups="games:games,game table,picks|record:picks backtest" side="true" label="Games views" >}}
{{< gamesfilter tab="games" >}}
{{< cfbgames title="college football" tab="games" sport="cfb" >}}
{{< nflgames title="NFL" tab="games" sport="nfl" >}}
{{< cbbgames title="college basketball" tab="games" sport="cbb" >}}
{{< nbagames title="NBA" tab="games" sport="nba" >}}
{{< gamestable title="game table :: every sport" tab="game table" >}}
{{< gamespicks tab="picks" >}}
{{< gamespicksbt tab="picks backtest" >}}
{{< /wintabs >}}
