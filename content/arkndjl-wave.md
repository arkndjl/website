+++
title = "wave :: ST. CLAIRE"
url = "/stclaire/wave/"
aliases = ["/wave/", "/arkndjl/wave/"]
description = "collections, sales, picks, merch, NYC shows, Mets and Knicks."
draft = false

# Everything on this page is data/wave.json (scripts/wave.py + wave_catalog.py, .github/workflows/wave.yml every 3 hours)
# drawn by layouts/shortcodes/arkndjlwave.html (hero, logo strip) and wavepanel.html (each tab; cards = partials/wave/).
# Logos: scripts/wave_logos.py.
+++

{{< arkndjlnav >}}
{{< arkndjlwave >}}
{{< wintabs tabs="drops,sales,picks,merch,shows,screen,mets knicks,suggested" label="WAVE" >}}
{{< wintabs tab="drops" tabs="collections,new in,headlines" sub="true" >}}
{{< wavepanel p="collections" >}}
{{< wavepanel p="new in" >}}
{{< wavepanel p="headlines" >}}
{{< /wintabs >}}
{{< wavepanel p="sales" >}}
{{< wintabs tab="picks" tabs="knicks,mets,bands,collabs,staples" sub="true" >}}
{{< wavepanel p="knicks" >}}
{{< wavepanel p="mets" >}}
{{< wavepanel p="bands" >}}
{{< wavepanel p="collabs" >}}
{{< wavepanel p="staples" >}}
{{< /wintabs >}}
{{< wavepanel p="merch" >}}
{{< wavepanel p="shows" >}}
{{< wavepanel p="screen" >}}
{{< wintabs tab="mets knicks" tabs="tickets,promos" sub="true" >}}
{{< wavepanel p="tickets" >}}
{{< wavepanel p="promos" >}}
{{< /wintabs >}}
{{< wavepanel p="brands" tab="suggested" >}}
{{< /wintabs >}}
{{< /arkndjlwave >}}
