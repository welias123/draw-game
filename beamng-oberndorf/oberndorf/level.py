"""Writers for the BeamNG level files: info.json, scene tree (items.level.json) and materials."""
import json
import os
import uuid

from . import config as C


def pid(*parts):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "oberndorf/" + "/".join(map(str, parts))))


def lp(*parts):
    """Absolute in-game path inside the level."""
    return "/".join([C.LEVEL_PATH] + list(parts))


class SceneTree:
    def __init__(self):
        self.groups = {"MissionGroup": []}
        self.parent = {}

    def group(self, name, parent="MissionGroup"):
        if name not in self.groups:
            self.groups[name] = []
            self.parent[name] = parent
            self.groups[parent].append({"name": name, "class": "SimGroup", "persistentId": pid("group", name),
                                        "__parent": parent})
        return name

    def add(self, group, obj):
        obj = dict(obj)
        obj["__parent"] = group
        obj.setdefault("persistentId", pid(group, obj.get("name", ""), len(self.groups[group])))
        self.groups[group].append(obj)

    def _dir(self, name):
        chain = [name]
        while chain[-1] in self.parent:
            chain.append(self.parent[chain[-1]])
        return os.path.join(*reversed(chain))

    def write(self, level_dir):
        main = os.path.join(level_dir, "main")
        os.makedirs(main, exist_ok=True)
        with open(os.path.join(main, "items.level.json"), "w") as f:
            f.write(json.dumps({"name": "MissionGroup", "class": "SimGroup", "persistentId": pid("MissionGroup"),
                                "enabled": "1"}) + "\n")
        for g, objs in self.groups.items():
            d = os.path.join(main, self._dir(g))
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "items.level.json"), "w") as f:
                for o in objs:
                    f.write(json.dumps(o, separators=(",", ":"), ensure_ascii=False) + "\n")


def material(name, tex=None, color=(0.8, 0.8, 0.8), rough=0.85, metal=0.0, decal=False, annotation=None,
             double=False, tags=("beamng",), emissive=None):
    st = {"roughnessFactor": rough, "metallicFactor": metal}
    if tex:
        st["baseColorMap"] = tex
    else:
        st["baseColorFactor"] = [round(c, 4) for c in color] + [1]
    if emissive:
        st["emissiveFactor"] = list(emissive)
        st["glow"] = True
    m = {"name": name, "mapTo": name, "class": "Material", "persistentId": pid("mat", name),
         "Stages": [st, {}, {}, {}], "version": 1.5}
    for i, t in enumerate(tags):
        m[f"materialTag{i}"] = t
    if decal:
        m["translucent"] = True
        m["translucentBlendOp"] = "LerpAlpha"
        m["materialTag0"] = "RoadAndPath"
    if double:
        m["doubleSided"] = True
    if annotation:
        m["annotation"] = annotation
    return m


def write_materials(path, mats):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({m["name"]: m for m in mats}, f, indent=1, ensure_ascii=False)


def terrain_materials(path, materials, tex, detail_tex, macro_tex, world_size):
    out = {}
    detail_size = {"Grass": 3, "Lawn": 2.5, "ForestFloor": 3, "Asphalt": 3, "Gravel": 2, "Dirt": 2.5, "Rock": 4}
    for internal, gm in materials:
        d = detail_tex[internal]
        u = pid("terrainmat", internal)
        name = f"{internal}-{u}"
        out[name] = {
            "name": name, "internalName": internal, "class": "TerrainMaterial", "persistentId": u,
            "aoBaseTex": tex["ao"], "aoBaseTexSize": world_size,
            "aoDetailTex": d["ao"], "aoDetailTexSize": detail_size[internal],
            "aoMacroTex": macro_tex["ao"], "aoMacroTexSize": 60,
            "baseColorBaseTex": tex["b"], "baseColorBaseTexSize": world_size,
            "baseColorDetailStrength": [0.6, 0.6],
            "baseColorDetailTex": d["b"], "baseColorDetailTexSize": detail_size[internal],
            "baseColorMacroStrength": [0.15, 0.25],
            "baseColorMacroTex": macro_tex["b"], "baseColorMacroTexSize": 60,
            "detailDistAtten": [1, 1], "detailDistances": [0, 0, 60, 120],
            "groundmodelName": gm,
            "heightBaseTex": tex["h"], "heightBaseTexSize": world_size,
            "heightDetailTex": d["h"], "heightDetailTexSize": detail_size[internal],
            "heightMacroTex": macro_tex["h"], "heightMacroTexSize": 60,
            "macroDistAtten": [0, 1], "macroDistances": [0, 10, 100, 3000],
            "normalBaseTex": tex["nm"], "normalBaseTexSize": world_size,
            "normalDetailStrength": [0.6, 0.3],
            "normalDetailTex": d["nm"], "normalDetailTexSize": detail_size[internal],
            "normalMacroStrength": [0.3, 0.5],
            "normalMacroTex": macro_tex["nm"], "normalMacroTexSize": 60,
            "roughnessBaseTex": tex["r"], "roughnessBaseTexSize": world_size,
            "roughnessDetailStrength": [0.4, 0.4],
            "roughnessDetailTex": d["r"], "roughnessDetailTexSize": detail_size[internal],
            "roughnessMacroStrength": [0.15, 0.4],
            "roughnessMacroTex": macro_tex["r"], "roughnessMacroTexSize": 60,
        }
    out[f"{C.LEVEL}_TerrainMaterialTextureSet"] = {
        "name": f"{C.LEVEL}_TerrainMaterialTextureSet", "class": "TerrainMaterialTextureSet",
        "persistentId": pid("texset"),
        "baseTexSize": [2048, 2048], "detailTexSize": [512, 512], "macroTexSize": [512, 512],
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(out, f, indent=1)


def environment_objects(tree, z0, max_height):
    g = tree.group("Level_objects")
    tree.add(g, {"name": "theLevelInfo", "class": "LevelInfo", "canvasClearColor": [180, 200, 230, 255],
                 "desc0": "Oberndorf in Tirol, Bezirk Kitzbuehel", "fogAtmosphereHeight": 1200,
                 "fogColor": [0.62, 0.74, 0.88, 1], "fogDensity": 0.00025, "fogDensityOffset": 300,
                 "gravity": -9.81000042, "levelName": C.LEVEL_TITLE, "soundAmbience": "AudioAmbienceDefault",
                 "temperatureCurveC": [0, 8, 0.25, 14, 0.5, 21, 0.75, 13, 1, 8], "visibleDistance": 6000})
    tree.add(g, {"name": "tod", "class": "TimeOfDay", "position": [0, 0, z0 + 50], "animate": "0",
                 "axisTilt": 23.44, "azimuthOverride": 0, "dayLength": 1800, "play": False,
                 "startTime": 0.15, "time": 0.15})
    tree.add(g, {"name": "sunsky", "class": "ScatterSky", "position": [0, 0, z0 + 50],
                 "ambientScale": [1, 0.94, 0.86, 1],
                 "ambientScaleGradientFile": "art/sky_gradients/default/gradient_ambient.png",
                 "brightness": 1.0, "colorize": [0.21, 0.35, 0.6, 1],
                 "colorizeGradientFile": "art/sky_gradients/default/gradient_colorize.png",
                 "exposure": 1.4, "flareScale": 10, "flareType": "BNG_Sunflare_2",
                 "fogScale": [0.6, 0.75, 1, 1], "fogScaleGradientFile": "art/sky_gradients/default/gradient_fog.png",
                 "mieScattering": 0.0004, "moonMat": "Moon_Glow_Mat", "moonScale": 0.03,
                 "nightCubemap": "nightCubemap", "nightFogGradientFile": "art/sky_gradients/default/gradient_fog.png",
                 "nightGradientFile": "art/sky_gradients/default/gradient_ambient.png",
                 "shadowDistance": 1600, "shadowSoftness": 0.2, "skyBrightness": 40,
                 "sunScale": [1, 0.92, 0.82, 1], "sunScaleGradientFile": "art/sky_gradients/default/gradient_sunscale.png",
                 "texSize": 1024, "useNightCubemap": True})
    tree.add(g, {"name": "theTerrain", "class": "TerrainBlock", "position": [-C.HALF, -C.HALF, round(z0, 3)],
                 "baseTexSize": 2048, "materialTextureSet": f"{C.LEVEL}_TerrainMaterialTextureSet",
                 "maxHeight": round(max_height, 3), "squareSize": C.SQUARE,
                 "terrainFile": lp("theTerrain.ter")})
    tree.add(g, {"name": "theForest", "class": "Forest"})
    return g
