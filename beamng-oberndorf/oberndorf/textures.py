"""Procedural textures: terrain, road decals and markings, building facades, roofs, props and trees."""
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage

from . import config as C

RNG = np.random.default_rng(C.SEED)


def noise(shape, sigma, rng=RNG, wrap=True):
    """Tileable smooth noise in [0, 1]."""
    a = rng.random(shape).astype(np.float32)
    a = ndimage.gaussian_filter(a, sigma, mode="wrap" if wrap else "reflect")
    a -= a.min()
    a /= max(a.max(), 1e-6)
    return a


def fbm(shape, sigmas=(1, 3, 8, 24), weights=(0.15, 0.25, 0.3, 0.3), rng=RNG):
    out = np.zeros(shape, np.float32)
    for s, w in zip(sigmas, weights):
        out += w * noise(shape, s, rng)
    out -= out.min()
    return out / max(out.max(), 1e-6)


def save(arr, path, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    a = np.clip(arr, 0, 255).astype(np.uint8)
    im = Image.fromarray(a, mode)
    if im.mode == "L":
        im = im.convert("RGB")  # keep one pixel format for all textures (terrain texture arrays)
    im.save(path, optimize=True)


def colorize(n, c0, c1):
    c0 = np.asarray(c0, np.float32)
    c1 = np.asarray(c1, np.float32)
    return c0 + (c1 - c0) * n[..., None]


def normal_from_height(h, strength=2.0):
    gy, gx = np.gradient(h.astype(np.float32))
    nx, ny = -gx * strength, gy * strength
    nz = np.ones_like(nx)
    l = np.sqrt(nx * nx + ny * ny + nz * nz)
    return np.stack([(nx / l * 0.5 + 0.5) * 255, (ny / l * 0.5 + 0.5) * 255, (nz / l * 0.5 + 0.5) * 255], -1)


def pebbles(shape, count, rmin, rmax, rng=RNG):
    """Height field of round stones (tileable)."""
    H, W = shape
    h = np.zeros(shape, np.float32)
    for _ in range(count):
        cx, cy = rng.random() * W, rng.random() * H
        r = rng.uniform(rmin, rmax)
        k = int(np.ceil(r)) + 1
        xs = np.arange(int(cx) - k, int(cx) + k + 1)
        ys = np.arange(int(cy) - k, int(cy) + k + 1)
        dx = xs[None, :] - cx
        dy = ys[:, None] - cy
        dd = (dx * dx + dy * dy) / (r * r)
        val = np.where(dd < 1, np.sqrt(np.clip(1 - dd, 0, 1)) * rng.uniform(0.6, 1.0), 0).astype(np.float32)
        iy = (ys % H)[:, None]
        ix = (xs % W)[None, :]
        h[iy, ix] = np.maximum(h[iy, ix], val)
    return h


# --------------------------------------------------------------------------------------------- terrain

TERRAIN_COLORS = {  # mean albedo used for both detail textures and the painted base map
    "Grass": (96, 128, 52),
    "Lawn": (104, 140, 60),
    "ForestFloor": (58, 62, 38),
    "Asphalt": (78, 78, 80),
    "Gravel": (150, 144, 132),
    "Dirt": (112, 92, 66),
    "Rock": (128, 126, 120),
}
DETAIL = 512
BASE = 2048


def terrain_detail(name, out_dir):
    s = (DETAIL, DETAIL)
    rng = np.random.default_rng(abs(hash(name)) % (2 ** 32))
    base = np.asarray(TERRAIN_COLORS[name], np.float32)
    if name in ("Grass", "Lawn"):
        n = fbm(s, (0.7, 2, 6, 20), (0.35, 0.25, 0.2, 0.2), rng)
        blades = noise(s, 0.6, rng)
        h = 0.6 * n + 0.4 * blades
        col = base[None, None] * (0.78 + 0.45 * h[..., None])
        col[..., 0] += (noise(s, 18, rng) - 0.5)[...] * 30
        rough = 0.92
    elif name == "ForestFloor":
        n = fbm(s, (0.8, 2, 7, 25), (0.3, 0.3, 0.2, 0.2), rng)
        needles = noise(s, 0.7, rng)
        h = 0.5 * n + 0.5 * needles
        col = colorize(h, (40, 36, 24), (100, 92, 60))
        moss = noise(s, 12, rng)[..., None]
        col = col * (1 - 0.4 * moss) + np.array([60, 82, 40]) * 0.4 * moss
        rough = 0.95
    elif name == "Asphalt":
        n = fbm(s, (0.6, 1.5, 6, 30), (0.5, 0.2, 0.15, 0.15), rng)
        h = n
        col = base[None, None] * (0.8 + 0.4 * n[..., None])
        rough = 0.82
    elif name == "Gravel":
        h = pebbles(s, 1400, 3, 9, rng) * 0.8 + 0.2 * noise(s, 1, rng)
        tint = noise(s, 2, rng)
        col = colorize(tint, (120, 114, 104), (182, 176, 162)) * (0.7 + 0.35 * h[..., None])
        rough = 0.9
    elif name == "Dirt":
        h = 0.7 * fbm(s, (1, 3, 9, 30), rng=rng) + 0.3 * pebbles(s, 300, 2, 5, rng)
        col = colorize(h, (82, 64, 44), (140, 116, 86))
        rough = 0.93
    else:  # Rock
        n = fbm(s, (1, 4, 14, 40), (0.25, 0.25, 0.3, 0.2), rng)
        cracks = np.abs(noise(s, 6, rng) - 0.5) < 0.02
        h = n - cracks * 0.3
        col = colorize(n, (96, 94, 90), (170, 166, 158))
        col[cracks] *= 0.55
        rough = 0.86
    # Re-centre on the reference colour so the detail matches the painted base map.
    col = col * (base / np.maximum(col.reshape(-1, 3).mean(0), 1))[None, None]
    p = os.path.join(out_dir, f"t_{name.lower()}")
    save(col, p + "_b.png", "RGB")
    save(normal_from_height(h * 255, 0.06), p + "_nm.png", "RGB")
    save(np.full(s, rough * 255) + (noise(s, 2, rng) - 0.5) * 20, p + "_r.png", "L")
    save(200 + 55 * h, p + "_ao.png", "L")
    save(h * 255, p + "_h.png", "L")
    return {"b": p + "_b.png", "nm": p + "_nm.png", "r": p + "_r.png", "ao": p + "_ao.png", "h": p + "_h.png"}


def terrain_macro(out_dir):
    s = (DETAIL, DETAIL)
    rng = np.random.default_rng(7)
    n = fbm(s, (4, 12, 30, 60), (0.2, 0.3, 0.3, 0.2), rng)
    p = os.path.join(out_dir, "t_macro")
    save(np.repeat((100 + 56 * n)[..., None], 3, -1), p + "_b.png", "RGB")
    save(normal_from_height(n * 255, 0.02), p + "_nm.png", "RGB")
    save(150 + 60 * n, p + "_r.png", "L")
    save(205 + 50 * n, p + "_ao.png", "L")
    save(n * 255, p + "_h.png", "L")
    return {"b": p + "_b.png", "nm": p + "_nm.png", "r": p + "_r.png", "ao": p + "_ao.png", "h": p + "_h.png"}


def terrain_base(layers, heights, out_dir, material_names):
    """Painted colour map for the whole terrain (seen from distance) + flat companions."""
    lay = layers[::2, ::2]  # 4096 -> 2048
    pal = np.array([TERRAIN_COLORS[m] for m in material_names], np.float32)
    col = pal[lay]
    # Variation: meadows of different farms, forest canopy, plus baked hill shading.
    var = fbm(lay.shape, (2, 8, 30, 80), (0.15, 0.25, 0.3, 0.3), np.random.default_rng(11))
    col *= (0.82 + 0.36 * var)[..., None]
    h = heights[::2, ::2]
    gy, gx = np.gradient(h, 3.0)
    slope = np.pi / 2 - np.arctan(np.hypot(gx, gy))
    asp = np.arctan2(-gx, gy)
    hs = np.sin(np.radians(50)) * np.sin(slope) + np.cos(np.radians(50)) * np.cos(slope) * np.cos(np.radians(300) - asp)
    col *= (0.75 + 0.3 * np.clip(hs, 0, 1))[..., None]
    col = ndimage.uniform_filter(col, (3, 3, 1))
    p = os.path.join(out_dir, "t_base")
    # Terrain textures are stored with image row 0 = north (top), like a map.
    save(col[::-1], p + "_b.png", "RGB")
    flat = np.zeros((BASE, BASE, 3), np.uint8)
    flat[..., 0] = 128
    flat[..., 1] = 128
    flat[..., 2] = 255
    save(flat, p + "_nm.png", "RGB")
    save(np.full((BASE, BASE), 230), p + "_r.png", "L")
    save(np.full((BASE, BASE), 255), p + "_ao.png", "L")
    save(np.full((BASE, BASE), 128), p + "_h.png", "L")
    return {"b": p + "_b.png", "nm": p + "_nm.png", "r": p + "_r.png", "ao": p + "_ao.png", "h": p + "_h.png"}


# --------------------------------------------------------------------------------------------- roads

def _edge_alpha(w, fade=0.05):
    u = (np.arange(w) + 0.5) / w
    a = np.clip(np.minimum(u, 1 - u) / fade, 0, 1)
    return a


def road_textures(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(21)
    W, H = 512, 1024
    out = {}
    # Austrian asphalt: dark, fine aggregate, a few repaired strips and tyre polish.
    n = fbm((H, W), (0.6, 2, 8, 40), (0.45, 0.2, 0.15, 0.2), rng)
    col = colorize(n, (52, 52, 54), (98, 97, 96))
    u = (np.arange(W) + 0.5) / W
    polish = np.exp(-((u - 0.3) ** 2) / 0.004) + np.exp(-((u - 0.7) ** 2) / 0.004)
    col *= (1 - 0.08 * polish)[None, :, None]
    patch = noise((H, W), 25, rng) > 0.78
    col[patch] *= 0.82
    ea = _edge_alpha(W, 0.035)[None, :]
    a = np.where(ea >= 1.0, 1.0, ea * (0.85 + 0.15 * noise((H, W), 2, rng)))
    out["obd_asphalt"] = _save_rgba(col, a, out_dir, "obd_asphalt")
    # Older village asphalt (lighter, more patches and cracks).
    n2 = fbm((H, W), (0.6, 2, 8, 40), (0.45, 0.2, 0.15, 0.2), rng)
    col2 = colorize(n2, (70, 70, 70), (122, 120, 117))
    col2[noise((H, W), 18, rng) > 0.72] *= 0.8
    cr = np.abs(noise((H, W), 4, rng) - 0.5) < 0.012
    col2[cr] *= 0.6
    ea2 = _edge_alpha(W, 0.05)[None, :]
    a2 = np.where(ea2 >= 1.0, 1.0, ea2 * (0.8 + 0.2 * noise((H, W), 2, rng)))
    out["obd_asphalt_minor"] = _save_rgba(col2, a2, out_dir, "obd_asphalt_minor")
    # Gravel farm track with grass median strip (typical Tyrolean Feldweg).
    g = pebbles((H, 256), 900, 2, 6, rng)
    g = np.asarray(Image.fromarray((g * 255).astype(np.uint8)).resize((W, H)), np.float32) / 255
    col3 = colorize(0.5 * g + 0.5 * noise((H, W), 1.5, rng), (118, 108, 92), (176, 166, 148))
    grass = np.exp(-((u - 0.5) ** 2) / 0.006)[None, :] * (0.6 + 0.4 * noise((H, W), 3, rng))
    grass_col = colorize(noise((H, W), 1, rng), (70, 100, 40), (110, 140, 60))
    col3 = col3 * (1 - grass[..., None]) + grass_col * grass[..., None]
    a3 = _edge_alpha(W, 0.12)[None, :] * (0.7 + 0.3 * noise((H, W), 2, rng))
    out["obd_gravel"] = _save_rgba(col3, a3, out_dir, "obd_gravel")
    # Forest/meadow path: compacted dirt.
    col4 = colorize(fbm((H, W), rng=rng), (92, 74, 52), (146, 124, 92))
    a4 = _edge_alpha(W, 0.2)[None, :] * (0.6 + 0.4 * noise((H, W), 3, rng))
    out["obd_dirt"] = _save_rgba(col4, a4, out_dir, "obd_dirt")
    # Paving stones (Pflaster) for pedestrian zones.
    img = Image.new("RGB", (W, H), (120, 116, 110))
    d = ImageDraw.Draw(img)
    st = 32
    for row in range(H // st + 1):
        off = (row % 2) * st // 2
        for col_i in range(-1, W // st + 1):
            x0 = col_i * st + off
            y0 = row * st
            v = int(rng.integers(-18, 18))
            d.rectangle([x0 + 2, y0 + 2, x0 + st - 2, y0 + st - 2], fill=(150 + v, 144 + v, 136 + v))
    col5 = np.asarray(img, np.float32) * (0.85 + 0.3 * noise((H, W), 2, rng))[..., None]
    out["obd_paving"] = _save_rgba(col5, _edge_alpha(W, 0.02)[None, :] * np.ones((H, 1)), out_dir, "obd_paving")
    # Markings (white, slightly worn). Textures run along v (image rows).
    def marking(name, on_frac, color=(236, 236, 230), w=32, h=512, zig=False):
        wear = 0.82 + 0.18 * noise((h, w), 1.2, rng)
        c = np.ones((h, w, 3), np.float32) * np.asarray(color, np.float32) * wear[..., None]
        v = (np.arange(h) + 0.5) / h
        on = (v < on_frac).astype(np.float32)[:, None] * np.ones((1, w))
        if zig:
            uu = (np.arange(w) + 0.5) / w
            tri = np.abs(((v * 2) % 1.0) - 0.5) * 2
            on = (np.abs(uu[None, :] - tri[:, None]) < 0.12).astype(np.float32)
        a = on * (0.9 + 0.1 * noise((h, w), 1, rng))
        return _save_rgba(c, a, out_dir, name)
    out["obd_line"] = marking("obd_line", 1.01)
    out["obd_line_dash"] = marking("obd_line_dash", 1 / 3)
    out["obd_line_dash_half"] = marking("obd_line_dash_half", 0.5)
    out["obd_zebra"] = marking("obd_zebra", 0.5, w=64, h=256)
    out["obd_zigzag_yellow"] = marking("obd_zigzag_yellow", 1.0, color=(236, 196, 30), w=64, h=256, zig=True)
    out["obd_invisible"] = _save_rgba(np.zeros((16, 16, 3)), np.zeros((16, 16)), out_dir, "obd_invisible")
    return out


def _save_rgba(col, alpha, out_dir, name):
    a = np.clip(alpha * 255, 0, 255)
    rgba = np.dstack([np.clip(col, 0, 255), a]).astype(np.uint8)
    p = os.path.join(out_dir, f"{name}.color.png")
    Image.fromarray(rgba, "RGBA").save(p, optimize=True)
    return p


# --------------------------------------------------------------------------------------------- buildings

def _window(d, x0, y0, x1, y1, frame=(245, 245, 240), glass=(40, 50, 58), shutters=None):
    if shutters:
        sw = (x1 - x0) * 0.42
        d.rectangle([x0 - sw - 4, y0, x0 - 4, y1], fill=shutters)
        d.rectangle([x1 + 4, y0, x1 + sw + 4, y1], fill=shutters)
        for yy in range(int(y0) + 6, int(y1), 10):
            d.line([x0 - sw - 2, yy, x0 - 6, yy], fill=tuple(int(c * 0.75) for c in shutters), width=2)
            d.line([x1 + 6, yy, x1 + sw + 2, yy], fill=tuple(int(c * 0.75) for c in shutters), width=2)
    d.rectangle([x0, y0, x1, y1], fill=frame)
    m = 8
    d.rectangle([x0 + m, y0 + m, x1 - m, y1 - m], fill=glass)
    xm = (x0 + x1) / 2
    d.rectangle([xm - 3, y0 + m, xm + 3, y1 - m], fill=frame)
    ym = y0 + (y1 - y0) * 0.38
    d.rectangle([x0 + m, ym - 3, x1 - m, ym + 3], fill=frame)
    # reflection highlight
    d.polygon([(x0 + m, y1 - m), (x0 + m + 30, y0 + m), (x0 + m + 48, y0 + m), (x0 + m + 18, y1 - m)], fill=(70, 84, 96))
    # window sill
    d.rectangle([x0 - 6, y1, x1 + 6, y1 + 8], fill=(200, 200, 196))


def building_textures(out_dir):
    """Facade tiles cover one window bay: 3.2 m wide x 3.0 m floor height (512 x 480 px -> stored 512x512)."""
    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(31)
    S = 512
    out = {}

    def plaster(base_col, dirt=0.12):
        n = fbm((S, S), (0.7, 3, 12, 40), (0.3, 0.3, 0.2, 0.2), rng)
        col = np.asarray(base_col, np.float32)[None, None] * (1 - dirt / 2 + dirt * n[..., None])
        # rain streaks
        streak = ndimage.gaussian_filter(rng.random((S, S)).astype(np.float32), (40, 1), mode="wrap")
        col *= (0.97 + 0.08 * (streak - streak.mean()) / max(streak.std(), 1e-6) * 0.2)[..., None]
        return Image.fromarray(np.clip(col, 0, 255).astype(np.uint8))

    shutter_cols = {"white": (60, 94, 60), "cream": (110, 70, 40), "yellow": (90, 60, 34)}
    for name, c in (("white", (236, 234, 226)), ("cream", (232, 222, 196)), ("yellow", (226, 210, 160))):
        im = plaster(c)
        d = ImageDraw.Draw(im)
        _window(d, 176, 150, 336, 360, shutters=shutter_cols[name])
        im.save(os.path.join(out_dir, f"bld_plaster_{name}_win.color.png"), optimize=True)
        out[f"plaster_{name}_win"] = os.path.join(out_dir, f"bld_plaster_{name}_win.color.png")
        im2 = plaster(c)
        im2.save(os.path.join(out_dir, f"bld_plaster_{name}.color.png"), optimize=True)
        out[f"plaster_{name}"] = os.path.join(out_dir, f"bld_plaster_{name}.color.png")
    # Tyrolean larch boarding (vertical boards), weathered brown, with window.
    def wood(window, tone=(120, 78, 44)):
        n = fbm((S, S), (0.5, 2, 8, 30), (0.3, 0.3, 0.2, 0.2), rng)
        grain = ndimage.gaussian_filter(rng.random((S, S)).astype(np.float32), (25, 0.6), mode="wrap")
        col = np.asarray(tone, np.float32)[None, None] * (0.75 + 0.35 * n[..., None] + 0.3 * (grain[..., None] - 0.5))
        for x in range(0, S, 32):
            col[:, x:x + 2] *= 0.55
        im = Image.fromarray(np.clip(col, 0, 255).astype(np.uint8))
        if window:
            d = ImageDraw.Draw(im)
            _window(d, 176, 150, 336, 360, frame=(236, 230, 214))
        return im
    for name, win in (("wood_win", True), ("wood", False)):
        p = os.path.join(out_dir, f"bld_{name}.color.png")
        wood(win).save(p, optimize=True)
        out[name] = p
    p = os.path.join(out_dir, "bld_barn.color.png")
    wood(False, (96, 72, 52)).save(p, optimize=True)
    out["barn"] = p
    # Balcony boards (horizontal) used for Tyrolean wooden balconies.
    im = wood(False, (118, 76, 40)).rotate(90)
    d = ImageDraw.Draw(im)
    for x in range(0, S, 64):
        d.rectangle([x + 22, 0, x + 42, S], fill=(64, 40, 22))
    p = os.path.join(out_dir, "bld_balcony.color.png")
    im.save(p, optimize=True)
    out["balcony"] = p
    # Shop / commercial ground floor: big windows.
    im = plaster((214, 212, 206), 0.06)
    d = ImageDraw.Draw(im)
    d.rectangle([40, 90, 472, 470], fill=(225, 225, 225))
    d.rectangle([52, 102, 460, 458], fill=(46, 58, 66))
    d.line([256, 102, 256, 458], fill=(225, 225, 225), width=8)
    d.polygon([(70, 458), (160, 102), (200, 102), (110, 458)], fill=(72, 88, 98))
    p = os.path.join(out_dir, "bld_shop.color.png")
    im.save(p, optimize=True)
    out["shop"] = p
    # Industrial cladding (trapezoidal sheet metal) with a strip window.
    n = fbm((S, S), rng=rng)
    col = np.full((S, S, 3), (176, 180, 182), np.float32) * (0.92 + 0.12 * n[..., None])
    for x in range(0, S, 32):
        col[:, x:x + 6] *= 0.8
    im = Image.fromarray(col.astype(np.uint8))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 200, S, 300], fill=(60, 72, 80))
    p = os.path.join(out_dir, "bld_metal.color.png")
    im.save(p, optimize=True)
    out["metal"] = p
    # Concrete
    n = fbm((S, S), rng=rng)
    p = os.path.join(out_dir, "bld_concrete.color.png")
    save(colorize(n, (140, 138, 132), (186, 184, 178)), p, "RGB")
    out["concrete"] = p
    # Roof tiles / sheet metal (one tile = 2 m x 2 m).
    for name, c0, c1 in (("roof_grey", (58, 60, 64), (92, 94, 98)), ("roof_brown", (70, 48, 36), (112, 78, 58)),
                         ("roof_red", (110, 46, 34), (160, 74, 52)), ("roof_dark", (40, 42, 46), (70, 72, 76))):
        n = fbm((S, S), (0.6, 2, 8, 30), (0.3, 0.3, 0.2, 0.2), rng)
        col = colorize(n, c0, c1)
        v = np.arange(S)
        rows = ((v % 64) < 6)[:, None]
        cols = (((np.arange(S)[None, :] + (v[:, None] // 64 % 2) * 32) % 64) < 4)
        col[rows[:, 0]] *= 0.6
        col[cols & ~rows] *= 0.8
        p = os.path.join(out_dir, f"bld_{name}.color.png")
        save(col, p, "RGB")
        out[name] = p
    n = fbm((S, S), rng=rng)
    col = colorize(n, (88, 92, 96), (120, 124, 128))
    for x in range(0, S, 48):
        col[:, x:x + 4] *= 1.3
    p = os.path.join(out_dir, "bld_roof_metal.color.png")
    save(col, p, "RGB")
    out["roof_metal"] = p
    return out


# --------------------------------------------------------------------------------------------- vegetation & props

def misc_textures(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(41)
    out = {}

    def tex(name, c0, c1, sigmas=(0.7, 2, 6, 18), size=256, extra=None):
        n = fbm((size, size), sigmas, rng=rng)
        col = colorize(n, c0, c1)
        if extra:
            col = extra(col, n)
        p = os.path.join(out_dir, f"{name}.color.png")
        save(col, p, "RGB")
        out[name] = p
    tex("obd_spruce", (22, 44, 26), (52, 84, 46))
    tex("obd_leaves", (52, 92, 34), (110, 150, 60))
    tex("obd_larch", (70, 100, 40), (130, 150, 70))
    tex("obd_bark", (56, 42, 32), (100, 80, 62), (0.5, 1, 4, 10))
    tex("obd_hedge", (40, 70, 30), (80, 120, 50))
    tex("obd_ballast", (90, 86, 80), (150, 144, 136), (0.6, 1, 2, 6))
    tex("obd_sleeper", (110, 108, 104), (150, 148, 142))
    tex("obd_fence_wood", (90, 64, 40), (140, 104, 70), (0.5, 1, 6, 20))
    tex("obd_stone_wall", (110, 108, 100), (170, 166, 156), (1, 3, 6, 12))
    tex("obd_water_bed", (60, 58, 50), (100, 94, 80))
    return out


def font(size, bold=True):
    from PIL import ImageFont
    cands = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
             "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"]
    for c in cands:
        if os.path.exists(c):
            return ImageFont.truetype(c, size)
    return ImageFont.load_default(size=size)


def fit_text(d, text, box_w, box_h, start=200, bold=True):
    size = start
    while size > 8:
        f = font(size, bold)
        l, t, r, b = d.textbbox((0, 0), text, font=f)
        if r - l <= box_w and b - t <= box_h:
            return f, (r - l, b - t, l, t)
        size -= 2
    f = font(8, bold)
    l, t, r, b = d.textbbox((0, 0), text, font=f)
    return f, (r - l, b - t, l, t)


def draw_centered(d, text, cx, cy, box_w, box_h, fill, start=200, bold=True):
    f, (w, h, l, t) = fit_text(d, text, box_w, box_h, start, bold)
    d.text((cx - w / 2 - l, cy - h / 2 - t), text, font=f, fill=fill)


# --------------------------------------------------------------------------------------------- Austrian signs

RED = (200, 16, 30)
WHITE = (250, 250, 248)
BLACK = (20, 20, 20)
BLUE = (0, 82, 160)
YELLOW = (250, 196, 0)
GREEN = (0, 120, 70)


def _sign_canvas(w=512, h=512, bg=(140, 140, 140)):
    im = Image.new("RGB", (w, h), bg)
    return im, ImageDraw.Draw(im)


def sign_give_way():
    im, d = _sign_canvas()
    pts = [(16, 40), (496, 40), (256, 456)]
    d.polygon(pts, fill=RED)
    d.polygon([(80, 76), (432, 76), (256, 380)], fill=WHITE)
    return im


def sign_stop():
    im, d = _sign_canvas()
    c, r = 256, 248
    oct_ = [(c + r * np.cos(np.radians(22.5 + 45 * i)), c + r * np.sin(np.radians(22.5 + 45 * i))) for i in range(8)]
    d.polygon(oct_, fill=WHITE)
    r2 = r - 14
    d.polygon([(c + r2 * np.cos(np.radians(22.5 + 45 * i)), c + r2 * np.sin(np.radians(22.5 + 45 * i))) for i in range(8)], fill=RED)
    draw_centered(d, "STOP", 256, 256, 380, 170, WHITE, 200)
    return im


def sign_priority_road():
    im, d = _sign_canvas()
    d.polygon([(256, 4), (508, 256), (256, 508), (4, 256)], fill=BLACK)
    d.polygon([(256, 14), (498, 256), (256, 498), (14, 256)], fill=WHITE)
    d.polygon([(256, 110), (402, 256), (256, 402), (110, 256)], fill=YELLOW)
    return im


def sign_speed(v):
    im, d = _sign_canvas()
    d.ellipse([8, 8, 504, 504], fill=RED)
    d.ellipse([62, 62, 450, 450], fill=WHITE)
    draw_centered(d, str(v), 256, 262, 330 if v >= 100 else 290, 200, BLACK, 240)
    return im


def sign_crosswalk():
    im, d = _sign_canvas()
    d.rectangle([8, 8, 504, 504], fill=BLUE)
    d.polygon([(256, 50), (470, 440), (42, 440)], fill=WHITE)
    # zebra
    for i in range(5):
        x0 = 120 + i * 58
        d.polygon([(x0, 410), (x0 + 30, 410), (x0 + 20, 380), (x0 - 10, 380)], fill=BLACK)
    # pedestrian
    d.ellipse([236, 160, 276, 200], fill=BLACK)
    d.line([256, 205, 250, 290], fill=BLACK, width=26)
    d.line([250, 290, 215, 365], fill=BLACK, width=22)
    d.line([250, 290, 300, 360], fill=BLACK, width=22)
    d.line([256, 220, 210, 270], fill=BLACK, width=18)
    d.line([256, 220, 305, 255], fill=BLACK, width=18)
    return im


def sign_bus_stop():
    im, d = _sign_canvas()
    d.ellipse([8, 8, 504, 504], fill=GREEN)
    d.ellipse([46, 46, 466, 466], fill=YELLOW)
    draw_centered(d, "H", 256, 262, 260, 300, GREEN, 320)
    return im


def sign_andreas():
    im, d = _sign_canvas(512, 96, (140, 140, 140))
    d.rectangle([0, 0, 512, 96], fill=WHITE)
    for i in range(0, 512, 128):
        d.rectangle([i + 64, 4, i + 127, 92], fill=RED)
    d.rectangle([0, 0, 511, 95], outline=RED, width=6)
    return im


def sign_town(name, end=False):
    im, d = _sign_canvas(768, 512, WHITE)
    d.rectangle([0, 0, 767, 511], fill=WHITE)
    d.rectangle([14, 14, 753, 497], outline=BLACK, width=10)
    lines = name.split("\n")
    if len(lines) == 1 and len(name) > 12 and " " in name:
        for sep in (" in ", " am ", " bei ", " im "):
            if sep in name:
                i = name.index(sep)
                lines = [name[:i], name[i + 1:]]
                break
        else:
            i = name.rfind(" ", 0, len(name) // 2 + 4)
            lines = [name[:i], name[i + 1:]] if i > 0 else [name]
    hbox = 380 / len(lines)
    # one common font size for all lines
    f = min((fit_text(d, ln, 660, hbox * 0.8, 200)[0] for ln in lines), key=lambda ff: ff.size)
    for k, ln in enumerate(lines):
        l, t, r, b = d.textbbox((0, 0), ln, font=f)
        cy = 66 + hbox * (k + 0.5)
        d.text((384 - (r - l) / 2 - l, cy - (b - t) / 2 - t), ln, font=f, fill=BLACK)
    if end:
        d.line([60, 470, 708, 42], fill=RED, width=46)
    return im


def sign_street(name):
    im, d = _sign_canvas(1024, 192, BLUE)
    d.rectangle([0, 0, 1023, 191], fill=BLUE)
    d.rectangle([8, 8, 1015, 183], outline=WHITE, width=6)
    draw_centered(d, name, 512, 98, 940, 120, WHITE, 140)
    return im


def sign_plate(text, w=768, h=192):
    im, d = _sign_canvas(w, h, WHITE)
    d.rectangle([0, 0, w - 1, h - 1], fill=WHITE)
    d.rectangle([6, 6, w - 7, h - 7], outline=BLACK, width=5)
    draw_centered(d, text, w / 2, h / 2 + 4, w - 60, h * 0.6, BLACK, 120)
    return im


def sign_direction(labels, arrow_right=True):
    """Austrian white direction sign (Wegweiser) for local destinations."""
    im, d = _sign_canvas(1024, 256, WHITE)
    d.rectangle([0, 0, 1023, 255], fill=WHITE)
    d.rectangle([6, 6, 1017, 249], outline=BLACK, width=6)
    txt = " · ".join(labels[:2])
    draw_centered(d, txt, 470 if arrow_right else 554, 128, 760, 120, BLACK, 110)
    if arrow_right:
        d.polygon([(900, 80), (990, 128), (900, 176)], fill=BLACK)
        d.rectangle([840, 112, 905, 144], fill=BLACK)
    else:
        d.polygon([(124, 80), (34, 128), (124, 176)], fill=BLACK)
        d.rectangle([119, 112, 184, 144], fill=BLACK)
    return im


def flowers_texture(path):
    rng = np.random.default_rng(5)
    S = 256
    col = np.zeros((S, S, 3), np.float32) + np.array([50, 90, 34])
    im = Image.fromarray(col.astype(np.uint8))
    d = ImageDraw.Draw(im)
    for _ in range(420):
        x, y = rng.random() * S, rng.random() * S * 0.8
        r = rng.uniform(4, 9)
        c = (int(rng.uniform(190, 235)), int(rng.uniform(10, 40)), int(rng.uniform(20, 50)))
        d.ellipse([x - r, y - r, x + r, y + r], fill=c)
    d.rectangle([0, int(S * 0.8), S, S], fill=(110, 70, 40))
    im.save(path, optimize=True)


def clock_texture(path):
    im = Image.new("RGB", (512, 256), (236, 232, 222))
    d = ImageDraw.Draw(im)
    d.ellipse([156, 28, 356, 228], fill=(30, 40, 60))
    d.ellipse([170, 42, 342, 214], fill=(240, 236, 220))
    for i in range(12):
        a = np.radians(i * 30)
        d.line([256 + 70 * np.cos(a), 128 + 70 * np.sin(a), 256 + 82 * np.cos(a), 128 + 82 * np.sin(a)], fill=(30, 30, 30), width=5)
    d.line([256, 128, 256, 70], fill=(200, 160, 40), width=8)
    d.line([256, 128, 300, 140], fill=(200, 160, 40), width=8)
    im.save(path, optimize=True)


def deck_textures(out_dir):
    """Bridge deck asphalt with baked Austrian markings (u across width, v along 8 m)."""
    rng = np.random.default_rng(61)
    W, H = 512, 1024
    n = fbm((H, W), (0.6, 2, 8, 40), (0.45, 0.2, 0.15, 0.2), rng)
    base = colorize(n, (52, 52, 54), (98, 97, 96))
    out = {}
    minor = base.copy()
    save(minor, os.path.join(out_dir, "obd_deck_minor.color.png"), "RGB")
    out["obd_deck_minor"] = os.path.join(out_dir, "obd_deck_minor.color.png")
    major = base.copy()
    # deck width 8.0 m: kerbs 0.5 m (u 0..0.0625), edge lines at 0.85 m from the kerb, solid centre line
    def band(u0, u1, color):
        major[:, int(u0 * W):int(u1 * W)] = color
    band(0.0, 0.07, (150, 150, 146))
    band(0.93, 1.0, (150, 150, 146))
    band(0.10, 0.12, (236, 236, 230))
    band(0.88, 0.90, (236, 236, 230))
    band(0.4925, 0.5075, (236, 236, 230))
    save(major, os.path.join(out_dir, "obd_deck_major.color.png"), "RGB")
    out["obd_deck_major"] = os.path.join(out_dir, "obd_deck_major.color.png")
    return out


def prop_textures(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(71)
    out = {}
    # Track bed: ballast with concrete sleepers every 0.6 m (texture spans 3.2 m x 2.4 m)
    W, H = 256, 192
    g = pebbles((H, W), 1500, 1.5, 3.5, rng)
    col = colorize(0.6 * g + 0.4 * noise((H, W), 1, rng), (88, 84, 78), (156, 150, 142))
    for k in range(4):
        y0 = int(k * H / 4 + 4)
        y1 = y0 + int(0.25 / 2.4 * H)
        x0, x1 = int(W * 0.09), int(W * 0.91)
        col[y0:y1, x0:x1] = colorize(noise((y1 - y0, x1 - x0), 1.5, rng), (150, 148, 142), (186, 184, 178))
    p = os.path.join(out_dir, "obd_track.color.png")
    save(col, p, "RGB")
    out["obd_track"] = p
    # Leitpflock: white, black band near the top with a reflector
    im = Image.new("RGB", (64, 256), (240, 240, 236))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 30, 64, 90], fill=(20, 20, 20))
    d.rectangle([20, 40, 44, 80], fill=(230, 160, 20))
    p = os.path.join(out_dir, "obd_delineator.color.png")
    im.save(p)
    out["obd_delineator"] = p
    # Guardrail: galvanized W profile
    v = np.linspace(0, 1, 128)
    prof = 0.75 + 0.25 * np.cos(v * 4 * np.pi)
    col = np.ones((128, 256, 3)) * np.array([170, 174, 176]) * prof[:, None, None]
    col *= (0.92 + 0.12 * noise((128, 256), 3, rng))[..., None]
    p = os.path.join(out_dir, "obd_guardrail.color.png")
    save(col, p, "RGB")
    out["obd_guardrail"] = p
    # Traffic light face (red lit)
    im = Image.new("RGB", (128, 384), (25, 25, 25))
    d = ImageDraw.Draw(im)
    for i, c in enumerate([(255, 40, 30), (70, 50, 10), (10, 60, 30)]):
        cy = 64 + i * 128
        d.ellipse([24, cy - 40, 104, cy + 40], fill=c)
    p = os.path.join(out_dir, "obd_signal.color.png")
    im.save(p)
    out["obd_signal"] = p
    # Platform: concrete with white safety line
    n = fbm((256, 256), rng=rng)
    col = colorize(n, (150, 148, 144), (190, 188, 184))
    col[:, 230:244] = (235, 235, 230)
    p = os.path.join(out_dir, "obd_platform.color.png")
    save(col, p, "RGB")
    out["obd_platform"] = p
    p = os.path.join(out_dir, "obd_flowers.color.png")
    flowers_texture(p)
    out["obd_flowers"] = p
    p = os.path.join(out_dir, "obd_clock.color.png")
    clock_texture(p)
    out["obd_clock"] = p
    return out
