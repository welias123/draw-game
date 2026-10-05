"""Road surface decals (DecalRoad objects) with Austrian road markings, plus junction analysis
shared with the sign placement."""
import numpy as np
import shapely

from .roads import CAR_CLASSES, MAJOR

DRAWN = CAR_CLASSES | {"pedestrian", "cycleway", "footway", "path", "bridleway"}
DRIVABILITY = {"primary": 1.0, "secondary": 1.0, "tertiary": 0.9, "unclassified": 0.8, "residential": 0.7,
               "living_street": 0.5, "service": 0.3, "unknown": 0.3, "track": 0.15}


def _uid(*parts):
    import uuid
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "oberndorf/" + "/".join(map(str, parts))))


class Builder:
    def __init__(self):
        self.objects = []

    def decal(self, group, name, material, nodes, prio, tex_len, **extra):
        nodes = [[round(float(x), 3), round(float(y), 3), round(float(z), 3), round(float(w), 3)] for x, y, z, w in nodes]
        if len(nodes) < 2:
            return
        o = {"class": "DecalRoad", "persistentId": _uid(group, name, len(self.objects)), "__parent": group,
             "position": nodes[0][:3], "material": material, "nodes": nodes, "renderPriority": int(prio),
             "textureLength": tex_len, "improvedSpline": True, "breakAngle": 3}
        if name:
            o["name"] = name
        o.update(extra)
        self.objects.append(o)


# ----------------------------------------------------------------------------------------- analysis

def car(w):
    return w.kind == "road" and w.cls in CAR_CLASSES and w.sub not in ("driveway",)


def is_urban(w, s, builtup):
    v = w.speed_at(s)
    if v is not None:
        return v <= 50
    p = w.at(s)
    return bool(builtup is not None and shapely.contains_xy(builtup, p[0], p[1]))


def junction_info(ways, junctions):
    """For every way: list of (s, cid, others[(way, s_other)])."""
    info = {id(w): [] for w in ways}
    for cid, lst in junctions.items():
        for w, s in lst:
            others = [(o, so) for o, so in lst if o is not w]
            info[id(w)].append((s, cid, others))
    for k in info:
        info[k].sort(key=lambda t: t[0])
    return info


def _dir_out(o, so):
    """Unit direction in which way o leaves the junction located at its arc length so."""
    dirs = []
    if so < o.length - 1.0:
        dirs.append(o.tangent(min(so + 4.0, o.length)) if so + 4 < o.length else o.tangent(so))
    if so > 1.0:
        dirs.append(-o.tangent(max(so - 4.0, 0.0)))
    return dirs


def approaches(ways, junctions):
    """Minor road arms ending at a more important road: where give-way/stop lines and signs belong.
    Returns dicts with way, s (arc length of the junction on that way), direction sign (+1: the arm
    approaches the junction with increasing s), major way, junction point."""
    out = []
    for cid, lst in junctions.items():
        cars = [(w, s) for w, s in lst if car(w) or w.kind == "rail"]
        if len(cars) < 2:
            continue
        top = max(w.rank for w, _ in cars if w.kind == "road") if any(w.kind == "road" for w, _ in cars) else 0
        majors = [(w, s) for w, s in cars if w.kind == "road" and w.rank == top]
        # Two continuing pieces of the same named road count as the through road.
        names = {w.name for w, _ in majors if w.name}
        for w, s in cars:
            if w.kind != "road" or w.rank >= top or w.rank < 3:
                continue
            if w.name and w.name in names:
                continue
            mj = majors[0][0]
            p = w.at(s)
            for sign, cond in ((+1, s > 6.0), (-1, s < w.length - 6.0)):
                if not cond:
                    continue
                if w.oneway == 1 and sign == -1 or w.oneway == -1 and sign == +1:
                    continue  # traffic leaves the junction on this arm
                out.append({"way": w, "s": s, "sign": sign, "major": mj, "major_s": majors[0][1], "point": p, "cid": cid,
                            "top_rank": top})
    return out


# ----------------------------------------------------------------------------------------- geometry

def _poly_runs(w, ranges_excluded):
    from .terrain import _runs
    return _runs(w, ranges_excluded)


def _nodes(w, a, b, width, offset=0.0, step_max=25.0, tol=0.12):
    """Simplified node list of the way between arc lengths a..b, optionally laterally offset."""
    m = (w.s > a) & (w.s < b)
    s = np.concatenate([[a], w.s[m], [b]])
    xy = np.vstack([w.at(a), w.xy[m], w.at(b)])
    z = np.concatenate([[w.z_at(a)], w.z[m], [w.z_at(b)]])
    if len(s) < 2 or b - a < 0.3:
        return []
    if offset:
        t = np.gradient(xy, axis=0)
        n = np.column_stack([t[:, 1], -t[:, 0]])  # right-hand normal
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        xy = xy + n * offset
    line = shapely.LineString(xy)
    simp = line.simplify(tol)
    pts = np.asarray(simp.coords)
    # Re-densify long straight pieces so the spline does not wander.
    out = [pts[0]]
    for p in pts[1:]:
        prev = out[-1]
        L = np.hypot(*(p - prev))
        k = max(int(np.ceil(L / step_max)), 1)
        for j in range(1, k + 1):
            out.append(prev + (p - prev) * (j / k))
    out = np.asarray(out)
    # heights: project back to the centreline arc length
    cl = shapely.LineString(w.xy)
    ss = np.array([cl.project(shapely.Point(q)) for q in out])
    ss = np.clip(ss, a, b)
    zz = np.interp(ss, w.s, w.z)
    return [(q[0], q[1], zq + 0.02, width) for q, zq in zip(out, zz)]


def _segments_mask(length, step=1.0):
    return np.arange(0.0, length + step * 0.5, step)


def _runs_of(mask_vals, u):
    """Group consecutive equal values: returns (value, u0, u1)."""
    out = []
    start = 0
    for i in range(1, len(mask_vals) + 1):
        if i == len(mask_vals) or mask_vals[i] != mask_vals[start]:
            out.append((mask_vals[start], u[start], u[min(i, len(u) - 1)]))
            start = i
    return out


def curvature_radius(w, u):
    """Approximate horizontal radius (m) along the way, sampled at arc lengths u."""
    h = 10.0
    a = np.array([w.at(max(x - h, 0)) for x in u])
    b = np.array([w.at(x) for x in u])
    c = np.array([w.at(min(x + h, w.length)) for x in u])
    ab = np.linalg.norm(b - a, axis=1)
    bc = np.linalg.norm(c - b, axis=1)
    ca = np.linalg.norm(a - c, axis=1)
    cross = np.abs((b - a)[:, 0] * (c - a)[:, 1] - (b - a)[:, 1] * (c - a)[:, 0])
    R = ab * bc * ca / np.maximum(2 * cross, 1e-9)
    return R


# ----------------------------------------------------------------------------------------- decals

def build_decals(ways, junctions, infra, builtup):
    B = Builder()
    jinfo = junction_info(ways, junctions)
    # ---------------- base surfaces, split at junctions (better AI graph)
    for w in ways:
        if w.kind != "road" or w.cls not in DRAWN:
            continue
        cuts = sorted({0.0, w.length} | {s for s, cid, others in jinfo[id(w)]
                                          if any(car(o) for o, _ in others) and 0.5 < s < w.length - 0.5})
        if w.surface == "asphalt":
            mat = "obd_asphalt" if w.cls in MAJOR or w.link else "obd_asphalt_minor"
            tl = 8.0
        elif w.surface == "paving":
            mat, tl = "obd_paving", 6.0
        elif w.surface == "gravel" and w.cls not in ("path", "footway", "bridleway"):
            mat, tl = "obd_gravel", 6.0
        else:
            mat, tl = "obd_dirt", 6.0
        width = w.width + (0.3 if w.surface == "asphalt" else 0.6)
        prio = 19 - w.rank
        for a, b in _poly_runs(w, w.bridge):
            pcs = [c for c in cuts if a < c < b]
            bounds = [a] + pcs + [b]
            for i in range(len(bounds) - 1):
                nodes = _nodes(w, bounds[i], bounds[i + 1], width)
                if w.oneway == -1:
                    nodes = nodes[::-1]
                extra = {}
                if w.cls in DRIVABILITY:
                    extra["drivability"] = DRIVABILITY[w.cls]
                    extra["oneWay"] = bool(w.oneway)
                    extra["lanesLeft"] = 0 if w.oneway else 1
                    extra["lanesRight"] = 1
                else:
                    extra["drivability"] = -1
                B.decal("roads_surface", None, mat, nodes, prio, tl, **extra)
        # Bridges have their own deck mesh; an invisible decal keeps them in the AI road graph.
        if w.cls in DRIVABILITY:
            for a, b in w.bridge:
                nodes = _nodes(w, max(a - 1.0, 0.0), min(b + 1.0, w.length), w.width)
                if w.oneway == -1:
                    nodes = nodes[::-1]
                B.decal("roads_surface", None, "obd_invisible", nodes, 30, 8.0, drivability=DRIVABILITY[w.cls],
                        oneWay=bool(w.oneway), lanesLeft=0 if w.oneway else 1, lanesRight=1)
    # ---------------- markings
    for w in ways:
        if w.kind != "road" or not car(w):
            continue
        major = w.cls in MAJOR and not w.link
        edge = (w.cls in ("primary", "secondary") or w.link) and w.width >= 4.0
        center = major and not w.oneway and w.width >= 5.5
        if not (edge or center):
            continue
        u = _segments_mask(w.length)
        urban = np.array([is_urban(w, x, builtup) for x in u])
        solid = np.zeros(len(u), bool)
        no_center = np.zeros(len(u), bool)
        gap_left = np.zeros(len(u), bool)
        gap_right = np.zeros(len(u), bool)
        for s, cid, others in jinfo[id(w)]:
            side_roads = [(o, so) for o, so in others if (car(o) and o.rank >= 3) or o.kind == "rail"]
            if not side_roads:
                continue
            hw_other = max(o.width for o, _ in side_roads) / 2
            tang = w.tangent(s)
            right = np.array([tang[1], -tang[0]])
            through = [o for o, _ in side_roads if o.name and o.name == w.name and o.rank == w.rank]
            for o, so in side_roads:
                if o in through:
                    continue
                if o.kind == "rail":
                    near = np.abs(u - s) < 30
                    solid |= near
                    continue
                L_sol = 25.0 if urban[min(int(s), len(u) - 1)] else 40.0
                if o.rank >= 4:
                    solid |= np.abs(u - s) < L_sol
                if o.rank > w.rank or (o.rank == w.rank and not through):
                    no_center |= np.abs(u - s) < hw_other + 1.0
                for d in _dir_out(o, so):
                    side = float(np.dot(d, right))
                    gap = np.abs(u - s) < (o.width / 2 + 4.5)
                    if side > 0.2:
                        gap_right |= gap
                    elif side < -0.2:
                        gap_left |= gap
            # junction at the end of this way with a higher road: stop markings before it
        # end trimming where the way ends at a junction with another road
        for s, cid, others in jinfo[id(w)]:
            oth = [o for o, _ in others if car(o) and not (o.name and o.name == w.name)]
            if not oth:
                continue
            hw_o = max(o.width for o in oth) / 2 + 1.5
            if s < 1.0:
                no_center |= u < hw_o
                gap_left |= u < hw_o
                gap_right |= u < hw_o
            elif s > w.length - 1.0:
                no_center |= u > w.length - hw_o
                gap_left |= u > w.length - hw_o
                gap_right |= u > w.length - hw_o
        R = curvature_radius(w, u)
        solid |= (R < 90) & ~urban
        for a, b in w.bridge:
            no_center |= (u > a - 0.5) & (u < b + 0.5)
            gap_left |= (u > a - 0.5) & (u < b + 0.5)
            gap_right |= (u > a - 0.5) & (u < b + 0.5)
        lw = 0.12
        if center:
            state = np.where(no_center, 0, np.where(solid, 1, np.where(urban, 2, 3)))
            for val, u0, u1 in _runs_of(state.tolist(), u):
                if val == 0 or u1 - u0 < 2.0:
                    continue
                nodes = _nodes(w, u0, min(u1, w.length), lw)
                if val == 1:
                    B.decal("roads_markings", None, "obd_line", nodes, 7, 4.0)
                else:
                    B.decal("roads_markings", None, "obd_line_dash", nodes, 7, 9.0 if val == 2 else 18.0)
        if edge:
            off = w.width / 2 - 0.3
            for gap, sgn in ((gap_right, 1.0), (gap_left, -1.0)):
                for val, u0, u1 in _runs_of(gap.tolist(), u):
                    if val or u1 - u0 < 3.0:
                        continue
                    nodes = _nodes(w, u0, min(u1, w.length), 0.15, offset=sgn * off)
                    B.decal("roads_markings", None, "obd_line", nodes, 7, 4.0)
    # ---------------- give-way / stop lines
    stops = [r["geom"] for r in infra if r["class"] == "stop" and r["geom"].geom_type == "Point"]
    gws = [r["geom"] for r in infra if r["class"] == "give_way" and r["geom"].geom_type == "Point"]
    stop_tree = shapely.STRtree(stops) if stops else None
    gw_tree = shapely.STRtree(gws) if gws else None
    control = []
    for ap in approaches(ways, junctions):
        w, s, sign = ap["way"], ap["s"], ap["sign"]
        mj = ap["major"]
        dist = mj.width / 2 + 1.2
        s_line = s - sign * dist
        if not (0 <= s_line <= w.length):
            continue
        p = w.at(s_line)
        kind = None
        if stop_tree is not None and len(stop_tree.query(shapely.Point(p).buffer(25))):
            kind = "stop"
        elif gw_tree is not None and len(gw_tree.query(shapely.Point(p).buffer(25))):
            kind = "give_way"
        elif mj.cls in MAJOR and w.rank >= 3:
            kind = "give_way"   # Austrian practice: side roads give way to Landes-/Bundesstrassen
        if kind is None:
            continue
        tang = w.tangent(s_line) * sign
        right = np.array([tang[1], -tang[0]])
        hw = w.width / 2
        z = w.z_at(s_line) + 0.02
        if w.oneway or w.width < 5.0:
            a, b = p - right * (hw - 0.2), p + right * (hw - 0.2)
        else:
            a, b = p + right * 0.1, p + right * (hw - 0.2)
        if kind == "stop":
            B.decal("roads_markings", None, "obd_line", [(*a, z, 0.5), (*b, z, 0.5)], 6, 4.0)
        elif mj.cls in MAJOR:
            B.decal("roads_markings", None, "obd_line_dash_half", [(*a, z, 0.3), (*b, z, 0.3)], 6, 1.0)
        control.append({**ap, "kind": kind, "line_point": p, "dir": tang, "right": right, "z": z})
    # ---------------- zebra crossings (Schutzwege)
    zebras = []
    cars = [w for w in ways if car(w)]
    tree = shapely.STRtree([shapely.LineString(w.xy) for w in cars])
    for r in infra:
        if r["class"] != "crossing" or r["geom"].geom_type != "Point":
            continue
        st = dict(r.get("source_tags") or [])
        if st.get("crossing") in ("unmarked", "no", "informal") or st.get("crossing:markings") == "no":
            continue
        pt = r["geom"]
        idx = tree.query(pt.buffer(3.0))
        if not len(idx):
            continue
        w = min((cars[i] for i in idx), key=lambda w: shapely.LineString(w.xy).distance(pt))
        if w.rank < 3:
            continue
        s = shapely.LineString(w.xy).project(pt)
        p = w.at(s)
        tang = w.tangent(s)
        right = np.array([tang[1], -tang[0]])
        hw = w.width / 2 - 0.1
        z = w.z_at(s) + 0.02
        a, b = p - right * hw, p + right * hw
        B.decal("roads_markings", None, "obd_zebra", [(*a, z, 3.5), (*b, z, 3.5)], 5, 1.0)
        zebras.append({"way": w, "s": s, "point": p, "dir": tang, "right": right, "z": z,
                       "signals": st.get("crossing") == "traffic_signals"})
    # ---------------- bus stops: yellow zig-zag along the kerb
    busstops = []
    for r in infra:
        if r["class"] != "bus_stop" or r["geom"].geom_type != "Point":
            continue
        pt = r["geom"]
        idx = tree.query(pt.buffer(15.0))
        if not len(idx):
            continue
        w = min((cars[i] for i in idx), key=lambda w: shapely.LineString(w.xy).distance(pt))
        cl = shapely.LineString(w.xy)
        s = cl.project(pt)
        p = w.at(s)
        tang = w.tangent(s)
        right = np.array([tang[1], -tang[0]])
        side = 1.0 if np.dot(np.asarray(pt.coords[0]) - p, right) >= 0 else -1.0
        name = (r.get("names") or {}).get("primary") or ""
        busstops.append({"way": w, "s": s, "side": side, "point": np.asarray(pt.coords[0]), "name": name})
        if w.rank < 4 or w.in_ranges(s, w.bridge, 15):
            continue
        a0, a1 = max(s - 10, 0), min(s + 10, w.length)
        nodes = _nodes(w, a0, a1, 0.9, offset=side * (w.width / 2 - 0.55))
        B.decal("roads_markings", None, "obd_zigzag_yellow", nodes, 6, 4.0)
    return B.objects, control, zebras, busstops
