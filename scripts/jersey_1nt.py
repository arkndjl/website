"""1NT esports jersey: realistic mockups for the branding guide (content/arkndjl-1nt-kit.md).

The jersey is drawn as SVG (ghost-mannequin cut: body, set-in sleeves, mesh side panels, rib collar, cuffs) with
the 1NT print (wireframe globe, lilac equator band, 1NT wordmark, crest, gamertag and number), then shaded like
fabric: cylinder falloff, drape folds from the armpits, hem ripples, highlights, weave noise, dashed stitching,
and a low-frequency displacement so the print and edges follow the cloth. Chromium (Playwright) rasterises it;
Pillow writes WebP.

The identity comes from 1NT's avatar (the px-1nt sprite in scripts/pixelart.py): a grey wireframe globe, a
glowing lilac equator and tall black 1NT letters with a light rim. Lilac and aquamarine with grey, white and
black only (no dark purple); lettering in Grenze Gotisch.

Run: python3 scripts/jersey_1nt.py            (writes static/img/art/1nt-kit-*.webp and static/fonts/grenze-gotisch.woff2)
     python3 scripts/jersey_1nt.py --preview DIR   (PNGs to DIR, site files untouched)
"""
import io, json, math, os, re, subprocess, sys, tempfile
from PIL import Image

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FONT = os.path.join(ROOT, "brand", "fonts", "gothic", "GrenzeGotisch.ttf")
PIXEL = os.path.join(ROOT, "static", "fonts", "mspgothic-pixel.woff2")
OUT = os.path.join(ROOT, "static", "img", "art")

LILAC, AQUA = "#c8aaf0", "#7fffd4"
INK, CHAR, STEEL, GREY, SILVER, CHALK, WHITE = "#0a0a0a", "#2a2a2c", "#3a3a3a", "#8c8c8c", "#bdbdbd", "#e8e8e8", "#f4f4f4"

# body, trim (collar/cuffs), panel (mesh sides), grid (globe lines) + its opacity, band, letters, rim (letter halo),
# light/shadow: how strong the highlight and multiply shading are on this base
KITS = {
    "home": dict(name="Globe", base="#ececec", trim=INK, panel=STEEL, grid=INK, gop=.13, band=LILAC, ink=INK, rim=WHITE,
                 tip=LILAC, light=.30, shade=1.0),
    "away": dict(name="Night", base="#141416", trim=INK, panel=STEEL, grid=GREY, gop=.30, band=LILAC, ink=WHITE, rim=INK,
                 tip=LILAC, light=.55, shade=.55),
    "alternate": dict(name="Lilac", base=LILAC, trim=INK, panel=CHAR, grid=INK, gop=.14, band=AQUA, ink=INK, rim=WHITE,
                      tip=AQUA, light=.32, shade=.9),
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


def crest(cx, cy, r, band=LILAC, uid="c"):
    """1NT crest: shaded wireframe globe, glowing equator, tall 1NT in Grenze Gotisch with a light rim."""
    s = r / 50
    return (f'<g transform="translate({cx} {cy}) scale({s:.4f})">'
            f'<defs><radialGradient id="cg{uid}" cx=".34" cy=".3" r=".8"><stop offset="0" stop-color="{CHALK}"/>'
            f'<stop offset=".45" stop-color="{SILVER}"/><stop offset=".8" stop-color="{GREY}"/><stop offset="1" stop-color="#666"/></radialGradient>'
            f'<clipPath id="cc{uid}"><circle r="46"/></clipPath></defs>'
            f'<circle r="50" fill="{STEEL}"/><circle r="46" fill="url(#cg{uid})"/>'
            f'<g clip-path="url(#cc{uid})">{grid(0, 0, 46, "#3e3e3e", .9, 1.4)}'
            f'<rect x="-50" y="-3.2" width="100" height="6.4" fill="{band}"/></g>'
            f'<text y="20" text-anchor="middle" font-family="Grenze Gotisch" font-weight="800" font-size="58" '
            f'letter-spacing="-1" fill="{INK}" stroke="{WHITE}" stroke-width="5" paint-order="stroke" '
            f'stroke-linejoin="round">1NT</text></g>')


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
 <feDisplacementMap in="SourceGraphic" in2="n" scale="10" xChannelSelector="R" yChannelSelector="G"/></filter>
<filter id="t{u}" x="0" y="0" width="100%" height="100%">
 <feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="2" seed="4" result="t"/>
 <feColorMatrix in="t" type="saturate" values="0"/><feComponentTransfer><feFuncA type="linear" slope="0" intercept="1"/></feComponentTransfer>
 <feComposite in2="SourceAlpha" operator="in"/></filter>
<filter id="b8{u}"><feGaussianBlur stdDeviation="8"/></filter>
<filter id="b40{u}" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="40"/></filter>
<filter id="g{u}" x="-10%" y="-200%" width="120%" height="500%"><feGaussianBlur stdDeviation="10"/></filter>
</defs>"""
    blur = {}
    def blurf(sd):
        if sd not in blur:
            blur[sd] = f'<filter id="f{sd}{u}" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="{sd}"/></filter>'
        return f"f{sd}{u}"

    neck = NECK_FRONT if side == "front" else NECK_BACK
    p = []  # print, clipped to the body and warped with it
    p.append(grid(500, 470, 440, k["grid"], k["gop"]))
    p.append(f'<rect x="100" y="428" width="800" height="44" fill="{k["band"]}" opacity=".55" filter="url(#g{u})"/>')
    p.append(f'<rect x="100" y="432" width="800" height="36" fill="{k["band"]}"/>')
    p.append(f'<rect x="100" y="422" width="800" height="3" fill="{k["ink"]}" opacity=".55"/><rect x="100" y="475" width="800" height="3" fill="{k["ink"]}" opacity=".55"/>')
    if side == "front":
        p.append(f'<text x="500" y="540" text-anchor="middle" font-family="Grenze Gotisch" font-weight="800" font-size="250" '
                 f'letter-spacing="-4" fill="{k["ink"]}" stroke="{k["rim"]}" stroke-width="14" paint-order="stroke" stroke-linejoin="round">1NT</text>')
        p.append(crest(612, 236, 44, k["band"], u))
        p.append(glyph(362, 206, 46, k["ink"]))
        p.append(f'<text x="385" y="276" text-anchor="middle" font-family="MS PGothic Pixel" font-size="17" letter-spacing="2" fill="{k["ink"]}">ARKNDJL</text>')
        if cap:
            p.append(f'<g transform="translate(612 306)"><rect x="-16" y="-18" width="32" height="36" rx="4" fill="{k["trim"]}" stroke="{k["band"]}" stroke-width="2.5"/>'
                     f'<text y="11" text-anchor="middle" font-family="Grenze Gotisch" font-weight="800" font-size="30" fill="{k["band"]}">C</text></g>')
        p.append(f'<g transform="rotate(-50 190 230)">{flag(fl, 166, 214, 48)}</g>')
        p.append(f'<g transform="rotate(50 812 234)">{glyph(794, 212, 38, k["ink"])}</g>')
    else:
        size = 78 if len(tag) <= 7 else 68 if len(tag) <= 9 else 60
        p.append(f'<text x="500" y="250" text-anchor="middle" font-family="Grenze Gotisch" font-weight="700" font-size="{size}" '
                 f'letter-spacing="3" fill="{k["ink"]}" stroke="{k["rim"]}" stroke-width="6" paint-order="stroke" stroke-linejoin="round">{tag}</text>')
        p.append(f'<text x="500" y="610" text-anchor="middle" font-family="Grenze Gotisch" font-weight="800" font-size="{330 if len(num) < 3 else 280}" '
                 f'letter-spacing="-6" fill="{k["ink"]}" stroke="{k["rim"]}" stroke-width="16" paint-order="stroke" stroke-linejoin="round">{num}</text>')
        p.append(crest(500, 146, 24, k["band"], u + "n"))
        p.append(f'<text x="500" y="770" text-anchor="middle" font-family="MS PGothic Pixel" font-size="16" letter-spacing="3" fill="{k["ink"]}" opacity=".7">ESEA · NORTH AMERICA</text>')

    # construction: panels, cuffs, collar
    c = []
    c.append(f'<path d="{PANEL_L}" fill="{k["panel"]}"/><path d="{PANEL_R}" fill="{k["panel"]}"/>')
    c.append(f'<path d="{PANEL_L}" fill="url(#m{u})"/><path d="{PANEL_R}" fill="url(#m{u})"/>')
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
 <rect x="0" y="0" width="1000" height="920" fill="#888" filter="url(#t{u})" opacity=".10" style="mix-blend-mode:overlay"/>
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
    """Cover: home back (captain) in front of the away front and the alternate, on a studio sweep."""
    bg = ('<defs><radialGradient id="sw" cx=".5" cy=".42" r=".75"><stop offset="0" stop-color="#f7f7f7"/>'
          '<stop offset=".6" stop-color="#dcdcdc"/><stop offset="1" stop-color="#b9b9bb"/></radialGradient>'
          '<radialGradient id="fl" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#000" stop-opacity=".28"/>'
          '<stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient></defs>'
          '<rect width="2400" height="1200" fill="url(#sw)"/>')
    floor = ''.join(f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="34" fill="url(#fl)"/>' for x, y, rx in ((560, 1110, 380), (1840, 1110, 380), (1200, 1150, 460)))
    def at(x, y, s, g):
        return f'<g transform="translate({x} {y}) scale({s})">{g}</g>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2400 1200" width="2400" height="1200">{bg}{floor}'
            + at(60, 200, 1.0, shadowed(jersey("away", "front", None, "ha"), "ha"))
            + at(1340, 200, 1.0, shadowed(jersey("alternate", "front", None, "hl"), "hl"))
            + at(640, 70, 1.12, shadowed(jersey("home", "back", None, "hh"), "hh"))
            + '</svg>')


def svg_roster():
    """The starting five, home backs."""
    parts = []
    for i, pl in enumerate(ROSTER):
        parts.append(f'<g transform="translate({i * 1000} 0)">{shadowed(jersey("home", "back", pl, f"r{i}"), f"r{i}")}</g>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 5000 920" width="5000" height="920">{"".join(parts)}</svg>'


def svg_front(kit):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 920" width="1000" height="920">'
            f'{shadowed(jersey(kit, "front", None, "a"), "a")}</svg>')


def page(svg):
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@font-face{{font-family:"Grenze Gotisch";src:url("file://{os.path.abspath(FONT)}") format("truetype");font-weight:100 900}}
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


def woff2():
    """Grenze Gotisch, Latin subset, for the guide's headings."""
    from fontTools import subset
    opts = subset.Options(); opts.flavor = "woff2"; opts.layout_features = ["*"]
    f = subset.load_font(FONT, opts)
    s = subset.Subsetter(opts); s.populate(unicodes=list(range(0x20, 0x7f)) + [0xb7, 0x2013, 0x2014, 0x2019])
    s.subset(f)
    subset.save_font(f, os.path.join(ROOT, "static", "fonts", "grenze-gotisch.woff2"), opts)


def main():
    preview = None
    if "--preview" in sys.argv:
        preview = sys.argv[sys.argv.index("--preview") + 1]
        os.makedirs(preview, exist_ok=True)
    items = [("1nt-kit-hero", svg_hero(), 1200, 600, 2),
             ("1nt-kit-roster", svg_roster(), 2000, 368, 1.5),
             ("1nt-kit-anatomy", svg_front("home"), 500, 460, 2)]
    items.append(("1nt-kit-crest", '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-54 -54 108 108" width="108" height="108">'
                  + crest(0, 0, 50, LILAC, "x") + "</svg>", 240, 240, 2))
    items += [(f"1nt-kit-{k}", svg_pair(k, None, k[:2]), 1000, 460, 2) for k in KITS]
    with tempfile.TemporaryDirectory() as tmp:
        imgs = render(items, tmp)
    for name, im in imgs.items():
        if preview:
            im.save(os.path.join(preview, name + ".png"))
        else:
            im.save(os.path.join(OUT, name + ".webp"), "WEBP", quality=86, method=6)
            print(name, os.path.getsize(os.path.join(OUT, name + ".webp")) // 1024, "KB")
    if not preview:
        woff2()


if __name__ == "__main__":
    main()
