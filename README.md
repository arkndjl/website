# arkndjl.net

Personal site of [arkndjl](https://arkndjl.net): sabermetrics, prospect evaluation, economics, art and music. Built with [Hugo](https://gohugo.io) and the [Terminal](https://github.com/panr/hugo-theme-terminal) theme, deployed to Cloudflare, which runs Hugo at build time and serves the generated `public/` folder (see `wrangler.toml`). `public/` is build output and is not tracked in git.

## Layout

| Path | What it is |
| --- | --- |
| `hugo.toml` | Site config: title, menu, site-wide links (`[params.links]`), theme options |
| `content/posts/` | Articles. Front matter conventions are in `archetypes/posts.md` |
| `content/eephus.md` | Page describing [eephus.io](https://eephus.io) / MLB PROSPX |
| `content/arkboard.md` | ARKBOARD hub: a tab per sport (college football, college basketball, HS/college baseball), each with its boards, FV chart and links |
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

The College Football tab has five views: **board** (the players who meet a board rule), **all FBS** (every graded player, `static/data/cfb-all.json`, loaded on demand), **mock draft** (`data/cfb_mock.json`: Tankathon's 2027 order and mock-implied needs, our draft-eligible grades plus positional value), **team talent** and **staff** (`data/cfb_teams.json`: projected starting-22 talent in expected NFL AV, a results-only Elo from ESPN's scoreboard, TvE, NIL+, and head coach / coordinator credit). `scripts/cfb_teams.mjs` holds the team, staff and mock models; `scripts/tankathon.mjs` the Tankathon scraper. Coordinators come from `data/cfb_staff.json` when present. FV constants in `fetch_cfb.mjs` are calibrated against NFL outcomes (nflverse drafts 2010-19) and a PFN backtest; the comments next to each constant give the numbers.

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
