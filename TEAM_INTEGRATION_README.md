# LunarSight – Member 4 Handover & Team Integration Guide
**NASA Space Apps Challenge | LunarSight Project**  
**Subsystem**: Member 4 – NASA Data & Scientific Calculations  

This document explains how any teammate (Frontend, UI/UX, Rover Navigation, or Backend) can set up, import, and run the scientific calculation engine.

---

## 1. Important Python Source Files

All core scientific code is organized in the `src/lunarsight_science/` package:

| File Path | Role & Functionality |
| :--- | :--- |
| **`src/lunarsight_science/ephemeris/sun_illumination.py`** | Primary function `calculate_sun_illumination()` (slope, aspect, cast shadows). |
| **`src/lunarsight_science/ephemeris/earth_visibility.py`** | Primary function `calculate_earth_visibility()` (Earth line-of-sight & antenna bearing). |
| **`src/lunarsight_science/ephemeris/sun_position.py`** | NASA SPICE orbital vectors for Sun elevation, azimuth, and solar flux ($W/m^2$). |
| **`src/lunarsight_science/terrain/elevation.py`** | LOLA DEM reader, Horn's slope algorithm, and 360° horizon elevation masking. |
| **`src/lunarsight_science/data_collection/spice_manager.py`** | NASA NAIF SPICE kernel manager and loader. |
| **`src/lunarsight_science/data_collection/lola_downloader.py`** | NASA LRO LOLA topography downloader and inspector. |
| **`src/lunarsight_science/validation/benchmarks.py`** | Scientific validation against live NASA JPL Horizons REST API. |
| **`examples/test_integration.py`** | Fast 5-line integration test script. |
| **`examples/demo_lunarsight_science.py`** | Master end-to-end mission briefing script. |

---

## 2. Detailed Technical Guide Reference
For complete function signatures, input parameters, and dictionary output schemas, refer to:
👉 **`SCIENTIFIC_MODULE_GUIDE.md`** (located in the project root).

---

## 3. Generated Visualizations
Three publication-ready 300 DPI visualization maps are generated in `data/processed/`:

1. **`data/processed/lunar_terrain.png`**: High-contrast elevation map of Shackleton Crater ($89.9^\circ\text{S}$) with calibrated elevation colorbar in meters.
2. **`data/processed/sun_illumination.png`**: Solar sunlight map showing illuminated terrain (bright yellow) vs topographic shadow / PSRs (dark blue).
3. **`data/processed/earth_visibility.png`**: Direct-to-Earth (DTE) communication map showing line-of-sight coverage (cyan) vs terrain blackout zones (blue).

---

## 4. Required NASA Datasets

The module requires the following datasets located in the `data/` folder:

### A. Lunar Topography (DEM)
- **Path**: `data/raw/lola/MOON_LRO_NAC_DEM_89S210E_4mp.tif`
- **Details**: Cloud-Optimized GeoTIFF ($300 \times 300\text{ pixels}$, $100\text{ m/pixel}$ resolution, $30\text{ km} \times 30\text{ km}$ area, South Polar Stereographic projection).
- **Access Mode**: Strictly **read-only**. Never modified or overwritten.

### B. Official NASA NAIF SPICE Ephemeris Kernels
Located in `data/spice_kernels/`:
- **`de440s.bsp`** (31.1 MB): NASA JPL planetary ephemeris (Sun, Earth, Moon positions 1900–2050).
- **`moon_pa_de421_1900-2050.bpc`** (2.0 MB): High-accuracy lunar orientation and libration matrix.
- **`pck00010.tpc`** (128 KB): IAU planetary constants and lunar radii.
- **`naif0012.tls`** (5 KB): NASA leapseconds time table.
- **`moon_080317.tf`** (18 KB): Lunar reference frame definitions.

*(If kernels are ever missing, run `python -m src.lunarsight_science.data_collection.spice_manager` to download them automatically).*

---

## 5. Required Dependencies

The required Python packages are listed in `requirements.txt`:
- `numpy>=1.26.0`
- `scipy>=1.12.0`
- `matplotlib>=3.8.0`
- `spiceypy>=5.1.2`
- `astropy>=6.0.0`
- `rasterio>=1.3.9`
- `pyproj>=3.6.1`
- `requests>=2.31.0`
- `pytest>=8.0.0`

> **Note on Environment**: Do **not** commit or copy the `.venv` folder. Each teammate creates their own virtual environment using `requirements.txt`.

---

## 6. How Teammates Can Set Up and Run

### Step A: Set up your local environment
```powershell
# 1. Create a virtual environment
python -m venv .venv

# 2. Activate it (PowerShell)
.\.venv\Scripts\Activate.ps1

# 3. Install requirements
pip install -r requirements.txt
```

### Step B: Run the automated tests to verify
```powershell
pytest -v
```
*(All 11 tests should pass).*

### Step C: How to import and use in your code
Teammates can import both functions directly into frontend web servers (Flask/FastAPI), UI dashboards (Streamlit/Dash), or rover planning scripts:

```python
from src.lunarsight_science.ephemeris.sun_illumination import calculate_sun_illumination
from src.lunarsight_science.ephemeris.earth_visibility import calculate_earth_visibility

# 1. Calculate Solar Illumination
# By default, uses current UTC time and dynamic NASA SPICE ephemeris:
sun_data = calculate_sun_illumination(save_image=False)

print("Sun Altitude (deg) :", sun_data["sun_elevation_deg"])
print("Sunlit Area (%)    :", sun_data["pct_illuminated"])
print("Shadowed Area (%)  :", sun_data["pct_shadowed"])

# 2. Calculate Earth Visibility
# By default, uses NASA SPICE ephemeris and real lunar librations:
earth_data = calculate_earth_visibility(save_image=False)

print("Earth Altitude (deg):", earth_data["earth_elevation_deg"])
print("Antenna Azimuth     :", earth_data["earth_azimuth_deg"])
print("Rim Crest Comm Link :", earth_data["rim_status"])
print("Crater Floor Link   :", earth_data["floor_status"])
```

### Tip for Teammates:
Pass **`save_image=False`** for fast in-memory calculations when updating UI sliders or running path-planning simulations. Pass **`save_image=True`** when you want to update the visualization image on disk.
