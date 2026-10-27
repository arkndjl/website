"""ARKNDJL jersey art: neo-gothic kits for five sports, rendered as vector SVG.

Each sport has a lilac home, aquamarine away and black alternate kit. Three
treatments of the same kits:
  revival   shaded fabric with Gothic Revival trim (arcade stripes, blackletter, glyph crest)
  glass     the kit leaded as a stained-glass window, lit from behind
  cathedral the revival kit set in a stone lancet window with tracery

Text is converted to outlines (fontTools) so the SVGs work as plain <img>.
Font: brand/fonts/gothic/GrenzeGotisch.ttf (Grenze Gotisch, OFL).
Run: python3 scripts/jersey_art.py            (site files: revival cards, cathedral lineups)
     python3 scripts/jersey_art.py --preview DIR [sport ...]   (every treatment)
"""
import math, os, random, sys
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FONT_DIR = os.path.join(ROOT, "brand", "fonts", "gothic")

DEEP, NIGHT, PLUM, PURPLE = "#241a3a", "#120c20", "#3a2d56", "#57068c"
LILAC, TEAL, BLACK, BG = "#c8c7ff", "#7fffd4", "#16111f", "#4a3b6b"

KITS = {
    "home": dict(base=LILAC, trim=PURPLE, accent=TEAL, ink=PURPLE, ring=TEAL, word=PURPLE),
    "away": dict(base=TEAL, trim=PURPLE, accent=LILAC, ink=PURPLE, ring=LILAC, word=PURPLE),
    "alternate": dict(base=BLACK, trim=TEAL, accent=LILAC, ink=LILAC, ring=PURPLE, word=TEAL),
}
# lettering: wordmark font, its text and size scale, numeral font and scale
LETTER = dict(word="GrenzeGotisch@800", text="ARKNDJL", wscale=.9, track=.05, num="GrenzeGotisch@800", nscale=1.05, hair=1.0)
NUMS = {"football": "11", "basketball": "1", "hockey": "31", "soccer": "10", "baseball": "7"}
SPORTS = ["football", "basketball", "hockey", "soccer", "baseball"]


# ---------- colour helpers ----------
def rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def hexc(c):
    return "#" + "".join(f"{max(0, min(255, round(v))):02x}" for v in c)


def mix(a, b, t):
    a, b = rgb(a), rgb(b)
    return hexc([a[i] + (b[i] - a[i]) * t for i in range(3)])


def shade(c, t):  # t < 0 darker (toward night), t > 0 lighter (toward white)
    return mix(c, NIGHT if t < 0 else "#ffffff", abs(t))


# ---------- text to outlines ----------
_fonts = {}


def font(name):
    """'File' or 'File@700' (a variable font at that weight)."""
    if name not in _fonts:
        file, _, wght = name.partition("@")
        dirs = [FONT_DIR] + os.environ.get("JERSEY_FONTS", "").split(os.pathsep)
        path = next(os.path.join(d, file + ".ttf") for d in dirs if d and os.path.exists(os.path.join(d, file + ".ttf")))
        f = TTFont(path)
        if wght:  # pin the weight axis so outlines and advances agree
            from fontTools.varLib.instancer import instantiateVariableFont
            f = instantiateVariableFont(f, {t.axisTag: (float(wght) if t.axisTag == "wght" else t.defaultValue)
                                            for t in f["fvar"].axes})
        gs = f.getGlyphSet()
        _fonts[name] = (gs, f.getBestCmap(), f["head"].unitsPerEm, f["hmtx"])
    return _fonts[name]


def glyphs(name, s, size, track=0.0):
    """[(glyph svg path at origin, advance)] for each char, in px."""
    gs, cmap, upm, hmtx = font(name)
    k = size / upm
    out = []
    for ch in s:
        gname = cmap.get(ord(ch))
        if gname is None:
            continue
        pen = SVGPathPen(gs)
        gs[gname].draw(TransformPen(pen, (k, 0, 0, -k, 0, 0)))
        out.append((pen.getCommands(), hmtx[gname][0] * k + track * size))
    return out


def text(name, s, size, x, y, anchor="middle", track=0.0):
    gl = glyphs(name, s, size, track)
    w = sum(a for _, a in gl) - track * size
    x0 = x - (w / 2 if anchor == "middle" else (w if anchor == "end" else 0))
    parts = []
    for d, a in gl:
        if d:
            parts.append(f'<path transform="translate({x0:.1f},{y:.1f})" d="{d}"/>')
        x0 += a
    return "".join(parts), w


def arc_text(name, s, size, cx, cy, r, track=0.0):
    """Text on an arch (centre cx,cy, radius r), baseline on the arc, reading left to right."""
    gl = glyphs(name, s, size, track)
    w = sum(a for _, a in gl) - track * size
    ang = -w / 2 / r
    parts = []
    for d, a in gl:
        mid = ang + a / 2 / r
        x, y = cx + r * math.sin(mid), cy - r * math.cos(mid)
        if d:
            parts.append(f'<path transform="translate({x:.1f},{y:.1f}) rotate({math.degrees(mid):.2f}) '
                         f'translate({-a / 2:.1f},0)" d="{d}"/>')
        ang += a / r
    return "".join(parts)


# ---------- the site glyph ----------
GLYPH = ("M52 0V45.9H98.8L243.6 263H42.8L352 750.3L661.2 263H460.4L604.2 45.9H652V0H491V45.9H523.6L376 269"
         "L388 272.8V45.9H429V0H275V45.9H316V272.8L328 269L179.4 45.9H213V0ZM191.3 342.2H512.7L352 596.3Z")


def glyph(cx, cy, h, fill, extra=""):
    k = h / 750.3
    return (f'<path fill="{fill}" {extra} transform="translate({cx - 352 * k:.1f},{cy + h / 2:.1f}) '
            f'scale({k:.4f},{-k:.4f})" d="{GLYPH}"/>')


# ---------- garment geometry ----------
def sym(half):
    """Closed symmetric path from the right half: start (top centre) then [('L',p)|('C',c1,c2,p)]."""
    start, segs = half[0], half[1:]
    pts = [start] + [s[-1] for s in segs]
    d = [f"M{start[0]:.1f} {start[1]:.1f}"]
    for s in segs:
        if s[0] == "L":
            d.append(f"L{s[1][0]:.1f} {s[1][1]:.1f}")
        else:
            d.append("C" + " ".join(f"{p[0]:.1f} {p[1]:.1f}" for p in s[1:]))
    for i in range(len(segs) - 1, -1, -1):
        s, p0 = segs[i], pts[i]
        if s[0] == "L":
            d.append(f"L{-p0[0]:.1f} {p0[1]:.1f}")
        else:
            c1, c2 = s[1], s[2]
            d.append(f"C{-c2[0]:.1f} {c2[1]:.1f} {-c1[0]:.1f} {c1[1]:.1f} {-p0[0]:.1f} {p0[1]:.1f}")
    return "".join(d) + "Z"


def neckline(start, s):
    """Open path for the collar: the first segment mirrored through the centre."""
    if s[0] == "L":
        return f"M{-s[1][0]:.1f} {s[1][1]:.1f}L{start[0]:.1f} {start[1]:.1f}L{s[1][0]:.1f} {s[1][1]:.1f}"
    c1, c2, p = s[1], s[2], s[3]
    return (f"M{-p[0]:.1f} {p[1]:.1f}C{-c2[0]:.1f} {c2[1]:.1f} {-c1[0]:.1f} {c1[1]:.1f} {start[0]:.1f} {start[1]:.1f}"
            f"C{c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} {p[0]:.1f} {p[1]:.1f}")


def shape(sport, back):
    """Right-half outline, right sleeve polygon and layout anchors for each cut. Origin top centre."""
    if sport == "football":
        dip = 30 if back else 52
        half = [(0, dip), ("C", (28, dip), (52, 26), (58, 10)), ("C", (90, 12), (122, 18), (146, 30)),
                ("C", (170, 42), (184, 62), (190, 92)), ("L", (204, 172)), ("C", (182, 182), (158, 186), (138, 184)),
                ("C", (134, 200), (130, 220), (130, 250)), ("L", (132, 440)), ("C", (90, 448), (40, 450), (0, 450))]
        sleeve = [(130, 30), (215, 70), (230, 190), (130, 200)]
        a = dict(num_y=330, num_size=210, plate_r=520, plate_y=118)
    elif sport == "basketball":
        dip = 46 if back else 92
        half = [(0, dip), ("C", (34, dip), (54, 50), (58, 10)), ("L", (98, 10)),
                ("C", (102, 70), (118, 128), (154, 150)), ("C", (156, 250), (152, 360), (154, 442)),
                ("C", (100, 450), (50, 452), (0, 452))]
        sleeve = None
        a = dict(num_y=380, num_size=220, plate_r=420, plate_y=160)
    elif sport == "hockey":
        dip = 32 if back else 46
        half = [(0, dip), ("C", (30, dip), (52, 28), (58, 12)), ("C", (100, 14), (140, 24), (170, 44)),
                ("C", (196, 62), (210, 120), (218, 180)), ("L", (230, 312)), ("L", (166, 322)),
                ("C", (160, 260), (156, 210), (152, 178)), ("C", (154, 280), (156, 380), (160, 460)),
                ("C", (110, 468), (54, 470), (0, 470))]
        sleeve = [(150, 30), (240, 110), (250, 330), (150, 330)]
        a = dict(num_y=320, num_size=170, plate_r=560, plate_y=150)
    elif sport == "soccer":
        dip = 26 if back else 62
        half = [(0, dip), ("L", (46, 10)) if not back else ("C", (24, dip), (42, 20), (46, 10)),
                ("C", (80, 14), (112, 22), (136, 34)), ("C", (160, 50), (176, 80), (190, 122)),
                ("L", (198, 150)), ("C", (178, 162), (160, 168), (138, 168)), ("C", (130, 230), (128, 300), (132, 440)),
                ("C", (90, 446), (44, 448), (0, 448))]
        sleeve = [(128, 24), (215, 90), (215, 190), (128, 190)]
        a = dict(num_y=310, num_size=190, plate_r=520, plate_y=110)
    else:  # baseball
        dip = 28 if back else 66
        half = [(0, dip), ("C", (20, dip), (40, 26), (48, 10)) if back else ("L", (48, 10)),
                ("C", (84, 14), (120, 22), (146, 36)), ("C", (172, 52), (186, 88), (198, 132)),
                ("L", (210, 182)), ("C", (186, 192), (164, 196), (146, 194)),
                ("C", (142, 260), (142, 340), (146, 446)), ("C", (98, 452), (48, 454), (0, 454))]
        sleeve = [(140, 28), (230, 90), (230, 220), (140, 220)]
        a = dict(num_y=320, num_size=190, plate_r=520, plate_y=115)
    return half, sleeve, a


# ---------- gothic ornament ----------
def arcade(x0, x1, y, h, n, col, line=None):
    """A band topped by a row of pointed arches: Gothic arcade trim, drawn horizontally."""
    w = (x1 - x0) / n
    d = [f"M{x0:.1f} {y + h:.1f}L{x0:.1f} {y:.1f}"]
    for i in range(n):
        a, b = x0 + i * w, x0 + (i + 1) * w
        m = (a + b) / 2
        d.append(f"Q{a:.1f} {y - w * 0.62:.1f} {m:.1f} {y - w * 0.95:.1f}"
                 f"Q{b:.1f} {y - w * 0.62:.1f} {b:.1f} {y:.1f}")
    d.append(f"L{x1:.1f} {y + h:.1f}Z")
    st = f' stroke="{line}" stroke-width="3" stroke-linejoin="round"' if line else ""
    return f'<path fill="{col}"{st} d="{"".join(d)}"/>'


def quatrefoil(cx, cy, r, attrs):
    """Four lobes on a square: the Gothic quatrefoil, as one path."""
    lr, o = r * .5, r * .5
    d = []
    for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
        x, y = cx + dx * o, cy + dy * o
        d.append(f"M{x - lr:.2f} {y:.2f}a{lr:.2f} {lr:.2f} 0 1 0 {2 * lr:.2f} 0a{lr:.2f} {lr:.2f} 0 1 0 {-2 * lr:.2f} 0Z")
    s = r * .5
    d.append(f"M{cx:.2f} {cy - s * 1.2:.2f}L{cx + s * 1.2:.2f} {cy:.2f}L{cx:.2f} {cy + s * 1.2:.2f}L{cx - s * 1.2:.2f} {cy:.2f}Z")
    return f'<path {attrs} d="{"".join(d)}"/>'


def crest(cx, cy, r, k, lead=False):
    """Quatrefoil crest holding the site glyph."""
    ring = k["trim"] if k["base"] != BLACK else k["accent"]
    inner = k["base"] if k["base"] != BLACK else PURPLE
    ink = k["trim"] if k["base"] != BLACK else TEAL
    s = quatrefoil(cx, cy, r * 1.16, f'fill="{NIGHT}"')
    s += quatrefoil(cx, cy, r * 1.06, f'fill="{ring}"')
    s += quatrefoil(cx, cy, r * .9, f'fill="{inner}"')
    s += glyph(cx, cy + r * .03, r * 1.02, ink, f'stroke="{NIGHT}" stroke-width="{18 if lead else 10}" paint-order="stroke"')
    return s


def number_art(s, cx, y, size, k, lead=False):
    """Pirata One numerals with a double keyline: accent ring, then a night hairline."""
    d, _ = text(LETTER["num"], s, size * LETTER["nscale"], cx, y, track=.03)
    ring, ink = k["ring"], k["ink"]
    return (f'<g fill="{NIGHT}" stroke="{NIGHT}" stroke-width="{size * .1:.1f}" stroke-linejoin="round">{d}</g>'
            f'<g fill="{ring}" stroke="{ring}" stroke-width="{size * .065:.1f}" stroke-linejoin="round">{d}</g>'
            f'<g fill="{ink}" stroke="{NIGHT}" stroke-width="{(3 if lead else 1.6) * LETTER.get("hair", 1)}">{d}</g>')


def wordmark(s, size, x, y, k, stroke=6):
    d, _ = text(LETTER["word"], LETTER["text"], size * LETTER["wscale"], x, y, track=LETTER["track"])
    return (f'<g fill="{NIGHT}" stroke="{NIGHT}" stroke-width="{stroke}" stroke-linejoin="round">{d}</g>'
            f'<g fill="{k["word"]}">{d}</g>')


# ---------- defs shared by every jersey ----------
def defs():
    return f'''<defs>
<filter id="soft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="9"/></filter>
<filter id="softer" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="24"/></filter>
<filter id="drop" x="-20%" y="-20%" width="140%" height="150%"><feGaussianBlur in="SourceAlpha" stdDeviation="10"/><feOffset dy="14"/><feComponentTransfer><feFuncA type="linear" slope=".55"/></feComponentTransfer><feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter>
<filter id="grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" seed="7"/><feColorMatrix values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 .5 0"/><feComposite in2="SourceGraphic" operator="in"/></filter>
<filter id="glassy" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".035" numOctaves="3" seed="3"/><feColorMatrix values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 .55 -.18"/><feComposite in2="SourceGraphic" operator="in"/></filter>
<filter id="glow" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="26"/></filter>
<pattern id="mesh" width="7" height="7" patternUnits="userSpaceOnUse"><circle cx="3.5" cy="3.5" r="1.25" fill="{NIGHT}"/></pattern>
<pattern id="knit" width="6" height="8" patternUnits="userSpaceOnUse"><path d="M0 0L3 4L6 0M0 4L3 8L6 4" fill="none" stroke="{NIGHT}" stroke-width=".8"/></pattern>
<pattern id="tracery" width="40" height="60" patternUnits="userSpaceOnUse"><path d="M0 60V26Q2 6 20 0Q38 6 40 26V60M20 0V60M10 60V34Q12 22 20 18Q28 22 30 34V60" fill="none" stroke="{LILAC}" stroke-width="1.3"/></pattern>
</defs>'''


def damask(col, op):
    """Tonal quatrefoil damask, the soccer kit's jacquard."""
    s = "".join(quatrefoil(x, y, 16, f'fill="none" stroke="{col}" stroke-width="1.6"') +
                quatrefoil(x + 22, y + 22, 7, f'fill="{col}"')
                for x in range(-242, 260, 44) for y in range(10, 480, 44))
    return f'<g opacity="{op}">{s}</g>'


def kit_trim(sport, back, k, half, a, uid, lead=False):
    """Stripes, collar and graphics for one jersey, in garment coordinates."""
    base, trim, acc = k["base"], k["trim"], k["accent"]
    ln = NIGHT if lead else None
    L = f' stroke="{NIGHT}" stroke-width="4"' if lead else ""
    sl = f'url(#{uid}sl)'
    g = []
    if sport == "football":
        for sx in (1, -1):
            g.append(f'<g clip-path="{sl}"><g transform="scale({sx},1) translate(176,150) rotate(-10)">'
                     f'{arcade(-70, 70, -12, 16, 7, trim, ln)}<rect x="-70" y="10" width="140" height="7" fill="{acc}"{L}/>'
                     f'{arcade(-70, 70, 30, 14, 7, trim, ln)}</g></g>')
    elif sport == "hockey":
        for sx in (1, -1):
            g.append(f'<g clip-path="{sl}"><g transform="scale({sx},1) translate(200,262) rotate(-6)">'
                     f'{arcade(-70, 70, -8, 26, 7, trim, ln)}<rect x="-70" y="22" width="140" height="8" fill="{acc}"{L}/>'
                     f'<rect x="-70" y="34" width="140" height="14" fill="{trim}"{L}/></g></g>')
        g.append(arcade(-170, 170, 376, 30, 14, trim, ln))
        g.append(f'<rect x="-170" y="410" width="340" height="9" fill="{acc}"{L}/>')
        g.append(f'<rect x="-170" y="424" width="340" height="16" fill="{trim}"{L}/>')
        g.append(f'<path d="M-240 112Q-120 80 0 78Q120 80 240 112L240 98Q120 64 0 62Q-120 64 -240 98Z" fill="{trim}"{L}/>')
    elif sport == "soccer":
        for sx in (1, -1):
            g.append(f'<g clip-path="{sl}"><g transform="scale({sx},1) translate(172,142) rotate(-17)">'
                     f'<rect x="-50" y="-6" width="100" height="10" fill="{trim}"{L}/><rect x="-50" y="7" width="100" height="5" fill="{acc}"{L}/></g></g>')
        g.append(f'<rect x="-140" y="428" width="280" height="10" fill="{trim}"{L}/>')
    elif sport == "baseball":
        for sx in (1, -1):
            g.append(f'<g clip-path="{sl}"><g transform="scale({sx},1) translate(182,170) rotate(-11)">'
                     f'<rect x="-60" y="-6" width="120" height="6" fill="{trim}"{L}/><rect x="-60" y="3" width="120" height="4" fill="{acc}"{L}/><rect x="-60" y="10" width="120" height="6" fill="{trim}"{L}/></g></g>')
    elif sport == "basketball":
        g.append(arcade(-160, 160, 416, 30, 12, trim, ln))
        g.append(f'<rect x="-160" y="440" width="320" height="6" fill="{acc}"/>')
    # collar
    nk = neckline(half[0], half[1])
    cw = {"basketball": 13, "hockey": 16}.get(sport, 11)
    g.append(f'<path d="{nk}" fill="none" stroke="{NIGHT}" stroke-width="{cw + 6}" stroke-linejoin="round"/>')
    g.append(f'<path d="{nk}" fill="none" stroke="{trim}" stroke-width="{cw}" stroke-linejoin="round"/>')
    g.append(f'<path d="{nk}" fill="none" stroke="{acc}" stroke-width="2.5" transform="translate(0,{cw * .55:.1f})"/>')
    if sport == "basketball":  # armhole binding
        p0, arm = half[2][1], half[3]
        d = f"M{p0[0]} {p0[1]}C{arm[1][0]} {arm[1][1]} {arm[2][0]} {arm[2][1]} {arm[3][0]} {arm[3][1]}"
        for sx in (1, -1):
            g.append(f'<g transform="scale({sx},1)"><path d="{d}" fill="none" stroke="{NIGHT}" stroke-width="19"/>'
                     f'<path d="{d}" fill="none" stroke="{trim}" stroke-width="13"/>'
                     f'<path d="{d}" fill="none" stroke="{acc}" stroke-width="2.5" transform="translate(-6,4)"/></g>')
    if sport == "hockey" and not back:  # lace-up collar
        y0 = half[0][1]
        g.append(f'<path d="M-14 {y0 - 2}L14 {y0 - 2}L6 {y0 + 54}L-6 {y0 + 54}Z" fill="{NIGHT}"/>')
        for i in range(4):
            yy = y0 + 8 + i * 12
            g.append(f'<path d="M-9 {yy}L9 {yy + 8}M9 {yy}L-9 {yy + 8}" stroke="{acc}" stroke-width="2.4"/>')
    if sport == "baseball" and not back:  # placket
        y0 = half[0][1]
        g.append(f'<rect x="-11" y="{y0}" width="22" height="{456 - y0}" fill="{mix(base, trim, .1)}"/>')
        g.append(f'<path d="M-11 {y0}V456M11 {y0}V456" stroke="{trim}" stroke-width="3"/>')

    # graphics
    if back:
        plate = arc_text(LETTER["word"], LETTER["text"], 52 * LETTER["wscale"], 0, a["plate_y"] + a["plate_r"], a["plate_r"], LETTER["track"])
        g.append(f'<g fill="{NIGHT}" stroke="{NIGHT}" stroke-width="7" stroke-linejoin="round">{plate}</g>')
        g.append(f'<g fill="{k["word"]}">{plate}</g>')
        g.append(number_art(NUMS[sport], 0, a["num_y"], a["num_size"], k, lead))
    elif sport == "football":
        g.append(wordmark("Arkndjl", 40, 0, 112, k))
        g.append(number_art(NUMS[sport], 0, 310, 190, k, lead))
        for sx in (1, -1):  # shoulder numbers
            d2, _ = text(LETTER["num"], NUMS[sport], 44 * LETTER["nscale"], 0, 0)
            g.append(f'<g transform="translate({sx * 162},100) rotate({sx * 14})"><g fill="{k["ring"]}" stroke="{NIGHT}" stroke-width="5" paint-order="stroke">{d2}</g></g>')
    elif sport == "basketball":
        arc = arc_text(LETTER["word"], LETTER["text"], 52 * LETTER["wscale"], 0, 186 + 360, 360, LETTER["track"])
        g.append(f'<g fill="{NIGHT}" stroke="{NIGHT}" stroke-width="7" stroke-linejoin="round">{arc}</g><g fill="{k["word"]}">{arc}</g>')
        g.append(number_art(NUMS[sport], 0, 380, 220, k, lead))
    elif sport == "hockey":
        g.append(crest(0, 230, 92, k, lead))
    elif sport == "soccer":
        g.append(crest(64, 112, 26, k, lead))
        g.append(wordmark("Arkndjl", 58, 0, 220, k))
    else:  # baseball: script across the chest with a swash, small number below
        wy = 196
        g.append(wordmark("Arkndjl", 64, 0, wy, k, 9))
        g.append(f'<path d="M-118 {wy + 16}Q0 {wy + 42} 124 {wy + 4}L124 {wy + 12}Q0 {wy + 54} -118 {wy + 24}Z" fill="{k["word"]}" stroke="{NIGHT}" stroke-width="2.5"/>')
        d, _ = text(LETTER["num"], NUMS[sport], 70 * LETTER["nscale"], -80, wy + 120)
        g.append(f'<g fill="{k["ink"]}" stroke="{NIGHT}" stroke-width="6" paint-order="stroke">{d}</g>')
    if sport == "baseball" and not back:  # buttons over the script, like the real thing
        y0 = half[0][1]
        for i in range(6):
            g.append(f'<circle cx="0" cy="{y0 + 24 + i * 64}" r="4.4" fill="{acc}" stroke="{NIGHT}" stroke-width="1.6"/>')
    return "".join(g)


def clips(uid, body, sleeve):
    if sleeve:
        sp = "M" + "L".join(f"{x} {y}" for x, y in sleeve) + "Z"
        s = f'<path d="{sp}"/><path transform="scale(-1,1)" d="{sp}"/>'
    else:
        s = '<rect x="-1" y="-1" width="1" height="1"/>'
    return f'<clipPath id="{uid}c"><path d="{body}"/></clipPath><clipPath id="{uid}sl">{s}</clipPath>'


def jersey(sport, back, kit, uid):
    """Revival jersey as an SVG <g> centred on x=0, top at y=0 (about 470 tall, 500 wide)."""
    k = KITS[kit]
    half, sleeve, a = shape(sport, back)
    body = sym(half)
    base = k["base"]
    dark = base == BLACK
    out = [clips(uid, body, sleeve)]
    out.append(f'<linearGradient id="{uid}g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{shade(base, .1 if not dark else .07)}"/>'
               f'<stop offset=".55" stop-color="{base}"/><stop offset="1" stop-color="{shade(base, -.16)}"/></linearGradient>')
    out.append(f'<g filter="url(#drop)"><path d="{body}" fill="url(#{uid}g)"/></g>')
    out.append(f'<g clip-path="url(#{uid}c)">')
    if sport in ("football", "basketball"):
        out.append(f'<rect x="-260" y="-10" width="520" height="500" fill="url(#mesh)" opacity="{.1 if not dark else .3}"/>')
    if sport == "hockey":
        out.append(f'<rect x="-260" y="-10" width="520" height="500" fill="url(#knit)" opacity="{.1 if not dark else .3}"/>')
    if sport == "soccer":
        out.append(damask(LILAC if dark else NIGHT, .16 if dark else .08))
    if sport == "baseball":
        out.append(f'<g opacity="{.3 if dark else .28}">' + "".join(
            f'<rect x="{x - .6}" y="0" width="1.2" height="480" fill="{k["trim"]}"/>' for x in range(-252, 260, 14)) + '</g>')
    if dark and sport in ("football", "basketball", "hockey"):  # tonal lancet tracery on the alternates
        out.append(f'<rect x="-260" y="150" width="520" height="340" fill="url(#tracery)" opacity=".1"/>')
    # body shading: side shadows, chest light, folds
    out.append(f'<path d="{body}" fill="none" stroke="{NIGHT}" stroke-width="46" opacity="{.24 if not dark else .5}" filter="url(#soft)"/>')
    out.append(f'<ellipse cx="-40" cy="170" rx="120" ry="150" fill="#fff" opacity="{.16 if not dark else .06}" filter="url(#softer)"/>')
    for d, o in (("M-120 200Q-104 300 -112 430", .22), ("M118 220Q100 310 112 430", .26), ("M-40 330Q-30 390 -46 445", .12),
                 ("M60 300Q74 380 62 445", .14), ("M-150 170Q-120 168 -110 190", .2), ("M150 170Q120 168 110 190", .2)):
        out.append(f'<path d="{d}" fill="none" stroke="{NIGHT}" stroke-width="16" opacity="{o * (1.5 if dark else 1):.2f}" filter="url(#soft)" stroke-linecap="round"/>')
        out.append(f'<path d="{d}" fill="none" stroke="#fff" stroke-width="8" opacity="{o * (.1 if dark else .22):.2f}" filter="url(#soft)" transform="translate(-14,0)" stroke-linecap="round"/>')
    out.append(kit_trim(sport, back, k, half, a, uid))
    out.append(f'<rect x="-260" y="-10" width="520" height="500" fill="#000" filter="url(#grain)" opacity=".16"/>')
    out.append('</g>')
    out.append(f'<path d="{body}" fill="none" stroke="{NIGHT}" stroke-width="4" stroke-linejoin="round"/>')
    out.append(f'<path d="{body}" fill="none" stroke="#fff" stroke-width="1.2" opacity="{.35 if not dark else .2}" transform="translate(-1.5,1.5)"/>')
    return "".join(out)


# ---------- stained glass ----------
def voronoi_cells(seed, n, box):
    """Jittered-grid Voronoi panes: reads as hand-cut glass rather than noise."""
    import numpy as np
    from scipy.spatial import Voronoi
    rnd = np.random.default_rng(seed)
    x0, y0, x1, y1 = box
    cols = max(1, int(math.sqrt(n * (x1 - x0) / (y1 - y0))))
    rows = max(1, n // cols)
    pts = [(x0 + (i + .5 + rnd.uniform(-.36, .36)) * (x1 - x0) / cols,
            y0 + (j + .5 + rnd.uniform(-.36, .36)) * (y1 - y0) / rows) for i in range(cols) for j in range(rows)]
    far = [[x0 - 3000, y0 - 3000], [x1 + 3000, y0 - 3000], [x0 - 3000, y1 + 3000], [x1 + 3000, y1 + 3000]]
    v = Voronoi(np.array(pts + far))
    cells = []
    for i in range(len(pts)):
        reg = v.regions[v.point_region[i]]
        if reg and -1 not in reg:
            cells.append([v.vertices[r] for r in reg])
    return cells


def glass_jersey(sport, back, kit, uid):
    """Stained-glass jersey: tinted panes, light through them, leading over everything."""
    k = KITS[kit]
    half, sleeve, a = shape(sport, back)
    body = sym(half)
    dark = k["base"] == BLACK
    base = "#241a3a" if dark else k["base"]
    seed = sum(map(ord, sport + kit + str(back)))
    rnd = random.Random(seed)
    cells = voronoi_cells(seed, 52, (-250, -10, 250, 480))
    out = [clips(uid, body, sleeve),
           f'<path d="{body}" fill="{TEAL if dark else k["base"]}" filter="url(#glow)" opacity="{.3 if dark else .5}"/>',
           f'<g clip-path="url(#{uid}c)">']
    for poly in cells:
        col = shade(base, rnd.uniform(-.2, .16))
        if rnd.random() < (.16 if dark else .1):
            col = mix(col, TEAL if dark else k["accent"], .35 if dark else .3)
        out.append(f'<path fill="{col}" d="M' + "L".join(f"{x:.1f} {y:.1f}" for x, y in poly) + 'Z"/>')
    out.append(f'<radialGradient id="{uid}lt" cx=".42" cy=".32" r=".75"><stop offset="0" stop-color="#fff" stop-opacity=".32"/>'
               f'<stop offset=".6" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="{NIGHT}" stop-opacity=".45"/></radialGradient>')
    out.append(f'<rect x="-260" y="-10" width="520" height="500" fill="url(#{uid}lt)"/>')
    out.append(f'<rect x="-260" y="-10" width="520" height="500" fill="#fff" filter="url(#glassy)" opacity="{.25 if dark else .55}"/>')
    leads = "".join("M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in poly) + "Z" for poly in cells)
    out.append(f'<path d="{leads}" fill="none" stroke="{NIGHT}" stroke-width="4.5" stroke-linejoin="round"/>')
    out.append(f'<path d="{leads}" fill="none" stroke="#6b5a8a" stroke-width="1.2" opacity=".6" transform="translate(-1,-1)"/>')
    out.append(kit_trim(sport, back, k, half, a, uid, lead=True))
    out.append('</g>')
    out.append(f'<path d="{body}" fill="none" stroke="{NIGHT}" stroke-width="10" stroke-linejoin="round"/>')
    out.append(f'<path d="{body}" fill="none" stroke="#8a7ab0" stroke-width="2" stroke-linejoin="round" opacity=".7"/>')
    return "".join(out)


# ---------- cathedral frame ----------
def lancet(cx, top, w, h):
    """Pointed (equilateral) arch: straight jambs, two arcs of radius w meeting at the apex."""
    spring = top + w * math.sqrt(3) / 2
    x0, x1 = cx - w / 2, cx + w / 2
    return (f"M{x0:.1f} {top + h:.1f}L{x0:.1f} {spring:.1f}A{w:.1f} {w:.1f} 0 0 1 {cx:.1f} {top:.1f}"
            f"A{w:.1f} {w:.1f} 0 0 1 {x1:.1f} {spring:.1f}L{x1:.1f} {top + h:.1f}Z"), spring


def rose(cx, cy, r, n, col):
    """Rose window: ring of n foils and spokes around a quatrefoil."""
    s = [f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="none" stroke="{col}" stroke-width="{r * .07:.1f}"/>']
    for i in range(n):
        t = 2 * math.pi * i / n
        s.append(f'<circle cx="{cx + r * .64 * math.cos(t):.1f}" cy="{cy + r * .64 * math.sin(t):.1f}" r="{r * .26:.1f}" fill="none" stroke="{col}" stroke-width="{r * .045:.1f}"/>')
        u = t + math.pi / n
        s.append(f'<line x1="{cx + r * .32 * math.cos(u):.1f}" y1="{cy + r * .32 * math.sin(u):.1f}" x2="{cx + r * math.cos(u):.1f}" y2="{cy + r * math.sin(u):.1f}" stroke="{col}" stroke-width="{r * .04:.1f}"/>')
    s.append(quatrefoil(cx, cy, r * .4, f'fill="none" stroke="{col}" stroke-width="{r * .045:.1f}"'))
    return "".join(s)


def cathedral_frame(cx, top, w, h, uid, inner):
    """Stone lancet with moulded jambs, rose tracery in the head, light falling through."""
    outer, _ = lancet(cx, top, w + 44, h + 30)
    mid, _ = lancet(cx, top + 14, w + 18, h + 6)
    win, spring = lancet(cx, top + 26, w, h - 12)
    rays = "".join(f'<path d="M{cx - w * .8 + i * w * .34:.1f} {top}L{cx - w * .62 + i * w * .34:.1f} {top}'
                   f'L{cx - w * .1 + i * w * .34:.1f} {top + h + 40}L{cx - w * .45 + i * w * .34:.1f} {top + h + 40}Z" fill="{LILAC}" opacity=".06"/>'
                   for i in range(5))
    return (f'<linearGradient id="{uid}st" x1="0" x2="1"><stop offset="0" stop-color="#54467a"/><stop offset=".5" stop-color="#9d95c6"/><stop offset="1" stop-color="#43365f"/></linearGradient>'
            f'<linearGradient id="{uid}sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#43307a"/><stop offset=".7" stop-color="{DEEP}"/><stop offset="1" stop-color="{NIGHT}"/></linearGradient>'
            f'<clipPath id="{uid}w"><path d="{win}"/></clipPath>'
            f'<path d="{outer}" fill="url(#{uid}st)" stroke="{NIGHT}" stroke-width="4"/>'
            f'<path d="{outer}" fill="#000" filter="url(#grain)" opacity=".4"/>'
            f'<path d="{mid}" fill="{DEEP}" stroke="#b3abda" stroke-width="3"/>'
            f'<path d="{win}" fill="url(#{uid}sky)" stroke="{NIGHT}" stroke-width="4"/>'
            f'<g clip-path="url(#{uid}w)">{rays}<g opacity=".5">{rose(cx, spring - w * .2, w * .27, 8, LILAC)}</g>'
            f'<circle cx="{cx}" cy="{spring - w * .2:.1f}" r="{w * .1:.1f}" fill="{TEAL}" opacity=".18" filter="url(#soft)"/>{inner}</g>'
            f'<path d="{win}" fill="none" stroke="#b3abda" stroke-width="2" opacity=".6"/>'
            + "".join(f'<rect x="{x - 16:.1f}" y="{spring + 10:.1f}" width="32" height="14" rx="3" fill="#9d95c6" stroke="{NIGHT}" stroke-width="3"/>'
                      for x in (cx - w / 2 - 11, cx + w / 2 + 11))
            + f'<rect x="{cx - w / 2 - 34:.1f}" y="{top + h + 18:.1f}" width="{w + 68:.1f}" height="18" rx="3" fill="#9d95c6" stroke="{NIGHT}" stroke-width="3"/>')


# ---------- cards ----------
def label(s, x, y, size, col, name="GrenzeGotisch@600", track=.04):
    d, _ = text(name, s, size, x, y, track=track)
    return f'<g fill="{col}">{d}</g>'


def background(w, h):
    return (f'<radialGradient id="bgr" cx=".5" cy=".42" r=".75"><stop offset="0" stop-color="#3a2a5e"/>'
            f'<stop offset="1" stop-color="{NIGHT}"/></radialGradient><rect width="{w}" height="{h}" fill="url(#bgr)"/>')


def piece(sport, kit, back, mode, x, y, s, uid):
    g = glass_jersey(sport, back, kit, uid) if mode == "glass" else jersey(sport, back, kit, uid)
    return f'<g transform="translate({x:.1f},{y:.1f}) scale({s:.3f})">{g}</g>'


def sport_card(sport, mode):
    """All three kits, front over back, one card per sport."""
    cw = 380
    ch = 470 if mode == "cathedral" else 350
    gap = 40 if mode == "cathedral" else 10
    W, H = cw * 3 + 80, 220 + ch * 2 + gap + (90 if mode == "cathedral" else 50)
    body = [background(W, H)]
    body.append(label(LETTER["text"], W / 2, 110, 86 * LETTER["wscale"], LILAC, LETTER["word"], LETTER["track"]))
    body.append(label(sport.upper() + "  ·  HOME  ·  AWAY  ·  ALTERNATE", W / 2, 162, 30, TEAL, track=.14))
    for i, kit in enumerate(KITS):
        cx = 40 + cw * i + cw / 2
        for j, back in enumerate((False, True)):
            top = 200 + j * (ch + gap)
            uid = f"{sport[:2]}{kit[:2]}{j}"
            if mode == "cathedral":
                inner = piece(sport, kit, back, "revival", cx, top + 200, .52, uid + "k")
                body.append(cathedral_frame(cx, top, cw - 80, ch - 20, uid, inner))
            else:
                body.append(piece(sport, kit, back, mode, cx, top + 20, .7, uid))
        body.append(label(kit.upper(), cx, H - 34, 26, LILAC, track=.16))
    return svg_doc(W, H, "".join(body), f"ARKNDJL {sport} kits")


def lineup(mode, kit="home"):
    cw = 330
    W, H = cw * 5 + 60, 830 if mode == "cathedral" else 560
    body = [background(W, H)]
    body.append(label(LETTER["text"], W / 2, 110, 86 * LETTER["wscale"], LILAC, LETTER["word"], LETTER["track"]))
    body.append(label(kit.upper() + " KITS", W / 2, 160, 28, TEAL, track=.18))
    for i, sport in enumerate(SPORTS):
        cx = 30 + cw * i + cw / 2
        uid = f"L{sport}{kit[:2]}"
        if mode == "cathedral":
            inner = piece(sport, kit, True, "revival", cx, 440, .48, uid + "k")
            body.append(cathedral_frame(cx, 200, cw - 70, 540, uid, inner))
        else:
            body.append(piece(sport, kit, True, mode, cx, 200, .62, uid))
        body.append(label(sport.upper(), cx, H - 22, 24, LILAC, track=.16))
    return svg_doc(W, H, "".join(body), f"ARKNDJL {kit} kits")


def svg_doc(w, h, body, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            f'<title>{title}</title>{defs()}{body}</svg>')


MODES = ["revival", "glass", "cathedral"]
if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--preview"]:
        out = args[1]
        os.makedirs(out, exist_ok=True)
        for m in MODES:
            for s in args[2:] or SPORTS:
                open(os.path.join(out, f"{m}-{s}.svg"), "w").write(sport_card(s, m))
            open(os.path.join(out, f"{m}-lineup.svg"), "w").write(lineup(m))
        print("ok")
        sys.exit()
    out = os.path.join(ROOT, "static", "img", "art")
    # site set: revival kits per sport, each kit's lineup in cathedral windows
    for s in SPORTS:
        open(os.path.join(out, f"arkndjl-jersey-{s}.svg"), "w").write(sport_card(s, os.environ.get("JERSEY_MODE", "revival")))
    for kit in KITS:
        open(os.path.join(out, f"arkndjl-jerseys-{kit}.svg"), "w").write(lineup(os.environ.get("LINEUP_MODE", "cathedral"), kit))
    print("ok")
