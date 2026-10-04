#!/usr/bin/env python3
"""Draw ARKLIBRARY's generated pixel art and write it as an SVG sprite sheet.

    python3 scripts/pixelart.py             # writes layouts/partials/px/sprites.html
    python3 scripts/pixelart.py --preview D # also writes enlarged PNG previews into D (needs ImageMagick)

Every sprite is drawn on a small grid with the helpers below and emitted as an SVG <symbol>
(one <rect> per horizontal run of a colour). Single-colour icons use the colour "c", which
renders as currentColor so they follow the theme like layouts/partials/icons.html; everything
else carries its own fill. Use a sprite with  <svg><use href="#px-mets"/></svg>.

  icon-anime, icon-manga, icon-book, icon-trophy   list-row type icons and the sports window icon
  px-<team>                                       team logos (24 x 24)
  px-tr-<type>                                    trophies (16 x 20), one per title type
  icon-crosshair                                  the LAURSEN_111 icon (also static/img/icons/laursen.svg)
  px-ak47, px-awp                                 Counter-Strike weapons
and animated sprites written as their own partials (frames in the px__f format, see style.css):
  layouts/partials/px/c4.html                     the C4, LED blinking and the timer counting down
"""
import math, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "layouts", "partials", "px", "sprites.html")


class Grid:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.px = [[None] * w for _ in range(h)]

    def set(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y][x] = c

    def get(self, x, y):
        return self.px[y][x] if 0 <= x < self.w and 0 <= y < self.h else None

    def rect(self, x, y, w, h, c):
        for j in range(y, y + h):
            for i in range(x, x + w):
                self.set(i, j, c)

    def disc(self, cx, cy, r, c):
        for j in range(self.h):
            for i in range(self.w):
                if (i + 0.5 - cx) ** 2 + (j + 0.5 - cy) ** 2 <= r * r:
                    self.set(i, j, c)

    def ellipse(self, cx, cy, rx, ry, c):
        for j in range(self.h):
            for i in range(self.w):
                if ((i + 0.5 - cx) / rx) ** 2 + ((j + 0.5 - cy) / ry) ** 2 <= 1:
                    self.set(i, j, c)

    def poly(self, pts, c):
        for j in range(self.h):
            for i in range(self.w):
                if inside(i + 0.5, j + 0.5, pts):
                    self.set(i, j, c)

    def art(self, x, y, rows, pal):
        """Stamp ASCII art: each char maps through pal; '.' and ' ' are transparent."""
        for j, row in enumerate(rows):
            for i, ch in enumerate(row):
                if ch not in ". ":
                    self.set(x + i, y + j, pal.get(ch, ch))

    def text(self, x, y, s, c, font=None):
        font = font or FONT3
        for ch in s:
            glyph = font[ch]
            for j, row in enumerate(glyph):
                for i, b in enumerate(row):
                    if b == "#":
                        self.set(x + i, y + j, c)
            x += len(glyph[0]) + 1

    def outline(self, c, inside_of=None):
        """Draw c on every empty pixel that touches a filled one (4-neighbour)."""
        add = []
        for j in range(self.h):
            for i in range(self.w):
                if self.px[j][i] is None and any(
                        self.get(i + dx, j + dy) not in (None,) and (inside_of is None or self.get(i + dx, j + dy) in inside_of)
                        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    add.append((i, j))
        for i, j in add:
            self.set(i, j, c)

    def replace(self, a, b):
        for row in self.px:
            for i, v in enumerate(row):
                if v == a:
                    row[i] = b

    def mirror(self):
        """Copy the left half onto the right half (for symmetric trophies)."""
        for row in self.px:
            for i in range(self.w // 2):
                row[self.w - 1 - i] = row[i]


def inside(x, y, pts):
    n, hit = len(pts), False
    for k in range(n):
        x1, y1 = pts[k]
        x2, y2 = pts[(k + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


METS_NY = [
    "..........ooo...ooo..........oooo..ooo..........",
    ".........ooooooooooo........ooooooooooo.........",
    "........oooooooooooo........oooooooooooo........",
    "........oooooooooooo........oooooooooooo........",
    "............ooooo..............ooooo............",
    "............ooooo...............oooo............",
    "............oooooo..............oooo............",
    "............ooooooo.............oooo............",
    "............ooooooo.............oooo............",
    "............oooooooo............oooo............",
    "............ooooooooo...........oooo............",
    "............oooooooooo..........oooo............",
    "............oooo..ooooo.........oooo............",
    "............oooo...oooo.........oooo............",
    "..........ooooooo..ooooo........oooooo..........",
    ".........ooooooooo..ooooo.....ooooooooo.........",
    ".........oooooooooo..ooooo...ooooooooooo........",
    "........oooooooooooo..ooooo.oooooooooooo........",
    "........ooo.ooooooooo..ooooooooooooo.ooo........",
    "........ooo.oooo..oooo.oooooooo.oooo..oo........",
    "........ooo.oooo...oooo.oooooo..oooo..oo........",
    ".........oo.oooo...oooo..ooooo..oooo..o.........",
    "............oooo....oooo.oooooo.oooo............",
    "............oooo.....ooooooooooooooo............",
    "............oooo.....ooooooooooooooo............",
    "............oooo......ooooo.oooooooo............",
    "............oooo......ooooo..ooooooo............",
    "............oooo......oooo....oooooo............",
    "............oooo......oooo.....ooooo............",
    "............oooo......oooo......oooo............",
    "............ooooo.....oooo......oooo............",
    "........oooooooooooo..oooo..oooooooooooo........",
    "........oooooooooooo..oooo..oooooooooooo........",
    ".........ooooooooooo..oooo..ooooooooooo.........",
    "..........ooo...ooo...oooo...oooo..ooo..........",
    "......................oooo......................",
    "......................oooo......................",
    "......................oooo......................",
    "......................oooo......................",
    "......................oooo......................",
    "......................oooo......................",
    "......................oooo......................",
    "......................oooo......................",
    ".....................oooooo.....................",
    "..................oooooooooooo..................",
    "..................oooooooooooo..................",
    "...................ooooooooooo..................",
    "....................ooo...ooo...................",
]

BARCA_CREST = [
    "................k..............k................",
    "..............kkykk..........kkykk..............",
    "....kkkkkkkkkkyyyyykkk....kkkyyyyykkkkkkkkkk....",
    "...kyyyyyyyyyyyymyyyyykkkkyyyyyyyyyyyyyyyyyyk...",
    "..kkyyyyyyyyymmrrrmyyyyyyyyyymryymmyyyyyyyyykk..",
    "...kyymwwwwwwrrrrrwwwwwyyymyyrryyrryyrryyyyyk...",
    "....kyywwwwwwrrrrrwwwwwwyyryyrryyrryyrryyyyk....",
    "....kyywwwwwwrrrrrwwwwwwyyryyrryyrryyrryyyyk....",
    ".....kyywwwwwrrrrrwwwwwwyyryyrryyrryyrryyyk.....",
    ".....kyyrrrrrrrrrrrrrrrmyyryyrryyrryyrryyyk.....",
    ".....kyyrrrrrrrrrrrrrrrmyyryyrryyrryyrryyyk.....",
    ".....kyymrrrrrrrrrrrrrrmyyryyrryyrryyrryyyk.....",
    ".....kyymrrrrrrrrrrrrrrmyyryyrryyrryyrryyyk.....",
    ".....kyymrrrrrrrrrrrrrrmyyryyrryyrryyrryyyk.....",
    ".....kyywwwwwrrrrrrwwwwyyyryyrryyrryyrryyyk.....",
    ".....kyywwwwwrrrrrwwwwwwyyryyrryyrryyrryyyk.....",
    "....kkyywwwwwrrrrrwwwwwwyyryyrryyrryyrryyykk....",
    "....kyywwwwwwrrrrrwwwwwwyyryyrryyrryyrryyyyk....",
    "....kyywwwwwwmmmmmmwwwwwyymyyrmyyrryymryyyyk....",
    "...kyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyk...",
    "..kkyyyyyyyyyyyykkkmyykkkyyykkkmyyyyyyyyyyyykk..",
    "..kyyyyyyyyyyyyykyyyyykyyyyykykkyyyyyyyyyyyyyk..",
    ".kyyyyyyyyyyyyyykkyyymkyyyyykkkkyyyyyyyyyyyyyyk.",
    "kkyyyyyyyyyyyyyykyyyyykykyyykykkyyyyyyyyyyyyyykk",
    ".kkyyyyyyyyyyyyykyyyyyykmyyykkkyyyyyyyyyyyyyykk.",
    "..kmymkkkkmmmmmmkkkkkmmmmmmkkkkkmmmmmmkkkkmymk..",
    "..kyybbbbbmmmmmmbbbbbmmmmmmbbbbbmmmmmmbbbbbymk..",
    "..kyybbbbbmmmmmmbbbbbmmmmmmbbbbbmmmmmmbbbbbyyk..",
    "..kmybbbbbmmmmmmbbbbbkmmmmmbbbbbmmmmmmbbbbbymk..",
    "..kkybbbbbmmmmmmbbbbbyyyyyybbbbbmmmmmmbbbbbykk..",
    "...kykbbbbmmmmmmbbbbyyyyyyyybbbbmmmmmmbbbbkyk...",
    "...kymbbbbmmmmmmbbbyyyyyyyyymbbbmmmmmmbbbbyyk...",
    "..kkyybbbbmmmmmmbbbyyyyyyyyykbbbmmmmmmbbbbyyk...",
    "...kmykbbbmmmmmmbbbyyyyyyyyyybbbmmmmmmbbbkymk...",
    "....kyybbbmmmmmmbbbyymyyyymyybbbmmmmmmbbbyyk....",
    "....kmykbbmmmmmmbbbkyyyyyyyykbbbmmmmmmbbkymk....",
    ".....kyykbmmmmmmbbbbyyyyyyyybbbbmmmmmmbkyyk.....",
    "......kyykmmmmmmbbbbbkyyyymbbbbbmmmmmmkyyk......",
    "......kkyyymmmmmbbbbbmmmmmmbbbbbmmmmmyyykk......",
    "........kyyymmmmbbbbbmmmmmmbbbbbmmmmyyyk........",
    ".........kkyyyymbbbbbmmmmmmbbbbbmyyyykk.........",
    "..........kkkyyyyyyykmmmmmmkyyyyyyykkk..........",
    ".............kkkyyyyyyyyyyyyyyyykkk.............",
    "................kkkkkyyyyyykkkkk................",
    ".....................kmyymk.....................",
    "......................kkkk......................",
    ".......................kk.......................",
    "................................................",
]

DBU_SEAL = [
    "...................rrwwwwwwrr...................",
    "................wwwrrrrrrrrrrwww................",
    ".............rwwrrrrrrwrwrrrrrrrwwr.............",
    "...........rwwrrrrrrwrrrwrwrrwrrrrww............",
    "..........wwrrrwwwrrwrrrrrrwwrrrwrrrwr..........",
    ".........wrrrrrrrwrrwrrrrrrrrwrwrrwrrrw.........",
    "........wrrrrwrrrrrrwrrrrrwwwrrwrrwrrrrw........",
    ".......wrrwrrrwrrwrrrrrrrrrrrrrrrrrrwrrrw.......",
    "......wrrrrwwrrrrrrrrrrrrrrrrrrrrrrwwrrrrw......",
    ".....wrrwwwrwrrrrrrrrrrwwrrrrrrrrrrwrrwwrrw.....",
    "....wrrrrwwrwrrrrrrrwrrrrrrrrrrrrrrrrwrrrrrw....",
    "...rwrrrrrwwrrrrrrrrrrrrwrrrrrrrrrrrwrrrrrrwr...",
    "...wrrrrrrrrrrrrwrrrrrwwwrrrrrrwrrrrrwrrrrrrw...",
    "..rwrrrrrrrrrrrwrrrrrrrrrrrrrrrrrrrrrrrrwrrrwr..",
    "..wrwrrrrrrrrrrwrrrrrrrrrrrrrrrwwrrrrrrrrrrrrw..",
    "..wrrwwwwrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrw..",
    ".wrrrwrrrrrrrrrrrrrrrwwwwrrrrrrrrrrrrrrrrwrrrrw.",
    ".wrrwwrrrrrwwwwwrrrwwwwwwwrrrrwwrrwwwrrrwrrrrrw.",
    ".wrrrrwrrrrwwwwwwrrrwwwrrwwrrrwwrrwwwrrrrrrwwrw.",
    "rrrrrrrrrrrrwwwwwrrrwwwrrwwrrrwwrrwwrrrrrwwrrrrr",
    "wrrrwwrrrrrrwwrwwwrrwwwwrwwrrrwwrrwwrrrrrrrrrrrw",
    "wrwrwrwrrrrrwwrrwwrrwwwwwwwrrrwrrrwwrrrrrrwwwwrw",
    "wrwwrrrrrrrrwwrrrwwrwwwwwwrrrwwrrrwwrrrrrrrrwrrw",
    "wrrrrwrrrrrrwwrrrwwrwwrrwwwrrwwrrrwwrrrrrrrrwrrw",
    "wrrrrrrrrrrrwwrrrwwrwwrrrwwwwwwrrrwwrrrrrrrwrrrw",
    "wrrrrwrrrrrrwwrrrwwrwwrrrwwwrwwrrrwwrrrrrrrrrrrw",
    "wrrrwrrrrrrrwwrrwwwrwrwrrwwwrwwwrrwwrrrrrrrrrrrw",
    "wrrrrrrrrrrwwwwwwwwrwwwwwwwwrwwwwwwwwrrrrwwwwrrw",
    "rrrwrrwrrrrwwwwwwwrwwrwwwwwrrwwwwwwwwrrrrrrrrrrr",
    ".wrwwrrrrrrrrrrrrrrrrrrwwwrrrrrrrrrrrrrrrwwrrrw.",
    ".wrrrrrwrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrwrrwrrw.",
    ".wrrrrwrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrw.",
    "..wrrwwrrrrrrrwrrrrrrrrrrrrrrrrrrwrrrrrrrrrrrw..",
    "..wrrwrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrwwwrrw..",
    "..rwrrrrrrrrrrrrrrrrrrrwwrrrrrrrrrrrrrwrrrrrwr..",
    "...wrrrrrrrrrrrrrrrrrrrwwrrrrrrrrrrrrrrwrrrrw...",
    "...rwrrrwwrwrrrrrrrrrrwrrwrrrrrrrrrrrrrrwrrwr...",
    "....wrrrwrrrwrrrrrrrrrrrrrrrrrrrrrrrwwwwwrrw....",
    ".....wrrwrrwrrrrrrrrrrrrrrrrrrrrrrrrrwrrrrw.....",
    "......wrrwwrrrrrrrrrrrrrrrrrrrrrrrrrrrwrrw......",
    ".......wrrrrrrrrrrrrrrrrrrrrrrwwrrrrrrrrw.......",
    "........wrrrrrrrrwrrrrrrrrrrrwrrwrrrrrrw........",
    ".........wrrrrrrwrrrwrwrrwrwrrwwwrrrrrw.........",
    "..........rwrrrrwrrrwwwrrwwwrrrrwrrrwr..........",
    "...........rwwrrrrrwrrwrrwrwrrrwrrwwr...........",
    ".............rwwrrrrwwwrrwwwrrrrwwr.............",
    "................wwwrrrrrrrrrrwww................",
    "...................rrwwwwwwrr...................",
]

RAVENS_HEAD = [
    "................................................",
    "................................................",
    "................................................",
    "................................................",
    "................................................",
    "................................................",
    "................................................",
    "................................................",
    "................................................",
    "................................................",
    "................................................",
    "................................................",
    "...................wwwwww.......................",
    "...............wwwggggggggwww...................",
    "............wwgggkkkkkkkkkkkggw.................",
    "..........wwggkkkpppwwwwppppkkggww..............",
    ".........wggkkppwgggggggggpppppkggw.............",
    ".......wggkkpwwwppwwwwkwggppppppkggww...........",
    "......wggkppppppppwggpkwgwppppkkpkkgw...........",
    ".....wggkkkkkkpppwggwwwwpppkkkrrkpkkwwww........",
    "....wggkkkgggkkppgggwkggwpppkkrrrpkkkkggww......",
    "...wgggggggggkkpwggwpkgggpkkkkrrkkkkkkkkkgww....",
    "..wgggwww..wgkkpgggppwgpppppppwwwkkkkwwwkkggw...",
    "..www......wgkpwgggwgppppppwwwwwwwwwwwwwwwwkgw..",
    ".ww.......wgkkpwkkkpppppppppppwwkkkwwwwwwwwwkgw.",
    "..........ggkggggkkppkkppppppppwkwwwwkkkkwwwwkgw",
    ".........wgggwwggkkkkkkkkpppppppwwwwwwwwwwkkwwkw",
    "........wwww..wgggggggggkkppppkppkkkkwwwwwwwkkkw",
    "........w.....wggww....wkkkppkkpkgggggggkkkggggw",
    ".............www.......wgkkkkgkgwwwwwwwwwwww..w.",
    "......................wwggkgwwww................",
    "........................wgkw....................",
    "........................wggw....................",
    ".........................wg.....................",
    "..........................w.....................",
    "................................................",
    "................................................",
    "................................................",
    "................................................",
    "................................................",
    "................................................",
    "................................................",
    "................................................",
    "................................................",
    "................................................",
    "................................................",
    "................................................",
    "................................................",
]

RANGERS_SHIELD = [
    "................................................",
    "bwwwwwwwwwwwb..wwwwwwwwwwwwwwwwww..bwwwwwwwwwwwb",
    ".wwwwwwwwwwwwbwwwwwwwwwwwwwwwwwwwwbwwwwwwwwwwww.",
    ".bwbbbbbbbbbwwwbbbbbbbbbbbbbbbbbbwwwbbbbbbbbbwb.",
    "..wwbbbbbbbbbwbbbbbbbbbbbbbbbbbbbbwbbbbbbbbbww..",
    "...wbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbw...",
    "...wwbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbww...",
    "....wbbwbwbbwwbwwbwbwbbbwbwbwwwbwwwwbwbwbbbw....",
    "....wbbwbwbbwbbbwwwbwbbbwbwbwbwbwbbwbwwwbbbw....",
    "....wbbwwwbbwbbbwwwwwbbbbwwbwbwbwwwwbwwwbbbw....",
    "....wbbwwwbbwwbbwwwwbbbbbwbbwbwbwwwbbwbwbbbw....",
    "....wbbwbwbbwbbbwwwwbbbbbwbbwbwbwbwbbwbbwbbw....",
    "....wbbwbwbbwwbbwwbwbbbbbwbbwwwbwbbwbwbbwbbw....",
    "....wbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbw....",
    "....wbbwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwwbbw....",
    "....wbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbw....",
    "....wbbbbbbbbbbbbbbbbbrrrrrrrrrrrrrrrrrrrbbw....",
    "....wbbbbbbbbbwwbbbwbbrrrrrrrrrrrrrrrrrrrrbw....",
    "....wbbbbbbbbbwbwbbbwbbbrrrrrrrrrrrrrrrrrrbw....",
    "....wbbbbbbbbwwbwbbbbwwbbrrrrrrrrrrrrrrrrrbw....",
    "....wbwbbbbbwbwwwbbbbbbwbbrrrrrrrrrrrrrrrrbw....",
    "....wbbbwbbbwbwbbbwwwbbbwbbbrrrrrrrrrrrrrrbw....",
    "....wbbbbwbbbbwbbwwwbbbbbbwbbrrrrrrrrrrrrrbw....",
    "....wbwwbbwwbbbbwwbwbbwwbbbwbbrrrrrrrrrrrrbw....",
    "....wbwwwbbbwbbwbwwbbwwbbwbbwwbbrrrrrrrrrrbw....",
    "....wbwwwwwbbwbbbbwbwwwbwbbbbbwbbrrrrrrrrrbw....",
    "....wbwwwwwwbbbwbbwbwbwwbbwwwbbwbbbrrrrrrrbw....",
    "....wbwwwwwwwwbbwbbwbbwwbwwbwbbbbwbbrrrrrrbw....",
    "....wbwwwwwwwwwbbwwbbwwbbwbbwbbwbbwbbrrrrrbw....",
    "....wbwwwwwwwwwwbbbwbbbbwbwwbbwwwbbwbbbrrrbw....",
    "....wbwwwwwwwwwwwwbbwbbbwbwbbwwbbbbbbwbbrrbw....",
    "....wbwwwwwwwwwwwwwbbwwbbwwbbwwbbbwwbbwbbbbw....",
    "....wbwwwwwwwwwwwwwwbbbwbbbbwbbbbwbwwbbwwbbw....",
    "....wbwwwwwwwwwwwwwwwwbbwbbbwbbbwwbwwbbbbbbw....",
    "....wbwwwwwwwwwwwwwwwwwbbbwbbbbwwwwwbwwwbbbw....",
    "....wbwwwwwwwwwwwwwwwwwwwbbwbbbwbwbbbwbwbbbw....",
    "....wbwwwwwwwwwwwwwwwwwwwwbbwwbbbwbbbwbwbbbw....",
    "....wbwwwwwwwwwwwwwwwwwwwwwbbbwbbbbwbwbbbbbw....",
    "....wbwwwwwwwwwwwwwwwwwwwwwwwbbwbbbwwwbbbbbw....",
    "....wbwwwwwwwwwwwwwwwwwwwwwwwwbbbwbbwbbbbbbw....",
    "....wwbwwwwwwwwwwwwwwwwwwwwwwwwbbbwbbbbbbbww....",
    "....bwwbbbbbbbbbbbbbbwwwwwwbbbbbbbbbbbbbbwwb....",
    ".....bwwwwwwwwwwwwwwwbbwwbbwwwwwwwwwwwwwwwb.....",
    ".......wwwwwwwwwwwwwwwwbbwwwwwwwwwwwwwwww.......",
    "....................bwwwwb......................",
    "................................................",
    "................................................",
    "................................................",
]
# (traced from the official marks at 48 x 48: the Mets cap NY, the Ravens head, the Barça crest,
#  the DBU seal
#  and the Rangers shield;
#  the Rangers interior and lettering are redrawn in logos() so the text stays legible)


# bold 6 x 9 letters for KNICKS
FONT6 = {k: v.split() for k, v in {
    "K": "##..## ##.##. ####.. ###... ###... ####.. ##.##. ##..## ##..##",
    "N": "##..## ###.## ###### ###### ##.### ##..## ##..## ##..## ##..##",
    "I": "#### .##. .##. .##. .##. .##. .##. .##. ####",
    "C": ".##### ###### ##.... ##.... ##.... ##.... ##.... ###### .#####",
    "S": ".##### ###### ##.... #####. .##### ....## ....## ###### #####.",
    "D": "#####. ###### ##..## ##..## ##..## ##..## ##..## ###### #####.",
    "B": "#####. ##..## ##..## #####. #####. ##..## ##..## ###### #####.",
    "U": "##..## ##..## ##..## ##..## ##..## ##..## ##..## ###### .####.",
}.items()}


# 3 x 5 pixel font (only the letters the sprites use)
FONT3 = {k: v.split() for k, v in {
    "A": "### #.# ### #.# #.#", "B": "##. #.# ##. #.# ##.", "C": "### #.. #.. #.. ###",
    "E": "### #.. ##. #.. ###", "F": "### #.. ##. #.. #..", "K": "#.# #.# ##. #.# #.#",
    "L": "#.. #.. #.. #.. ###", "N": "#..# ##.# #.## #..# #..#", "S": "### #.. ### ..# ###",
    "T": "### .#. .#. .#. .#.", "Y": "#.# #.# .#. .#. .#.", "1": ".#. ##. .#. .#. ###",
    "R": "##. #.# ##. #.# #.#", "0": "### #.# #.# #.# ###", "2": "### ..# ### #.. ###",
    "3": "### ..# ### ..# ###", "4": "#.# #.# ### ..# ..#", "5": "### #.. ### ..# ###",
    "6": "### #.. ### #.# ###", "7": "### ..# ..# ..# ..#", "8": "### #.# ### #.# ###",
    "9": "### #.# ### ..# ###", ":": ". # . # .", "W": "#...# #...# #.#.# ##.## #...#", "O": "### #.# #.# #.# ###", "G": "### #.. #.# #.# ###", "D": "##. #.# #.# #.# ##.",
}.items()}

# ------------------------------------------------------------------ palettes
GOLD = {"H": "#fff3b0", "G": "#f2c230", "g": "#c8901a", "d": "#7a5410"}
SILV = {"H": "#ffffff", "G": "#d8dde6", "g": "#9aa3b2", "d": "#5b6372"}
BASE = {"b": "#4a3418", "B": "#2c1e0d", "p": "#e8e0d0"}


def cup(shade, base=True, handles="ears", lid=False, slim=False):
    """A generic trophy cup on a 16 x 20 grid, built on the left half then mirrored."""
    t = Grid(16, 20)
    P = dict(shade, **BASE)
    if slim:
        bowl = ["......HG", ".....HGG", ".....HGG", ".....GGg", "......Gg", "......Gg", ".......g"]
    else:
        bowl = ["...HHGGG", "...HGGGG", "...HGGGG", "....GGGG", "....GGGg", ".....GGg", "......Gg", ".......g"]
    top = 3 if lid else 1
    t.art(0, top, bowl, P)
    if lid:
        t.art(0, 0, [".......H", "......GG", ".....GGG"], P)
    if handles == "ears":
        t.art(0, top, ["..G.....", ".G......", ".G......", "..G.....", "...G...."], P)
    elif handles == "big":
        t.art(0, top - 1, [".GGG....", "G...G...", "G.......", "G.......", ".G......", "..GG...."], P)
    y = top + len(bowl)
    t.art(0, y, [".......g", ".......g", "......GG", ".....GGg"], P)
    if base:
        t.art(0, 16, ["....bbbb", "....bppb", "...bbbbb", "...BBBBB"], P)
    t.mirror()
    return t


def trophies():
    T = {}
    # Commissioner's-style flagged pennant (NL pennant): felt pennant on a stick
    g = Grid(16, 20)
    g.rect(2, 1, 1, 18, "#7a5410")
    g.poly([(3, 1), (15.5, 7), (3, 13)], "#002d72")
    g.text(4, 5, "NL", "#ff5910")
    g.rect(2, 0, 1, 1, "#f2c230")
    T["pennant"] = g
    # division title: a hanging banner with a notched hem
    g = Grid(16, 20)
    g.rect(1, 1, 14, 1, "#7a5410")
    g.rect(3, 2, 10, 14, "#002d72")
    g.poly([(3, 16), (8, 13), (13, 16), (13, 19), (8, 16.5), (3, 19)], "#002d72")
    g.rect(3, 2, 10, 1, "#ff5910")
    g.text(5, 5, "E", "#ff5910")
    g.text(4, 11, "NL", "#ffffff")  # N is 4 wide
    T["division"] = g
    # Vince Lombardi: a silver football tipped up on a tapering stand
    g = Grid(16, 20)
    P = dict(SILV, **BASE)
    g.ellipse(8, 4, 3.2, 4.2, "#d8dde6")
    g.ellipse(7.3, 3.4, 1.4, 2.4, "#ffffff")
    for y in (2, 4, 6):
        g.set(8, y, "#5b6372"); g.set(9, y, "#5b6372")
    g.rect(8, 1, 1, 7, "#9aa3b2")
    g.art(0, 8, ["......Gg", "......Gg", "......Gg", ".....GGg", ".....GGg", "....GGGg", "....GGGg", "...GGGGg"], P)
    g.art(0, 16, ["...bbbbb", "...bpppb", "..bbbbbb", "..BBBBBB"], P)
    for row in g.px[8:]:
        for i in range(8):
            row[15 - i] = row[i]
    T["superbowl"] = g
    # Larry O'Brien: a gold ball dropping through a hoop and net, on a tall stand
    g = Grid(16, 20)
    P = dict(GOLD, **BASE)
    g.disc(8, 3.2, 3.2, "#f2c230")
    g.disc(7, 2.4, 1.3, "#fff3b0")
    g.rect(8, 0, 1, 7, "#c8901a"); g.rect(5, 3, 7, 1, "#c8901a")
    g.art(0, 6, ["..GGGGGG", "...G.G.G", "....G.G.", "....G.G.", ".....GGg", "......Gg", "......Gg",
                 ".....GGg", ".....GGg", "....GGGg"], P)
    g.art(0, 16, ["...bbbbb", "...bpppb", "..bbbbbb", "..BBBBBB"], P)
    for row in g.px[6:]:
        for i in range(8):
            row[15 - i] = row[i]
    T["nba"] = g
    # La Liga: tall silver cup with a lid
    T["laliga"] = cup(SILV, handles="ears", lid=True)
    # Champions League: the big-eared silver cup
    T["ucl"] = cup(SILV, handles="big")
    # Copa del Rey: gold cup with a lid
    T["copa"] = cup(GOLD, handles="ears", lid=True)
    # Supercopa de España: small slim gold cup
    T["supercopa"] = cup(GOLD, handles=None, slim=True)
    # UEFA Super Cup: slim silver vase
    T["supercup"] = cup(SILV, handles=None, slim=True, lid=True)
    # Club World Cup: gold globe on a stand
    g = Grid(16, 20)
    P = dict(GOLD, **BASE)
    g.disc(8, 5, 5, "#f2c230")
    g.disc(7, 4, 2.2, "#fff3b0")
    for x in range(3, 13):
        g.set(x, 5, "#c8901a")
    for y in range(0, 10):
        if g.get(8, y):
            g.set(8, y, "#c8901a")
    g.art(0, 10, ["......Gg", "......Gg", ".....GGg", "....GGGg", "....GGGg", "...GGGGg"], P)
    g.art(0, 16, ["...bbbbb", "...bpppb", "..bbbbbb", "..BBBBBB"], P)
    for row in g.px[10:]:
        for i in range(8):
            row[15 - i] = row[i]
    T["cwc"] = g
    # Prince of Wales Trophy (NHL conference title): silver urn with a domed lid and finial
    g = Grid(16, 20)
    P = dict(SILV, **BASE)
    g.art(0, 0, [".......H", "......HG", ".....HGG", "....HGGG", "...GGGGG", "..G.HGGG", ".G..HGGG",
                 ".G..GGGG", "..G.GGGg", "...GGGGg", ".....GGg", "......Gg", "......Gg", ".....GGg",
                 "....GGGg", "...GGGGg"], P)
    g.art(0, 16, ["...bbbbb", "...bpppb", "..bbbbbb", "..BBBBBB"], P)
    g.mirror()
    T["conference"] = g
    # Presidents' Trophy (best NHL record): a wide silver bowl on a column
    g = Grid(16, 20)
    P = dict(SILV, **BASE)
    g.art(0, 2, ["HHHHGGGG", ".HGGGGGG", "..GGGGGg", "...GGGgg", ".....GGg", "......Gg", "......Gg",
                 "......Gg", "......Gg", ".....GGg", "....GGGg", "...GGGGg", "..GGGGGg"], P)
    g.art(0, 16, ["..bbbbbb", "..bpppbb", ".bbbbbbb", ".BBBBBBB"], P)
    g.mirror()
    T["presidents"] = g
    # ESEA League plaques: a shield on a stand, banded in the division's colour
    for div, band in (("open", "#b0763c"), ("intermediate", "#c8ccd6"), ("main", "#f2c230")):
        g = Grid(16, 20)
        g.poly([(2, 1), (14, 1), (14, 9), (8, 15.5), (2, 9)], "#1d1d1b")
        g.poly([(3, 2), (13, 2), (13, 8.6), (8, 14), (3, 8.6)], "#2e7d32")
        g.rect(3, 4, 10, 3, band)
        g.art(5, 8, ["#...#", ".#.#.", "..#.."], {"#": "#9fe870"})
        g.rect(7, 15, 2, 1, "#4a3418")
        g.art(0, 16, ["...bbbbb", "...bpppb", "..bbbbbb", "..BBBBBB"], BASE)
        for row in g.px[16:]:
            for i in range(8):
                row[15 - i] = row[i]
        T[f"esea-{div}"] = g
    # FACEIT top 1000 (season leaderboard): an orange plaque with 1K on a stand
    g = Grid(16, 20)
    g.poly([(2, 1), (14, 1), (14, 11), (8, 15.5), (2, 11)], "#1d1d1b")
    g.poly([(3, 2), (13, 2), (13, 10.6), (8, 14.2), (3, 10.6)], "#ff5500")
    g.art(4, 4, ["#.#..#", "#.#.#.", "#.##..", "#.#.#.", "#.#..#"], {"#": "#ffffff"})
    g.rect(7, 15, 2, 1, "#4a3418")
    g.art(0, 16, ["...bbbbb", "...bpppb", "..bbbbbb", "..BBBBBB"], BASE)
    for row in g.px[16:]:
        for i in range(8):
            row[15 - i] = row[i]
    T["faceit-top1000"] = g
    # bronze medal on a ribbon (a 3rd-place finish)
    g = Grid(16, 20)
    g.poly([(4, 0), (7, 0), (9, 7), (6, 7)], "#3a7bd5"); g.poly([(9, 0), (12, 0), (10, 7), (7, 7)], "#c8102e")
    g.disc(8, 12.5, 5.6, "#7a4a1e"); g.disc(8, 12.5, 4.6, "#c47a3a"); g.disc(7, 11.5, 1.8, "#e0a06a")
    g.art(7, 10, ["##", ".#", "##", ".#", "##"], {"#": "#5a3210"})
    T["medal-3"] = g
    # empty plinth, for a team with no titles yet
    g = Grid(16, 20)
    g.art(0, 16, ["...bbbbb", "...bpppb", "..bbbbbb", "..BBBBBB"], BASE)
    g.mirror()
    for (x, y) in ((6, 9), (7, 8), (8, 8), (9, 9), (9, 10), (8, 11), (8, 13)):
        g.set(x, y, "#9aa3b2")
    T["none"] = g
    return T


def logos():
    L = {}
    # Mets: the interlocking NY from the cap, in orange
    g = Grid(48, 48)
    g.art(0, 0, METS_NY, {"o": "#ff5910"})
    L["mets"] = g
    # Knicks: the triangle crest (layout traced from the official mark), redrawn so it reads:
    # white edge, blue rim, silver band, NEW YORK on the arch, KNICKS with a blue drop shadow,
    # and the ball sitting in the point of the triangle.
    g = Grid(48, 48)
    WH, BL, DB, OR, SV, SEAM = "#ffffff", "#006bb6", "#00438a", "#f58426", "#bec0c2", "#1d1d1b"
    g.poly([(8, 3), (40, 3), (43, 6), (44, 12), (4, 12), (5, 6)], WH)  # the arch behind NEW YORK
    g.poly([(0, 11), (48, 11), (24, 46)], WH)                       # the triangle
    g.poly([(2.5, 12.5), (45.5, 12.5), (24, 43.5)], BL)              # blue rim
    g.poly([(6.5, 14.5), (41.5, 14.5), (24, 39.5)], SV)              # silver band
    for k in range(4):                                              # blue shadow stripes in the band
        g.poly([(9 + 9 * k, 14.5), (11 + 9 * k, 14.5), (17 + 4 * k, 27), (15 + 4 * k, 27)], BL)
    x = 8
    for ch, wd in (("N", 4), ("E", 3), ("W", 5), (" ", 1), ("Y", 3), ("O", 3), ("R", 3), ("K", 3)):
        if ch != " ":
            g.text(x, 5, ch, BL)
        x += wd + 1
    word, x = "KNICKS", 5
    for ch in word:                                                 # shadow first, then the letter
        g.text(x + 1, 13, ch, DB, font=FONT6)
        x += len(FONT6[ch][0]) + 1
    x = 5
    for ch in word:
        g.text(x, 12, ch, OR, font=FONT6)
        x += len(FONT6[ch][0]) + 1
    g.disc(24, 32.5, 10.6, DB)                                      # ball: dark rim, orange, seams
    g.disc(24, 32.5, 9.6, OR)
    for y in range(48):
        for xx in range(48):
            if g.get(xx, y) == OR and y > 21:
                if xx == 24 or y == 32 or abs(math.hypot(xx + .5 - 13, y + .5 - 32.5) - 9) < .55 \
                        or abs(math.hypot(xx + .5 - 35, y + .5 - 32.5) - 9) < .55:
                    g.set(xx, y, SEAM)
    L["knicks"] = g
    # Ravens: the head, traced block by block; the B, the eye and the beak are finished by hand
    g = Grid(48, 48)
    PU, BK, GO, WH, RD = "#241773", "#000000", "#9e7c0c", "#ffffff", "#c60c30"
    g.art(0, 0, RAVENS_HEAD, {"p": PU, "k": BK, "g": GO, "w": WH, "r": RD})
    g.rect(15, 16, 14, 8, PU)
    g.text(17, 15, "B", GO, font=FONT6)
    for y in range(18, 23):
        for x in range(28, 34):
            if g.get(x, y) == RD:
                g.set(x, y, PU)
    g.rect(29, 18, 4, 4, WH); g.rect(30, 19, 2, 2, RD)
    for y in range(22, 29):
        for x in range(31, 45):
            if g.get(x, y) == BK:
                g.set(x, y, WH)
    g.rect(32, 25, 12, 1, BK)
    g.px = g.px[6:] + g.px[:6]  # sit the head in the middle of the square
    L["ravens"] = g
    # Rangers: the shield. Border from the trace; inside redrawn: NEW YORK on the top band,
    # then the red corner, the blue diagonal band carrying RANGERS, and the white lower left.
    g = Grid(48, 48)
    W, B, R = "#ffffff", "#0038a8", "#ce1126"
    g.art(0, 0, RANGERS_SHIELD, {"w": W, "b": B, "r": R})
    g.rect(5, 7, 38, 6, B)
    g.text(8, 8, "NEW", W)
    g.text(26, 8, "YORK", W)
    for y in range(15, 41):
        for x in range(6 if y < 40 else 7, 42 if y < 40 else 41):
            if y < 16 + 0.75 * (x - 21):
                g.set(x, y, R)
            elif y > 26 + 0.72 * (x - 11):
                g.set(x, y, W)
            else:
                g.set(x, y, B)
    for k, ch in enumerate("RANGERS"):  # upright letters stepping down the band
        x = 8 + 5 * k
        mid = (max(15, 16 + 0.75 * (x + 1 - 21)) + min(39, 26 + 0.72 * (x + 1 - 11))) / 2
        g.text(x, round(mid - 2.5), ch, W)
    L["rangers"] = g
    # FC Barcelona: the crest, traced; FCB, the blaugrana stripes and the ball redrawn clean
    g = Grid(48, 48)
    GD, RD, BL, MR, WH, DK = "#edbb00", "#db0030", "#004d98", "#a50044", "#ffffff", "#1d1d1b"
    g.art(0, 0, BARCA_CREST, {"y": GD, "r": RD, "b": BL, "m": MR, "w": WH, "k": DK})
    for y in range(48):  # stray maroon specks from the trace: red in the top quarters, gold on the rim
        for x in range(48):
            if g.get(x, y) == MR and y < 19:
                g.set(x, y, RD)
            elif g.get(x, y) == MR and (x < 5 or x > 42):
                g.set(x, y, GD)
    g.rect(8, 19, 32, 6, GD)
    for x, ch in ((15, "F"), (22, "C"), (29, "B")):
        g.text(x, 20, ch, DK)
    stripes = [(5, BL), (10, MR), (16, BL), (21, MR), (27, BL), (32, MR), (38, BL), (43, None)]
    for y in range(26, 44):
        for x in range(48):
            if g.get(x, y) in (BL, MR):
                c = [col for x0, col in stripes if x0 <= x][-1]
                if c:
                    g.set(x, y, c)
    g.rect(5, 25, 38, 1, DK)
    g.disc(24, 33, 5.2, DK)
    g.disc(24, 33, 4.3, GD)
    for (x, y) in ((22, 31), (22, 32), (22, 34), (22, 35), (26, 31), (26, 32), (26, 34), (26, 35),
                   (23, 33), (24, 33), (25, 33), (24, 30), (24, 36)):  # panel seams, in a darker gold
        g.set(x, y, "#a37a00")
    L["barcelona"] = g
    # Denmark: the DBU seal. The ring of lettering is traced; the middle is redrawn:
    # a bold white DBU between a small flourish and the rosette.
    g = Grid(48, 48)
    RE, WH = "#c8102e", "#ffffff"
    g.art(0, 0, DBU_SEAL, {"r": RE, "w": WH})
    for y in range(48):
        for x in range(48):
            r = math.hypot(x + .5 - 24, y + .5 - 24)
            if r > 24:
                g.set(x, y, None)
            elif r > 23:
                g.set(x, y, WH)
            elif r < 16.4:
                g.set(x, y, WH if r > 15.4 else RE)
    x = 14
    for ch in "DBU":
        g.text(x, 20, ch, WH, font=FONT6)
        x += 7
    g.art(18, 14, ["#.##..##.#", ".#..##..#."], {"#": WH})      # the flourish over DBU
    g.art(21, 31, [".##.", "#..#", "#..#", ".##."], {"#": WH})  # the rosette under it
    L["denmark"] = g
    return L


def icons():
    """16 x 16 single-colour icons ("c" = currentColor)."""
    I = {}
    I["icon-anime"] = ascii_icon([  # a big anime eye with a sparkle
        "................", "................", "....########....", "..##........##..", ".#..########..#.",
        "#..##########..#", "#.####..######.#", "#.####..######.#", "#.############.#", "#..##########..#",
        ".#..########..#.", "..##........##..", "....########....", "................", "................", "................"])
    I["icon-manga"] = ascii_icon([  # a speech bubble with speed lines
        "................", "...##########...", "..#..........#..", ".#..##..##....#.", ".#............#.",
        ".#..######....#.", ".#............#.", "..#..........#..", "...###..######..", ".....#.#........",
        ".....##.........", "......#.........", "................", "##..##..##..##..", "................", "................"])
    I["icon-book"] = ascii_icon([  # a solid hardback with a title label
        "................", "..###########...", "..#.#########...", "..#.#########...", "..#.###...###...",
        "..#.#########...", "..#.#########...", "..#.#########...", "..#.#########...", "..#.#########...",
        "..#.#########...", "..#.#########...", "..#.##########..", "..#...........#.", "..############..", "................"])
    I["icon-trophy"] = ascii_icon([
        "................", "..############..", "##.##########.##", "#..##########..#", "#..##########..#",
        ".#.##########.#.", "..#.########.#..", "....########....", ".....######.....", "......####......",
        ".......##.......", ".......##.......", "......####......", ".....######.....", "....########....", "................"])
    return I


def counterstrike():
    """Counter-Strike sprites: weapons as symbols, the C4 as animation frames."""
    S = {}
    I = {}
    I["icon-tiktok"] = ascii_icon([
        "................", "........##......", "........###.....", "........####....", "........##.###..",
        "........##...##.", "........##......", "........##......", "....######......", "...#######......",
        "..###...##......", "..##....##......", "..###..###......", "...######.......", "....####........", "................"])
    I["icon-twitch"] = ascii_icon([
        "................", "..############..", "..#..........#..", "..#..........#..", "..#...#..#...#..",
        "..#...#..#...#..", "..#...#..#...#..", "..#..........#..", "..#.........#...", "..#........#....",
        "..#####...#.....", "......#..#......", "......#.#.......", "......##........", "................", "................"])
    I["icon-crosshair"] = ascii_icon([
        "................", ".......##.......", ".......##.......", ".......##.......", ".......##.......",
        "................", "................", "####........####", "####........####", "................",
        "................", ".......##.......", ".......##.......", ".......##.......", ".......##.......", "................"])
    # AK-47, facing right
    g = Grid(48, 14)
    WD, WL, MT, ML, BK, MG = "#8b4a1e", "#b5652a", "#3a3a40", "#6b6b75", "#1d1d1b", "#a0522d"
    g.poly([(0, 5), (11, 5), (13, 7), (13, 9), (4, 11.5), (0, 11.5)], WD)
    g.rect(0, 5, 11, 1, WL)
    g.rect(12, 4, 15, 4, MT); g.rect(12, 4, 15, 1, ML)
    g.poly([(17, 8), (20.5, 8), (19.5, 12.5), (16, 12.5)], WD)
    g.poly([(22, 8), (26, 8), (29.5, 13.5), (25.5, 13.5)], MG)
    g.rect(27, 4, 9, 4, WD); g.rect(27, 4, 9, 1, WL)
    g.rect(27, 3, 10, 1, MT)
    g.rect(36, 5, 11, 1, MT); g.rect(36, 6, 6, 1, BK)
    g.rect(44, 3, 1, 2, MT); g.rect(46, 4, 2, 3, MT)
    g.rect(14, 3, 2, 1, MT)
    g.set(21, 8, BK); g.set(22, 8, BK)  # trigger guard
    S["px-ak47"] = g
    # AWP, facing right
    g = Grid(64, 16)
    GN, GL, GD, BK, LN, MT = "#4b5d3a", "#6b7f55", "#2f3b25", "#1d1d1b", "#6fb3ff", "#5b6372"
    g.poly([(0, 6), (14, 6), (16.5, 8), (16.5, 10), (8, 12.5), (0, 12.5)], GN)
    g.rect(0, 6, 14, 1, GL)
    g.rect(6, 8, 5, 2, None)  # thumbhole
    g.rect(16, 6, 22, 4, GN); g.rect(16, 6, 22, 1, GL)
    g.poly([(20, 10), (23.5, 10), (22.5, 14.5), (19, 14.5)], GD)
    g.rect(27, 10, 4, 3, GD)
    g.rect(18, 2, 20, 3, BK); g.rect(16, 1, 3, 5, BK); g.rect(37, 1, 3, 5, BK)
    g.rect(39, 2, 1, 3, LN)
    g.rect(22, 5, 2, 1, BK); g.rect(33, 5, 2, 1, BK)
    g.rect(24, 10, 1, 1, MT); g.rect(25, 11, 1, 1, MT)
    g.rect(38, 7, 22, 2, GD); g.rect(38, 7, 22, 1, MT)
    g.rect(59, 6, 5, 4, BK)
    S["px-awp"] = g
    # FACEIT skill level 10: the red gauge ring with 10 in the middle
    g = Grid(16, 16)
    g.disc(8, 8, 7.6, "#1d1d1b")
    for y in range(16):
        for x in range(16):
            r = math.hypot(x + .5 - 8, y + .5 - 8)
            ang = math.degrees(math.atan2(y + .5 - 8, x + .5 - 8))
            if 5.2 < r < 7.4 and not (60 < ang < 120):
                g.set(x, y, "#fe1f00")
    g.art(5, 5, ["#.###", "#.#.#", "#.#.#", "#.#.#", "#.###"], {"#": "#ffffff"})
    S["px-faceit10"] = g
    # 1NT: the wireframe globe with the lavender band and tall 1NT lettering (built from the team avatar)
    g = Grid(32, 32)
    R = 14.6
    for y in range(32):
        for x in range(32):
            dx, dy = x + .5 - 16, y + .5 - 16
            r = math.hypot(dx, dy)
            if r > R + .6:
                continue
            if r > R - .4:
                g.set(x, y, "#3a3a3a"); continue
            lit = math.hypot(x + .5 - 11, y + .5 - 10)  # light from the upper left
            g.set(x, y, "#e8e8e8" if lit < 6 else "#bdbdbd" if lit < 11 else "#8c8c8c" if lit < 16 else "#666666")
            half = math.sqrt(max(R * R - dy * dy, 0))
            on_parallel = any(abs(dy - (lv + .5)) < .5 for lv in range(-13, 13, 3))
            on_meridian = abs(dx) < .5 or any(abs(abs(dx) - k * half) < .5 for k in (.3, .58, .82, .96))
            if on_parallel or on_meridian:
                g.set(x, y, "#3e3e3e")
    for y in range(15, 17):  # the glowing equator
        for x in range(32):
            if g.get(x, y) and g.get(x, y) != "#3a3a3a":
                g.set(x, y, "#c8aaf0")
    K = "#0a0a0a"
    g.rect(7, 9, 2, 14, K); g.set(6, 10, K); g.set(5, 11, K); g.rect(6, 9, 1, 1, K); g.rect(5, 21, 6, 2, K)
    g.rect(12, 9, 2, 14, K); g.rect(18, 9, 2, 14, K)
    for k in range(11):
        g.rect(14 + round(k * 3 / 10), 10 + k, 2, 1, K)
    g.rect(21, 9, 7, 2, K); g.rect(23, 9, 2, 14, K)
    halo = [(x, y) for y in range(32) for x in range(32) if g.get(x, y) not in (None, K)
            and any(g.get(x + a, y + b) == K for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1)))]
    for x, y in halo:  # a light rim so the letters stand off the wireframe
        g.set(x, y, "#f4f4f4")
    S["px-1nt"] = g
    # a cartoon bomb for Bomb Squad (no team mark on record)
    g = Grid(24, 24)
    g.disc(11, 14, 8.6, "#1d1d1b")
    g.disc(9, 11.5, 2.2, "#5b6372")
    g.rect(14, 4, 4, 3, "#5b6372")
    for (x, y) in ((18, 3), (19, 2), (20, 2), (21, 1)):
        g.set(x, y, "#c9a86b")
    for (x, y, c) in ((21, 0, "#ff3b3b"), (22, 1, "#f2c230"), (20, 0, "#f2c230"), (22, 0, "#ffffff")):
        g.set(x, y, c)
    S["px-bombsquad"] = g
    # flags, 16 x 11
    g = Grid(16, 11)
    for y in range(11):
        g.rect(0, y, 16, 1, "#b22234" if y % 2 == 0 else "#ffffff")
    g.rect(0, 0, 7, 6, "#3c3b6e")
    for y in (1, 3):
        for x in (1, 3, 5):
            g.set(x, y, "#ffffff")
    for y in (2, 4):
        for x in (2, 4):
            g.set(x, y, "#ffffff")
    S["px-flag-us"] = g
    g = Grid(16, 11)
    g.rect(0, 0, 16, 11, "#c8102e"); g.rect(5, 0, 2, 11, "#ffffff"); g.rect(0, 4, 16, 2, "#ffffff")
    S["px-flag-dk"] = g
    g = Grid(16, 11)
    g.rect(0, 0, 16, 11, "#ffffff"); g.rect(0, 0, 4, 11, "#d52b1e"); g.rect(12, 0, 4, 11, "#d52b1e")
    g.art(5, 2, ["...#..", ".#.#.#", "..###.", "######", ".####.", "...#.."], {"#": "#d52b1e"})
    g.rect(8, 8, 1, 2, "#d52b1e")
    S["px-flag-ca"] = g
    # C4: three tan sticks taped together under the keypad module; two frames
    frames = []
    for k, (led, digits) in enumerate((("#ff3b3b", "40"), ("#7a1010", "39"))):
        g = Grid(40, 26)
        TN, TH, TD, TP = "#c9a86b", "#e3c896", "#8e6f3e", "#1d1d1b"
        for i in range(3):
            y0 = 10 + i * 5
            g.rect(2, y0, 36, 5, TN); g.rect(2, y0, 36, 1, TH); g.rect(2, y0 + 4, 36, 1, TD)
            for (x, y) in ((2, y0), (37, y0), (2, y0 + 4), (37, y0 + 4)):
                g.set(x, y, None)
        g.rect(7, 10, 3, 15, TP); g.rect(30, 10, 3, 15, TP)
        g.rect(11, 1, 18, 12, "#5b6372"); g.rect(12, 2, 16, 10, "#9aa3b2")
        g.rect(13, 3, 14, 5, "#24451a")
        g.text(16, 3, digits, "#9fe870")
        for x in (13, 16, 19, 22):
            g.rect(x, 9, 2, 1, "#e8ecf2"); g.rect(x, 11, 2, 1, "#e8ecf2")
        g.rect(25, 9, 2, 3, led)
        for (x, y) in ((10, 5), (9, 6), (8, 7), (7, 8), (6, 9)):
            g.set(x, y, "#e5322d")
        for (x, y) in ((29, 5), (30, 6), (31, 7), (32, 8), (33, 9)):
            g.set(x, y, "#3a7bd5")
        for (x, y) in ((29, 8), (30, 9)):
            g.set(x, y, "#f2c230")
        frames.append(g)
    return I, S, {"c4": frames}


def animated(name, frames, cls_n):
    out = [f'<svg class="px px--{name} px--n{cls_n}" viewBox="0 0 {frames[0].w} {frames[0].h}" width="{frames[0].w}" height="{frames[0].h}" shape-rendering="crispEdges" aria-hidden="true" focusable="false">']
    for i, g in enumerate(frames):
        inner = symbol("x", g)
        inner = inner[inner.index(">") + 1:inner.rindex("</symbol>")]
        out.append(f'<g class="px__f" style="--i:{i}">{inner}</g>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def ascii_icon(rows):
    g = Grid(16, 16)
    g.art(0, 0, rows, {"#": "c"})
    return g


def symbol(sid, g):
    rects = []
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
            fill = "" if c == "c" else f' fill="{c}"'
            rects.append(f'<rect x="{x0}" y="{y}" width="{x - x0}" height="1"{fill}/>')
    return f'<symbol id="{sid}" viewBox="0 0 {g.w} {g.h}" shape-rendering="crispEdges">{"".join(rects)}</symbol>'


def preview(name, g, outdir, scale=8):
    ppm = os.path.join(outdir, name + ".ppm")
    with open(ppm, "w") as f:
        f.write(f"P3 {g.w} {g.h} 255\n")
        for row in g.px:
            for c in row:
                c = {None: "#2b2140", "c": "#e8e0d0"}.get(c, c)
                f.write(" ".join(str(int(c[i:i + 2], 16)) for i in (1, 3, 5)) + "\n")
    subprocess.run(["convert", ppm, "-filter", "point", "-resize", f"{scale * 100}%", ppm[:-4] + ".png"], check=True)
    os.remove(ppm)


def main():
    sprites = {}
    sprites.update(icons())
    sprites.update({f"px-{k}": v for k, v in logos().items()})
    sprites.update({f"px-tr-{k}": v for k, v in trophies().items()})
    cs_icons, cs_sprites, cs_anim = counterstrike()
    sprites.update(cs_icons)
    sprites.update(cs_sprites)
    for name, frames in cs_anim.items():
        with open(os.path.join(ROOT, "layouts", "partials", "px", f"{name}.html"), "w") as f:
            f.write(animated(name, frames, len(frames)))
    # the menu bar loads icons as files, in the menu's lavender
    icon = symbol("x", cs_icons["icon-crosshair"])
    icon = icon[icon.index(">") + 1:icon.rindex("</symbol>")]
    with open(os.path.join(ROOT, "static", "img", "icons", "laursen.svg"), "w") as f:
        f.write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" shape-rendering="crispEdges" fill="#c8c7ff">{icon}</svg>\n')
    with open(OUT, "w") as f:
        f.write("{{- /* Generated by scripts/pixelart.py: edit that script, not this file. */ -}}\n")
        f.write('<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">')
        f.write("".join(symbol(k, v) for k, v in sprites.items()))
        f.write("</svg>\n")
    print(f"wrote {len(sprites)} sprites to {os.path.relpath(OUT, ROOT)}")
    if "--preview" in sys.argv:
        d = sys.argv[sys.argv.index("--preview") + 1]
        os.makedirs(d, exist_ok=True)
        for k, v in sprites.items():
            preview(k, v, d)


if __name__ == "__main__":
    main()
