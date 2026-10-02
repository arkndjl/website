# arkndjl.net

Personal site of [arkndjl](https://arkndjl.net): sabermetrics, prospect evaluation, economics, art and music. Built with [Hugo](https://gohugo.io) and the [Terminal](https://github.com/panr/hugo-theme-terminal) theme, deployed to Cloudflare from `public/` (see `wrangler.toml`).

## Layout

| Path | What it is |
| --- | --- |
| `hugo.toml` | Site config: title, menu, site-wide links (`[params.links]`), theme options |
| `content/posts/` | Articles. Front matter conventions are in `archetypes/posts.md` |
| `content/_index.md` | Framed intro block at the top of the home page |
| `content/eephus.md` | Page describing [eephus.io](https://eephus.io) / MLB PROSPX |
| `content/arkboard.md` | ARKBOARD hub: current boards, version history, NBA v3 table |
| `content/about.md`, `socials.md`, `art.md`, `music.md` | Static pages linked from the menu |
| `layouts/partials/extended_head.html` | Extra `<head>` tags: theme color, font preload, `rel=me`, schema.org JSON-LD |
| `layouts/partials/footer.html` | Footer override with the site links from `[params.links]` |
| `layouts/shortcodes/card.html` | `{{< card url="..." title="..." >}}…{{< /card >}}` call-out box |
| `static/style.css` | Custom CSS loaded after the theme (tables, intro, cards, TOC) |
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

`brand/` holds the HTML templates for the Open Graph share image (`og-image.html`) and the favicon (`icon.html`), plus `render.js`, which screenshots them into `static/` with Playwright:

```sh
npm i -D playwright && npx playwright install chromium   # once
node brand/render.js
```

Edit the text or colors in the templates and re-run. The X/Twitter header, YouTube banner and X profile picture (`twitter-banner.html`, `youtube-banner.html`, `avatar.html`) render into `brand/exports/`. Large images are rendered at 2x and downscaled for crisp type.
