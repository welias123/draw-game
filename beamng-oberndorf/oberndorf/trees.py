"""Trees: low-poly spruce and broadleaf models (with LODs), forest fill and single trees."""
import json
import os

import numpy as np
import shapely

from .collada import Mesh, write_dae
from .roads import sample_grid


def spruce_mesh(detail="hi"):
    m = Mesh()
    segs = 7 if detail == "hi" else 5
    m.add_cylinder("obd_bark", (0, 0, -0.3), 4.0, 0.22, segs=5, top=False, radius_top=0.15)
    if detail == "hi":
        tiers = [(1.6, 9.0, 3.0), (6.0, 8.0, 2.4), (10.5, 7.0, 1.7), (14.5, 5.5, 1.0)]
    else:
        tiers = [(1.8, 18.2, 2.8)]
    for z0, h, r in tiers:
        m.add_cylinder("obd_spruce", (0, 0, z0), h, r, segs=segs, top=False, radius_top=0.0, uv_scale=3)
        # underside disc
        ang = np.linspace(0, 2 * np.pi, segs + 1)
        for i in range(segs):
            m.add_tri("obd_spruce", (r * np.cos(ang[i + 1]), r * np.sin(ang[i + 1]), z0),
                      (r * np.cos(ang[i]), r * np.sin(ang[i]), z0), (0, 0, z0 + 0.4))
    return m


def broadleaf_mesh(detail="hi"):
    m = Mesh()
    m.add_cylinder("obd_bark", (0, 0, -0.3), 4.2, 0.25, segs=5, top=False, radius_top=0.16)
    # crown: two stacked squashed "spheres" (octagonal bicones)
    segs = 8 if detail == "hi" else 5
    blobs = [((0, 0, 3.4), 3.4, 2.6, 3.2), ((0.6, -0.4, 6.2), 2.6, 2.2, 2.8)] if detail == "hi" else [((0, 0, 3.2), 3.6, 0, 5.8)]
    for (cx, cy, cz), r, hb, ht in blobs:
        ang = np.linspace(0, 2 * np.pi, segs + 1)
        zmid = cz + (hb if hb else 0) * 0.5
        bottom = (cx, cy, cz)
        top = (cx, cy, cz + (hb + ht if hb else ht))
        mid = [(cx + r * np.cos(a), cy + r * np.sin(a), zmid) for a in ang]
        for i in range(segs):
            m.add_tri("obd_leaves", mid[i], mid[i + 1], top, ((0, 0), (1, 0), (0.5, 1)))
            m.add_tri("obd_leaves", mid[i + 1], mid[i], bottom, ((0, 0), (1, 0), (0.5, 1)))
    return m


def write_tree_shapes(shape_dir):
    """Tree DAEs with two detail levels (DTS-style hierarchy; trailing numbers are detail sizes)."""
    os.makedirs(shape_dir, exist_ok=True)
    mats = set()
    mats |= set(write_dae(os.path.join(shape_dir, "obd_spruce.dae"),
                          [("spruce_a120", spruce_mesh("hi")), ("spruce_a14", spruce_mesh("lo"))], lod=True))
    mats |= set(write_dae(os.path.join(shape_dir, "obd_broadleaf.dae"),
                          [("broadleaf_a110", broadleaf_mesh("hi")), ("broadleaf_a12", broadleaf_mesh("lo"))], lod=True))
    return sorted(mats)


def _rot(yaw):
    c, s = np.cos(yaw), np.sin(yaw)
    return [round(c, 4), round(-s, 4), 0, round(s, 4), round(c, 4), 0, 0, 0, 1]


def forest_points(land, heights, exclusion, rng, density=1 / 55.0):
    """Random tree positions inside forest polygons (excluding roads, buildings, water)."""
    from .terrain import N, SQ, poly_mask
    forests = [r["geom"] for r in land if r["class"] in ("forest", "wood")]
    if not forests:
        return np.zeros((0, 2))
    mask = poly_mask(forests) & ~exclusion
    # jittered grid
    step = np.sqrt(1 / density)
    xs = np.arange(-N * SQ / 2, N * SQ / 2, step)
    gx, gy = np.meshgrid(xs, xs)
    pts = np.column_stack([gx.ravel(), gy.ravel()]) + rng.uniform(-step * 0.45, step * 0.45, (gx.size, 2))
    ix = np.clip(((pts[:, 0] + N * SQ / 2) / SQ).astype(int), 0, N - 1)
    iy = np.clip(((pts[:, 1] + N * SQ / 2) / SQ).astype(int), 0, N - 1)
    keep = mask[iy, ix]
    return pts[keep]


def write_forest(level_dir, level_path, pts, heights, rng, kind_probs=(("obd_spruce", 0.85), ("obd_broadleaf", 0.15))):
    os.makedirs(os.path.join(level_dir, "forest"), exist_ok=True)
    zs = sample_grid(heights, pts[:, 0], pts[:, 1])
    names = [k for k, _ in kind_probs]
    probs = np.array([p for _, p in kind_probs])
    kinds = rng.choice(len(names), size=len(pts), p=probs / probs.sum())
    files = {}
    for k, name in enumerate(names):
        sel = np.flatnonzero(kinds == k)
        path = os.path.join(level_dir, "forest", f"{name}.forest4.json")
        with open(path, "w") as f:
            for i in sel:
                sc = float(rng.uniform(0.75, 1.35)) if name == "obd_spruce" else float(rng.uniform(0.8, 1.3))
                f.write(json.dumps({"pos": [round(float(pts[i, 0]), 2), round(float(pts[i, 1]), 2), round(float(zs[i]) - 0.15, 2)],
                                    "rotationMatrix": _rot(rng.uniform(0, 2 * np.pi)), "scale": round(sc, 3),
                                    "type": name}, separators=(",", ":")) + "\n")
        files[name] = len(sel)
    data = {}
    import uuid
    for name, shape, radius in (("obd_spruce", "obd_spruce.dae", 0.35), ("obd_broadleaf", "obd_broadleaf.dae", 0.4)):
        data[name] = {
            "name": name, "internalName": name, "class": "TSForestItemData",
            "persistentId": str(uuid.uuid5(uuid.NAMESPACE_URL, "oberndorf/forest/" + name)),
            "shapeFile": f"{level_path}/art/shapes/trees/{shape}",
            "radius": radius, "collidable": True, "mass": 3000, "rigidity": 30,
            "tightnessCoefficient": 0.4, "dampingCoefficient": 0.7, "windScale": 0.4,
            "trunkBendScale": 0.002, "branchAmp": 0.05, "detailAmp": 0.1, "detailFreq": 0.2,
        }
    os.makedirs(os.path.join(level_dir, "art", "forest"), exist_ok=True)
    with open(os.path.join(level_dir, "art", "forest", "managedItemData.json"), "w") as f:
        json.dump(data, f, indent=2)
    return files


def single_trees(world, land, rng):
    """Individual (mapped) trees and tree rows as meshes in the village tiles."""
    hi_b, hi_s = broadleaf_mesh("hi"), spruce_mesh("hi")
    n = 0
    pts = []
    for r in land:
        g = r["geom"]
        if r["class"] == "tree" and g.geom_type == "Point":
            pts.append((g.x, g.y))
        elif r["class"] == "tree_row" and g.geom_type == "LineString":
            for d in np.arange(0, g.length, 7.0):
                q = g.interpolate(d)
                pts.append((q.x, q.y))
    for x, y in pts:
        z = world.ground(x, y) - 0.1
        spruce = rng.random() < 0.3
        base = hi_s if spruce else hi_b
        sc = rng.uniform(0.55, 1.0) if spruce else rng.uniform(0.6, 1.15)
        yaw = rng.uniform(0, 2 * np.pi)
        c, s = np.cos(yaw), np.sin(yaw)
        m = world.mesh(x, y)
        for mat, p in base.parts.items():
            for V, N, UV, F in zip(p["v"], p["n"], p["uv"], p["f"]):
                Vr = V * sc
                Vr = np.column_stack([Vr[:, 0] * c - Vr[:, 1] * s + x, Vr[:, 0] * s + Vr[:, 1] * c + y, Vr[:, 2] + z])
                Nr = np.column_stack([N[:, 0] * c - N[:, 1] * s, N[:, 0] * s + N[:, 1] * c, N[:, 2]])
                m.add(mat, Vr, Nr, UV, F)
        n += 1
    return n
