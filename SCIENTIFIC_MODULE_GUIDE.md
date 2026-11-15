# LunarSight Scientific Calculation Module – Integration Guide
**Member 4: NASA Data and Scientific Calculations**  
**NASA Space Apps Challenge**

This guide provides technical specifications, import instructions, and parameter reference for team members integrating the scientific calculations into frontends, rover path planners, or mission dashboards.

---

## 1. Module Imports

All functions are organized inside the `src.lunarsight_science` package.

```python
# 1. Solar illumination & topographic shadow calculation
from src.lunarsight_science.ephemeris.sun_illumination import calculate_sun_illumination

# 2. Earth visibility & communication link calculation
from src.lunarsight_science.ephemeris.earth_visibility import calculate_earth_visibility

# 3. Dynamic NASA NAIF SPICE ephemeris (high-precision coordinates)
from src.lunarsight_science.ephemeris.sun_position import compute_sun_position
from src.lunarsight_science.ephemeris.earth_visibility import compute_earth_position
```

---

## 2. Function Specifications & Required Parameters

### A. `calculate_sun_illumination()`

Evaluates surface slope, aspect, and cast-shadow ray-marching across the LOLA DEM.

| Parameter | Type | Default | Units / Description |
| :--- | :---: | :---: | :--- |
| `dem_path` | `Path \| str` | `data/raw/lola/...` | Path to LOLA GeoTIFF DEM file. |
| `output_path` | `Path \| str` | `data/processed/...` | Destination path for output PNG map. |
| `sun_elevation_deg` | `float` | `2.0` | Solar elevation angle above horizontal datum (degrees). |
| `sun_azimuth_deg` | `float` | `45.0` | Compass direction of Sun from North through East ($0^\circ$ to $360^\circ$). |
| `utc_time_str` | `str \| None` | `None` | Optional UTC timestamp (e.g. `"2026-11-14 12:00:00 UTC"`). If provided, overrides simulated angles with dynamic NASA SPICE ephemeris. |
| `save_image` | `bool` | `True` | Set to `False` for headless data-only processing without disk I/O. |

---

### B. `calculate_earth_visibility()`

Evaluates topocentric line-of-sight to Earth across the terrain to identify communication availability and blackouts.

| Parameter | Type | Default | Units / Description |
| :--- | :---: | :---: | :--- |
| `dem_path` | `Path \| str` | `data/raw/lola/...` | Path to LOLA GeoTIFF DEM file. |
| `output_path` | `Path \| str` | `data/processed/...` | Destination path for output PNG map. |
| `site_lat` | `float` | `-89.9` | Planetocentric latitude (degrees, negative for South). |
| `site_lon` | `float` | `0.0` | Planetocentric longitude (degrees East, $-180^\circ$ to $+180^\circ$). |
| `utc_time_str` | `str \| None` | `None` | Optional UTC timestamp. If provided, evaluates dynamic SPICE libration angles. |
| `save_image` | `bool` | `True` | Set to `False` for fast data-only processing. |

---

## 3. Example Function Calls

### Example 1: Basic Simulated Illumination & Visibility
```python
from src.lunarsight_science.ephemeris.sun_illumination import calculate_sun_illumination
from src.lunarsight_science.ephemeris.earth_visibility import calculate_earth_visibility

# Run simulated grazing illumination (Elevation +1.5°, Azimuth 90° East)
sun_data = calculate_sun_illumination(
    sun_elevation_deg=1.5,
    sun_azimuth_deg=90.0,
    save_image=True
)

# Run Earth visibility for Shackleton region
earth_data = calculate_earth_visibility(
    site_lat=-89.9,
    site_lon=0.0,
    save_image=True
)
```

### Example 2: Dynamic NASA SPICE Integration
```python
# Pass a real UTC mission date to pull exact solar and terrestrial vectors
mission_time = "2026-11-14 12:00:00 UTC"

sun_data = calculate_sun_illumination(utc_time_str=mission_time)
earth_data = calculate_earth_visibility(utc_time_str=mission_time)

print(f"Sun Altitude : {sun_data['sun_elevation_deg']}°")
print(f"Sunlit Area  : {sun_data['pct_illuminated']}%")
print(f"Earth Status : {earth_data['rim_status']}")
```

---

## 4. Example Dictionary Outputs

### Output of `calculate_sun_illumination()`:
```python
{
    "status": "SUCCESS",
    "method": "SIMULATED_GRAZING_VECTOR",  # or "NASA_SPICE_DYNAMIC (2026-11-14 12:00:00 UTC)"
    "sun_elevation_deg": 2.0,              # Degrees above horizon
    "sun_azimuth_deg": 45.0,               # Degrees clockwise from North
    "pct_illuminated": 15.24,              # Percentage of terrain receiving direct sun
    "pct_shadowed": 84.76,                 # Percentage of terrain in shadow (PSRs)
    "total_pixels": 90000,                 # Total grid cells evaluated
    "illuminated_pixels": 13716,           # Cells facing Sun and clear of terrain peaks
    "shadowed_pixels": 76284,              # Cells in shadow
    "output_image_path": "data/processed/sun_illumination.png"
}
```

### Output of `calculate_earth_visibility()`:
```python
{
    "status": "SUCCESS",
    "method": "SIMULATED_MEAN_LOCKING",    # or "NASA_SPICE_DYNAMIC (2026-11-14 12:00:00 UTC)"
    "site_lat": -89.9,                     # Target latitude
    "site_lon": 0.0,                      # Target longitude
    "earth_elevation_deg": 0.1,            # Elevation angle above spherical datum
    "earth_azimuth_deg": 0.0,              # Antenna pointing bearing toward Nearside
    "rim_status": "Earth Visible",         # Direct line of sight from crater rim
    "floor_status": "Earth Not Visible",   # Blocked by +8° to +12° crater walls
    "pct_visible": 62.3,                   # Percentage of terrain with DTE access
    "pct_blocked": 37.7,                   # Percentage of terrain in radio blackout
    "output_image_path": "data/processed/earth_visibility.png"
}
```

---

## 5. Dataset Configuration

- **File Path**: `data/raw/lola/MOON_LRO_NAC_DEM_89S210E_4mp.tif`
- **File Format**: Cloud-Optimized GeoTIFF (`GTiff`, 32-bit float).
- **Access Policy**: **Read-Only**. Scripts never modify or overwrite this file.
- **Grid Size**: $300 \times 300$ cells ($90,000$ elevation points).
- **Pixel Resolution**: $100.0\text{ meters per pixel}$ ($30\text{ km} \times 30\text{ km}$ spatial footprint).
- **Vertical Relief**: $-3,000.0\text{ m}$ (Shackleton floor) to $+1,360.0\text{ m}$ (rim crest).

---

## 6. Coordinate System & Reference Frame

| Property | Standard / Specification |
| :--- | :--- |
| **Planetary Body** | Moon (NAIF ID: `301`) |
| **Reference Datum** | IAU 2000 Moon Mean Radius ($R = 1,737,400\text{ m}$) |
| **Cartographic Projection** | South Polar Stereographic (`+proj=stere +lat_0=-90 +lon_0=0 +k=1 +R=1737400 +units=m +no_defs`) |
| **Ephemeris Frame** | `IAU_MOON` (Mean Earth / Polar Axis) or `MOON_PA` (Principal Axes) |
| **Compass Azimuth** | $0^\circ$ to $360^\circ$ clockwise from Lunar North ($0^\circ = \text{North}$, $90^\circ = \text{East}$, $180^\circ = \text{South}$, $270^\circ = \text{West}$) |
| **Time System** | UTC $\to$ Ephemeris Time (ET / TDB seconds past J2000 epoch) |

---

## 7. Current Architecture & NASA SPICE Integration Status

1. **NASA SPICE Kernels Fully Integrated**:
   - `spice_manager.py` downloads official generic kernels (`de440s.bsp`, `naif0012.tls`, `pck00010.tpc`, `moon_pa_de421.bpc`, `moon_080317.tf`).
   - `sun_position.py` computes millimeter-precise Sun vectors with light-time correction (`LT+S`).
   - `benchmarks.py` cross-validates against live queries from the **NASA JPL Horizons REST API** ($< 0.001\%$ error margin).

2. **NASA SPICE Ephemeris Execution**:
   - **Default Execution**: When no `utc_time_str` is provided, `calculate_sun_illumination()` and `calculate_earth_visibility()` automatically default to the current UTC time (`datetime.now(timezone.utc)`) and calculate exact Sun and Earth vectors using NASA SPICE kernels (`de440s.bsp`, `moon_pa_de421.bpc`, `pck00010.tpc`).
   - **No Silent Fallback**: If required SPICE kernels are missing from `data/spice_kernels/`, the functions raise a clear `RuntimeError` rather than silently generating simulated results.
   - **Custom Solar Angles**: Custom angles can still be passed explicitly (e.g. `sun_elevation_deg=1.5, sun_azimuth_deg=90.0`) for testing synthetic scenarios.

3. **Spatial Resolution Limitation**:
   - The primary DEM has a grid cell size of $100\text{ m}$. Boulders, micro-craters, and surface features smaller than $100\text{ m}$ are not resolved in the current elevation raster.
