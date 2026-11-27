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
- Team short forms (UConn, FAU) live in `scripts/names.py` TEAM_ALIAS; `scripts/names.mjs` holds the same list and the
  browser reads `data/team_alias.json`. After a change run `python3 scripts/names.py --teams` (the tests and the build
  gate fail when the three differ).
- A spelling the rules miss (Neo / Neoklis Avdalas, a source's typo) goes in `data/name_aliases.json` "players"; a
  common nickname goes in its "nicknames". Matches still check team and position, so same-name players stay apart.

## ARKBOARD Process (was "Reference", before that "Library")

- The ARKBOARD section with Research, Glossary/Methodology and Data Sources tabs is **Process** (Noah, Nov 17 2026): page
  `content/arkboard-process.md`, URL `/arkboard/process/`, short link `arkndjl.net/process`, menu identifier
  `arkboard-process`. Never call it "Library" (that is ARKLIBRARY), "Lab", "Reference" or "ARKPROCESS". `/reference`, `/library`,
  `/lab`, `/arkboard/reference/`, `/arkboard/library/` and `/arkboard/lab/` redirect to it in `static/_redirects`. The page is
  written by `scripts/library_build.py` (Research + Glossary/Methodology from `data/library.json`, then Data Sources); rerun it
  rather than hand-editing. Glossary numbers are read from the live fit files in `scripts/library_glossary.py` (never typed in), and
  `.github/workflows/process-refresh.yml` reruns both scripts after every board/refit workflow (Noah, Nov 19: always auto-refresh).
- Glossary GFX cards: every term window has a GFX card button (`assets/js/gfx.js` buildTerm, link `arkndjl.net/process#g-<term>`).
  `data/glossary_gfx.json` is written by `scripts/glossary_gfx.py` (rerun after a season file or refit): compact cards from
  `research/glossary_gfx_base.json` (16:9, formula + one picture) and explainer cards (3:4: stands for, what, use, formula,
  held-out test vs similar metrics, distribution/calibration, top 10 from the site's data) from its EXPLAIN builders. Keys =
  the term exactly as in `data/library.json`; a term with no entry gets the plain card. Test numbers come from backtest files
  only, reported as they are even when ours does not win.
- Data Sources tab: `{{< datasources >}}` reads `data/data_sources.json`. A new fetcher that pulls from a new outside
  source adds the source there (name, link, what the site takes from it).

## Copy: no intros or descriptive blurbs

- No intro, lede, kicker, subtitle or descriptive blurb on any page, tab, card or window ("how arkndjl.net looks and
  reads", "every sport's X in one table", "where they will go"). Titles, labels, column headers, data and numbers only;
  let the page speak for itself. When unsure, cut.
- A note on how a table is built goes in the `about` of `wintable-close.html`, which is only the status bar's hover
  title, never a visible paragraph. Column meanings go in `<th title>` tooltips.
- Method prose lives only in Process (Glossary/Methodology). Model and backtest tabs on sport pages show tables,
  formulas and numbers, no explanatory paragraphs or "how it works" windows (Noah, Nov 2). Kept: Process text,
  article bodies, source attributions in status bars, résumé content on about/contact.

## Term hovers (acronyms and metric labels)

- One popover, one dictionary: `assets/js/terms.js` (loaded in the footer on every page) reads `data/terms.json` and shows what
  a label stands for, one plain line on what it is, the header's own `title` note, and a link to its Process glossary entry.
  Hover or focus on desktop, tap on phones. Never write a per-page tooltip or a second glossary of labels.
- It finds terms by itself: any `<th>` whose text is a key (case-insensitive; "XPM NOW" falls back to the one known word),
  any element with `data-term="KEY"`, metric chips (`.cfb__chip` with a title), and known site metrics in running text inside `.tick__g`, `.nws__main` or `[data-terms]`
  (keys with `"inline": true`).
- A new column label or metric: add it to `data/terms.json` `terms` (`n` stands for, `d` one short sentence in Noah's voice, then
  `g` = the glossary term exactly as in `data/library.json`, or `a` = an abbreviation group from `groups`). `by.<page slug>`
  holds a page's own reading (WAR on `/arkboard/nfl/` is NFL WAR) and `when` one picked by the header's own note (`m`, a
  regex: G is goals when the note says goals); `only` limits a key to the pages listed. `alias` maps other spellings to a key; `"part": false`
  keeps a short word (ON, G, ST) from matching inside longer labels.
- Labels with no glossary term of their own are listed under Process > Glossary/Methodology > abbreviations, written from
  `data/terms.json` by `scripts/library_glossary.py` (rerun it and `scripts/library_build.py` after a change; `python3 scripts/check_terms.py` checks every link).

## ARKBOARD tabs

- Side strip = sections, kept short. Tabs that are views of one thing share a side tab and sit under it as subtabs:
  `{{< wintabs tab="units" tabs="offense,defense" sub="true" >}}…{{< /wintabs >}}` inside the page's main `wintabs`
  (board, leaders, depth chart + backup watch, lineups, ARK Ranking + season odds + bracket, standouts/rookies + next up +
  true freshmen + G League, portal + re-signed + team builder, units, talent, NIL, coaches, classes, mock draft, leagues). A new view goes into the subtab group it belongs to before it gets a side tab of its own.
- Group order: players | rosters | games | teams | market | recruits | draft | model (soccer: leagues after teams).
- Tab names are the URL hash. A subtab's own name still opens it (`#defense`), so nest without renaming; a renamed
  or removed name needs an ALIAS entry in `layouts/shortcodes/wintabs.html`.
- Phones show the groups in one row and the open group's tabs in the next. A lazytab that renders nothing hides its tab.

## Site search

- Header bar on every page + `/search/` results page (`assets/js/search.js`, `layouts/partials/search-bar.html`,
  `layouts/shortcodes/search.html`). Index = `/search/index.json`, written by Hugo each build
  (`layouts/_default/single.searchindex.json`: pages, every wintabs tab/subtab, Process terms + research, ARKLIBRARY lists,
  ST. CLAIRE, 1NT, LAURSEN_111, articles) + `static/data/search-players.json` (players/teams, `scripts/search_index.py`,
  rerun by the `search index` workflow). Player rows name a page stem + tab, so moved pages and ALIASed tabs keep working.
  A new player board: add it to `scripts/search_index.py`. A page to keep out: `searchExclude = true`.

## News (ticker, /news/, daily GFX)

- One feed, no hand posting: `scripts/news.py` reads the site's data files and writes `data/news.json` (state in
  `scripts/data/news_state.json`); the odds-snap workflow reruns it every half hour. A new kind of news = a new source
  function there with an explicit weight rule in the docstring (MAJOR = w >= 60 feeds the strip and the GFX).
- The header strip is `layouts/partials/ticker.html` on every page (home: games then news; elsewhere news only;
  `noTicker = true` drops it). `/news/` = `layouts/shortcodes/news.html`; the daily card = `buildNews` in
  `assets/js/gfx.js` (`/news/#gfx` opens the newest). Category icons: 11x11 bitmaps in `data/news_icons.json`.
- Never surface hidden pages (Franchise Fantasy) or betting lines in the feed.

## Recruit GFX card and MOVES strip

- Rows with a class year in `data-rc` (`layouts/partials/rcgfx.html`: CFB class/future tabs, CBB class tabs) draw the recruit
  card, `buildRCard` in `assets/js/gfx.js`: FV to the whole number with Y1 FV (CFB) or IF NBA (CBB) under it, GRADES,
  PROJECTION (FV scale, FV and Y1 FV or NBA odds, year-1 cells; no year 2-3 projection for recruits, Noah Nov 26), PREDICTIONS while uncommitted, MOVES and VISITS (officials first, then the latest unofficial, six in all; committed recruits from the weekly On3 pull in recruit-leans.yml), FV INPUTS. It is a
  projection card: predictive numbers only. Age reads the rows' `age` and `ageRel` (years over the class median); absent = not drawn.
- Moves on every player card come from `static/data/moves/<sport>.json`, written by `scripts/player_moves.py` (rerun by the
  recruit news workflow) from files already in the repo; headline and transaction rows are kept in
  `scripts/data/player_moves_hist.json.gz`. A new kind of move needs a label in `MV_LAB` (gfx.js).
