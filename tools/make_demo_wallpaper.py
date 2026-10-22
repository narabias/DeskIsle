"""Generate deskisle/assets/demo/wallpaper.jpg (procedural, no third-party art)."""

import math
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

W, H = 1920, 1080
OUT = Path(__file__).resolve().parent.parent / "deskisle" / "assets" / "demo" / "wallpaper.jpg"


def lerp(a, b, t):
    return a + (b - a) * t


def ridge(x, seed, base, amp, freq):
    rnd = random.Random(seed)
    y = np.full_like(x, base, dtype=np.float64)
    for octave in range(5):
        phase = rnd.random() * math.tau
        f = freq * (2.1 ** octave)
        a = amp / (1.9 ** octave)
        y += a * np.sin(x * f + phase) * (0.6 + 0.4 * np.sin(x * f * 0.37 + phase * 2))
    return y


def main() -> None:
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    t = yy / H
    sky_top = np.array([22, 28, 74], float)
    sky_mid = np.array([108, 64, 150], float)
    sky_low = np.array([255, 150, 110], float)
    img = np.zeros((H, W, 3), float)
    for c in range(3):
        upper = lerp(sky_top[c], sky_mid[c], np.clip(t / 0.45, 0, 1))
        lower = lerp(sky_mid[c], sky_low[c], np.clip((t - 0.45) / 0.25, 0, 1))
        img[..., c] = np.where(t < 0.45, upper, lower)
    # Sun glow
    sx, sy = W * 0.68, H * 0.62
    d = np.sqrt((xx - sx) ** 2 + ((yy - sy) * 1.2) ** 2)
    glow = np.exp(-d / 260.0)
    img += glow[..., None] * np.array([255, 190, 120]) * 0.75
    disc = np.clip(1.0 - (d - 58) / 3.0, 0, 1)
    img = img * (1 - disc[..., None]) + disc[..., None] * np.array([255, 240, 214])
    # Stars
    rnd = random.Random(7)
    for _ in range(260):
        x, y = rnd.randrange(W), rnd.randrange(int(H * 0.4))
        b = rnd.random() * 0.8
        img[y, x] = img[y, x] * (1 - b) + 255 * b
    # Mountains
    x = np.arange(W, dtype=np.float64)
    layers = [
        (0.58, 70, 0.0032, (150, 92, 150), 11),
        (0.66, 60, 0.0045, (104, 62, 128), 23),
        (0.74, 54, 0.006, (64, 40, 96), 37),
        (0.83, 46, 0.008, (34, 24, 58), 51),
    ]
    for base, amp, freq, color, seed in layers:
        top = ridge(x, seed, base * H, amp, freq)
        mask = yy >= top[None, :]
        haze = np.clip((yy - top[None, :]) / 240.0, 0, 1)
        col = np.array(color, float)
        shade = col[None, None, :] * (1 - 0.35 * haze[..., None])
        img = np.where(mask[..., None], shade, img)
    # Lake reflection
    lake = int(H * 0.88)
    reflect = img[lake - (np.arange(H - lake) * 1.6).astype(int).clip(0, lake - 1)][:, ::1]
    ripple = (np.sin(np.arange(H - lake)[:, None] * 0.9 + xx[lake:] * 0.02) * 0.5 + 0.5)
    water = reflect * 0.55 + np.array([30, 30, 70]) * 0.45
    water = water * (0.9 + 0.1 * ripple[..., None])
    img[lake:] = water
    out = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB").filter(ImageFilter.GaussianBlur(0.6))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(OUT, quality=88, optimize=True, progressive=True)
    print(OUT, OUT.stat().st_size)


if __name__ == "__main__":
    sys.exit(main())
