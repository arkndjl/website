# arkndjl brand

Clean, cybergothic, terminal-native. Purple ground, lilac structure, teal voice. The mark is the alchemical glyph 🜎 (U+1F70E, philosophers' sulfur), set in Noto Sans Symbols.

The full guide with every element rendered is `exports/brand-guide.png` (also `brand-guide.pdf`).

## Palette

| Name | Hex | RGB | Use | Contrast on purple |
| --- | --- | --- | --- | --- |
| purple | `#4a3b6b` | 74, 59, 107 | background (site `--background`) | |
| lilac | `#c8c7ff` | 200, 199, 255 | accent: links, logo, rules, labels (site `--accent`) | 6.1 : 1 (AA) |
| teal | `#7fffd4` | 127, 255, 212 | text, wordmark (site `--foreground`) | 8.1 : 1 (AAA) |
| deep purple | `#3a2d56` | 58, 45, 86 | vignettes, secondary surfaces | |
| NYU violet | `#57068c` | 87, 6, 140 | the NYU badge only, white text, 2px lilac outline | |
| white | `#ffffff` | 255, 255, 255 | badge text only | |

## Logo files (`exports/`)

| File | What |
| --- | --- |
| `logo-glyph-lilac.svg` / `.png` | the glyph, lilac, transparent. Use on purple. |
| `logo-glyph-purple.svg` / `.png` | the glyph, purple, transparent. Use on lilac or white. |
| `logo-glyph-teal.svg` / `.png` | the glyph, teal, transparent. Secondary. |
| `logo-emblem-lilac.png` | ringed emblem (double ring + four ticks), lilac, transparent |
| `logo-emblem-purple.png` | ringed emblem, purple, transparent |
| `logo-lockup.png` | emblem + wordmark, transparent |
| `logo-lockup-on-purple.png` | emblem + wordmark on purple |
| `wordmark-teal.png` / `wordmark-purple.png` | "arkndjl" in Fira Code 700, transparent |
| `twitter-avatar.png` | profile picture: purple glyph with a teal outline on lilac (1000 × 1000). Also the favicon, on transparent. |
| `twitter-avatar-inverse.png` | profile picture, inverse: lilac glyph with a teal ring and ticks on purple |
| `logo-glyph-deep.svg` | the glyph in deep purple: the giant background glyph on banners and the site |
| `logo-glyph-tile.svg` | the glyph centred in a square cell: the wallpaper tile (half-drop repeat) |
| `icons/*.svg` | pixel-art marks (16 × 16 grid): the section marks arkndjl (brush + note), arkboard (draft board), arklibrary (open book), and the social icons twitter, substack, github, youtube, linkedin, soundcloud, mail, rss. Built by `make-icons.py`; socials are inlined in the site header, section marks sit next to their menu entries. |

Rules: clear space of one quarter of the emblem's diameter; minimum sizes glyph 16px, emblem 48px, wordmark 24px; only the palette colours; never stretch, rotate or add effects.

## Social images (`exports/`)

| File | Size | Notes |
| --- | --- | --- |
| `../static/og-image.png` | 1200 × 627 | wide share card (og:image: Facebook, Discord, LinkedIn, iMessage) |
| `../static/og-square.png` | 1200 × 1200 | square share image for X's summary card (twitter:image): emblem only |
| `twitter-banner.png` | 1500 × 500 | X header. Lower rows start at x = 400 so the profile picture does not cover them. |
| `youtube-banner.png` | 2560 × 1440 | YouTube banner. Emblem + wordmark inside the 1546 × 423 safe area. |

## Type

- MS PGothic, as its 16px bitmap strike converted pixel for pixel into an outline web font (`static/fonts/mspgothic-pixel.woff2`, built by `make-pixel-font.py` from `fonts/msgothic.ttc`, which is not committed). Same drawings as MS Gothic, proportional widths so slim letters sit tight. Use whole multiples of 16px: 16 body, 32 bio/links/labels, 128 wordmark.
- Noto Sans Symbols 500 for the glyph (`fonts/NotoSansSymbols[wght].ttf`, OFL).
- Fira Code only for code blocks on the site.
- Lowercase by default; uppercase only for tracked labels (tracking `.25em`) and ARKBOARD.

## Elements

Flat only: no gradients, no glow. Grid (48px, lilac at 7%); glyph wallpaper (half-drop tile, lilac at 12% on images, 5% on the site); giant deep-purple glyphs bleeding past the frame, some flipped; inset frame with "+" corner marks; stripe bands (2px lilac every 10px, echoing the site header); ringed emblem; underlined lilac links separated by `::`; the NYU badge. All defined in `theme.css`. Banners carry only the emblem, the wordmark, the two sites and the badge; nothing is set smaller than 48px on the X header because phones show it at about a quarter size.

## Regenerating

```sh
pip install fonttools brotli                              # once
npm i -D playwright && npx playwright install chromium    # once
python3 brand/make-glyph.py        # glyph outline -> favicon.svg, logo-glyph-*.svg, data/favicon.json
python3 brand/make-pixel-font.py   # msgothic.ttc 16px strike -> static/fonts/msgothic-pixel.woff2
python3 brand/make-icons.py        # pixel social icons -> layouts/partials/icons.html, exports/icons/
node brand/render.js           # share card, favicons, banners, logo PNGs, brand guide
```

Templates: `og-image.html`, `og-square.html`, `twitter-banner.html`, `youtube-banner.html`, `logo.html`, `avatar.html`, `favicon.html`, `brand-guide.html`, all sharing `theme.css`.

## Pixel icons and sprites

Two generators turn ASCII pixel maps into inline SVG, so everything stays crisp at integer scales and takes its colours from the site's CSS variables.

- `make-icons.py`: 16×16 single-colour icons (`#` = filled). Writes `layouts/partials/icons.html` (a `<symbol id="icon-NAME">` sprite used with `<use href="#icon-NAME">`, `fill: currentColor`), `exports/icons/*.svg` and `static/img/icons/*.svg` (lilac copies for the menu). Includes the social icons, the section marks (arkndjl, arkboard, arklibrary), list-window icons (tv, film, note, pointer, calendar, brush, events) and the player controls (play, pause, stop, prev, next, vol, mute).
- `make-pixel-art.py`: multi-colour, multi-frame sprites. Each sprite is a list of frames; each frame is a W×H grid of palette codes (`l` lilac, `t` teal, `p` purple, `d` deep purple, `k` darkest, `v` NYU violet, `w` white, `.` transparent). Writes `layouts/partials/px/NAME.html` (one `<svg class="px px--NAME px--nFRAMES">` with a `<g class="px__f" style="--i:N">` per frame), per-frame previews in `exports/pixelart/`, and a contact sheet (`exports/pixelart/sheet.html` + `sheet.png`, rendered by `render-pixelart.js`).

Sprites: `cassette` 64×40 (8 frames, reels turn), `eq` 40×16 (8), `disc` 32×32 (8), `notes` 24×24 (4), `star` 8×8 (4), `easel` 48×40 (6), `calendar` 32×24 (2), `glyph` 24×24 (4, colour breathes). The site CSS (`.px`, `.px__f`, `px-nN` keyframes in `static/style.css`) shows one frame at a time with stepped timing; `--px-dur` on a sprite sets its loop length, sizes are fixed at integer multiples of the pixel grid, and animations pause under `prefers-reduced-motion`. The music player (`layouts/shortcodes/arkplayer.html`) freezes its sprites while nothing is playing.

```sh
python3 brand/make-icons.py
python3 brand/make-pixel-art.py            # also renders the sheet when node + Playwright are available
NODE_PATH=/opt/node-tools/node_modules node brand/render-pixelart.js
```
