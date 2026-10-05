"""Road and rail network: geometry, widths, surfaces, elevation profiles and junctions."""
from dataclasses import dataclass, field

import numpy as np
import shapely
from scipy import ndimage

from . import config as C
from .geo import load_layer, name_of

# Carriageway widths (m) roughly following Austrian RVS cross sections.
WIDTH = {
    "primary": 7.0, "secondary": 6.5, "tertiary": 6.0, "unclassified": 5.0, "residential": 5.0,
    "living_street": 4.5, "service": 3.5, "track": 3.0, "pedestrian": 4.0, "unknown": 3.5,
    "cycleway": 2.5, "footway": 1.8, "path": 1.6, "bridleway": 2.0,
}
SUB_WIDTH = {"driveway": 3.0, "parking_aisle": 5.0, "alley": 3.5, "sidewalk": 1.8, "crosswalk": 3.0, "link": 4.5}
SHOULDER = {
    "primary": 1.2, "secondary": 1.0, "tertiary": 0.8, "unclassified": 0.6, "residential": 0.5,
    "living_street": 0.4, "service": 0.4, "track": 0.4, "pedestrian": 0.3, "unknown": 0.4,
    "cycleway": 0.3, "footway": 0.2, "path": 0.2, "rail": 1.2,
}
RANK = {
    "primary": 9, "secondary": 8, "tertiary": 7, "unclassified": 6, "residential": 5, "living_street": 4,
    "service": 3, "unknown": 3, "pedestrian": 2, "track": 2, "cycleway": 1, "footway": 1, "path": 1,
    "bridleway": 1, "rail": 6,
}
SIGMA = {  # along-road elevation smoothing (m)
    "primary": 16, "secondary": 13, "tertiary": 11, "unclassified": 8, "residential": 8,
    "living_street": 6, "service": 5, "unknown": 5, "pedestrian": 5, "track": 6,
    "cycleway": 5, "footway": 3, "path": 3, "bridleway": 3, "rail": 30,
}
CAR_CLASSES = {"primary", "secondary", "tertiary", "unclassified", "residential", "living_street",
               "service", "unknown", "track"}
MAJOR = {"primary", "secondary", "tertiary"}
SKIP = {"steps"}


@dataclass
class Way:
    id: str
    kind: str          # "road" | "rail"
    cls: str
    sub: str
    name: str
    ref: str
    xy: np.ndarray     # dense polyline (N, 2)
    s: np.ndarray      # arc length (N,)
    width: float
    shoulder: float
    surface: str       # asphalt | gravel | paving | dirt
    oneway: int        # 0 two-way, 1 forward only, -1 backward only
    bridge: list
    tunnel: list
    speed: list        # (s0, s1, kmh)
    conns: dict        # connector id -> arc length
    rank: int
    link: bool = False
    z: np.ndarray = None
    destinations: list = field(default_factory=list)

    @property
    def length(self):
        return float(self.s[-1])

    def at(self, s):
        return np.array([np.interp(s, self.s, self.xy[:, 0]), np.interp(s, self.s, self.xy[:, 1])])

    def z_at(self, s):
        return float(np.interp(s, self.s, self.z))

    def tangent(self, s):
        d = 1.0
        a = self.at(max(s - d, 0.0))
        b = self.at(min(s + d, self.length))
        t = b - a
        n = np.hypot(*t)
        return t / n if n > 1e-9 else np.array([1.0, 0.0])

    def speed_at(self, s):
        for s0, s1, v in self.speed:
            if s0 - 1e-6 <= s <= s1 + 1e-6:
                return v
        return None

    def in_ranges(self, s, ranges, pad=0.0):
        return any(a - pad <= s <= b + pad for a, b in ranges)


def _ranges(rules, length, key="values", match=None):
    out = []
    for r in rules or []:
        vals = r.get(key)
        if match is not None:
            if isinstance(vals, list):
                if match not in vals:
                    continue
            elif vals != match:
                continue
        b = r.get("between")
        a0, a1 = (0.0, 1.0) if not b else (b[0], b[1])
        out.append((a0 * length, a1 * length))
    return out


def _densify(coords, extra_s, step=2.0):
    p = np.asarray(coords, np.float64)[:, :2]
    seg = np.hypot(*np.diff(p, axis=0).T)
    keep = np.concatenate([[True], seg > 1e-6])
    p = p[keep]
    seg = np.hypot(*np.diff(p, axis=0).T)
    S = np.concatenate([[0.0], np.cumsum(seg)])
    samples = [S]
    for i, L in enumerate(seg):
        n = int(np.ceil(L / step))
        if n > 1:
            samples.append(S[i] + np.arange(1, n) * L / n)
    samples.append(np.clip(np.asarray(extra_s, np.float64), 0, S[-1]))
    s = np.unique(np.round(np.concatenate(samples), 4))
    xy = np.column_stack([np.interp(s, S, p[:, 0]), np.interp(s, S, p[:, 1])])
    return xy, s


def _surface(r, cls):
    vals = [x["value"] for x in (r.get("road_surface") or [])]
    v = vals[0] if vals else None
    if v in ("gravel", "unpaved", "fine_gravel", "compacted", "pebblestone"):
        return "gravel"
    if v in ("dirt", "ground", "grass", "earth", "mud"):
        return "dirt"
    if v in ("paving_stones", "sett", "cobblestone", "concrete:plates"):
        return "paving"
    if v in ("paved", "asphalt", "concrete"):
        return "asphalt"
    if cls == "track":
        return "gravel"
    if cls in ("path", "bridleway"):
        return "gravel"
    return "asphalt"


def _oneway(r):
    for a in r.get("access_restrictions") or []:
        w = a.get("when") or {}
        if a.get("access_type") == "denied" and w.get("heading") and not w.get("mode") and not w.get("vehicle") \
                and not w.get("using") and not w.get("recognized") and not w.get("during"):
            return 1 if w["heading"] == "backward" else -1
    return 0


def load_network():
    conn_xy = {r["id"]: np.array(r["geom"].coords[0][:2]) for r in load_layer("connector", pad=200)}
    ways = []
    for r in load_layer("segment", pad=50):
        cls = r["class"] or "unknown"
        kind = r["subtype"]
        if kind not in ("road", "rail") or cls in SKIP:
            continue
        if kind == "rail":
            flags = [v for f in (r.get("rail_flags") or []) for v in f["values"]]
            if "is_abandoned" in flags or "is_disused" in flags:
                continue
        g = r["geom"]
        if g.geom_type != "LineString" or g.length < 1.0:
            continue
        L = g.length
        flags_src = r.get("road_flags") if kind == "road" else r.get("rail_flags")
        bridge = _ranges(flags_src, L, match="is_bridge")
        tunnel = _ranges(flags_src, L, match="is_tunnel")
        link = bool(_ranges(flags_src, L, match="is_link"))
        sub = r.get("subclass") or ""
        conns = {}
        for c in r.get("connectors") or []:
            cid = c["connector_id"]
            if cid in conn_xy:
                conns[cid] = float(g.project(shapely.Point(conn_xy[cid])))
            else:
                conns[cid] = float(c["at"]) * L
        speed = []
        for sl in r.get("speed_limits") or []:
            ms = sl.get("max_speed")
            if not ms or sl.get("when"):
                continue
            b = sl.get("between") or [0.0, 1.0]
            speed.append((b[0] * L, b[1] * L, int(ms["value"])))
        extra = list(conns.values()) + [x for ab in bridge + tunnel for x in ab] + [x for a, b_, _ in speed for x in (a, b_)]
        xy, s = _densify(g.coords, extra)
        if kind == "rail":
            cls_k = "rail"
            width, shoulder, surface = 1.435, SHOULDER["rail"], "gravel"
        else:
            cls_k = cls
            wr = [w["value"] for w in (r.get("width_rules") or []) if w.get("value")]
            width = SUB_WIDTH.get(sub, WIDTH.get(cls, 3.5))
            if link:
                width = SUB_WIDTH["link"]
            if wr and 1.0 <= wr[0] <= 12.0:
                width = float(wr[0])
            shoulder = SHOULDER.get(cls, 0.3)
            surface = _surface(r, cls)
        routes = r.get("routes") or []
        ref = next((x["ref"] for x in routes if x.get("ref") and not str(x["ref"]).startswith("E")), "") or ""
        dests = []
        for d in r.get("destinations") or []:
            labels = [l["value"] for l in d.get("labels") or []]
            if labels:
                dests.append({"labels": labels, "from": d.get("from_connector_id"), "when": d.get("when")})
        ways.append(Way(
            id=r["id"], kind=kind, cls=cls_k, sub=sub, name=name_of(r) or "", ref=ref,
            xy=xy, s=s, width=width, shoulder=shoulder, surface=surface,
            oneway=_oneway(r) if kind == "road" else 0, bridge=bridge, tunnel=tunnel, speed=speed,
            conns=conns, rank=RANK.get(cls_k, 2), link=link, destinations=dests,
        ))
    _add_level_crossings(ways)
    return ways, conn_xy


def _add_level_crossings(ways):
    """Rails crossing roads at grade get a shared pseudo connector so their heights match."""
    rails = [w for w in ways if w.kind == "rail"]
    roads = [w for w in ways if w.kind == "road" and w.cls in CAR_CLASSES | {"path", "footway", "cycleway"}]
    if not rails:
        return
    tree = shapely.STRtree([shapely.LineString(w.xy) for w in roads])
    for rw in rails:
        rl = shapely.LineString(rw.xy)
        for i in tree.query(rl, predicate="intersects"):
            w = roads[i]
            inter = rl.intersection(shapely.LineString(w.xy))
            pts = [inter] if inter.geom_type == "Point" else [g for g in getattr(inter, "geoms", []) if g.geom_type == "Point"]
            for p in pts:
                s_r = rl.project(p)
                s_w = shapely.LineString(w.xy).project(p)
                if rw.in_ranges(s_r, rw.bridge + rw.tunnel, 3) or w.in_ranges(s_w, w.bridge + w.tunnel, 3):
                    continue
                cid = f"lx_{rw.id[:8]}_{w.id[:8]}_{int(s_r)}"
                for way, s in ((rw, s_r), (w, s_w)):
                    _insert_vertex(way, s)
                    way.conns[cid] = s


def _insert_vertex(w, s):
    if np.min(np.abs(w.s - s)) < 1e-3:
        return
    i = int(np.searchsorted(w.s, s))
    p = w.at(s)
    w.xy = np.insert(w.xy, i, p, axis=0)
    w.s = np.insert(w.s, i, s)


def clip_to_map(ways, margin=8.0):
    """Cut ways at the terrain border (keeps a small margin)."""
    lim = C.HALF - margin
    out = []
    for w in ways:
        inside = (np.abs(w.xy[:, 0]) < lim) & (np.abs(w.xy[:, 1]) < lim)
        if inside.all():
            out.append(w)
            continue
        if not inside.any():
            continue
        idx = np.flatnonzero(inside)
        runs = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)
        for k, run in enumerate(runs):
            if len(run) < 3:
                continue
            a, b = run[0], run[-1] + 1
            s0, s1 = w.s[a], w.s[b - 1]
            nw = Way(**{**w.__dict__})
            nw.id = f"{w.id}#{k}"
            nw.xy = w.xy[a:b].copy()
            nw.s = w.s[a:b] - s0
            shift = lambda rs: [(max(x0, s0) - s0, min(x1, s1) - s0) for x0, x1 in rs if x1 > s0 and x0 < s1]
            nw.bridge = shift(w.bridge)
            nw.tunnel = shift(w.tunnel)
            nw.speed = [(max(x0, s0) - s0, min(x1, s1) - s0, v) for x0, x1, v in w.speed if x1 > s0 and x0 < s1]
            nw.conns = {c: s - s0 for c, s in w.conns.items() if s0 - 1e-6 <= s <= s1 + 1e-6}
            out.append(nw)
    return out


def sample_grid(grid, x, y):
    """Bilinear sample of a terrain-grid array at world coordinates."""
    gx = (np.asarray(x) + C.HALF) / C.SQUARE
    gy = (np.asarray(y) + C.HALF) / C.SQUARE
    return ndimage.map_coordinates(grid, [gy, gx], order=1, mode="nearest")


def _smooth_profile(s, z, sigma):
    if s[-1] < 2.0:
        return np.full_like(z, z.mean())
    u = np.arange(0.0, s[-1] + 1.0, 1.0)
    zu = np.interp(u, s, z)
    zu = ndimage.gaussian_filter1d(zu, sigma, mode="nearest")
    return np.interp(s, u, zu)


def compute_elevations(ways, dem):
    for w in ways:
        raw = sample_grid(dem, w.xy[:, 0], w.xy[:, 1])
        w.z = _smooth_profile(w.s, raw, SIGMA.get(w.cls, 6))
    # Junction heights: weighted toward the highest ranked road.
    acc = {}
    for w in ways:
        for cid, s in w.conns.items():
            acc.setdefault(cid, []).append((w, s))
    jz = {}
    for cid, lst in acc.items():
        if len(lst) < 2:
            continue
        wts = np.array([4.0 ** w.rank for w, _ in lst])
        zs = np.array([w.z_at(s) for w, s in lst])
        jz[cid] = float((wts * zs).sum() / wts.sum())
    for w in ways:
        pins = sorted((s, jz[c] - w.z_at(s)) for c, s in w.conns.items() if c in jz)
        if not pins:
            continue
        ps = np.array([p[0] for p in pins])
        dz = np.array([p[1] for p in pins])
        corr = np.interp(w.s, ps, dz)
        # Fade the correction to zero beyond the outermost pins (dangling ends).
        fade = 40.0
        before = w.s < ps[0]
        corr[before] = dz[0] * np.clip(1 - (ps[0] - w.s[before]) / fade, 0, 1)
        after = w.s > ps[-1]
        corr[after] = dz[-1] * np.clip(1 - (w.s[after] - ps[-1]) / fade, 0, 1)
        w.z = w.z + corr
    # Bridges span straight between their abutments.
    for w in ways:
        for a, b in w.bridge:
            a2, b2 = max(a - 4.0, 0.0), min(b + 4.0, w.length)
            m = (w.s >= a2) & (w.s <= b2)
            if m.sum() < 2:
                continue
            za, zb = w.z_at(a2), w.z_at(b2)
            w.z[m] = za + (zb - za) * (w.s[m] - a2) / max(b2 - a2, 1e-6)
    return jz


def junctions(ways):
    """connector id -> list of (way, s) for connectors shared by >= 2 ways."""
    acc = {}
    for w in ways:
        for cid, s in w.conns.items():
            acc.setdefault(cid, []).append((w, s))
    return {c: v for c, v in acc.items() if len(v) >= 2}


def build():
    ways, conn_xy = load_network()
    ways = clip_to_map(ways)
    return ways, conn_xy
