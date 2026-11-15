"""Configuration constants for LunarSight Scientific Modules.

All scientific calculations (illumination, Earth visibility, terrain analysis)
derive their geodetic constants, file paths, coordinate conventions, and frame
definitions from this module.
"""

from pathlib import Path

# Project root directory (resolves to the top-level LunarSight repository folder)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 1. Official LOLA Digital Elevation Model (DEM) files
LOLA_DEM_IMAGE_RELATIVE_PATH = Path(
    "data/raw/lola/LDEM_875S_20M_FLOAT.IMG"
)
LOLA_DEM_LABEL_RELATIVE_PATH = Path(
    "data/raw/lola/LDEM_875S_20M_FLOAT.LBL"
)
LOLA_DEM_IMAGE_PATH = PROJECT_ROOT / LOLA_DEM_IMAGE_RELATIVE_PATH
LOLA_DEM_LABEL_PATH = PROJECT_ROOT / LOLA_DEM_LABEL_RELATIVE_PATH

# Preserve the generic path names for existing callers while pointing them at
# the selected, validated LOLA product.
DEM_RELATIVE_PATH = LOLA_DEM_IMAGE_RELATIVE_PATH
DEM_FILE_PATH = LOLA_DEM_IMAGE_PATH

# 2. SPICE Kernel Directory
SPICE_KERNELS_RELATIVE_DIR = Path("data/spice_kernels")
SPICE_KERNELS_DIR = PROJECT_ROOT / SPICE_KERNELS_RELATIVE_DIR

# 3. Lunar Reference Frame
# Intended reference frame: Mean Earth / Polar Axis (MOON_ME)
# NOTE: MOON_ME is the intended reference frame. Its active validation remains
# pending until the corresponding binary lunar PCK and frame kernels are
# provided and verified in the kernel pool.
LUNAR_REFERENCE_FRAME = "MOON_ME"
FRAME_VALIDATION_STATUS = "PENDING_KERNELS"

# 4. Lunar Geodetic Constants
# IAU standard mean lunar radius (1,737.4 km)
LUNAR_RADIUS_METRES = 1737400.0

# 5. Coordinate Conventions
# - Latitude: Planetocentric (-90.0 deg at South Pole to +90.0 deg at North Pole)
# - Longitude: East-positive (0.0 to 360.0 degrees)
COORDINATE_SYSTEM = "planetocentric"
LONGITUDE_CONVENTION = "east-positive"

# 6. Units of Measurement
ELEVATION_UNITS = "metres"
DISTANCE_UNITS = "metres"
