#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Pixel art for "your favorites" (/favorites/), drawn with scripts/pixelart.py's helpers in the px__f frame format:

  layouts/partials/px/hero-favorites.html     the favorites.exe hero: a beating heart in a display case and a list
                                              beside it whose rows light up one by one (8 frames)
  layouts/partials/px/fav-<group>.html        one 24 x 24 sprite a group: teams, players, articles, songs, videos (4 frames)
  static/img/icons/favorites.svg              the menu icon (16 x 16, the heart)
  (the one-colour heart, #icon-favorites in layouts/partials/icons.html, is printed by --symbol)

    python3 scripts/favorites_art.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pixelart import Grid, animated  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PX = os.path.join(ROOT, 'layouts', 'partials', 'px')

K = '#241a3a'      # win-dark
D = '#3a2d56'      # win-well
U = '#57068c'      # title purple
M = '#6d6a9e'      # dim lilac
L = '#c8c7ff'      # lilac
P = '#b46cff'      # purple
T = '#7fffd4'      # teal
W = '#ffffff'
PL = '#b9f2ff'     # platinum
PD = '#7fcbe6'     # platinum shade

ICON = [
    '................',
    '..LLLL....LLLL..',
    '.LPPPPL..LPPPPL.',
    'LPWWPPPLLPPPPPPL',
    'LPWPPPPPPPPPPPPL',
    'LPPPPPPPPPPPPPPL',
    'LPPPPPPPPPPPPPUL',
    '.LPPPPPPPPPPPUL.',
    '..LPPPPPPPPPUL..',
    '...LPPPPPPPUL...',
    '....LPPPPPUL....',
    '.....LPPPUL.....',
    '......LPUL......',
    '.......LL.......',
    '................',
    '................',
]


def heart(g, cx, cy, r, fill, edge, glint=True, shade=U):
    """A pixel heart r wide each side of cx: two lobes and a point, outlined in edge, shaded at the lower right."""
    pts = set()
    lr = r * 0.54
    for y in range(int(cy - r), int(cy + r * 1.2) + 2):
        for x in range(int(cx - r) - 1, int(cx + r) + 2):
            px, py = x + 0.5, y + 0.5
            lobe = any((px - (cx + s * lr * 0.92)) ** 2 + (py - (cy - r * 0.28)) ** 2 <= lr * lr for s in (-1, 1))
            tip = py >= cy - r * 0.28 and abs(px - cx) <= (cy + r * 1.05 - py) * 0.98 and py <= cy + r * 1.05
            if lobe or tip: pts.add((x, y))
    for (x, y) in pts:
        edgy = any((x + a, y + b) not in pts for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        g.set(x, y, edge if edgy else fill)
    for (x, y) in pts:
        if g.get(x, y) == fill and ((x + 1, y + 1) not in pts or (x + 2, y + 1) not in pts): g.set(x, y, shade)
    if glint:
        top = min(y for _, y in pts)
        gx = int(cx - lr * 0.92)
        g.rect(gx - 1, top + 2, 2, 1, W); g.set(gx - 2, top + 3, W)
    return pts


def sparkle(g, x, y, k, c=PL):
    if k == 0: g.set(x, y, c)
    elif k == 1: g.set(x, y, W); g.set(x - 1, y, c); g.set(x + 1, y, c); g.set(x, y - 1, c); g.set(x, y + 1, c)
    elif k == 2: g.set(x, y, W); g.rect(x - 2, y, 5, 1, c); g.rect(x, y - 2, 1, 5, c)


def hero():
    frames = []
    beat = [7, 8, 9, 8, 7, 7, 8, 7]
    for k in range(8):
        g = Grid(64, 40)
        # display case
        g.rect(2, 2, 40, 35, L); g.rect(3, 3, 38, 33, M); g.rect(5, 5, 34, 26, K)
        g.rect(5, 5, 34, 1, D); g.rect(5, 5, 1, 26, D)
        g.rect(3, 33, 38, 1, D); g.rect(8, 37, 28, 2, M); g.rect(8, 37, 28, 1, L)
        for i in range(4): g.set(7 + i * 9, 32, T if (i + k) % 4 == 0 else D)       # base lights
        # the heart and its shadow
        r = beat[k]
        heart(g, 22, 17, r, PL, L, shade=PD)
        g.rect(22 - r + 2, 29, 2 * r - 4, 1, D)
        sparkle(g, 9, 9, (k + 0) % 4 if k % 4 < 3 else 0)
        sparkle(g, 34, 8, (k + 2) % 4 if (k + 2) % 4 < 3 else 0, T)
        sparkle(g, 35, 25, (k + 1) % 3)
        # the list: rows light up one by one, a heart bullet each
        g.rect(45, 4, 17, 30, L); g.rect(46, 5, 15, 28, D); g.rect(46, 5, 15, 3, U); g.rect(57, 6, 2, 1, L)
        lens = [9, 7, 10, 6, 8, 9]
        for j in range(6):
            y = 10 + j * 4
            on = j <= k
            c = PL if on and j == min(k, 5) else (P if on else M)
            g.set(47, y, c); g.set(49, y, c); g.rect(47, y + 1, 3, 1, c); g.set(48, y + 2, c)
            g.rect(51, y + 1, lens[j], 1, L if on else M)
        frames.append(g)
    return frames


def sprite_frame():
    return Grid(24, 24)


def teams():   # a pennant on a pole, waving
    out = []
    for k in range(4):
        g = sprite_frame()
        g.rect(4, 3, 2, 19, L); g.rect(3, 21, 4, 2, M)
        for x in range(6, 21):
            w = (x - 6) / 14
            top = 4 + round(w * 4) + (1 if (x // 4 + k) % 2 else 0)
            bot = 14 - round(w * 4) + (1 if (x // 4 + k) % 2 else 0)
            if bot > top: g.rect(x, top, 1, bot - top, T if x < 9 else P)
        g.rect(10, 8 + (k % 2), 5, 1, W)
        out.append(g)
    return out


def players():   # a jersey whose number blinks
    out = []
    for k in range(4):
        g = sprite_frame()
        g.rect(7, 3, 10, 2, L); g.rect(9, 3, 6, 1, K)
        g.rect(3, 5, 18, 5, L); g.rect(6, 5, 12, 16, L)
        g.rect(4, 6, 2, 3, P); g.rect(18, 6, 2, 3, P)
        g.rect(7, 6, 10, 14, P); g.rect(7, 19, 10, 1, U)
        c = W if k % 2 == 0 else PL
        # 1
        g.rect(9, 9, 1, 7, c); g.set(8, 10, c)
        # 1
        g.rect(14, 9, 1, 7, c); g.set(13, 10, c)
        out.append(g)
    return out


def articles():   # a page whose lines write themselves
    out = []
    for k in range(4):
        g = sprite_frame()
        g.rect(5, 2, 13, 20, L); g.rect(6, 3, 11, 18, W); g.rect(17, 2, 2, 4, M); g.rect(18, 4, 1, 18, M); g.rect(6, 21, 13, 1, M)
        lens = [8, 9, 6, 9, 7]
        for j in range(5):
            if j <= k + 1: g.rect(7, 5 + j * 3, lens[j] if j <= k else lens[j] // 2, 1, U if j else P)
        heart(g, 16, 18, 3, P, U, glint=False)
        out.append(g)
    return out


def songs():   # a record spinning
    out = []
    for k in range(4):
        g = sprite_frame()
        g.disc(12, 12, 10, K); g.disc(12, 12, 9, D)
        for rr in (7, 5): g.disc(12, 12, rr, K); g.disc(12, 12, rr - 1, D)
        g.disc(12, 12, 3, T); g.set(12, 12, K)
        dx, dy = ((0, -8), (6, -6), (8, 0), (6, 6))[k]
        g.set(12 + dx, 12 + dy, W); g.set(12 + dx * 7 // 8, 12 + dy * 7 // 8, L)
        g.rect(19, 2, 2, 9, M); g.rect(17, 10, 3, 2, L)                     # tonearm
        out.append(g)
    return out


def videos():   # a small CRT with a play mark and scanlines that roll
    out = []
    for k in range(4):
        g = sprite_frame()
        g.rect(2, 4, 20, 15, L); g.rect(3, 5, 18, 13, K)
        for y in range(5, 18):
            if (y + k) % 3 == 0: g.rect(3, y, 18, 1, D)
        for i in range(5): g.rect(10, 8 + i, 1 + (i if i < 3 else 4 - i), 1, T)
        g.rect(8, 19, 8, 1, M); g.rect(5, 20, 14, 2, L)
        g.set(19, 16, T if k % 2 else M)
        out.append(g)
    return out


GROUPS = {'teams': teams, 'players': players, 'articles': articles, 'songs': songs, 'videos': videos}


def icon(mono=False):
    g = Grid(16, 16)
    pal = {'L': 'c', 'P': 'c', 'W': None, 'U': 'c'} if mono else {'L': L, 'P': PL, 'W': W, 'U': PD}
    for y, row in enumerate(ICON):
        for x, ch in enumerate(row):
            if ch in pal and pal[ch]: g.set(x, y, pal[ch])
    return g


def svg(g):
    rects = []
    for y, row in enumerate(g.px):
        x = 0
        while x < g.w:
            c = row[x]
            if c is None: x += 1; continue
            x0 = x
            while x < g.w and row[x] == c: x += 1
            rects.append(f'<rect x="{x0}" y="{y}" width="{x - x0}" height="1"' + ('' if c == 'c' else f' fill="{c}"') + '/>')
    return ''.join(rects)


def main():
    with open(os.path.join(PX, 'hero-favorites.html'), 'w') as f:
        f.write(animated('hero-favorites', hero(), 8))
    for k, fn in GROUPS.items():
        with open(os.path.join(PX, f'fav-{k}.html'), 'w') as f:
            f.write(animated(f'fav-{k}', fn(), 4).replace('class="px px--fav-', 'class="px px--fav px--fav-'))
    with open(os.path.join(ROOT, 'static', 'img', 'icons', 'favorites.svg'), 'w') as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" shape-rendering="crispEdges">' + svg(icon()) + '</svg>')
    if '--symbol' in sys.argv:   # the #icon-favorites body for layouts/partials/icons.html
        print(svg(icon(True)))
    print(f'favorites art: hero + {len(GROUPS)} group sprites + icon')


if __name__ == '__main__':
    main()
