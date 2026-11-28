# arkndjl.net

## Standing rules (read first; detail in docs/rules/)

- Keep rules in two places: when a standing rule changes, update this file or `docs/rules/` and project memory in the
  same thread. A weekly sync and each monthly PROCESS batch check the two against each other. The repo is public:
  secrets, private client or business work, personal contact details and betting stakes stay in memory only.
- Design ([docs/rules/design.md](docs/rules/design.md)): pixel art, purple / teal / lilac, one font (MS PGothic), no
  emoji, team logos full colour, ARK stars platinum with the 5-star+ shimmer, table/player/team GFX 4:5 (other cards 16:9), no overlap, boxed
  column groups, every page works on a phone.
- Copy ([docs/rules/copy-voice.md](docs/rules/copy-voice.md)): minimal text, no blurbs; everything published in Noah's
  voice (academic, his own words, Oxford commas, no LLM phrasing or marketing); ARKLOG never logs copy cleanups or
  mentions AI; one PROCESS #N article a month; every article gets an articleGFX card (each section's key words, a comma list).
- Models ([docs/rules/models-tests.md](docs/rules/models-tests.md)): ship only what passes out-of-sample tests, point
  in time; 2026-27 is a lockbox; every failed or deferred test with a later look goes in data/retests.json; cross-sport rule; predictive metric in predictive contexts, descriptive in
  descriptive; FV is absolute 20-80 true talent, mean headline, never class-relative or a shared cross-sport scale. Replacement levels are refit on a schedule and by position (`scripts/repl_levels.py`, weekly; a split ships only after it passes).
- Boards ([docs/rules/boards.md](docs/rules/boards.md)), metric definitions ([docs/rules/metrics.md](docs/rules/metrics.md)),
  sections ([docs/rules/sections.md](docs/rules/sections.md)), posting schedule and shipping
  ([docs/rules/workflow.md](docs/rules/workflow.md)): merge when done, then `python3 scripts/check_live.py`; retrigger
  the build if not live in about 20 minutes.

## ARKLIBRARY (content/arklibrary.md)

- Keep music artists and albums in sync: when an album is added to `albums.exe`, add its artist
  to the music `artists.exe` list too, with a photo (`p-<slug>` in scripts/fetch_covers.py).
  Albums credited to several acts (e.g. "Julian Casablancas + The Voidz") need each act listed.
- Artist photos come from Deezer. Check that the photo is the same Deezer artist as the album's
  (several artists share names); pin the artist id (`("deezer", "<id>")`) when the name search
  picks someone else.

## Scheduled retests (data/retests.json; Noah, Nov 28)

- A failed or deferred test with a later retest goes into `data/retests.json` in the same PR (trigger, gate, `after` =
  `sport:kind:year` in data/seasons + `lag`, or `due`; `how` = watch / auto / hand). `scripts/retests.py` (retests.yml,
  Tue and Fri) writes `data/retests_state.json` for ARKLOG > retests (`arklogretests.html`) and the Process overview,
  opens a "retest due" issue for hand tests, and only ships a pass. The PR that runs one adds its `result`. `--test` after a change.

## Forward logs (Nov 28; docs/forward-logs.md)

- Data the site reads and then overwrites gets a dated, change-only log in `scripts/snapshots.py` -> `scripts/data/snaps/`
  (injuries and news every 30 minutes in odds-snap.yml; depth charts, weekly board vintages and agency rows in
  process-refresh.yml; CFB offers in cfb-recruits.yml; On3 grades and NIL in cfb-board.yml). Batch a new log into an existing
  workflow, never a new one (Actions minutes). Each log names its future test in `data/retests.json` (`fwd_*`, `ready` on
  `data/snapshots.json`). Public data only. `python3 scripts/snapshots.py --test` after a change.

## Player names (every sport)

- Join sources by player name only through the shared matcher: `scripts/names.py` (Python) and `scripts/names.mjs`
  (Node; `layouts/partials/namekey.html` in the browser). Same rules in all three: run `python3 scripts/names.py --test`
  and `node scripts/names.mjs --test` after a change. Prefer a stable id (ESPN, Barttorvik pid, gsis) when both sides have one.
- Team short forms (UConn, FAU) live in `scripts/names.py` TEAM_ALIAS; `scripts/names.mjs` holds the same list and the
  browser reads `data/team_alias.json`. After a change run `python3 scripts/names.py --teams` (the tests and the build
  gate fail when the three differ).
- A spelling the rules miss (Neo / Neoklis Avdalas, a source's typo) goes in `data/name_aliases.json` "players"; a
  common nickname goes in its "nicknames". Matches still check team and position, so same-name players stay apart.

## Process (was ARKBOARD Process, "Reference", before that "Library"; ARKLOG folded in Nov 28)

- **Process** is its own section (Noah, Nov 28 2026): page `content/arkboard-process.md`, URL `/process/`, top menu item
  `process` right under donate (icon `static/img/icons/process.svg`); not in the ARKBOARD menu or hub (Noah, Nov 28).
  ARKLOG is a group inside it (log, updates, calendar, milestones, scoreboard, traffic, build, data). Milestones = `scripts/milestones.py` -> `data/milestones.json` (social, site and log thresholds, detected from the data, never typed in). Never call it "Library" (that is ARKLIBRARY),
  "Lab", "Reference" or "ARKPROCESS". `/arkboard/process/`, `/arklog/`, `/reference`, `/library`, `/lab` and the old
  ARKBOARD paths redirect to it in `static/_redirects`; bare `/arklog/` opens `/process/#log` (Noah, Nov 28).
- Philosophy (Noah, Nov 28): Overview | Philosophy | Metrics ... Text in Noah's words is `research/philosophy.json` (numbers as
  `{key}` placeholders), filled with figures from the fit files by `scripts/philosophy_build.py` into `data/philosophy.json`,
  drawn by `layouts/shortcodes/procphil.html`; process-refresh.yml reruns it. The 16:9 ARKPHILOSOPHY card
  (`static/img/process/arkphilosophy.png`) is `python3 scripts/philosophy_gfx.py` (Playwright; rerun by hand); its lines are Noah's own
  words from the interview (`card` in research/philosophy.json), no taglines. The head window is `procview.html`: the animated pixel
  monitor and the Philosophy tab sprites are drawn by `scripts/process_art.py`, and `assets/js/lowpoly.js` renders a low-poly model
  for the open group (ARKLOG = 3D bars of every test by sport and verdict).
- Side strip (Nov 28): Overview | Philosophy | ARKLOG (`ARKLOG` in library_build.py) | Metrics (FV, FV scales, player value, player odds) | Models (team ratings,
  game models, drafts and mocks, testing) | Research | Data (data sources, data and names, abbreviations). The page is written by
  `scripts/library_build.py` from `data/library.json`; rerun it rather than hand-editing. A new glossary section goes in SIDE
  and GLOSS_TAB there; the gate terms (held out, walk-forward, ship gate, ledger) are moved into "testing" by METHOD.
  Overview (`procover.html`) and the sport sheets (`procsports.html`) read `data/library.json` "overview"; the charts in a
  term's window are drawn from its GFX card data (`entry_charts`). Nothing on the page is typed in.
- Glossary numbers are read from the live fit files in `scripts/library_glossary.py` (never typed in), and
  `.github/workflows/process-refresh.yml` reruns the scripts after every board/refit workflow (Noah, Nov 19: always auto-refresh).
- Glossary GFX cards: every term window has a GFX card button (`assets/js/gfx.js` buildTerm, link `arkndjl.net/process#g-<term>`).
  `data/glossary_gfx.json` is written by `scripts/glossary_gfx.py` (rerun after a season file or refit): compact cards from
  `research/glossary_gfx_base.json` (16:9, formula + one picture) and explainer cards (3:4, and 16:9 from the "GFX 16:9" button, `buildWide`: stands for, what, use, formula,
  held-out test vs similar metrics, distribution/calibration, top 10 from the site's data) from its EXPLAIN builders. Keys =
  the term exactly as in `data/library.json`; a term with no entry gets the plain card. Test numbers come from backtest files
  only, reported as they are even when ours does not win.
- Data Sources tab: `{{< datasources >}}` reads `data/data_sources.json`. A new fetcher that pulls from a new outside
  source adds the source there (name, link, what the site takes from it).

## ARKLOG (Process > ARKLOG, /process/#log; was /arklog/, before that "site data")

- The dated record of every change on the whole site (ARKBOARD, 1NT, LAURSEN_111, ST. CLAIRE, ARKLIBRARY, site) plus the site
  data tabs (traffic, build, data). `scripts/arklog.py` reads the merged pull requests (cache `scripts/data/arklog_prs.json.gz`)
  into `static/data/arklog.json` (rows, `assets/js/arklog.js`) and `data/arklog.json` (tallies and charts for the scoreboard and
  the Process overview); process-refresh.yml reruns it. Never hand-write a row. `python3 scripts/arklog.py --test` after a parser change.
- A pull request description is the log entry, in Noah's voice (below). A model or metric test ends with its own line,
  `ARKLOG: shipped · R² .643 to .732 · t = 2.1` (`shipped`, `part shipped` or `failed`; then the one held-out number that
  decided it, before to after, and its t; leave the number out when there is no single one). That line is taken as
  written. Without it the row is read by pattern, which misreads often: check the new row on /process/#log after the merge
  and correct it in `research/arklog_fix.json`. Every test through #1304 was read against its write-up on Nov 27 and is
  held there (`v`, `e`, `tt`); do not regenerate those entries.
- Hidden pages (Franchise Fantasy, the ST. CLAIRE style guide) never appear in the log (`OUT` in arklog.py).
- Copy cleanups (taglines, blurbs, intros, rewrites into Noah's words) are never logged, and no row mentions AI (Noah, Nov 28):
  `NOAI` drops the row, `AI_LINE` drops a description line; earlier rows are hidden in the fix file.
- Content rows (`k: "content"`, `content_rows` in arklog.py, Noah Nov 28): YouTube uploads (ARKNDJL, LAURSEN_111, YTST), LAURSEN_111
  Twitch streams, 1NT ESEA matches, articles, and ST. CLAIRE releases (a track in content/arkndjl-music.md with `date = "YYYY-MM-DD"`).
  Read from the social pulls, data/esea.json and content/; they sit beside the changes but never count as changes or tests.
- Process updates: one post a month ("PROCESS #N: ... / <month> updates", PROCESS in capitals), front matter `series = "process"`, tags include "process" and "arklog", and
  `month = "YYYY-MM"`, listed by ARKLOG > updates. It covers every section of the site that month: models and metrics,
  features, bug fixes, 1NT, ST. CLAIRE, videos and articles released, social data, site data, with site screenshots and
  charts. Start from `python3 scripts/arklog.py --month YYYY-MM`.
- GFX: log row card (`buildLog`), scoreboard (`buildBoard`), sport sheet (`buildSheet`) in `assets/js/gfx.js`.

## Voice (ARKLOG, articles, Process)

- Everything published is in Noah's voice (Noah, Nov 27): plain full sentences, numbers stated as they came out, failures
  included. No LLM phrasing or formatting (dashes as punctuation, bold lead-ins, "not just X but Y", rhetorical questions,
  summary closers), no advertising or marketing, no taglines. Ask Noah for writing samples when unsure; the posts
  `introducing-xpm` and `introducing-cbb-xpm` are the reference.

## Copy: no intros or descriptive blurbs

- No intro, lede, kicker, subtitle or descriptive blurb on any page, tab, card or window ("how arkndjl.net looks and
  reads", "every sport's X in one table", "where they will go"). Titles, labels, column headers, data and numbers only;
  let the page speak for itself. When unsure, cut.
- A note on how a table is built goes in the `about` of `wintable-close.html`, which is only the status bar's hover
  title, never a visible paragraph. Column meanings go in `<th title>` tooltips.
- Method prose lives only in Process. Model and backtest tabs on sport pages show tables,
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
- Labels with no glossary term of their own are listed under Process > Data > abbreviations, written from
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
- Recruit positions (Nov 28): the Pos cell on the CFB and CBB class tables (and so the recruit card) shows the projected college
  position, `scripts/recruit_pos.py` -> `data/recruit_pos.json` ("<class>|<name>": label, hover odds), partial `recpos.html`. A second
  spot shows at 30% (CFB: DB/WR, S/LB) or 35% (CBB: G, G/F, F, PF/C); the listed code stays when the projection agrees. Fit by hand
  (`--fit`, cfbfastR rosters + Barttorvik roles); the recruit workflows only apply it. Not an FV input (failed both sports Nov 28).
- Moves on every player card come from `static/data/moves/<sport>.json`, written by `scripts/player_moves.py` (rerun by the
  recruit news workflow) from files already in the repo; headline and transaction rows are kept in
  `scripts/data/player_moves_hist.json.gz`. A new kind of move needs a label in `MV_LAB` (gfx.js).

## Class rankings (every school, every commit; Noah, Nov 28)

- Every board program is ranked in every class, schools with no commit yet too (they share the last rank). Commits only
  On3's team lists name (`data/class_offboard.json`, `scripts/class_offboard.py` from the HS ARK stars packs) count in
  the commits and star buckets at their HS ARK stars, 1 at the lowest, and xFV 20, so they add no class points: their
  points failed held out (`scripts/research/class_unranked_nov28`, t -2.05; a 0.5-star tier t -2.01). `everyClass` in
  `scripts/cfb_recruit.mjs`, `class_ranks` in `scripts/cbb_recruit_fit.py`.
- classGFX shows leads, visits and offers on every card (`buildClassCard`): a column beside a small class, one-line rows
  under a big one, across the card with no commit. Offers = On3 program offer lists (`on3_commits.mjs --offers`, packed to
  `scripts/data/class_offers.json.gz`) plus each pulled recruit's On3 recruitment (`of` in the live/committed packs).
  School slugs for every program: `data/school_slugs.json` (`class_offboard.py --slugs`).

## DECT (Declare, Even, College, Transfer; was DEC, before that DoR)

- A decision metric in dollars (what is worth most to him), separate from Ret% and Transfer% (what he will do). Board values are
  Declare / Even / College / Transfer (Noah, Nov 27); never "DoR", "DTR", "DEC", "Return", "Equal" or "Toss Up". `scripts/dect.py`
  is fit by hand (needs the CBB kit and `scripts/xaav.py`'s Basketball-Reference cache) and writes `data/dect_fit.json`: rookie
  deal and later earnings by pick and draft age (NFL from OverTheCap contracts, NBA from salary history), pick spread from players
  with no choice (CFB grads, CBB seniors), outcome bins by pick. College = xNIL x the school's pay per market dollar (roster yNIL / xNIL) + the same draft value a year older, Transfer = the
  same on xNIL; each side is a certainty equivalent (log utility); Even = the top two are inside one standard error; the mean edge
  stays in the hover. Returners' own record is the downside case on Process, never the model (they are a selected sample).
  `dectOf` in `scripts/cfb_teams.mjs` and `nba_dect` (read by `scripts/cbb_tabs.py`) write `dect` / `dectL` / `dectD` / `dectM` /
  `dectP` / `dectT` on the draft boards. Refit after each draft and when the rookie scale in `scripts/cfb_declare_econ.py` moves.

## Flip predictions (recruit transactions, news)

- Two kinds, both alerts only (they move nothing on the boards). A 247 Crystal Ball for a school other than his commitment
  is a `cb` row with `fr` (shown "crystal ball flip"): from 247 headlines (`scripts/recruit_news.py`), or, when only a post
  carries it (247 serves no feed a bot may read), a row in `data/crystal_balls.json` with the post's link. On3/Rivals flip
  picks (`fp`) are experts whose latest pick, made since he committed, names another school: `scripts/player_moves.py`
  from the daily committed On3 pull (recruit-leans.yml) into `data/recruit_extra.json` "flips". `scripts/news.py` posts both (w 45).

## NIL deals ledger

- A confirmed NIL deal is one row in `data/nil_deals.json` (player, team, season, amount for that season, date, source; `cls` for a
  recruit). Nothing else is typed: the next board runs move the player's yNIL / xNIL half way to the report (`NIL_DEALS` in
  `scripts/fetch_cfb.mjs`, `scripts/cbb_market.py`), `scripts/transactions.py` and `scripts/recruit_news.py` list it in the
  transactions and recruit transactions tabs (`k: "nil"`), and `scripts/news.py` posts it. School budgets are `data/nil_budgets.json`.
- `scripts/nil_deal_scan.py` (recruit news workflow, every 3 hours) adds rows from headlines (`auto: 1`): NIL or revenue share, a
  dollar amount, one board player, his school or a unique graded name, a national outlet or two outlets, $8M a season at most.
  The rest wait in `scripts/data/nil_deal_candidates.json`. A new false match gets a case in its `--test` and a pattern in `NOT`.
- Football position pay (`XNIL.pos` in `scripts/fetch_cfb.mjs`) and the basketball mid- and low-major levels (`XNIL` in
  `scripts/cbb_recruit_fit.py`) are set on the College Sports Commission's yearly pay report (`scripts/research/nil_nov27/pos2.py`,
  `cbb_levels.py`): redo both when a new report is out.

## HS ARK stars (every college player's high school grade)

- `scripts/arkstars_hist.py` grades past classes (2008 on) with the same index and cuts as the live recruit tabs, one row a
  recruit from ESPN's class lists, the 247 composite and On3's team commit lists (`scripts/on3_commits.mjs`; team id lists in
  `scripts/data/arkstars_on3_teams.json` and `arkstars_on3_extra.json`). Packs: `scripts/data/arkstars_hist_cfb.json.gz`,
  `arkstars_hist_cbb.json.gz`. No flag = the join only: `static/data/arkstars-cfb.json`, `arkstars-cbb.json` (by ESPN id, with
  `how` = how he was matched) and `data/arkstars_hs.json` ("Name|Team" -> stars). `--update` folds a new On3 pull in, `--pull`
  rebuilds every class (needs the full On3 cache), `--test` reruns the held-out tests into `data/arkstars_hist_research.json`
  (the Process "ARK stars" entry reads it). `.github/workflows/arkstars-hist.yml`: weekly pull, join after each board run.
- A table shows it with `{{ partial "hsark.html" (dict "sport" "cfb" "name" .name "team" .team) }}` under an `HS` header
  (portal, transfer watch, re-signed). No source lists him = 1 star; specialists get no grade. A change to how thin rows are
  graded must pass the forward test (fit 2011-19, test 2020-21) before it ships.

## NIL agencies (market > agencies, CFB and CBB)

- `data/agencies.json` is the ledger: one row a player or recruit and source (agency, agent, scope, source URL, date,
  confidence high / medium / low). "Family" = a relative handles his deals, "None" = a source says he has no agent. Never
  guessed: a player no source names stays out, and a named agent with no named firm stays out. Agency spellings are folded by
  `ALIAS` in `scripts/agencies.py`.
- `scripts/agencies.py` joins the ledger to the boards through the shared name matcher and writes `data/agencies_board.json`
  (the agencies and agency clients subtabs, `layouts/shortcodes/agencies.html`) and `static/data/agencies.json` (the agency
  line on player and recruit cards, `pcAgency` in gfx.js); process-refresh.yml reruns it. `--test` after a change.
- Drafted clients are tracked forward from the 2027 drafts, never backfilled (Noah, Nov 28): once a year's NFL / NBA draft is complete
  on ESPN, `record_drafts` in `scripts/agencies.py` writes every ledger college client who was picked to `data/agency_pros.json` with
  the agency on file that day and marks the year done; the board shows Drafted, 1st rd and Pro% (drafted / (drafted + college clients now)).
- The board shows tendency scores, not x/y/zNIL (Noah, Nov 28): plus scores, 100 = the average agency, 25 = one SD, each the agency's
  mean client value shrunk by (sum + k x mean) / (n + k). Deal+ = -zNIL / SD (paid above worth), Breakout+ = FV - mean FV at his ARK
  stars and class. A score shows only for a sport where it passed the split-half test (`scripts/research/agencies_nov28/tendency.py`
  -> `research/agency_tendency.json`, p < .05 weighted and unweighted; rerun by hand when the ledger grows). Situation+ (FV growth),
  Reach+ (power-conference spot) and Stability+ (stayed) failed Nov 28; CBB had nothing pass. Recruits count for talent only.
  Agency+ (lead column, Nov 28) = mean of z-scored parts: Deal (COMPOSITE; Breakout+ left out, it measures the clients, Noah) as the shrunk edge sum(v - mu) / ((n + k) sd), times n
  only when above zero (Noah: big rosters not charged per player for a low score) + sent (pre-draft-process first-round picks); `components` in agencies.py; forward test 2022-24 -> 2025-26 sends in
  `scripts/research/agencies_nov28/compose.py` (research/agency_composite.json).
  The 2022-26 R1 backfill in agency_pros.json (`backfill: 1`) counts nowhere (Noah, Nov 28: sources too thin); sent starts 2027.
  Drafted counts only agencies signed before the draft process (declaring; Dec 1 football, Mar 15 basketball), never the pro agent.
  GFX: `buildAgency` (one agency) and `buildAgencyBoard` (the board), both 16:9.

## Season rollovers (calendar, phases, post days)

- One calendar per sport: `data/seasons/<sport>.json` (league dates `events`, step `keys`: phase, season, draft, class,
  post, esea...; site `steps`; `bumps` = hard-coded constants that follow a key). Read it through `scripts/season.py` /
  `scripts/season.mjs` (`--get cfb class` in workflows), never a new month cutoff. Phases: preseason, regular, postseason, offseason.
- `scripts/season_roll.py` (season-roll workflow, twice a day, catch-up safe) does each step once on its date: archive to
  `scripts/data/history/<sport>/<season>/`, bump constants (all or none, compiled and tested, put back on failure), run,
  alert (hand jobs, GitHub issue `lead` days ahead). State in `data/season_state.json`; ARKLOG > calendar shows it all.
  `python3 scripts/season_roll.py --plan` and `--on DATE --dry` rehearse; `--test` after any calendar change.
- A new hard-coded season constant goes in its sport's `bumps` (auto 0 when it needs a refit or new ids first). A
  year-named file a workflow commits uses a glob. Weekly post day = calendar `post` (rank_moves.py, fetch_cfb.mjs).
- Dates a league hasn't published carry `est: 1`; replace them when announced (NBA Finals/draft, NHL playoffs, ESEA S60...).

## Article views and favorites

- Every post shows its views and a "favorite" button with the platinum pixel ARK star and its favorite count in the post meta line (article page, home and
  /posts/): `layouts/partials/poststats.html` + `assets/js/poststats.js`, counted by the site Worker (`/api/posts`, Durable
  Object `PostStats` in `worker/site.js`). A view is one a visitor (hashed IP + user agent, salted per day) per article per day,
  bots and other origins skipped. A favorite is one per browser (random id in local storage) and can be taken back; per IP a day,
  5 favorites of one article and 40 clicks in all. No setup: a new post gets both by itself. Only articles from PROCESS #0 on show them (`postStatsFrom` in hugo.toml; Noah, Nov 28: older ones were not counted).
  Every star button (articles, list strip, your favs, songs, video.exe) uses one sprite: `--ark-star` (mask) and `--ark-star-on` (colour) on
  :root in style.css, a 9 x 9 grid drawn at 9 or 18 px only (never a fractional scale). Favoriting plays a pixel spark burst (none under reduced motion) and a quiet 8-bit blip made with WebAudio (Noah, Nov 28: star, not heart).
- `scripts/post_stats.py` (site-stats.yml, every 6 hours) samples the counts into `data/post_stats.json`; `scripts/milestones.py`
  reads it for the article milestones in ARKLOG. Process > ARKLOG > traffic has articles.exe (`layouts/shortcodes/articlestats.html`,
  in TABS traffic of `scripts/library_build.py`): one row an article, live counts, sorts on every header.
- Article lists (home and /posts/) have a strip on top (`layouts/partials/postbar.html`, `assets/js/postbar.js`): search, type, tag,
  sort (newest, views, favorites) and a favorited toggle (this browser's stars). Type is the post's front matter `form` (board, method,
  research, analysis, essay, process, list, video, tool; `kind` is reserved by Hugo). Every post is on one page (`pagerSize = 100`).
  Tags are the search terms: give each post its sport, league, topic, metric names (xpm, fv, war) and teams or players it is about.
- video.exe (`layouts/partials/home-video.html`) has the same kind of strip under its channel buttons: find, tag, favorited (favs.js).
  Video tags are never typed per video: `data/video_tags.json` gives each channel its tags and a regex on the title adds the rest
  (ARKMIX -> arkmix); a new kind of video gets a rule there. The playing video's tags show on the LCD.

## articleGFX (every article)

- Every post has an articleGFX button (layouts/_default/single.html, `buildArticle` in assets/js/gfx.js): a 16:9 card with the
  title, each section's heading over a comma list of its key words, and the article's own figures. No tweet or post text (Noah, Nov 28: he writes his own).
- Each new article gets a `[gfx]` block in its front matter: `keys` = one comma list a section, in order (Noah, Nov 28: key words
  and taglines from the section, not lines from it). `python3 scripts/article_gfx.py`
  (in the build gate) checks every key word is in its section.
