"""Central configuration for the Oberndorf in Tirol BeamNG map generator."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OVERTURE_DIR = os.path.join(DATA, "overture")
DEM_DIR = os.path.join(DATA, "dem")
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")

LEVEL = "oberndorf_in_tirol"
LEVEL_TITLE = "Oberndorf in Tirol"
LEVEL_PATH = f"/levels/{LEVEL}"

# Map origin: centre of the municipality of Oberndorf in Tirol (Bezirk Kitzbuehel).
CENTER_LON = 12.39272
CENTER_LAT = 47.49778
# Local transverse mercator centred on the map, so +y is true north and distances are metres.
LOCAL_CRS = (f"+proj=tmerc +lat_0={CENTER_LAT} +lon_0={CENTER_LON} +k=1 "
             "+x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs")

# Terrain: 4096 x 4096 vertices at 1.5 m -> 6.1 km x 6.1 km, covers the whole municipality.
TER_SIZE = 4096
SQUARE = 1.5
HALF = TER_SIZE * SQUARE / 2.0

# Geographic bbox used for downloading (a little larger than the terrain).
FETCH_BBOX = (12.345, 47.466, 12.440, 47.530)

OVERTURE_RELEASE = "2026-09-23.1"
OVERTURE_BUCKET = "overturemaps-us-west-2"
OVERTURE_LAYERS = [
    ("transportation", "segment"),
    ("transportation", "connector"),
    ("buildings", "building"),
    ("buildings", "building_part"),
    ("base", "infrastructure"),
    ("base", "land_use"),
    ("base", "land_cover"),
    ("base", "water"),
    ("base", "land"),
    ("places", "place"),
    ("divisions", "division_area"),
]

# Terrarium elevation tiles (Mapzen / AWS open data, includes the Austrian 10 m DGM).
DEM_ZOOM = 15
DEM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"

SEED = 1337
