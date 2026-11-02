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
  and `/arkboard/lab/` redirect to it in `static/_redirects`. Add the Research and Glossary/Methodology tabs to that
  page's `wintabs` ahead of "data sources".
- Data Sources tab: `{{< datasources >}}` reads `data/data_sources.json`. A new fetcher that pulls from a new outside
  source adds the source there (name, link, what the site takes from it).
