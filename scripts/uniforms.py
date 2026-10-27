"""ARKNDJL full uniforms as pixel art: headwear, jersey, pants or shorts, socks and shoes.

Five sports, four kits each (lilac home, grey road, black-and-lilac alternate,
aquamarine alternate 2), drawn front and back. Colours are lilac and aquamarine with
white, grey and black only. The site glyph is the team logo. All lettering is the site
font, MS PGothic's 16px bitmap strike (static/fonts/mspgothic-pixel.woff2), at 1:1 pixels. Every piece is a sprite: flat colour regions,
then lit from the top left (highlight rim, shadow band with a dithered edge) and
ringed with a selective outline (a darker shade of the colour it borders).

Sprites feed two outputs:
  scripts/uniforms.py   pixel uniform cards  -> static/img/art/arkndjl-uniform-<sport>.png, -lineup.png
  scripts/jersey_ps1.py low-poly figures      -> static/img/art/arkndjl-ps1-<sport>.gif, -lineup.gif
"""
import io, os, re
import numpy as np
from PIL import Image, ImageDraw

LILAC, TEAL, WHITE = (200, 199, 255), (127, 255, 212), (240, 240, 246)
ROAD = (158, 158, 168)  # road grey, the away base
LGREY, GREY, CHAR, BLACK = (192, 192, 202), (140, 140, 150), (48, 48, 56), (24, 24, 28)
BG, BG2 = (28, 28, 33), (36, 36, 42)

KITS = {  # Noah's picks, Oct 27 2026: H1 home, R3 road, L1 alternate, R4 second alternate
    "home": dict(role="home", label="HOME", base=LILAC, trim=CHAR, acc=TEAL, ink=CHAR, ring=WHITE, word=CHAR,
                 pants=WHITE, ptrim=LILAC, sock=LILAC, shoe=WHITE, shell=LILAC, cap=CHAR, logo=LILAC),
    "away": dict(role="road", label="ROAD", base=ROAD, trim=CHAR, acc=TEAL, ink=LILAC, ring=CHAR, word=CHAR,
                 pants=ROAD, ptrim=TEAL, sock=ROAD, shoe=WHITE, shell=ROAD, cap=CHAR, logo=TEAL),
    "alternate": dict(role="alt", label="ALTERNATE", dark=True, base=BLACK, trim=LILAC, acc=TEAL, ink=LILAC, ring=CHAR,
                      word=LILAC, pants=BLACK, ptrim=LILAC, sock=BLACK, shoe=BLACK, shell=BLACK, cap=BLACK, logo=LILAC),
    "alternate-2": dict(role="alt2", label="ALTERNATE 2", base=TEAL, trim=CHAR, acc=LILAC, ink=CHAR, ring=WHITE, word=CHAR,
                        pants=WHITE, ptrim=TEAL, sock=TEAL, shoe=WHITE, shell=TEAL, cap=CHAR, logo=TEAL),
}
NUMS = {"football": "11", "basketball": "1", "hockey": "31", "soccer": "10", "baseball": "7"}
SPORTS = ["football", "basketball", "hockey", "soccer", "baseball"]


def tone(c, t):
    """t > 0 toward white, t < 0 toward a cool near-black."""
    tgt = (255, 255, 255) if t > 0 else (12, 12, 18)
    return tuple(int(round(a + (b - a) * abs(t))) for a, b in zip(c, tgt))


# ---------- fonts ----------
# ---------- lettering: the site font ----------
FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static", "fonts", "mspgothic-pixel.woff2")
_GLYPHS = {}


def _font():
    if "font" not in _GLYPHS:
        from fontTools.ttLib import TTFont
        from PIL import ImageFont
        f = TTFont(FONT)
        f.flavor = None
        buf = io.BytesIO()
        f.save(buf)
        buf.seek(0)
        _GLYPHS["font"] = ImageFont.truetype(buf, 16)  # the strike's native size: one font pixel per pixel
    return _GLYPHS["font"]


def glyph(ch):
    """Boolean bitmap of one character: cap-height rows (11), trimmed to its ink."""
    if ch not in _GLYPHS:
        f = _font()
        im = Image.new("L", (24, 18), 0)
        ImageDraw.Draw(im).text((2, 0), ch, font=f, fill=255)
        a = np.asarray(im) > 127
        a = a[3:14]
        cols = np.where(a.any(0))[0]
        _GLYPHS[ch] = a[:, cols[0]:cols[-1] + 1] if len(cols) else np.zeros((11, 3), bool)
    return _GLYPHS[ch]


def lettering(s, gap=1, scale=1):
    """Bitmap of a string in the site font: glyphs joined with `gap` pixels, then scaled up."""
    parts = []
    for i, ch in enumerate(s):
        g = glyph(ch)
        parts.append(g)
        if i < len(s) - 1:
            parts.append(np.zeros((11, gap), bool))
    m = np.concatenate(parts, axis=1)
    return np.kron(m, np.ones((scale, scale), bool)) if scale > 1 else m


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

    def stamp(self, m, x0, y, c):
        for j, i in zip(*np.where(m)):
            X, Y = x0 + i, y + j
            if 0 <= X < self.w and 0 <= Y < self.h and self.m[Y, X]:
                self.col[Y, X] = c
                self.flat[Y, X] = True

    def word(self, s, cx, y, c):
        """Wordmark in the site font, centred on cx; returns its pixel width."""
        m = lettering(s)
        self.stamp(m, cx - m.shape[1] // 2, y, c)
        return m.shape[1]

    def number(self, s, cx, y, ink, ring, small=False):
        """Numbers in the site font: 2x with a 1px ring, or 1x unringed when small."""
        if small:
            m = lettering(s)
        else:  # body numbers: the font's strokes doubled sideways (its bold), then 2x
            m = lettering(s, gap=2)
            m = np.pad(m, ((0, 0), (0, 1)))
            m = m | np.roll(m, 1, 1)
            m = np.kron(m, np.ones((2, 2), bool))
        x0 = cx - m.shape[1] // 2
        if not small:
            p = np.pad(m, 1)
            halo = np.zeros_like(p)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    halo |= np.roll(np.roll(p, dy, 0), dx, 1)
            self.stamp(halo & ~p, x0 - 1, y - 1, ring)
        self.stamp(m, x0, y, ink)

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
S = 3.2
DU_W, DU_H = 58, 100
DCX = 92.5 / 3.2  # body midline on the centre of pixel column 92, so centred art lands on it exactly
OX = DCX - 22  # the pieces below were laid out on a 22-centre grid
FW, FH = 185, int(DU_H * S) + 1  # 92 columns either side of the midline
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
    "basketball": [(0, 13.4), (4, 13.4), (7.1, 13.4), (7.8, 17), (9.8, 22), (11.2, 25.5), (10.8, 31), (9.4, 48), (0, 48.5)],
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
        e = s.edge(4)
        s.paint(e & (ay < 27), trim)
        s.paint(s.edge(2) & (ay < 26) & (ay > 13.6), acc)
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
            s.paint((np.abs(sx - (ay - 30) * .55) < 1.8) & (ay > 15), tone(base, .35) if not k.get("dark") else CHAR)
        s.paint(ay > 50.2, trim)
    else:
        s.paint((ax > 12) & (ay > 28.6 + (ax - 12) * .45), trim)
        s.paint((ax > 12) & (ay > 27.8 + (ax - 12) * .45) & (ay <= 28.6 + (ax - 12) * .45), acc)
        X = np.mgrid[0:FH, 0:FW][1]
        s.paint(((X - int(DCX * S)) % 8 == 4) & (ay > 14.5), tone(base, -.12) if not k.get("dark") else CHAR)
        if not back:
            s.paint((ax < .55) & (ay > 20) & ((ay < 20.8) | (ay > 25.6)), trim)  # placket, broken by the wordmark
    cx = int(round(DCX * S))
    n = NUMS[sport]
    P = lambda y: int(round(y * S))
    sm = k["trim"] if k.get("dark") else k["ink"]  # 3x5 numbers go unringed: a ring fills their counters
    if back:
        top = {"basketball": 26.4, "hockey": 19.6}.get(sport, 16.2)
        s.word("ARKNDJL", cx, P(top), k["word"])
        s.number(n, cx, P(top + 4.2), k["ink"], k["ring"])
    elif sport == "football":
        s.logo(cx, P(19), 14, k["word"])  # collar crest, centred under the V like a league shield
        s.number(n, cx, P(22.4), k["ink"], k["ring"])
        for sxx in (1, -1):
            s.number(n, cx + sxx * int(14.4 * S), P(16.4), sm, base, small=True)
    elif sport == "basketball":
        s.word("ARKNDJL", cx, P(26.4), k["word"])
        s.number(n, cx, P(30.4), k["ink"], k["ring"])
    elif sport == "hockey":
        s.logo(cx, P(28.5), 34, k["word"], ring=acc)
        for y in range(P(13.4), P(16.6), 4):  # lace-up collar
            for d in (0, 1):
                s.px(cx - 2 + d, y + d, acc); s.px(cx + 2 - d, y + d, acc)
    elif sport == "soccer":
        s.logo(cx + int(5 * S), P(19.6), 14, k["word"])
        s.word("ARKNDJL", cx, P(25), k["ink"] if not k.get("dark") else k["word"])
    else:
        ww = s.word("ARKNDJL", cx, P(21), k["word"])
        s.rect(cx - ww // 2, P(21) + 12, cx - ww // 2 + ww - 1, P(21) + 13, acc)
        s.number(n, cx - int(5 * S), P(26.5), k["ink"], k["ring"], small=True)
        if not back:
            for y in range(P(21) + 18, P(50), 12):
                s.px(cx, y, WHITE if k["role"] != "home" else CHAR)
    if sport == "hockey":  # sleeve numbers on both upper arms, front and back
        for sxx in (1, -1):
            s.number(n, cx + sxx * int(round(14.4 * S)), P(21.5), sm, base, small=True)
    return s


def pants(sport, back, kit):
    k = KITS[kit]
    pc, pt = k["pants"], k["ptrim"]
    if sport in ("basketball", "soccer"):
        pc, pt = k["base"], k["trim"]
    if sport == "baseball" and k["role"] == "road":
        pc = ROAD  # road greys top to bottom
    if sport == "hockey":
        pc, pt = (CHAR, k["base"]) if not k.get("dark") else (BLACK, LILAC)
    s = Sprite(FW, FH)
    s.shape(M(PANTS[sport]), pc)
    ax, ay, sx = grid()
    top = PANTS[sport][0][1]
    s.paint(ay < top + 1.3, CHAR if sport in ("football", "baseball") else pt)  # belt / waistband
    cx = int(round(DCX * S))
    if sport == "football":
        s.paint((ax > 8.2) & (ax < 9) & (ay > top + 1.3), pt if k["role"] != "home" else CHAR)
        s.paint((ax >= 9) & (ay > top + 1.3), k["acc"])
        if not back: s.logo(cx - int(5.5 * S), int((top + 4.5) * S), 10, pt if k["role"] != "home" else CHAR)
    elif sport == "baseball":
        s.paint((ax > 8.9) & (ax < 9.7) & (ay > top + 1.3), pt if k["role"] != "road" else CHAR)
        if k["role"] == "home":
            X = np.mgrid[0:FH, 0:FW][1]
            s.paint(((X - cx) % 8 == 4) & (ay > top + 1.3), tone(pc, -.1))
    elif sport == "hockey":
        s.paint((ax > 9.8) & (ax < 11.2) & (ay > top + 1.3), pt)
        s.logo(cx - int(5.8 * S), int(56 * S), 14, pt)
    elif sport == "basketball":
        s.paint((ax > 9.2) & (ay > top + 1.3), k["trim"])
        s.paint((ax > 8.6) & (ax <= 9.2) & (ay > top + 1.3), k["acc"])
        s.paint(ay > 66.8, k["trim"])
        s.logo(cx - int(5.4 * S) if not back else cx + int(5.4 * S), int(59 * S), 12, k["word"])
    else:
        s.paint((ax > 9) & (ay > top + 1.3), k["acc"])
        if not back:
            s.number(NUMS[sport], cx + int(5.2 * S), int(55 * S), k["word"], k["base"], small=True)
    return s


def socks(sport, kit):
    k = KITS[kit]
    sc = WHITE if sport == "basketball" and not k.get("dark") else k["sock"]
    t = SOCK_TOP[sport]
    w = 9.4 if sport in ("hockey", "soccer") else 8.9
    s = Sprite(FW, FH)
    out = [(1.5, t), (w, t), (7.8, 72), (6.7, 90.4), (1.7, 90.4), (1.6, 72)]
    if t > 72:
        out = [(1.8, t), (6.9, t), (6.7, 90.4), (1.7, 90.4)]
    for p in R(out):
        s.shape(p, sc)
    ax, ay, sx = grid()
    trim = k["trim"] if not k.get("dark") else k["trim"]
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
    tr = k["trim"] if not k.get("dark") else k["trim"]
    if sport == "football":
        s.ellipse(E(15.4, -0.2, 28.6, 14.6), k["shell"])
        s.paint((ax < 0.7) & (ay < 9), tr)
        s.paint((ax >= 0.7) & (ax < 1.3) & (ay < 8.6), k["acc"] if not k.get("dark") else k["trim"])
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
            s.logo(cx, int(2.6 * S), 10, tr)
    elif sport == "baseball":
        cap = k["cap"]
        s.ellipse(E(16.4, -0.6, 27.6, 10.4), cap)
        s.cut([(0, 6.8 * S), (FW, 6.8 * S), (FW, FH), (0, FH)])
        if back:
            s.shape(M([(0, 4.6), (1.8, 4.6), (1.8, 6.8), (0, 6.8)]), tone(cap, -.5))
        else:
            s.shape(M([(0, 6.4), (6.6, 6.4), (5.2, 8.6), (0, 8.6)]), tone(cap, .12))
            s.logo(cx, int(3.6 * S), 12, k["logo"])
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
    alt = k.get("dark")
    hi = k["trim"] if alt else WHITE

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
            s.px(int(round(DCX * S)), int(round(cy * S)), TEAL)

    if sport == "football":
        gc = k["base"] if not alt else k["trim"]
        for sign in (1, -1):
            band(ARM, sign, 42.6, 44.4, hi)  # wristbands
            glove(sign, gc, 2.5)
        band(ARM, -rs, 27, 42.6, BLACK if not alt else k["acc"])  # one arm sleeve
        if not back:  # towel tucked at the waist and a tinted eye shield
            s.shape(U([(DCX - 6.4, 46), (DCX - 3.6, 46), (DCX - 3.4, 54.5), (DCX - 6.6, 54.5)]), WHITE)
            s.paint((ay > 52.4) & (ay < 53.4), k["acc"] if not alt else k["trim"])
            s.shape(M([(0, 7.4), (5, 7.4), (4.6, 9), (0, 9)]), (62, 92, 98))
            s.paint((ay < 8) & (ax > 2) & (ax < 4), (120, 170, 170))
    elif sport == "basketball":
        band(ARM, -rs, 17, 44, BLACK if not alt else k["acc"])  # shooting sleeve
        for sign in (1, -1):
            band(ARM, sign, 42, 44.6, k["trim"] if not alt else k["trim"])
        band(LEG, rs, 66, 77, BLACK if not alt else GREY)  # knee sleeve
        chain(1.05)
    elif sport == "hockey":
        for sign in (1, -1):
            glove(sign, k["base"] if not alt else BLACK, 3.1, cuff=6.5, cuff_c=CHAR if not alt else k["trim"])
        # stick in the right hand: shaft to the ice, blade out
        top, foot = (hx(rs) - rs * .6, 33), (hx(rs) + rs * 2.6, 93.2)
        bar(top, foot, 1.3, 1.3, BLACK if not alt else CHAR)
        bar((foot[0] - rs * .4, 94.2), (foot[0] + rs * 7.6, 94.6), 2.2, 2.6, BLACK if not alt else CHAR)
        bar((foot[0] + rs * 1.2, 94.3), (foot[0] + rs * 6.4, 94.6), 2.3, 2.7, WHITE)  # blade tape
        bar(top, (top[0] + rs * .15, 35.4), 1.6, 1.6, WHITE)  # knob tape
        s.paint((np.abs(ay - 70) < .6) & s.m, k["base"] if not alt else k["trim"])
    elif sport == "soccer":
        for sign in (1, -1):
            band(LEG, sign, 86.4, 88.6, WHITE)  # ankle tape
        band(ARM, -rs, 43, 44.6, k["acc"])
    else:  # baseball, dressed as a hitter
        gc = WHITE if not alt else k["trim"]
        for sign in (1, -1):
            glove(sign, gc, 2.4, cuff=2.6, cuff_c=k["cap"] if not alt else k["trim"])
        # leg guard on the front shin, elbow guard on the lead arm
        s.paint(limb(LEG, -rs) & (ay > 74) & (ay < 86), k["cap"] if not alt else CHAR, inside=False)
        s.paint(limb(LEG, -rs) & (ay > 74) & (ay < 75.2), k["base"] if not alt else k["trim"])
        band(ARM, -rs, 31, 36, k["cap"] if not alt else CHAR)
        band(ARM, -rs, 33.2, 34, k["base"] if not alt else k["trim"])
        # bat hanging from the right hand, barrel to the ground
        knob = (hx(rs), hy - 1.6)
        bar(knob, (knob[0] + rs * 4.4, 88), 1.1, 2.6, BLACK if not alt else CHAR)
        bar((knob[0] + rs * 3.3, 70), (knob[0] + rs * 3.45, 71.6), 2.2, 2.2, k["base"] if not alt else k["trim"])
        chain(.9)
        if back:  # fielding glove in the back pocket
            gx = 22 - rs * 5.4
            s.ellipse(E(gx - 2.8, 47.5, gx + 2.8, 54.5), (58, 52, 50))
            s.paint((np.abs(ay - 51) < .5) & s.m, LILAC if not alt else k["trim"])
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
def text(img, s, cx, y, c, k=1):
    """Card label in the site font, centred on cx, k-times pixel size."""
    m = lettering(s, scale=k)
    x0 = cx - m.shape[1] // 2
    ys, xs = np.where(m)
    img[y + ys, x0 + xs, :3] = c
    img[y + ys, x0 + xs, 3] = 255


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
    gap, pair_gap = 8, 32
    W = len(KITS) * (2 * fw + gap) + (len(KITS) - 1) * pair_gap + 48
    H = fh + 100
    img = backdrop(W, H)
    text(img, "ARKNDJL", W // 2, 10, LILAC, 2)
    text(img, sport.upper(), W // 2, 38, TEAL)
    for i, kit in enumerate(KITS):
        x0 = 24 + i * (2 * fw + gap + pair_gap)
        for j, f in enumerate(figs[i]):
            paste(img, f, x0 + j * (fw + gap) + (fw - f.shape[1]) // 2, 56)
        text(img, KITS[kit]["label"], x0 + fw + gap // 2, H - 34, LILAC)
        text(img, "FRONT", x0 + fw // 2, H - 18, GREY)
        text(img, "BACK", x0 + fw + gap + fw // 2, H - 18, GREY)
    return img


def lineup(kit="home"):
    figs = [figure(s, False, kit) for s in SPORTS]
    fw = max(f.shape[1] for f in figs)
    fh = max(f.shape[0] for f in figs)
    W = 5 * (fw + 12) + 36
    H = fh + 86
    img = backdrop(W, H)
    text(img, "ARKNDJL", W // 2, 10, LILAC, 2)
    text(img, KITS[kit]["label"] + " UNIFORMS", W // 2, 38, TEAL)
    for i, f in enumerate(figs):
        x = 24 + i * (fw + 12)
        paste(img, f, x + (fw - f.shape[1]) // 2, 56)
        text(img, SPORTS[i].upper(), x + fw // 2, H - 22, LILAC)
    return img


def specimen():
    """Brand-guide type sheet: the site font as wordmark, labels and each kit's numbers."""
    W, H = 400, 150
    img = backdrop(W, H)
    text(img, "ARKNDJL", W // 2, 10, LILAC, 2)
    text(img, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", W // 2, 44, TEAL)
    text(img, "HOME  ROAD  ALTERNATE  0123456789", W // 2, 62, GREY)
    sp = Sprite(W, H)
    sp.m[:] = True
    sp.col[:] = BG
    for i, kit in enumerate(KITS):  # each kit's numbers on a swatch of its base
        cx = 50 + i * 100
        sp.rect(cx - 40, 86, cx + 39, 135, KITS[kit]["base"])
        sp.number(("0123", "45", "67", "89")[i], cx, 100, KITS[kit]["ink"], KITS[kit]["ring"])
    band = np.zeros((H, W), bool)
    band[86:136] = True
    img[band, :3] = sp.col[band]
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


def save(img, path, scale=2):
    Image.fromarray(img).resize((img.shape[1] * scale, img.shape[0] * scale), Image.NEAREST).save(path, optimize=True)


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static", "img", "art")
    for s in SPORTS:
        save(sport_card(s), os.path.join(out, f"arkndjl-uniform-{s}.png"))
    save(lineup(), os.path.join(out, "arkndjl-uniform-lineup.png"))
    for kit in ("away", "alternate", "alternate-2"):
        save(lineup(kit), os.path.join(out, f"arkndjl-uniform-lineup-{kit}.png"))
    save(specimen(), os.path.join(out, "arkndjl-uniform-type.png"))
    save(anatomy(), os.path.join(out, "arkndjl-uniform-anatomy.png"))
    print("ok")
