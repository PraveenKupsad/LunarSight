"""
Configuration and Physical Constants for Lunar Calculations
Based on NASA/IAU Standards and Planetary Data System (PDS) specifications.
"""

from pathlib import Path

# Base Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
SPICE_KERNELS_DIR = DATA_DIR / "spice_kernels"

# Lunar Physical & Geometric Constants (IAU / NASA LRO LOLA standards)
MOON_MEAN_RADIUS_KM = 1737.4           # Standard mean volumetric radius in km
MOON_EQUATORIAL_RADIUS_KM = 1738.1     # Equatorial radius in km
MOON_POLAR_RADIUS_KM = 1736.0          # Polar radius in km

# Coordinate Reference Frames
# IAU_MOON: Standard IAU Mean Earth/Polar Axis frame defined in pck00010.tpc
# MOON_PA / MOON_ME: Frames defined in moon_080317.tf FK
DEFAULT_LUNAR_FRAME = "IAU_MOON"

# NASA Data Sources & Endpoints
NASA_NAIF_GENERIC_KERNELS_URL = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels"
NASA_JPL_HORIZONS_API_URL = "https://ssd-api.jpl.nasa.gov/horizons.api"

# Candidate Lunar South Pole Sites of Interest (Artemis III / Scientific Benchmarks)
BENCHMARK_SITES = {
    "SHACKLETON_RIM": {
        "lat": -89.9,
        "lon": 0.0,
        "description": "Connecting ridge near Shackleton Crater Rim"
    },
    "MALAPERT_MOUNTAIN": {
        "lat": -85.99,
        "lon": 2.93,
        "description": "Malapert Mountain (high continuous Earth visibility and solar exposure)"
    },
    "DE_GERLACHE_RIM": {
        "lat": -88.5,
        "lon": -88.3,
        "description": "De Gerlache Crater Connecting Ridge"
    }
}
