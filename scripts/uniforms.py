"""ARKNDJL full uniforms as pixel art: headwear, jersey, pants or shorts, socks and shoes.

Five sports, three kits each (lilac home, aquamarine away, black alternate), drawn
front and back. Colours are lilac and aquamarine with white, grey and black only.
The site glyph is the team logo. Every piece is a sprite: flat colour regions,
then lit from the top left (highlight rim, shadow band with a dithered edge) and
ringed with a selective outline (a darker shade of the colour it borders).

Sprites feed two outputs:
  scripts/uniforms.py   pixel uniform cards  -> static/img/art/arkndjl-uniform-<sport>.png, -lineup.png
  scripts/jersey_ps1.py low-poly figures      -> static/img/art/arkndjl-ps1-<sport>.gif, -lineup.gif
"""
import os, re
import numpy as np
from PIL import Image, ImageDraw

LILAC, TEAL, WHITE = (200, 199, 255), (127, 255, 212), (240, 240, 246)
LGREY, GREY, CHAR, BLACK = (192, 192, 202), (140, 140, 150), (48, 48, 56), (24, 24, 28)
BG, BG2 = (28, 28, 33), (36, 36, 42)

KITS = {
    "home": dict(base=LILAC, trim=CHAR, acc=TEAL, ink=CHAR, ring=WHITE, word=CHAR,
                 pants=WHITE, ptrim=LILAC, sock=LILAC, shoe=WHITE, shell=LILAC, cap=CHAR, logo=LILAC),
    "away": dict(base=TEAL, trim=CHAR, acc=LILAC, ink=CHAR, ring=WHITE, word=CHAR,
                 pants=WHITE, ptrim=TEAL, sock=TEAL, shoe=WHITE, shell=TEAL, cap=CHAR, logo=TEAL),
    "alternate": dict(base=BLACK, trim=TEAL, acc=LILAC, ink=LILAC, ring=TEAL, word=TEAL,
                      pants=BLACK, ptrim=TEAL, sock=BLACK, shoe=BLACK, shell=BLACK, cap=BLACK, logo=TEAL),
}
NUMS = {"football": "11", "basketball": "1", "hockey": "31", "soccer": "10", "baseball": "7"}
SPORTS = ["football", "basketball", "hockey", "soccer", "baseball"]


def tone(c, t):
    """t > 0 toward white, t < 0 toward a cool near-black."""
    tgt = (255, 255, 255) if t > 0 else (12, 12, 18)
    return tuple(int(round(a + (b - a) * abs(t))) for a, b in zip(c, tgt))


# ---------- fonts ----------
F3 = {  # 3x5, for card labels
    "A": "010101111101101", "B": "110101110101110", "C": "011100100100011", "D": "110101101101110",
    "E": "111100110100111", "F": "111100110100100", "G": "011100101101011", "H": "101101111101101",
    "I": "111010010010111", "J": "001001001101010", "K": "101101110101101", "L": "100100100100111",
    "M": "101111111101101", "N": "110101101101101", "O": "010101101101010", "P": "110101110100100",
    "R": "110101110101101", "S": "011100010001110", "T": "111010010010010", "U": "101101101101111",
    "V": "101101101101010", "W": "101101111111101", "Y": "101101010010010", " ": "000000000000000",
    "/": "001001010100100", "-": "000000111000000", "0": "111101101101111", "1": "010110010010111",
    "3": "110001010001110", "7": "111001010010010",
}
F4 = {  # 4x7 wordmark
    "A": [".##.", "#..#", "#..#", "####", "#..#", "#..#", "#..#"],
    "R": ["###.", "#..#", "#..#", "###.", "#.#.", "#..#", "#..#"],
    "K": ["#..#", "#.#.", "##..", "##..", "#.#.", "#..#", "#..#"],
    "N": ["#..#", "##.#", "##.#", "#.##", "#.##", "#..#", "#..#"],
    "D": ["###.", "#..#", "#..#", "#..#", "#..#", "#..#", "###."],
    "J": ["...#", "...#", "...#", "...#", "#..#", "#..#", ".##."],
    "L": ["#...", "#...", "#...", "#...", "#...", "#...", "####"],
}
F6 = {  # 6x10 block numerals
    "0": [".####.", "##..##", "##..##", "##..##", "##..##", "##..##", "##..##", "##..##", "##..##", ".####."],
    "1": ["..##..", ".###..", "####..", "..##..", "..##..", "..##..", "..##..", "..##..", "..##..", "######"],
    "3": ["#####.", "....##", "....##", "....##", ".####.", "....##", "....##", "....##", "....##", "#####."],
    "7": ["######", "....##", "....##", "...##.", "...##.", "..##..", "..##..", ".##...", ".##...", ".##..."],
    "2": [".####.", "##..##", "....##", "....##", "...##.", "..##..", ".##...", "##....", "##....", "######"],
    "4": ["##..##", "##..##", "##..##", "##..##", "######", "....##", "....##", "....##", "....##", "....##"],
    "5": ["######", "##....", "##....", "#####.", "....##", "....##", "....##", "....##", "##..##", ".####."],
    "6": [".####.", "##....", "##....", "#####.", "##..##", "##..##", "##..##", "##..##", "##..##", ".####."],
    "8": [".####.", "##..##", "##..##", "##..##", ".####.", "##..##", "##..##", "##..##", "##..##", ".####."],
    "9": [".####.", "##..##", "##..##", "##..##", "##..##", ".#####", "....##", "....##", "....##", ".####."],
}


# ---------- the site glyph, rasterised from its vector path ----------
GLYPH = ("M52 0V45.9H98.8L243.6 263H42.8L352 750.3L661.2 263H460.4L604.2 45.9H652V0H491V45.9H523.6L376 269"
         "L388 272.8V45.9H429V0H275V45.9H316V272.8L328 269L179.4 45.9H213V0ZM191.3 342.2H512.7L352 596.3Z")


def glyph_mask(h):
    """Boolean mask of the glyph, h pixels tall (8x supersampled, area threshold)."""
    polys, cur, x, y = [], [], 0.0, 0.0
    for cmd, args in re.findall(r"([MLHVZ])([^MLHVZ]*)", GLYPH):
        v = [float(a) for a in args.split()]
        if cmd == "M": x, y = v; cur = [(x, y)]
        elif cmd == "L": x, y = v; cur.append((x, y))
        elif cmd == "H": x = v[0]; cur.append((x, y))
        elif cmd == "V": y = v[0]; cur.append((x, y))
        elif cmd == "Z": polys.append(cur); cur = []
    ss = 8
    k = h * ss / 750.3
    half = int(np.ceil(300 * k / ss))  # the glyph spans x 52..652, centre 352
    w = (2 * half + 1) * ss            # odd pixel width, so the glyph centres on a pixel column
    im = Image.new("L", (w, h * ss), 0)
    d = ImageDraw.Draw(im)
    for i, p in enumerate(polys):  # path is in y-up font units; second subpath is the counter
        d.polygon([((px - 352) * k + w / 2, (750.3 - py) * k) for px, py in p], fill=255 if i == 0 else 0)
    a = np.asarray(im, float).reshape(h, ss, w // ss, ss).mean(axis=(1, 3))
    a = (a + a[:, ::-1]) / 2  # the mark is mirror-symmetric; keep its pixels so
    m = a > 110
    cols = np.where(m.any(0))[0]
    return m[:, cols[0]:cols[-1] + 1]


# ---------- sprite canvas ----------
class Sprite:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.col = np.zeros((h, w, 3), np.uint8)
        self.m = np.zeros((h, w), bool)
        self.flat = np.zeros((h, w), bool)  # pixels left unshaded (logos, numbers keep their edges)

    def _poly_mask(self, pts):
        im = Image.new("1", (self.w, self.h), 0)
        ImageDraw.Draw(im).polygon(pts, fill=1)
        return np.asarray(im, bool)

    def shape(self, pts, c):
        pm = self._poly_mask(pts)
        self.m |= pm
        self.col[pm] = c
        return pm

    def ellipse(self, box, c, add=True):
        im = Image.new("1", (self.w, self.h), 0)
        ImageDraw.Draw(im).ellipse(box, fill=1)
        pm = np.asarray(im, bool)
        if add: self.m |= pm
        self.col[pm & self.m] = c
        return pm

    def cut(self, pts):
        self.m &= ~self._poly_mask(pts)

    def paint(self, region, c, inside=True):
        r = region & self.m if inside else region
        if not inside: self.m |= region
        self.col[r] = c

    def rect(self, x0, y0, x1, y1, c, inside=True):
        r = np.zeros_like(self.m)
        r[max(0, y0):y1 + 1, max(0, x0):x1 + 1] = True
        self.paint(r, c, inside)

    def px(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h and self.m[y, x]:
            self.col[y, x] = c

    def bitmap(self, rows, x, y, c, flat=True):
        for j, row in enumerate(rows):
            for i, ch in enumerate(row):
                if ch == "#" and 0 <= x + i < self.w and 0 <= y + j < self.h and self.m[y + j, x + i]:
                    self.col[y + j, x + i] = c
                    if flat: self.flat[y + j, x + i] = True

    def word3(self, s, cx, y, c):
        """3x5 wordmark, for chests too narrow for the 4x7 one."""
        w = len(s) * 4 - 1
        for i, ch in enumerate(s):
            rows = ["".join("#" if b == "1" else "." for b in F3[ch][r * 3:r * 3 + 3]) for r in range(5)]
            self.bitmap(rows, cx - w // 2 + i * 4, y, c)

    def word(self, s, cx, y, c):
        w = len(s) * 5 - 1
        for i, ch in enumerate(s):
            self.bitmap(F4[ch], cx - w // 2 + i * 5, y, c)

    def number(self, s, cx, y, ink, ring, small=False):
        """Block numerals with a 1px ring; small uses the 3x5 font."""
        if small:
            rows = [["".join("#" if b == "1" else "." for b in F3[ch][r * 3:r * 3 + 3]) for r in range(5)] for ch in s]
            gw = 3
        else:
            rows = [F6[ch] for ch in s]
            gw = 6
        w = len(s) * (gw + 1) - 1
        x0 = cx - w // 2
        cells = set()
        for i, g in enumerate(rows):
            for j, row in enumerate(g):
                for k, ch in enumerate(row):
                    if ch == "#": cells.add((x0 + i * (gw + 1) + k, y + j))
        for (x, yy) in list(cells):
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    q = (x + dx, yy + dy)
                    if q not in cells and 0 <= q[0] < self.w and 0 <= q[1] < self.h and self.m[q[1], q[0]]:
                        self.col[q[1], q[0]] = ring
                        self.flat[q[1], q[0]] = True
        for (x, yy) in cells:
            if 0 <= x < self.w and 0 <= yy < self.h and self.m[yy, x]:
                self.col[yy, x] = ink
                self.flat[yy, x] = True

    def logo(self, cx, cy, h, c, ring=None):
        g = glyph_mask(h)
        gh, gw = g.shape
        x0, y0 = cx - gw // 2, cy - gh // 2
        if ring is not None:
            for y in range(gh):
                for x in range(gw):
                    if g[y, x]:
                        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                            X, Y = x0 + x + dx, y0 + y + dy
                            inside = 0 <= y + dy < gh and 0 <= x + dx < gw and g[y + dy, x + dx]
                            if not inside and 0 <= X < self.w and 0 <= Y < self.h and self.m[Y, X]:
                                self.col[Y, X] = ring
                                self.flat[Y, X] = True
        for y in range(gh):
            for x in range(gw):
                if g[y, x] and 0 <= x0 + x < self.w and 0 <= y0 + y < self.h and self.m[y0 + y, x0 + x]:
                    self.col[y0 + y, x0 + x] = c
                    self.flat[y0 + y, x0 + x] = True

    def edge(self, width=1):
        """Mask of inside pixels within `width` of the outside."""
        m = self.m
        e = np.zeros_like(m)
        cur = m.copy()
        for _ in range(width):
            p = np.pad(cur, 1)
            inner = cur & p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
            e |= cur & ~inner
            cur = inner
        return e

    def render(self, light=True):
        """RGBA image: lit from the top left, selective outline."""
        m, col = self.m, self.col.astype(int).copy()
        out = col.copy()
        if light:
            p = np.pad(m, 1)
            up, dn, lf, rt = p[:-2, 1:-1], p[2:, 1:-1], p[1:-1, :-2], p[1:-1, 2:]
            p2 = np.pad(m, 2)
            rt2, dn2 = p2[2:-2, 4:], p2[4:, 2:-2]
            hi = m & (~up | ~lf)
            sh = m & (~rt | ~dn | ~rt2 | ~dn2)
            # broad shadow band on the right of every row span, with a checker edge
            band = np.zeros_like(m)
            for y in range(self.h):
                xs = np.where(m[y])[0]
                if not len(xs): continue
                runs = np.split(xs, np.where(np.diff(xs) > 1)[0] + 1)
                for r in runs:
                    if len(r) < 6: continue
                    cut = r[0] + int(len(r) * .74)
                    band[y, cut + 1:r[-1] + 1] = True
                    if (y + cut) % 2 == 0: band[y, cut] = True
            for region, t in ((band & ~sh, -.14), (sh, -.26), (hi & ~sh, .2)):
                r = region & ~self.flat
                out[r] = [tone(tuple(c), t) for c in col[r]] if r.any() else out[r]
        img = np.zeros((self.h, self.w, 4), np.uint8)
        img[..., :3] = np.clip(out, 0, 255)
        img[..., 3] = m * 255
        # selective outline: a darker shade of the neighbouring colour
        p = np.pad(m, 1)
        ring = ~m & (p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:])
        ys, xs = np.where(ring)
        for y, x in zip(ys, xs):
            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                X, Y = x + dx, y + dy
                if 0 <= X < self.w and 0 <= Y < self.h and m[Y, X]:
                    img[y, x, :3] = tone(tuple(int(v) for v in col[Y, X]), -.72)
                    img[y, x, 3] = 255
                    break
        return img


def sym(cx, half):
    """Mirror a right-half outline (dx, y) from the top centre round to the bottom centre."""
    right = [(cx + dx, y) for dx, y in half]
    left = [(cx - dx, y) for dx, y in reversed(half)]
    return right + left


# ---------- the athlete ----------
# Body and garments are drawn in design units on a 44 x 100 figure (a 7.5-head athlete,
# about 6'2"), then scaled by S to pixels, so every piece is cut to the same body.
S = 1.6
DU_W, DU_H = 58, 100
DCX = 46.5 / 1.6  # body midline on the centre of pixel column 46, so centred art lands on it exactly
OX = DCX - 22  # the pieces below were laid out on a 22-centre grid
FW, FH = 93, int(DU_H * S) + 1  # 46 columns either side of the midline
SKIN = (166, 166, 178)  # mannequin grey


def U(pts):
    return [(x * S, y * S) for x, y in pts]


def M(half):
    """Symmetric outline in pixels from a right half given as (dx, y) design units."""
    return U(sym(DCX, half))


def R(right):
    """A right-side polygon (dx, y) and its mirror, in pixels."""
    return U([(DCX + dx, y) for dx, y in right]), U([(DCX - dx, y) for dx, y in right])


def E(x0, y0, x1, y1):
    """Ellipse box in pixels from design units on the 22-centre grid."""
    return ((x0 + OX) * S, y0 * S, (x1 + OX) * S, y1 * S)


def grid():
    Y, X = np.mgrid[0:FH, 0:FW]
    return np.abs(X + .5 - DCX * S) / S, (Y + .5) / S, (X + .5 - DCX * S) / S


ARM = [(10, 14.5), (13, 16), (15.6, 30), (17.6, 45), (15, 46), (12.6, 32), (10, 24)]
LEG = [(1, 49), (8.6, 49), (8.6, 60), (7.1, 72), (6.1, 90), (2, 90), (2, 72), (1, 60)]
FOOT = [(2, 90), (6.6, 90), (8.6, 94), (2, 94)]
HAND = (16.4, 47.6)  # (dx, y) of the hand centres


def mannequin():
    s = Sprite(FW, FH)
    s.ellipse(E(17, 1, 27, 13.5), SKIN)
    s.shape(M([(0, 12), (1.8, 12), (1.8, 16), (0, 16)]), SKIN)
    s.shape(M([(0, 14), (10, 14), (10.6, 16), (9.6, 30), (7.6, 44), (8.6, 50), (0, 50)]), SKIN)
    for part in (ARM, LEG, FOOT):
        for p in R(part): s.shape(p, SKIN)
    for sx in (1, -1):
        cx, cy = DCX + sx * 16.4, 47.6
        s.ellipse(((cx - 2) * S, (cy - 2) * S, (cx + 2) * S, (cy + 2) * S), SKIN)
    return s


JERSEY = {
    "football": [(0, 13.4), (5, 13.4), (12, 13.6), (16.6, 15.6), (18.1, 19), (18.6, 25), (13.1, 26.6),
                 (10.6, 25.6), (10.1, 30), (9.2, 47), (0, 47.5)],
    "basketball": [(0, 13.4), (4, 13.4), (7.1, 13.4), (7.6, 17), (9.1, 22), (10.1, 25), (9.7, 30), (8.7, 48), (0, 48.5)],
    "hockey": [(0, 13.4), (5, 13.1), (13.1, 13.6), (16.1, 16), (18.6, 30), (20.1, 45), (15.6, 46.6), (13.1, 33),
               (11.6, 26), (11.7, 30), (12.1, 54), (0, 54.5)],
    "soccer": [(0, 13.4), (4, 13.4), (11.1, 13.8), (13.6, 16), (15.6, 25), (16.1, 28), (12.6, 29.1), (11.1, 24),
               (10.2, 30), (9.7, 51), (0, 51.5)],
    "baseball": [(0, 13.4), (4, 13.4), (11.6, 14), (14.1, 16.5), (16.1, 26), (16.6, 30), (12.6, 31.1), (11.1, 25),
                 (10.4, 30), (10.1, 50), (0, 50.5)],
}
NECK = {  # (front, back) neck holes as right halves
    "football": ([(0, 12.5), (4.6, 12.5), (3.1, 15.5), (0, 16.6)], [(0, 12.5), (4.6, 12.5), (3.1, 14.2), (0, 14.8)]),
    "basketball": ([(0, 12.5), (4.1, 12.5), (3.6, 18), (0, 21)], [(0, 12.5), (4.1, 12.5), (3.6, 15.5), (0, 16.5)]),
    "hockey": ([(0, 12.5), (4.6, 12.5), (3.1, 15), (0, 15.6)], [(0, 12.5), (4.6, 12.5), (3.1, 14.2), (0, 14.6)]),
    "soccer": ([(0, 12.5), (3.6, 12.5), (0, 19)], [(0, 12.5), (3.6, 12.5), (2.6, 14.2), (0, 14.6)]),
    "baseball": ([(0, 12.5), (3.6, 12.5), (0, 20)], [(0, 12.5), (3.6, 12.5), (2.6, 14.2), (0, 14.6)]),
}
PANTS = {
    "football": [(0, 45), (9.1, 45), (9.9, 52), (9.6, 62), (9.3, 70.6), (1.3, 70.6), (0.8, 56), (0, 55)],
    "baseball": [(0, 45), (9.1, 45), (10.1, 52), (10.1, 66), (9.4, 80), (1.5, 80), (0.8, 57), (0, 56)],
    "hockey": [(0, 44), (10.1, 44), (11.6, 52), (11.9, 66), (1.5, 66.6), (0.8, 57), (0, 56)],
    "basketball": [(0, 45), (9.6, 45), (10.6, 55), (10.9, 68), (1.6, 68.6), (0.8, 59), (0, 58)],
    "soccer": [(0, 46), (9.1, 46), (10.1, 54), (10.3, 62), (1.5, 62.6), (0.8, 56.5), (0, 56)],
}
SOCK_TOP = {"football": 69, "baseball": 79, "hockey": 65, "soccer": 61, "basketball": 85}


def jersey(sport, back, kit):
    k = KITS[kit]
    base, trim, acc = k["base"], k["trim"], k["acc"]
    s = Sprite(FW, FH)
    s.shape(M(JERSEY[sport]), base)
    neck = NECK[sport][1 if back else 0]
    collar = [(dx * 1.45 + (0.6 if dx else 0), y + (1.1 if y > 13 else 0)) for dx, y in neck]
    s.paint(s._poly_mask(M(collar)), trim)
    s.cut(M(neck))
    ax, ay, sx = grid()
    sleeve = ax > 10.7
    if sport == "football":
        for y0, c in ((20, trim), (21.2, acc), (22.4, trim)):
            s.paint(sleeve & (ay >= y0) & (ay < y0 + .9), c)
    elif sport == "basketball":
        e = s.edge(2)
        s.paint(e & (ay < 27), trim)
        s.paint(s.edge(1) & (ay < 26) & (ay > 13.6), acc)
        s.paint((ay > 45) & (ay < 46.3), trim)
    elif sport == "hockey":
        for y0, c in ((36, trim), (37.6, acc), (39.2, trim)):
            s.paint((ax > 12.6) & (ay >= y0 + (ax - 14) * .3) & (ay < y0 + 1.2 + (ax - 14) * .3), c)
        for y0, c in ((47, trim), (48.6, acc), (50.2, trim)):
            s.paint((ax < 12.2) & (ay >= y0) & (ay < y0 + 1.3), c)
        s.paint((ay > 17) & (ay < 18.2), trim)  # shoulder yoke
        s.paint((ay >= 18.2) & (ay < 18.9), acc)
    elif sport == "soccer":
        s.paint((ax > 12) & (ay > 26.4 + (ax - 12) * .45), trim)
        if not back:  # shoulder-to-hip sash, a lighter shade of the base
            s.paint((np.abs(sx - (ay - 30) * .55) < 1.8) & (ay > 15), tone(base, .35) if kit != "alternate" else CHAR)
        s.paint(ay > 50.2, trim)
    else:
        s.paint((ax > 12) & (ay > 28.6 + (ax - 12) * .45), trim)
        s.paint((ax > 12) & (ay > 27.8 + (ax - 12) * .45) & (ay <= 28.6 + (ax - 12) * .45), acc)
        X = np.mgrid[0:FH, 0:FW][1]
        s.paint(((X - int(DCX * S)) % 4 == 2) & (ay > 14.5), tone(base, -.12) if kit != "alternate" else CHAR)
        if not back:
            s.paint((ax < .55) & (ay > 20) & ((ay < 20.8) | (ay > 25.6)), trim)  # placket, broken by the wordmark
    cx = int(round(DCX * S))
    n = NUMS[sport]
    P = lambda y: int(round(y * S))
    sm = TEAL if kit == "alternate" else k["ink"]  # 3x5 numbers go unringed: a ring fills their counters
    if back:
        top = {"basketball": 26.4, "hockey": 19.6}.get(sport, 16.2)
        s.word3("ARKNDJL", cx, P(top), k["word"])
        s.number(n, cx, P(top + 4.2), k["ink"], k["ring"])
    elif sport == "football":
        s.logo(cx, P(19), 7, k["word"])  # collar crest, centred under the V like a league shield
        s.number(n, cx, P(22.4), k["ink"], k["ring"])
        for sxx in (1, -1):
            s.number(n, cx + sxx * int(14.4 * S), P(16.4), sm, base, small=True)
    elif sport == "basketball":
        s.word3("ARKNDJL", cx, P(26.4), k["word"])
        s.number(n, cx, P(30.4), k["ink"], k["ring"])
    elif sport == "hockey":
        s.logo(cx, P(28.5), 17, k["word"], ring=acc)
        for y in range(P(13.4), P(16.6), 2):  # lace-up collar
            s.px(cx - 1, y, acc); s.px(cx, y + 1, acc)
    elif sport == "soccer":
        s.logo(cx + int(5 * S), P(19.6), 7, k["word"])
        s.word3("ARKNDJL", cx, P(25), k["ink"] if kit != "alternate" else k["word"])
    else:
        s.word3("ARKNDJL", cx, P(21), k["word"])
        s.rect(cx - 13, P(21) + 6, cx + 13, P(21) + 6, acc)
        s.number(n, cx - int(5 * S), P(26.5), k["ink"], k["ring"], small=True)
        if not back:
            for y in range(P(21) + 9, P(50), 7):
                s.px(cx, y, WHITE if kit != "home" else CHAR)
    if sport == "hockey":  # sleeve numbers on both upper arms, front and back
        for sxx in (1, -1):
            s.number(n, cx + sxx * int(round(14.4 * S)), P(21.5), sm, base, small=True)
    return s


def pants(sport, back, kit):
    k = KITS[kit]
    pc, pt = k["pants"], k["ptrim"]
    if sport in ("basketball", "soccer"):
        pc, pt = k["base"], k["trim"]
    if sport == "baseball" and kit == "away":
        pc = LGREY  # classic road grey
    if sport == "hockey":
        pc, pt = (CHAR, k["base"]) if kit != "alternate" else (BLACK, TEAL)
    s = Sprite(FW, FH)
    s.shape(M(PANTS[sport]), pc)
    ax, ay, sx = grid()
    top = PANTS[sport][0][1]
    s.paint(ay < top + 1.3, CHAR if sport in ("football", "baseball") else pt)  # belt / waistband
    cx = int(round(DCX * S))
    if sport == "football":
        s.paint((ax > 8.2) & (ax < 9) & (ay > top + 1.3), pt if kit != "home" else CHAR)
        s.paint((ax >= 9) & (ay > top + 1.3), k["acc"])
        if not back: s.logo(cx - int(5.5 * S), int((top + 4.5) * S), 5, pt if kit != "home" else CHAR)
    elif sport == "baseball":
        s.paint((ax > 8.9) & (ax < 9.7) & (ay > top + 1.3), pt if kit != "away" else CHAR)
        if kit == "home":
            X = np.mgrid[0:FH, 0:FW][1]
            s.paint(((X - cx) % 4 == 2) & (ay > top + 1.3), tone(pc, -.1))
    elif sport == "hockey":
        s.paint((ax > 9.8) & (ax < 11.2) & (ay > top + 1.3), pt)
        s.logo(cx - int(5.8 * S), int(56 * S), 7, pt)
    elif sport == "basketball":
        s.paint((ax > 9.2) & (ay > top + 1.3), k["trim"])
        s.paint((ax > 8.6) & (ax <= 9.2) & (ay > top + 1.3), k["acc"])
        s.paint(ay > 66.8, k["trim"])
        s.logo(cx - int(5.4 * S) if not back else cx + int(5.4 * S), int(59 * S), 6, k["word"])
    else:
        s.paint((ax > 9) & (ay > top + 1.3), k["acc"])
        if not back:
            s.number(NUMS[sport], cx + int(5.2 * S), int(55 * S), k["word"], k["base"], small=True)
    return s


def socks(sport, kit):
    k = KITS[kit]
    sc = WHITE if sport == "basketball" and kit != "alternate" else k["sock"]
    t = SOCK_TOP[sport]
    w = 9.4 if sport in ("hockey", "soccer") else 8.9
    s = Sprite(FW, FH)
    out = [(1.5, t), (w, t), (7.8, 72), (6.7, 90.4), (1.7, 90.4), (1.6, 72)]
    if t > 72:
        out = [(1.8, t), (6.9, t), (6.7, 90.4), (1.7, 90.4)]
    for p in R(out):
        s.shape(p, sc)
    ax, ay, sx = grid()
    trim = k["trim"] if kit != "alternate" else TEAL
    if sport == "soccer":
        s.paint(ay < t + 3, trim); s.paint((ay > t + 3.6) & (ay < t + 4.4), k["acc"])
    elif sport == "hockey":
        for y0, c in ((t + 3, trim), (t + 4.6, k["acc"]), (t + 6.2, trim)):
            s.paint((ay >= y0) & (ay < y0 + 1.2), c)
    elif sport == "football":
        s.paint((ay > t + 3) & (ay < t + 4.2), trim); s.paint((ay > t + 4.8) & (ay < t + 5.5), k["acc"])
    elif sport == "baseball":  # stirrups over white sanitaries
        s.paint(ay < t + 1, trim)
        s.paint((ay > 84) & (np.abs(ax - 4.2) < (ay - 84) * .45), WHITE)
    else:
        s.paint((ay > t + 1) & (ay < t + 1.9), trim)
    return s


def shoes(sport, kit):
    k = KITS[kit]
    sc = k["shoe"]
    s = Sprite(FW, FH)
    if sport == "hockey":
        for p in R([(1.6, 86), (7.1, 86), (7.6, 90), (9.6, 92), (9.6, 94), (1.6, 94)]): s.shape(p, sc)
        for p in R([(1.1, 95), (10.1, 95), (10.1, 96.6), (1.1, 96.6)]): s.shape(p, LGREY)
        for p in R([(2.6, 94), (3.4, 94), (3.4, 95), (2.6, 95)]): s.shape(p, GREY)
        for p in R([(8.4, 94), (9.2, 94), (9.2, 95), (8.4, 95)]): s.shape(p, GREY)
    else:
        top = 86.4 if sport == "basketball" else 89.4
        for p in R([(1.6, top), (6.9, top), (7.4, 91), (9.3, 92.2), (9.4, 94.9), (1.6, 94.9)]): s.shape(p, sc)
        ax, ay, sx = grid()
        sole = CHAR if sc not in (CHAR, BLACK) else GREY
        s.paint(ay > 93.8, sole)
        s.paint((ay > 91.6) & (ay < 92.5) & (ax > 4), k["acc"] if sc == BLACK else k["base"] if sport != "basketball" else k["base"])
    return s


def headwear(sport, back, kit):
    k = KITS[kit]
    s = Sprite(FW, FH)
    ax, ay, sx = grid()
    cx = int(round(DCX * S))
    tr = k["trim"] if kit != "alternate" else TEAL
    if sport == "football":
        s.ellipse(E(15.4, -0.2, 28.6, 14.6), k["shell"])
        s.paint((ax < 0.7) & (ay < 9), tr)
        s.paint((ax >= 0.7) & (ax < 1.3) & (ay < 8.6), k["acc"] if kit != "alternate" else LILAC)
        if back:
            pass
        else:
            s.paint((ay > 7.6) & (ax < 5.4), tone(SKIN, -.5))  # face opening behind the mask
            for y0 in (9.2, 11.8):
                s.paint((ay > y0) & (ay < y0 + .8) & (ax < 5.6), GREY)
            s.paint((np.abs(ax - 2.6) < .4) & (ay > 7.6), GREY)
            s.paint((ax > 5.4) & (ax < 6.4) & (ay > 7.4) & (ay < 13), tone(k["shell"], -.2))
    elif sport == "hockey":
        s.ellipse(E(16, -0.6, 28, 11), k["shell"])
        s.cut([(0, 8.6 * S), (FW, 8.6 * S), (FW, FH), (0, FH)])
        for p in R([(4.6, 6.6), (6.6, 6.6), (6.6, 10.4), (4.6, 10.4)]): s.shape(p, tone(k["shell"], -.18))
        s.paint((ay > 4.6) & (ay < 5.4), tr)
        if not back:
            s.shape(M([(0, 6.4), (4.4, 6.4), (4.4, 8.9), (0, 8.9)]), (186, 214, 224))  # visor
        else:
            s.logo(cx, int(2.6 * S), 5, tr)
    elif sport == "baseball":
        cap = k["cap"]
        s.ellipse(E(16.4, -0.6, 27.6, 10.4), cap)
        s.cut([(0, 6.8 * S), (FW, 6.8 * S), (FW, FH), (0, FH)])
        if back:
            s.shape(M([(0, 4.6), (1.8, 4.6), (1.8, 6.8), (0, 6.8)]), tone(cap, -.5))
        else:
            s.shape(M([(0, 6.4), (6.6, 6.4), (5.2, 8.6), (0, 8.6)]), tone(cap, .12))
            s.logo(cx, int(3.6 * S), 6, k["logo"])
    elif sport == "basketball":
        s.shape(M([(0, 3.6), (5.1, 3.6), (5.3, 5.3), (0, 5.3)]), tr)
    else:  # soccer: captain's armband on the left arm
        band = [(11, 18.8), (14, 19.2), (14.7, 22.4), (11.4, 22.1)]
        p = R(band)[0 if not back else 1]
        s.shape(p, tr)
    return s


SILVER = (214, 216, 226)


def limb(part, sign):
    """Pixel mask of a limb on the screen side `sign` (+1 right, -1 left)."""
    a, b = R(part)
    return Sprite(FW, FH)._poly_mask(a if sign > 0 else b)


def gear(sport, back, kit):
    """Gloves, sticks, bats, guards and jewellery, drawn over the uniform."""
    k = KITS[kit]
    s = Sprite(FW, FH)
    ax, ay, sx = grid()
    rs = 1 if back else -1  # screen side of the athlete's right hand
    hx = lambda sign: DCX + sign * HAND[0]
    hy = HAND[1]
    alt = kit == "alternate"
    hi = TEAL if alt else WHITE

    def glove(sign, c, r=2.4, cuff=None, cuff_c=None):
        if cuff:
            s.paint(limb(ARM, sign) & (ay > hy - cuff) & (ay < hy - 1), cuff_c or c, inside=False)
        s.ellipse(E(hx(sign) - OX - r, hy - r, hx(sign) - OX + r, hy + r), c)

    def band(part, sign, y0, y1, c):
        s.paint(limb(part, sign) & (ay >= y0) & (ay < y1), c, inside=False)

    def bar(p0, p1, w0, w1, c):
        """A tapered rod from p0 to p1 in design units (x absolute on the DCX grid)."""
        (x0, y0), (x1, y1) = p0, p1
        dx, dy = x1 - x0, y1 - y0
        n = (dx * dx + dy * dy) ** .5
        nx, ny = -dy / n, dx / n
        pts = [(x0 + nx * w0 / 2, y0 + ny * w0 / 2), (x1 + nx * w1 / 2, y1 + ny * w1 / 2),
               (x1 - nx * w1 / 2, y1 - ny * w1 / 2), (x0 - nx * w0 / 2, y0 - ny * w0 / 2)]
        return s.shape(U(pts), c)

    def chain(drop, pendant=True):
        for i in range(13):
            dx = -4.2 + i * .7
            y = 13.4 + (4.2 - abs(dx)) * drop
            x = int(round((DCX + dx) * S)); yy = int(round(y * S))
            if 0 <= x < FW and 0 <= yy < FH and i % 2 == 0 and not (back and y > 14.6):
                s.m[yy, x] = True; s.col[yy, x] = SILVER; s.flat[yy, x] = True
        if pendant and not back:
            cy = 13.4 + 4.2 * drop + 1.6
            s.ellipse(E(22 - 1.3, cy - 1.3, 22 + 1.3, cy + 1.3), SILVER)
            s.px(int(round(DCX * S)), int(round(cy * S)), TEAL if kit != "away" else LILAC)

    if sport == "football":
        gc = k["base"] if not alt else TEAL
        for sign in (1, -1):
            band(ARM, sign, 42.6, 44.4, hi)  # wristbands
            glove(sign, gc, 2.5)
        band(ARM, -rs, 27, 42.6, BLACK if not alt else LILAC)  # one arm sleeve
        if not back:  # towel tucked at the waist and a tinted eye shield
            s.shape(U([(DCX - 6.4, 46), (DCX - 3.6, 46), (DCX - 3.4, 54.5), (DCX - 6.6, 54.5)]), WHITE)
            s.paint((ay > 52.4) & (ay < 53.4), k["acc"] if not alt else TEAL)
            s.shape(M([(0, 7.4), (5, 7.4), (4.6, 9), (0, 9)]), (62, 92, 98))
            s.paint((ay < 8) & (ax > 2) & (ax < 4), (120, 170, 170))
    elif sport == "basketball":
        band(ARM, -rs, 17, 44, BLACK if not alt else LILAC)  # shooting sleeve
        for sign in (1, -1):
            band(ARM, sign, 42, 44.6, k["trim"] if not alt else TEAL)
        band(LEG, rs, 66, 77, BLACK if not alt else GREY)  # knee sleeve
        chain(1.05)
    elif sport == "hockey":
        for sign in (1, -1):
            glove(sign, k["base"] if not alt else BLACK, 3.1, cuff=6.5, cuff_c=CHAR if not alt else TEAL)
        # stick in the right hand: shaft to the ice, blade out
        top, foot = (hx(rs) - rs * .6, 33), (hx(rs) + rs * 2.6, 93.2)
        bar(top, foot, 1.3, 1.3, BLACK if not alt else CHAR)
        bar((foot[0] - rs * .4, 94.2), (foot[0] + rs * 7.6, 94.6), 2.2, 2.6, BLACK if not alt else CHAR)
        bar((foot[0] + rs * 1.2, 94.3), (foot[0] + rs * 6.4, 94.6), 2.3, 2.7, WHITE)  # blade tape
        bar(top, (top[0] + rs * .15, 35.4), 1.6, 1.6, WHITE)  # knob tape
        s.paint((np.abs(ay - 70) < .6) & s.m, k["base"] if not alt else TEAL)
    elif sport == "soccer":
        for sign in (1, -1):
            band(LEG, sign, 86.4, 88.6, WHITE)  # ankle tape
        band(ARM, -rs, 43, 44.6, k["acc"])
    else:  # baseball, dressed as a hitter
        gc = WHITE if not alt else TEAL
        for sign in (1, -1):
            glove(sign, gc, 2.4, cuff=2.6, cuff_c=k["cap"] if not alt else LILAC)
        # leg guard on the front shin, elbow guard on the lead arm
        s.paint(limb(LEG, -rs) & (ay > 74) & (ay < 86), k["cap"] if not alt else CHAR, inside=False)
        s.paint(limb(LEG, -rs) & (ay > 74) & (ay < 75.2), k["base"] if not alt else TEAL)
        band(ARM, -rs, 31, 36, k["cap"] if not alt else CHAR)
        band(ARM, -rs, 33.2, 34, k["base"] if not alt else TEAL)
        # bat hanging from the right hand, barrel to the ground
        knob = (hx(rs), hy - 1.6)
        bar(knob, (knob[0] + rs * 4.4, 88), 1.1, 2.6, BLACK if not alt else CHAR)
        bar((knob[0] + rs * 3.3, 70), (knob[0] + rs * 3.45, 71.6), 2.2, 2.2, k["base"] if not alt else TEAL)
        chain(.9)
        if back:  # fielding glove in the back pocket
            gx = 22 - rs * 5.4
            s.ellipse(E(gx - 2.8, 47.5, gx + 2.8, 54.5), (58, 52, 50))
            s.paint((np.abs(ay - 51) < .5) & s.m, LILAC if not alt else TEAL)
    return s


ORDER = {  # draw order, bottom to top: tucked jerseys go under the pants
    "football": ["socks", "shoes", "jersey", "pants", "head"],
    "baseball": ["socks", "shoes", "jersey", "pants", "head"],
    "basketball": ["socks", "shoes", "jersey", "pants", "head"],
    "hockey": ["socks", "shoes", "pants", "jersey", "head"],
    "soccer": ["socks", "shoes", "pants", "jersey", "head"],
}


def layers(sport, back, kit):
    make = {"jersey": lambda: jersey(sport, back, kit), "pants": lambda: pants(sport, back, kit),
            "socks": lambda: socks(sport, kit), "shoes": lambda: shoes(sport, kit),
            "head": lambda: headwear(sport, back, kit), "gear": lambda: gear(sport, back, kit)}
    return [mannequin()] + [make[n]() for n in ORDER[sport] + ["gear"]]


def figure(sport, back, kit, light=True):
    """The athlete in the full uniform as one RGBA image."""
    img = np.zeros((FH + 2, FW + 2, 4), np.uint8)
    for s in layers(sport, back, kit):
        paste(img, s.render(light), 1, 1)
    return img


# ---------- cards ----------
def text3(img, s, cx, y, c, k=1):
    w = (len(s) * 4 - 1) * k
    x0 = cx - w // 2
    for i, ch in enumerate(s):
        bits = F3[ch]
        for r in range(5):
            for q in range(3):
                if bits[r * 3 + q] == "1":
                    img[y + r * k:y + r * k + k, x0 + (i * 4 + q) * k:x0 + (i * 4 + q) * k + k, :3] = c
                    img[y + r * k:y + r * k + k, x0 + (i * 4 + q) * k:x0 + (i * 4 + q) * k + k, 3] = 255


def backdrop(w, h):
    img = np.zeros((h, w, 4), np.uint8)
    img[..., :3] = BG
    img[..., 3] = 255
    yy, xx = np.mgrid[0:h, 0:w]
    img[((xx + yy) % 8 == 0) & (yy % 4 == 0), :3] = BG2
    return img


def paste(dst, src, x, y):
    h, w = src.shape[:2]
    a = src[..., 3:] > 0
    dst[y:y + h, x:x + w] = np.where(a, src, dst[y:y + h, x:x + w])


def sport_card(sport):
    figs = [[figure(sport, b, kit) for b in (False, True)] for kit in KITS]
    fw = max(f.shape[1] for pair in figs for f in pair)
    fh = max(f.shape[0] for pair in figs for f in pair)
    gap, pair_gap = 4, 16
    W = 3 * (2 * fw + gap) + 2 * pair_gap + 24
    H = fh + 52
    img = backdrop(W, H)
    text3(img, "ARKNDJL", W // 2, 5, LILAC, 2)
    text3(img, sport.upper(), W // 2, 18, TEAL)
    for i, kit in enumerate(KITS):
        x0 = 12 + i * (2 * fw + gap + pair_gap)
        for j, f in enumerate(figs[i]):
            paste(img, f, x0 + j * (fw + gap) + (fw - f.shape[1]) // 2, 28)
        text3(img, kit.upper(), x0 + fw + gap // 2, H - 14, LILAC)
        text3(img, "FRONT   BACK", x0 + fw + gap // 2, H - 7, GREY)
    return img


def lineup(kit="home"):
    figs = [figure(s, False, kit) for s in SPORTS]
    fw = max(f.shape[1] for f in figs)
    fh = max(f.shape[0] for f in figs)
    W = 5 * (fw + 6) + 18
    H = fh + 46
    img = backdrop(W, H)
    text3(img, "ARKNDJL", W // 2, 5, LILAC, 2)
    text3(img, kit.upper() + " UNIFORMS", W // 2, 18, TEAL)
    for i, f in enumerate(figs):
        x = 12 + i * (fw + 6)
        paste(img, f, x + (fw - f.shape[1]) // 2, 28)
        text3(img, SPORTS[i].upper(), x + fw // 2, H - 9, LILAC)
    return img


def specimen():
    """Brand-guide type sheet: the wordmark, the 3x5 label face and the block numerals with their ring."""
    W, H = 200, 84
    img = backdrop(W, H)
    sp = Sprite(W, H)
    sp.m[:] = True
    sp.col[:] = BG
    sp.word("ARKNDJL", W // 2, 6, LILAC)
    for i, c in enumerate((LILAC, TEAL, WHITE)):
        sp.number("0123456789"[i * 4:i * 4 + 4], 40 + i * 60, 46, CHAR if i < 2 else BLACK, c)
    out = sp.col.copy()
    img[..., :3] = np.where(sp.flat[..., None], out, img[..., :3])
    text3(img, "ABCDEFGHIJKLMNOPRSTUVWY", W // 2, 20, TEAL)
    text3(img, "0137 / -", W // 2, 28, GREY)
    # numerals sit on a swatch of the kit they go on
    for i, c in enumerate((LILAC, TEAL, BLACK)):
        x0 = 40 + i * 60 - 15
        sub = img[42:58, x0:x0 + 30, :3]
        m = ~sp.flat[42:58, x0:x0 + 30]
        sub[m] = c
    return img


def anatomy():
    """Home football and baseball, front and back, for the brand guide."""
    figs = [figure("football", False, "home"), figure("football", True, "home"),
            figure("baseball", False, "home"), figure("baseball", True, "home")]
    fw, fh = figs[0].shape[1], figs[0].shape[0]
    W, H = 4 * fw + 20, fh + 8
    img = backdrop(W, H)
    for i, f in enumerate(figs):
        paste(img, f, 4 + i * (fw + 4), 4)
    return img


def save(img, path, scale=4):
    Image.fromarray(img).resize((img.shape[1] * scale, img.shape[0] * scale), Image.NEAREST).save(path, optimize=True)


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static", "img", "art")
    for s in SPORTS:
        save(sport_card(s), os.path.join(out, f"arkndjl-uniform-{s}.png"))
    save(lineup(), os.path.join(out, "arkndjl-uniform-lineup.png"))
    for kit in ("away", "alternate"):
        save(lineup(kit), os.path.join(out, f"arkndjl-uniform-lineup-{kit}.png"))
    save(specimen(), os.path.join(out, "arkndjl-uniform-type.png"))
    save(anatomy(), os.path.join(out, "arkndjl-uniform-anatomy.png"), 3)
    print("ok")
