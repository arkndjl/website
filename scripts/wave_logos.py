#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""WAVE's pixel logos (ST. CLAIRE /stclaire/wave/): one 48 x 48 tile per brand, band, team and suggested brand, all
in the site palette (lilac, aquamarine, purple), hand-lettered on the grid. Writes layouts/partials/px/wave.html
(written as static/img/px/wave-logos.svg, one cached file); use a logo with
<svg><use href="/img/px/wave-logos.svg#px-wv-<id>"/></svg>.

    python3 scripts/wave_logos.py             # writes the sprite sheet
    python3 scripts/wave_logos.py --preview D # also writes a contact sheet D/wave-logos.png (needs ImageMagick)

Ids are scripts/wave.py slugs (slug(name)): a band added to ARKLIBRARY without a bespoke mark here gets the
lettered tile from `word()` on the next run, so every tracked name always has a logo.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pixelart as pa  # noqa: E402
import wave  # noqa: E402

ROOT = pa.ROOT
OUT = os.path.join(ROOT, 'static', 'img', 'px', 'wave-logos.svg')     # <svg><use href="/img/px/wave-logos.svg#px-wv-<id>"/></svg>
PORTAL = os.path.join(ROOT, 'static', 'img', 'px', 'wave-portal.svg')  # the ST. CLAIRE hub portal art
L, A, P, M, D, K, W = '#c8c7ff', '#7fffd4', '#57068c', '#4a3b6b', '#241a3a', '#0e0b16', '#f4f2ff'
S = 48

# 5 x 7 capitals
F5 = {k: v.split() for k, v in {
    'A': '.###. #...# #...# ##### #...# #...# #...#', 'B': '####. #...# #...# ####. #...# #...# ####.',
    'C': '.#### #.... #.... #.... #.... #.... .####', 'D': '####. #...# #...# #...# #...# #...# ####.',
    'E': '##### #.... #.... ####. #.... #.... #####', 'F': '##### #.... #.... ####. #.... #.... #....',
    'G': '.#### #.... #.... #.### #...# #...# .####', 'H': '#...# #...# #...# ##### #...# #...# #...#',
    'I': '### .#. .#. .#. .#. .#. ###', 'J': '..### ...#. ...#. ...#. ...#. #..#. .##..',
    'K': '#...# #..#. #.#.. ##... #.#.. #..#. #...#', 'L': '#.... #.... #.... #.... #.... #.... #####',
    'M': '#...# ##.## #.#.# #.#.# #...# #...# #...#', 'N': '#...# ##..# #.#.# #..## #...# #...# #...#',
    'O': '.###. #...# #...# #...# #...# #...# .###.', 'P': '####. #...# #...# ####. #.... #.... #....',
    'Q': '.###. #...# #...# #...# #.#.# #..#. .##.#', 'R': '####. #...# #...# ####. #.#.. #..#. #...#',
    'S': '.#### #.... #.... .###. ....# ....# ####.', 'T': '##### ..#.. ..#.. ..#.. ..#.. ..#.. ..#..',
    'U': '#...# #...# #...# #...# #...# #...# .###.', 'V': '#...# #...# #...# #...# #...# .#.#. ..#..',
    'W': '#...# #...# #...# #.#.# #.#.# ##.## #...#', 'X': '#...# #...# .#.#. ..#.. .#.#. #...# #...#',
    'Y': '#...# #...# .#.#. ..#.. ..#.. ..#.. ..#..', 'Z': '##### ....# ...#. ..#.. .#... #.... #####',
    '0': '.###. #...# #..## #.#.# ##..# #...# .###.', '1': '..#.. .##.. ..#.. ..#.. ..#.. ..#.. .###.',
    '4': '...#. ..##. .#.#. #..#. ##### ...#. ...#.', '7': '##### ....# ...#. ..#.. .#... .#... .#...',
    '9': '.###. #...# #...# .#### ....# ....# .###.', "'": '# # .', '(': '.# #. #. #. #. #. .#', ')': '#. .# .# .# .# .# #.',
    '-': '... ... ... ### ... ... ...', '.': '. . . . . . #', '_': '..... ..... ..... ..... ..... ..... #####',
    'É': '##### #.... ####. #.... #.... #.... #####',
}.items()}
# 3 x 5 capitals
F3 = {k: v.split() for k, v in {
    'A': '.#. #.# ### #.# #.#', 'B': '##. #.# ##. #.# ##.', 'C': '.## #.. #.. #.. .##', 'D': '##. #.# #.# #.# ##.',
    'E': '### #.. ##. #.. ###', 'F': '### #.. ##. #.. #..', 'G': '.## #.. #.# #.# .##', 'H': '#.# #.# ### #.# #.#',
    'I': '### .#. .#. .#. ###', 'J': '..# ..# ..# #.# .#.', 'K': '#.# #.# ##. #.# #.#', 'L': '#.. #.. #.. #.. ###',
    'M': '#...# ##.## #.#.# #...# #...#', 'N': '#..# ##.# #.## #..# #..#', 'O': '.#. #.# #.# #.# .#.', 'P': '##. #.# ##. #.. #..',
    'Q': '.#. #.# #.# ##. .##', 'R': '##. #.# ##. #.# #.#', 'S': '.## #.. .#. ..# ##.', 'T': '### .#. .#. .#. .#.',
    'U': '#.# #.# #.# #.# ###', 'V': '#.# #.# #.# #.# .#.', 'W': '#...# #...# #.#.# ##.## #...#', 'X': '#.# #.# .#. #.# #.#',
    'Y': '#.# #.# .#. .#. .#.', 'Z': '### ..# .#. #.. ###', '0': '### #.# #.# #.# ###', '1': '.#. ##. .#. .#. ###',
    '7': '### ..# .#. .#. .#.', '9': '### #.# ### ..# ###', "'": '# # . . .', '(': '.# #. #. #. .#', ')': '#. .# .# .# #.',
    '-': '... ... ### ... ...', '_': '... ... ... ... ###', '.': '. . . . #', 'É': '### #.. ##. #.. ###',
}.items()}
# lowercase, 4 wide, x-height 5, 2 px ascenders / descenders (rows 0-8; baseline row 6)
FL = {k: v.split() for k, v in {
    'a': '.... .... .##. ...# .### #..# .###', 'b': '#... #... ###. #..# #..# #..# ###.', 'c': '.... .... .### #... #... #... .###',
    'e': '.... .... .##. #..# #### #... .###', 'h': '#... #... ###. #..# #..# #..# #..#', 'i': '. # . # # # #',
    'k': '#... #... #..# #.#. ##.. #.#. #..#', 'l': '# # # # # # #', 'm': '..... ..... ####. #.#.# #.#.# #.#.# #.#.#',
    'n': '.... .... ###. #..# #..# #..# #..#', 'o': '.... .... .##. #..# #..# #..# .##.', 'p': '.... .... ###. #..# #..# ###. #...',
    'r': '... ... #.# ##. #.. #.. #..', 's': '.... .... .### #... .##. ...# ###.', 't': '.#. .#. ### .#. .#. .#. ..#',
    'v': '..... ..... #...# #...# .#.#. .#.#. ..#..', 'w': '..... ..... #...# #...# #.#.# #.#.# .#.#.', 'x': '.... .... #..# .##. .##. .##. #..#',
    'y': '.... .... #..# #..# .### ...# ###.', 'g': '.... .... .### #..# .### ...# ###.', 'u': '.... .... #..# #..# #..# #..# .###',
    'd': '...# ...# .### #..# #..# #..# .###', 'f': '.## #.. ### #.. #.. #.. #..', 'j': '.# .. .# .# .# .# #.', ' ': '. . . . . . .',
}.items()}


def tw(s, font):
    return sum(len(font[c][0]) + 1 for c in s) - 1


def put(g, x, y, s, c, font=F5, k=1, track=1):
    """Text at (x, y); k = pixel scale (2 makes each font pixel a 2 x 2 block)."""
    for ch in s:
        if ch == ' ':
            x += 3 * k
            continue
        glyph = font[ch]
        for j, row in enumerate(glyph):
            for i, b in enumerate(row):
                if b == '#':
                    g.rect(x + i * k, y + j * k, k, k, c)
        x += (len(glyph[0]) + track) * k
    return x


def width(s, font=F5, k=1, track=1):
    return sum((3 if ch == ' ' else len(font[ch][0]) + track) * k for ch in s) - track * k


def cput(g, y, s, c, font=F5, k=1, track=1, cx=24):
    return put(g, round(cx - width(s, font, k, track) / 2), y, s, c, font, k, track)


def shadow(g, c, dx=1, dy=1, of=None):
    """Drop a copy of the filled pixels (or only colours in `of`) dx, dy behind them in c."""
    pts = [(i, j) for j in range(S) for i in range(S) if g.get(i, j) is not None and (of is None or g.get(i, j) in of)]
    for i, j in pts:
        if g.get(i + dx, j + dy) is None:
            g.set(i + dx, j + dy, c)


def recolor(g, m):
    for row in g.px:
        for i, v in enumerate(row):
            if v is not None:
                row[i] = m.get(v, v)
    return g


def line(g, x0, y0, x1, y1, c):
    n = max(abs(x1 - x0), abs(y1 - y0), 1)
    for t in range(n + 1):
        g.set(round(x0 + (x1 - x0) * t / n), round(y0 + (y1 - y0) * t / n), c)


def word(name, col=L, sh=P):
    """A lettered tile for any name: up to three lines, the biggest font that fits 44 px."""
    g = pa.Grid(S, S)
    txt = re.sub(r'[^A-Z0-9\'()\-_. É]', '', name.upper().replace('&', 'AND'))
    words = txt.split()
    for font, k, tr in ((F5, 2, 1), (F5, 1, 1), (F3, 1, 1), (F3, 1, 0)):
        h = len(font['A']) * k
        lines, cur = [], ''
        for w_ in words:
            trial = (cur + ' ' + w_).strip()
            if width(trial, font, k, tr) <= 44:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = w_
        lines.append(cur)
        if all(width(l_, font, k, tr) <= 44 for l_ in lines) and len(lines) * (h + 3) <= 40:
            break
    y = round(24 - (len(lines) * (h + 3) - 3) / 2)
    for l_ in lines:
        cput(g, y, l_, col, font, k, tr)
        y += h + 3
    shadow(g, sh)
    return g


def logos():
    base = pa.logos()
    X = {}
    # --- the four brands
    X['ysl'] = recolor(base['ysl'], {'#c9a24d': L})
    shadow(X['ysl'], P)
    g = recolor(base['newbalance'], {'#cf0a2c': L})
    shadow(g, A, of={L})
    X['newbalance'] = g
    g = pa.Grid(S, S)                                     # '47: the apostrophe and a heavy 4 7, aqua cut
    put(g, 5, 8, "'", L, F5, 3)
    put(g, 10, 6, '47', L, F5, 3, track=1)
    for j in range(6, 28):
        if j % 4 == 2:
            for i in range(S):
                if g.get(i, j) == L:
                    g.set(i, j, A)
    cput(g, 33, 'BRAND', A, F3, 2, track=1)
    shadow(g, P)
    X['47'] = g
    g = pa.Grid(S, S)                                     # STUDIO SEVEN: a torn 7 over the stacked wordmark
    put(g, 14, 2, '7', L, F5, 4)
    line(g, 12, 20, 36, 12, A); line(g, 12, 21, 36, 13, A)
    cput(g, 33, 'STUDIO', L, F3, 1, track=2)
    cput(g, 40, 'SEVEN', A, F3, 1, track=3)
    shadow(g, P)
    X['studioseven'] = g
    # --- the two teams
    X['mets'] = recolor(base['mets'], {'#ff5910': A})
    shadow(X['mets'], P)
    X['knicks'] = recolor(base['knicks'], {'#ffffff': L, '#006bb6': P, '#00438a': K, '#f58426': A, '#bec0c2': D, '#1d1d1b': D})

    # --- the bands
    g = pa.Grid(S, S)                                     # the strokes: small "the", wide STROKES, underline
    put(g, 6, 12, 'the', A, FL)
    cput(g, 21, 'STROKES', L, F5, 1, track=1)
    g.rect(4, 31, 40, 1, L); g.rect(4, 33, 26, 1, A)
    shadow(g, P)
    X['thestrokes'] = g
    g = pa.Grid(S, S)                                     # ethel cain: a tall Latin cross over the name
    g.rect(22, 3, 4, 28, L); g.rect(14, 10, 20, 4, L)
    g.rect(23, 4, 1, 26, W)
    cput(g, 35, 'ETHEL', L, F3, 1, track=2); cput(g, 41, 'CAIN', A, F3, 1, track=3)
    shadow(g, P)
    X['ethelcain'] = g
    g = pa.Grid(S, S)                                     # automatic: a power ring
    g.disc(24, 17, 12, L); g.disc(24, 17, 9, None); g.rect(21, 3, 6, 12, None); g.rect(23, 4, 2, 13, A)
    cput(g, 35, 'AUTOMATIC', L, F3, 1)
    shadow(g, P)
    X['automatic'] = g
    g = pa.Grid(S, S)                                     # chokecherry: a cherry pair on one stem
    g.disc(16, 22, 6, L); g.disc(31, 24, 6, L); g.set(14, 19, W); g.set(29, 21, W); g.set(15, 19, W); g.set(30, 21, W)
    line(g, 17, 16, 25, 5, A); line(g, 30, 18, 25, 5, A); g.rect(25, 4, 6, 2, A)
    put(g, 3, 32, 'choke', L, FL); put(g, 20, 39, 'cherry', A, FL, track=0)
    shadow(g, P)
    X['chokecherry'] = g
    g = pa.Grid(S, S)                                     # geese: two birds in a V over the name
    for ox, oy in ((10, 8), (26, 14)):
        for d in (0, 1):
            line(g, ox, oy + d, ox + 6, oy + 4 + d, L); line(g, ox + 6, oy + 4 + d, ox + 12, oy + d, L)
        g.set(ox + 6, oy + 6, A)
    cput(g, 28, 'GEESE', L, F5, 1, track=2)
    shadow(g, P)
    X['geese'] = g
    g = pa.Grid(S, S)                                     # ninajirachi: a CRT with a heart on it
    g.rect(10, 4, 28, 20, L); g.rect(12, 6, 24, 16, D); g.rect(20, 24, 8, 3, L); g.rect(16, 27, 16, 2, L)
    for j, row in enumerate(['.##.##.', '#######', '#######', '.#####.', '..###..', '...#...']):
        for i, ch in enumerate(row):
            if ch == '#':
                g.set(20 + i, 10 + j, A)
    cput(g, 33, 'NINA', L, F3, 1, track=2); cput(g, 40, 'JIRACHI', A, F3, 1)
    X['ninajirachi'] = g
    g = pa.Grid(S, S)                                     # hardrock: a faceted stone
    g.poly([(12, 14), (20, 6), (32, 7), (38, 16), (33, 27), (16, 27)], L)
    line(g, 20, 6, 24, 16, M); line(g, 32, 7, 24, 16, M); line(g, 12, 14, 24, 16, M); line(g, 24, 16, 33, 27, M); line(g, 24, 16, 16, 27, M)
    g.set(26, 10, W); g.set(27, 10, W)
    cput(g, 34, 'HARDROCK', A, F3, 1)
    shadow(g, P)
    X['hardrock'] = g
    g = pa.Grid(S, S)                                     # pinkpantheress: a five-petal flower
    for cx, cy in ((24, 8), (31, 13), (28, 21), (20, 21), (17, 13)):
        g.disc(cx, cy, 4.2, L)
    g.disc(24, 15, 3.2, A)
    put(g, 15, 28, 'pink', A, FL); cput(g, 37, 'pantheress', L, FL, track=0)
    shadow(g, P)
    X['pinkpantheress'] = g
    g = pa.Grid(S, S)                                     # fka twigs: FKA big, a twig underneath
    cput(g, 6, 'FKA', L, F5, 2, track=1)
    line(g, 6, 30, 40, 26, A); line(g, 18, 29, 22, 23, A); line(g, 30, 27, 34, 22, A)
    cput(g, 34, 'twigs', L, FL, track=1)
    shadow(g, P)
    X['fkatwigs'] = g
    g = pa.Grid(S, S)                                     # sextile: the six-ray sextile glyph
    for (dx, dy) in ((0, -1), (0, 1), (.87, .5), (-.87, -.5), (.87, -.5), (-.87, .5)):
        line(g, 24, 16, round(24 + dx * 12), round(16 + dy * 12), L)
        line(g, 25, 16, round(25 + dx * 12), round(16 + dy * 12), L)
    g.disc(24.5, 16.5, 2.5, A)
    cput(g, 34, 'SEXTILE', L, F5, 1, track=1)
    shadow(g, P)
    X['sextile'] = g
    g = pa.Grid(S, S)                                     # charli xcx: XCX in a slab box
    g.rect(4, 10, 40, 26, L); g.rect(6, 12, 36, 22, D)
    cput(g, 16, 'XCX', A, F5, 2, track=1)
    put(g, 6, 38, 'charli', L, FL)
    X['charlixcx'] = g
    g = pa.Grid(S, S)                                     # playboi carti: a star over CARTI, sharp serifs
    for j, row in enumerate(['....#....', '....#....', '...###...', '#########', '..#####..', '..##.##..', '.##...##.', '.#.....#.']):
        for i, ch in enumerate(row):
            if ch == '#':
                g.set(19 + i, 5 + j, A)
    cput(g, 18, 'CARTI', L, F5, 1, track=2)
    for x in range(8, 41, 4):
        g.set(x, 27, L)
    cput(g, 31, 'PLAYBOI', A, F3, 1)
    shadow(g, P)
    X['playboicarti'] = g
    g = pa.Grid(S, S)                                     # the voidz: a void ring, the name torn across it
    g.disc(24, 13, 10, L); g.disc(24, 13, 7, D); g.disc(24, 13, 3, None)
    cput(g, 29, 'VOIDZ', A, F5, 1, track=2)
    for j in (31, 32):                                    # glitch: two rows of the name slip right
        g.px[j] = [None, None] + g.px[j][:-2]
    cput(g, 40, 'THE', L, F3, 1, track=2)
    shadow(g, P, of={A, L})
    X['thevoidz'] = g
    g = pa.Grid(S, S)                                     # julian casablancas: a JC monogram
    put(g, 8, 6, 'J', L, F5, 3)
    put(g, 25, 6, 'C', A, F5, 3)
    g.rect(6, 30, 36, 1, L)
    cput(g, 35, 'CASABLANCAS', L, F3, 1, track=1)
    shadow(g, P)
    X['juliancasablancas'] = g
    g = pa.Grid(S, S)                                     # my bloody valentine: big lowercase mbv, tilted
    cput(g, 6, 'mbv', L, FL, 3, track=1)
    for j in range(6, 27, 3):                             # a smear of scan lines through the letters
        for i in range(S):
            if g.get(i, j) == L:
                g.set(i, j, A)
    cput(g, 36, 'VALENTINE', A, F3, 1, track=1)
    shadow(g, P)
    X['mybloodyvalentine'] = g
    g = pa.Grid(S, S)                                     # lauryn hill: a ribbon mic over the name
    g.ellipse(24, 9, 6, 6, L); g.rect(19, 9, 10, 1, D); g.rect(19, 6, 10, 1, D); g.rect(19, 12, 10, 1, D)
    g.rect(22, 15, 4, 10, L); g.rect(18, 25, 12, 2, A)
    cput(g, 31, 'LAURYN', L, F3, 1, track=2); cput(g, 38, 'HILL', A, F3, 1, track=3)
    shadow(g, P)
    X['laurynhill'] = g
    g = pa.Grid(S, S)                                     # fleetwood mac: a moon over two lines
    g.disc(24, 11, 8, L); g.disc(28, 9, 7, None); g.set(20, 8, W)
    cput(g, 24, 'FLEETWOOD', L, F3, 1, track=1)
    cput(g, 32, 'MAC', A, F5, 1, track=2)
    shadow(g, P)
    X['fleetwoodmac'] = g
    g = pa.Grid(S, S)                                     # nas: Queensbridge arches under NAS
    cput(g, 5, 'NAS', L, F5, 2, track=2)
    for x0 in (4, 18, 32):
        for i in range(13):
            y = 34 - round(6 * (1 - ((i - 6) / 6) ** 2))
            g.set(x0 + i, y, A)
        g.rect(x0, 34, 1, 8, A); g.rect(x0 + 12, 34, 1, 8, A)
    g.rect(2, 34, 44, 1, L)
    shadow(g, P)
    X['nas'] = g
    g = pa.Grid(S, S)                                     # the fashion: spaced caps on a runway line
    cput(g, 12, 'THE', A, F3, 1, track=3)
    cput(g, 20, 'FASHION', L, F5, 1, track=1)
    g.rect(6, 31, 36, 1, L)
    for x in range(8, 41, 6):
        g.rect(x, 33, 2, 1, A)
    shadow(g, P)
    X['thefashion'] = g
    for aid, (first, last) in (('pattinson', ('ROBERT', 'PATTINSON')), ('chalamet', ('TIMOTHEE', 'CHALAMET'))):
        g = pa.Grid(S, S)                                 # a film strip with a clapper, the actor's name under it
        g.rect(6, 4, 36, 18, L); g.rect(6, 7, 36, 12, D)
        for x in range(8, 41, 5):
            g.rect(x, 5, 2, 1, D); g.rect(x, 20, 2, 1, D)
        g.poly([(14, 17), (14, 10), (30, 8), (30, 15)], A)  # the slate
        for x in (17, 22, 27):
            line(g, x, 10, x + 2, 15, D)
        g.rect(31, 9, 6, 7, M); g.disc(34, 12.5, 2, L)       # the lens
        cput(g, 27, first, A, F3, 1, track=1)
        cput(g, 35, last, L, F3, 1, track=1)
        shadow(g, P, of={A, L})
        X[aid] = g
    return X


def all_logos():
    X = logos()
    ids = [b['id'] for b in wave.BRANDS] + [t['id'] for t in wave.TEAMS] + [a['id'] for a in wave.ACTORS]
    bands = [b['name'] for b in wave.library_bands()]
    for i, name in enumerate(bands):
        sid = wave.slug(name)
        if sid not in X:
            X[sid] = word(name, L if i % 2 else A)
    for i, s in enumerate(wave.SUGGEST):
        sid = wave.slug(s['name'])
        if sid not in X:
            X[sid] = word(s['name'], (L, A)[i % 2], P)
    for b in wave.BRANDS:
        if b['id'] not in X:
            X[b['id']] = word(b['name'].title(), A, P)
    missing = [i for i in ids + [wave.slug(b) for b in bands] if i not in X]
    assert not missing, missing
    return X


def portal():
    """The hub portal art: a 96 x 40 pixel wave, three bands of lilac, aqua and purple."""
    import math
    g = pa.Grid(96, 40)
    for x in range(96):
        for band, (amp, ph, col, y0) in enumerate(((7, 0, P, 26), (6, 1.3, A, 20), (5, 2.4, L, 14))):
            y = round(y0 + amp * math.sin(x / 9 + ph))
            for j in range(y, y + 3):
                g.set(x, j, col)
    return g


def paths(g):
    """One <path> per colour, one 'M x y h w v1 h-w z' per horizontal run: a third of the size of <rect>s."""
    by = {}
    for y, row in enumerate(g.px):
        x = 0
        while x < g.w:
            c = row[x]
            if c is None:
                x += 1
                continue
            x0 = x
            while x < g.w and row[x] == c:
                x += 1
            by.setdefault(c, []).append(f'M{x0} {y}h{x - x0}v1h-{x - x0}z')
    return ''.join(f'<path fill="{c}" d="{"".join(d)}"/>' for c, d in by.items())


def main():
    X = all_logos()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg"><!-- Generated by scripts/wave_logos.py: edit that script, not this file. -->')
        f.write(''.join(f'<symbol id="px-wv-{k}" viewBox="0 0 {v.w} {v.h}" shape-rendering="crispEdges">{paths(v)}</symbol>' for k, v in X.items()))
        f.write('</svg>\n')
    g = portal()
    with open(PORTAL, 'w') as f:
        f.write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {g.w} {g.h}" width="{g.w * 4}" height="{g.h * 4}" shape-rendering="crispEdges">{paths(g)}</svg>\n')
    print(f'wrote {len(X)} WAVE logos to {os.path.relpath(OUT, ROOT)}')
    if '--preview' in sys.argv:
        d = sys.argv[sys.argv.index('--preview') + 1]
        os.makedirs(d, exist_ok=True)
        files = []
        for k, v in X.items():
            pa.preview(k, v, d, scale=4)
            files.append(os.path.join(d, k + '.png'))
        subprocess.run(['montage', *files, '-tile', '8x', '-geometry', '+6+6', '-background', '#120d1c', '-label', '%t',
                        os.path.join(d, 'wave-logos.png')], check=True)


if __name__ == '__main__':
    main()
