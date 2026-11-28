# Design rules

## Look

- Pixel art for site elements (icons, bars, badges, flags, stars, tiles). Y2K, retro and analog on purpose, as the
  opposite of minimalist "frictionless" design.
- Palette: purple, teal (aquamarine) and lilac. Page background `#4a3b6b`; lilac `#c8c7ff` / `#9a8cc4`; teal
  `#7fffd4`; platinum `#b9f2ff` for ARK stars.
- One font everywhere: MS PGothic (the site's pixel cut, `static/fonts/mspgothic-pixel.woff2`). No second face in
  pages, GFX or guides.
- No emoji anywhere: pages, GFX, news, log rows.
- Team logos are full colour and full resolution, never pixelated (the one exception to the pixel look). Never add
  `image-rendering: pixelated` or a point-filter step to logos.
- ARK stars are flat platinum; 5-star+ adds the stepped ice-to-white shimmer everywhere it shows (boards, cards,
  GFX). Industry stars stay lilac. Reduced motion = still.
- Star buttons (favorites) use the one `--ark-star` sprite at 9 or 18 px only, never a fractional scale.

## GFX cards

- Share GFX for X/Twitter are 16:9 unless a card type says otherwise (explainer cards also come in 3:4).
- Clean layout: no overlap, no wrap, no cut text; text as big as fits.
- Every table GFX keeps name, position, class, team logo and FV; the sorted column and the weekly move column are
  added and never dropped. Full-league GFX show every team (32 / 30).
- Column groups are visibly boxed or tinted (the class rankings pattern): count, rate, value and delta columns drawn
  in tinted cells, the lead metric in the dark cell with the teal underline (`colKind` in `assets/js/gfx.js`).
- Player cards colour percentiles in five tiers. A projection card (recruits) shows predictive numbers only.
- Before showing Noah a GFX or screenshot, check the pixel font actually loaded (`document.fonts`), or render it
  from live arkndjl.net. A local build can fall back to a monospace face.

## Mobile

- Every page and tab must work on a phone: no page-level sideways scroll, a pinned label column on wide tables
  (`assets/js/mobile.js` does it), tap targets 24 px or more. Check phone width before merging a layout change.
