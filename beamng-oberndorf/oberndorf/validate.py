"""Consistency checks for the generated level: python -m oberndorf.validate"""
import glob
import json
import os
import struct
import sys
import xml.etree.ElementTree as ET

from . import config as C

NS = "{http://www.collada.org/2005/11/COLLADASchema}"


def game_path(L, p):
    p = p.replace("\\", "/")
    if p.startswith(C.LEVEL_PATH + "/"):
        return os.path.join(L, p[len(C.LEVEL_PATH) + 1:])
    return None  # engine/core path


def main():
    L = os.path.join(C.BUILD, "levels", C.LEVEL)
    errors, warnings = [], []
    # ---- JSON files
    materials = {}
    for p in glob.glob(os.path.join(L, "**", "*.json"), recursive=True):
        try:
            if p.endswith("items.level.json") or p.endswith(".forest4.json"):
                with open(p, encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        if line.strip():
                            json.loads(line)
            else:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                if p.endswith("materials.json"):
                    for k, v in d.items():
                        if v.get("class") == "Material":
                            materials[v["mapTo"]] = (p, v)
        except Exception as e:
            errors.append(f"JSON {p}: {e}")
    # ---- textures referenced by materials
    for name, (p, m) in materials.items():
        for st in m["Stages"]:
            for k, v in st.items():
                if k.endswith("Map"):
                    gp = game_path(L, v)
                    if gp and not os.path.exists(gp):
                        errors.append(f"material {name}: missing texture {v}")
    tm = json.load(open(os.path.join(L, "art", "terrains", "main.materials.json")))
    for k, v in tm.items():
        for kk, vv in v.items():
            if kk.endswith("Tex"):
                gp = game_path(L, vv)
                if gp and not os.path.exists(gp):
                    errors.append(f"terrain material {k}: missing {vv}")
    # ---- scene objects
    n_obj = 0
    for p in glob.glob(os.path.join(L, "main", "**", "items.level.json"), recursive=True):
        for line in open(p, encoding="utf-8"):
            if not line.strip():
                continue
            o = json.loads(line)
            n_obj += 1
            if o["class"] == "TSStatic":
                gp = game_path(L, o["shapeName"])
                if not os.path.exists(gp):
                    errors.append(f"TSStatic shape missing: {o['shapeName']}")
            if o["class"] == "DecalRoad":
                if o["material"] not in materials:
                    errors.append(f"DecalRoad material missing: {o['material']}")
                if len(o["nodes"]) < 2:
                    errors.append("DecalRoad with < 2 nodes")
            if o["class"] == "TerrainBlock":
                gp = game_path(L, o["terrainFile"])
                b = open(gp, "rb").read()
                ver, n = b[0], struct.unpack("<I", b[1:5])[0]
                off = 5 + n * n * 2 + n * n + 4 * n * n
                cnt = struct.unpack("<I", b[off:off + 4])[0]
                off += 4
                names = []
                for _ in range(cnt):
                    ln = b[off]
                    names.append(b[off + 1:off + 1 + ln].decode())
                    off += 1 + ln
                if off != len(b):
                    errors.append(f".ter size mismatch ({off} vs {len(b)})")
                internal = {v.get("internalName") for v in tm.values()}
                for nm in names:
                    if nm not in internal:
                        errors.append(f"terrain layer {nm} has no TerrainMaterial")
                print(f"terrain: version {ver}, size {n}, layers {names}")
    # ---- DAE files
    n_dae = n_tri = 0
    for p in glob.glob(os.path.join(L, "art", "shapes", "**", "*.dae"), recursive=True):
        try:
            root = ET.parse(p).getroot()
        except ET.ParseError as e:
            errors.append(f"DAE parse {p}: {e}")
            continue
        n_dae += 1
        for geo in root.iter(NS + "geometry"):
            arrays = {fa.get("id"): int(fa.get("count")) for fa in geo.iter(NS + "float_array")}
            for fa in geo.iter(NS + "float_array"):
                if len(fa.text.split()) != int(fa.get("count")):
                    errors.append(f"{p}: float_array count mismatch")
            nverts = min(arrays.values()) // 2  # uv array has 2 per vertex
            for tri in geo.iter(NS + "triangles"):
                mat = tri.get("material")
                if mat not in materials:
                    errors.append(f"{os.path.basename(p)}: material {mat} not defined")
                idx = list(map(int, tri.find(NS + "p").text.split()))
                if len(idx) != 3 * int(tri.get("count")):
                    errors.append(f"{p}: index count mismatch")
                if idx and max(idx) >= nverts:
                    errors.append(f"{p}: index out of range")
                n_tri += int(tri.get("count"))
        for node in root.iter(NS + "node"):
            nm = node.get("name") or ""
            if "lod" not in p and nm[-1:].isdigit() and "trees" not in p:
                warnings.append(f"{os.path.basename(p)}: node name ends with digit ({nm}) -> would be read as LOD size")
    # pycollada full load of a few files
    try:
        import collada
        for p in sorted(glob.glob(os.path.join(L, "art", "shapes", "**", "*.dae"), recursive=True))[::40]:
            collada.Collada(p)
    except ImportError:
        warnings.append("pycollada not installed: skipped deep DAE check")
    except Exception as e:
        errors.append(f"pycollada: {e}")
    # ---- forest
    fitems = json.load(open(os.path.join(L, "art", "forest", "managedItemData.json")))
    for k, v in fitems.items():
        if not os.path.exists(game_path(L, v["shapeFile"])):
            errors.append(f"forest item {k}: missing shape")
    print(f"objects: {n_obj}, materials: {len(materials)}, dae files: {n_dae}, triangles: {n_tri:,}")
    for w in warnings[:20]:
        print("WARN", w)
    for e in errors[:50]:
        print("ERROR", e)
    print("OK" if not errors else f"{len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
