"""Projection helpers and Overture data loading in local map coordinates (metres, +x east, +y north)."""
import os

import numpy as np
import pyarrow.parquet as pq
import shapely
from pyproj import Transformer

from . import config as C

_to_local = Transformer.from_crs("EPSG:4326", C.LOCAL_CRS, always_xy=True)
_to_wgs = Transformer.from_crs(C.LOCAL_CRS, "EPSG:4326", always_xy=True)

MAP_BOX = shapely.box(-C.HALF, -C.HALF, C.HALF, C.HALF)


def to_local(lon, lat):
    return _to_local.transform(lon, lat)


def to_wgs(x, y):
    return _to_wgs.transform(x, y)


def project_geom(g):
    def f(c):
        x, y = _to_local.transform(c[:, 0], c[:, 1])
        return np.column_stack([x, y])
    return shapely.transform(g, f)


def load_layer(name, clip=True, pad=0.0):
    """Load an Overture layer as a list of dicts with a projected shapely 'geom'."""
    path = os.path.join(C.OVERTURE_DIR, f"{name}.parquet")
    rows = pq.read_table(path).to_pylist()
    box = MAP_BOX.buffer(pad) if pad else MAP_BOX
    out = []
    for r in rows:
        g = project_geom(shapely.from_wkb(r["geometry"]))
        if clip and not g.intersects(box):
            continue
        r["geom"] = g
        del r["geometry"]
        out.append(r)
    return out


def source_tags(r):
    st = r.get("source_tags")
    if not st:
        return {}
    if isinstance(st, dict):
        return st
    return dict(st)


def name_of(r):
    n = r.get("names")
    if n and n.get("primary"):
        return n["primary"]
    return None
