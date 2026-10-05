"""Download the raw data: Overture Maps (OpenStreetMap based) and Terrarium elevation tiles.

Usage:  python -m oberndorf.fetch
"""
import math
import os
import sys
import time
import urllib.request

from . import config as C


def fetch_overture(force=False):
    import pyarrow.compute as pc
    import pyarrow.dataset as ds
    import pyarrow.fs as pafs
    import pyarrow.parquet as pq

    os.makedirs(C.OVERTURE_DIR, exist_ok=True)
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    kw = dict(anonymous=True, region="us-west-2")
    if proxy:
        kw["proxy_options"] = proxy
    s3 = pafs.S3FileSystem(**kw)
    xmin, ymin, xmax, ymax = C.FETCH_BBOX
    for theme, typ in C.OVERTURE_LAYERS:
        out = os.path.join(C.OVERTURE_DIR, f"{typ}.parquet")
        if os.path.exists(out) and not force:
            print(f"  {typ}: cached")
            continue
        t = time.time()
        path = f"{C.OVERTURE_BUCKET}/release/{C.OVERTURE_RELEASE}/theme={theme}/type={typ}/"
        d = ds.dataset(path, filesystem=s3, format="parquet")
        flt = ((pc.field("bbox", "xmin") < xmax) & (pc.field("bbox", "xmax") > xmin) &
               (pc.field("bbox", "ymin") < ymax) & (pc.field("bbox", "ymax") > ymin))
        tbl = d.to_table(filter=flt)
        pq.write_table(tbl, out)
        print(f"  {typ}: {tbl.num_rows} rows ({time.time() - t:.1f}s)")


def lonlat_to_tile(lon, lat, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def dem_tile_range(z=C.DEM_ZOOM):
    xmin, ymin, xmax, ymax = C.FETCH_BBOX
    x0, y0 = lonlat_to_tile(xmin, ymax, z)
    x1, y1 = lonlat_to_tile(xmax, ymin, z)
    return int(x0), int(y0), int(x1), int(y1)


def fetch_dem(z=C.DEM_ZOOM):
    os.makedirs(C.DEM_DIR, exist_ok=True)
    x0, y0, x1, y1 = dem_tile_range(z)
    n = 0
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            out = os.path.join(C.DEM_DIR, f"{z}_{x}_{y}.png")
            if os.path.exists(out):
                continue
            url = C.DEM_URL.format(z=z, x=x, y=y)
            for attempt in range(4):
                try:
                    with urllib.request.urlopen(url, timeout=60) as r:
                        data = r.read()
                    break
                except Exception as e:  # network hiccup: back off and retry
                    if attempt == 3:
                        raise
                    print(f"  retry {url}: {e}")
                    time.sleep(2 ** (attempt + 1))
            with open(out, "wb") as f:
                f.write(data)
            n += 1
    print(f"  DEM tiles z{z}: x {x0}-{x1}, y {y0}-{y1} ({n} new)")


def main():
    force = "--force" in sys.argv
    print("Overture Maps ...")
    fetch_overture(force)
    print("Elevation tiles ...")
    fetch_dem()


if __name__ == "__main__":
    main()
