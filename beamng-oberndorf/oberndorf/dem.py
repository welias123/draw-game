"""Digital elevation model: mosaic Terrarium tiles and resample onto the BeamNG terrain grid."""
import functools
import math
import os

import numpy as np
from PIL import Image
from scipy import ndimage

from . import config as C
from .fetch import dem_tile_range
from .geo import to_wgs


@functools.lru_cache(maxsize=2)
def _mosaic(z=C.DEM_ZOOM):
    x0, y0, x1, y1 = dem_tile_range(z)
    w = (x1 - x0 + 1) * 256
    h = (y1 - y0 + 1) * 256
    m = np.zeros((h, w), np.float32)
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            im = np.asarray(Image.open(os.path.join(C.DEM_DIR, f"{z}_{x}_{y}.png")).convert("RGB"), np.float32)
            e = im[:, :, 0] * 256.0 + im[:, :, 1] + im[:, :, 2] / 256.0 - 32768.0
            m[(y - y0) * 256:(y - y0 + 1) * 256, (x - x0) * 256:(x - x0 + 1) * 256] = e
    return m, x0, y0


def grid_xy(n=C.TER_SIZE, sq=C.SQUARE):
    """World x/y of terrain vertex columns/rows (row index = y, from south to north)."""
    c = -C.HALF + np.arange(n) * sq
    return c, c


def sample_dem(xs, ys, z=C.DEM_ZOOM):
    """Bicubic sample of the elevation at local coordinates (arrays)."""
    m, x0, y0 = _mosaic(z)
    lon, lat = to_wgs(np.asarray(xs, np.float64), np.asarray(ys, np.float64))
    n = 2 ** z
    px = ((np.asarray(lon) + 180.0) / 360.0 * n - x0) * 256.0 - 0.5
    lat_r = np.radians(np.asarray(lat))
    py = ((1.0 - np.arcsinh(np.tan(lat_r)) / math.pi) / 2.0 * n - y0) * 256.0 - 0.5
    return ndimage.map_coordinates(m, [py, px], order=3, mode="nearest")


def terrain_dem():
    """Elevation (m above sea level) on the full terrain grid, smoothed to remove tile artefacts."""
    xs, ys = grid_xy()
    out = np.zeros((C.TER_SIZE, C.TER_SIZE), np.float32)
    X = np.broadcast_to(xs[None, :], (256, C.TER_SIZE))
    for r0 in range(0, C.TER_SIZE, 256):
        Y = np.broadcast_to(ys[r0:r0 + 256, None], (256, C.TER_SIZE))
        out[r0:r0 + 256] = sample_dem(X.ravel(), Y.ravel()).reshape(256, C.TER_SIZE)
    # The source DGM is ~10 m; a light blur removes the 8-bit quantisation steps.
    out = ndimage.gaussian_filter(out, 2.0)
    return out
