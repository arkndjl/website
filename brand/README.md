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
| `twitter-avatar.png` | profile picture: purple glyph on lilac (1000 × 1000) |
| `twitter-avatar-inverse.png` | profile picture: lilac glyph on purple |

Rules: clear space of one quarter of the emblem's diameter; minimum sizes glyph 16px, emblem 48px, wordmark 24px; only the palette colours; never stretch, rotate or add effects.

## Social images (`exports/`)

| File | Size | Notes |
| --- | --- | --- |
| `../static/og-image.png` | 1200 × 627 | share card used by the site (Open Graph / Twitter card) |
| `twitter-banner.png` | 1500 × 500 | X header. Lower rows start at x = 400 so the profile picture does not cover them. |
| `youtube-banner.png` | 2560 × 1440 | YouTube banner. Emblem + wordmark inside the 1546 × 423 safe area. |

## Type

- Fira Code (the site font): 700 wordmark and headings, 600 bio lines, 500 tracked uppercase labels (`.26em`), 400 body.
- Noto Sans Symbols 500 for the glyph (`fonts/NotoSansSymbols[wght].ttf`, OFL).
- Lowercase by default; uppercase only for tracked labels and ARKBOARD.

## Elements

Grid (48px, lilac at 7%) with a soft vignette; inset frame with "+" corner marks; ringed emblem; thin rules with a centred glyph ornament; underlined lilac links separated by `::`. All defined in `theme.css`.

## Regenerating

```sh
pip install fonttools                                     # once
npm i -D playwright && npx playwright install chromium    # once
python3 brand/make-glyph.py    # glyph outline -> favicon.svg, logo-glyph-*.svg, data/favicon.json
node brand/render.js           # share card, favicons, banners, logo PNGs, brand guide
```

Templates: `og-image.html`, `twitter-banner.html`, `youtube-banner.html`, `logo.html`, `glyph.html`, `favicon.html`, `brand-guide.html`, all sharing `theme.css`.
