#!/usr/bin/env python3
"""Pixel art for Process (/process/), drawn on small grids with scripts/pixelart.py's helpers and written as animated
sprites in the px__f frame format (style.css):

  layouts/partials/px/hero-process.html        the process.exe hero: a monitor whose bar chart builds, one bar failing,
                                              a check when it is done, and a log window scrolling beside it (8 frames)
  layouts/partials/px/phil-<tab>.html          one 32 x 32 sprite a Philosophy tab (4 frames)

    python3 scripts/process_art.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pixelart import Grid, animated  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PX = os.path.join(ROOT, 'layouts', 'partials', 'px')

K = '#241a3a'      # win-dark
D = '#3a2d56'      # win-well
B = '#4a3b6b'      # background
U = '#57068c'      # title purple
M = '#6d6a9e'      # dim lilac
L = '#c8c7ff'      # lilac
P = '#b46cff'      # purple
T = '#7fffd4'      # teal
F = '#ff9ec7'      # pink (failed)
W = '#ffffff'
PL = '#b9f2ff'     # platinum


def line(g, x0, y0, x1, y1, c):
    n = max(abs(x1 - x0), abs(y1 - y0)) or 1
    for i in range(n + 1):
        g.set(round(x0 + (x1 - x0) * i / n), round(y0 + (y1 - y0) * i / n), c)


def frame_box(g, x, y, w, h, c):
    g.rect(x, y, w, 1, c); g.rect(x, y + h - 1, w, 1, c); g.rect(x, y, 1, h, c); g.rect(x + w - 1, y, 1, h, c)


def hero():
    heights = [6, 10, 5, 13, 9, 16]
    frames = []
    for k in range(8):
        g = Grid(64, 40)
        # monitor
        g.rect(3, 2, 42, 33, L); g.rect(4, 3, 40, 31, M); g.rect(6, 5, 36, 25, K)
        g.rect(4, 33, 40, 1, D)
        g.rect(19, 35, 10, 2, M); g.rect(13, 37, 22, 2, L); g.rect(13, 38, 22, 1, M)
        g.rect(38, 31, 3, 1, T if k % 2 else D)                      # power led
        # chart
        g.rect(9, 26, 30, 1, M); g.rect(9, 8, 1, 18, M)
        for i, h in enumerate(heights):
            if i <= k:
                x = 11 + i * 5
                hh = h if i < k or k >= 6 else max(2, h // 2)          # the newest bar is still rising
                g.rect(x, 26 - hh, 3, hh, F if i == 2 else T)
                g.rect(x, 26 - hh, 3, 1, W if i != 2 else '#ffe0ee')
        if k >= 6 and k % 2 == 0:                                     # a check when the run is done
            for (x, y) in ((23, 8), (24, 9), (25, 10), (26, 9), (27, 8), (28, 7), (29, 6)):
                g.set(x, y, T); g.set(x, y + 1, T)
        if k % 2 == 0:
            g.rect(8, 7, 3, 1, L)                                     # cursor
        # log window
        g.rect(47, 5, 15, 27, L); g.rect(48, 6, 13, 25, D); g.rect(48, 6, 13, 3, U)
        g.rect(58, 7, 2, 1, L)
        verdict = [T, P, F, T, T, P, T, F, T]
        lens = [9, 6, 8, 5, 9, 7, 4, 8, 6]
        for j in range(8):
            y = 10 + j * 3 - (k % 3)
            if 10 <= y <= 29:
                i = (j + k // 3) % len(lens)
                g.set(49, y, verdict[i]); g.rect(51, y, lens[i], 1, L if j else W)
        frames.append(g)
    return frames


def scale():
    out = []
    for k, tilt in enumerate((-3, 0, 3, 0)):
        g = Grid(32, 32)
        g.rect(15, 6, 2, 20, L); g.rect(10, 26, 12, 2, L); g.rect(8, 28, 16, 2, M)
        g.rect(14, 4, 4, 3, P)
        line(g, 4, 9 + tilt, 27, 9 - tilt, W)
        for (cx, side, c) in ((5, 1, T), (26, -1, P)):
            cy = 9 + tilt * side
            line(g, cx, cy, cx - 3, cy + 7, M); line(g, cx, cy, cx + 3, cy + 7, M)
            g.rect(cx - 4, cy + 8, 9, 2, c); g.rect(cx - 3, cy + 10, 7, 1, c)
        out.append(g)
    return out


def hourglass():
    out = []
    for k in range(4):
        g = Grid(32, 32)
        g.rect(7, 3, 18, 3, L); g.rect(7, 26, 18, 3, L)
        for y in range(6, 26):
            w = abs(y - 15.5) * 0.75 + 1
            x0, x1 = round(16 - w), round(16 + w)
            g.set(x0 - 1, y, M); g.set(x1, y, M)
            if y < 15 and y >= 7 + k * 2:
                g.rect(x0, y, x1 - x0, 1, T)
            if y > 16 and y >= 25 - k * 2 - 1:
                g.rect(x0, y, x1 - x0, 1, T)
        for y in range(15, 24 - k * 2):
            if (y + k) % 2 == 0:
                g.set(16, y, T)
        g.rect(28, 25 - k * 5, 2, k * 5 + 1, P)                       # the count that builds
        out.append(g)
    return out


def projection():
    out = []
    steps = [(4, 26), (8, 22), (12, 22), (16, 17), (20, 17), (24, 11)]
    for k in range(4):
        g = Grid(32, 32)
        g.rect(3, 28, 26, 1, M)
        for i, (x, y) in enumerate(steps[:3 + k]):
            g.rect(x, y, 4, 28 - y, T if i < 5 else PL)
            g.rect(x, y, 4, 1, W)
        tw = PL if k % 2 else W                                       # the star at 80
        g.set(27, 1, tw); g.rect(26, 2, 3, 1, tw); g.set(27, 3, tw)
        if k % 2 == 0:
            g.set(25, 2, L); g.set(29, 2, L)
        out.append(g)
    return out


def globe():
    out = []
    for k in range(4):
        g = Grid(32, 32)
        g.disc(16, 16, 12.5, U)
        g.disc(16, 16, 11.5, D)
        for y in (9, 16, 23):
            w = math.sqrt(max(0, 11.5 ** 2 - (y + 0.5 - 16) ** 2))
            g.rect(round(16 - w), y, round(2 * w), 1, M)
        for m in range(4):
            ph = (m / 4 + k / 16) * math.pi
            for y in range(5, 28):
                w = math.sqrt(max(0, 11.5 ** 2 - (y + 0.5 - 16) ** 2))
                x = 16 + w * math.cos(ph)
                g.set(int(x), y, T if m == 0 else L)
        out.append(g)
    return out


def shipping():
    out = []
    for k in range(4):
        g = Grid(32, 32)
        g.rect(5, 12, 22, 16, P); g.rect(5, 12, 22, 1, L); g.rect(15, 12, 2, 16, U)
        g.rect(4, 9, 24, 4, L); g.rect(15, 9, 2, 4, M)
        sy = 2 if k == 0 else 5
        if k < 2:
            g.rect(12, sy, 8, 2, M); g.rect(15, sy - 2, 2, 2, M)    # the stamp coming down
        if k == 2:
            for (x, y) in ((9, 20), (10, 21), (11, 22), (12, 21), (13, 20), (14, 19), (15, 18), (16, 17)):
                g.rect(x, y, 2, 2, T)
        if k == 3:
            for d in range(7):
                g.rect(10 + d, 16 + d, 2, 2, F); g.rect(16 - d, 16 + d, 2, 2, F)
        out.append(g)
    return out


def gear(g, cx, cy, r, teeth, rot, c, hub):
    g.disc(cx, cy, r, c)
    for i in range(teeth):
        a = rot + i / teeth * 2 * math.pi
        for d in (r + 0.5, r + 1.5):
            g.set(int(cx + d * math.cos(a)), int(cy + d * math.sin(a)), c)
            g.set(int(cx + d * math.cos(a + 0.12)), int(cy + d * math.sin(a + 0.12)), c)
    g.disc(cx, cy, r * 0.4, hub)


def friction():
    out = []
    for k in range(4):
        g = Grid(32, 32)
        gear(g, 11, 12, 7, 8, k * math.pi / 16, L, K)
        gear(g, 22, 22, 5, 6, -k * math.pi / 12 + 0.3, T, K)
        if k % 2:
            g.set(17, 17, W); g.set(16, 18, PL)                      # a spark where they meet
        out.append(g)
    return out


def heart():
    rows = ['..####...####..', '.######.######.', '###############', '###############', '###############',
            '.#############.', '..###########..', '...#########...', '....#######....', '.....#####.....', '......###......',
            '.......#.......']
    out = []
    for k in range(4):
        g = Grid(32, 32)
        big = k in (0, 2)
        if big:
            for j, row in enumerate(rows):
                for i, ch in enumerate(row):
                    if ch == '#':
                        g.rect(1 + i * 2, 4 + j * 2, 2, 2, F)
            g.rect(7, 8, 2, 4, '#ffe0ee')
        else:
            g.art(8, 9, rows, {'#': F})
            g.set(10, 10, '#ffe0ee'); g.set(10, 11, '#ffe0ee')
        g.rect(4, 29, 24, 1, M)
        for i in range(24):                                          # the pulse line
            y = 29 - (3 if (i + k * 6) % 24 in (10, 11) else 0) + (2 if (i + k * 6) % 24 == 12 else 0)
            g.set(4 + i, y, T)
        out.append(g)
    return out


def die():
    pips = {1: [(1, 1)], 2: [(0, 0), (2, 2)], 3: [(0, 0), (1, 1), (2, 2)], 4: [(0, 0), (2, 0), (0, 2), (2, 2)],
            5: [(0, 0), (2, 0), (1, 1), (0, 2), (2, 2)], 6: [(0, 0), (2, 0), (0, 1), (2, 1), (0, 2), (2, 2)]}
    out = []
    for k, (face, dy) in enumerate(((5, 0), (2, -3), (6, -1), (3, 0))):
        g = Grid(32, 32)
        y0 = 7 + dy
        g.rect(6, y0, 20, 20, L); g.rect(7, y0 + 1, 18, 18, W); g.rect(6, y0 + 19, 20, 1, M); g.rect(25, y0, 1, 20, M)
        for (i, j) in pips[face]:
            g.rect(9 + i * 6, y0 + 3 + j * 6, 3, 3, U)
        w = 20 - abs(dy) * 2
        g.rect(16 - w // 2, 29, w, 1, D)                             # shadow
        out.append(g)
    return out


PHIL = {'predict and describe': scale, 'count and rate': hourglass, 'projection': projection, 'one framework': globe,
        'shipping': shipping, 'friction': friction, 'human': heart, 'skin in the game': die}


def slug(t):
    return t.replace(' ', '-')


def main():
    with open(os.path.join(PX, 'hero-process.html'), 'w') as f:
        f.write(animated('hero-process', hero(), 8))
    for tab, fn in PHIL.items():
        with open(os.path.join(PX, f'phil-{slug(tab)}.html'), 'w') as f:
            f.write(animated(f'phil-{slug(tab)}', fn(), 4).replace('class="px px--phil-', 'class="px px--phil px--phil-'))
    print(f'process art: hero + {len(PHIL)} philosophy sprites')


if __name__ == '__main__':
    main()
