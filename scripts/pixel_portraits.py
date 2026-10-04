#!/usr/bin/env python3
"""Turn photos and logos into small pixel-art images (needs ImageMagick).

    python3 scripts/pixel_portraits.py           # make anything missing
    python3 scripts/pixel_portraits.py --force   # remake everything

Each source is cropped square, shrunk to a small grid (32 or 48 px) and cut down to a
limited palette without dithering, so it reads as pixel art. Pages show the result scaled
up by a whole number with image-rendering: pixelated (see .pxphoto in static/style.css).

PEOPLE: the person is cut out of the photo (a transparent PNG, or a flat backdrop
flood-filled away), framed head and shoulders centred on their head, and set on a flat
team-colour background, as a smooth 192 x 192 photo.
"""
import os, subprocess, sys, tempfile, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "arkndjl.net pixel portraits (https://arkndjl.net)"

# out (under static/) -> (source url, square crop "WxH+X+Y" of the source or None if it is square, grid, colours)
PORTRAITS = {
    "img/px/laursen.png": ("https://distribution.faceit-cdn.net/images/c3a31e6a-3dc2-415b-b4ab-7fa87d0dea42.jpg", None, 40, 16),
}


# out -> (source url, backdrop fuzz % or None if the PNG is already cut out, background colour,
#         frame size as a multiple of the figure's narrower side: larger shows more around the head)
PEOPLE = {
    "img/athletes/brunson.png": ("https://a.espncdn.com/i/headshots/nba/players/full/3934672.png", None, "#006bb6", 1.2),
    # MLB's cut-out ("silo") headshots: Longoria's current one is in Rays colours; deGrom's 2022 one is a Mets photo
    "img/athletes/longoria.png": ("https://img.mlbstatic.com/mlb-photos/image/upload/w_426,q_auto:best/v1/people/446334/headshot/silo/current", None, "#8fbce6", 1.2),
    "img/athletes/degrom.png": ("https://img.mlbstatic.com/mlb-photos/image/upload/w_426,q_auto:best/v1/people/594798/headshot/silo/2022", None, "#ff5910", 1.2),
    "img/athletes/david-wright.png": ("https://img.mlbstatic.com/mlb-photos/image/upload/w_426,q_auto:best/v1/people/431151/headshot/67/current", 9, "#ff5910", 1.45),
}


def pixels(path):
    """(width, height, {(x, y): (r, g, b, a)}) from ImageMagick's txt: output, channels 0-255, alpha 0-1."""
    out = subprocess.run(["convert", path, "-depth", "8", "txt:-"], capture_output=True, text=True, check=True).stdout.splitlines()
    w, h = (int(v) for v in out[0].split(":")[1].split(",")[:2])  # "# ImageMagick pixel enumeration: W,H,255,srgba"
    px = {}
    for line in out[1:]:
        xy, rest = line.split(":", 1)
        x, y = map(int, xy.split(","))
        v = [float(t.rstrip("%")) for t in rest.split("(")[1].split(")")[0].split(",")]
        a = v[3] if len(v) > 3 else 1.0
        px[(x, y)] = (v[0], v[1], v[2], a if a <= 1 else a / 255)
    return w, h, px


def person(out, url, fuzz, bg, zoom, size=192):
    path = os.path.join(ROOT, "static", out)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src, cut = (os.path.join(tmp, n) for n in ("src", "cut.png"))
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r, open(src, "wb") as f:
            f.write(r.read())
        args = ["convert", src + "[0]", "-alpha", "set"]
        if fuzz:  # clear the studio backdrop from all four corners
            sw, sh = (int(v) for v in subprocess.run(["identify", "-format", "%w %h", src + "[0]"], capture_output=True,
                                                      text=True, check=True).stdout.split())
            args += ["-fuzz", f"{fuzz}%", "-fill", "none"]
            for x, y in ((0, 0), (sw - 1, 0), (0, sh - 1), (sw - 1, sh - 1)):
                args += ["-draw", f"matte {x},{y} floodfill"]
        subprocess.run(args + ["-trim", "+repage", "-resize", "480x480>", cut], check=True)
        w, h, px = pixels(cut)
        solid = {k for k, v in px.items() if v[3] > .5}
        top = min(y for _, y in solid)
        head = [x for x, y in solid if y < top + h * .3]  # the head: the top 30 % of the figure
        cx = sum(head) / len(head)
        side = round(min(w, h) * zoom)  # head and shoulders, with room around them
        x0 = round(cx - side / 2)
        y0 = top - round(side * .1)  # headroom
        pad = side  # the frame may run past the photo: pad it with transparency first
        subprocess.run(["convert", cut, "-background", "none", "-bordercolor", "none", "-border", str(pad), cut], check=True)
        x0, y0 = x0 + pad, y0 + pad
        subprocess.run(["convert", cut, "-crop", f"{side}x{side}+{x0}+{y0}", "+repage", "-resize", f"{size}x{size}!",
                        "-background", bg, "-alpha", "remove", "-alpha", "off", "-strip", path], check=True)
    print(f"  made  {out}")


def make(out, url, crop, grid, colours):
    path = os.path.join(ROOT, "static", out)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r, tempfile.NamedTemporaryFile(suffix=".img") as src:
        src.write(r.read())
        src.flush()
        args = ["convert", src.name + "[0]", "-background", "#2b2140", "-flatten"]
        if crop:  # without one the source is taken as already square
            args += ["-crop", crop, "+repage"]
        args += ["-filter", "box", "-resize", f"{grid}x{grid}!", "+dither", "-colors", str(colours), "-strip", path]
        subprocess.run(args, check=True)
    print(f"  made  {out}")


def main():
    force = "--force" in sys.argv
    for out, (url, crop, grid, colours) in PORTRAITS.items():
        if force or not os.path.exists(os.path.join(ROOT, "static", out)):
            make(out, url, crop, grid, colours)
    for out, (url, fuzz, bg, zoom) in PEOPLE.items():
        if force or not os.path.exists(os.path.join(ROOT, "static", out)):
            person(out, url, fuzz, bg, zoom)


if __name__ == "__main__":
    main()
