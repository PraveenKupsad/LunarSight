"""
Integration Verification Test for SCIENTIFIC_MODULE_GUIDE.md Examples
======================================================================
Validates that all code snippets, imports, function calls, and dictionary
structures documented in SCIENTIFIC_MODULE_GUIDE.md work exactly as advertised.
"""

import pytest

# 1. Verify Imports from Section 1
from src.lunarsight_science.ephemeris.sun_illumination import calculate_sun_illumination
from src.lunarsight_science.ephemeris.earth_visibility import calculate_earth_visibility
from src.lunarsight_science.ephemeris.sun_position import compute_sun_position
from src.lunarsight_science.ephemeris.earth_visibility import compute_earth_position


def test_guide_example_1_simulated():
    """Verifies Example 1: Basic Simulated Illumination & Visibility."""
    sun_data = calculate_sun_illumination(
        sun_elevation_deg=1.5,
        sun_azimuth_deg=90.0,
        save_image=False
    )
    assert isinstance(sun_data, dict)
    
    # Check all keys documented in Section 4
    expected_sun_keys = [
        "status", "method", "sun_elevation_deg", "sun_azimuth_deg",
        "pct_illuminated", "pct_shadowed", "total_pixels",
        "illuminated_pixels", "shadowed_pixels", "output_image_path"
    ]
    for key in expected_sun_keys:
        assert key in sun_data, f"Missing key in sun_data: {key}"
        
    assert sun_data["status"] == "SUCCESS"
    assert sun_data["sun_elevation_deg"] == 1.5
    assert sun_data["sun_azimuth_deg"] == 90.0

    earth_data = calculate_earth_visibility(
        site_lat=-89.9,
        site_lon=0.0,
        save_image=False
    )
    assert isinstance(earth_data, dict)
    
    # Check all keys documented in Section 4
    expected_earth_keys = [
        "status", "method", "site_lat", "site_lon", "earth_elevation_deg",
        "earth_azimuth_deg", "rim_status", "floor_status",
        "pct_visible", "pct_blocked", "output_image_path"
    ]
    for key in expected_earth_keys:
        assert key in earth_data, f"Missing key in earth_data: {key}"

    assert earth_data["status"] == "SUCCESS"
    assert earth_data["rim_status"] in ["Earth Visible", "Earth Not Visible"]
    assert earth_data["floor_status"] in ["Earth Visible", "Earth Not Visible"]


def test_guide_example_2_spice_dynamic():
    """Verifies Example 2: Dynamic NASA SPICE Integration."""
    mission_time = "2026-11-14 12:00:00 UTC"

    sun_data = calculate_sun_illumination(utc_time_str=mission_time, save_image=False)
    earth_data = calculate_earth_visibility(utc_time_str=mission_time, save_image=False)

    assert isinstance(sun_data, dict)
    assert isinstance(earth_data, dict)

    # Check that values accessed in Example 2 exist and are valid types
    assert isinstance(sun_data["sun_elevation_deg"], float)
    assert isinstance(sun_data["pct_illuminated"], float)
    assert earth_data["rim_status"] in ["Earth Visible", "Earth Not Visible"]

    # Check SPICE method attribution
    assert "NASA_SPICE_DYNAMIC" in sun_data["method"]
    assert "NASA_SPICE_DYNAMIC" in earth_data["method"]


def test_guide_section_1_spice_helpers():
    """Verifies helper imports documented in Section 1."""
    mission_time = "2026-11-14 12:00:00 UTC"
    sun_pos = compute_sun_position(mission_time, lat_deg=-89.9, lon_deg=0.0)
    assert "solar_elevation_deg" in sun_pos
    assert "solar_azimuth_deg" in sun_pos

    earth_pos = compute_earth_position(mission_time, lat_deg=-89.9, lon_deg=0.0)
    assert "earth_elevation_deg" in earth_pos
    assert "dte_link_active" in earth_pos
