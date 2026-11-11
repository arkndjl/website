+++
title = "Predictions :: ARKBOARD"
url = "/arkboard/predictions/"
aliases = ["/arkboard/games/"]
description = "Every ARKBOARD prediction on one page, and the only place for picks: college football, NFL, college basketball, NBA, NHL and soccer projections from the ARKBOARD game models against the market, one game table across every sport, and picks ranked by expected return, sized at full Kelly, each market's held-out backtest and each game model's walk-forward test, judged by the close; futures and win totals; player projections: NBA points, rebounds and assists with DraftKings props, NFL fantasy and college football weekly lines."
keywords = ["arkboard", "predictions", "futures", "win totals", "game projections", "picks", "college football picks", "nfl picks", "college basketball picks", "nba picks", "soccer predictions", "expected value", "kelly criterion", "betting model", "game model", "nba player projections", "player props", "nfl fantasy projections", "ppr projections"]
draft = false
cover = "/og/predictions.png"
+++

{{< arknav >}}

{{< winpane title="predictions.exe" icon="calendar" sprite="px/hero-predictions" status="" class="winpane--art" />}}

{{< wintabs groups="games:games,game table,picks|players:NBA players,CBB players,NFL fantasy,NFL rankings,NFL breakouts,CFB players,player backtest|futures:futures|record:picks backtest,game models,paper book" side="true" label="Predictions views" >}}
{{< gamesfilter tab="games" >}}
{{< cfbgames title="college football" tab="games" sport="cfb" picks="true" >}}
{{< nflgames title="NFL" tab="games" sport="nfl" >}}
{{< cbbgames title="college basketball" tab="games" sport="cbb" picks="true" >}}
{{< nbagames title="NBA" tab="games" sport="nba" >}}
{{< nhlgames title="NHL" tab="games" sport="nhl" >}}
{{< soccergames title="soccer" tab="games" sport="soccer" >}}
{{< tennismatches title="tennis" tab="games" sport="tennis" picks="true" >}}
{{< lazytab tab="game table" >}}
{{< gamestable title="game table" tab="game table" >}}
{{< /lazytab >}}
{{< lazytab tab="picks" >}}
{{< gamespicks tab="picks" >}}
{{< predtable tab="picks" >}}
{{< mlboard tab="picks" >}}
{{< /lazytab >}}
{{< lazytab tab="NBA players" >}}
{{< nbaplayers title="NBA players" tab="NBA players" >}}
{{< propspaper title="NBA props :: paper book" tab="NBA players" >}}
{{< /lazytab >}}
{{< lazytab tab="CBB players" >}}
{{< nbaplayers src="cbb_players" title="CBB players" tab="CBB players" >}}
{{< /lazytab >}}
{{< nflfantasy title="NFL fantasy" tab="NFL fantasy" >}}
{{< nflprops title="NFL props :: paper book" tab="NFL fantasy" >}}
{{< nflrank title="NFL rankings" tab="NFL rankings" >}}
{{< nflbreakout title="NFL breakouts" tab="NFL breakouts" >}}
{{< lazytab tab="CFB players" >}}
{{< cfbproj title="CFB players" tab="CFB players" >}}
{{< /lazytab >}}
{{< lazytab tab="player backtest" >}}
{{< nbaplayerstest title="NBA player projections" tab="player backtest" >}}
{{< nbaplayerstest src="cbb_players" title="CBB player projections" tab="player backtest" >}}
{{< nflfantasytest title="NFL fantasy projections" tab="player backtest" >}}
{{< /lazytab >}}
{{< lazytab tab="futures" >}}
{{< predfutures tab="futures" >}}
{{< /lazytab >}}
{{< lazytab tab="picks backtest" >}}
{{< ruledrift tab="picks backtest" >}}
{{< rulemonitor tab="picks backtest" >}}
{{< gamespicksbt tab="picks backtest" >}}
{{< closefit tab="picks backtest" >}}
{{< nbanews title="NBA injury news vs the line :: 2019-26" tab="picks backtest" >}}
{{< /lazytab >}}
{{< lazytab tab="game models" >}}
{{< modelgov title="game models" tab="game models" >}}
{{< cfbmodel title="college football game model" tab="game models" >}}
{{< nbamodel title="NBA game model" tab="game models" >}}
{{< nhlmodel title="NHL game model" tab="game models" >}}
{{< soccermodel title="soccer game model" tab="game models" >}}
{{< cbbgamemodel title="college basketball game model :: inputs" tab="game models" >}}
{{< cbbgamemodel view="tests" title="college basketball game model :: what was tested" tab="game models" >}}
{{< modelgov view="ledger" title="model ledger" tab="game models" >}}
{{< modelgov view="pipeline" title="pipeline" tab="game models" >}}
{{< /lazytab >}}
{{< lazytab tab="paper book" >}}
{{< gamespaper tab="paper book" >}}
{{< propspaper tab="paper book" >}}
{{< nflprops tab="paper book" >}}
{{< /lazytab >}}
{{< /wintabs >}}
