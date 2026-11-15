"""
NASA SPICE Sun Position & Sunlight Illumination Engine
======================================================
Calculates high-precision lunar-centric Sun position vectors, topocentric 
solar elevation/azimuth angles, and direct solar irradiance for any lunar coordinate.

Scientific Methods & Reference Frames:
- Frame: MOON_PA (Principal Axes) or IAU_MOON (Mean Earth / Polar Axis)
- Topocentric Frame: East-North-Zenith local horizon frame
- Light-time correction: LT+S (One-way light time + stellar aberration)
- Physical Standards: IAU / NASA NAIF SPICE Toolkit
"""

import math
from datetime import datetime
from typing import Any
import numpy as np
import spiceypy as spice

from ..config import MOON_MEAN_RADIUS_KM
from ..data_collection.spice_manager import ensure_kernels, load_kernels


# Solar Constants
AU_KM = 149597870.7                  # Astronomical Unit in km
SOLAR_CONSTANT_1AU = 1361.0          # Solar irradiance at 1 AU in W/m^2
SUN_RADIUS_KM = 696340.0             # Nominal Solar physical radius in km


def init_spice() -> None:
    """Ensures SPICE kernels are downloaded and loaded into memory."""
    if spice.ktotal("ALL") == 0:
        ensure_kernels()
        load_kernels()


def lunar_latlon_to_cartesian(
    lat_deg: float,
    lon_deg: float,
    elevation_km: float = 0.0,
    moon_radius_km: float = MOON_MEAN_RADIUS_KM
) -> np.ndarray:
    """
    Converts lunar planetocentric latitude and longitude to a 3D Cartesian position vector
    in the Moon body-fixed frame (km).
    """
    lat_rad = math.radians(lat_deg)
    lon_rad = math.radians(lon_deg)
    r = moon_radius_km + elevation_km

    x = r * math.cos(lat_rad) * math.cos(lon_rad)
    y = r * math.cos(lat_rad) * math.sin(lon_rad)
    z = r * math.sin(lat_rad)
    return np.array([x, y, z])


def get_topocentric_basis(lat_deg: float, lon_deg: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Computes orthonormal unit vectors for the local Topocentric Horizon frame:
    - Zenith (Up): Outward normal to the lunar sphere
    - North: Tangent to meridian pointing towards Lunar North Pole
    - East: Tangent to parallel pointing towards lunar East (increasing longitude)
    """
    lat_rad = math.radians(lat_deg)
    lon_rad = math.radians(lon_deg)

    # Zenith / Up unit vector
    u_zenith = np.array([
        math.cos(lat_rad) * math.cos(lon_rad),
        math.cos(lat_rad) * math.sin(lon_rad),
        math.sin(lat_rad)
    ])

    # North unit vector
    u_north = np.array([
        -math.sin(lat_rad) * math.cos(lon_rad),
        -math.sin(lat_rad) * math.sin(lon_rad),
        math.cos(lat_rad)
    ])

    # East unit vector (East = North x Zenith)
    u_east = np.array([
        -math.sin(lon_rad),
        math.cos(lon_rad),
        0.0
    ])

    return u_east, u_north, u_zenith


def compute_sun_position(
    utc_time_str: str,
    lat_deg: float,
    lon_deg: float,
    elevation_km: float = 0.0,
    lunar_frame: str = "IAU_MOON"
) -> dict[str, Any]:
    """
    Calculates the exact position of the Sun relative to a lunar surface site at a specific UTC time.

    Returns:
    - solar_elevation_deg: Sun center angle above the local mathematical horizon (degrees)
    - solar_azimuth_deg: Compass bearing from Lunar North through East [0° to 360°)
    - distance_km: Distance from lunar site to Sun center (km)
    - solar_disk_radius_deg: Apparent angular radius of the Sun's disk (degrees)
    - solar_irradiance_w_m2: Direct unshadowed solar flux at the Moon's orbital distance (W/m^2)
    - disk_state: 'FULL', 'PARTIAL', or 'BELOW_HORIZON' (relative to smooth horizon)
    """
    init_spice()

    # Convert UTC string to Ephemeris Time (ET/TDB seconds past J2000)
    et = spice.str2et(utc_time_str)

    # 1. Lunar surface site position in Moon body-fixed frame (km)
    r_site_moon = lunar_latlon_to_cartesian(lat_deg, lon_deg, elevation_km)

    # 2. Vector from Moon center to Sun center in lunar frame with light-time correction
    pos_sun_moon, _ = spice.spkpos("SUN", et, lunar_frame, "LT+S", "MOON")
    r_sun_moon = np.array(pos_sun_moon)

    # 3. Topocentric vector from surface site to Sun
    r_sun_topo = r_sun_moon - r_site_moon
    dist_km = float(np.linalg.norm(r_sun_topo))

    # 4. Project into local Topocentric Horizon (East-North-Zenith) frame
    u_east, u_north, u_zenith = get_topocentric_basis(lat_deg, lon_deg)

    e_coord = float(np.dot(r_sun_topo, u_east))
    n_coord = float(np.dot(r_sun_topo, u_north))
    z_coord = float(np.dot(r_sun_topo, u_zenith))

    # 5. Solar Elevation (Altitude)
    sin_elev = z_coord / dist_km
    sin_elev = max(-1.0, min(1.0, sin_elev))
    elev_deg = math.degrees(math.asin(sin_elev))

    # 6. Solar Azimuth (0° to 360° from North clockwise through East)
    azimuth_deg = math.degrees(math.atan2(e_coord, n_coord))
    if azimuth_deg < 0:
        azimuth_deg += 360.0

    # 7. Apparent angular radius of the solar disk
    disk_radius_deg = math.degrees(math.asin(SUN_RADIUS_KM / dist_km))

    # 8. Solar irradiance at lunar distance
    irradiance = SOLAR_CONSTANT_1AU * ((AU_KM / dist_km) ** 2)

    # 9. Horizon disk state (smooth spherical Moon baseline)
    if (elev_deg - disk_radius_deg) >= 0.0:
        disk_state = "FULL"
    elif (elev_deg + disk_radius_deg) <= 0.0:
        disk_state = "BELOW_HORIZON"
    else:
        disk_state = "PARTIAL"

    return {
        "utc_time": utc_time_str,
        "ephemeris_time": et,
        "site_lat_deg": lat_deg,
        "site_lon_deg": lon_deg,
        "site_elevation_km": elevation_km,
        "solar_elevation_deg": round(elev_deg, 4),
        "solar_azimuth_deg": round(azimuth_deg, 4),
        "solar_distance_km": round(dist_km, 1),
        "solar_disk_radius_deg": round(disk_radius_deg, 4),
        "solar_irradiance_w_m2": round(irradiance, 2),
        "disk_state": disk_state
    }


def compute_sun_timeseries(
    start_utc: str,
    stop_utc: str,
    step_hours: float,
    lat_deg: float,
    lon_deg: float,
    elevation_km: float = 0.0
) -> list[dict[str, Any]]:
    """
    Computes a continuous solar illumination time series over an observation interval.
    """
    init_spice()
    start_et = spice.str2et(start_utc)
    stop_et = spice.str2et(stop_utc)
    step_seconds = step_hours * 3600.0

    timeseries = []
    current_et = start_et
    while current_et <= stop_et:
        utc_str = spice.et2utc(current_et, "ISOC", 0)
        result = compute_sun_position(utc_str, lat_deg, lon_deg, elevation_km)
        timeseries.append(result)
        current_et += step_seconds

    return timeseries


if __name__ == "__main__":
    print("=" * 70)
    print("LunarSight - NASA SPICE Solar Ephemeris & Illumination Analysis")
    print("=" * 70)

    # Test coordinate: Shackleton Crater Rim (-89.9° Lat, 0.0° Lon)
    site_lat = -89.9
    site_lon = 0.0
    test_date = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    print(f"\nTarget Site: Shackleton Crater Rim ({site_lat}°, {site_lon}°)")
    print(f"Timestamp  : {test_date}\n")

    res = compute_sun_position(test_date, site_lat, site_lon)

    print("Calculated Solar Parameters:")
    print(f"  • Solar Elevation Angle : {res['solar_elevation_deg']:+.3f}°")
    print(f"  • Solar Azimuth Angle   : {res['solar_azimuth_deg']:.2f}° (Compass direction)")
    print(f"  • Distance to Sun       : {res['solar_distance_km']:,.0f} km")
    print(f"  • Apparent Sun Diameter : {res['solar_disk_radius_deg'] * 2:.3f}°")
    print(f"  • Solar Irradiance      : {res['solar_irradiance_w_m2']:.1f} W/m²")
    print(f"  • Solar Disk Visibility : {res['disk_state']}")
    print("\nCalculation completed successfully.")
