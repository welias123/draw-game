"""Street furniture and infrastructure meshes: Austrian traffic signs, lamps, signals, delineators,
guardrails, fences, walls, benches, railway (track, catenary, platforms) and bridges."""
import numpy as np
import shapely

from .collada import Mesh
from .markings import car, is_urban, junction_info
from .roads import MAJOR, sample_grid

TILE = 256.0
UP = np.array([0.0, 0.0, 1.0])


class World:
    """Collects meshes in world coordinates, bucketed into square tiles."""

    def __init__(self, heights, tile=TILE):
        self.h = heights
        self.tile = tile
        self.tiles = {}

    def mesh(self, x, y):
        k = (int(np.floor(x / self.tile)), int(np.floor(y / self.tile)))
        if k not in self.tiles:
            self.tiles[k] = Mesh()
        return self.tiles[k]

    def ground(self, x, y):
        return float(sample_grid(self.h, [x], [y])[0])


# ------------------------------------------------------------------------------------------- signs

def _shape(kind):
    if kind == "tri_down":
        return [(-0.469, 0.422), (0.469, 0.422), (0.0, -0.391)]
    if kind == "octagon":
        r = 0.484
        return [(r * np.cos(np.radians(22.5 + 45 * i)), -r * np.sin(np.radians(22.5 + 45 * i))) for i in range(8)][::-1]
    if kind == "diamond":
        return [(0, 0.49), (-0.49, 0), (0, -0.49), (0.49, 0)][::-1]
    if kind == "circle":
        r = 0.484
        return [(r * np.cos(a), r * np.sin(a)) for a in np.linspace(0, 2 * np.pi, 25)[:-1]]
    return [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)]


def sign_plate(m, mat, kind, center, facing, sx, sy):
    """Flat sign plate: front textured (CCW seen from the front), grey back."""
    n = np.array([facing[0], facing[1], 0.0])
    n /= np.linalg.norm(n)
    r = np.array([-n[1], n[0], 0.0])
    c = np.asarray(center, np.float64)
    poly = _shape(kind)
    area = sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
               for i in range(len(poly)))
    if area < 0:  # front face must be counter-clockwise as seen by the viewer
        poly = poly[::-1]
    P = [c + r * (u * sx) + UP * (v * sy) for u, v in poly]
    UV = [(u + 0.5, v + 0.5) for u, v in poly]
    k = len(P)
    V = np.array(P)
    F = [[0, i, i + 1] for i in range(1, k - 1)]
    m.add(mat, V, np.tile(n, (k, 1)), UV, F)
    Vb = V - n * 0.012
    m.add("obd_sign_back", Vb, np.tile(-n, (k, 1)), UV, [[0, i + 1, i] for i in range(1, k - 1)])
    # rim
    for i in range(k):
        a, b = V[i], V[(i + 1) % k]
        m.add_quad("obd_sign_back", a - n * 0.012, b - n * 0.012, b, a)


def pole(m, x, y, z0, height, r=0.03, mat="obd_pole"):
    m.add_cylinder(mat, (x, y, z0 - 0.3), height + 0.3, r, segs=8)


def place_sign(world, items, pos, facing, bottom=2.0):
    """items: list of (material, shape, width, height) stacked top to bottom on one pole."""
    x, y = pos
    m = world.mesh(x, y)
    zg = world.ground(x, y)
    total = sum(h for _, _, _, h in items) + 0.05 * (len(items) - 1)
    top = zg + bottom + total
    n = np.array([facing[0], facing[1]])
    n = n / np.linalg.norm(n)
    px, py = x - n[0] * 0.05, y - n[1] * 0.05
    pole(m, px, py, zg, top - zg + 0.05)
    z = top
    for mat, kind, w, h in items:
        z -= h / 2
        sign_plate(m, mat, kind, (x, y, z), n, w, h)
        z -= h / 2 + 0.05


def roadside(w, s, sign_dir, extra=0.9):
    """Point on the right side of travel direction sign_dir (+1 = increasing s) and facing vector."""
    t = w.tangent(s) * sign_dir
    right = np.array([t[1], -t[0]])
    p = w.at(s) + right * (w.width / 2 + extra)
    return p, -t


SIGN_SIZES = {"give_way": (0.9, 0.9), "stop": (0.75, 0.75), "priority": (0.65, 0.65), "speed": (0.6, 0.6),
              "crosswalk": (0.6, 0.6), "bus": (0.45, 0.45), "town": (1.2, 0.8), "street": (0.85, 0.16),
              "andreas": (1.1, 0.2)}


def build_signs(world, ways, junctions, control, zebras, busstops, infra, builtup, localities, sign_reg):
    """sign_reg(kind, key) -> material name (registers a texture to be generated)."""
    count = {}

    def add(kind, items, pos, facing, bottom=2.0):
        place_sign(world, items, pos, facing, bottom)
        count[kind] = count.get(kind, 0) + 1

    # Give way / stop at junction approaches
    for c in control:
        w, sgn = c["way"], c["sign"]
        s = float(np.clip(c["s"] - sgn * (c["major"].width / 2 + 1.2), 0, w.length))
        p, f = roadside(w, s, sgn, 0.8)
        if c["kind"] == "stop":
            add("stop", [(sign_reg("stop", None), "octagon", *SIGN_SIZES["stop"])], p, f)
        else:
            add("give_way", [(sign_reg("give_way", None), "tri_down", *SIGN_SIZES["give_way"])], p, f)
    # Vorrangstrasse after junctions on the priority road (both directions), spaced >= 250 m
    placed = []
    for c in control:
        mj, s0 = c["major"], c["major_s"]
        if mj.cls not in ("primary", "secondary", "tertiary"):
            continue
        for sgn in (+1, -1):
            if mj.oneway and sgn != mj.oneway:
                continue
            s = s0 + sgn * 25.0
            if not (0 < s < mj.length) or mj.in_ranges(s, mj.bridge, 5):
                continue
            p, f = roadside(mj, s, sgn, 1.0)
            if any(np.hypot(*(p - q)) < 250 and np.dot(f, g) > 0.7 for q, g in placed):
                continue
            placed.append((p, f))
            add("priority", [(sign_reg("priority", None), "diamond", *SIGN_SIZES["priority"])], p, f)
    # Speed limits, Ortstafel / Ortsende: transitions inside a way and between continuing ways
    events = []
    for w in ways:
        if not car(w) or w.rank < 4 or not w.speed:
            continue
        sp = sorted(w.speed)
        for (a0, a1, v0), (b0, b1, v1) in zip(sp[:-1], sp[1:]):
            if v0 != v1 and abs(a1 - b0) <= 2.0:
                events.append((w, b0, +1, v1, v0))
                events.append((w, b0, -1, v0, v1))
    for cid, lst in junctions.items():
        cw = [(w, s) for w, s in lst if car(w) and w.rank >= 4]
        for wa, sa in cw:
            for wb, sb in cw:
                if wa is wb or not _continues(wa, sa, wb, sb):
                    continue
                if sb < 1.0:
                    sgn, ss = +1, min(sb + 8.0, wb.length)
                elif sb > wb.length - 1.0:
                    sgn, ss = -1, max(sb - 8.0, 0.0)
                else:
                    continue
                va, vb = wa.speed_at(sa), wb.speed_at(ss)
                if va and vb and va != vb:
                    events.append((wb, ss, sgn, vb, va))
    done_ev = []
    for w, s, sgn, vnew, vold in events:
        if w.oneway and sgn != w.oneway:
            continue
        p, f = roadside(w, s, sgn, 1.0)
        if any(np.hypot(*(p - q)) < 15 and np.dot(f, g) > 0.7 for q, g in done_ev):
            continue
        done_ev.append((p, f))
        if vnew == 50 and vold > 50 and w.cls in MAJOR:
            name = locality_at(localities, p)
            add("town", [(sign_reg("town", name), "rect", *SIGN_SIZES["town"])], p, f, bottom=1.6)
        elif vold == 50 and vnew > 50 and w.cls in MAJOR:
            name = locality_at(localities, p)
            items = [(sign_reg("town_end", name), "rect", *SIGN_SIZES["town"])]
            if vnew != 100:
                items.insert(0, (sign_reg("speed", vnew), "circle", *SIGN_SIZES["speed"]))
            add("town_end", items, p, f, bottom=1.6)
        else:
            add("speed", [(sign_reg("speed", vnew), "circle", *SIGN_SIZES["speed"])], p, f)
    # Schutzweg signs on both sides for both directions
    for z in zebras:
        w = z["way"]
        for sgn in (+1, -1):
            if w.oneway and sgn != w.oneway:
                continue
            p, f = roadside(w, z["s"] - sgn * 1.0, sgn, 0.6)
            add("crosswalk", [(sign_reg("crosswalk", None), "rect", *SIGN_SIZES["crosswalk"])], p, f)
    # Bus stops: H sign + stop name plate
    seen = []
    for b in busstops:
        w, s, side = b["way"], b["s"], b["side"]
        p = b["point"]
        if any(np.hypot(*(p - q)) < 8 for q in seen):
            continue
        seen.append(p)
        t = w.tangent(s)
        right = np.array([t[1], -t[0]]) * side
        q = w.at(s) + right * (w.width / 2 + 1.2)
        items = [(sign_reg("bus", None), "circle", *SIGN_SIZES["bus"])]
        if b["name"]:
            items.append((sign_reg("plate", b["name"]), "rect", 0.6, 0.15))
        add("bus", items, q, t if side > 0 else -t, bottom=2.1)
        _bench(world, q + right * 1.2, t)
    # Street name signs at junctions of differently named roads
    jinfo = junction_info(ways, junctions)
    done = set()
    for w in ways:
        if not car(w) or not w.name or w.rank < 4:
            continue
        for s, cid, others in jinfo[id(w)]:
            oth = [o for o, _ in others if car(o) and o.name and o.name != w.name and o.rank >= w.rank]
            if not oth or (cid, w.name) in done:
                continue
            done.add((cid, w.name))
            sgn = 1 if s < w.length / 2 else -1
            d = oth[0].width / 2 + 2.5
            ss = s + sgn * d
            if not (0 <= ss <= w.length):
                continue
            t = w.tangent(ss) * sgn
            right = np.array([t[1], -t[0]])
            p = w.at(ss) + right * (w.width / 2 + 1.0)
            # plate parallel to the street (readable from the crossing road), double sided
            facing = np.array([t[1], -t[0]])
            mat = sign_reg("street", w.name)
            m = world.mesh(*p)
            zg = world.ground(*p)
            pole(m, p[0], p[1], zg, 2.6)
            sign_plate(m, mat, "rect", (p[0] + facing[0] * 0.04, p[1] + facing[1] * 0.04, zg + 2.45), facing, 0.85, 0.16)
            sign_plate(m, mat, "rect", (p[0] - facing[0] * 0.04, p[1] - facing[1] * 0.04, zg + 2.45), -facing, 0.85, 0.16)
            count["street"] = count.get("street", 0) + 1
    # Andreaskreuz at level crossings
    for cid, lst in junctions.items():
        if not cid.startswith("lx_"):
            continue
        for w, s in lst:
            if w.kind != "road" or not car(w):
                continue
            for sgn in (+1, -1):
                ss = s - sgn * 8.0
                if not (0 < ss < w.length):
                    continue
                p, f = roadside(w, ss, sgn, 0.8)
                _andreas(world, p, f, sign_reg("andreas", None))
                count["andreas"] = count.get("andreas", 0) + 1
    return count


def _continues(wa, sa, wb, sb):
    """True if way wb continues way wa at this junction (same street or straight on)."""
    if wa.name and wa.name == wb.name or wa.ref and wa.ref == wb.ref:
        return True
    if wa.cls not in MAJOR or wb.cls not in MAJOR:
        return False
    da = wa.tangent(sa) * (1 if sa > wa.length / 2 else -1)   # direction arriving at the junction
    db = wb.tangent(sb) * (1 if sb < wb.length / 2 else -1)   # direction leaving the junction
    return float(np.dot(da, db)) > 0.82


def _andreas(world, p, f, mat):
    m = world.mesh(*p)
    zg = world.ground(*p)
    pole(m, p[0], p[1], zg, 2.6, r=0.04)
    n = np.array([f[0], f[1], 0.0]) / np.linalg.norm(f)
    r = np.array([-n[1], n[0], 0.0])
    c = np.array([p[0], p[1], zg + 2.1]) + n * 0.05
    for ang in (30, -30):
        a = np.radians(ang)
        d = r * np.cos(a) + UP * np.sin(a)
        e = np.cross(n, d)
        L, H = 1.1, 0.2
        q = [c - d * L / 2 - e * H / 2, c + d * L / 2 - e * H / 2, c + d * L / 2 + e * H / 2, c - d * L / 2 + e * H / 2]
        m.add_quad(mat, *q)
        m.add_quad("obd_sign_back", q[1] - n * 0.01, q[0] - n * 0.01, q[3] - n * 0.01, q[2] - n * 0.01)
        c = c + n * 0.01


def locality_at(localities, p):
    for name, g in localities:
        if shapely.contains_xy(g, p[0], p[1]):
            return name.replace("Sankt ", "St. ")  # as written on the real Ortstafel
    return "Oberndorf in Tirol"


# ------------------------------------------------------------------------------------------- furniture

def _bench(world, p, t):
    m = world.mesh(*p)
    zg = world.ground(*p)
    ax = np.asarray(t, np.float64)
    perp = np.array([-ax[1], ax[0]])
    m.add_box("obd_fence_wood", (p[0], p[1], zg + 0.45), (1.8, 0.42, 0.06), axis=ax)
    bp = p + perp * 0.2
    m.add_box("obd_fence_wood", (bp[0], bp[1], zg + 0.75), (1.8, 0.05, 0.4), axis=ax)
    for e in (-0.75, 0.75):
        q = p + ax * e
        m.add_box("obd_pole", (q[0], q[1], zg + 0.21), (0.06, 0.4, 0.45), axis=ax)


def build_lamps_signals(world, ways, infra):
    cars = [w for w in ways if car(w)]
    tree = shapely.STRtree([shapely.LineString(w.xy) for w in cars])
    n_l = n_s = n_b = 0
    for r in infra:
        g = r["geom"]
        if g.geom_type != "Point":
            continue
        x, y = g.x, g.y
        cls = r["class"]
        if cls == "street_lamp":
            idx = tree.query(g.buffer(25))
            zg = world.ground(x, y)
            m = world.mesh(x, y)
            if len(idx):
                w = min((cars[i] for i in idx), key=lambda w: shapely.LineString(w.xy).distance(g))
                s = shapely.LineString(w.xy).project(g)
                d = w.at(s) - np.array([x, y])
                d = d / max(np.linalg.norm(d), 1e-6)
            else:
                d = np.array([1.0, 0.0])
            m.add_cylinder("obd_lamp", (x, y, zg - 0.3), 6.8, 0.07, segs=8, radius_top=0.05)
            arm_end = np.array([x, y]) + d * 1.4
            m.add_box("obd_lamp", ((x + arm_end[0]) / 2, (y + arm_end[1]) / 2, zg + 6.4), (1.45, 0.06, 0.06), axis=d)
            m.add_box("obd_lamp", (arm_end[0], arm_end[1], zg + 6.3), (0.6, 0.28, 0.12), axis=d)
            m.add_box("obd_lamp_glass", (arm_end[0], arm_end[1], zg + 6.235), (0.5, 0.22, 0.01), axis=d)
            n_l += 1
        elif cls == "traffic_signals":
            idx = [i for i in tree.query(g.buffer(10)) if cars[i].rank >= 4]
            idx = sorted(idx, key=lambda i: shapely.LineString(cars[i].xy).distance(g))[:2]
            for i in idx:
                w = cars[i]
                s = shapely.LineString(w.xy).project(g)
                for sgn in (+1, -1):
                    if w.oneway and sgn != w.oneway:
                        continue
                    ss = s - sgn * 3.0
                    if not (0 < ss < w.length):
                        continue
                    p, f = roadside(w, ss, sgn, 0.7)
                    mm = world.mesh(*p)
                    zg = world.ground(*p)
                    pole(mm, p[0], p[1], zg, 3.4, r=0.05)
                    sign_plate(mm, "obd_signal", "rect", (p[0] + f[0] * 0.12, p[1] + f[1] * 0.12, zg + 2.9), f, 0.32, 0.9)
                    mm.add_box("obd_sign_back", (p[0] + f[0] * 0.02, p[1] + f[1] * 0.02, zg + 2.9), (0.32, 0.2, 0.9),
                               axis=(-f[1], f[0]))
                    n_s += 1
        elif cls == "bench":
            idx = tree.query(g.buffer(15))
            t = np.array([1.0, 0.0])
            if len(idx):
                w = min((cars[i] for i in idx), key=lambda w: shapely.LineString(w.xy).distance(g))
                t = w.tangent(shapely.LineString(w.xy).project(g))
            _bench(world, np.array([x, y]), t)
            n_b += 1
        elif cls in ("bollard", "block"):
            zg = world.ground(x, y)
            world.mesh(x, y).add_cylinder("obd_delineator", (x, y, zg - 0.2), 1.1, 0.08, segs=8)
    return {"lamps": n_l, "signals": n_s, "benches": n_b}


def build_delineators(world, ways, builtup):
    """Austrian Leitpfloecke every 50 m outside built-up areas on main roads."""
    n = 0
    for w in ways:
        if w.kind != "road" or w.cls not in MAJOR:
            continue
        for s in np.arange(25.0, w.length - 5, 50.0):
            if w.in_ranges(s, w.bridge, 10) or is_urban(w, s, builtup):
                continue
            for sgn in (+1, -1):
                p, f = roadside(w, s, sgn, 0.9)
                zg = world.ground(*p)
                world.mesh(*p).add_box("obd_delineator", (p[0], p[1], zg + 0.45), (0.1, 0.12, 1.3), axis=f, uv_scale=1 / 1.3)
                n += 1
    return n


def _rail_strip(m, mat, pts, zs, h_bottom, h_top, offset):
    """Vertical strip along a polyline at lateral offset (right positive), double sided."""
    t = np.gradient(pts, axis=0)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-9)
    right = np.column_stack([t[:, 1], -t[:, 0]])
    q = pts + right * offset
    s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(q, axis=0).T))])
    for i in range(len(q) - 1):
        a, b = q[i], q[i + 1]
        za, zb = zs[i], zs[i + 1]
        uv = ((s[i] / 2, 0), (s[i + 1] / 2, 0), (s[i + 1] / 2, 1), (s[i] / 2, 1))
        m.add_quad(mat, (*a, za + h_bottom), (*b, zb + h_bottom), (*b, zb + h_top), (*a, za + h_top), uv, double=True)


def guardrail(world, pts, zs):
    """Steel W-beam guardrail along pts (ground heights zs), posts every 2 m."""
    if len(pts) < 2:
        return
    c = pts.mean(0)
    m = world.mesh(*c)
    _rail_strip(m, "obd_guardrail", pts, zs, 0.45, 0.78, 0.0)
    s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))])
    t = np.gradient(pts, axis=0)
    for d in np.arange(0, s[-1], 2.0):
        i = min(int(np.searchsorted(s, d)), len(pts) - 1)
        p = pts[i]
        m.add_box("obd_pole", (p[0], p[1], zs[i] + 0.3), (0.12, 0.06, 0.9), axis=t[i])


def build_guardrails(world, ways, nat):
    n = 0
    for w in ways:
        if w.kind != "road" or w.cls not in MAJOR | {"unclassified"} or w.width < 5:
            continue
        u = np.arange(0.0, w.length, 2.0)
        if len(u) < 3:
            continue
        need = {+1: np.zeros(len(u), bool), -1: np.zeros(len(u), bool)}
        for sgn in (+1, -1):
            for i, s in enumerate(u):
                t = w.tangent(s)
                right = np.array([t[1], -t[0]]) * sgn
                p = w.at(s) + right * (w.width / 2 + 3.0)
                drop = w.z_at(s) - float(sample_grid(nat, [p[0]], [p[1]])[0])
                near_bridge = any(a - 25 < s < b + 25 for a, b in w.bridge) and not w.in_ranges(s, w.bridge)
                need[sgn][i] = drop > 2.2 or near_bridge
        for sgn in (+1, -1):
            mk = need[sgn]
            # close small gaps, drop tiny runs
            idx = np.flatnonzero(mk)
            if not len(idx):
                continue
            runs = np.split(idx, np.flatnonzero(np.diff(idx) > 5) + 1)
            for run in runs:
                a, b = u[run[0]] - 6, u[run[-1]] + 6
                a, b = max(a, 0), min(b, w.length)
                if b - a < 16:
                    continue
                ss = np.arange(a, b, 2.0)
                pts, zs = [], []
                for s in ss:
                    t = w.tangent(s)
                    right = np.array([t[1], -t[0]]) * sgn
                    pts.append(w.at(s) + right * (w.width / 2 + 0.55))
                    zs.append(w.z_at(s))
                guardrail(world, np.array(pts), np.array(zs))
                n += 1
    return n


def build_barriers(world, infra):
    n = 0
    for r in infra:
        g = r["geom"]
        cls = r["class"]
        if g.geom_type not in ("LineString", "MultiLineString"):
            continue
        for line in getattr(g, "geoms", [g]):
            L = line.length
            if L < 1.0:
                continue
            ss = np.linspace(0, L, max(int(L / 2.0), 1) + 1)
            pts = np.array([line.interpolate(s).coords[0][:2] for s in ss])
            zs = sample_grid(world.h, pts[:, 0], pts[:, 1])
            c = pts.mean(0)
            m = world.mesh(*c)
            if cls == "fence":
                # Tyrolean wooden fence: posts + two rails
                _rail_strip(m, "obd_fence_wood", pts, zs, 0.5, 0.62, 0.0)
                _rail_strip(m, "obd_fence_wood", pts, zs, 0.95, 1.07, 0.0)
                t = np.gradient(pts, axis=0)
                for i in range(0, len(pts)):
                    m.add_box("obd_fence_wood", (pts[i][0], pts[i][1], zs[i] + 0.5), (0.1, 0.1, 1.2), axis=t[i])
            elif cls in ("wall", "city_wall", "retaining_wall", "jersey_barrier"):
                hgt = {"wall": 1.2, "city_wall": 2.5, "retaining_wall": 1.6, "jersey_barrier": 0.8}[cls]
                mat = "obd_stone_wall" if cls in ("wall", "city_wall") else "bld_concrete"
                _wall(m, mat, pts, zs, hgt, 0.35)
            elif cls == "hedge":
                _wall(m, "obd_hedge", pts, zs, 1.5, 0.8)
            elif cls == "guard_rail":
                guardrail(world, pts, zs)
            else:
                continue
            n += 1
    return n


def _wall(m, mat, pts, zs, hgt, thick):
    t = np.gradient(pts, axis=0)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-9)
    right = np.column_stack([t[:, 1], -t[:, 0]])
    L = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))])
    for side in (1, -1):
        q = pts + right * side * thick / 2
        for i in range(len(q) - 1):
            a, b = q[i], q[i + 1]
            za, zb = zs[i], zs[i + 1]
            uv = ((L[i] / 2, -0.15), (L[i + 1] / 2, -0.15), (L[i + 1] / 2, hgt / 2), (L[i] / 2, hgt / 2))
            if side == 1:
                m.add_quad(mat, (*a, za - 0.3), (*b, zb - 0.3), (*b, zb + hgt), (*a, za + hgt), uv)
            else:
                m.add_quad(mat, (*b, zb - 0.3), (*a, za - 0.3), (*a, za + hgt), (*b, zb + hgt), uv)
    ql = pts - right * thick / 2
    qr = pts + right * thick / 2
    for i in range(len(pts) - 1):
        m.add_quad(mat, (*ql[i], zs[i] + hgt), (*qr[i], zs[i] + hgt), (*qr[i + 1], zs[i + 1] + hgt),
                   (*ql[i + 1], zs[i + 1] + hgt), ((0, 0), (thick, 0), (thick, 1), (0, 1)))
    for i, sgn in ((0, 1), (len(pts) - 1, -1)):
        a, b = ql[i], qr[i]
        if sgn == 1:
            m.add_quad(mat, (*a, zs[i] - 0.3), (*b, zs[i] - 0.3), (*b, zs[i] + hgt), (*a, zs[i] + hgt))
        else:
            m.add_quad(mat, (*b, zs[i] - 0.3), (*a, zs[i] - 0.3), (*a, zs[i] + hgt), (*b, zs[i] + hgt))


# ------------------------------------------------------------------------------------------- railway

def build_railway(world, ways, infra):
    n = 0
    for w in ways:
        if w.kind != "rail":
            continue
        ss = np.arange(0.0, w.length, 2.0)
        if len(ss) < 2:
            continue
        ss = np.append(ss, w.length)
        pts = np.array([w.at(s) for s in ss])
        zs = np.array([w.z_at(s) for s in ss]) + 0.05
        t = np.gradient(pts, axis=0)
        t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-9)
        right = np.column_stack([t[:, 1], -t[:, 0]])
        # chunk the track into pieces of ~100 m so it lands in the right tiles
        for k0 in range(0, len(pts) - 1, 50):
            k1 = min(k0 + 51, len(pts))
            P, Z, R = pts[k0:k1], zs[k0:k1], right[k0:k1]
            m = world.mesh(*P.mean(0))
            # track bed with sleepers (texture), ballast shoulders down to the ground
            for i in range(len(P) - 1):
                v0, v1 = ss[k0 + i] / 2.4, ss[k0 + i + 1] / 2.4
                a0, a1 = P[i] - R[i] * 1.6, P[i + 1] - R[i + 1] * 1.6
                b0, b1 = P[i] + R[i] * 1.6, P[i + 1] + R[i + 1] * 1.6
                m.add_quad("obd_track", (*a0, Z[i] + 0.25), (*b0, Z[i] + 0.25), (*b1, Z[i + 1] + 0.25), (*a1, Z[i + 1] + 0.25),
                           ((0, v0), (1, v0), (1, v1), (0, v1)))
                on_bridge = w.in_ranges(ss[k0 + i], w.bridge, 2)
                if not on_bridge:
                    for sgn in (-1, 1):
                        e0, e1 = P[i] + R[i] * sgn * 1.6, P[i + 1] + R[i + 1] * sgn * 1.6
                        f0, f1 = P[i] + R[i] * sgn * 2.4, P[i + 1] + R[i + 1] * sgn * 2.4
                        quad = [(*e0, Z[i] + 0.25), (*f0, Z[i] - 0.25), (*f1, Z[i + 1] - 0.25), (*e1, Z[i + 1] + 0.25)]
                        if sgn < 0:
                            quad = [quad[1], quad[0], quad[3], quad[2]]
                        m.add_quad("obd_ballast", *quad, ((0, v0), (0.4, v0), (0.4, v1), (0, v1)))
            # rails (UIC 60 approximated): top + two sides
            for g in (-0.7175, 0.7175):
                for i in range(len(P) - 1):
                    c0, c1 = P[i] + R[i] * g, P[i + 1] + R[i + 1] * g
                    for off, (h0, h1) in ((-0.035, (0.25, 0.42)), (0.035, (0.25, 0.42))):
                        a, b = c0 + R[i] * off, c1 + R[i + 1] * off
                        if off < 0:
                            m.add_quad("obd_rail", (*b, Z[i + 1] + h0), (*a, Z[i] + h0), (*a, Z[i] + h1), (*b, Z[i + 1] + h1))
                        else:
                            m.add_quad("obd_rail", (*a, Z[i] + h0), (*b, Z[i + 1] + h0), (*b, Z[i + 1] + h1), (*a, Z[i] + h1))
                    a, b = c0 - R[i] * 0.035, c1 - R[i + 1] * 0.035
                    a2, b2 = c0 + R[i] * 0.035, c1 + R[i + 1] * 0.035
                    m.add_quad("obd_rail_top", (*a, Z[i] + 0.42), (*a2, Z[i] + 0.42), (*b2, Z[i + 1] + 0.42), (*b, Z[i + 1] + 0.42))
        # Overhead line (main line only)
        if not w.name.startswith("AB") and w.length > 150:
            masts = np.arange(10.0, w.length, 55.0)
            prev = None
            for s in masts:
                p = w.at(s)
                tt = w.tangent(s)
                rr = np.array([tt[1], -tt[0]])
                mp = p + rr * 3.3
                zg = w.z_at(s)
                m = world.mesh(*mp)
                m.add_box("obd_steel", (mp[0], mp[1], zg + 3.6), (0.26, 0.26, 7.6), axis=tt)
                arm = p + rr * 1.6
                m.add_box("obd_steel", (arm[0], arm[1], zg + 6.9), (0.08, 3.5, 0.08), axis=tt)
                wire = (p[0], p[1], zg + 6.05)
                if prev is not None:
                    a, b = np.array(prev), np.array(wire)
                    d = b[:2] - a[:2]
                    L = np.hypot(*d)
                    mid = (a + b) / 2
                    if L < 70:
                        mm = world.mesh(mid[0], mid[1])
                        mm.add_box("obd_wire", tuple(mid), (L, 0.025, 0.025), axis=d)
                        mm.add_box("obd_wire", (mid[0], mid[1], mid[2] + 1.1), (L, 0.02, 0.02), axis=d)
                prev = wire
        n += 1
    # Platforms
    for r in infra:
        g = r["geom"]
        st = dict(r.get("source_tags") or [])
        if r["class"] != "platform" or g.geom_type not in ("Polygon",) or st.get("railway") != "platform":
            continue
        rail_z = None
        for w in ways:
            if w.kind == "rail" and shapely.LineString(w.xy).distance(g) < 6:
                rail_z = w.z_at(shapely.LineString(w.xy).project(g.centroid))
                break
        if rail_z is None:
            continue
        top = rail_z + 0.25 + 0.42 + 0.38
        from .buildings import _triangulate_planar, _orient_ccw
        poly = _orient_ccw(g.simplify(0.1))
        m = world.mesh(poly.centroid.x, poly.centroid.y)
        for tri in _triangulate_planar(poly):
            V = np.column_stack([tri, np.full(3, top)])
            m.add("obd_platform", V, np.tile([0, 0, 1], (3, 1)), tri / 2.0, [[0, 1, 2]])
        ring = np.asarray(poly.exterior.coords)
        for i in range(len(ring) - 1):
            a, b = ring[i], ring[i + 1]
            zb = min(world.ground(*a), world.ground(*b)) - 0.3
            m.add_quad("bld_concrete", (*a, zb), (*b, zb), (*b, top), (*a, top))
    return n


# ------------------------------------------------------------------------------------------- bridges

def build_bridges(world, ways):
    n = 0
    for w in ways:
        for a, b in w.bridge:
            if b - a < 2.0:
                continue
            if w.kind == "rail":
                W, top_mat, kerb = 5.2, "obd_ballast", 0.0
            elif w.cls in ("footway", "path", "cycleway", "bridleway", "steps", "pedestrian"):
                W, top_mat, kerb = w.width + 0.6, "obd_fence_wood", 0.0
            else:
                W = w.width + 1.2
                top_mat = "obd_deck_major" if (w.cls in MAJOR and w.width >= 5.5) else "obd_deck_minor"
                kerb = 0.5
            ss = np.arange(a - 0.5, b + 0.5, 2.0)
            ss = np.clip(np.append(ss, b + 0.5), 0, w.length)
            P = np.array([w.at(s) for s in ss])
            Z = np.array([w.z_at(s) for s in ss])
            if w.kind == "rail":
                Z = Z + 0.24
            T = np.gradient(P, axis=0)
            T /= np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-9)
            R = np.column_stack([T[:, 1], -T[:, 0]])
            L = R * (-W / 2)
            Rr = R * (W / 2)
            m = world.mesh(*P.mean(0))
            depth = 0.9 if w.kind == "road" else 1.2
            for i in range(len(P) - 1):
                v0, v1 = (ss[i] - a) / 8.0, (ss[i + 1] - a) / 8.0
                l0, l1 = P[i] + L[i], P[i + 1] + L[i + 1]
                r0, r1 = P[i] + Rr[i], P[i + 1] + Rr[i + 1]
                m.add_quad(top_mat, (*l0, Z[i]), (*r0, Z[i]), (*r1, Z[i + 1]), (*l1, Z[i + 1]),
                           ((0, v0), (1, v0), (1, v1), (0, v1)))
                m.add_quad("bld_concrete", (*r0, Z[i] - depth), (*l0, Z[i] - depth), (*l1, Z[i + 1] - depth), (*r1, Z[i + 1] - depth))
                m.add_quad("bld_concrete", (*r0, Z[i] - depth), (*r1, Z[i + 1] - depth), (*r1, Z[i + 1]), (*r0, Z[i]),
                           ((v0 * 4, 0), (v1 * 4, 0), (v1 * 4, depth / 2), (v0 * 4, depth / 2)))
                m.add_quad("bld_concrete", (*l1, Z[i + 1] - depth), (*l0, Z[i] - depth), (*l0, Z[i]), (*l1, Z[i + 1]),
                           ((v1 * 4, 0), (v0 * 4, 0), (v0 * 4, depth / 2), (v1 * 4, depth / 2)))
            # railings
            for side in (-1, 1):
                q = P + R * side * (W / 2 - 0.08)
                rail_mat = "obd_fence_wood" if top_mat == "obd_fence_wood" else "obd_guardrail"
                _rail_strip(m, rail_mat, q, Z, 0.9, 1.05, 0.0)
                _rail_strip(m, rail_mat, q, Z, 0.45, 0.55, 0.0)
                for i in range(0, len(q), 1):
                    m.add_box("obd_pole" if rail_mat != "obd_fence_wood" else "obd_fence_wood",
                              (q[i][0], q[i][1], Z[i] + 0.52), (0.07, 0.07, 1.05), axis=T[i])
            # piers for long spans
            span = b - a
            if span > 22:
                k = int(span // 20)
                for j in range(1, k + 1):
                    s = a + span * j / (k + 1)
                    p = w.at(s)
                    zt = w.z_at(s) - depth
                    zg = world.ground(*p) - 1.0
                    if zt - zg > 0.5:
                        m.add_box("bld_concrete", (p[0], p[1], (zt + zg) / 2), (1.2, W - 1.0, zt - zg), axis=w.tangent(s))
            # abutments
            for s in (a, b):
                p = w.at(s)
                zt = w.z_at(s) - depth * 0.5
                zg = world.ground(*p) - 1.5
                if zt - zg > 0.3:
                    m.add_box("bld_concrete", (p[0], p[1], (zt + zg) / 2), (1.0, W + 0.4, zt - zg), axis=w.tangent(s))
            n += 1
    return n
