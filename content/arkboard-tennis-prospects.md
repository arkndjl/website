+++
title = "Tennis Prospects :: ARKBOARD"
url = "/arkboard/tennis-prospects/"
description = "Tennis Prospects ARKBOARD: every ATP and WTA player under 22 with a ranking or a pro match in the last year, graded on the 20-80 FV scale: the mean outcome of past prospects with the same profile, peak ranking value at ages 22-28 by rarity within a birth year. Backtested on every October from 1993 to 2019, held out by birth year: age, ranking, our Elo on every pro match at every level, results over the last year, years on the pro tour and time at Futures and in qualifying."
keywords = ["arkboard", "tennis prospects", "next gen", "best young tennis players", "under 21", "under 22", "atp prospects", "wta prospects", "future value", "20-80 scale", "big board", "tennis elo"]
draft = false
+++

{{< arknav >}}

{{< winpane title="tennis_prospects.exe :: under-22 big boards" icon="tennis" sprite="px/hero-tennis" status="Sackmann archive · Tennis Abstract · every pro level" class="winpane--art" />}}

{{< wintabs groups="players:ATP board,WTA board|model:fv model,ATP past,WTA past,all-time FV" side="true" label="Tennis prospects views" >}}
{{< tennisprospects view="board" tour="atp" tab="ATP board" >}}
{{< lazytab tab="WTA board" >}}{{< tennisprospects view="board" tour="wta" tab="WTA board" >}}{{< /lazytab >}}
{{< lazytab tab="ATP past" >}}{{< tennisprospects view="past" tour="atp" tab="ATP past" >}}{{< /lazytab >}}
{{< lazytab tab="WTA past" >}}{{< tennisprospects view="past" tour="wta" tab="WTA past" >}}{{< /lazytab >}}
{{< lazytab tab="fv model" >}}
{{< desk tab="fv model" >}}
{{< deskcol >}}
{{< tennisprospects view="model" tour="atp" title="ATP :: fv model, value, scale, drivers, calibration" >}}
{{< fvcard sport="tennis-atp" title="ATP :: fv scorecard, tier odds vs what happened, held out" >}}
{{< /deskcol >}}
{{< deskcol >}}
{{< tennisprospects view="model" tour="wta" title="WTA :: fv model, value, scale, drivers, calibration" >}}
{{< fvcard sport="tennis-wta" title="WTA :: fv scorecard, tier odds vs what happened, held out" >}}
{{< /deskcol >}}
{{< /desk >}}
{{< /lazytab >}}
{{< lazytab tab="all-time FV" >}}
{{< fvalltime sport="tennis" tab="all-time FV" >}}
{{< /lazytab >}}
{{< /wintabs >}}
