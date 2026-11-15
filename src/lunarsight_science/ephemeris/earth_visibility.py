"""Earth visibility and Direct-to-Earth (DTE) communication geometry.

Calculates geometric Earth elevation, azimuth, distance, angular radius,
and line-of-sight visibility for coordinates on the lunar surface using
NASA/JPL SPICE ephemerides in the designated Mean Earth / Polar Axis (MOON_ME) frame.

IMPORTANT SCIENTIFIC ASSUMPTIONS & LIMITATIONS:
1. Visibility Classification:
   FULL/PARTIAL/OCCULTED classifies geometric visibility of the Earth disk relative
   to the mean lunar reference sphere. It DOES NOT account for local terrain
   obstructions, crater walls, multipath interference, antenna gain, or RF link budget.
2. Terrain Obstruction:
   Terrain horizon analysis using DEM data is NOT YET IMPLEMENTED.
3. Topocentric Observer & Aberration Approximation:
   Subtracting the landing-site body-fixed vector from the Moon-centre Earth position vector
   (v_topo = r_earth/moon - r_site/moon) is a geometric parallax approximation. It evaluates
   stellar aberration and light-time ('LT+S') at the Moon's center of mass rather than
   providing a fully site-specific, topocentric light-time/aberration solution.
4. Earth Angular Radius Approximation:
   The Earth equatorial radius (6,378,137.0 m) is used as a spherical upper-bound
   approximation. Because of Earth's oblateness (polar radius ~6,356,752 m), the true
   apparent angular radius varies by up to ~0.33% depending on sub-lunar latitude.
5. South Pole Azimuth Convention:
   At the exact pole (latitude = -90.0 deg), physical North is undefined. The code uses
   MOON_ME +X as the 0 deg azimuth reference and +Y as the 90 deg reference. This is an
   assumed coordinate convention only: the alignment of +X with the 0 deg Selenographic
   Meridian or Mean Earth direction has not been physically verified. Verification is
   pending availability of the relevant frame kernel and validation of its transformation.
6. Frame Support Limitation:
   spice.namfrm(LUNAR_REFERENCE_FRAME) only verifies that the frame name string is
   recognized by SPICE. It DOES NOT validate kernel coverage, kernel data integrity,
   or the physical accuracy of the frame transformation for the requested time range.
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import math
import numpy as np

try:
    import spiceypy as spice
    HAS_SPICEYPY = True
except ImportError:
    HAS_SPICEYPY = False

from ..config import (
    LUNAR_REFERENCE_FRAME,
    LUNAR_RADIUS_METRES,
    SPICE_KERNELS_DIR,
    COORDINATE_SYSTEM,
    LONGITUDE_CONVENTION,
    DISTANCE_UNITS,
    ELEVATION_UNITS,
)

# Standard nominal Earth equatorial radius in metres (IAU / WGS84 standard: 6,378.137 km)
# NOTE: Used as a spherical upper-bound approximation for apparent angular radius.
EARTH_EQUATORIAL_RADIUS_METRES = 6378137.0

# Maximum allowed timesteps per calculation request to prevent DoS / memory exhaustion
MAX_ALLOWED_TIMESTEPS = 8760  # e.g., 1 year at 1-hour resolution
MAX_SAFE_LONGITUDE_DEG = float(2**53)
# Keep longitude reduction within the exact-integer range of IEEE-754 doubles.
# Reject sub-resolution steps to prevent timedelta rounding to zero.
MIN_STEP_HOURS = timedelta.resolution.total_seconds() / 3600.0
# Steps cannot exceed the full range representable by Python's datetime values.
MAX_STEP_HOURS = (datetime.max - datetime.min).total_seconds() / 3600.0


def _finite_science_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        converted = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(converted):
        return None
    return converted


def check_required_kernels(kernel_dir: Path) -> Dict[str, Any]:
    """Inspects the kernel directory and identifies available and missing SPICE kernels.

    Distinguishes:
    - LSK: Leapseconds (*.tls)
    - PCK (Text): Planetary physical constants (*.tpc)
    - SPK: Planetary Ephemeris (*.bsp)
    - BPC: Binary Lunar PCK (*.bpc) for high-precision lunar physical libration
    - FK: Frame Kernel (*.tf) defining frame relationships for MOON_ME

    Note: Frame kernels (*.tf) and binary PCKs (*.bpc) are distinct requirements
    and neither replaces the other.
    """
    if not kernel_dir.exists() or not kernel_dir.is_dir():
        return {
            "all_present": False,
            "kernel_dir": str(kernel_dir),
            "found_files": [],
            "missing_categories": [
                "LSK (Leapseconds .tls)",
                "PCK_TEXT (Planetary Constants .tpc)",
                "SPK (Ephemeris .bsp)",
                "BPC (Binary Lunar PCK .bpc)",
                "FK (Frame Kernel .tf)"
            ]
        }

    found_files = [p.name for p in kernel_dir.iterdir() if p.is_file()]

    has_lsk = any(f.lower().endswith(".tls") for f in found_files)
    has_pck = any(f.lower().endswith(".tpc") for f in found_files)
    has_spk = any(f.lower().endswith(".bsp") for f in found_files)
    has_bpc = any(f.lower().endswith(".bpc") for f in found_files)
    has_fk = any(f.lower().endswith(".tf") for f in found_files)

    missing = []
    if not has_lsk:
        missing.append("LSK (Leapseconds .tls, e.g., naif0012.tls)")
    if not has_pck:
        missing.append("PCK_TEXT (Planetary Constants .tpc, e.g., pck00010.tpc)")
    if not has_spk:
        missing.append("SPK (Ephemeris .bsp, e.g., de421.bsp or de440.bsp)")
    if not has_bpc:
        missing.append("BPC (Binary Lunar PCK .bpc, e.g., moon_pa_de421_1900-2050.bpc or moon_pa_de440_200625.bpc)")
    if not has_fk:
        missing.append("FK (Frame Kernel .tf, e.g., moon_080317.tf)")

    return {
        "all_present": (len(missing) == 0),
        "kernel_dir": str(kernel_dir),
        "found_files": found_files,
        "missing_categories": missing
    }


def parse_utc_iso_string(timestamp_str: str) -> Optional[datetime]:
    """Parses an ISO 8601 string and strictly verifies that an explicit UTC timezone is present.

    Rejects naive timestamps and '-00:00' (indeterminate UTC offset).
    Accepts only explicit, known UTC indicators: 'Z' or '+00:00'.
    """
    if not isinstance(timestamp_str, str):
        return None
    raw = timestamp_str.strip()

    # Explicitly reject indeterminate UTC offset '-00:00'
    if raw.endswith("-00:00"):
        return None

    # Accept only explicit 'Z' or '+00:00'
    if not (raw.endswith("Z") or raw.endswith("+00:00")):
        return None

    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
            return None
        return dt
    except Exception:
        return None


def classify_earth_disk_visibility(
    elevation_deg: float,
    angular_radius_deg: float
) -> Tuple[str, bool]:
    """Classifies the geometric visibility of the Earth disk relative to the mean spherical horizon.

    Parameters:
        elevation_deg: Apparent elevation angle of Earth's center above the spherical horizon in degrees.
        angular_radius_deg: Apparent angular radius of the Earth disk in degrees.

    Returns:
        Tuple[str, bool]: (classification, is_visible)
            - ("FULL", True): Earth disk is entirely above the geometric horizon (elev > radius).
            - ("PARTIAL", True): Earth disk intersects the geometric horizon (-radius <= elev <= radius).
            - ("OCCULTED", False): Earth disk is entirely below the geometric horizon (elev < -radius).
    """
    if elevation_deg > angular_radius_deg:
        return "FULL", True
    elif elevation_deg >= -angular_radius_deg:
        return "PARTIAL", True
    else:
        return "OCCULTED", False


def calculate_earth_visibility(
    latitude_deg: float,
    longitude_deg: float,
    start_time_utc: str,
    end_time_utc: str,
    step_hours: float = 1.0,
    use_terrain_horizon: bool = False
) -> Dict[str, Any]:
    """Calculates geometric Earth position and Direct-to-Earth (DTE) visibility status.

    Coordinates and Units:
    - latitude_deg: Planetocentric latitude (-90.0 at South Pole to +90.0 at North Pole).
    - longitude_deg: East-positive longitude (0.0 to 360.0 degrees).
    - elevation / distances: Metres.
    - Reference frame: MOON_ME (Mean Earth / Polar Axis).

    Scientific & Horizon Clarifications:
    - Visibility states (FULL, PARTIAL, OCCULTED) represent the geometric visibility of the
      Earth disk relative to the local horizontal tangent plane on the mean lunar sphere.
      They DO NOT account for local terrain masking, crater rims, or RF propagation effects.
    - Terrain horizon masking is marked NOT_IMPLEMENTED; no terrain-corrected visibility
      is computed or claimed.
    - If required SPICE kernels are unavailable, returns status="MISSING_KERNELS".

    Returns:
        Dict[str, Any]: Structured calculation results matching the scientific interface.
    """
    # 1. Strict Input Validation (Reject NaN, Inf, Out-of-bounds)
    latitude_value = _finite_science_number(latitude_deg)
    if latitude_value is None:
        return {
            "status": "INVALID_INPUT",
            "error": "Latitude must be a valid, finite real number.",
            "data": None
        }

    if not (-90.0 <= latitude_value <= 90.0):
        return {
            "status": "INVALID_INPUT",
            "error": f"Latitude {latitude_deg} is out of bounds. Must be between -90.0 and +90.0 degrees ({COORDINATE_SYSTEM}).",
            "data": None
        }

    longitude_value = _finite_science_number(longitude_deg)
    if longitude_value is None:
        return {
            "status": "INVALID_INPUT",
            "error": "Longitude must be a valid, finite real number.",
            "data": None
        }

    if abs(longitude_deg) > MAX_SAFE_LONGITUDE_DEG:
        return {
            "status": "INVALID_INPUT",
            "error": (
                "Longitude magnitude exceeds the safe range for degree "
                "normalization."
            ),
            "data": None
        }

    step_hours_value = _finite_science_number(step_hours)
    if step_hours_value is None or step_hours_value <= 0.0:
        return {
            "status": "INVALID_INPUT",
            "error": "step_hours must be a finite positive number.",
            "data": None
        }
    if step_hours_value < MIN_STEP_HOURS:
        return {
            "status": "INVALID_INPUT",
            "error": (
                "step_hours must be at least one microsecond to advance "
                "the UTC timeline safely."
            ),
            "data": None
        }
    if step_hours_value > MAX_STEP_HOURS:
        return {
            "status": "INVALID_INPUT",
            "error": "step_hours exceeds the supported datetime range.",
            "data": None
        }

    norm_lon_deg = longitude_value % 360.0

    # 2. Validate UTC Timestamps (Rejects naive and '-00:00' timestamps)
    t_start = parse_utc_iso_string(start_time_utc)
    if t_start is None:
        return {
            "status": "INVALID_INPUT",
            "error": f"start_time_utc '{start_time_utc}' is invalid. Must be an ISO 8601 string with an explicit known UTC timezone ('Z' or '+00:00').",
            "data": None
        }

    t_end = parse_utc_iso_string(end_time_utc)
    if t_end is None:
        return {
            "status": "INVALID_INPUT",
            "error": f"end_time_utc '{end_time_utc}' is invalid. Must be an ISO 8601 string with an explicit known UTC timezone ('Z' or '+00:00').",
            "data": None
        }

    if t_end < t_start:
        return {
            "status": "INVALID_INPUT",
            "error": "end_time_utc cannot be earlier than start_time_utc.",
            "data": None
        }

    delta_step = timedelta(hours=step_hours_value)
    duration = t_end - t_start
    duration_microseconds = (
        (duration.days * 86400 + duration.seconds) * 1_000_000
        + duration.microseconds
    )
    step_microseconds = (
        (delta_step.days * 86400 + delta_step.seconds) * 1_000_000
        + delta_step.microseconds
    )
    estimated_steps = duration_microseconds // step_microseconds + 1
    if estimated_steps > MAX_ALLOWED_TIMESTEPS:
        return {
            "status": "INVALID_INPUT",
            "error": f"Requested duration results in {estimated_steps} timesteps, exceeding the safety limit of {MAX_ALLOWED_TIMESTEPS}. Increase step_hours or reduce the time window.",
            "data": None
        }

    # 3. Check SpiceyPy and Kernel Availability
    if not HAS_SPICEYPY:
        return {
            "status": "DEPENDENCY_ERROR",
            "error": "SpiceyPy library is not available in the current Python environment.",
            "data": None
        }

    kernel_check = check_required_kernels(SPICE_KERNELS_DIR)
    if not kernel_check["all_present"]:
        return {
            "status": "MISSING_KERNELS",
            "error": (
                f"Required SPICE kernels are not present in '{SPICE_KERNELS_DIR}'. "
                f"Missing categories: {', '.join(kernel_check['missing_categories'])}. "
                "High-precision calculations in MOON_ME require complete NAIF kernel coverage "
                "(LSK, text PCK, ephemeris SPK, binary lunar PCK, and frame kernel)."
            ),
            "details": {
                "kernel_dir": str(SPICE_KERNELS_DIR),
                "found_files": kernel_check["found_files"],
                "missing_categories": kernel_check["missing_categories"]
            },
            "data": None
        }

    # 4. Terrain Handling Clarification
    terrain_analysis_status = "NOT_IMPLEMENTED"
    terrain_note = (
        "Terrain horizon obstruction analysis using DEM data is NOT_IMPLEMENTED in this module. "
        "Reported values represent unmasked geometric Earth-disk elevation relative to the mean lunar sphere."
    )

    # 5. SPICE Ephemeris Topocentric Calculation
    loaded_kernels = []
    timeline: List[Dict[str, Any]] = []
    calculation_result: Dict[str, Any] | None = None

    try:
        # Furnish kernels
        for f in SPICE_KERNELS_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in [".tls", ".tpc", ".bsp", ".bpc", ".tf"]:
                spice.furnsh(str(f))
                loaded_kernels.append(f.name)

        # Verify that the MOON_ME reference frame is registered in the SPICE frame subsystem.
        # NOTE: namfrm() verifies name registration only; it does not validate kernel epoch coverage.
        frame_code = spice.namfrm(LUNAR_REFERENCE_FRAME)
        if frame_code == 0:
            return {
                "status": "FRAME_UNSUPPORTED",
                "error": f"The loaded kernels do not support reference frame '{LUNAR_REFERENCE_FRAME}'. Ensure the appropriate frame kernel and binary PCK are present.",
                "data": None
            }

        lat_rad = math.radians(latitude_value)
        lon_rad = math.radians(norm_lon_deg)

        # Site position in MOON_ME Cartesian coordinates (metres)
        site_x = LUNAR_RADIUS_METRES * math.cos(lat_rad) * math.cos(lon_rad)
        site_y = LUNAR_RADIUS_METRES * math.cos(lat_rad) * math.sin(lon_rad)
        site_z = LUNAR_RADIUS_METRES * math.sin(lat_rad)
        site_vec_m = np.array([site_x, site_y, site_z], dtype=float)

        zenith_u = np.array([
            math.cos(lat_rad) * math.cos(lon_rad),
            math.cos(lat_rad) * math.sin(lon_rad),
            math.sin(lat_rad)
        ], dtype=float)

        is_exact_pole = abs(latitude_value) >= 89.9999

        current_t = t_start

        while current_t <= t_end:
            iso_utc = current_t.strftime("%Y-%m-%dT%H:%M:%SZ")
            et = spice.str2et(iso_utc)

            # Retrieve Earth position relative to Moon center in MOON_ME (km -> metres)
            # NOTE: Evaluated using light-time and stellar aberration ('LT+S') at Moon center.
            # Topocentric parallax is computed geometrically by subtracting site_vec_m.
            earth_pos_km, _ = spice.spkpos("EARTH", et, LUNAR_REFERENCE_FRAME, "LT+S", "MOON")
            earth_pos_m = np.array(earth_pos_km, dtype=float) * 1000.0

            # Topocentric vector from landing site to Earth
            topo_vec_m = earth_pos_m - site_vec_m
            dist_m = float(np.linalg.norm(topo_vec_m))

            # Earth elevation angle above spherical tangent horizon
            sin_elev = float(np.dot(topo_vec_m, zenith_u) / dist_m)
            sin_elev = max(-1.0, min(1.0, sin_elev))
            elev_deg = math.degrees(math.asin(sin_elev))

            # Azimuth calculation
            if is_exact_pole:
                # Assumed output convention pending verification of the MOON_ME frame orientation.
                u_ref = np.array([1.0, 0.0, 0.0], dtype=float)
                u_ortho = np.array([0.0, 1.0, 0.0], dtype=float)
                az_deg = math.degrees(math.atan2(np.dot(topo_vec_m, u_ortho), np.dot(topo_vec_m, u_ref))) % 360.0
            else:
                east_u = np.array([-math.sin(lon_rad), math.cos(lon_rad), 0.0], dtype=float)
                north_u = np.cross(zenith_u, east_u)
                az_deg = math.degrees(math.atan2(np.dot(topo_vec_m, east_u), np.dot(topo_vec_m, north_u))) % 360.0

            # Earth apparent angular radius (using equatorial radius spherical approximation)
            sin_ang_rad = min(1.0, EARTH_EQUATORIAL_RADIUS_METRES / dist_m)
            earth_angular_radius_deg = math.degrees(math.asin(sin_ang_rad))

            # Geometric Earth-disk visibility classification via helper
            disk_class, is_visible = classify_earth_disk_visibility(elev_deg, earth_angular_radius_deg)

            timeline.append({
                "timestamp_utc": iso_utc,
                "earth_elevation_deg": round(elev_deg, 4),
                "earth_azimuth_deg": round(az_deg, 4),
                "earth_distance_m": round(dist_m, 2),
                "earth_angular_radius_deg": round(earth_angular_radius_deg, 4),
                "geometric_earth_disk_classification": disk_class,
                "is_earth_visible": is_visible
            })

            if delta_step > t_end - current_t:
                break
            current_t += delta_step

    except Exception as exc:
        calculation_result = {
            "status": "CALCULATION_ERROR",
            "error": f"SPICE calculation error: {str(exc)}",
            "data": None
        }
    finally:
        try:
            spice.kclear()
        except Exception:
            if calculation_result is None:
                calculation_result = {
                    "status": "CALCULATION_ERROR",
                    "error": "SPICE kernel cleanup failed.",
                    "details": {"code": "SPICE_CLEANUP_ERROR"},
                    "data": None,
                }

    if calculation_result is not None:
        return calculation_result

    elevations = [pt["earth_elevation_deg"] for pt in timeline]
    visible_count = sum(1 for pt in timeline if pt["is_earth_visible"])
    total_steps = len(timeline)

    visibility_fraction = round(visible_count / total_steps, 4) if total_steps > 0 else 0.0
    if visibility_fraction >= 0.999:
        los_status = "CONTINUOUS"
    elif visibility_fraction > 0.0:
        los_status = "INTERMITTENT"
    else:
        los_status = "NO_DIRECT_LINE_OF_SIGHT"

    summary = {
        "total_timesteps": total_steps,
        "mean_earth_elevation_deg": round(float(np.mean(elevations)), 4) if elevations else None,
        "max_earth_elevation_deg": round(float(np.max(elevations)), 4) if elevations else None,
        "min_earth_elevation_deg": round(float(np.min(elevations)), 4) if elevations else None,
        "geometric_visibility_fraction": visibility_fraction,
        "line_of_sight_status": los_status,
        "terrain_obstruction_analysis": terrain_analysis_status,
        "terrain_obstruction_notes": terrain_note,
        "classification_definition": "FULL/PARTIAL/OCCULTED classifies geometric Earth-disk elevation relative to the mean spherical horizon. It does not account for terrain topography, local relief, or RF link margins."
    }

    return {
        "status": "SUCCESS",
        "site": {
            "latitude_deg": latitude_deg,
            "longitude_deg": norm_lon_deg,
            "coordinate_system": COORDINATE_SYSTEM,
            "longitude_convention": LONGITUDE_CONVENTION,
            "radius_m": LUNAR_RADIUS_METRES,
            "distance_units": DISTANCE_UNITS,
            "elevation_units": ELEVATION_UNITS
        },
        "reference_frame": LUNAR_REFERENCE_FRAME,
        "kernels_used": loaded_kernels,
        "time_range": {
            "start_time_utc": start_time_utc,
            "end_time_utc": end_time_utc,
            "step_hours": step_hours
        },
        "summary": summary,
        "timeline": timeline
    }
