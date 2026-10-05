"""Build the complete BeamNG mod: python -m oberndorf.build"""
import json
import math
import os
import re
import shutil
import time
import zipfile

import numpy as np
import shapely

from . import buildings, config as C, dem, geo, level, markings, props, roads, terrain, textures, trees
from .collada import Mesh, write_dae

T0 = time.time()


def log(msg):
    print(f"[{time.time() - T0:7.1f}s] {msg}", flush=True)


def slug(s):
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("Ä", "Ae").replace("Ö", "Oe") \
        .replace("Ü", "Ue").replace("ß", "ss")
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()[:40] or "x"


class SignRegistry:
    def __init__(self, out_dir):
        self.out_dir = out_dir
        self.mats = {}

    def __call__(self, kind, key):
        if kind in ("speed",):
            name = f"obd_sign_speed_{key}"
        elif key is None:
            name = f"obd_sign_{kind}"
        else:
            name = f"obd_sign_{kind}_{slug(str(key))}"
        if name not in self.mats:
            os.makedirs(self.out_dir, exist_ok=True)
            T = textures
            im = {"give_way": lambda: T.sign_give_way(), "stop": lambda: T.sign_stop(),
                  "priority": lambda: T.sign_priority_road(), "speed": lambda: T.sign_speed(key),
                  "crosswalk": lambda: T.sign_crosswalk(), "bus": lambda: T.sign_bus_stop(),
                  "andreas": lambda: T.sign_andreas(), "town": lambda: T.sign_town(key),
                  "town_end": lambda: T.sign_town(key, end=True), "street": lambda: T.sign_street(key),
                  "plate": lambda: T.sign_plate(key)}[kind]()
            fn = f"{name}.color.png"
            im.save(os.path.join(self.out_dir, fn), optimize=True)
            self.mats[name] = fn
        return name


def write_chunks(world_tiles, tree, group, shape_dir, rel_dir, prefix, node_name):
    used = set()
    n = 0
    for (i, j), mesh in sorted(world_tiles.items()):
        if mesh.empty():
            continue
        b = mesh.bounds()
        ox = (i + 0.5) * props.TILE
        oy = (j + 0.5) * props.TILE
        oz = float(math.floor(b[0][2]))
        local = Mesh()
        local.merge(mesh, offset=(-ox, -oy, -oz))
        fn = f"{prefix}_{i + 20}_{j + 20}.dae"
        used |= set(write_dae(os.path.join(shape_dir, fn), [(node_name, local)]))
        tree.add(group, {"class": "TSStatic", "position": [ox, oy, oz], "rotationMatrix": [1, 0, 0, 0, 1, 0, 0, 0, 1],
                         "shapeName": level.lp(rel_dir, fn), "collisionType": "Visible Mesh",
                         "decalType": "Visible Mesh", "isRenderEnabled": False, "useInstanceRenderData": True})
        n += 1
    return used, n


def main():
    L = os.path.join(C.BUILD, "levels", C.LEVEL)
    if os.path.exists(C.BUILD):
        shutil.rmtree(C.BUILD)
    os.makedirs(L)
    rng = np.random.default_rng(C.SEED)
    tree = level.SceneTree()

    # ------------------------------------------------------------------ data
    log("DEM ...")
    nat = dem.terrain_dem()
    log("road network ...")
    ways, _ = roads.build()
    roads.compute_elevations(ways, nat)
    J = roads.junctions(ways)
    landuse = geo.load_layer("land_use", pad=50)
    land = geo.load_layer("land", pad=50)
    infra = geo.load_layer("infrastructure", pad=50)
    water = geo.load_layer("water", pad=50)
    blds = geo.load_layer("building")
    divisions = geo.load_layer("division_area", pad=0)
    localities = [((r["names"] or {}).get("primary"), r["geom"]) for r in divisions
                  if r["subtype"] == "locality" and r["class"] == "land"]
    localities = [(n, g) for n, g in localities if n]
    builtup = shapely.union_all([r["geom"].buffer(30) for r in landuse
                                 if r["class"] in ("residential", "commercial", "retail", "industrial")]).buffer(-15)

    # ------------------------------------------------------------------ terrain
    log("terrain: water ...")
    h1, bodies, stream_core = terrain.carve_water(nat, water)
    log("terrain: roads ...")
    sp = terrain.road_samples(ways)
    heights, core, core_mat, _ = terrain.carve_roads(h1, sp)
    log("terrain: layers ...")
    lay = terrain.paint_layers(heights, nat, landuse, land, infra, core, core_mat, bodies, stream_core,
                               [r["geom"] for r in blds])
    z0 = float(math.floor(heights.min())) - 2.0
    max_h = float(math.ceil(heights.max() - z0)) + 2.0
    terrain.write_ter(os.path.join(L, "theTerrain.ter"), heights, z0, max_h, lay)
    back = terrain.read_ter_heights(os.path.join(L, "theTerrain.ter"), z0, max_h)
    log(f"terrain written: z0={z0} maxHeight={max_h} roundtrip max err={np.abs(back - heights).max():.3f} m")
    heights = back  # everything else sits on the quantised terrain

    tdir = os.path.join(L, "art", "terrains")
    det = {m: textures.terrain_detail(m, tdir) for m, _ in terrain.MATERIALS}
    mac = textures.terrain_macro(tdir)
    base = textures.terrain_base(lay, heights, tdir, [m for m, _ in terrain.MATERIALS])
    rel = lambda p: level.lp(os.path.relpath(p, L).replace(os.sep, "/"))
    det = {k: {kk: rel(vv) for kk, vv in v.items()} for k, v in det.items()}
    mac = {k: rel(v) for k, v in mac.items()}
    base = {k: rel(v) for k, v in base.items()}
    level.terrain_materials(os.path.join(tdir, "main.materials.json"), terrain.MATERIALS, base, det, mac,
                            C.TER_SIZE * C.SQUARE)
    level.environment_objects(tree, z0, max_h)

    # ------------------------------------------------------------------ roads
    log("road decals & markings ...")
    decals, control, zebras, busstops = markings.build_decals(ways, J, infra, builtup)
    for o in decals:
        tree.group(o["__parent"])
        tree.add(o["__parent"], o)
    rdir = os.path.join(L, "art", "road")
    rtex = textures.road_textures(rdir)
    road_mats = []
    ann = {"obd_asphalt": "ASPHALT", "obd_asphalt_minor": "ASPHALT", "obd_gravel": "GRAVEL", "obd_dirt": "DIRT",
           "obd_paving": "COBBLESTONE"}
    for name, p in rtex.items():
        road_mats.append(level.material(name, tex=rel(p), rough=0.85 if name in ann else 0.6, decal=True,
                                        annotation=None if name == "obd_invisible" else ("ROAD" if name in ann else "SOLID_LINE")))
    level.write_materials(os.path.join(rdir, "main.materials.json"), road_mats)
    log(f"  {len(decals)} decal roads, {len(control)} junction controls, {len(zebras)} zebras, {len(busstops)} bus stops")

    # ------------------------------------------------------------------ buildings
    log("buildings ...")
    bres, stats = buildings.build_buildings(blds, landuse, heights)
    log(f"  {len(bres)} buildings: {stats}")
    bworld = props.World(heights)
    for (x, y), m in bres:
        bworld.mesh(x, y).merge(m)
    sdir = os.path.join(L, "art", "shapes")
    g = tree.group("buildings")
    used_b, nb = write_chunks(bworld.tiles, tree, g, os.path.join(sdir, "buildings"), "art/shapes/buildings",
                              "bld", "bldmesh")
    log(f"  {nb} building chunks")

    # ------------------------------------------------------------------ props
    log("props: signs, lamps, rails, bridges ...")
    world = props.World(heights)
    sign_reg = SignRegistry(os.path.join(sdir, "signs"))
    sc = props.build_signs(world, ways, J, control, zebras, busstops, infra, builtup, localities, sign_reg)
    ls = props.build_lamps_signals(world, ways, infra)
    nd = props.build_delineators(world, ways, builtup)
    ng = props.build_guardrails(world, ways, nat)
    nbar = props.build_barriers(world, infra)
    nr = props.build_railway(world, ways, infra)
    nbr = props.build_bridges(world, ways)
    nt = trees.single_trees(world, land, rng)
    log(f"  signs {sc}, {ls}, delineators {nd}, guardrails {ng}, barriers {nbar}, rail ways {nr}, bridges {nbr}, trees {nt}")
    g = tree.group("props")
    used_p, npc = write_chunks(world.tiles, tree, g, os.path.join(sdir, "props"), "art/shapes/props", "props", "propmesh")
    log(f"  {npc} prop chunks")

    # ------------------------------------------------------------------ forest
    log("forest ...")
    excl = core | stream_core | terrain.poly_mask([r["geom"] for r in blds], buffer=3.0)
    for b in bodies:
        (r0, r1, c0, c1), m = b["mask"]
        excl[r0:r1, c0:c1] |= m
    fpts = trees.forest_points(land, heights, excl, rng)
    fcount = trees.write_forest(L, C.LEVEL_PATH, fpts, heights, rng)
    used_t = trees.write_tree_shapes(os.path.join(sdir, "trees"))
    log(f"  forest trees: {fcount}")

    # ------------------------------------------------------------------ water
    log("water ...")
    nw = build_water(tree, ways, water, bodies, nat, heights)
    log(f"  {nw} water objects")

    # ------------------------------------------------------------------ materials for meshes
    btex = textures.building_textures(os.path.join(sdir, "buildings"))
    mtex = textures.misc_textures(os.path.join(sdir, "misc"))
    ptex = textures.prop_textures(os.path.join(sdir, "misc"))
    dtex = textures.deck_textures(os.path.join(sdir, "misc"))
    texmap = {}
    for k, p in btex.items():
        texmap["bld_" + k] = p
    texmap.update(mtex)
    texmap.update(ptex)
    texmap.update(dtex)
    for name, fn in sign_reg.mats.items():
        texmap[name] = os.path.join(sdir, "signs", fn)
    consts = {
        "obd_sign_back": ((0.45, 0.46, 0.47), 0.5, 0.6), "obd_pole": ((0.55, 0.57, 0.58), 0.45, 0.8),
        "obd_lamp": ((0.2, 0.22, 0.23), 0.5, 0.5), "obd_lamp_glass": ((0.95, 0.93, 0.85), 0.2, 0.0),
        "obd_steel": ((0.25, 0.26, 0.27), 0.6, 0.6), "obd_wire": ((0.25, 0.18, 0.12), 0.5, 0.8),
        "obd_rail": ((0.32, 0.22, 0.16), 0.8, 0.5), "obd_rail_top": ((0.7, 0.71, 0.72), 0.25, 1.0),
    }
    used = set(used_b) | set(used_p) | set(used_t)
    mesh_mats = []
    for name in sorted(used):
        if name in consts:
            col, rough, metal = consts[name]
            mesh_mats.append(level.material(name, color=col, rough=rough, metal=metal))
        elif name in texmap:
            rough = 0.5 if name.startswith("obd_sign") else 0.85
            mesh_mats.append(level.material(name, tex=rel(texmap[name]), rough=rough,
                                            double=name in ("obd_fence_wood", "obd_guardrail") or name.startswith("bld_roof")))
        else:
            log(f"  WARNING: no texture for material {name}")
            mesh_mats.append(level.material(name, color=(0.8, 0.2, 0.8)))
    level.write_materials(os.path.join(sdir, "main.materials.json"), mesh_mats)

    # ------------------------------------------------------------------ spawn points, info
    spawns = spawn_points(tree, ways, infra)
    tree.write(L)
    preview(L, lay, heights, ways, bres)
    info = {
        "title": C.LEVEL_TITLE,
        "description": ("Oberndorf in Tirol (Bezirk Kitzbühel) im Maßstab 1:1 aus echten Daten: Straßen mit "
                        "österreichischen Bodenmarkierungen und Verkehrszeichen, Gebäude, Bahn, Ache und Gelände. "
                        "Daten: © OpenStreetMap-Mitwirkende (ODbL) via Overture Maps; Höhen: Mapzen Terrain Tiles."),
        "authors": "Generated with oberndorf-generator",
        "previews": [f"{C.LEVEL}_preview.jpg"],
        "size": [int(C.TER_SIZE * C.SQUARE), int(C.TER_SIZE * C.SQUARE)],
        "biome": "Alpine",
        "roads": "Bundesstraße B161, Landes- und Gemeindestraßen, Güterwege",
        "suitablefor": "Freeroam",
        "features": "Echte Straßen, Markierungen, Verkehrszeichen, Gebäude, Bahnlinie",
        "defaultSpawnPointName": spawns[0][0],
        "spawnPoints": [{"translationId": t, "objectname": n, "preview": f"{C.LEVEL}_preview.jpg"} for n, t in spawns],
    }
    with open(os.path.join(L, "info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)
    log("zip ...")
    os.makedirs(C.DIST, exist_ok=True)
    zpath = os.path.join(C.DIST, f"{C.LEVEL}.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _, files in os.walk(C.BUILD):
            for fn in files:
                if fn.endswith(".terrainheightmap.png"):
                    continue  # only needed for re-importing in the World Editor; kept in build/
                p = os.path.join(root, fn)
                z.write(p, os.path.relpath(p, C.BUILD).replace(os.sep, "/"))
    log(f"done: {zpath} ({os.path.getsize(zpath) / 1e6:.1f} MB)")


def build_water(tree, ways, water, bodies, nat, heights):
    g = tree.group("water")
    n = 0
    common = {"baseColor": [42, 92, 96, 255], "depthGradientMax": 3, "depthGradientTex": "core/art/water/depthcolor_ramp.png",
              "foamTex": "core/art/water/foam.dds", "rippleTex": "core/art/water/ripple.dds",
              "fullReflect": False, "reflectivity": 0.5, "overallRippleMagnitude": 0.6, "overallWaveMagnitude": 0.05,
              "Ripples (texture animation)": [{"rippleDir": [0, 1], "rippleSpeed": 0.4, "rippleTexScale": [6, 6]},
                                              {"rippleDir": [0.1, 1], "rippleSpeed": 0.7, "rippleTexScale": [2, 2]},
                                              {"rippleDir": [-0.1, 1], "rippleSpeed": 0.1, "rippleTexScale": [10, 10]}],
              "flowMagnitudePhysics": 1.5}
    river_polys = [b for b in bodies if b["river"]]
    for r in water:
        gm = r["geom"]
        if r["class"] != "river" or gm.geom_type != "LineString" or gm.length < 30:
            continue
        st = dict(r.get("source_tags") or [])
        if st.get("tunnel"):
            continue
        L = gm.length
        ds = np.arange(0, L, 12.0)
        pts = np.array([gm.interpolate(d).coords[0][:2] for d in ds] + [gm.coords[-1][:2]])
        inside = None
        nodes = []
        for p in pts:
            if abs(p[0]) > C.HALF - 10 or abs(p[1]) > C.HALF - 10:
                nodes.append(None)
                continue
            width = None
            zsurf = None
            for b in river_polys:
                if b["geom"].contains(shapely.Point(p)):
                    width = 2 * b["geom"].exterior.distance(shapely.Point(p)) + 2.0
                    (r0, r1, c0, c1), surf = b["surface"]
                    gx, gy = terrain.world_to_grid(p[0], p[1])
                    zsurf = float(surf[int(np.clip(gy - r0, 0, surf.shape[0] - 1)), int(np.clip(gx - c0, 0, surf.shape[1] - 1))]) + 0.1
                    break
            if width is None:
                try:
                    width = float(st.get("width", 6.0)) + 1.5
                except ValueError:
                    width = 7.5
                zsurf = float(roads.sample_grid(heights, [p[0]], [p[1]])[0]) + 0.75
            nodes.append([float(p[0]), float(p[1]), zsurf, min(width, 45.0), 2.0, 0, 0, 1])
        # split at None (outside map) and make the surface monotonic downstream
        runs, cur = [], []
        for nd in nodes:
            if nd is None:
                if len(cur) > 1:
                    runs.append(cur)
                cur = []
            else:
                cur.append(nd)
        if len(cur) > 1:
            runs.append(cur)
        for run in runs:
            z = np.array([nd[2] for nd in run])
            if z[0] < z[-1]:
                z = np.minimum.accumulate(z[::-1])[::-1]
            else:
                z = np.minimum.accumulate(z)
            for nd, zz in zip(run, z):
                nd[2] = round(float(zz), 3)
                nd[0], nd[1] = round(nd[0], 2), round(nd[1], 2)
            tree.add(g, {"class": "River", "name": f"river_{n}", "position": run[0][:3], "nodes": run, **common})
            n += 1
    # lakes / ponds
    for b in bodies:
        if b["river"]:
            continue
        gm = b["geom"]
        if gm.area < 300:
            continue
        rect = gm.minimum_rotated_rectangle
        c = np.asarray(rect.exterior.coords)[:4]
        e0, e1 = c[1] - c[0], c[2] - c[1]
        if np.hypot(*e0) < np.hypot(*e1):
            c = np.roll(c, -1, axis=0)
            e0, e1 = e1, e0
        ax = e0 / np.hypot(*e0)
        perp = e1 / np.hypot(*e1)
        Lx = np.hypot(*e0)
        start = c[0] + e1 / 2
        nodes = []
        for d in np.linspace(0, Lx, max(int(Lx / 8), 2) + 1):
            p = start + ax * d
            chord = shapely.LineString([p - perp * 500, p + perp * 500]).intersection(gm)
            wdt = chord.length if not chord.is_empty else 1.0
            if wdt < 1.0:
                continue
            mid = np.asarray(chord.centroid.coords[0]) if not chord.is_empty else p
            nodes.append([round(float(mid[0]), 2), round(float(mid[1]), 2), round(b["surface"], 3), round(wdt + 1.0, 2), 2.0, 0, 0, 1])
        if len(nodes) >= 2:
            tree.add(g, {"class": "River", "name": f"lake_{n}", "position": nodes[0][:3], "nodes": nodes, **common,
                         "flowMagnitudePhysics": 0})
            n += 1
    return n


def spawn_points(tree, ways, infra):
    g = tree.group("PlayerDropPoints")
    cars = [w for w in ways if markings.car(w) and w.rank >= 4 and not w.bridge]
    out = []

    def near(pt, pred=lambda w: True, name="spawn", title=""):
        best = None
        for w in cars:
            if not pred(w):
                continue
            ls = shapely.LineString(w.xy)
            d = ls.distance(pt)
            if best is None or d < best[0]:
                best = (d, w, ls.project(pt))
        if best is None:
            return
        _, w, s = best
        s = float(np.clip(s, 5, w.length - 5))
        p = w.at(s)
        t = w.tangent(s)
        right = np.array([t[1], -t[0]])
        p = p + right * (w.width / 4 if not w.oneway else 0)
        z = w.z_at(s) + 0.5
        dx, dy = t
        tree.add(g, {"name": name, "class": "SpawnSphere", "position": [round(p[0], 3), round(p[1], 3), round(z, 3)],
                     "autoplaceOnSpawn": "0", "dataBlock": "SpawnSphereMarker", "radius": 5,
                     "rotationMatrix": [round(-dy, 5), round(-dx, 5), 0, round(dx, 5), round(-dy, 5), 0, 0, 0, 1],
                     "sphereWeight": "1", "indoorWeight": "1", "outdoorWeight": "1"})
        out.append((name, title))

    church = None
    for r in geo.load_layer("building"):
        if (r.get("class") or "") == "church" and abs(r["geom"].centroid.x + 540) < 200:
            church = r["geom"].centroid
    near(church or shapely.Point(-450, 100), lambda w: w.cls in ("tertiary", "unclassified", "residential"),
         "spawn_ortszentrum", "Ortszentrum (Kirche)")
    station = [r["geom"] for r in infra if r["class"] == "railway_halt" and "Oberndorf" in ((r.get("names") or {}).get("primary") or "")]
    station = station or [r["geom"] for r in infra if r["class"] in ("railway_station", "railway_halt")]
    near(station[0].centroid if station else shapely.Point(-100, -100), lambda w: True, "spawn_bahnhof", "Bahnhof Oberndorf")
    near(shapely.Point(0, 0), lambda w: w.cls == "primary", "spawn_b161", "B161 Pass-Thurn-Straße")
    horn = [w for w in cars if "Horn" in w.name]
    if horn:
        top = max(horn, key=lambda w: w.z.max())
        i = int(np.argmax(top.z))
        near(shapely.Point(top.xy[i]), lambda w: w is top, "spawn_kitzbueheler_horn", "Panoramastraße Kitzbüheler Horn")
    return out


def preview(L, lay, heights, ways, bres):
    from PIL import Image, ImageDraw
    pal = np.array([textures.TERRAIN_COLORS[m] for m, _ in terrain.MATERIALS], np.uint8)
    img = pal[lay[::4, ::4]].astype(np.float32)
    h = heights[::4, ::4]
    gy, gx = np.gradient(h, 6.0)
    slope = np.pi / 2 - np.arctan(np.hypot(gx, gy))
    asp = np.arctan2(-gx, gy)
    hs = np.sin(np.radians(45)) * np.sin(slope) + np.cos(np.radians(45)) * np.cos(slope) * np.cos(np.radians(315) - asp)
    img = (img * np.clip(0.55 + 0.6 * hs, 0.3, 1.2)[..., None]).clip(0, 255).astype(np.uint8)[::-1]
    im = Image.fromarray(img).convert("RGB")
    d = ImageDraw.Draw(im)
    n = img.shape[0]
    sc = n / (C.TER_SIZE * C.SQUARE)

    def P(x, y):
        return ((x + C.HALF) * sc, n - (y + C.HALF) * sc)
    for w in sorted(ways, key=lambda w: w.rank):
        if w.kind == "rail":
            d.line([P(*p) for p in w.xy[::3]], fill=(70, 60, 60), width=2)
        elif w.rank >= 3:
            d.line([P(*p) for p in w.xy[::3]], fill=(250, 250, 250) if w.rank >= 7 else (225, 225, 220),
                   width=3 if w.rank >= 7 else 1)
    for (x, y), _ in bres:
        q = P(x, y)
        d.rectangle([q[0] - 1, q[1] - 1, q[0] + 1, q[1] + 1], fill=(170, 80, 60))
    im = im.resize((1024, 1024))
    im.save(os.path.join(L, f"{C.LEVEL}_preview.jpg"), quality=88)


if __name__ == "__main__":
    main()
