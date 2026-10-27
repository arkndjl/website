"""Pixel-art ARKNDJL jersey mockups (football, basketball, hockey, soccer, baseball) as crisp SVGs.

Writes static/img/art/arkndjl-jersey-<sport>.svg (front + back on one card) and
arkndjl-jerseys-lineup.svg. Lilac and aquamarine with black, grey and white accents. Run: python3 scripts/jersey_art.py
"""
import os

# lilac and aquamarine, with neutral black, grey and white accents (no purple)
DEEP, ROW = "#1b1b1f", "#2b2b31"
LILAC, TEAL, WHITE = "#c8c7ff", "#7fffd4", "#ffffff"
BLACK, CHAR, GREY = "#131316", "#2e2e35", "#8d8d96"
OUTLINE = "#09090b"
SHADE = {BLACK: "#08080a", CHAR: "#1f1f24", GREY: "#6e6e76", "#b3b1f0": "#9c97d6", "#6ce8c0": "#58c9a6",
         "#26262c": "#1a1a1f", LILAC: "#a89fd8", TEAL: "#5fd1b0", WHITE: "#d4d4dc"}

# 3x5 pixel font
F = {
 "A": "010101111101101", "B": "110101110101110", "C": "011100100100011", "D": "110101101101110",
 "E": "111100110100111", "F": "111100110100100", "G": "011100101101011", "H": "101101111101101",
 "I": "111010010010111", "J": "001001001101010", "K": "101101110101101", "L": "100100100100111",
 "M": "101111111101101", "N": "110101101101101", "O": "010101101101010", "P": "110101110100100",
 "R": "110101110101101", "S": "011100010001110", "T": "111010010010010", "U": "101101101101111",
 "V": "101101101101010", "W": "101101111111101", "Q": "010101101111011", "X": "101101010101101", "Z": "111001010100111", "Y": "101101010010010", "0": "111101101101111", "1": "010110010010111",
 "2": "110001010100111", "3": "110001010001110", "4": "101101111001001", "5": "111100110001110",
 "6": "011100110101010", "7": "111001010010010", "8": "010101010101010", "9": "010101011001110",
 " ": "000000000000000", "/": "001001010100100", "-": "000000111000000", ".": "000000000000010",
}


# 5x7 block numerals for the big numbers
N = {
 "0": ["01110", "11011", "11011", "11011", "11011", "11011", "01110"],
 "1": ["00110", "01110", "11110", "00110", "00110", "00110", "11111"],
 "7": ["11111", "00011", "00110", "00110", "01100", "01100", "01100"],
 "3": ["11110", "00011", "00011", "01110", "00011", "00011", "11110"],
}


def number(g, s, cx, y, col, ring, mask, k=2):
    w = (len(s) * 6 - 1) * k
    x0, cells = cx - w // 2, set()
    for i, ch in enumerate(s):
        for r, row in enumerate(N[ch]):
            for c, b in enumerate(row):
                if b == "1":
                    for dy in range(k):
                        for dx in range(k):
                            cells.add((x0 + (i * 6 + c) * k + dx, y + r * k + dy))
    for (x, y2) in cells:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                q = (x + dx, y2 + dy)
                if q not in cells and q in mask: g[q] = ring
    for q in cells:
        if q in mask: g[q] = col


def text_w(s, k=1):
    return (len(s) * 4 - 1) * k


def text(g, s, x, y, col, k=1, mask=None):
    for i, ch in enumerate(s):
        bits = F[ch]
        for r in range(5):
            for c in range(3):
                if bits[r * 3 + c] == "1":
                    for dy in range(k):
                        for dx in range(k):
                            p = (x + (i * 4 + c) * k + dx, y + r * k + dy)
                            if mask is None or p in mask:
                                g[p] = col


def ctext(g, s, cx, y, col, k=1, mask=None):
    text(g, s, cx - text_w(s, k) // 2, y, col, k, mask)


W, H, CX = 44, 46, 22


def body(spec):
    """spec: list of (y0, y1, half_width) for the garment and (y0, y1, half_width) neck holes."""
    rows, neck = spec
    m = set()
    for y0, y1, hw in rows:
        for y in range(y0, y1 + 1):
            for x in range(CX - hw, CX + hw):
                m.add((x, y))
    for y0, y1, hw in neck:
        for y in range(y0, y1 + 1):
            for x in range(CX - hw, CX + hw):
                m.discard((x, y))
    return m


def cut(m, pred):
    return {p for p in m if not pred(*p)}


# kits: base, trim (collar, stripes, wordmark), second stripe, number, number ring, pinstripe, outline
KITS = {
    "home": dict(base=LILAC, trim=CHAR, alt=TEAL, ink=CHAR, ring=WHITE, pin="#b3b1f0", line=OUTLINE),
    "away": dict(base=TEAL, trim=CHAR, alt=WHITE, ink=CHAR, ring=LILAC, pin="#6ce8c0", line=OUTLINE),
    "alternate": dict(base=BLACK, trim=TEAL, alt=LILAC, ink=LILAC, ring=GREY, pin="#26262c", line=GREY),
}
NUMS = {"football": "11", "basketball": "1", "hockey": "31", "soccer": "10", "baseball": "7"}
SIDES = lambda a, b: list(range(CX - a, CX - b)) + list(range(CX + b, CX + a))


def jersey(sport, back, kit="home"):
    k = KITS[kit]
    base, trim, alt, ink, ring = k["base"], k["trim"], k["alt"], k["ink"], k["ring"]
    g = {}
    num = NUMS[sport]
    if sport == "football":
        m = body(([(3, 3, 9), (4, 5, 14), (6, 14, 19), (15, 15, 16), (16, 41, 14)],
                  [(3, 4, 4), (5, 5, 3)]))
        for p in m: g[p] = base
        for y in (10, 12):  # sleeve stripes
            for x in SIDES(19, 14): g[(x, y)] = trim if y == 10 else alt
        for x in SIDES(19, 14):
            if (x, 14) in m: g[(x, 14)] = trim
        ny = 17 if back else 15
    elif sport == "basketball":
        m = body(([(3, 7, 8), (8, 8, 9), (9, 9, 10), (10, 10, 11), (11, 11, 12), (12, 41, 14)],
                  [(3, 6, 4), (7, 8, 3), (9, 9, 2)] if not back else [(3, 4, 4), (5, 5, 3)]))
        for p in m: g[p] = base
        for x in range(CX - 14, CX + 14): g[(x, 39)] = alt  # hem stripe
        ny = 20
    elif sport == "hockey":
        m = body(([(3, 3, 10), (4, 5, 15), (6, 8, 18), (9, 24, 20), (25, 41, 15)],
                  [(3, 4, 4), (5, 5, 3)]))
        m |= {(x, y) for y in range(25, 31) for x in SIDES(20, 15)}
        for p in m: g[p] = base
        for y in (26, 27, 29, 30):  # elbow-to-cuff stripes
            for x in SIDES(20, 15): g[(x, y)] = alt if y == 29 else trim
        for y in (35, 36, 38):  # hem stripes
            for x in range(CX - 15, CX + 15): g[(x, y)] = alt if y == 38 else trim
        ny = 17 if back else 22
    elif sport == "soccer":
        m = body(([(3, 3, 9), (4, 5, 13), (6, 15, 19), (16, 41, 14)],
                  [(3, 4, 4), (5, 5, 3)] if back else [(3, 4, 4), (5, 6, 3), (7, 7, 2), (8, 8, 1)]))
        m = cut(m, lambda x, y: y >= 12 and abs(x - CX + 0.5) > 14 + max(0, 15 - y))
        for p in m: g[p] = base
        if not back:  # shoulder-to-hip sash
            for p in m:
                if -3 <= (p[0] - CX) - (p[1] - 24) < 3 and p[1] > 6: g[p] = alt
        for x in SIDES(19, 14):
            for y in (13, 14):
                if (x, y) in m: g[(x, y)] = trim if y == 14 else alt
        ny = 17
    else:  # baseball: button front, piping, pinstripes
        m = body(([(3, 3, 9), (4, 5, 13), (6, 16, 19), (17, 41, 14)],
                  [(3, 4, 4), (5, 5, 3), (6, 6, 2)] if not back else [(3, 4, 4), (5, 5, 3)]))
        m = cut(m, lambda x, y: y >= 13 and abs(x - CX + 0.5) > 14 + max(0, 16 - y))
        for p in m: g[p] = base
        for p in m:
            if (p[0] - CX) % 3 == 1 and p[1] > 5: g[p] = k["pin"]
        for x in SIDES(19, 14):  # sleeve piping
            if (x, 15) in m: g[(x, 15)] = trim
        if not back:
            for y in [y for y in range(7, 42) if not 10 <= y <= 17]:  # placket piping + buttons
                g[(CX - 1, y)] = trim
                g[(CX, y)] = alt if y % 5 == 0 else base
        ny = 17

    # collar trim: body cells touching the neck hole
    for (x, y) in list(m):
        if y <= 10 and any((x + dx, y + dy) not in m and abs(x + dx - CX + 0.5) < 6 and y + dy >= 3
                           for dx, dy in ((1, 0), (-1, 0), (0, -1), (0, 1))):
            g[(x, y)] = trim
    if sport == "basketball":  # armhole + neck binding
        for (x, y) in list(m):
            if y <= 16 and any((x + dx, y + dy) not in m for dx, dy in ((1, 0), (-1, 0), (0, -1))):
                g[(x, y)] = trim
    if sport == "hockey" and not back:  # lace-up collar
        for y in range(6, 10):
            g[(CX - 1, y)] = OUTLINE if y % 2 else trim
            g[(CX, y)] = trim if y % 2 else OUTLINE

    # graphics
    word = trim
    if back:
        ctext(g, "ARKNDJL", CX, {"basketball": 13, "hockey": 10}.get(sport, 9), word, 1, m)
        number(g, num, CX, ny, ink, ring, m)
    elif sport == "football":
        ctext(g, "ARKNDJL", CX, 7, word, 1, m)
        number(g, num, CX, ny, ink, ring, m)
    elif sport == "basketball":
        ctext(g, "ARKNDJL", CX, 13, word, 1, m)
        number(g, num, CX, ny, ink, ring, m)
    elif sport == "hockey":
        crest(g, CX, 13, trim, alt, 1)
    elif sport == "soccer":
        crest(g, CX + 6, 9, trim, alt, 0)
        ctext(g, "ARKNDJL", CX, 20, ink, 1, m)
    else:
        ctext(g, "ARKNDJL", CX, 11, word, 1, m)
        for x in range(CX - 13, CX + 13):  # swoosh tail under the wordmark
            if abs(x - CX + 0.5) > 2: g[(x, 17)] = alt
        text(g, num, CX - 10, 24, ink, 2, m)

    # shading: right edge darker
    for (x, y) in m:
        if ((x + 1, y) not in m or (x + 2, y) not in m) and g[(x, y)] in (base, trim, alt, k["pin"]):
            g[(x, y)] = SHADE.get(g[(x, y)], g[(x, y)])
    out = {}
    for (x, y) in m:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            q = (x + dx, y + dy)
            if q not in m: out[q] = k["line"]
    for q, c in out.items(): g.setdefault(q, c)
    return g


def crest(g, cx, y, fg, acc, small):
    """Pixel 'A' glyph crest from the site logo."""
    if small:
        art = ["....##....", "...####...", "...#..#...", "..##..##..", "..######..",
               ".##....##.", ".#......#.", "###....###"]
    else:
        art = [".##.", "#..#", "####", "#..#"]
    w = len(art[0])
    for r, row in enumerate(art):
        for c, ch in enumerate(row):
            if ch == "#": g[(cx - w // 2 + c, y + r)] = fg
    if small:
        for c in range(w): g[(cx - w // 2 + c, y + len(art) + 1)] = acc


def svg(cells, w, h, scale=8, title=""):
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w*scale}" height="{h*scale}" '
           f'shape-rendering="crispEdges"><title>{title}</title><rect width="{w}" height="{h}" fill="{DEEP}"/>']
    by = {}
    for (x, y), c in cells.items():
        if 0 <= x < w and 0 <= y < h: by.setdefault(c, []).append((x, y))
    for c, ps in by.items():
        ps = sorted(ps, key=lambda p: (p[1], p[0]))
        d, i = [], 0
        while i < len(ps):  # merge horizontal runs
            x, y = ps[i]; n = 1
            while i + n < len(ps) and ps[i + n] == (x + n, y): n += 1
            d.append(f"M{x} {y}h{n}v1h-{n}z"); i += n
        out.append(f'<path fill="{c}" d="{"".join(d)}"/>')
    out.append("</svg>")
    return "".join(out)


def place(dst, src, ox, oy):
    for (x, y), c in src.items(): dst[(x + ox, y + oy)] = c


def bg(cells, w, h):
    for y in range(h):
        for x in range(w):
            if (x + y) % 6 == 0 and y % 3 == 0: cells[(x, y)] = ROW


SPORTS = ["football", "basketball", "hockey", "soccer", "baseball"]
if __name__ == "__main__":
    root = os.path.join(os.path.dirname(__file__), "..", "static", "img", "art")
    for s in SPORTS:  # one card per sport: home, away, alternate; fronts over backs
        w, h = (W + 2) * 3 + 4, (H + 10) * 2 + 14
        cells = {}
        bg(cells, w, h)
        for i, kit in enumerate(KITS):
            x0 = 3 + i * (W + 2)
            place(cells, jersey(s, False, kit), x0, 2)
            place(cells, jersey(s, True, kit), x0, H + 10 + 2)
            ctext(cells, kit.upper(), x0 + CX, H + 2 + 2, LILAC)
        ctext(cells, "FRONT / BACK", w // 2, h - 20, LILAC)
        ctext(cells, "ARKNDJL / " + s.upper(), w // 2, h - 10, TEAL)
        open(os.path.join(root, f"arkndjl-jersey-{s}.svg"), "w").write(svg(cells, w, h, 6, f"ARKNDJL {s} kits"))
    w, h = (W + 2) * len(SPORTS) + 4, (H + 10) * 3 + 4
    cells = {}
    bg(cells, w, h)
    for r, kit in enumerate(KITS):
        for i, s in enumerate(SPORTS):
            place(cells, jersey(s, True, kit), 3 + i * (W + 2), 2 + r * (H + 10))
    open(os.path.join(root, "arkndjl-jerseys-lineup.svg"), "w").write(svg(cells, w, h, 5, "ARKNDJL kit lineup"))
    print("ok")
