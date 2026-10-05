"""Minimal COLLADA 1.4.1 writer (Z-up, metres) for static meshes with several materials."""
import os

import numpy as np


class Mesh:
    """Triangle soup grouped by material. Vertices are not shared between materials."""

    def __init__(self):
        self.parts = {}

    def _part(self, mat):
        if mat not in self.parts:
            self.parts[mat] = {"v": [], "n": [], "uv": [], "f": [], "count": 0}
        return self.parts[mat]

    def add(self, mat, verts, normals, uvs, faces):
        verts = np.asarray(verts, np.float64).reshape(-1, 3)
        if len(verts) == 0:
            return
        p = self._part(mat)
        p["v"].append(verts)
        p["n"].append(np.asarray(normals, np.float64).reshape(-1, 3))
        p["uv"].append(np.asarray(uvs, np.float64).reshape(-1, 2))
        p["f"].append(np.asarray(faces, np.int64).reshape(-1, 3))  # chunk-local indices
        p["count"] += len(verts)

    def add_quad(self, mat, a, b, c, d, uv=((0, 0), (1, 0), (1, 1), (0, 1)), double=False):
        """Quad a-b-c-d counter-clockwise when seen from the front."""
        v = np.array([a, b, c, d], np.float64)
        n = np.cross(v[1] - v[0], v[2] - v[0])
        ln = np.linalg.norm(n)
        if ln < 1e-12:
            n = np.cross(v[2] - v[0], v[3] - v[0])
            ln = np.linalg.norm(n)
            if ln < 1e-12:
                return
        n = n / ln
        self.add(mat, v, np.tile(n, (4, 1)), uv, [[0, 1, 2], [0, 2, 3]])
        if double:
            self.add(mat, v[::-1], np.tile(-n, (4, 1)), list(uv)[::-1], [[0, 1, 2], [0, 2, 3]])

    def add_tri(self, mat, a, b, c, uv=((0, 0), (1, 0), (0.5, 1))):
        v = np.array([a, b, c], np.float64)
        n = np.cross(v[1] - v[0], v[2] - v[0])
        ln = np.linalg.norm(n)
        if ln < 1e-12:
            return
        self.add(mat, v, np.tile(n / ln, (3, 1)), uv, [[0, 1, 2]])

    def add_box(self, mat, center, size, axis=(1, 0), uv_scale=1.0, bottom=True):
        """Oriented box: axis = 2D direction of local x."""
        cx, cy, cz = center
        sx, sy, sz = size
        ax = np.array([axis[0], axis[1], 0.0])
        ax /= np.linalg.norm(ax)
        ay = np.array([-ax[1], ax[0], 0.0])
        az = np.array([0.0, 0.0, 1.0])
        c = np.array([cx, cy, cz])

        def P(i, j, k):
            return c + ax * sx / 2 * i + ay * sy / 2 * j + az * sz / 2 * k
        u = uv_scale
        faces = [
            (P(-1, -1, -1), P(1, -1, -1), P(1, -1, 1), P(-1, -1, 1), sx, sz),   # -y
            (P(1, 1, -1), P(-1, 1, -1), P(-1, 1, 1), P(1, 1, 1), sx, sz),       # +y
            (P(1, -1, -1), P(1, 1, -1), P(1, 1, 1), P(1, -1, 1), sy, sz),       # +x
            (P(-1, 1, -1), P(-1, -1, -1), P(-1, -1, 1), P(-1, 1, 1), sy, sz),   # -x
            (P(-1, -1, 1), P(1, -1, 1), P(1, 1, 1), P(-1, 1, 1), sx, sy),       # top
        ]
        if bottom:
            faces.append((P(-1, 1, -1), P(1, 1, -1), P(1, -1, -1), P(-1, -1, -1), sx, sy))
        for a, b, cc, d, w, h in faces:
            self.add_quad(mat, a, b, cc, d, ((0, 0), (w * u, 0), (w * u, h * u), (0, h * u)))

    def add_cylinder(self, mat, base, height, radius, segs=8, top=True, radius_top=None, uv_scale=1.0):
        bx, by, bz = base
        rt = radius if radius_top is None else radius_top
        ang = np.linspace(0, 2 * np.pi, segs + 1)
        for i in range(segs):
            a0, a1 = ang[i], ang[i + 1]
            p0 = (bx + radius * np.cos(a0), by + radius * np.sin(a0), bz)
            p1 = (bx + radius * np.cos(a1), by + radius * np.sin(a1), bz)
            q1 = (bx + rt * np.cos(a1), by + rt * np.sin(a1), bz + height)
            q0 = (bx + rt * np.cos(a0), by + rt * np.sin(a0), bz + height)
            u0, u1 = i / segs * uv_scale, (i + 1) / segs * uv_scale
            if rt > 1e-6:
                self.add_quad(mat, p0, p1, q1, q0, ((u0, 0), (u1, 0), (u1, height), (u0, height)))
            else:
                self.add_tri(mat, p0, p1, (bx, by, bz + height), ((u0, 0), (u1, 0), ((u0 + u1) / 2, height)))
        if top and rt > 1e-6:
            c = (bx, by, bz + height)
            for i in range(segs):
                a0, a1 = ang[i], ang[i + 1]
                self.add_tri(mat, (bx + rt * np.cos(a0), by + rt * np.sin(a0), bz + height),
                             (bx + rt * np.cos(a1), by + rt * np.sin(a1), bz + height), c,
                             ((0.5 + 0.5 * np.cos(a0), 0.5 + 0.5 * np.sin(a0)),
                              (0.5 + 0.5 * np.cos(a1), 0.5 + 0.5 * np.sin(a1)), (0.5, 0.5)))

    def merge(self, other, offset=(0, 0, 0)):
        off = np.asarray(offset, np.float64)
        for mat, p in other.parts.items():
            for v, n, uv, f in zip(p["v"], p["n"], p["uv"], p["f"]):
                self.add(mat, v + off, n, uv, f)

    def bounds(self):
        allv = [v for p in self.parts.values() for v in p["v"]]
        if not allv:
            return None
        a = np.vstack(allv)
        return a.min(0), a.max(0)

    def tri_count(self):
        return sum(sum(len(f) for f in p["f"]) for p in self.parts.values())

    def empty(self):
        return not self.parts


def _fmt(a, prec):
    s = np.char.mod(f"%.{prec}f", np.asarray(a, np.float64).ravel())
    s = np.char.rstrip(np.char.rstrip(s, "0"), ".")
    s[s == "-0"] = "0"
    s[s == ""] = "0"
    return " ".join(s.tolist())


def _geometry_xml(gid, mesh):
    out = []
    mats = sorted(mesh.parts)
    V = []
    Nn = []
    UV = []
    tris = []
    count = 0
    for m in mats:
        p = mesh.parts[m]
        fs = []
        for v, f in zip(p["v"], p["f"]):
            fs.append(f + count)
            count += len(v)
        V.append(np.vstack(p["v"]))
        Nn.append(np.vstack(p["n"]))
        UV.append(np.vstack(p["uv"]))
        tris.append((m, np.vstack(fs)))
    V = np.vstack(V)
    Nn = np.vstack(Nn)
    UV = np.vstack(UV)
    nv = len(V)
    out.append(f'<geometry id="{gid}" name="{gid}"><mesh>')
    out.append(f'<source id="{gid}-pos"><float_array id="{gid}-pos-arr" count="{nv * 3}">{_fmt(V, 2)}</float_array>'
               f'<technique_common><accessor source="#{gid}-pos-arr" count="{nv}" stride="3">'
               '<param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/>'
               '</accessor></technique_common></source>')
    out.append(f'<source id="{gid}-nrm"><float_array id="{gid}-nrm-arr" count="{nv * 3}">{_fmt(Nn, 2)}</float_array>'
               f'<technique_common><accessor source="#{gid}-nrm-arr" count="{nv}" stride="3">'
               '<param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/>'
               '</accessor></technique_common></source>')
    out.append(f'<source id="{gid}-uv"><float_array id="{gid}-uv-arr" count="{nv * 2}">{_fmt(UV, 3)}</float_array>'
               f'<technique_common><accessor source="#{gid}-uv-arr" count="{nv}" stride="2">'
               '<param name="S" type="float"/><param name="T" type="float"/>'
               '</accessor></technique_common></source>')
    out.append(f'<vertices id="{gid}-vtx"><input semantic="POSITION" source="#{gid}-pos"/></vertices>')
    for m, f in tris:
        out.append(f'<triangles material="{m}" count="{len(f)}">'
                   f'<input semantic="VERTEX" source="#{gid}-vtx" offset="0"/>'
                   f'<input semantic="NORMAL" source="#{gid}-nrm" offset="0"/>'
                   f'<input semantic="TEXCOORD" source="#{gid}-uv" offset="0" set="0"/>'
                   f'<p>{" ".join(map(str, f.ravel()))}</p></triangles>')
    out.append('</mesh></geometry>')
    return "".join(out), mats


def write_dae(path, nodes, lod=False):
    """nodes: list of (name, Mesh). With lod=True the DTS-style base00/start01 hierarchy is used and
    node names must end with their detail size (e.g. 'tree_hi_a150')."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    geoms = []
    all_mats = set()
    inst = []
    for name, mesh in nodes:
        if mesh.empty():
            continue
        gid = f"{name}-mesh"
        xml, mats = _geometry_xml(gid, mesh)
        geoms.append(xml)
        all_mats.update(mats)
        binds = "".join(f'<instance_material symbol="{m}" target="#{m}"/>' for m in mats)
        inst.append(f'<node id="{name}" name="{name}" type="NODE">'
                    f'<instance_geometry url="#{gid}"><bind_material><technique_common>{binds}'
                    '</technique_common></bind_material></instance_geometry></node>')
    effects = "".join(
        f'<effect id="{m}-fx"><profile_COMMON><technique sid="common"><lambert><diffuse>'
        '<color sid="diffuse">0.8 0.8 0.8 1</color></diffuse></lambert></technique></profile_COMMON></effect>'
        for m in sorted(all_mats))
    materials = "".join(f'<material id="{m}" name="{m}"><instance_effect url="#{m}-fx"/></material>'
                        for m in sorted(all_mats))
    body = "".join(inst)
    if lod:
        body = ('<node id="base00" name="base00" type="NODE"><node id="start01" name="start01" type="NODE">'
                + body + '</node></node>')
    xml = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">'
           '<asset><contributor><authoring_tool>oberndorf-generator</authoring_tool></contributor>'
           '<unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset>'
           f'<library_effects>{effects}</library_effects>'
           f'<library_materials>{materials}</library_materials>'
           f'<library_geometries>{"".join(geoms)}</library_geometries>'
           f'<library_visual_scenes><visual_scene id="Scene" name="Scene">{body}</visual_scene></library_visual_scenes>'
           '<scene><instance_visual_scene url="#Scene"/></scene></COLLADA>\n')
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)
    return sorted(all_mats)
