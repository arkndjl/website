"""Pixel-art ARKNDJL jersey mockups (football, basketball, hockey, soccer) as crisp SVGs.

Writes static/img/art/arkndjl-jersey-<sport>.svg (front + back on one card) and
arkndjl-jerseys-lineup.svg. Site palette only. Run: python3 scripts/jersey_art.py
"""
import os

DEEP, ROW, BG, PURPLE = "#241a3a", "#3a2d56", "#4a3b6b", "#57068c"
LILAC, TEAL, PINK, WHITE = "#c8c7ff", "#7fffd4", "#ff9ec7", "#ffffff"
OUTLINE = "#120c20"
SHADE = {PURPLE: "#461072", LILAC: "#a89fd8", TEAL: "#5fd1b0", DEEP: "#1a1230", WHITE: "#d9d7ff"}

# 3x5 pixel font
F = {
 "A": "010101111101101", "B": "110101110101110", "C": "011100100100011", "D": "110101101101110",
 "E": "111100110100111", "F": "111100110100100", "G": "011100101101011", "H": "101101111101101",
 "I": "111010010010111", "J": "001001001101010", "K": "101101110101101", "L": "100100100100111",
 "M": "101111111101101", "N": "110101101101101", "O": "010101101101010", "P": "110101110100100",
 "R": "110101110101101", "S": "011100010001110", "T": "111010010010010", "U": "101101101101111",
 "V": "101101101101010", "Y": "101101010010010", "0": "111101101101111", "1": "010110010010111",
 "2": "110001010100111", "3": "110001010001110", "4": "101101111001001", "5": "111100110001110",
 "6": "011100110101010", "7": "111001010010010", "8": "010101010101010", "9": "010101011001110",
 " ": "000000000000000", "/": "001001010100100", "-": "000000111000000", ".": "000000000000010",
}


# 5x7 block numerals for the big numbers
N = {
 "0": ["01110", "11011", "11011", "11011", "11011", "11011", "01110"],
 "1": ["00110", "01110", "11110", "00110", "00110", "00110", "11111"],
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


def jersey(sport, back):
    g = {}
    if sport == "football":
        m = body(([(3, 3, 9), (4, 5, 14), (6, 14, 19), (15, 15, 16), (16, 41, 14)],
                  [(3, 4, 4), (5, 5, 3)]))
        base, trim, alt = PURPLE, TEAL, LILAC
        for p in m: g[p] = base
        for y in (10, 12):  # sleeve stripes
            for x in list(range(CX - 19, CX - 14)) + list(range(CX + 14, CX + 19)):
                g[(x, y)] = trim
        for x in range(CX - 19, CX + 19):  # sleeve cuffs
            if (x, 14) in m and abs(x - CX + 0.5) > 14: g[(x, 14)] = alt
        num, ny = "11", 17 if back else 15
    elif sport == "basketball":
        m = body(([(3, 7, 8), (8, 8, 9), (9, 9, 10), (10, 10, 11), (11, 11, 12), (12, 41, 14)],
                  [(3, 6, 4), (7, 8, 3), (9, 9, 2)] if not back else [(3, 4, 4), (5, 5, 3)]))
        base, trim, alt = TEAL, PURPLE, LILAC
        for p in m: g[p] = base
        num, ny = "1", 20
    elif sport == "hockey":
        m = body(([(3, 3, 10), (4, 5, 15), (6, 8, 18), (9, 24, 20), (25, 41, 15)],
                  [(3, 4, 4), (5, 5, 3)]))
        m |= {(x, y) for y in range(25, 31) for x in list(range(CX - 20, CX - 15)) + list(range(CX + 15, CX + 20))}
        base, trim, alt = LILAC, PURPLE, TEAL
        for p in m: g[p] = base
        for y in (26, 27, 29):  # elbow-to-cuff stripes
            for x in list(range(CX - 20, CX - 15)) + list(range(CX + 15, CX + 20)):
                g[(x, y)] = trim if y != 29 else alt
        for y in (35, 36, 38):  # hem stripes
            for x in range(CX - 15, CX + 15):
                g[(x, y)] = trim if y != 38 else alt
        for y in range(30, 31):  # cuff
            for x in list(range(CX - 20, CX - 15)) + list(range(CX + 15, CX + 20)):
                g[(x, y)] = trim
        num, ny = "31", 17 if back else 22
    else:  # soccer
        m = body(([(3, 3, 9), (4, 5, 13), (6, 15, 19), (16, 41, 14)],
                  [(3, 4, 4), (5, 5, 3)] if back else [(3, 4, 4), (5, 6, 3), (7, 7, 2), (8, 8, 1)]))
        m = cut(m, lambda x, y: y >= 12 and abs(x - CX + 0.5) > 14 + max(0, 15 - y))
        base, trim, alt = PURPLE, LILAC, TEAL
        for p in m: g[p] = base
        for p in m:  # pinstripes
            if (p[0] - CX) % 4 == 0 and abs(p[0] - CX + 0.5) < 14 and p[1] > 6: g[p] = "#6032a8"
        for x in range(CX - 18, CX + 18):
            for y in (13, 14):
                if (x, y) in m and abs(x - CX + 0.5) > 14: g[(x, y)] = alt
        num, ny = "10", 17 if back else 0

    # collar trim: body cells touching the neck hole or the top edge
    for (x, y) in list(m):
        if y <= 10 and any((x + dx, y + dy) not in m and abs(x + dx - CX + 0.5) < 6 and y + dy >= 3
                           for dx, dy in ((1, 0), (-1, 0), (0, -1), (0, 1))):
            g[(x, y)] = trim
    if sport == "basketball":  # armhole + neck binding all the way round
        for (x, y) in list(m):
            if y <= 16 and any((x + dx, y + dy) not in m for dx, dy in ((1, 0), (-1, 0), (0, -1))):
                g[(x, y)] = trim
    if sport == "hockey" and not back:  # lace-up collar
        for y in range(6, 10):
            g[(CX - 1, y)] = DEEP if y % 2 else trim
            g[(CX, y)] = trim if y % 2 else DEEP

    # graphics
    ink = WHITE if base != LILAC and base != TEAL else PURPLE
    ring = {"football": TEAL, "basketball": LILAC, "hockey": TEAL, "soccer": TEAL}[sport]
    if back:
        ctext(g, "ARKNDJL", CX, {"basketball": 13, "hockey": 10}.get(sport, 9), LILAC if base == PURPLE else trim, 1, m)
        number(g, num, CX, ny, ink, ring, m)
    elif sport == "football":
        ctext(g, "ARKNDJL", CX, 7, LILAC, 1, m)
        number(g, num, CX, ny, ink, ring, m)
    elif sport == "basketball":
        ctext(g, "ARKNDJL", CX, 13, PURPLE, 1, m)
        number(g, num, CX, ny, ink, ring, m)
    elif sport == "hockey":
        crest(g, CX, 13, PURPLE, TEAL, 1)
    else:
        crest(g, CX + 6, 9, LILAC, TEAL, 0)
        ctext(g, "ARKNDJL", CX, 20, WHITE, 1, m)
    # number shadow on the back for depth
    # shading: right edge darker, left edge highlight
    for (x, y) in m:
        if ((x + 1, y) not in m or (x + 2, y) not in m) and g[(x, y)] in (base, trim, alt, "#6032a8"):
            g[(x, y)] = SHADE.get(g[(x, y)], g[(x, y)])
    # outline
    out = {}
    for (x, y) in m:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            q = (x + dx, y + dy)
            if q not in m: out[q] = OUTLINE
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


SPORTS = ["football", "basketball", "hockey", "soccer"]
if __name__ == "__main__":
    root = os.path.join(os.path.dirname(__file__), "..", "static", "img", "art")
    for s in SPORTS:
        w, h = W * 2 + 6, H + 22
        cells = {}
        bg(cells, w, h)
        place(cells, jersey(s, False), 2, 4)
        place(cells, jersey(s, True), W + 4, 4)
        ctext(cells, "FRONT", 2 + CX, 2 + H + 2, LILAC)
        ctext(cells, "BACK", W + 4 + CX, 2 + H + 2, LILAC)
        ctext(cells, "ARKNDJL / " + s.upper(), w // 2, h - 8, TEAL)
        open(os.path.join(root, f"arkndjl-jersey-{s}.svg"), "w").write(svg(cells, w, h, 8, f"ARKNDJL {s} jersey"))
    w, h = W * 4 + 10, H + 16
    cells = {}
    bg(cells, w, h)
    for i, s in enumerate(SPORTS):
        place(cells, jersey(s, True), 2 + i * (W + 2), 2)
        ctext(cells, s.upper(), 2 + i * (W + 2) + CX, H + 6, LILAC)
    open(os.path.join(root, "arkndjl-jerseys-lineup.svg"), "w").write(svg(cells, w, h, 6, "ARKNDJL jersey lineup"))
    print("ok")
