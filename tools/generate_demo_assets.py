"""Generate the soft landscape images used by the PixelMint marketing visuals.

Run from the project root (only needed if you want to regenerate the assets):

    .\\.venv\\Scripts\\python.exe tools\\generate_demo_assets.py

Everything is drawn procedurally with Pillow, so the project ships no
third-party photographs. The script also prints the real file sizes so the
static labels in the templates can be kept honest.
"""

import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "optimizer" / "static" / "optimizer" / "img"


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient(size, stops):
    """Vertical multi-stop gradient. stops = [(position 0..1, (r, g, b)), ...]"""
    w, h = size
    img = Image.new("RGB", size)
    px = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if p0 <= t <= p1:
                px.line([(0, y), (w, y)], fill=lerp(c0, c1, (t - p0) / (p1 - p0 or 1)))
                break
    return img


def ridge(width, base_y, amplitude, rng, roughness=0.55, steps=7):
    """Mid-point displacement ridge line -> list of y values per x."""
    n = 2**steps
    pts = [base_y + rng.uniform(-amplitude, amplitude) for _ in (0, 1)]
    spread = amplitude
    while len(pts) < n + 1:
        nxt = []
        for a, b in zip(pts, pts[1:]):
            nxt += [a, (a + b) / 2 + rng.uniform(-spread, spread)]
        nxt.append(pts[-1])
        pts = nxt
        spread *= roughness
    return [pts[min(len(pts) - 1, round(x / width * (len(pts) - 1)))] for x in range(width + 1)]


def pines(draw, rng, y_base, x0, x1, count, color, scale=1.0):
    for _ in range(count):
        x = rng.uniform(x0, x1)
        h = rng.uniform(40, 90) * scale
        w = h * 0.38
        for i in range(3):
            top = y_base - h + i * h * 0.26
            draw.polygon(
                [(x, top), (x - w * (0.55 + i * 0.22), top + h * 0.42), (x + w * (0.55 + i * 0.22), top + h * 0.42)],
                fill=color,
            )
        draw.rectangle([x - 2, y_base - h * 0.12, x + 2, y_base], fill=color)


def landscape(size, seed, palette):
    rng = random.Random(seed)
    w, h = size
    horizon = int(h * 0.60)

    sky = gradient((w, horizon), palette["sky"])
    img = Image.new("RGB", size, palette["sky"][-1][1])
    img.paste(sky, (0, 0))

    # Soft sun glow
    glow = Image.new("RGB", size, (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy, r = int(w * palette["sun_x"]), int(horizon * 0.82), int(h * 0.20)
    gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=palette["sun"])
    glow = glow.filter(ImageFilter.GaussianBlur(h * 0.09))
    img = ImageChops.add(img, glow)

    # Mountain layers (far -> near)
    draw = ImageDraw.Draw(img)
    layers = palette["mountains"]
    for i, color in enumerate(layers):
        base = horizon - h * (0.20 - i * 0.045)
        line = ridge(w, base, h * (0.13 - i * 0.02), rng)
        draw.polygon([(0, horizon)] + [(x, min(horizon, y)) for x, y in enumerate(line)] + [(w, horizon)], fill=color)
    pines(draw, rng, horizon, w * 0.05, w * 0.95, 70, palette["pines"], 0.45)

    # Lake with reflection
    top = img.crop((0, 0, w, horizon))
    reflection = top.transpose(Image.FLIP_TOP_BOTTOM).resize((w, h - horizon))
    reflection = reflection.filter(ImageFilter.GaussianBlur(5))
    tint = Image.new("RGB", reflection.size, palette["lake"])
    reflection = Image.blend(reflection, tint, 0.35)
    img.paste(reflection, (0, horizon))
    draw = ImageDraw.Draw(img)
    for _ in range(260):
        y = rng.randint(horizon + 4, h - 4)
        x = rng.randint(0, w)
        length = rng.randint(20, 160) * (1 + (y - horizon) / h)
        shade = rng.choice([(255, 255, 255), palette["lake"]])
        draw.line([(x, y), (x + length, y)], fill=shade, width=rng.choice([1, 1, 2]))
    img = img.filter(ImageFilter.GaussianBlur(0.8))

    # Foreground shore
    draw = ImageDraw.Draw(img)
    for side in (0, 1):
        pts = ridge(int(w * 0.5), h * 0.90, h * 0.05, rng, steps=6)
        shore = [(x if side == 0 else w - x, y) for x, y in enumerate(pts)]
        draw.polygon([(0 if side == 0 else w, h)] + shore + [(w * 0.5 if side == 0 else w * 0.5, h)], fill=palette["shore"])
    pines(draw, rng, h * 0.93, 0, w * 0.22, 9, palette["shore"], 1.5)
    pines(draw, rng, h * 0.93, w * 0.80, w, 9, palette["shore"], 1.4)

    # Fine grain so the file behaves like a real photograph when compressed.
    grain = Image.effect_noise(size, 38).convert("RGB")
    img = Image.blend(img, ImageChops.overlay(img, grain), 0.55)
    img = ImageChops.add(img, Image.effect_noise(size, 14).convert("RGB").point(lambda v: v // 14))
    return img


PALETTES = {
    "dawn": {
        "sky": [(0, (186, 228, 216)), (0.55, (233, 246, 240)), (1, (252, 236, 215))],
        "sun": (255, 214, 168), "sun_x": 0.68,
        "mountains": [(176, 214, 204), (131, 187, 173), (84, 152, 134), (52, 118, 101)],
        "pines": (38, 96, 82), "lake": (122, 180, 170), "shore": (24, 66, 58),
    },
    "dusk": {
        "sky": [(0, (203, 214, 236)), (0.6, (240, 232, 244)), (1, (254, 226, 214))],
        "sun": (255, 190, 160), "sun_x": 0.30,
        "mountains": [(190, 198, 226), (150, 164, 205), (104, 124, 176), (70, 90, 140)],
        "pines": (52, 66, 112), "lake": (150, 166, 206), "shore": (30, 40, 78),
    },
    "meadow": {
        "sky": [(0, (206, 232, 232)), (0.6, (238, 246, 236)), (1, (250, 244, 214))],
        "sun": (255, 232, 160), "sun_x": 0.52,
        "mountains": [(196, 224, 196), (156, 206, 162), (110, 176, 126), (72, 140, 96)],
        "pines": (48, 112, 74), "lake": (150, 200, 190), "shore": (30, 82, 56),
    },
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    hero = landscape((1400, 900), 7, PALETTES["dawn"])
    hero.save(OUT / "landscape-original.jpg", "JPEG", quality=96, subsampling=0)
    hero.save(OUT / "landscape-optimized.webp", "WEBP", quality=62, method=6)

    landscape((720, 480), 21, PALETTES["dusk"]).save(OUT / "ghost-dusk.jpg", "JPEG", quality=72, optimize=True)
    landscape((720, 480), 33, PALETTES["meadow"]).save(OUT / "ghost-meadow.jpg", "JPEG", quality=72, optimize=True)

    for path in sorted(OUT.iterdir()):
        print(f"{path.name:32} {path.stat().st_size / 1024:8.1f} KB")


if __name__ == "__main__":
    main()
