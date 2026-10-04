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


# 3 x 5 pixel font (only the letters the sprites use)
FONT3 = {k: v.split() for k, v in {
    "A": "### #.# ### #.# #.#", "B": "##. #.# ##. #.# ##.", "C": "### #.. #.. #.. ###",
    "E": "### #.. ##. #.. ###", "F": "### #.. ##. #.. #..", "K": "#.# #.# ##. #.# #.#",
    "L": "#.. #.. #.. #.. ###", "N": "#..# ##.# #.## #..# #..#", "S": "### #.. ### ..# ###",
    "T": "### .#. .#. .#. .#.", "Y": "#.# #.# .#. .#. .#.", "1": ".#. ##. .#. .#. ###",
    "R": "##. #.# ##. #.# #.#", "G": "### #.. #.# #.# ###", "D": "##. #.# #.# #.# ##.",
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
    # NBA Cup: a squat gold chalice with a silver rim
    g = cup(GOLD, handles="ears")
    for x in range(3, 13):
        g.set(x, 1, "#ffffff")
    T["nbacup"] = g
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
    # Mets: orange interlocking NY on a royal-blue disc
    g = Grid(24, 24)
    g.disc(12, 12, 11.6, "#ffffff")
    g.disc(12, 12, 10.6, "#002d72")
    N = ["##....##", "###...##", "####..##", "##.##.##", "##..####", "##...###", "##....##", "##....##", "##....##", "##....##"]
    Y = ["##....##", "##....##", ".##..##.", "..####..", "...##...", "...##...", "...##...", "...##...", "..####..", "..####.."]
    g.art(3, 6, N, {"#": "#ff5910"})
    g.art(10, 8, Y, {"#": "#ff5910"})
    for (x, y) in ((10, 8), (11, 9), (10, 9)):  # the Y's arm crosses in front of the N, keyed in white
        g.set(x, y, "#ffffff")
    L["mets"] = g
    # Knicks: orange basketball with a blue band and NYK
    g = Grid(24, 24)
    g.disc(12, 12, 11.6, "#1d1d1b")
    g.disc(12, 12, 10.6, "#f58426")
    for y in range(24):
        for x in range(24):
            if g.get(x, y) == "#f58426" and (x == 12 or abs(math.hypot(x - 1, y - 12) - 8.5) < 0.6
                                              or abs(math.hypot(x - 23, y - 12) - 8.5) < 0.6):
                g.set(x, y, "#a3501a")
    g.rect(0, 8, 24, 8, "#006bb6")
    g.rect(0, 8, 24, 1, "#bec0c2"); g.rect(0, 15, 24, 1, "#bec0c2")
    g.text(6, 10, "NYK", "#ffffff")
    L["knicks"] = g
    # Giants: lowercase ny in blue with a red keyline
    g = Grid(24, 24)
    g.rect(0, 0, 24, 24, "#ffffff")
    n = ["#.####.", "#######", "###..##", "##...##", "##...##", "##...##", "##...##", "##...##"]
    y = ["##...##", "##...##", "##...##", "##...##", ".##.###", "..####.", "....##.", "...##..", "####...", "###...."]
    inner = Grid(24, 24)
    inner.art(2, 6, n, {"#": "#0b2265"})
    inner.art(12, 6, y, {"#": "#0b2265"})
    inner.outline("#a71930")
    for j in range(24):
        for i in range(24):
            if inner.px[j][i]:
                g.set(i, j, inner.px[j][i])
    L["giants"] = g
    # Rangers: blue shield, red diagonal band, white trim
    g = Grid(24, 24)
    shield = [(2, 1), (22, 1), (22, 13), (12, 23), (2, 13)]
    g.poly(shield, "#ffffff")
    g.poly([(3, 2), (21, 2), (21, 13), (12, 21.6), (3, 13)], "#0038a8")
    g.poly([(3, 15), (21, 5), (21, 10), (3, 20)], "#ffffff")
    g.poly([(3, 16), (21, 6), (21, 9), (3, 19)], "#ce1126")
    for y0 in range(24):
        for x0 in range(24):
            if not inside(x0 + .5, y0 + .5, [(3, 2), (21, 2), (21, 13), (12, 21.6), (3, 13)]) and g.get(x0, y0) in ("#ce1126",):
                g.set(x0, y0, None)
    g.text(5, 4, "NY", "#ffffff")
    for k in range(7):  # the RANGERS lettering, as white ticks along the band
        g.set(5 + 2 * k, 16 - k, "#ffffff")
    for y0 in range(24):
        for x0 in range(24):
            if g.get(x0, y0) and not inside(x0 + .5, y0 + .5, shield):
                g.set(x0, y0, None)
    L["rangers"] = g
    # FC Barcelona crest: St George cross, Senyera, blaugrana with the ball
    g = Grid(24, 24)
    outer = [(3, 0), (21, 0), (23, 3), (21, 6), (21, 15), (12, 23.5), (3, 15), (3, 6), (1, 3)]
    g.poly(outer, "#1d1d1b")
    g.poly([(4, 1), (20, 1), (22, 3), (20, 5), (4, 5), (2, 3)], "#f2c230")  # top rim
    g.rect(4, 6, 8, 5, "#ffffff")
    g.rect(7, 6, 2, 5, "#cd122d"); g.rect(4, 8, 8, 1, "#cd122d")
    for k, x in enumerate(range(13, 21)):
        g.rect(x, 6, 1, 5, "#f2c230" if k % 2 == 0 else "#cd122d")
    g.rect(4, 11, 17, 2, "#f2c230")
    for x in (7, 8, 10, 12, 13, 15, 16):
        g.set(x, 3, "#1d1d1b")
    body = [(4, 13), (20, 13), (20, 15), (12, 22), (4, 15)]
    for k, x in enumerate(range(4, 21)):
        for yy in range(13, 23):
            if inside(x + .5, yy + .5, body):
                g.set(x, yy, "#004d98" if (x // 2) % 2 == 0 else "#a50044")
    g.disc(12, 15.5, 2.4, "#f2c230")
    g.set(11, 15, "#c8901a"); g.set(12, 16, "#c8901a")
    L["barcelona"] = g
    # Denmark: the Dannebrog
    g = Grid(24, 24)
    g.rect(0, 3, 24, 18, "#c8102e")
    g.rect(7, 3, 3, 18, "#ffffff")
    g.rect(0, 10, 24, 3, "#ffffff")
    g.rect(0, 20, 24, 1, "#8f0b20")
    g.rect(23, 3, 1, 18, "#8f0b20")
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
