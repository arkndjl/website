+++
title = "ARKLOG"
url = "/arklog/"
description = "ARKLOG: every change to arkndjl.net with its date, and for every model and metric test the held-out number before and after and whether it shipped or failed. Also the site's own numbers: visitors, traffic, builds and data freshness."
keywords = ["arklog", "update log", "changelog", "model updates", "backtests", "held out", "site stats", "visitors", "traffic", "arkndjl"]
draft = false
+++

{{< wintabs groups="Log:log,updates,scoreboard|Site data:traffic,build,data" side="true" class="libtabs" label="ARKLOG views" >}}
{{< arklog tab="log" >}}
{{< arklogupdates tab="updates" >}}
{{< lazytab tab="scoreboard" >}}{{< arklogboard tab="scoreboard" >}}{{< /lazytab >}}
{{< desk tab="traffic" >}}
{{< sitestats part="views" class="desk__wide" >}}
{{< sitestats part="trend" >}}
{{< sitestats part="traffic" >}}
{{< /desk >}}
{{< desk tab="build" >}}
{{< sitestats part="build" class="desk__wide" >}}
{{< /desk >}}
{{< desk tab="data" >}}
{{< sitestats part="fresh" class="desk__wide" >}}
{{< /desk >}}
{{< /wintabs >}}
