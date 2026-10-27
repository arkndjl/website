"""1NT sticker capsule: CS2 Major-style team and signature stickers for content/arkndjl-stickers.md.

Layout and finishes follow how Valve's Major capsules are built (studied for reference, nothing copied): every team
gets a team sticker (its logo, die-cut with a white peel border and a small event stamp) and every player a signature
sticker (the autograph written over a small team mark, die-cut around both). Each comes in the Major finishes:
paper (flat print), glitter (sparkle flakes in the ink), holo (iridescent foil in the light areas), foil (chrome) and
gold (the whole sticker in gold leaf). Here the holo and glitter spectra stay in the 1NT palette (lilac, aquamarine,
white, grey); gold is the one colour outside it because the finish is gold by definition.

The art is SVG (the logo via scripts/jersey_1nt.py, autographs written with the Hershey script font as single pen
strokes), Chromium rasterises it, then numpy cuts the die line and lays each finish on the pixels. The page adds the
moving shine on top in CSS, masked by these same images.

The team mark is the 1NT logo (scripts/logo_1nt.py); rerun after it changes.

Needs: pip install Hershey-Fonts fonttools brotli numpy pillow; node with playwright.
Run: python3 scripts/stickers_1nt.py            (writes static/img/stickers/1nt/*.webp)
     python3 scripts/stickers_1nt.py --preview DIR   (PNGs to DIR, site files untouched)
"""
import math, os, sys, tempfile
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jersey_1nt import logo, pixeltext, render, LILAC, WHITE  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "static", "img", "stickers", "1nt")
AQUA, NIGHT = "#7fffd4", "#161619"
S = 600  # canvas, px
EVENT = "ESEA NA 2026"
FINISHES = ["paper", "glitter", "holo", "foil", "gold"]

# starting five: id, signature text, the small raised tag after it, ink, flourish
PLAYERS = [
    ("laursen", "Laursen", "111", LILAC, "swoosh"),
    ("saintz", "Saintz", "", AQUA, "halo"),
    ("mf", "mf", "", WHITE, "underscore"),
    ("chawk", "Chawk", "", LILAC, "wing"),
    ("rezzah", "rezzah", "", AQUA, "double"),
]


def crest_svg(cx, cy, r, uid):
    """The team mark: the 1NT Orbit logo (scripts/logo_1nt.py, picked Oct 27 2026) in a box 2r wide centred on
    (cx, cy), drawn through the jersey script's logo() so both stay in step."""
    return logo(cx, cy - r + 252 * 2 * r / 512, 2 * r, uid)


# ---------- autographs ----------
_H = None


def strokes(text, size, slant):
    """Hershey script strokes for text, cap height `size`, slanted, y down, origin at the left baseline."""
    global _H
    if _H is None:
        from HersheyFonts import HersheyFonts
        _H = HersheyFonts(); _H.load_default_font("scriptc"); _H.normalize_rendering(100)
    k = size / 100
    return [[(x * k + y * k * slant, -y * k) for x, y in st] for st in _H.strokes_for_text(text)]


def bbox(sts):
    xs = [p[0] for s in sts for p in s]; ys = [p[1] for s in sts for p in s]
    return min(xs), max(xs), min(ys), max(ys)


def smooth(pts, n=4):
    """Catmull-Rom through the Hershey points, so the pen line reads as ink, not a polyline."""
    if len(pts) < 3:
        return pts
    P = [pts[0]] + pts + [pts[-1]]
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for j in range(n):
            t = j / n; t2, t3 = t * t, t * t * t
            out.append(tuple(.5 * ((2 * p1[a]) + (-p0[a] + p2[a]) * t + (2 * p0[a] - 5 * p1[a] + 4 * p2[a] - p3[a]) * t2
                                   + (-p0[a] + 3 * p1[a] - 3 * p2[a] + p3[a]) * t3) for a in (0, 1)))
    out.append(pts[-1])
    return out


def path(pts):
    return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts)


def flourish(kind, x0, x1, base, size):
    """Pen strokes after the name: each player signs a little differently."""
    w = x1 - x0
    if kind == "swoosh":  # a long rising underline that hooks back
        return [[(x0 + w * t, base + size * (.32 - .22 * t) + size * .08 * math.sin(t * math.pi)) for t in np.linspace(-.04, 1.02, 30)]
                + [(x1 + size * .1, base - size * .05), (x1 - size * .05, base + size * .02)]]
    if kind == "halo":  # a halo ring over the first letter
        cx, cy = x0 + size * .38, base - size * 1.32
        return [[(cx + size * .34 * math.cos(a), cy + size * .1 * math.sin(a)) for a in np.linspace(.3, 2 * math.pi + .9, 34)]]
    if kind == "underscore":  # the handle's underscore as one long flat stroke
        return [[(x0 - size * .05, base + size * .26), (x1 + size * .55, base + size * .12)]]
    if kind == "wing":  # a check that opens like a wing
        return [[(x1 - w * .12, base + size * .05), (x1 + size * .05, base + size * .3), (x1 + size * .45, base - size * .7)]]
    if kind == "double":  # two quick underlines
        return [[(x0 + w * .05, base + size * .2), (x1 + size * .05, base + size * .12)],
                [(x0 + w * .25, base + size * .36), (x1 - w * .1, base + size * .3)]]
    return []


def autograph(text, tag, ink, kind, cx, cy, width):
    """The signature: script strokes slanted and fitted to `width`, a flourish, the raised tag; ink over a dark
    outline so it reads on the crest and on the white border."""
    size = 100
    sts = strokes(text, size, .18)
    l, r, t, b = bbox(sts)
    tag_sts = []
    if tag:
        tag_sts = strokes(tag, size * .5, .18)
        tl, tr, tt, tb = bbox(tag_sts)
        tag_sts = [[(x - tl + r + size * .08, y - size * .55) for x, y in s] for s in tag_sts]
        r = max(r, bbox(tag_sts)[1])
    fl = flourish(kind, l, r, 0, size)
    allp = sts + tag_sts + fl
    L, R, T, B = bbox(allp)
    k = min(width / (R - L), 240 / (B - T))  # short handles stop at a height, long ones at the width
    ox, oy = cx - (L + R) / 2 * k, cy - (T + B) / 2 * k
    tf = lambda s: [(x * k + ox, y * k + oy) for x, y in s]
    d = " ".join(path(smooth(tf(s))) for s in allp)
    pen = 7.5 * k
    return (f'<g fill="none" stroke-linecap="round" stroke-linejoin="round">'
            f'<path d="{d}" stroke="{NIGHT}" stroke-width="{pen + 9:.1f}"/>'
            f'<path d="{d}" stroke="{ink}" stroke-width="{pen:.1f}"/>'
            f'<path d="{d}" stroke="#ffffff" stroke-opacity=".45" stroke-width="{pen * .3:.1f}" transform="translate(-1 -1.5)"/></g>')


def stamp(cx, cy, text, h=15):
    """The event stamp Majors print small on each sticker: pixel font, grey on the peel border."""
    return pixeltext(text, cx, cy, h, "#7a7a80")


def plate(cx, cy, text):
    """A small tab with the event under a signature, part of the die-cut, like a Major autograph's stamp."""
    w, h = 210, 34
    return (f'<rect x="{cx - w / 2}" y="{cy - h / 2}" width="{w}" height="{h}" rx="7" fill="{NIGHT}"/>'
            f'<rect x="{cx - w / 2 + 3}" y="{cy - h / 2 + 3}" width="{w - 6}" height="{h - 6}" rx="5" fill="none" stroke="{LILAC}" stroke-width="1.5"/>'
            + pixeltext(text, cx, cy, 14, "#e8e8e8"))


def svg_team():
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}" width="{S}" height="{S}">'
            + crest_svg(S / 2, S / 2 - 6, 262, "t") + "</svg>")


def svg_sig(p):
    pid, text, tag, ink, kind = p
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}" width="{S}" height="{S}">'
            + f'<g opacity=".8">{crest_svg(S / 2, 230, 158, pid)}</g>'
            + autograph(text, tag, ink, kind, S / 2, 300, 470)
            + plate(S / 2, 470, f"1NT · {EVENT}") + "</svg>")


# ---------- die-cut and finishes ----------

def shrink(mask, px):
    m = mask
    while px > 0:
        step = min(px, 6)
        m = m.filter(ImageFilter.MinFilter(2 * step + 1)); px -= step
    return m


def round_grow(mask, px):
    """Grow a mask by px with round corners (blur, then a low threshold), in steps so the reach stays even."""
    m = mask
    while px > 0:
        step = min(px, 8)
        m = m.filter(ImageFilter.GaussianBlur(step / 2)).point(lambda v: 255 if v > 6 else 0); px -= step
    return m


def diecut(art, border, close):
    """White peel border: the art's silhouette grown by `border` px, closed (grow, then shrink) so thin strokes and
    gaps merge into one sticker, edges softened."""
    a = art.getchannel("A").point(lambda v: 255 if v > 24 else 0)
    m = round_grow(a, border + close)
    m = ImageOps.invert(round_grow(ImageOps.invert(m), close))  # closing: grow, then shrink back
    m = m.filter(ImageFilter.GaussianBlur(1.6)).point(lambda v: 255 if v > 127 else 0)
    outside = m.copy(); ImageDraw.floodfill(outside, (0, 0), 128)  # holes are whatever the outside can't reach
    m = outside.point(lambda v: 0 if v == 128 else 255).filter(ImageFilter.GaussianBlur(.8))
    return np.asarray(m, dtype=np.float32) / 255


RAMP = {
    "holo": [LILAC, AQUA, "#f4f4f4", "#bdbdbd", LILAC],
    "gold": ["#3a2708", "#7d5a15", "#c39a35", "#ecd07a", "#fff6d2"],
    "foil": ["#202024", "#55555c", "#a4a4ac", "#e9e9f0", "#ffffff"],
}


def hexrgb(h):
    h = h.lstrip("#"); return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.float32)


def ramp(name, v):
    """Map v in [0, 1] (any shape) through a colour ramp."""
    stops = np.stack([hexrgb(c) for c in RAMP[name]])
    v = np.clip(v, 0, 1) * (len(stops) - 1)
    i = np.minimum(v.astype(int), len(stops) - 2); f = (v - i)[..., None]
    return stops[i] * (1 - f) + stops[i + 1] * f


def finish(art, cut, kind, seed):
    """Compose one finish: the art over its white border, then the finish laid on the pixels."""
    rng = np.random.default_rng(seed)
    A = np.asarray(art, np.float32) / 255
    rgb, aa = A[..., :3] * 255, A[..., 3:4]
    h, w = cut.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    lum = (rgb @ np.array([.299, .587, .114], np.float32)) / 255
    border = np.full((h, w, 3), 250, np.float32)
    if kind == "gold":
        border = ramp("gold", .78 + .12 * np.sin((xx + yy) / w * 5.0))
    elif kind == "foil":
        border = ramp("foil", .8 + .15 * np.sin((xx * .7 + yy) / w * 7.0))
    out = border * (1 - aa) + rgb * aa
    phase = ((xx * .65 + yy) / w * 2.2)
    if kind == "paper":
        out += rng.normal(0, 3.2, (h, w, 1))
    elif kind == "glitter":
        flake = (rng.random((h, w)) < .028).astype(np.float32)
        flake = np.asarray(Image.fromarray((flake * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3)), np.float32) / 255 * (rng.random((h, w)) > .5)
        tint = np.stack([hexrgb(c) for c in (LILAC, AQUA, "#ffffff", "#ffffff")])[rng.integers(0, 4, (h, w))]
        sparkle = flake[..., None] * aa
        out = out * (1 - .85 * sparkle) + tint * .85 * sparkle
        out += rng.normal(0, 14, (h, w, 1)) * aa  # the speckle under the flakes
    elif kind == "holo":
        irid = ramp("holo", (phase + lum * .9) % 1.0)
        lines = .5 + .5 * np.sin((xx + yy * .35) * .9)
        k = (.08 + .85 * lum ** 1.4)[..., None] * aa  # dark ink stays dark, light areas go fully holo
        out = out * (1 - k) + irid * k
        out += (lines[..., None] - .5) * 18 * aa
        bk = .3 * (1 - aa)  # a thin holo sheen on the border too
        out = out * (1 - bk) + ramp("holo", phase % 1.0) * bk
    elif kind == "foil":
        v = .15 + .75 * lum + .22 * np.sin(phase * 2 * math.pi + lum * 3)
        chrome = ramp("foil", v)
        k = .72 * aa
        out = out * (1 - k) + (chrome * .85 + rgb * .15) * k
    elif kind == "gold":
        v = .12 + .8 * lum + .14 * np.sin(phase * 2 * math.pi + lum * 2.5)
        out = out * (1 - aa) + ramp("gold", v) * aa
    out = np.clip(out, 0, 255)
    rgba = np.dstack([out, cut[..., None] * 255]).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def edge(img, cut):
    """A thin grey kiss-cut line inside the border edge, as on a real sticker."""
    m = Image.fromarray((cut * 255).astype(np.uint8))
    inner = np.asarray(shrink(m, 2), np.float32) / 255
    ring = np.clip(cut - inner, 0, 1)[..., None]
    a = np.asarray(img, np.float32)
    a[..., :3] = a[..., :3] * (1 - .35 * ring) + 150 * .35 * ring
    return Image.fromarray(a.astype(np.uint8), "RGBA")


def sheet(imgs):
    """The gallery tile: the six holo stickers on a grey backing sheet."""
    W, H = 1200, 900
    bg = Image.new("RGBA", (W, H), (214, 214, 218, 255))
    g = np.asarray(bg, np.float32)
    rng = np.random.default_rng(7)
    g[..., :3] += rng.normal(0, 2.5, (H, W, 1))
    bg = Image.fromarray(np.clip(g, 0, 255).astype(np.uint8), "RGBA")
    spots = [("team", 600, 300, 520), ("laursen", 210, 230, 330), ("saintz", 990, 230, 330),
             ("mf", 210, 650, 330), ("chawk", 600, 700, 330), ("rezzah", 990, 650, 330)]
    for pid, cx, cy, sz in spots:
        im = imgs[(pid, "holo")].resize((sz, sz), Image.LANCZOS)
        sh = Image.new("RGBA", im.size, (0, 0, 0, 0)); sh.putalpha(im.getchannel("A").point(lambda v: v * .35))
        sh = sh.filter(ImageFilter.GaussianBlur(6))
        bg.alpha_composite(sh, (cx - sz // 2 + 3, cy - sz // 2 + 8)); bg.alpha_composite(im, (cx - sz // 2, cy - sz // 2))
    return bg.convert("RGB")


def main():
    preview = None
    if "--preview" in sys.argv:
        preview = sys.argv[sys.argv.index("--preview") + 1]
        os.makedirs(preview, exist_ok=True)
    items = [("team", svg_team(), S, S, 1)] + [(p[0], svg_sig(p), S, S, 1) for p in PLAYERS]
    with tempfile.TemporaryDirectory() as tmp:
        arts = render(items, tmp)
    out = {}
    for n, (pid, art) in enumerate(arts.items()):
        if pid == "team":  # the event stamp sits on the border under the logo
            st = render_stamp()  # drawn centred at S / 2; moved to just under the mark's lowest pixel
            bottom = art.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()[3]
            art = art.copy(); art.alpha_composite(st, (0, bottom + 15 - S // 2))
            cut = diecut(art, 26, 10)
        else:
            cut = diecut(art, 20, 34)
        for f in FINISHES:
            out[(pid, f)] = edge(finish(art, cut, f, 11 * n + FINISHES.index(f)), cut)
    dest = preview or OUT
    os.makedirs(dest, exist_ok=True)
    for (pid, f), im in out.items():
        if preview:
            im.save(os.path.join(dest, f"{pid}-{f}.png"))
        else:
            im.resize((480, 480), Image.LANCZOS).save(os.path.join(dest, f"{pid}-{f}.webp"), "WEBP", quality=88, method=6)
    sh = sheet(out)
    if preview:
        sh.save(os.path.join(dest, "sheet.png"))
    else:
        sh.save(os.path.join(ROOT, "static", "img", "art", "1nt-stickers-sheet.webp"), "WEBP", quality=86, method=6)
        total = sum(os.path.getsize(os.path.join(dest, x)) for x in os.listdir(dest))
        print(len(out), "stickers,", total // 1024, "KB")


_STAMP = None


def render_stamp():
    """The team sticker's event stamp, rendered once on a transparent canvas the size of the sticker."""
    global _STAMP
    if _STAMP is None:
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}" width="{S}" height="{S}">'
               + stamp(S / 2, S / 2, EVENT, 13) + "</svg>")
        with tempfile.TemporaryDirectory() as tmp:
            _STAMP = render([("stamp", svg, S, S, 1)], tmp)["stamp"]
    return _STAMP


if __name__ == "__main__":
    main()
