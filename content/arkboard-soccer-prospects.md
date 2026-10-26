+++
title = "Soccer Prospects :: ARKBOARD"
url = "/arkboard/soccer-prospects/"
description = "Soccer Prospects ARKBOARD: every player under 22 at the season start in 33 leagues (the big five, 9 more European top flights, second divisions, Brazil, Argentina, MLS, Premier League 2), graded on the 20-80 FV scale: the mean outcome of past prospects with the same profile, peak senior value at ages 22-26. Backtested on the 2013-20 seasons: age, market value, this season's value at club strength, minutes share, scoring, size, position."
keywords = ["arkboard", "soccer prospects", "football prospects", "wonderkids", "under 21", "under 22", "best young players", "future value", "20-80 scale", "big board", "transfermarkt", "market value"]
draft = false
cover = "/og/soccer-prospects.png"
+++

{{< arknav >}}

{{< winpane title="soccer_prospects.exe :: under-22 big board" icon="soccer" sprite="px/hero-soccer" status="Transfermarkt lineups and values · 33 leagues" class="winpane--art" />}}

{{< wintabs groups="players:big board,first-year,ARKLIST|model:fv model,past prospects" label="Soccer prospects views" >}}
{{< soccerboard view="board" tab="big board" >}}
{{< rookies sport="soccerp" icon="soccer" title="first-year :: first senior season, FV and GAR" tab="first-year" >}}
{{< arklist sport="soccer-prospects" title="ARKLIST :: soccer prospects" tab="ARKLIST" >}}
{{< soccerboard view="past" tab="past prospects" >}}
{{< desk tab="fv model" >}}
{{< deskcol >}}
{{< soccerboard view="model" title="fv model :: value, scale, drivers, calibration" >}}
{{< /deskcol >}}
{{< deskcol >}}
{{< fvcard sport="soccer" title="fv scorecard :: tier odds vs what happened, held out" >}}
{{< /deskcol >}}
{{< /desk >}}
{{< /wintabs >}}
