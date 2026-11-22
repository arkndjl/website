+++
title = "wave :: ST. CLAIRE"
url = "/stclaire/wave/"
aliases = ["/wave/", "/arkndjl/wave/"]
description = "drops, merch, NYC shows, Mets and Knicks."
draft = false

# Everything on this page is data/wave.json (scripts/wave.py, .github/workflows/wave.yml every 3 hours) drawn by
# layouts/shortcodes/arkndjlwave.html (hero, logo wall) and wavepanel.html (each tab). Logos: scripts/wave_logos.py.
+++

{{< arkndjlnav >}}
{{< arkndjlwave >}}
{{< wintabs tabs="drops,merch,shows,screen,mets knicks,suggested" label="WAVE" >}}
{{< wavepanel p="drops" >}}
{{< wavepanel p="merch" >}}
{{< wavepanel p="shows" >}}
{{< wavepanel p="screen" >}}
{{< wintabs tab="mets knicks" tabs="tickets,promos,collabs" sub="true" >}}
{{< wavepanel p="tickets" >}}
{{< wavepanel p="promos" >}}
{{< wavepanel p="collabs" >}}
{{< /wintabs >}}
{{< wintabs tab="suggested" tabs="brands,collections" sub="true" >}}
{{< wavepanel p="brands" >}}
{{< wavepanel p="collections" >}}
{{< /wintabs >}}
{{< /wintabs >}}
{{< /arkndjlwave >}}
