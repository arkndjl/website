"""1NT logo options: the avatar's globe and lilac equator, reworked as esports marks, lettered in the site's pixel
font (MS PGothic's 16 px bitmap, static/fonts/mspgothic-pixel.woff2), bolded to two-pixel strokes.

Each option is a 512 x 512 SVG. Letters are drawn as pixel cells (no font needed to view the SVGs), with a
white rim and a black outline one cell out, like a sticker, so they read on the globe and on black.

Noah's picks (Oct 27 2026): the Orbit, pixelated (D), is the main logo; the smooth Orbit (C) is the alternate.
Run: python3 scripts/logo_1nt.py --site   (static/img/1nt/1nt-logo.svg = the pixel Orbit, the main logo;
1nt-logo-smooth.svg the smooth alternate; 1nt-logo-mono.svg one colour; 1nt-logo-pixel.svg = 1nt-logo.svg)
     python3 scripts/logo_1nt.py DIR      (every option to DIR/1nt-logo-<option>.svg and DIR/options.json)
"""
import functools, json, math, os, sys, tempfile
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PIXEL = os.path.join(ROOT, "static", "fonts", "mspgothic-pixel.woff2")
LILAC, NIGHT, INK, STEEL, GREY, SILVER, CHALK, WHITE = ("#c8aaf0", "#161619", "#0a0a0a", "#3a3a3a", "#8c8c8c",
                                                         "#bdbdbd", "#e8e8e8", "#f4f4f4")


# ---------- pixel lettering ----------
def bitmap(text, bold=True, gap=1):
    """Cells (x, y) of text in the pixel font at its native 16 px, one cell per pixel; bold doubles each stroke
    to the right, like the avatar's two-cell letters. Returns (cells, width, height)."""
    from fontTools.ttLib import TTFont
    with tempfile.TemporaryDirectory() as tmp:
        f = TTFont(PIXEL); f.flavor = None; ttf = os.path.join(tmp, "px.ttf"); f.save(ttf)
        font = ImageFont.truetype(ttf, 128)
        cells, x0 = set(), 0
        for ch in text:
            im = Image.new("L", (200, 200), 0)
            ImageDraw.Draw(im).text((8, 0), ch, font=font, fill=255)
            g = {(x, y) for y in range(24) for x in range(24) if im.getpixel((x * 8 + 4, y * 8 + 4)) > 127}
            if bold:
                g |= {(x + 1, y) for x, y in g}
            xs = [x for x, _ in g]
            lo, hi = min(xs), max(xs)
            cells |= {(x - lo + x0, y) for x, y in g}
            x0 += hi - lo + 1 + gap
    ys = [y for _, y in cells]
    top = min(ys)
    cells = {(x, y - top) for x, y in cells}
    return cells, x0 - gap, max(ys) - top + 1


def grow(cells, r=1):
    """Square dilation by r cells (keeps pixel corners crisp)."""
    return {(x + dx, y + dy) for x, y in cells for dx in range(-r, r + 1) for dy in range(-r, r + 1)}


def cells_path(cells, s, ox, oy, sy=None):
    """One path of horizontal runs; cells are s wide and sy (default s) tall."""
    sy = sy or s
    out = []
    for y in sorted({y for _, y in cells}):
        xs = sorted(x for x, yy in cells if yy == y)
        i = 0
        while i < len(xs):
            j = i
            while j + 1 < len(xs) and xs[j + 1] == xs[j] + 1:
                j += 1
            out.append(f"M{ox + xs[i] * s:.2f} {oy + y * sy:.2f}h{(j - i + 1) * s:.2f}v{sy:.2f}h-{(j - i + 1) * s:.2f}z")
            i = j + 1
    return "".join(out)


def lettering(text, cx, cy, s, tall=1.45, ink=INK, rim=WHITE, line=INK, rims=(1, 2)):
    """Pixel letters centred on (cx, cy): outline, rim, letters. Cells are tall (like the avatar's tall 1NT), so
    the wide 16 px glyphs condense into an esports wordmark."""
    c, w, h = bitmap(text)
    sy = s * tall
    ox, oy = cx - w * s / 2, cy - h * sy / 2
    return (f'<path d="{cells_path(grow(c, rims[1]), s, ox, oy, sy)}" fill="{line}"/>'
            f'<path d="{cells_path(grow(c, rims[0]), s, ox, oy, sy)}" fill="{rim}"/>'
            f'<path d="{cells_path(c, s, ox, oy, sy)}" fill="{ink}"/>')


# ---------- the 1NT wordmark (drawn, not typeset) ----------
# Heavy pixel capitals in the MS Gothic / DS manner: three-cell strokes on a 13-row grid, the 1 with its flag and
# a foot like the avatar's, chamfered outer corners. Row 6 (the middle row) is the equator: it prints lilac.
def _glyphs():
    one = {(x, y) for y in range(13) for x in range(2, 5)} | {(1, 1), (0, 2), (1, 2), (1, 3)} | {(x, y) for y in (11, 12) for x in range(7)}
    one -= {(0, 12), (6, 12)}
    n = {(x, y) for y in range(13) for x in (0, 1, 2, 7, 8, 9)}
    n |= {(x, y) for y in range(13) for x in range(round(y * 7 / 12), round(y * 7 / 12) + 3) if 0 <= x <= 9}
    n -= {(0, 0), (9, 12)}
    t = {(x, y) for y in range(3) for x in range(11)} | {(x, y) for y in range(3, 13) for x in range(4, 7)}
    t -= {(0, 0), (10, 0)}
    return {"1": (one, 7), "N": (n, 10), "T": (t, 11)}


GLYPHS = _glyphs()


def word_cells(text="1NT", gap=2):
    cells, x0 = set(), 0
    for ch in text:
        g, w = GLYPHS[ch]
        cells |= {(x + x0, y) for x, y in g}
        x0 += w + gap
    return cells, x0 - gap, 13


def wordmark(cx, cy, s, tall=1.15, uid="w", band=LILAC, flat=True, ext_col="#3a3a3a"):
    """1NT centred on (cx, cy) by its letters (the extrusion trails down-right): ink outline, steel extrusion,
    ink keyline, then chrome letters (white top, silver bottom) with the lilac equator row through the middle."""
    c, w, h = word_cells()
    sy = s * tall
    ox, oy = cx - w * s / 2, cy - h * sy / 2
    ext = {(x + d, y + d) for x, y in c for d in (1, 2)} - c
    top = {(x, y) for x, y in c if y < 6}
    mid = {(x, y) for x, y in c if y == 6}
    bot = {(x, y) for x, y in c if y > 6}
    P = lambda cells, col: f'<path d="{cells_path(cells, s, ox, oy, sy)}" fill="{col}"/>'
    base = P(grow(c | ext, 1), INK) + P(ext, ext_col) + P(grow(c, 1) - ext - c, INK)
    if flat:  # one white, the lilac equator row, no gradients (flat like the big esports marks)
        return base + P(top | bot, WHITE) + P(mid, band)
    return (base + P(top, WHITE) + P(mid, band) + P(bot, "#c6c6cc")
            + P({(x, y) for x, y in top if y == 0 or (x, y - 1) not in c}, "#ffffff"))


def word_box(s, tall=1.15):
    c, w, h = word_cells()
    return w * s, h * s * tall


# ---------- the globe ----------
def wire(cx, cy, r, color, op, width):
    out = [f'<g fill="none" stroke="{color}" stroke-opacity="{op}" stroke-width="{width}">',
           f'<line x1="{cx}" y1="{cy - r}" x2="{cx}" y2="{cy + r}"/>']
    for j in range(-9, 10):
        dy = j * r / 9.5
        half = math.sqrt(max(r * r - dy * dy, 0))
        out.append(f'<line x1="{cx - half:.1f}" y1="{cy + dy:.1f}" x2="{cx + half:.1f}" y2="{cy + dy:.1f}"/>')
    for k in (.3, .58, .82, .96):
        out.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{k * r:.1f}" ry="{r}"/>')
    return "".join(out) + "</g>"


def globe(cx, cy, r, uid, ring=STEEL, ringw=None, band=True, band_h=None):
    ringw = ringw or r * .085
    return (f'<defs><radialGradient id="gg{uid}" cx=".34" cy=".3" r=".85"><stop offset="0" stop-color="{CHALK}"/>'
            f'<stop offset=".45" stop-color="{SILVER}"/><stop offset=".8" stop-color="{GREY}"/><stop offset="1" stop-color="#5e5e62"/></radialGradient>'
            f'<clipPath id="gc{uid}"><circle cx="{cx}" cy="{cy}" r="{r}"/></clipPath></defs>'
            f'<circle cx="{cx}" cy="{cy}" r="{r + ringw}" fill="{ring}"/><circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#gg{uid})"/>'
            f'<g clip-path="url(#gc{uid})">{wire(cx, cy, r, "#3e3e3e", .9, r * .022)}'
            + (f'<rect x="{cx - r}" y="{cy - (band_h or r * .15) / 2}" width="{2 * r}" height="{band_h or r * .15}" fill="{LILAC}"/>' if band else "")
            + '</g>')


# ---------- options ----------
def opt_visor():
    """A: the equator leaves the globe as a visor bar with stepped pixel ends; letters ride the bar."""
    cx, cy, r = 256, 256, 168
    bar_h, steps = 46, ""
    for i, (x0, w) in enumerate(((22, 36), (12, 18), (4, 10))):  # stepped ends, widest nearest the globe
        hh = bar_h - i * 12
        steps += (f'<rect x="{x0}" y="{cy - hh / 2}" width="{w}" height="{hh}" fill="{LILAC}"/>'
                  f'<rect x="{512 - x0 - w}" y="{cy - hh / 2}" width="{w}" height="{hh}" fill="{LILAC}"/>')
    return (f'<rect x="56" y="{cy - bar_h / 2 - 8}" width="400" height="{bar_h + 16}" fill="{INK}"/>'
            + globe(cx, cy, r, "a", band=False)
            + f'<rect x="58" y="{cy - bar_h / 2}" width="396" height="{bar_h}" fill="{LILAC}"/>{steps}'
            + lettering("1NT", cx, cy, 9.5))


def opt_shield():
    """B: an esports shield in Night with a steel rim and lilac keyline; the globe sits inside, the band crosses
    the shield, the letters sit on the band."""
    shield = "M256 22 L462 78 L462 268 C462 392 372 456 256 494 C140 456 50 392 50 268 L50 78 Z"
    inner = "M256 46 L438 96 L438 268 C438 378 360 434 256 468 C152 434 74 378 74 268 L74 96 Z"
    return (f'<defs><clipPath id="sc"><path d="{inner}"/></clipPath></defs>'
            f'<path d="{shield}" fill="{STEEL}"/><path d="{inner}" fill="{NIGHT}"/>'
            f'<g clip-path="url(#sc)">{wire(256, 262, 300, GREY, .35, 3)}'
            + globe(256, 250, 138, "b", band=False)
            + f'<rect x="40" y="228" width="432" height="44" fill="{LILAC}"/>'
            f'<rect x="40" y="220" width="432" height="4" fill="{INK}"/><rect x="40" y="276" width="432" height="4" fill="{INK}"/></g>'
            f'<path d="{inner}" fill="none" stroke="{LILAC}" stroke-width="4"/>'
            + lettering("1NT", 256, 250, 8.6))


def sparkle(x, y, c, col=WHITE, core=LILAC):
    """A four-point pixel star of cell size c centred on (x, y)."""
    cells = {(0, -2), (0, -1), (-2, 0), (-1, 0), (1, 0), (2, 0), (0, 1), (0, 2)}
    return (f'<path d="{cells_path(grow({(0, 0)}, 0) | cells, c, x - c / 2, y - c / 2)}" fill="{col}"/>'
            f'<rect x="{x - c / 2}" y="{y - c / 2}" width="{c}" height="{c}" fill="{core}"/>')


def _ell(cx, cy, rx, ry):
    return f"M{cx - rx} {cy}A{rx} {ry} 0 1 0 {cx + rx} {cy}A{rx} {ry} 0 1 0 {cx - rx} {cy}Z"


def opt_orbit(uid="o", mono=None, wired=True, sparkles=True):
    """C, the smooth Orbit (the alternate; the main logo is this pixelated, opt_pixel), drawn as a flat esports mark: flat colour, a bold silhouette,
    sharp tapering swoosh and negative space instead of outlines, so it holds in one colour (mono=colour).
    A two-tone globe with its wire cut out of it, a lilac orbit swoosh tapering to points (thin behind the globe,
    heavy in front, cut clear of the globe), and the 1NT wordmark centred on the globe with its lilac row on the
    equator."""
    cx, cy, r, s, tall = 256, 252, 156, 7.8, 1.15
    sy = s * tall
    rx, tilt = 246, -16
    lit, shade, band, ring = (mono,) * 4 if mono else (CHALK, GREY, LILAC, LILAC)
    rot = f'transform="rotate({tilt} {cx} {cy})"'
    # one unbroken ring: the inner edge is an ellipse raised 8 units, so the band is 16 thick at the far side, 32 at
    # the near side and 22 at the ends, with no tapering to points
    ring_d = f'<path d="{_ell(cx, cy, rx, 86)}{_ell(cx, cy - 8, rx - 22, 62)}" fill-rule="evenodd" {rot}/>'
    front = back = ring_d
    lower = f'<rect x="-300" y="{cy}" width="1112" height="600" {rot}/>'
    upper = f'<rect x="-300" y="-600" width="1112" height="{cy + 601}" {rot}/>'  # 1 unit of overlap: no seam
    w, h = word_box(s, tall)
    gap = 7
    wc = word_cells()[0]
    shadow = set() if mono else {(x + d, y + d) for x, y in wc for d in (1, 2)}
    knock = cells_path(grow(wc | shadow, 3 if mono else 2), s, cx - w / 2, cy - h / 2, sy)  # clear space round the letters
    wire = [f'<line x1="{cx}" y1="{cy - r}" x2="{cx}" y2="{cy + r}"/>']
    for j in (-2, -1, 1, 2):
        dy = j * r / 2.6
        half = math.sqrt(r * r - dy * dy)
        wire.append(f'<line x1="{cx - half:.1f}" y1="{cy + dy:.1f}" x2="{cx + half:.1f}" y2="{cy + dy:.1f}"/>')
    for k in (.42, .8):
        wire.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{k * r:.1f}" ry="{r}"/>')
    defs = (f'<defs><clipPath id="lo{uid}">{lower}</clipPath><clipPath id="up{uid}">{upper}</clipPath>'
            f'<clipPath id="gd{uid}"><circle cx="{cx}" cy="{cy}" r="{r}"/></clipPath>'
            f'<mask id="gm{uid}" maskUnits="userSpaceOnUse" x="0" y="0" width="512" height="512"><rect width="512" height="512" fill="#fff"/>'
            + (f'<g fill="none" stroke="#000" stroke-width="{gap}">{"".join(wire)}</g>' if wired else '')
            + f'<g clip-path="url(#lo{uid})" fill="#000" stroke="#000" stroke-width="{2 * gap + 4}">{front}</g>'
            f'<path d="{knock}" fill="#000"/></mask>'
            f'<mask id="sm{uid}" maskUnits="userSpaceOnUse" x="0" y="0" width="512" height="512"><rect width="512" height="512" fill="#fff"/>'
            f'<path d="{knock}" fill="#000"/></mask>'
            # the far arc is behind the globe: masked off the whole disc, so it never shows through
            # the wire or the letters' clear space
            f'<mask id="bk{uid}" maskUnits="userSpaceOnUse" x="0" y="0" width="512" height="512"><rect width="512" height="512" fill="#fff"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#000"/></mask>'
            f'<clipPath id="kn{uid}"><path d="{knock}"/></clipPath></defs>')
    globe_g = (f'<g mask="url(#gm{uid})"><circle cx="{cx}" cy="{cy}" r="{r}" fill="{shade}"/>'
               f'<g clip-path="url(#gd{uid})"><circle cx="{cx - r * .2}" cy="{cy - r * .16}" r="{r * .9}" fill="{lit}"/>'
               '</g></g>')
    # the equator: one unbroken lilac band across the word only (Noah, Oct 28), straight through the letters (their
    # middle rows and outline, centred on the word), two cells thick like the avatar's. In one colour, hairlines cut
    # either side of it keep it readable.
    bh = 2 * sy
    band_g = (f'<g><rect x="{cx - w / 2 - s:.1f}" y="{cy - bh / 2:.1f}" width="{w + 2 * s:.1f}" height="{bh:.1f}" '
              f'fill="{band}"/></g>')
    if mono:
        cut = ''.join(f'<rect x="0" y="{y:.1f}" width="512" height="{gap}" fill="#000"/>'
                      for y in (cy - bh / 2 - gap, cy + bh / 2))
        defs = defs.replace(f'<path d="{knock}" fill="#000"/></mask><mask id="sm',
                            cut + f'<path d="{knock}" fill="#000"/></mask><mask id="sm', 1)
        defs = defs.replace('</defs>', f'<mask id="bm{uid}" maskUnits="userSpaceOnUse" x="0" y="0" width="512" '
                            f'height="512"><rect width="512" height="512" fill="#fff"/>{cut}'
                            f'<g clip-path="url(#lo{uid})" fill="#000" stroke="#000" stroke-width="{2 * gap}">{front}</g></mask></defs>')
    letters = (wordmark(cx, cy, s, tall, ext_col="#3a3a3a") if not mono else
               f'<path d="{cells_path(word_cells()[0], s, cx - w / 2, cy - h / 2, sy)}" fill="{mono}"/>')
    return (defs + f'<g mask="url(#bk{uid})"><g clip-path="url(#up{uid})" fill="{ring}">{back}</g></g>' + globe_g
            + (f'<g mask="url(#bm{uid})">{letters}</g>' if mono else letters) + band_g
            # the near half of the ring passes in front of everything, the word included, so it is never broken;
            # where it crosses the letters an ink keyline separates them
            + ('' if mono else f'<g clip-path="url(#kn{uid})"><g clip-path="url(#lo{uid})" fill="{INK}" stroke="{INK}" '
               f'stroke-width="{gap}">{front}</g></g>')
            + f'<g clip-path="url(#lo{uid})" fill="{ring}">{front}</g>'
            + ("" if mono or not sparkles else sparkle(430, 118, 7) + sparkle(452, 200, 4)))


def raster(svg_text, size=512):
    """RGBA PIL image of an SVG, drawn by the preinstalled Chromium (Playwright via node)."""
    import subprocess, tempfile
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        src, out, js = (os.path.join(tmp, f) for f in ("in.svg", "out.png", "r.js"))
        open(src, "w").write(svg_text)
        open(js, "w").write(
            "const {chromium}=require('playwright');const fs=require('fs');(async()=>{const b=await chromium.launch();"
            f"const p=await b.newPage({{viewport:{{width:{size},height:{size}}}}});"
            "await p.setContent('<body style=\"margin:0\">'+fs.readFileSync(process.argv[2],'utf8')"
            f".replace('<svg','<svg width=\"{size}\" height=\"{size}\"')+'</body>');"
            f"await p.screenshot({{path:process.argv[3],omitBackground:true,clip:{{x:0,y:0,width:{size},height:{size}}}}});"
            "await b.close();})();")
        subprocess.run(["node", js, src, out], check=True, cwd=ROOT)
        return Image.open(out).convert("RGBA").copy()


GLINT = "#efe6ff"
WIRE_LIT, WIRE_DARK = "#8c8c8c", "#5a5a5a"  # the wire as darker lines on the lit and shaded globe, like the avatar's


@functools.lru_cache(maxsize=None)
def opt_pixel(n=64, spin=None, glint=None, twinkle=0):
    """The main 1NT logo since Oct 27 2026 (Noah): the Orbit drawn natively on a 64-cell grid (8 units a cell), not
    resampled from the vector, so every pixel is a whole cell: the letters land cell for cell on the grid, curves are
    stepped one cell at a time, and nothing is left over from resampling. Painted back to front: the far half of the
    orbit (dim, and only outside the globe, so it can never show in front of it), the two-tone globe with its wire
    drawn one cell wide in darker grey, the near half of the orbit with a one-cell gap where it crosses the globe, the letters with
    their clear space, then the equator, three cells deep (rows 5-7 of the 13-row letters), across the whole globe."""
    q = 512 / n
    cx, cy, r, rx, tilt = 256, 252, 156, 246, math.radians(16)
    ctr = lambda x, y: ((x + .5) * q, (y + .5) * q)
    def unrot(px, py):  # undo the orbit's -16 degree tilt about the globe centre
        dx, dy = px - cx, py - cy
        return dx * math.cos(tilt) - dy * math.sin(tilt), dx * math.sin(tilt) + dy * math.cos(tilt)
    def ell(u, v, ey, a, b):
        return (u / a) ** 2 + ((v - ey) / b) ** 2 <= 1
    in_disc = lambda px, py, rr=r: math.hypot(px - cx, py - cy) <= rr
    allc = [(x, y) for y in range(n) for x in range(n)]
    front, back, ang = set(), set(), {}
    # one unbroken ring: thickness eases from 2 cells at the far side to 4 at the near side, never tapering to a
    # point, so there are no breaks at the ends; the far half is only drawn outside the globe
    for x, y in allc:
        u, v = unrot(*ctr(x, y))
        th = 2 * q + 2 * q * (1 + math.sin(math.atan2(v / 86, u / rx))) / 2
        if not ell(u, v, 0, rx, 86) or ell(u, v, 0, rx - th, 86 - th):
            continue
        ang[(x, y)] = math.atan2(v / 86, u / rx)
        if v >= 0:
            front.add((x, y))
        elif not in_disc(*ctr(x, y)):
            back.add((x, y))
    # wire: each curve stepped across both axes so it stays one cell wide and unbroken
    wire = set()
    def mark(px, py):
        wire.add((int(px // q), int(py // q)))
    for i in range(int(4 * r)):
        t = -r + i / 2
        mark(cx, cy + t)  # meridian
        # meridians: the still logo's at sin(longitude) .42 and .8; animation frames (spin, degrees) turn the globe
        # with meridians every 25 degrees, so a 25-degree turn loops
        ks = (.42, .8, -.42, -.8) if spin is None else [math.sin(math.radians(spin + 25 * j)) for j in range(-4, 5)
                                                         if abs(spin + 25 * j) < 90 and abs(spin + 25 * j) > 1]
        for k in ks:
            a = k * r
            if abs(t) <= r:
                h = a * math.sqrt(1 - (t / r) ** 2); mark(cx + h, cy + t)
            if abs(t) <= abs(a):
                h = r * math.sqrt(1 - (t / a) ** 2); xx = cx + math.copysign(abs(t), a); mark(xx, cy - h); mark(xx, cy + h)
    for j in (-2, -1, 1, 2):
        dy = j * r / 2.6
        half = math.sqrt(r * r - dy * dy)
        for i in range(int(4 * half)):
            mark(cx - half + i / 2, cy + dy)
    wc, ww, wh = word_cells()
    ox, oy = int(cx / q) - ww // 2, int(cy / q) - wh // 2  # letters land on whole cells, centred on the globe
    let = {(x + ox, y + oy) for x, y in wc}
    ext = {(x + d, y + d) for x, y in let for d in (1, 2)} - let
    knock = grow(let | ext, 1)  # the letters' own ink outline is their clear space on the globe
    near = lambda c, s: any((c[0] + i, c[1] + j) in s for i in (-1, 0, 1) for j in (-1, 0, 1))
    cells = {c: LILAC for c in back}  # the far arc, same lilac as the near one so the ring reads whole
    lx, ly = cx - .2 * r, cy - .16 * r
    for x, y in allc:
        px, py = ctr(x, y)
        if not in_disc(px, py) or (x, y) in knock or (x, y) in front or near((x, y), front):
            continue
        lit = math.hypot(px - lx, py - ly) <= .9 * r
        cells[(x, y)] = (WIRE_LIT if lit else WIRE_DARK) if (x, y) in wire else (CHALK if lit else GREY)
    for c in front - knock:
        cells[c] = LILAC
    # drop slivers: globe, arc and orbit pieces smaller than a few cells read as noise, not drawing
    def comps(s):
        s, out = set(s), []
        while s:
            st, comp = [s.pop()], set()
            while st:
                c = st.pop(); comp.add(c)
                for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nb = (c[0] + d[0], c[1] + d[1])
                    if nb in s:
                        s.remove(nb); st.append(nb)
            out.append(comp)
        return out
    for group, least in (({c for c, v in cells.items() if v == LILAC}, 4),
                         ({c for c, v in cells.items() if v == "#836fa0"}, 4)):
        for comp in comps(group):
            if len(comp) < least:
                for c in comp:
                    del cells[c]
    for c in grow(let | ext, 1):
        cells[c] = INK
    for c in ext:
        cells[c] = STEEL
    for c in let:
        cells[c] = WHITE
    # the equator: rows 5-7 of the letters, across the word only and centred on it (Noah, Oct 28), outline included
    for x, y in allc:
        if y - oy in (5, 6, 7) and ox - 1 <= x <= ox + ww:
            cells[(x, y)] = LILAC
    # the near half of the ring passes in front of everything, the word included, with an ink keyline where it
    # crosses the letters, so it is never broken
    over = {c for c in front if c in knock}
    for c in grow(over, 1) - front:
        if c in knock:
            cells[c] = INK
    for c in front:
        cells[c] = LILAC
    # sparkles as clean grid crosses: the big one with a lilac core and two-cell arms, the small one a plain plus
    for (sx, sy), arm, core in (((430, 118), 2, LILAC), ((452, 200), 1, WHITE)):
        gx, gy = int(sx / q), int(sy / q)
        for d in range(-arm, arm + 1):
            cells[(gx + d, gy)] = cells[(gx, gy + d)] = WHITE
        cells[(gx, gy)] = core
    if glint is not None:  # animation: a pale highlight running round the ring (glint = angle in radians)
        for c, a in ang.items():
            if cells.get(c) == LILAC and abs((a - glint + math.pi) % (2 * math.pi) - math.pi) < .13:
                cells[c] = GLINT
    if twinkle:  # animation: the big sparkle shrinks to a plus and the small one to a dot
        for (sx, sy), arm in (((430, 118), 2), ((452, 200), 1)):
            gx, gy = int(sx / q), int(sy / q)
            for d in (-arm, arm):
                cells.pop((gx + d, gy), None); cells.pop((gx, gy + d), None)
    pal = ["#836fa0", GREY, CHALK, WIRE_LIT, WIRE_DARK, INK, STEEL, WHITE, LILAC, GLINT]
    return "".join(f'<path d="{cells_path({k for k, v in cells.items() if v == col}, q, 0, 0)}" fill="{col}"/>'
                   for col in pal if col in cells.values())


OPTIONS = [("visor", "A", "Visor", opt_visor,
            "The equator leaves the globe as a lilac visor bar with stepped pixel ends, and the letters ride the bar. Widest silhouette, strongest at stream size."),
           ("shield", "B", "Shield", opt_shield,
            "A Night-black esports shield with a steel rim and lilac keyline. The globe sits inside, and the band crosses the shield under the letters."),
           ("orbit", "C", "Orbit", opt_orbit,
            "The equator becomes a tilted lilac orbit around the globe, behind at the top and in front at the bottom, with the letters on the globe."),
           ("pixel", "D", "Pixel", opt_pixel,
            "The Orbit logo drawn natively on a 64-cell grid in its own flat palette; the main logo.")]


def svg(inner):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">{inner}</svg>'


def icon16():
    """The 1NT section's 16x16 menu icon (Noah, Oct 28): the logo's planet drawn natively at 16 cells, too small for
    the letters: the two-tone globe with one meridian and two parallels, and the whole lilac orbit ring, its far half
    behind the globe."""
    n, cx, cy, r = 16, 8.0, 8.0, 5.0
    rx, ry, th, tilt = 7.9, 3.0, 1.3, math.radians(18)
    cells, near = {}, set()
    for y in range(n):
        for x in range(n):
            dx, dy = x + .5 - cx, y + .5 - cy
            u, v = dx * math.cos(tilt) - dy * math.sin(tilt), dx * math.sin(tilt) + dy * math.cos(tilt)
            if (u / rx) ** 2 + (v / ry) ** 2 <= 1 < (u / (rx - th)) ** 2 + (v / (ry - th)) ** 2:
                if v >= 0:
                    near.add((x, y))
                else:
                    cells[(x, y)] = LILAC
    for y in range(n):
        for x in range(n):
            px, py = x + .5, y + .5
            if math.hypot(px - cx, py - cy) <= r + .3:
                lit = math.hypot(px - cx + 1.3, py - cy + 1.3) <= r
                wired = x == 8 or y in (5, 10)
                cells[(x, y)] = (WIRE_LIT if lit else WIRE_DARK) if wired else (CHALK if lit else GREY)
    for c in near:
        cells[c] = LILAC
    body = "".join(f'<path d="{cells_path({k for k, v in cells.items() if v == col}, 1, 0, 0)}" fill="{col}"/>'
                   for col in (GREY, CHALK, WIRE_LIT, WIRE_DARK, LILAC) if col in cells.values())
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" shape-rendering="crispEdges">{body}</svg>'


def write_gif(out_dir, frames=24, ms=80):
    """1nt-logo-animated.gif (512 px), -384.gif (the site's: 6 px a cell, so 192 and 128 px displays stay whole-pixel)
    and -256.gif: a seamless loop of the pixel logo on a transparent background.
    Over one loop the globe turns one meridian step (25 degrees, so it repeats), a glint runs once round the orbit in
    the same direction as the globe's near face, and the sparkles blink twice."""
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    fr = []
    for i in range(frames):
        f = i / frames
        s = svg(opt_pixel(spin=12.5 - 25 * f, glint=-math.pi / 2 + 2 * math.pi * f,
                          twinkle=1 if i in (5, 6, 17) else 0)).replace("<svg ", '<svg shape-rendering="crispEdges" ')
        fr.append(raster(s, 512).convert("RGBA"))
    cols = sorted({p[:3] for f in fr for p in f.getdata() if p[3] >= 128})
    idx = {c: i + 1 for i, c in enumerate(cols)}  # index 0 is the transparent background
    pal = [0, 0, 0] + [v for c in cols for v in c]
    pal += [0] * (768 - len(pal))
    for size, name in ((512, "1nt-logo-animated.gif"), (384, "1nt-logo-animated-384.gif"),
                       (256, "1nt-logo-animated-256.gif")):
        ps = []
        for f in fr:
            p = Image.new("P", f.size)
            p.putpalette(pal)
            p.putdata([idx[px[:3]] if px[3] >= 128 else 0 for px in f.getdata()])
            ps.append(p if size == 512 else p.resize((size, size), Image.NEAREST))
        ps[0].save(os.path.join(out_dir, name), save_all=True, append_images=ps[1:], duration=ms, loop=0,
                   transparency=0, disposal=2)


def main():
    if sys.argv[1] == "--site":
        out = os.path.join(ROOT, "static", "img", "1nt")
        os.makedirs(out, exist_ok=True)
        px = opt_pixel()  # the main logo since Oct 27 2026; 1nt-logo-pixel.svg stays as the same file for old links
        for name, inner in (("1nt-logo", px), ("1nt-logo-pixel", px), ("1nt-logo-smooth", opt_orbit()),
                            ("1nt-logo-mono", opt_orbit("m", mono=WHITE))):
            open(os.path.join(out, name + ".svg"), "w").write(svg(inner))
        open(os.path.join(ROOT, "static", "img", "icons", "1nt.svg"), "w").write(icon16())
        return
    if sys.argv[1] == "--gif":  # animated main logo, transparent: globe turns, a glint runs round the ring, sparkles twinkle
        write_gif(sys.argv[2])
        return
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    meta = []
    for key, letter, name, fn, note in OPTIONS:
        s = svg(fn())
        open(os.path.join(out, f"1nt-logo-{key}.svg"), "w").write(s)
        meta.append(dict(key=key, letter=letter, name=name, note=note))
    json.dump(meta, open(os.path.join(out, "options.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
