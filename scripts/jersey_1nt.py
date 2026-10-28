"""1NT esports jersey: realistic mockups for the branding guide (content/arkndjl-1nt-kit.md).

The jersey is drawn as SVG (ghost-mannequin cut: body, set-in sleeves, mesh side panels, rib collar, cuffs) with
the 1NT print (wireframe globe, lilac equator band, logo, gamertag and number), then shaded like
fabric: cylinder falloff, drape folds from the armpits, hem ripples, highlights, weave noise, dashed stitching,
and a low-frequency displacement so the print and edges follow the cloth. Chromium (Playwright) rasterises it;
Pillow writes WebP.

The identity comes from 1NT's avatar (the px-1nt sprite in scripts/pixelart.py): a grey wireframe globe, a
glowing lilac equator and tall black 1NT letters with a light rim. Lilac and aquamarine with grey, white and
black only (no dark purple). The chest and nape marks are the 1NT Orbit logo (scripts/logo_1nt.py); every letter is the
site's MS PGothic pixel font (Noah, Oct 27 2026: no other face anywhere).

Run: python3 scripts/jersey_1nt.py            (writes static/img/art/1nt-kit-*.webp)
     python3 scripts/jersey_1nt.py --preview DIR   (PNGs to DIR, site files untouched)
"""
import io, json, math, os, re, subprocess, sys, tempfile

import logo_1nt
from PIL import Image

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PIXEL = os.path.join(ROOT, "static", "fonts", "mspgothic-pixel.woff2")
OUT = os.path.join(ROOT, "static", "img", "art")

LILAC = "#c8aaf0"
INK, CHAR, STEEL, GREY, SILVER, CHALK, WHITE = "#0a0a0a", "#2a2a2c", "#3a3a3a", "#8c8c8c", "#bdbdbd", "#e8e8e8", "#f4f4f4"

# body, trim (collar/cuffs), panel (mesh sides), grid (globe lines) + its opacity, band, letters, rim (letter halo),
# light/shadow: how strong the highlight and multiply shading are on this base
# 1NT has one kit, Night (Noah, Oct 27 2026): black body, grey globe lines, glowing lilac equator, white letters.
# weave: fabric-noise strength (black needs more to read as cloth)
KITS = {
    "night": dict(name="Night", base="#161619", trim=INK, panel="#2c2c30", grid=GREY, gop=.34, band=LILAC, ink=WHITE, rim=INK,
                  tip=LILAC, light=.62, shade=.6, weave=.15),
}
# starting five: gamertag, number, flag; the captain wears C on the chest
ROSTER = [("LAURSEN_111", "111", "dk", True), ("Saintz", "5", "us", False), ("mf_", "23", "us", False),
          ("Chawk", "4", "us", False), ("rezzah", "9", "ca", False)]

# ---------- geometry (viewBox 0 0 1000 920; chest 512 wide, 728 long from the neck point, a tee's ~.7) ----------
def mirror(d):
    """Reflect a path's x coordinates about x = 500 (every number pair is x y)."""
    toks = re.findall(r"[A-Za-z]|-?[\d.]+", d)
    out, xy = [], 0
    for tk in toks:
        if tk.isalpha():
            out.append(tk); xy = 0; continue
        v = float(tk)
        out.append(f"{1000 - v:g}" if xy % 2 == 0 else tk); xy += 1
    return " ".join(out)

BODY = ("M 420 92 C 450 72, 550 72, 580 92 L 724 130 C 790 152, 860 220, 904 292 L 796 384 "
        "C 782 362, 768 346, 756 334 C 758 440, 752 560, 756 660 C 758 730, 754 780, 752 820 "
        "C 640 842, 360 842, 248 820 C 246 780, 242 730, 244 660 C 248 560, 242 440, 244 334 "
        "C 232 346, 218 362, 204 384 L 96 292 C 140 220, 210 152, 276 130 Z")
NECK_FRONT = "M 420 92 C 445 128, 555 128, 580 92"
NECK_BACK = "M 420 92 C 450 104, 550 104, 580 92"
NECK_TOP = "M 420 92 C 450 72, 550 72, 580 92"
ARM_L = "M 276 130 C 290 200, 276 280, 244 334"
PANEL_L = "M 244 334 L 278 346 C 286 480, 280 680, 286 828 L 248 820 C 246 780, 242 730, 244 660 C 248 560, 242 440, 244 334 Z"
SEAM_L = "M 278 346 C 286 480, 280 680, 286 828"
CUFF_L = "M 83 313 L 191 405 L 220 358 L 112 266 Z"
CUFF_SEAM_L, TIP_L = "M 112 266 L 220 358", "M 102 282 L 208 372"
SHOULDER_L = "M 420 92 L 276 130"
ARM_R, PANEL_R, SEAM_R, CUFF_R, CUFF_SEAM_R, TIP_R, SHOULDER_R = map(mirror, (ARM_L, PANEL_L, SEAM_L, CUFF_L, CUFF_SEAM_L, TIP_L, SHOULDER_L))
# chest marks and sleeve patches (see jersey()): the sleeve centre is the middle of the armhole seam, armpit,
# cuff seam quad; its cuff runs at atan2(92, 108) = 40.4 degrees
CHEST_DX, CHEST_Y = 112, 236
SLEEVE_X, SLEEVE_Y, SLEEVE_A = 213, 272, 40.4
HEM = "M 250 804 C 360 826, 640 826, 750 804"

# soft folds: (path, width, blur, opacity); highlights run beside them
_F = [("M 262 352 C 320 396, 372 432, 400 482", 34, 14, .26),
      ("M 286 630 C 312 672, 318 722, 310 790", 22, 12, .16),
      ("M 236 190 C 210 230, 190 262, 170 296", 22, 12, .18)]
FOLDS = _F + [(mirror(d), w, b, o) for d, w, b, o in _F] + [
    ("M 330 566 C 420 600, 580 600, 670 566", 26, 18, .10),
    ("M 402 832 C 406 796, 412 774, 424 744", 16, 8, .18), ("M 562 834 C 566 796, 572 770, 584 746", 16, 8, .16),
    ("M 476 838 C 476 812, 480 794, 486 780", 10, 6, .12),
    ("M 424 104 C 450 146, 550 146, 576 104", 18, 8, .30),
]
SHINES = [
    ("M 282 356 C 336 398, 384 432, 412 476", 18, 14, .9), (mirror("M 284 360 C 336 398, 380 430, 406 470"), 14, 14, .6),
    ("M 304 650 C 328 690, 334 736, 328 790", 12, 12, .6), ("M 418 832 C 422 796, 428 776, 438 748", 10, 8, .6),
    ("M 218 186 C 196 226, 176 256, 158 288", 14, 10, .7),
]


def grid(cx, cy, r, color, op, width=2.4):
    """The wireframe globe: parallels as chords every r/9.5, meridians as ellipses."""
    out = [f'<g fill="none" stroke="{color}" stroke-opacity="{op}" stroke-width="{width}">',
           f'<circle cx="{cx}" cy="{cy}" r="{r}"/>', f'<line x1="{cx}" y1="{cy - r}" x2="{cx}" y2="{cy + r}"/>']
    step = r / 9.5
    for j in range(-9, 10):
        dy = j * step
        half = math.sqrt(max(r * r - dy * dy, 0))
        out.append(f'<line x1="{cx - half:.1f}" y1="{cy + dy:.1f}" x2="{cx + half:.1f}" y2="{cy + dy:.1f}"/>')
    for k in (.3, .58, .82, .96):
        out.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{k * r:.1f}" ry="{r}"/>')
    out.append("</g>")
    return "".join(out)


_FONTS = {}


def ink(text):
    """Per-glyph (advance, ink bounds) at 1 em in the site's pixel font."""
    if not _FONTS:
        from fontTools.ttLib import TTFont
        f = TTFont(PIXEL)
        _FONTS["px"] = (f.getGlyphSet(), f.getBestCmap(), f["head"].unitsPerEm)
    from fontTools.pens.boundsPen import BoundsPen
    gs, cmap, upm = _FONTS["px"]
    out = []
    for ch in text:
        name = cmap[ord(ch)]
        bp = BoundsPen(gs); gs[name].draw(bp)
        out.append((gs[name].width / upm, bp.bounds and [v / upm for v in bp.bounds]))
    return out


def pixeltext(text, cx, cy, height, fill, rim=None, sw=0, spacing=0.0, maxw=None):
    """Pixel-font text whose ink box is centred on (cx, cy) with the given ink height, shrunk to maxw. Positioned
    from the outlines, so it is optically centred whatever the anchor rules."""
    g = ink(text)
    def box(size):
        x, xs, ys = 0.0, [], []
        for i, (adv, b) in enumerate(g):
            if b:
                xs += [x + b[0] * size, x + b[2] * size]; ys += [b[1] * size, b[3] * size]
            x += adv * size + (spacing * size if i < len(g) - 1 else 0)
        return min(xs), max(xs), min(ys), max(ys)
    l, r, bot, top = box(1.0)
    size = height / (top - max(bot, 0))
    if maxw and (r - l) * size > maxw:
        size = maxw / (r - l)
    l, r, bot, top = box(size)
    x0 = cx - (l + r) / 2
    base = cy + (top + max(bot, 0)) / 2
    head = f'<text x="{x0:.1f}" y="{base:.1f}" font-size="{size:.1f}" letter-spacing="{spacing * size:.2f}" '
    # pixel font: its strokes are one pixel (1/16 em) wide, so a same-colour stroke of .75 pixel makes them bold
    # like the avatar's letters without closing small counters; the rim is a wider copy underneath
    px = size / 16 * .75
    out = ""
    if rim:
        out += f'{head}font-family="MS PGothic Pixel" fill="{rim}" stroke="{rim}" stroke-width="{px + 2 * sw:.1f}" stroke-linejoin="miter">{text}</text>'
    return out + f'{head}font-family="MS PGothic Pixel" fill="{fill}" stroke="{fill}" stroke-width="{px:.1f}" stroke-linejoin="miter">{text}</text>'


def logo(cx, cy, width, uid, kind="pixel"):
    """The 1NT logo (scripts/logo_1nt.py): the pixel Orbit, the main logo since Oct 27 2026 (or kind="smooth"),
    scaled to width and placed so its equator sits on (cx, cy)."""
    sc = width / 512
    inner = logo_1nt.opt_pixel() if kind == "pixel" else logo_1nt.opt_orbit("lg" + uid)
    ey = 252
    return f'<g transform="translate({cx - 256 * sc:.1f} {cy - ey * sc:.1f}) scale({sc:.4f})">{inner}</g>'


def glyph(x, y, size, color):
    """The ARKNDJL site glyph (static/style.css --px-glyph), as the sponsor mark."""
    s = size / 840.4
    return (f'<g transform="translate({x} {y}) scale({s:.5f}) translate(68.2 795.4) scale(1 -1)"><path fill="{color}" '
            'd="M52 0V45.9H98.8L243.6 263H42.8L352 750.3L661.2 263H460.4L604.2 45.9H652V0H491V45.9H523.6L376 269L388 272.8V45.9'
            'H429V0H275V45.9H316V272.8L328 269L179.4 45.9H213V0ZM191.3 342.2H512.7L352 596.3Z"/></g>')


def flag(code, x, y, w):
    """Small flag patches (drawn, not images) for the sleeve: Denmark, USA, Canada."""
    h = w * .66
    if code == "dk":
        return (f'<g transform="translate({x} {y})"><rect width="{w}" height="{h}" fill="#c8102e"/>'
                f'<rect x="{w * .32}" width="{w * .12}" height="{h}" fill="#fff"/><rect y="{h * .43}" width="{w}" height="{h * .14}" fill="#fff"/></g>')
    if code == "ca":
        return (f'<g transform="translate({x} {y})"><rect width="{w}" height="{h}" fill="#fff"/>'
                f'<rect width="{w * .25}" height="{h}" fill="#d52b1e"/><rect x="{w * .75}" width="{w * .25}" height="{h}" fill="#d52b1e"/>'
                f'<path d="M{w * .5} {h * .2} l{w * .07} {h * .2} l{w * .08} -{h * .04} l-{w * .03} {h * .26} h-{w * .24} l-{w * .03} -{h * .26} l{w * .08} {h * .04} z" fill="#d52b1e"/></g>')
    stripes = "".join(f'<rect y="{i * h / 7:.2f}" width="{w}" height="{h / 14:.2f}" fill="#b22234"/>' for i in range(7))
    return (f'<g transform="translate({x} {y})"><rect width="{w}" height="{h}" fill="#fff"/>{stripes}'
            f'<rect width="{w * .42}" height="{h * .54}" fill="#3c3b6e"/></g>')


def jersey(kit, side, player=None, uid="j"):
    """One jersey, front or back, as an SVG group in the 1000 x 1080 box."""
    k = KITS[kit]
    tag, num, fl, cap = player or ROSTER[0]
    u = f"{uid}{kit[:2]}{side[0]}"
    defs = f"""<defs>
<clipPath id="s{u}"><path d="{BODY}"/></clipPath>
<pattern id="m{u}" width="8" height="8" patternUnits="userSpaceOnUse"><circle cx="4" cy="4" r="1.7" fill="#000" fill-opacity=".45"/></pattern>
<linearGradient id="cy{u}" gradientUnits="userSpaceOnUse" x1="70" x2="930" y1="0" y2="0">
 <stop offset="0" stop-opacity=".22"/><stop offset=".19" stop-opacity=".30"/><stop offset=".25" stop-opacity=".10"/>
 <stop offset=".38" stop-opacity="0"/><stop offset=".62" stop-opacity="0"/><stop offset=".75" stop-opacity=".12"/>
 <stop offset=".81" stop-opacity=".34"/><stop offset="1" stop-opacity=".26"/></linearGradient>
<linearGradient id="vy{u}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".0"/>
 <stop offset=".7" stop-color="#000" stop-opacity=".0"/><stop offset="1" stop-color="#000" stop-opacity=".16"/></linearGradient>
<filter id="w{u}" x="-5%" y="-5%" width="110%" height="110%">
 <feTurbulence type="fractalNoise" baseFrequency=".0055" numOctaves="2" seed="{7 if side == 'front' else 11}" result="n"/>
 <feDisplacementMap in="SourceGraphic" in2="n" scale="6" xChannelSelector="R" yChannelSelector="G"/></filter>
<filter id="t{u}" x="0" y="0" width="100%" height="100%">
 <feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="2" seed="4" result="t"/>
 <feColorMatrix in="t" type="saturate" values="0"/><feComponentTransfer><feFuncA type="linear" slope="0" intercept="1"/></feComponentTransfer>
 <feComposite in2="SourceAlpha" operator="in"/></filter>
<filter id="b8{u}"><feGaussianBlur stdDeviation="8"/></filter>
<filter id="b40{u}" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="40"/></filter>
<filter id="g{u}" x="-10%" y="-200%" width="120%" height="500%"><feGaussianBlur stdDeviation="14"/></filter>
<linearGradient id="gl{u}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset=".55" stop-color="#f0f0f3"/><stop offset="1" stop-color="#c9c9cf"/></linearGradient>
<filter id="hp{u}" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="2.5" stdDeviation="1.8" flood-color="#000" flood-opacity=".65"/></filter>
<radialGradient id="gm{u}" gradientUnits="userSpaceOnUse" cx="500" cy="450" r="520"><stop offset="0" stop-color="#fff"/><stop offset=".55" stop-color="#fff" stop-opacity=".75"/><stop offset="1" stop-color="#fff" stop-opacity=".25"/></radialGradient>
<mask id="gk{u}"><rect width="1000" height="920" fill="url(#gm{u})"/></mask>
<linearGradient id="pp{u}" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".035"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
</defs>"""
    blur = {}
    def blurf(sd):
        if sd not in blur:
            blur[sd] = f'<filter id="f{sd}{u}" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="{sd}"/></filter>'
        return f"f{sd}{u}"

    neck = NECK_FRONT if side == "front" else NECK_BACK
    p = []  # print, clipped to the body and warped with it
    p.append(f'<g mask="url(#gk{u})">{grid(500, 470, 440, k["grid"], k["gop"])}</g>')
    p.append(f'<rect x="100" y="424" width="800" height="52" fill="{k["band"]}" opacity=".75" filter="url(#g{u})"/>')
    p.append(f'<rect x="100" y="432" width="800" height="36" fill="{k["band"]}"/>')
    p.append(f'<rect x="100" y="422" width="800" height="3" fill="{k["ink"]}" opacity=".55"/><rect x="100" y="475" width="800" height="3" fill="{k["ink"]}" opacity=".55"/>')
    if side == "front":
        # chest: the crest is the chest mark, centred, its equator on the band; sponsor (wearer's right) and the
        # captain's C (left) mirror each other above it, 11 cm out and 13 cm under the shoulder seam
        p.append(f'<g filter="url(#hp{u})">{logo(500, 450, 440, u)}</g>')
        # the glyph, with the logo designer's handle under it in place of a wordmark (Noah, Oct 27 2026)
        p.append(glyph(500 - CHEST_DX - 23, CHEST_Y - 40, 46, k["ink"]))
        # +1: half the trailing letter-spacing, which text-anchor counts as part of the run
        p.append(f'<text x="{500 - CHEST_DX + 1}" y="{CHEST_Y + 26}" text-anchor="middle" font-family="MS PGothic Pixel" font-size="17" letter-spacing="2" '
                 f'fill="{k["ink"]}">maceyrose</text>')
        if cap:
            p.append(f'<g transform="translate({500 + CHEST_DX} {CHEST_Y})"><rect x="-22" y="-26" width="44" height="52" fill="{k["trim"]}" stroke="{k["band"]}" stroke-width="3"/>'
                     + pixeltext("C", 0, 0, 28, k["band"]) + "</g>")
        # jock tag: woven label at the wearer's left hem, as on match shirts
        p.append(f'<g transform="translate(652 742)" filter="url(#hp{u})"><rect x="-32" y="-16" width="64" height="32" fill="{k["trim"]}" stroke="{k["band"]}" stroke-width="2"/>'
                 f'<text y="6" text-anchor="middle" font-family="MS PGothic Pixel" font-size="18" fill="{k["band"]}">1NT</text></g>')
        # sleeve patches: centred on each sleeve, level with the cuff (so upright when the arm hangs)
        if fl:  # the player's own flag; the retail shirt has none
            p.append(f'<g transform="translate({SLEEVE_X} {SLEEVE_Y}) rotate({SLEEVE_A})">{flag(fl, -24, -16, 48)}</g>')
        p.append(f'<g transform="translate({1000 - SLEEVE_X} {SLEEVE_Y}) rotate({-SLEEVE_A})">{logo(0, 0, 76, u + "sl")}</g>')  # the 1NT logo, not the glyph (Noah, Oct 28)
    else:
        # back: number centred on the band, nameplate centred above it, both on the centre line
        # site pixel font: nameplate above, number centred on the band like the avatar's letters on its equator
        # heat-pressed: a soft gloss down the letters and a shadow where the film stands off the cloth
        p.append(f'<g filter="url(#hp{u})">' + pixeltext(tag, 500, 258, 46, f"url(#gl{u})", k["rim"], 6, .02, maxw=420) + "</g>")
        p.append(f'<g filter="url(#hp{u})">' + pixeltext(num, 500, 450, 236, f"url(#gl{u})", k["rim"], 12, -.02, maxw=360) + "</g>")
        p.append(logo(500, 148, 64, u + "n"))

    # construction: panels, cuffs, collar
    c = []
    c.append(f'<path d="{PANEL_L}" fill="{k["panel"]}"/><path d="{PANEL_R}" fill="{k["panel"]}"/>')
    c.append(f'<path d="{PANEL_L}" fill="url(#m{u})"/><path d="{PANEL_R}" fill="url(#m{u})"/>')
    c.append(f'<path d="{SEAM_L}" fill="none" stroke="{k["band"]}" stroke-width="3"/><path d="{SEAM_R}" fill="none" stroke="{k["band"]}" stroke-width="3"/>')
    c.append(f'<path d="{CUFF_L}" fill="{k["trim"]}"/><path d="{CUFF_R}" fill="{k["trim"]}"/>')
    c.append(f'<path d="{TIP_L}" stroke="{k["tip"]}" stroke-width="4"/><path d="{TIP_R}" stroke="{k["tip"]}" stroke-width="4"/>')
    if side == "front":  # the inside of the back neck shows above the front collar (ghost mannequin)
        c.append(f'<path d="{NECK_TOP} C 555 128, 445 128, 420 92 Z" fill="{k["trim"]}"/>')
        c.append(f'<path d="{NECK_TOP} C 555 128, 445 128, 420 92 Z" fill="#000" opacity=".45"/>')
        c.append(f'<path d="M 482 96 C 494 94, 506 94, 518 96 L 517 110 C 506 109, 494 109, 483 110 Z" fill="{WHITE}" opacity=".92"/>'
                 f'<text x="500" y="106" text-anchor="middle" font-family="MS PGothic Pixel" font-size="9" fill="{INK}">L</text>')
        c.append(f'<path d="{NECK_TOP}" fill="none" stroke="{k["trim"]}" stroke-width="16"/>')
    c.append(f'<path d="{neck}" fill="none" stroke="{k["trim"]}" stroke-width="22" stroke-linecap="round"/>')
    c.append(f'<path d="{neck}" transform="translate(0 {12 if side == "front" else 10})" fill="none" stroke="{k["tip"]}" stroke-width="3.5"/>')

    # stitching
    seams = [ARM_L, ARM_R, SEAM_L, SEAM_R, CUFF_SEAM_L, CUFF_SEAM_R, HEM, SHOULDER_L if side == "back" else "", SHOULDER_R if side == "back" else ""]
    st = "".join(f'<path d="{d}" fill="none" stroke="#000" stroke-opacity=".38" stroke-width="1.8" stroke-dasharray="6 4"/>'
                 f'<path d="{d}" transform="translate(1.6 1.6)" fill="none" stroke="#fff" stroke-opacity=".22" stroke-width="1.2" stroke-dasharray="6 4"/>'
                 for d in seams if d)
    st += (f'<path d="{neck}" transform="translate(0 {24 if side == "front" else 22})" fill="none" stroke="#000" stroke-opacity=".35" stroke-width="1.6" stroke-dasharray="5 4"/>')

    folds = "".join(f'<path d="{d}" fill="none" stroke="#000" stroke-opacity="{o * k["shade"]:.3f}" stroke-width="{w}" stroke-linecap="round" filter="url(#{blurf(b)})"/>'
                    for d, w, b, o in FOLDS if side == "front" or "424 104" not in d)
    shines = "".join(f'<path d="{d}" fill="none" stroke="#fff" stroke-opacity="{o * k["light"]:.3f}" stroke-width="{w}" stroke-linecap="round" filter="url(#{blurf(b)})"/>'
                     for d, w, b, o in SHINES)
    if side == "back":  # shoulder blades read on the back instead of the chest drape
        folds += (f'<path d="M 370 300 C 412 340, 436 380, 440 420" fill="none" stroke="#000" stroke-opacity="{.12 * k["shade"]:.3f}" stroke-width="40" filter="url(#{blurf(18)})"/>'
                  f'<path d="M 630 300 C 588 340, 564 380, 560 420" fill="none" stroke="#000" stroke-opacity="{.12 * k["shade"]:.3f}" stroke-width="40" filter="url(#{blurf(18)})"/>'
                  f'<path d="M 440 120 C 470 140, 530 140, 560 120" fill="none" stroke="#000" stroke-opacity=".22" stroke-width="16" filter="url(#{blurf(8)})"/>')

    body = f"""<g filter="url(#w{u})">
<path d="{BODY}" fill="{k['base']}"/>
<g clip-path="url(#s{u})" style="isolation:isolate">
 {''.join(p)}
 {''.join(c)}
 {st}
 <g style="mix-blend-mode:multiply"><rect x="0" y="0" width="1000" height="920" fill="url(#cy{u})"/><rect x="0" y="0" width="1000" height="920" fill="url(#vy{u})"/>{folds}</g>
 <g style="mix-blend-mode:screen"><ellipse cx="{410 if side == 'front' else 590}" cy="330" rx="130" ry="170" fill="#fff" fill-opacity="{.20 * k['light']:.3f}" filter="url(#b40{u})"/>{shines}</g>
 <rect x="0" y="0" width="1000" height="920" fill="#888" filter="url(#t{u})" opacity="{k.get('weave', .10)}" style="mix-blend-mode:overlay"/>
 <rect x="0" y="0" width="1000" height="920" fill="url(#pp{u})" style="mix-blend-mode:screen"/>
 <path d="{BODY}" fill="none" stroke="#fff" stroke-opacity="{.10 * k['light']:.3f}" stroke-width="14" filter="url(#{blurf(6)})" style="mix-blend-mode:screen"/>
</g>
<path d="{BODY}" fill="none" stroke="#000" stroke-opacity=".28" stroke-width="2"/>
</g>"""
    return defs.replace("</defs>", "".join(blur.values()) + "</defs>") + body


def shadowed(inner, uid):
    return (f'<defs><filter id="ds{uid}" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="22" stdDeviation="20" '
            f'flood-color="#000" flood-opacity=".30"/></filter></defs><g filter="url(#ds{uid})">{inner}</g>')


def svg_pair(kit, player=None, uid="p"):
    """Front and back side by side, transparent background."""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2000 920" width="2000" height="920">'
            f'<g transform="translate(0 0)">{shadowed(jersey(kit, "front", player, uid + "f"), uid + "f")}</g>'
            f'<g transform="translate(1000 0)">{shadowed(jersey(kit, "back", player, uid + "b"), uid + "b")}</g></svg>')


def svg_hero():
    """Cover: the captain's back behind the front, overlapped like a product shot, on a studio sweep."""
    bg = ('<defs><radialGradient id="sw" cx=".5" cy=".4" r=".8"><stop offset="0" stop-color="#f2f2f3"/>'
          '<stop offset=".55" stop-color="#d4d4d7"/><stop offset="1" stop-color="#a7a7ac"/></radialGradient>'
          '<radialGradient id="fl" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#000" stop-opacity=".34"/>'
          '<stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient></defs>'
          '<rect width="2400" height="1200" fill="url(#sw)"/>')
    floor = ''.join(f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="36" fill="url(#fl)"/>' for x, y, rx in ((820, 1110, 440), (1550, 1150, 500)))
    def at(x, y, s, g):
        return f'<g transform="translate({x} {y}) scale({s})">{g}</g>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2400 1200" width="2400" height="1200">{bg}{floor}'
            + at(330, 150, .98, shadowed(jersey("night", "back", None, "hb"), "hb"))
            + at(1000, 80, 1.1, shadowed(jersey("night", "front", None, "hf"), "hf"))
            + '</svg>')


def svg_roster():
    """The starting five's backs."""
    parts = []
    for i, pl in enumerate(ROSTER):
        parts.append(f'<g transform="translate({i * 1000} 0)">{shadowed(jersey("night", "back", pl, f"r{i}"), f"r{i}")}</g>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 5000 920" width="5000" height="920">{"".join(parts)}</svg>'


def svg_front(kit):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 920" width="1000" height="920">'
            f'{shadowed(jersey(kit, "front", None, "a"), "a")}</svg>')


def page(svg):
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@font-face{{font-family:"MS PGothic Pixel";src:url("file://{os.path.abspath(PIXEL)}") format("woff2")}}
html,body{{margin:0;background:transparent}} svg{{display:block}}</style></head><body>{svg}</body></html>"""


RENDER_JS = r"""
const {chromium} = require('playwright');
(async () => {
  const jobs = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));
  const b = await chromium.launch();
  for (const j of jobs) {
    const p = await b.newPage({viewport: {width: j.w, height: j.h}, deviceScaleFactor: j.scale});
    await p.goto('file://' + j.html);
    await p.evaluate(() => document.fonts.ready);
    await p.waitForTimeout(150);
    await p.screenshot({path: j.png, omitBackground: true, clip: {x: 0, y: 0, width: j.w, height: j.h}});
    await p.close();
  }
  await b.close();
})();
"""


def render(items, tmp):
    """items: (name, svg, css width, css height, scale) -> {name: PIL image}"""
    jobs = []
    for name, svg, w, h, scale in items:
        html = os.path.join(tmp, name + ".html")
        sized = svg.replace('width="', 'data-w="', 1).replace('height="', 'data-h="', 1).replace("<svg ", f'<svg width="{w}" height="{h}" ', 1)
        open(html, "w").write(page(sized))
        jobs.append(dict(html=html, png=os.path.join(tmp, name + ".png"), w=w, h=h, scale=scale))
    jf = os.path.join(tmp, "jobs.json")
    json.dump(jobs, open(jf, "w"))
    js = os.path.join(tmp, "render.js")
    open(js, "w").write(RENDER_JS)
    subprocess.run(["node", js, jf], check=True, cwd=tmp)
    return {name: Image.open(os.path.join(tmp, name + ".png")).copy() for name, *_ in items}


RETAIL = ("YourName", "99", None, False)  # the shirt as sold: placeholder name and number, no flag or captain's C


def svg_banner():
    """FACEIT team cover, 1920 x 480 (4:1, FACEIT's organizer cover spec; the logo stays inside the central 8:3,
    1280 px wide, so a club-style crop keeps it): the Night shirt's globe print and lilac equator, the pixel logo
    centred on the band, a few grid sparkles."""
    W, H, cy = 1920, 480, 240
    stars = "".join(logo_1nt.sparkle(x, y, c) for x, y, c in ((300, 96, 6), (520, 380, 4), (1460, 110, 4), (1640, 360, 6), (180, 300, 4), (1790, 170, 4)))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">'
            '<defs><radialGradient id="bv" cx=".5" cy=".5" r=".75"><stop offset="0" stop-color="#232327"/><stop offset="1" stop-color="#0c0c0e"/></radialGradient>'
            '<radialGradient id="bm" gradientUnits="userSpaceOnUse" cx="960" cy="240" r="1000"><stop offset="0" stop-color="#fff"/><stop offset=".5" stop-color="#fff" stop-opacity=".6"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>'
            f'<mask id="bk"><rect width="{W}" height="{H}" fill="url(#bm)"/></mask>'
            '<filter id="bg" x="-5%" y="-300%" width="110%" height="700%"><feGaussianBlur stdDeviation="16"/></filter></defs>'
            f'<rect width="{W}" height="{H}" fill="url(#bv)"/>'
            f'<g mask="url(#bk)">{grid(960, cy, 900, GREY, .22, 2)}</g>'
            f'<rect x="0" y="{cy - 22}" width="{W}" height="44" fill="{LILAC}" opacity=".7" filter="url(#bg)"/>'
            f'<rect x="0" y="{cy - 14}" width="{W}" height="28" fill="{LILAC}"/>'
            f'<rect x="0" y="{cy - 24}" width="{W}" height="3" fill="{WHITE}" opacity=".5"/><rect x="0" y="{cy + 21}" width="{W}" height="3" fill="{WHITE}" opacity=".5"/>'
            f'<g shape-rendering="crispEdges">{stars}{logo(960, cy, 440, "bn")}</g></svg>')


def retail_items():
    """The shareable sales set (Noah, Oct 27 2026): YourName #99 on the back, full-size PNGs."""
    def one(side, uid):
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 920" width="1000" height="920">'
                f'{shadowed(jersey("night", side, RETAIL, uid), uid)}</svg>')
    bg = ('<defs><radialGradient id="sw" cx=".5" cy=".4" r=".8"><stop offset="0" stop-color="#2a2a2f"/>'
          '<stop offset=".6" stop-color="#18181b"/><stop offset="1" stop-color="#0c0c0e"/></radialGradient>'
          '<radialGradient id="fl" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#000" stop-opacity=".6"/>'
          '<stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient></defs>'
          '<rect width="2400" height="1200" fill="url(#sw)"/>')
    floor = ''.join(f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="36" fill="url(#fl)"/>' for x, y, rx in ((820, 1110, 440), (1550, 1150, 500)))
    hero = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2400 1200" width="2400" height="1200">{bg}{floor}'
            f'<g transform="translate(330 150) scale(.98)">{shadowed(jersey("night", "back", RETAIL, "rb"), "rb")}</g>'
            f'<g transform="translate(1000 80) scale(1.1)">{shadowed(jersey("night", "front", RETAIL, "rf"), "rf")}</g></svg>')
    pair = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2000 920" width="2000" height="920">'
            f'<g>{shadowed(jersey("night", "front", RETAIL, "pf"), "pf")}</g>'
            f'<g transform="translate(1000 0)">{shadowed(jersey("night", "back", RETAIL, "pb"), "pb")}</g></svg>')
    return [("1nt-faceit-banner", svg_banner(), 1920, 480, 1), ("1nt-night-hero", hero, 1200, 600, 2), ("1nt-night-front-back", pair, 1000, 460, 2),
            ("1nt-night-front", one("front", "of"), 1000, 920, 2), ("1nt-night-back", one("back", "ob"), 1000, 920, 2)]


def main():
    if "--retail" in sys.argv:  # python3 scripts/jersey_1nt.py --retail DIR
        out = sys.argv[sys.argv.index("--retail") + 1]
        os.makedirs(out, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            for name, im in render(retail_items(), tmp).items():
                im.save(os.path.join(out, name + ".png"), optimize=True)
                print(name, im.size, os.path.getsize(os.path.join(out, name + ".png")) // 1024, "KB")
        return
    preview = None
    if "--preview" in sys.argv:
        preview = sys.argv[sys.argv.index("--preview") + 1]
        os.makedirs(preview, exist_ok=True)
    items = [("1nt-kit-hero", svg_hero(), 1200, 600, 2),
             ("1nt-kit-roster", svg_roster(), 2000, 368, 1.5),
             ("1nt-kit-anatomy", svg_front("night"), 500, 460, 2)]
    items.append(("1nt-kit-crest", '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-54 -54 108 108" width="108" height="108">'
                  + logo(0, 0, 108, "x") + "</svg>", 240, 240, 2))
    items += [(f"1nt-kit-{k}", svg_pair(k, None, k[:2]), 1000, 460, 2) for k in KITS]
    with tempfile.TemporaryDirectory() as tmp:
        imgs = render(items, tmp)
    for name, im in imgs.items():
        if preview:
            im.save(os.path.join(preview, name + ".png"))
        else:
            im.save(os.path.join(OUT, name + ".webp"), "WEBP", quality=86, method=6)
            print(name, os.path.getsize(os.path.join(OUT, name + ".webp")) // 1024, "KB")


if __name__ == "__main__":
    main()
