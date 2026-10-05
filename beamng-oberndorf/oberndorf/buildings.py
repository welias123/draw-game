"""3D buildings from the real footprints: Tyrolean houses with gable roofs, balconies, farms, churches, industry."""
import numpy as np
import shapely
from scipy.spatial import Delaunay

from .collada import Mesh
from .roads import sample_grid

BAY = 3.2      # facade texture: one window bay
FLOOR = 3.0    # storey height (texture repeat)

WALL_MATS = ["bld_plaster_white", "bld_plaster_cream", "bld_plaster_yellow"]
ROOF_MATS = ["bld_roof_grey", "bld_roof_brown", "bld_roof_dark", "bld_roof_red"]


def _rng_for(r):
    return np.random.default_rng(abs(hash(r["id"])) % (2 ** 32))


def _classify(r, area, ctx):
    cls = (r.get("class") or "").lower()
    sub = (r.get("subtype") or "").lower()
    if cls in ("church", "cathedral"):
        return "church"
    if cls in ("chapel", "shrine", "wayside_shrine"):
        return "chapel"
    if cls in ("garage", "garages", "carport", "shed", "hut", "kiosk", "toilets", "transformer_tower", "service"):
        return "garage" if cls != "carport" else "carport"
    if cls in ("roof", "shelter"):
        return "carport"
    if cls in ("cowshed", "barn", "stable", "farm_auxiliary", "greenhouse") or sub == "agricultural" and cls != "farm":
        return "barn"
    if cls == "farm":
        return "farmhouse"
    if cls in ("industrial", "warehouse", "hangar") or sub == "industrial":
        return "industrial"
    if cls in ("retail", "commercial", "supermarket", "office") or sub == "commercial" and cls != "hotel":
        return "commercial" if area < 2500 else "industrial"
    if cls == "hotel":
        return "hotel"
    if cls in ("apartments",):
        return "apartments"
    if sub in ("education", "medical", "civic", "entertainment", "religious") or cls in ("school", "hospital", "public",
                                                                                         "government", "fire_station",
                                                                                         "sports_hall", "sports_centre"):
        return "public"
    if cls == "train_station":
        return "public"
    # Unknown: decide by size and land use context.
    if area < 22:
        return "garage"
    if ctx == "industrial":
        return "industrial" if area > 150 else "garage"
    if ctx == "commercial":
        return "commercial" if area > 120 else "garage"
    if ctx == "farmyard":
        return "barn" if area > 160 else ("farmhouse" if area > 70 else "garage")
    if area < 55:
        return "garage"
    if area > 1200:
        return "industrial"
    if area > 450:
        return "apartments"
    return "house"


def _obb(poly):
    """Oriented bounding box: centre, long axis unit vector, half length, half width."""
    rect = poly.minimum_rotated_rectangle
    c = np.asarray(rect.exterior.coords)[:4]
    e0 = c[1] - c[0]
    e1 = c[2] - c[1]
    l0, l1 = np.hypot(*e0), np.hypot(*e1)
    if l0 >= l1:
        ax, hl, hw = e0 / max(l0, 1e-9), l0 / 2, l1 / 2
    else:
        ax, hl, hw = e1 / max(l1, 1e-9), l1 / 2, l0 / 2
    ctr = c.mean(0)
    return ctr, ax, hl, hw


class RoofFn:
    """Height of the roof surface above the eave line as a function of the 2D position."""

    def __init__(self, kind, ctr, ax, hl, hw, pitch, cap=None, poly=None):
        self.kind, self.ctr, self.ax, self.hl, self.hw = kind, ctr, ax, hl, hw
        self.k = np.tan(np.radians(pitch))
        self.perp = np.array([-ax[1], ax[0]])
        self.cap = cap
        self.poly = poly

    def __call__(self, p):
        p = np.atleast_2d(p)
        d = p - self.ctr
        da = np.abs(d @ self.ax)
        db = np.abs(d @ self.perp)
        if self.kind == "gable":
            z = self.k * (self.hw - db)
        elif self.kind == "hipped":
            z = self.k * np.minimum(self.hw - db, self.hl - da)
        elif self.kind == "skeleton":
            bd = shapely.distance(shapely.points(p), self.poly.exterior)
            inside = shapely.contains_xy(self.poly, p[:, 0], p[:, 1])
            z = self.k * np.where(inside, bd, -bd)
        else:
            z = np.zeros(len(p))
        if self.cap is not None:
            z = np.minimum(z, self.cap)
        return z

    def ridge_lines(self, extent):
        """Crease lines used to split the roof polygon into planar pieces."""
        c, a, b = self.ctr, self.ax, self.perp
        E = extent
        if self.kind == "gable":
            return [shapely.LineString([c - a * E, c + a * E])]
        if self.kind == "hipped":
            r = max(self.hl - self.hw, 0.0)
            p0, p1 = c - a * r, c + a * r
            lines = [shapely.LineString([p0, p1])] if r > 0.01 else []
            for s in (-1, 1):
                for pt, sgn in ((p0, -1), (p1, 1)):
                    d = (a * sgn + b * s)
                    lines.append(shapely.LineString([pt, pt + d / np.linalg.norm(d) * E]))
            return lines
        return []


def _orient_ccw(poly):
    return shapely.geometry.polygon.orient(poly, 1.0)


def _triangulate_planar(piece):
    tris = shapely.constrained_delaunay_triangles(piece)
    out = []
    for t in tris.geoms:
        if t.area < 1e-4:
            continue
        c = np.asarray(t.exterior.coords)[:3]
        if np.cross(c[1] - c[0], c[2] - c[0]) < 0:
            c = c[::-1]
        out.append(c)
    return out


def _roof_mesh(mesh, mat, poly_roof, fn, eave_z, uv_axis, thickness=0.18, fascia_mat=None):
    """Roof surface over poly_roof (2D) at eave_z + fn(p), plus a fascia board around the edge."""
    if fn.kind in ("gable", "hipped"):
        ext = float(np.hypot(*(np.asarray(poly_roof.bounds[2:]) - poly_roof.bounds[:2]))) + 5
        lines = fn.ridge_lines(ext)
        if lines:
            pieces = shapely.polygonize([shapely.union_all([poly_roof.boundary] + [l.intersection(poly_roof) for l in lines])])
            pieces = [p for p in pieces.geoms if p.area > 0.01 and poly_roof.buffer(0.01).contains(p.representative_point())]
        else:
            pieces = [poly_roof]
        tris = [t for p in pieces for t in _triangulate_planar(p)]
    elif fn.kind == "skeleton":
        b = poly_roof.boundary
        L = b.length
        bpts = [np.asarray(b.interpolate(d).coords[0]) for d in np.arange(0, L, 1.2)]
        x0, y0, x1, y1 = poly_roof.bounds
        gx, gy = np.meshgrid(np.arange(x0, x1, 1.5), np.arange(y0, y1, 1.5))
        g = np.column_stack([gx.ravel(), gy.ravel()])
        inside = shapely.contains_xy(poly_roof.buffer(-0.3), g[:, 0], g[:, 1])
        pts = np.vstack([np.asarray(bpts), g[inside]]) if inside.any() else np.asarray(bpts)
        if len(pts) < 3:
            return
        dt = Delaunay(pts)
        tris = []
        for simp in dt.simplices:
            c = pts[simp]
            cen = c.mean(0)
            if not shapely.contains_xy(poly_roof, cen[0], cen[1]):
                continue
            if np.cross(c[1] - c[0], c[2] - c[0]) < 0:
                c = c[::-1]
            tris.append(c)
    else:
        tris = _triangulate_planar(poly_roof)
    if not tris:
        return
    T = np.asarray(tris)  # (n, 3, 2)
    flat = T.reshape(-1, 2)
    z = eave_z + fn(flat)
    V = np.column_stack([flat, z])
    perp = np.array([-uv_axis[1], uv_axis[0]])
    U = np.column_stack([flat @ uv_axis / 2.0, flat @ perp / 2.0])
    Tri3 = V.reshape(-1, 3, 3)
    nrm = np.cross(Tri3[:, 1] - Tri3[:, 0], Tri3[:, 2] - Tri3[:, 0])
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
    nrm[nrm[:, 2] < 0] *= -1
    N = np.repeat(nrm, 3, axis=0)
    F = np.arange(len(V)).reshape(-1, 3)
    mesh.add(mat, V, N, U, F)  # roof materials are double sided, so the overhang is visible from below
    # Fascia around the roof outline.
    ring = np.asarray(poly_roof.exterior.coords)
    zr = eave_z + fn(ring)
    for i in range(len(ring) - 1):
        a, b = ring[i], ring[i + 1]
        if np.hypot(*(b - a)) < 0.05:
            continue
        mesh.add_quad(fascia_mat or mat, (*a, zr[i] - thickness), (*b, zr[i + 1] - thickness), (*b, zr[i + 1]), (*a, zr[i]))


def _walls(mesh, poly, z_bottom, gf, eave, fn, mats, bay=BAY, upper_mat=None, upper_from=None):
    """Extrude walls from z_bottom up to the roof surface (eave + fn) along the footprint outline."""
    ring = np.asarray(poly.exterior.coords)[:, :2]
    # Insert vertices where the outline crosses roof creases so wall tops follow the roof.
    creases = fn.ridge_lines(1000.0) if fn.kind in ("gable", "hipped") else []
    pts = [ring[0]]
    for i in range(len(ring) - 1):
        a, b = ring[i], ring[i + 1]
        L = np.hypot(*(b - a))
        if L < 1e-6:
            continue
        if creases:
            seg = shapely.LineString([a, b])
            ts = []
            for cl in creases:
                x = seg.intersection(cl)
                for q in getattr(x, "geoms", [x]):
                    if q.geom_type == "Point":
                        t = seg.project(q) / L
                        if 1e-4 < t < 1 - 1e-4:
                            ts.append(t)
            for t in sorted(ts):
                pts.append(a + (b - a) * t)
            pts.append(b)
        elif fn.kind == "skeleton":
            n = max(int(L / 0.75), 1)
            for t in np.linspace(0, 1, n + 1)[1:]:
                pts.append(a + (b - a) * t)
        else:
            pts.append(b)
    pts = np.asarray(pts)
    top = eave + np.maximum(fn(pts), 0.0)
    plain, win = mats
    # Group into straight wall runs for nice window spacing.
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        L = float(np.hypot(*(b - a)))
        if L < 0.02:
            continue
        za, zb = top[i], top[i + 1]
        # basement / plinth part
        if gf - z_bottom > 0.05:
            mesh.add_quad(plain, (*a, z_bottom), (*b, z_bottom), (*b, gf), (*a, gf),
                          ((0, (z_bottom - gf) / FLOOR), (L / bay, (z_bottom - gf) / FLOOR), (L / bay, 0), (0, 0)))
        mat = win if L > 1.6 else plain
        if upper_mat and upper_from is not None and min(za, zb) > upper_from:
            # two bands: plaster below, wood above
            mesh.add_quad(mat, (*a, gf), (*b, gf), (*b, upper_from), (*a, upper_from),
                          ((0, 0), (L / bay, 0), (L / bay, (upper_from - gf) / FLOOR), (0, (upper_from - gf) / FLOOR)))
            mesh.add_quad(upper_mat, (*a, upper_from), (*b, upper_from), (*b, zb), (*a, za),
                          ((0, (upper_from - gf) / FLOOR), (L / bay, (upper_from - gf) / FLOOR),
                           (L / bay, (zb - gf) / FLOOR), (0, (za - gf) / FLOOR)))
        else:
            mesh.add_quad(mat, (*a, gf), (*b, gf), (*b, zb), (*a, za),
                          ((0, 0), (L / bay, 0), (L / bay, (zb - gf) / FLOOR), (0, (za - gf) / FLOOR)))


def _balconies(mesh, ctr, ax, hl, hw, z_floor, rng):
    """Tyrolean wooden balconies along both eave sides, with flower boxes."""
    perp = np.array([-ax[1], ax[0]])
    length = 2 * hl - 1.2
    if length < 3:
        return
    for s in (-1, 1):
        if rng.random() < 0.25:
            continue
        c = ctr + perp * s * (hw + 0.55)
        mesh.add_box("bld_balcony", (c[0], c[1], z_floor), (length, 1.1, 0.16), axis=ax, uv_scale=0.5)
        cr = ctr + perp * s * (hw + 1.08)
        mesh.add_box("bld_balcony", (cr[0], cr[1], z_floor + 0.55), (length, 0.06, 0.95), axis=ax, uv_scale=0.5)
        for e in (-1, 1):
            ce = ctr + perp * s * (hw + 0.55) + ax * e * (length / 2)
            mesh.add_box("bld_balcony", (ce[0], ce[1], z_floor + 0.55), (0.06, 1.1, 0.95), axis=ax, uv_scale=0.5)
        cf = ctr + perp * s * (hw + 1.18)
        mesh.add_box("obd_flowers", (cf[0], cf[1], z_floor + 1.1), (length * 0.9, 0.22, 0.22), axis=ax, uv_scale=0.5)


def _tower(mesh, base_xy, z0, size, height, roof_mat, wall_mat, ax):
    c = np.asarray(base_xy)
    mesh.add_box(wall_mat, (c[0], c[1], z0 + height / 2), (size, size, height), axis=ax, uv_scale=1 / FLOOR)
    # Onion-free pointed spire (typical Tyrolean church: tall pyramid with a clock band).
    perp = np.array([-ax[1], ax[0]])
    hs = size / 2 + 0.15
    corners = [c + ax * i * hs + perp * j * hs for i, j in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    apex = (c[0], c[1], z0 + height + size * 2.2)
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        mesh.add_tri(roof_mat, (*a, z0 + height), (*b, z0 + height), apex, ((0, 0), (1, 0), (0.5, 3)))
    mesh.add_box("obd_clock", (c[0], c[1], z0 + height - 2.0), (size + 0.04, size + 0.04, 1.6), axis=ax, uv_scale=1 / 1.6)


def build_buildings(buildings, landuse, heights):
    """Returns list of (centroid_xy, Mesh) in world coordinates."""
    ctx_geoms, ctx_kind = [], []
    for r in landuse:
        k = {"industrial": "industrial", "commercial": "commercial", "retail": "commercial",
             "farmyard": "farmyard"}.get(r["class"])
        if k:
            ctx_geoms.append(r["geom"])
            ctx_kind.append(k)
    tree = shapely.STRtree(ctx_geoms) if ctx_geoms else None
    out = []
    stats = {}
    for r in buildings:
        g = r["geom"]
        if g.geom_type == "MultiPolygon":
            g = max(g.geoms, key=lambda p: p.area)
        if g.geom_type != "Polygon" or g.area < 4:
            continue
        if r.get("is_underground"):
            continue
        poly = _orient_ccw(shapely.Polygon(g.exterior).simplify(0.15))
        if not poly.is_valid or poly.area < 4:
            poly = _orient_ccw(shapely.Polygon(g.exterior).buffer(0))
            if poly.geom_type != "Polygon":
                continue
        area = poly.area
        ctx = None
        if tree is not None:
            for i in tree.query(poly.centroid, predicate="within"):
                ctx = ctx_kind[i]
                break
        kind = _classify(r, area, ctx)
        stats[kind] = stats.get(kind, 0) + 1
        rng = _rng_for(r)
        m = Mesh()
        ring = np.asarray(poly.exterior.coords)[:, :2]
        gz = sample_grid(heights, ring[:, 0], ring[:, 1])
        zc = float(sample_grid(heights, [poly.centroid.x], [poly.centroid.y])[0])
        zmin, zmax = float(min(gz.min(), zc)), float(max(gz.max(), zc))
        gf = zmax - min(0.4, 0.25 * (zmax - zmin)) + 0.1
        z_bottom = zmin - 0.6
        ctr, ax, hl, hw = _obb(poly)
        rect = area / max(4 * hl * hw, 1e-6)
        H = r.get("height")
        floors = r.get("num_floors")
        # defaults per type: (floors, pitch, overhang, roof kind)
        if kind == "house":
            nfl = 2 if area < 140 else 3
            pitch, over = rng.uniform(20, 28), 0.9
        elif kind == "farmhouse":
            nfl, pitch, over = 2, rng.uniform(20, 26), 1.1
        elif kind == "barn":
            nfl, pitch, over = 2, rng.uniform(18, 24), 0.8
        elif kind == "apartments":
            nfl, pitch, over = 4, 22, 0.8
        elif kind == "hotel":
            nfl, pitch, over = 4, 22, 1.0
        elif kind == "public":
            nfl, pitch, over = 3, 24, 0.6
        elif kind == "commercial":
            nfl, pitch, over = 2, 10, 0.4
        elif kind == "industrial":
            nfl, pitch, over = 2, 7, 0.3
        elif kind == "church":
            nfl, pitch, over = 3, 42, 0.5
        elif kind == "chapel":
            nfl, pitch, over = 1, 40, 0.3
        elif kind == "carport":
            nfl, pitch, over = 1, 12, 0.2
        else:  # garage / shed
            nfl, pitch, over = 1, rng.uniform(12, 22), 0.4
        if floors:
            nfl = max(1, int(floors))
        wall_h = {"industrial": 7.0, "church": 10.0, "chapel": 3.4, "garage": 2.6, "carport": 2.5,
                  "barn": 6.0}.get(kind, nfl * 2.9 + 0.2)
        roof_kind = "gable"
        rs = (r.get("roof_shape") or "").lower()
        if rs in ("flat",) or (kind == "industrial" and area > 900):
            roof_kind = "flat"
        elif rs in ("hipped", "pyramidal", "half-hipped") or kind == "public" and area > 400:
            roof_kind = "hipped"
        elif rect < 0.8 and kind not in ("garage", "carport"):
            roof_kind = "skeleton"
        roof_h_est = np.tan(np.radians(pitch)) * hw if roof_kind != "flat" else 0.3
        if H:
            # The given height is the ridge (top) height above ground.
            wall_h = max(2.4, float(H) - roof_h_est)
            if wall_h > 40:
                wall_h = 40
        eave = gf + wall_h
        cap = None
        if roof_kind == "skeleton":
            cap = np.tan(np.radians(pitch)) * min(hw, 7.0)
        fn = RoofFn(roof_kind, ctr, ax, hl, hw, pitch, cap=cap, poly=poly if roof_kind == "skeleton" else None)
        if roof_kind == "flat":
            fn = RoofFn("flat", ctr, ax, hl, hw, 0)
        # materials
        wall_choice = WALL_MATS[int(rng.integers(0, len(WALL_MATS)))] if rng.random() < 0.45 else WALL_MATS[0]
        roof_mat = ROOF_MATS[int(rng.choice(4, p=[0.45, 0.25, 0.22, 0.08]))]
        upper_mat = upper_from = None
        if kind in ("industrial",):
            mats = ("bld_concrete", "bld_metal")
            roof_mat = "bld_roof_metal"
        elif kind == "barn":
            mats = ("bld_concrete", "bld_barn")
            roof_mat = "bld_roof_metal" if rng.random() < 0.5 else roof_mat
        elif kind == "commercial":
            mats = ("bld_plaster_white", "bld_shop")
            upper_mat = "bld_plaster_white_win"
            upper_from = gf + 3.5
        elif kind in ("garage", "carport"):
            mats = (wall_choice, wall_choice)
        elif kind in ("church", "chapel"):
            mats = ("bld_plaster_white", "bld_plaster_white_win")
            roof_mat = "bld_roof_dark" if kind == "church" else "bld_roof_red"
        else:
            mats = (wall_choice, wall_choice + "_win")
            if kind in ("house", "farmhouse", "hotel") and nfl >= 2 and rng.random() < (0.85 if kind == "farmhouse" else 0.5):
                upper_mat = "bld_wood_win"
                upper_from = eave - FLOOR + 0.2
        if kind == "carport":
            # Roof on posts.
            for p in ring[:-1]:
                m.add_box("bld_wood", (p[0], p[1], (gf + eave) / 2), (0.15, 0.15, eave - gf + 0.2), axis=ax)
        else:
            _walls(m, poly, z_bottom, gf, eave, fn, mats, upper_mat=upper_mat, upper_from=upper_from)
        roof_poly = poly.buffer(over, join_style="mitre", mitre_limit=2.0) if over > 0 else poly
        if roof_poly.geom_type != "Polygon":
            roof_poly = poly
        roof_poly = _orient_ccw(roof_poly)
        if roof_kind == "flat":
            _roof_mesh(m, "bld_concrete", poly, fn, eave + 0.05, ax, thickness=0.3, fascia_mat="bld_concrete")
        else:
            _roof_mesh(m, roof_mat, roof_poly, fn, eave, ax, fascia_mat="bld_wood")
        if kind in ("house", "farmhouse", "hotel") and roof_kind == "gable" and rect > 0.85 and nfl >= 2 and 50 < area < 700:
            if rng.random() < 0.75:
                _balconies(m, ctr, ax, hl, hw, eave - FLOOR + 0.1, rng)
        if kind == "church":
            tpos = ctr - ax * (hl - 2.6)
            _tower(m, tpos, gf, min(5.5, hw * 1.2), max(wall_h + 14, 26.0), "bld_roof_dark", "bld_plaster_white", ax)
        if kind == "chapel":
            tpos = ctr + ax * (hl * 0.5)
            ridge = eave + fn(np.array([ctr]))[0]
            _tower(m, tpos, ridge - 0.5, 1.4, 2.0, "bld_roof_red", "bld_plaster_white", ax)
        out.append(((poly.centroid.x, poly.centroid.y), m))
    return out, stats
