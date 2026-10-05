"""Terrain: carve roads/rails/water into the DEM, paint material layers and write the BeamNG .ter file."""
import json
import struct

import numpy as np
import shapely
from PIL import Image, ImageDraw
from scipy import ndimage

from . import config as C
from .roads import CAR_CLASSES, sample_grid

N = C.TER_SIZE
SQ = C.SQUARE

# Terrain material layers (index in the .ter file).
MATERIALS = [
    # internal name, groundmodel
    ("Grass", "GRASS"),               # 0 meadow
    ("Lawn", "GRASS2"),               # 1 gardens / urban green
    ("ForestFloor", "DIRT_GRASS"),    # 2 forest
    ("Asphalt", "GROUNDMODEL_ASPHALT1"),  # 3 paved roads
    ("Gravel", "GRAVEL"),             # 4 gravel roads, ballast, shoulders
    ("Dirt", "DIRT_LOOSE"),           # 5 farmyards, construction, river bed
    ("Rock", "ROCK"),                 # 6 cliffs and steep slopes
]
L_GRASS, L_LAWN, L_FOREST, L_ASPHALT, L_GRAVEL, L_DIRT, L_ROCK = range(7)


def world_to_grid(x, y):
    return (np.asarray(x) + C.HALF) / SQ, (np.asarray(y) + C.HALF) / SQ


def poly_mask(geoms, buffer=0.0):
    """Rasterise polygons into a boolean terrain-grid mask (row = y)."""
    im = Image.new("L", (N, N), 0)
    dr = ImageDraw.Draw(im)
    for g in geoms:
        if buffer:
            g = g.buffer(buffer)
        for p in getattr(g, "geoms", [g]):
            if p.geom_type != "Polygon" or p.is_empty:
                continue
            gx, gy = world_to_grid(*np.asarray(p.exterior.coords)[:, :2].T)
            dr.polygon(list(zip(gx.tolist(), gy.tolist())), fill=1)
            for hole in p.interiors:
                hx, hy = world_to_grid(*np.asarray(hole.coords)[:, :2].T)
                dr.polygon(list(zip(hx.tolist(), hy.tolist())), fill=0)
    return np.asarray(im, bool)


def window_of(g, pad=0.0):
    x0, y0, x1, y1 = g.bounds
    c0, r0 = world_to_grid(x0 - pad, y0 - pad)
    c1, r1 = world_to_grid(x1 + pad, y1 + pad)
    c0, r0 = max(int(np.floor(c0)), 0), max(int(np.floor(r0)), 0)
    c1, r1 = min(int(np.ceil(c1)) + 1, N), min(int(np.ceil(r1)) + 1, N)
    if c1 <= c0 or r1 <= r0:
        return None
    return r0, r1, c0, c1


def poly_mask_window(geoms, win):
    r0, r1, c0, c1 = win
    im = Image.new("L", (c1 - c0, r1 - r0), 0)
    dr = ImageDraw.Draw(im)
    for g in geoms:
        for p in getattr(g, "geoms", [g]):
            if p.geom_type != "Polygon" or p.is_empty:
                continue
            gx, gy = world_to_grid(*np.asarray(p.exterior.coords)[:, :2].T)
            dr.polygon(list(zip((gx - c0).tolist(), (gy - r0).tolist())), fill=1)
            for hole in p.interiors:
                hx, hy = world_to_grid(*np.asarray(hole.coords)[:, :2].T)
                dr.polygon(list(zip((hx - c0).tolist(), (hy - r0).tolist())), fill=0)
    return np.asarray(im, bool)


def _profile_samples(xy, s, z, half, step=0.5, crown=0.0):
    """Sample a ribbon around a centreline: returns x, y, z, |lateral| arrays."""
    if len(s) < 2 or s[-1] < 0.3:
        return None
    u = np.arange(0.0, s[-1] + 1e-6, step)
    if u[-1] < s[-1]:
        u = np.append(u, s[-1])
    cx = np.interp(u, s, xy[:, 0])
    cy = np.interp(u, s, xy[:, 1])
    cz = np.interp(u, s, z)
    tx = np.gradient(cx)
    ty = np.gradient(cy)
    tn = np.hypot(tx, ty)
    tn[tn < 1e-9] = 1.0
    nx, ny = -ty / tn, tx / tn
    lat = np.arange(-half, half + 1e-6, step)
    X = cx[:, None] + nx[:, None] * lat[None, :]
    Y = cy[:, None] + ny[:, None] * lat[None, :]
    Z = cz[:, None] - crown * np.abs(lat)[None, :]
    A = np.broadcast_to(np.abs(lat)[None, :], X.shape)
    return X.ravel(), Y.ravel(), Z.ravel(), A.ravel()


def _runs(w, ranges):
    """Arc-length runs of a way outside the given ranges."""
    cuts = sorted(ranges)
    runs, cur = [], 0.0
    for a, b in cuts:
        if a > cur:
            runs.append((cur, a))
        cur = max(cur, b)
    if cur < w.length:
        runs.append((cur, w.length))
    return [(a, b) for a, b in runs if b - a > 0.5]


def _sub(w, a, b):
    m = (w.s >= a) & (w.s <= b)
    s = np.concatenate([[a], w.s[m], [b]])
    xy = np.vstack([w.at(a), w.xy[m], w.at(b)])
    z = np.concatenate([[w.z_at(a)], w.z[m], [w.z_at(b)]])
    s, idx = np.unique(s, return_index=True)
    return xy[idx], s, z[idx]


class Splat:
    """Accumulates prioritised height/material samples onto the terrain grid."""

    def __init__(self):
        self.score = np.full(N * N, -1.0, np.float32)
        self.h = np.zeros(N * N, np.float32)
        self.mat = np.full(N * N, -1, np.int16)
        self.batches = []

    def add(self, x, y, z, score, mat):
        gx, gy = world_to_grid(x, y)
        ix = np.rint(gx).astype(np.int64)
        iy = np.rint(gy).astype(np.int64)
        ok = (ix >= 0) & (ix < N) & (iy >= 0) & (iy < N)
        idx = iy[ok] * N + ix[ok]
        sc = np.asarray(score, np.float32)
        sc = np.broadcast_to(sc, ok.shape)[ok]
        mt = np.broadcast_to(np.asarray(mat, np.int16), ok.shape)[ok]
        np.maximum.at(self.score, idx, sc)
        self.batches.append((idx, sc, np.asarray(z, np.float32)[ok], mt))

    def resolve(self):
        for idx, sc, z, mt in self.batches:
            win = sc >= self.score[idx]
            self.h[idx[win]] = z[win]
            self.mat[idx[win]] = mt[win]
        self.batches = []
        return (self.score.reshape(N, N), self.h.reshape(N, N), self.mat.reshape(N, N))


def carve_water(nat, water):
    """Channels for streams and beds for rivers/ponds. Returns new heights and water surface info."""
    h = nat.copy()
    # Rivers & lakes (polygons): lower the bed below the surface.
    polys = [r for r in water if r["geom"].geom_type in ("Polygon", "MultiPolygon")
             and r["class"] in ("river", "water", "pond", "lake", "reservoir", "basin")
             and r["geom"].area > 120]
    bodies = []
    for r in polys:
        g = r["geom"]
        win = window_of(g, pad=12.0)
        if win is None:
            continue
        r0, r1, c0, c1 = win
        m = poly_mask_window([g], win)
        if m.sum() < 4:
            continue
        sub = nat[r0:r1, c0:c1]
        inner = ndimage.distance_transform_edt(m) * SQ
        is_river = r["class"] == "river"
        if is_river:
            # Surface follows the valley: smooth heavily inside the polygon.
            wsum = ndimage.gaussian_filter(m.astype(np.float32), 10)
            surf = ndimage.gaussian_filter(np.where(m, sub, 0), 10) / np.maximum(wsum, 1e-3) - 0.4
            depth = np.clip(inner / 5.0, 0, 1) * 1.6 + 0.3
        else:
            # Lidar DTMs show lakes as flat water surfaces: use the low end of the inside heights.
            surf_val = float(np.percentile(sub[m], 10)) - 0.2
            surf = np.full_like(sub, surf_val)
            depth = np.clip(inner / 6.0, 0, 1) * 2.0 + 0.35
        bed = np.maximum(surf - depth, sub - 2.5)
        hs = h[r0:r1, c0:c1]
        h[r0:r1, c0:c1] = np.where(m, np.minimum(hs, bed), hs)
        surf_full = None
        if is_river:
            surf_full = (win, surf.astype(np.float32))
        bodies.append({"geom": g, "river": is_river, "name": (r.get("names") or {}).get("primary"),
                       "surface": surf_full if is_river else float(surf_val), "mask": (win, m)})
    # Streams (lines): carve a small channel following a downhill profile.
    sp = Splat()
    for r in water:
        g = r["geom"]
        if g.geom_type != "LineString" or r["class"] not in ("stream", "ditch", "drain", "canal", "river"):
            continue
        st = dict(r.get("source_tags") or [])
        if st.get("tunnel") in ("culvert", "yes"):
            continue
        width = {"river": 6.0, "stream": 1.6, "canal": 1.5, "ditch": 0.8, "drain": 0.8}.get(r["class"], 1.2)
        try:
            width = float(st.get("width", width))
        except ValueError:
            pass
        depth = {"river": 1.6, "stream": 0.8, "canal": 0.7}.get(r["class"], 0.5)
        xy = np.asarray(g.coords)[:, :2]
        seg = np.hypot(*np.diff(xy, axis=0).T)
        s = np.concatenate([[0], np.cumsum(seg)])
        u = np.arange(0, s[-1] + 0.5, 1.0)
        pts = np.column_stack([np.interp(u, s, xy[:, 0]), np.interp(u, s, xy[:, 1])])
        z = sample_grid(nat, pts[:, 0], pts[:, 1])
        z = ndimage.gaussian_filter1d(z, 3, mode="nearest")
        rev = z[-1] > z[0]
        zf = np.minimum.accumulate(z[::-1] if rev else z)
        zf = zf[::-1] if rev else zf
        z = np.maximum(zf, z - 1.0) - depth  # never trench more than ~1 m below the ground
        smp = _profile_samples(pts, u, z, width / 2 + 0.25, step=0.5)
        if smp is None:
            continue
        X, Y, Z, A = smp
        prof = Z + depth * (A / (width / 2 + 0.25)) ** 2 * 0.6
        sp.add(X, Y, prof, 10.0 - A, L_DIRT)
    score, bed, _ = sp.resolve()
    core = score > -1
    if core.any():
        dist, (iy, ix) = ndimage.distance_transform_edt(~core, return_indices=True)
        d = dist * SQ
        lim = bed[iy, ix] + d * 0.9
        cut = np.minimum(h, lim)
        t = np.clip((d - 3.0) / 7.0, 0.0, 1.0)
        cut = cut + (h - cut) * (t * t * (3.0 - 2.0 * t))
        h = np.where(core, np.minimum(h, bed), cut)
    return h, bodies, core


def road_samples(ways):
    """Ribbon samples for all carved ways: (splat, info list)."""
    sp = Splat()
    for w in ways:
        if w.kind == "road" and w.cls not in CAR_CLASSES | {"pedestrian", "footway", "cycleway", "path", "bridleway"}:
            continue
        hw = w.width / 2.0
        if w.kind == "rail":
            hw = 1.6
        half = hw + w.shoulder
        crown = 0.015 if (w.kind == "road" and w.width >= 5.0 and w.surface == "asphalt") else 0.0
        for a, b in _runs(w, w.bridge):
            xy, s, z = _sub(w, a, b)
            smp = _profile_samples(xy, s, z, half, step=0.5, crown=crown)
            if smp is None:
                continue
            X, Y, Z, A = smp
            score = w.rank * 100.0 + 50.0 - A
            if w.kind == "rail":
                mat = np.full(A.shape, L_GRAVEL, np.int16)
            else:
                core_mat = {"asphalt": L_ASPHALT, "paving": L_ASPHALT, "gravel": L_GRAVEL, "dirt": L_DIRT}[w.surface]
                shoulder_mat = L_GRAVEL if w.rank >= 5 else core_mat
                if w.cls in ("path", "footway", "bridleway") and w.surface != "asphalt":
                    core_mat = shoulder_mat = L_DIRT if w.surface == "dirt" else L_GRAVEL
                mat = np.where(A <= hw + 0.05, core_mat, shoulder_mat).astype(np.int16)
                if w.rank <= 1:  # paths: do not dominate the surrounding cells
                    score = score - 30.0
            sp.add(X, Y, Z, score, mat)
    return sp


def carve_roads(base, sp):
    score, core_h, core_mat = sp.resolve()
    core = score > -1
    dist, (iy, ix) = ndimage.distance_transform_edt(~core, return_indices=True)
    d = dist * SQ
    near = core_h[iy, ix]
    # Embankment / cut slopes: gentle rounding next to the road, then ~1:1.4.
    lim = 0.22 * np.minimum(d, 1.5) + 0.8 * np.maximum(d - 1.5, 0.0)
    h = np.clip(base, near - lim, near + lim)
    # Only shape the ground close to the road; fade back to the natural terrain further out.
    t = np.clip((d - 14.0) / 22.0, 0.0, 1.0)
    t = t * t * (3.0 - 2.0 * t)
    h = h + (base - h) * t
    h = np.where(core, core_h, h)
    # Soften the crease between embankment and natural ground (not on the road itself).
    band = (~core) & (d < 40)
    hs = ndimage.gaussian_filter(h, 1.0)
    h = np.where(band, hs, h)
    return h.astype(np.float32), core, core_mat, d


def paint_layers(h, nat, landuse, land, infra, core, core_mat, water_bodies, stream_core, buildings):
    lay = np.full((N, N), L_GRASS, np.uint8)
    lu = {}
    for r in landuse:
        lu.setdefault(r["class"], []).append(r["geom"])
    lawn = [g for c in ("residential", "grass", "park", "garden", "cemetery", "school", "kindergarten", "playground",
                        "recreation_ground", "commercial", "retail", "allotments", "dog_park", "camp_site")
            for g in lu.get(c, [])]
    dirt = [g for c in ("farmyard", "construction", "landfill", "brownfield", "greenfield", "quarry")
            for g in lu.get(c, [])]
    gravel = [g for c in ("industrial", "railway") for g in lu.get(c, [])]
    pitch = [g for c in ("pitch", "track") for g in lu.get(c, [])]
    forest = [r["geom"] for r in land if r["class"] in ("forest", "wood")]
    scrub = [r["geom"] for r in land if r["class"] in ("scrub",)]
    rock = [r["geom"] for r in land if r["class"] in ("bare_rock", "rock", "stone", "scree", "cliff")]
    parking = [r["geom"] for r in infra if r["class"] in ("parking", "parking_space")
               and r["geom"].geom_type in ("Polygon", "MultiPolygon")]
    platforms = [r["geom"] for r in infra if r["class"] == "platform" and r["geom"].geom_type in ("Polygon", "MultiPolygon")]
    if lawn:
        lay[poly_mask(lawn)] = L_LAWN
    if scrub:
        lay[poly_mask(scrub)] = L_GRASS
    if forest:
        lay[poly_mask(forest)] = L_FOREST
    if pitch:
        lay[poly_mask(pitch)] = L_LAWN
    if dirt:
        lay[poly_mask(dirt)] = L_DIRT
    if gravel:
        lay[poly_mask(gravel)] = L_GRAVEL
    # Yards around buildings in farmyards/industry tend to be paved or gravel.
    if buildings:
        lay[poly_mask(buildings, buffer=1.2)] = L_GRAVEL
    if parking:
        lay[poly_mask(parking)] = L_ASPHALT
    if platforms:
        lay[poly_mask(platforms)] = L_ASPHALT
    if rock:
        lay[poly_mask(rock)] = L_ROCK
    gy, gx = np.gradient(ndimage.gaussian_filter(nat, 2.0), SQ)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    lay[(slope > 40) & ~core & (lay != L_FOREST)] = L_ROCK
    lay[(slope > 48) & ~core] = L_ROCK
    for b in water_bodies:
        (r0, r1, c0, c1), m = b["mask"]
        lay[r0:r1, c0:c1][m] = L_DIRT
    lay[stream_core] = L_DIRT
    rc = core & (core_mat >= 0)
    lay[rc] = core_mat[rc].astype(np.uint8)
    return lay


def write_ter(path, heights, z0, max_height, layers, materials=MATERIALS):
    """Write a BeamNG .ter (layout as saved by the World Editor, version 8)."""
    n = heights.shape[0]
    hq = np.clip(np.rint((heights - z0) / max_height * 65535.0), 0, 65535).astype("<u2")
    lay = layers.astype(np.uint8)
    lay2 = np.repeat(np.repeat(lay, 2, axis=0), 2, axis=1)  # layerTextureMap: twice the resolution
    with open(path, "wb") as f:
        f.write(struct.pack("<B", 8))
        f.write(struct.pack("<I", n))
        f.write(hq.tobytes())
        f.write(lay.tobytes())
        f.write(lay2.tobytes())
        f.write(struct.pack("<I", len(materials)))
        for name, _ in materials:
            b = name.encode("ascii")
            f.write(struct.pack("<B", len(b)))
            f.write(b)
    meta = {
        "binaryFormat": "version(char), size(unsigned int), heightMap(heightMapSize * heightMapItemSize), "
                        "layerMap(layerMapSize * layerMapItemSize), layerTextureMap(layerMapSize * layerMapItemSize), materialNames",
        "datafile": f"{C.LEVEL_PATH}/theTerrain.ter",
        "heightMapItemSize": 2,
        "heightMapSize": n * n,
        "heightmapImage": f"{C.LEVEL_PATH}/theTerrain.terrainheightmap.png",
        "layerMapItemSize": 1,
        "layerMapSize": n * n,
        "materials": [m for m, _ in materials],
        "size": n,
        "version": 8,
    }
    with open(path.replace(".ter", ".terrain.json"), "w") as f:
        json.dump(meta, f, indent=2)
    # 16-bit heightmap PNG (north up) so the terrain can also be re-imported in the World Editor.
    Image.fromarray(hq[::-1].astype(np.uint16)).save(path.replace(".ter", ".terrainheightmap.png"))
    return hq


def read_ter_heights(path, z0, max_height):
    with open(path, "rb") as f:
        b = f.read()
    n = struct.unpack("<I", b[1:5])[0]
    h = np.frombuffer(b, "<u2", n * n, 5).reshape(n, n).astype(np.float32)
    return z0 + h / 65535.0 * max_height
