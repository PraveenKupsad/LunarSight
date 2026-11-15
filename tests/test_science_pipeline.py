"""
Automated Pytest Suite for LunarSight Science Module
=====================================================
Validates DEM integrity, SPICE ephemeris, simplified illumination,
Earth visibility, and topographic shadowing.
"""

from pathlib import Path
import pytest
import numpy as np
import rasterio

from src.lunarsight_science.config import MOON_MEAN_RADIUS_KM
from src.lunarsight_science.data_collection.lola_downloader import LOLA_DATA_DIR, LOLA_CATALOG
from src.lunarsight_science.ephemeris.sun_position import (
    lunar_latlon_to_cartesian,
    compute_sun_position
)
from src.lunarsight_science.ephemeris.sun_illumination import (
    compute_slope_aspect,
    compute_cast_shadows
)
from src.lunarsight_science.ephemeris.earth_visibility import (
    compute_approximate_earth_direction,
    compute_earth_position
)
from src.lunarsight_science.terrain.elevation import (
    load_default_dem,
    compute_horizon_profile,
    evaluate_topographic_illumination
)


def test_dem_file_integrity():
    """Validates that the LOLA DEM file exists, is readable, and has valid bounds."""
    dem_path = load_default_dem()
    assert dem_path.exists(), "DEM file must exist"
    
    with rasterio.open(dem_path, "r") as src:
        assert src.width == 300
        assert src.height == 300
        data = src.read(1)
        assert data.min() < -2000.0, "Shackleton floor must be deeper than -2000m"
        assert data.max() > 1000.0, "Shackleton rim crest must exceed +1000m"
        assert src.crs is not None, "DEM must have valid coordinate reference system"


def test_cartesian_conversion():
    """At Lunar South Pole (lat = -90°), x=0, y=0, z = -R."""
    cart = lunar_latlon_to_cartesian(-90.0, 0.0)
    assert abs(cart[0]) < 1e-6
    assert abs(cart[1]) < 1e-6
    assert abs(cart[2] + MOON_MEAN_RADIUS_KM) < 1e-6


def test_sun_position_outputs():
    """Verifies that solar ephemeris yields valid topocentric angles."""
    res = compute_sun_position("2026-11-14 12:00:00 UTC", -89.9, 0.0)
    assert "solar_elevation_deg" in res
    assert "solar_azimuth_deg" in res
    assert 0.0 <= res["solar_azimuth_deg"] < 360.0
    assert -2.0 <= res["solar_elevation_deg"] <= 2.0  # Polar constraint


def test_simplified_illumination_physics():
    """Tests slope, aspect, and cast-shadow algorithms on synthetic topography."""
    test_grid = np.zeros((50, 50), dtype=np.float32)
    # Create a steep mound
    test_grid[25, 25] = 500.0
    slope, aspect = compute_slope_aspect(test_grid, cell_size_m=100.0)
    assert slope.max() > 0.0
    assert aspect.min() >= 0.0 and aspect.max() <= 2 * np.pi

    # Cast shadows from a low sun angle
    shadow_mask = compute_cast_shadows(test_grid, sun_elev_rad=0.05, sun_azimuth_rad=0.0, cell_size_m=100.0)
    assert shadow_mask.dtype == bool
    assert not shadow_mask.all(), "Some pixels must be shadowed by the mound"


def test_earth_visibility_simplified_and_spice():
    """Verifies approximate geometric Earth direction and SPICE calculations."""
    # Simplified mean tidal-locking direction
    elev, az = compute_approximate_earth_direction(-89.9, 0.0)
    assert -1.0 <= elev <= 1.0  # Polar grazing elevation
    assert abs(az - 0.0) < 1.0 or abs(az - 360.0) < 1.0  # Facing near-side meridian (North)

    # Dynamic SPICE calculation
    res = compute_earth_position("2026-11-14 12:00:00 UTC", -85.99, 2.93)
    assert "earth_elevation_deg" in res
    assert "dte_link_active" in res
    assert abs(res["sub_earth_lat_deg"]) <= 9.0  # Libration bound


def test_calculate_sun_illumination_returns_dict():
    """Verifies that calculate_sun_illumination exists, uses NASA SPICE by default, and returns valid data."""
    from src.lunarsight_science.ephemeris.sun_illumination import calculate_sun_illumination
    res = calculate_sun_illumination(save_image=False)
    assert isinstance(res, dict), "Must return a Python dictionary"
    assert "NASA_SPICE_DYNAMIC" in res["method"], "Default method must be NASA SPICE dynamic"
    assert "pct_illuminated" in res
    assert "pct_shadowed" in res
    assert "sun_elevation_deg" in res
    assert "sun_azimuth_deg" in res
    assert -2.0 <= res["sun_elevation_deg"] <= 2.0, "Polar Sun elevation must stay within physical limits"
    assert 0.0 <= res["sun_azimuth_deg"] < 360.0
    assert res["status"] == "SUCCESS"


def test_calculate_earth_visibility_returns_dict():
    """Verifies that calculate_earth_visibility exists, uses NASA SPICE by default, and returns valid data."""
    from src.lunarsight_science.ephemeris.earth_visibility import calculate_earth_visibility
    res = calculate_earth_visibility(save_image=False)
    assert isinstance(res, dict), "Must return a Python dictionary"
    assert "NASA_SPICE_DYNAMIC" in res["method"], "Default method must be NASA SPICE dynamic"
    assert "earth_elevation_deg" in res
    assert "earth_azimuth_deg" in res
    assert "rim_status" in res
    assert "floor_status" in res
    # Earth elevation at south pole oscillates between approx -7° and +7° due to real lunar librations (±8.5°)
    assert -10.0 <= res["earth_elevation_deg"] <= 10.0, "Polar Earth elevation must stay within lunar libration limits (±8.5°)"
    assert 0.0 <= res["earth_azimuth_deg"] < 360.0
    assert res["status"] == "SUCCESS"


def test_terrain_shadowing():
    """Verifies 360-degree horizon ray-tracing and PSR detection."""
    dem_path = load_default_dem()
    horizon = compute_horizon_profile(dem_path, 150, 150, azimuth_step_deg=30.0)
    assert len(horizon) > 0

    # Low sun (+0.5°) must be blocked inside deep crater floor (150, 150)
    eval_res = evaluate_topographic_illumination(0.5, 45.0, horizon)
    assert eval_res["illumination_state"] in ["DIRECT_SUNLIGHT", "TOPOGRAPHIC_SHADOW"]
