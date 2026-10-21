+++
title = "Predictions :: ARKBOARD"
url = "/arkboard/predictions/"
aliases = ["/arkboard/games/"]
description = "Every ARKBOARD prediction on one page, and the only place for picks: college football, NFL, college basketball and NBA projections from the ARKBOARD game models against the market, one game table across all four sports, and picks ranked by expected return, with Kelly units and each market's held-out backtest, judged by the close; futures and win totals."
keywords = ["arkboard", "predictions", "futures", "win totals", "game projections", "picks", "college football picks", "nfl picks", "college basketball picks", "nba picks", "expected value", "kelly criterion", "betting model", "game model"]
draft = false
+++

{{< arknav >}}

{{< winpane title="predictions.exe :: every sport" icon="calendar" sprite="px/hero-football" status="CFB · NFL · CBB · NBA" />}}

{{< wintabs groups="games:games,game table,picks|futures:futures|record:picks backtest,paper book" side="true" label="Predictions views" >}}
{{< gamesfilter tab="games" >}}
{{< cfbgames title="college football" tab="games" sport="cfb" picks="true" >}}
{{< nflgames title="NFL" tab="games" sport="nfl" >}}
{{< cbbgames title="college basketball" tab="games" sport="cbb" picks="true" >}}
{{< nbagames title="NBA" tab="games" sport="nba" >}}
{{< gamestable title="game table :: every sport" tab="game table" >}}
{{< gamespicks tab="picks" >}}
{{< predfutures tab="futures" >}}
{{< gamespicksbt tab="picks backtest" >}}
{{< gamespaper tab="paper book" >}}
{{< /wintabs >}}
