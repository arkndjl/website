# arkndjl.net

Personal site of [arkndjl](https://arkndjl.net): sabermetrics, prospect evaluation, economics, art and music. Built with [Hugo](https://gohugo.io) and the [Terminal](https://github.com/panr/hugo-theme-terminal) theme, deployed to Cloudflare, which runs Hugo at build time and serves the generated `public/` folder (see `wrangler.toml`). `public/` is build output and is not tracked in git.

## Layout

| Path | What it is |
| --- | --- |
| `hugo.toml` | Site config: title, menu, site-wide links (`[params.links]`), theme options |
| `content/posts/` | Articles. Front matter conventions are in `archetypes/posts.md` |
| `content/eephus.md` | Page describing [eephus.io](https://eephus.io) / MLB PROSPX |
| `content/arkboard.md` | ARKBOARD hub: current boards, version history, NBA v3 table |
| `content/about.md`, `socials.md`, `art.md`, `music.md` | Static pages linked from the menu |
| `layouts/partials/extended_head.html` | Extra `<head>` tags: theme color, font preload, `rel=me`, schema.org JSON-LD |
| `layouts/partials/footer.html` | Footer override with the site links from `[params.links]` |
| `layouts/shortcodes/card.html` | `{{< card url="..." title="..." >}}…{{< /card >}}` call-out box |
| `static/style.css` | Custom CSS loaded after the theme (tables, cards, TOC) |
| `static/img/`, `static/audio/` | Media referenced from posts |
| `themes/terminal/` | Vendored theme (edit via overrides in `layouts/`, not in place) |

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

The site asks for MS Gothic first and falls back to the theme's Fira Code, so visitors with MS Gothic installed (Windows) see it and everyone else sees Fira Code. To show it everywhere, and to use it in the brand images, the font file has to be in the repo: copy `msgothic.ttc` from `C:\Windows\Fonts` to `brand/fonts/`, then it can be subset to a small web font and wired into `static/style.css` and `brand/theme.css`. Note that Microsoft's font license does not allow web embedding; that is a decision for the site owner.
