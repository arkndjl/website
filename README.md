# arkndjl.net

Personal site of [arkndjl](https://arkndjl.net): sabermetrics, prospect evaluation, economics, art and music. Built with [Hugo](https://gohugo.io) and the [Terminal](https://github.com/panr/hugo-theme-terminal) theme, deployed to Cloudflare, which runs Hugo at build time and serves the generated `public/` folder (see `wrangler.toml`). `public/` is build output and is not tracked in git.

## Layout

| Path | What it is |
| --- | --- |
| `hugo.toml` | Site config: title, menu, site-wide links (`[params.links]`), theme options |
| `content/posts/` | Articles. Front matter conventions are in `archetypes/posts.md` |
| `content/eephus.md` | Page describing [eephus.io](https://eephus.io) / MLB PROSPX |
| `content/arkboard.md` | ARKBOARD hub (`/arkboard/`): what ARKBOARD is, a card per sport with quick links, FV at a glance. The nav's ARKBOARD entry opens a dropdown of the sport pages (children in `hugo.toml`, pixel icons in `static/img/icons/`) |
| `content/arkboard-college-football.md` | College Football / NFL Draft (`/arkboard/college-football/`): every CFB view in a grouped side navigation (players, games, teams, model & draft); `#games` etc. open a view |
| `content/arkboard-college-basketball.md`, `content/arkboard-baseball.md` | College Basketball / NBA Draft and College Baseball / MLB Draft pages |
| `content/about.md`, `arkndjl.md`, `arklibrary.md` | Static pages linked from the menu. ARKNDJL is own art and music, ARKLIBRARY the collection; both list gallery pieces in their front matter (`[[gallery]]` blocks, images in `static/img/art/`) |
| `layouts/partials/extended_head.html` | Extra `<head>` tags: theme color, font preload, `rel=me`, schema.org JSON-LD |
| `layouts/partials/footer.html` | Footer override with the site links from `[params.links]` |
| `layouts/shortcodes/card.html` | `{{< card url="..." title="..." >}}…{{< /card >}}` call-out box |
| `layouts/shortcodes/gallery.html`, `video.html` | art gallery grid from front matter; framed YouTube embed (`{{< video id="..." width="560" >}}`) |
| `static/style.css` | Custom CSS loaded after the theme (tables, cards, TOC) |
| `static/img/`, `static/audio/` | Media referenced from posts |
| `themes/terminal/` | Vendored theme (edit via overrides in `layouts/`, not in place) |

## College Football ARKBOARD (automated)

`data/cfb.json` is the board, built by `scripts/fetch_cfb.mjs` from PFN's impact rankings, On3's college grades and ESPN rosters, then graded by the 20-80 FV model in the same script. The `{{< cfbboard >}}` shortcode renders it on the ARKBOARD page, with filters and sortable columns.

```sh
npm i -D playwright && npx playwright install chromium   # once (On3 is behind Cloudflare)
node scripts/fetch_cfb.mjs             # fetch everything, regrade, rewrite data/cfb.json
node scripts/fetch_cfb.mjs --offline   # regrade from the cached pulls (scripts/.cache/cfb/), e.g. after tuning the model
node scripts/fetch_cfb.mjs --skip-on3  # refetch PFN + ESPN only
```

The board rules (`RULES`), the FCS switch (`INCLUDE_FCS`) and every model constant (`FV_*`, `STARTERS`) are at the top of the script. Hand overrides (dates of birth, FV grades, notes) go in `data/cfb_manual.json`. `.github/workflows/cfb-board.yml` runs the script Mondays and Wednesdays from August through January and commits the result, which triggers the Cloudflare build. It can also be run by hand from the Actions tab. Team logos are pixelated into `static/img/cfb/logos/` when ImageMagick is installed.

The College Football tab has fourteen views: **all FBS** (every graded player, `static/data/cfb-all.json`, loaded on demand, 50 to a page), **draft board** (the same, limited to players eligible for the 2027 draft), **games** (`data/cfb_games.json`: the next unplayed week, with Elo win probabilities and spreads, playstyle from CFBD advanced stats, injuries from ESPN, and each side's top five prospects on offense and defense), **projections** (`data/cfb_proj.json`: the week's top 300 offensive players by projected PPR points, from the same opponent-scaled per-game lines), **game table** (the same week as one sortable table: model spread vs the market line and the edge between them, and each game's projected top three on offense and defense from this season's per-game CFBD stat lines scaled by the opponent), **mock draft** (`data/cfb_mock.json`: the 2027 order from ESPN's NFL standings, needs from ESPN depth charts and contracts, our grades plus positional value and the per-round position counts in `data/cfb_draft_priors.json`), **team talent** and **staff** (`data/cfb_teams.json`: projected starting-22 talent, Elo with a preseason prior from last season's Elo, SP+ and recruiting, TvE, team xNIL, and head coach / coordinator credit). xNIL (expected NIL) is a player's share of his program's NIL budget (anchored to the revenue-share cap: ~$20M at Power 4 schools, ~$3M in the Group of Five, `XNIL`), split by a market index fitted on On3's valuations (FV, position, role, On3 grade, consensus rank). For draft-eligible prospects, FV is then blended toward the grade implied by PFN's industry consensus big board (seven analyst boards averaged), up to 35% with all seven boards (`CONS_W`), because consensus rank was the strongest single predictor of NFL outcome in the backtest. `scripts/cfb_teams.mjs` holds the team, games, staff and mock models. Coordinators come from `data/cfb_staff.json` when present. Recruiting ratings, SP+ and advanced stats come from the CollegeFootballData API, which needs a free key in the `CFBD_API_KEY` environment variable (a repository secret for the workflow); the pulls are cached in `scripts/.cache/cfb/`. Game projections come from `scripts/cfb_model.mjs`. It rates teams with Elo plus opponent-adjusted EPA per play (garbage time removed). The ratings are solved as a ridge regression shrunk toward a preseason prior: last season's Elo, SP+ and efficiency, plus this season's 247 talent composite and returning production, weighted by a regression fit one season ahead. On top of the ratings it adds home field, rest, time zones, travel distance and altitude. The blend weights and settings (Elo K, Elo home field, prior strength) are fit on walk-forward predictions, where each week is rated only on earlier weeks. Fitting uses last season; this season is scored out of sample against the closing line (log loss, Brier, MAE, ATS by edge size). The **model** tab shows that report and the **season odds** tab shows 10,000 simulated seasons (projected wins, conference title game and title, playoff and bowl odds); both are in `data/cfb_model.json`. Win, cover and over chances are normal around the model margin and total. Totals are plays × points per play plus wind, rain and cold (Open-Meteo, cached by game in `weather.json`). A starting QB listed out is replaced by his backup's EPA per play. Every coming game's model line is logged to `data/cfb_edges.json` and graded against the closing line once played. **Availability** (`data/cfb_injuries.json`): Rotoballer's college news (the last ~5 days, each headline clause read for a status) and ESPN's report, matched to rosters; the newest item per player wins, short-term statuses lapse after 9 days, season-ending ones stand until news says otherwise, and `injuries` in `data/cfb_manual.json` overrides both. Statuses carry a chance of playing (out 0, doubtful .25, questionable .6, probable .9) that scales each starter's cost in the projections; a season-ending injury takes the player off the projected depth chart and costs 1 FV (2 for an ACL/Achilles). **Stars** (`stars` in `data/cfb_manual.json`) mark favourites with ★ and fill the **ARKLIST** tab. **Consensus** adds Tankathon's and PFF's big boards to PFN's seven analyst boards (nine in all); a **riser** (↗) is a draft-eligible prospect the model grades 6+ FV above his consensus rank's grade, or a 55+ no board ranks. **FV** also weighs age on a curve (outliers move most), class runway, a first-year bonus at positions where young contributors are rare (measured each run), frame projected to age 22 along each position's age-weight slope, snap share, and ESPN's schedule-adjusted QBR for quarterbacks. **Archetypes** (power/receiving/elusive back, deep threat, YAC weapon, move TE, speed/power rusher, coverage linebacker, lockdown corner…) come from the PFN lines. **Running back roles** (Every Down Back, Early Down Back, 3rd Down Back; the RB role filter and the chip after RB) come from estimated snap shares on standard and passing downs (passing downs: 2nd and 8+, 3rd or 4th and 5+): a back's snap share split by how his backfield share of carries + targets tilts between the two (`rbRoles` in `scripts/cfb_pbp.mjs`). Every-down is 50%+ of the snaps on both, early-down 30%+ on standard downs and 10+ points fewer on passing downs, 3rd-down the mirror; anyone else is a committee back. Calibrated on the 2024 NFL season, where participation data has the true snaps by down: the labels match the true ones for 82% of backs (81% six weeks in) and never mix up early-down and 3rd-down backs. **Kickers and punters** are graded from each team's field goals over expected and punt field position (CFBD drives) credited by share of attempts; a primary kicker's absence prices into the game projections. The **games** tab polls ESPN's scoreboard for live scores while games are on, and **top performers** lists the latest week's top three at each position from CFBD box scores. The workflow runs Sunday through Wednesday, Friday and Saturday. **Play-by-play** (`scripts/cfb_pbp.mjs`): CFBD plays, one call a week, parsed for ball carrier, target, sacker and hurrier, give each player EPA per carry, explosive rates and red-zone production; a stat enters FV only when it holds up in a split-half test (odd vs even games) this season, weighted by that reliability. The existing FV stats are reweighted the same way by their season-to-season correlation in PFN's history (pressure rate repeats at ~.5, sacks per pressure at ~0, so sack conversion is shown only as a regression flag). The age curve was backtested on the 2005-18 drafts (career AV vs the pick's expectation): youth is linear, the old tail steeper. Game-model inputs are kept only when they improve log loss in both the fit and the test season: opponent-adjusted success rate made it; explosiveness and red-zone points per trip did not. **Breakouts** (`data/cfb_breakout.json`) lists first- and second-year skill players whose touches and targets jumped over their last two games; **portal** (`data/cfb_portal.json`) lists this season's transfers with FV and each team's net expected NFL value in minus out; the **staff** tab adds scheme fingerprints (4th-down go rate, tempo, run rate, havoc, stuff rate, explosiveness allowed, as FBS percentiles). FV constants are calibrated against NFL outcomes in `data/cfb_calibration.json` (nflverse drafts 2010-19: tier counts per position, composite reliability, size norms, per-round draft counts); the comments next to each constant give the numbers.

Any markdown table window can get the same sort/filter bar: `{{< wintable filter="FV,Team" >}}` or `{{< board ... filter="POS,FV" >}}` adds a dropdown per named column, plus an "age ≤" box when the table has an Age column.

## Writing a post

```sh
hugo new posts/my-post-slug.md   # uses archetypes/posts.md
```

Set `draft = false` when ready. Useful front matter:

- `description` is shown in the post list and used for SEO / share cards.
- `tags` become `#tag` links; `keywords` feed the `<meta name="keywords">` tag.
- `Toc = true` renders a table of contents from `##` / `###` headings.
- Images: `{{< image src="/img/..." alt="meaningful description" position="center" >}}`.

## Local preview

```sh
hugo server -D      # http://localhost:1313, includes drafts
hugo --minify       # production build into public/
```

`buildFuture = true` is on, so posts dated in the future still publish.

## Share image and favicons

`brand/` holds the brand guide, palette, logo files and the HTML templates for the share image, favicons and social banners; see `brand/README.md`. `render.js` screenshots the templates with Playwright:

```sh
npm i -D playwright && npx playwright install chromium   # once
node brand/render.js
```

Edit the templates and re-run. Banners, logos and the brand guide render into `brand/exports/`; run `python3 brand/make-glyph.py` first if the glyph font changes.

## Typeface

The site is set in MS PGothic's 16px bitmap strike (MS Gothic's pixel drawings with proportional widths), converted pixel for pixel into a small outline web font (`static/fonts/mspgothic-pixel.woff2`) so it renders identically on every OS. `brand/make-pixel-font.py` builds it from `brand/fonts/msgothic.ttc` (copied from `C:\Windows\Fonts`; the source file is not committed since Microsoft's license does not allow redistribution). Code blocks keep Fira Code.

## 1NT/LAURSEN_111: ESEA and FACEIT

`content/laursen_111.md` has two tabs, **1NT** (first) and **LAURSEN_111**. Any tab on the site opens from the URL hash (`/laursen_111/#laursen-111`, `/arkboard/college-football/#draft-board`); old `/arkboard/#…` links forward to the right sport page, and `static/_redirects` adds short links like `/1nt`.

`data/esea.json` is written by `scripts/fetch_esea.mjs` from the FACEIT Data API and rendered by `{{< esea part="..." >}}`:

- `season`, `matches`, `cards`, `players`: the S59 record, standings rank, every match with both teams' box scores (country flags, ARK Rating, swing, map MVP), player cards and season stats. GFX buttons on the season window and each box score make 16:9 graphics.
- `preview`: the next opponent (roster, elo, S59 results and ARK Ratings), map edges (team map win rates shrunk to 50% by 8 maps, log5) a Bo1 veto by minimax with 1NT always banning Inferno then Mirage (`FIXED_BANS`), and a round spread: elo, the expected map and team ARK Rating blended in log-odds into a map win chance, then turned into a per-round win chance and expected round differential with an exact race-to-13 model (MR3 overtime).
- `stakes`: the playoff line (top 48 per Main group), move-ups (top 4 to Advanced, top 2 to the Season Finals), move-downs (under 4 wins) and the Finals prize table, with binomial odds.
- `alltime`: every player's maps for 1NT (from each player's FACEIT match stats, cached and fetched incrementally), with tenure and the seasons/events played.
- `split` (LAURSEN_111 tab): his FACEIT maps split into PUGs, scrims (queue/hub matches with five 1NT members on his side) and 1NT matches (ESEA plus cups), with per-map and per-season tables.

- `form`: every player's last 100 FACEIT maps in 90 days, with All Games / Official (league, cups, qualifiers) / PUGs / Scrims tabs. Talent is 1-5 stars in half steps on the same rolling window (form ARK .70, elo .30; 3 stars = an average player in our league's matches, one star = one SD). The preview's team talent, role matchups, game plan, fanGFX and teamGFX use it.

- Every player gets Entry+, Duel+, Multi+, Clutch+, Util+, AWP+ (AWP impact vs everyone) and Surv+ on the rolling table and player cards, plus a hot/cold flag (ARK over the last 20 maps vs 100). Team talent is the projected five's mean stars, shown next to each team.
- `stakes` adds a 10,000-run season simulation (seed odds, top 4/16/48, the cut line); `model` (`model_log.exe`) freezes each preview's projection at kickoff and scores it (calls, covers, Brier); `lineups` shows map W-L by five-man group and pair (official and scrims, 90 days); the preview's veto dropdown shows the opponent's official maps (90 days). One-match lineups go in `data/cs.json` `matchLineups` (by match id).

Round-level data (pistols, eco/anti-eco, setups, positions) needs match demos, which this API key can't download (FACEIT's Downloads API needs separate approval). `ESEA_DEMO_PROBE` (the workflow's `probe` input) checks access.

ARK Rating 2 fits its weights on round outcomes instead of hand-setting them: over every cached map (both teams' box scores, 90 days), each team's round share is regressed (ridge toward prior weights, sign-constrained, clutches capped) on its players' per-round kills, deaths, damage, multi-kill rounds, entry ±, clutches, assists, enemies flashed, utility damage and flash/utility successes minus the other team's. A player's value is the rounds he adds per round; a KAST-style outcome credit shares half the team's round share over .500 among its five (half equally, half by round MVPs). 1.00 = the average line in our matches, spread matched to HLTV Rating 1.0. `data/esea.json` arkModel has the weights, fit size and R². `rankings` (S59 rankings) lists every team in the division with its standing, round differential, team ARK, talent stars, elo and a power rank.

It needs a FACEIT server API key (developers.faceit.com) in `FACEIT_API_KEY`, a repository secret for `.github/workflows/esea.yml`, which runs every 20 minutes and commits only when something changed. `ESEA_SEASON` moves it to the next season (it otherwise follows `season` in the data file, starting at 59).
