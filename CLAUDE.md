# arkndjl.net

## ARKLIBRARY (content/arklibrary.md)

- Keep music artists and albums in sync: when an album is added to `albums.exe`, add its artist
  to the music `artists.exe` list too, with a photo (`p-<slug>` in scripts/fetch_covers.py).
  Albums credited to several acts (e.g. "Julian Casablancas + The Voidz") need each act listed.
- Artist photos come from Deezer. Check that the photo is the same Deezer artist as the album's
  (several artists share names); pin the artist id (`("deezer", "<id>")`) when the name search
  picks someone else.

## Player names (every sport)

- Join sources by player name only through the shared matcher: `scripts/names.py` (Python) and `scripts/names.mjs`
  (Node; `layouts/partials/namekey.html` in the browser). Same rules in all three: run `python3 scripts/names.py --test`
  and `node scripts/names.mjs --test` after a change. Prefer a stable id (ESPN, Barttorvik pid, gsis) when both sides have one.
- A spelling the rules miss (Neo / Neoklis Avdalas, a source's typo) goes in `data/name_aliases.json` "players"; a
  common nickname goes in its "nicknames". Matches still check team and position, so same-name players stay apart.

## ARKBOARD Reference (was "Library")

- The ARKBOARD section with Research, Glossary/Methodology and Data Sources tabs is **Reference**: page
  `content/arkboard-reference.md`, URL `/arkboard/reference/`, short link `arkndjl.net/reference`, menu identifier
  `arkboard-reference`. Never call it "Library" (that is ARKLIBRARY) or "Lab". `/library`, `/lab`, `/arkboard/library/`
  and `/arkboard/lab/` redirect to it in `static/_redirects`. The page is written by `scripts/library_build.py`
  (Research + Glossary/Methodology from `data/library.json`, then Data Sources); rerun it rather than hand-editing.
- Data Sources tab: `{{< datasources >}}` reads `data/data_sources.json`. A new fetcher that pulls from a new outside
  source adds the source there (name, link, what the site takes from it).

## Copy: no intros or descriptive blurbs

- No intro, lede, kicker, subtitle or descriptive blurb on any page, tab, card or window ("how arkndjl.net looks and
  reads", "every sport's X in one table", "where they will go"). Titles, labels, column headers, data and numbers only;
  let the page speak for itself. When unsure, cut.
- A note on how a table is built goes in the `about` of `wintable-close.html`, which is only the status bar's hover
  title, never a visible paragraph. Column meanings go in `<th title>` tooltips.
- Method prose lives only in Reference (Glossary/Methodology). Model and backtest tabs on sport pages show tables,
  formulas and numbers, no explanatory paragraphs or "how it works" windows (Noah, Nov 2). Kept: Reference text,
  article bodies, source attributions in status bars, résumé content on about/contact.
