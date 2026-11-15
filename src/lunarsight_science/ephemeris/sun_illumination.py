"""Solar illumination calculations for the Lunar South Pole.

Calculates geometric solar elevation, azimuth, and geometric solar-disk
visibility for coordinates on the lunar surface using NASA/JPL SPICE
ephemerides in the designated Mean Earth / Polar Axis (MOON_ME) frame.

IMPORTANT SCIENTIFIC LIMITATIONS:
1. Illumination states (FULL/PARTIAL/DARK) are strictly geometric solar-disk
   horizon classifications relative to an idealized lunar reference sphere.
   They DO NOT represent physical surface illumination percentage, regolith
   albedo, shadows cast by local topography/rocks, or solar power/energy flux.
2. Optional terrain-Sun classifications describe only a sampled,
   piecewise-linear horizon model. They do not certify continuous lunar
   terrain, and MOON_ME frame alignment remains pending kernel validation.
3. Millimeter or flight-grade accuracy is not claimed; calculations reflect
   ephemeris-derived geometric vectors without empirical validation against
   in-situ landing telemetry.
"""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Dict, List, Optional
import math
import numpy as np

try:
    import spiceypy as spice
    HAS_SPICEYPY = True
except ImportError:
    HAS_SPICEYPY = False

from ..config import (
    FRAME_VALIDATION_STATUS,
    LUNAR_REFERENCE_FRAME,
    LUNAR_RADIUS_METRES,
    SPICE_KERNELS_DIR,
    LOLA_DEM_IMAGE_PATH,
    LOLA_DEM_LABEL_PATH,
    COORDINATE_SYSTEM,
    LONGITUDE_CONVENTION,
    DISTANCE_UNITS,
    ELEVATION_UNITS,
)
from ..terrain.lola_dem import (
    LolaDemError,
    LolaDemReader,
    LolaImageError,
    LolaLabelError,
)
from ..terrain.terrain_horizon import (
    TerrainHorizonError,
    TerrainHorizonProfile,
    calculate_terrain_horizon,
    local_site_frame,
    validate_horizon_sampling_parameters,
)
from ..terrain.terrain_sun_visibility import (
    MAX_DISK_WITNESS_SAMPLES,
    TerrainSunVisibility,
    classify_solar_disk_against_terrain,
)

# Standard nominal solar radius in metres (IAU standard: 696,340 km)
SOLAR_RADIUS_METRES = 696340000.0

# Maximum allowed timesteps per calculation request to prevent DoS / memory exhaustion
MAX_ALLOWED_TIMESTEPS = 8760  # e.g., 1 year at 1-hour resolution
MAX_SAFE_LONGITUDE_DEG = float(2**53)
# Keep longitude reduction within the exact-integer range of IEEE-754 doubles.
# Reject sub-resolution steps to prevent timedelta rounding to zero.
MIN_STEP_HOURS = timedelta.resolution.total_seconds() / 3600.0
# Steps cannot exceed the full range representable by Python's datetime values.
MAX_STEP_HOURS = (datetime.max - datetime.min).total_seconds() / 3600.0


@dataclass(frozen=True)
class TerrainSunOptions:
    """Explicit sampling and classification settings for terrain-Sun analysis."""

    max_distance_m: float
    radial_step_m: float
    azimuth_step_deg: float
    required_coverage_distance_m: float
    classification_tolerance_deg: float
    disk_sample_spacing_deg: float
    max_disk_samples: int


def _finite_option(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number.")
    try:
        converted = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be a finite real number.") from exc
    if not math.isfinite(converted):
        raise ValueError(f"{name} must be a finite real number.")
    return converted


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


def _validate_terrain_options(
    use_terrain_horizon: bool,
    terrain_options: TerrainSunOptions | None,
) -> TerrainSunOptions | None:
    if not isinstance(use_terrain_horizon, bool):
        raise ValueError("use_terrain_horizon must be a boolean.")
    if use_terrain_horizon and terrain_options is None:
        raise ValueError(
            "terrain_options is required when use_terrain_horizon is true."
        )
    if not use_terrain_horizon and terrain_options is not None:
        raise ValueError(
            "terrain_options cannot be supplied when use_terrain_horizon is false."
        )
    if terrain_options is None:
        return None
    if not isinstance(terrain_options, TerrainSunOptions):
        raise ValueError("terrain_options must be a TerrainSunOptions instance.")

    max_distance = _finite_option(
        terrain_options.max_distance_m,
        "terrain_options.max_distance_m",
    )
    radial_step = _finite_option(
        terrain_options.radial_step_m,
        "terrain_options.radial_step_m",
    )
    azimuth_step = _finite_option(
        terrain_options.azimuth_step_deg,
        "terrain_options.azimuth_step_deg",
    )
    required_distance = _finite_option(
        terrain_options.required_coverage_distance_m,
        "terrain_options.required_coverage_distance_m",
    )
    tolerance = _finite_option(
        terrain_options.classification_tolerance_deg,
        "terrain_options.classification_tolerance_deg",
    )
    sample_spacing = _finite_option(
        terrain_options.disk_sample_spacing_deg,
        "terrain_options.disk_sample_spacing_deg",
    )
    if (
        isinstance(terrain_options.max_disk_samples, bool)
        or not isinstance(terrain_options.max_disk_samples, Integral)
        or terrain_options.max_disk_samples <= 0
    ):
        raise ValueError(
            "terrain_options.max_disk_samples must be a positive integer."
        )
    if terrain_options.max_disk_samples > MAX_DISK_WITNESS_SAMPLES:
        raise ValueError(
            "terrain_options.max_disk_samples exceeds the operational limit "
            f"of {MAX_DISK_WITNESS_SAMPLES}."
        )
    if required_distance <= 0.0:
        raise ValueError(
            "terrain_options.required_coverage_distance_m must be positive."
        )
    if required_distance > max_distance:
        raise ValueError(
            "terrain_options.required_coverage_distance_m cannot exceed "
            "terrain_options.max_distance_m."
        )
    if not 0.0 < tolerance < 180.0:
        raise ValueError(
            "terrain_options.classification_tolerance_deg must be in (0, 180)."
        )
    if not 0.0 < sample_spacing <= 180.0:
        raise ValueError(
            "terrain_options.disk_sample_spacing_deg must be in (0, 180]."
        )

    validate_horizon_sampling_parameters(
        max_distance,
        radial_step,
        azimuth_step,
    )
    return TerrainSunOptions(
        max_distance_m=max_distance,
        radial_step_m=radial_step,
        azimuth_step_deg=azimuth_step,
        required_coverage_distance_m=required_distance,
        classification_tolerance_deg=tolerance,
        disk_sample_spacing_deg=sample_spacing,
        max_disk_samples=int(terrain_options.max_disk_samples),
    )


def _terrain_data_error(code: str, message: str) -> Dict[str, Any]:
    return {
        "status": "TERRAIN_DATA_ERROR",
        "error": message,
        "details": {"code": code},
        "data": None,
    }


class _SunCalculationResponse(Exception):
    def __init__(self, response: Dict[str, Any]) -> None:
        self.response = response


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

    Rejects naive timestamps or non-UTC offsets.
    """
    if not isinstance(timestamp_str, str):
        return None
    raw = timestamp_str.strip()
    if not (raw.endswith("Z") or raw.endswith("+00:00") or raw.endswith("-00:00")):
        return None  # Rejects naive or non-UTC timestamps

    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
            return None
        return dt
    except Exception:
        return None


def calculate_sun_illumination(
    latitude_deg: float,
    longitude_deg: float,
    start_time_utc: str,
    end_time_utc: str,
    step_hours: float = 1.0,
    use_terrain_horizon: bool = False,
    *,
    terrain_options: TerrainSunOptions | None = None,
) -> Dict[str, Any]:
    """Calculates geometric solar position and solar-disk horizon classification.

    Coordinates and Units:
    - latitude_deg: Planetocentric latitude (-90.0 at South Pole to +90.0 at North Pole).
    - longitude_deg: East-positive longitude (0.0 to 360.0 degrees).
    - elevation / distances: Metres.
    - Reference frame: MOON_ME (Mean Earth / Polar Axis).
    - Exact Pole Azimuth Convention: At the exact pole (latitude = -90.0 deg), physical
      North is undefined. By explicit coordinate convention, azimuth is measured
      clockwise from the 0.0 deg Selenographic Meridian (direction towards Mean Earth).

    Scientific & Horizon Clarifications:
    - Illumination states (FULL, PARTIAL, DARK) represent the geometric visibility of the
      solar disk relative to the local horizontal tangent plane on the mean lunar sphere.
      They DO NOT indicate actual illuminated surface area, surface albedo, or solar power.
    - Optional terrain classifications are separate from geometric results and describe
      only the sampled piecewise-linear horizon model. They do not certify continuous
      lunar terrain; MOON_ME frame alignment remains pending kernel validation.
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

    try:
        validated_terrain_options = _validate_terrain_options(
            use_terrain_horizon,
            terrain_options,
        )
    except ValueError as exc:
        return {
            "status": "INVALID_INPUT",
            "error": str(exc),
            "data": None,
        }

    norm_lon_deg = longitude_value % 360.0

    # 2. Validate UTC Timestamps with Explicit Timezone Requirement
    t_start = parse_utc_iso_string(start_time_utc)
    if t_start is None:
        return {
            "status": "INVALID_INPUT",
            "error": f"start_time_utc '{start_time_utc}' is invalid. Must be an ISO 8601 string with an explicit UTC timezone indicator (e.g. '2027-01-01T00:00:00Z').",
            "data": None
        }

    t_end = parse_utc_iso_string(end_time_utc)
    if t_end is None:
        return {
            "status": "INVALID_INPUT",
            "error": f"end_time_utc '{end_time_utc}' is invalid. Must be an ISO 8601 string with an explicit UTC timezone indicator (e.g. '2027-01-02T00:00:00Z').",
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

    try:
        kernel_check = check_required_kernels(SPICE_KERNELS_DIR)
    except Exception:
        return {
            "status": "CALCULATION_ERROR",
            "error": "SPICE kernel preflight failed.",
            "details": {"code": "SPICE_KERNEL_PREFLIGHT_ERROR"},
            "data": None,
        }
    if not kernel_check["all_present"]:
        if use_terrain_horizon:
            return {
                "status": "MISSING_KERNELS",
                "error": (
                    "Required SPICE kernels are unavailable. Terrain-aware Sun "
                    "calculations require complete MOON_ME kernel coverage."
                ),
                "details": {
                    "found_files": kernel_check["found_files"],
                    "missing_categories": kernel_check["missing_categories"],
                },
                "data": None,
            }
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
        "Terrain horizon analysis using DEM data is NOT_IMPLEMENTED in this module. "
        "Reported values represent unmasked geometric solar-disk elevation relative to the mean lunar sphere."
    )
    if validated_terrain_options is not None:
        terrain_note = (
            "The legacy terrain_shadow_analysis marker remains NOT_IMPLEMENTED "
            "and does not summarize the separate terrain_sun_visibility results. "
            "Those results classify the solar disk against a sampled "
            "piecewise-linear horizon only and do not certify continuous terrain."
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

        # Verify that the MOON_ME reference frame is recognized in the loaded SPICE kernel pool
        frame_code = spice.namfrm(LUNAR_REFERENCE_FRAME)
        if frame_code == 0:
            if use_terrain_horizon:
                raise _SunCalculationResponse({
                    "status": "FRAME_UNSUPPORTED",
                    "error": (
                        f"The loaded kernels do not support reference frame "
                        f"'{LUNAR_REFERENCE_FRAME}'."
                    ),
                    "details": {"code": "FRAME_UNSUPPORTED"},
                    "data": None,
                })
            raise _SunCalculationResponse({
                "status": "FRAME_UNSUPPORTED",
                "error": f"The loaded kernels do not support reference frame '{LUNAR_REFERENCE_FRAME}'. Ensure the appropriate frame kernel and binary PCK are present.",
                "data": None
            })

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
        terrain_profile: TerrainHorizonProfile | None = None
        terrain_site_unit: np.ndarray | None = None
        terrain_north_u: np.ndarray | None = None
        terrain_east_u: np.ndarray | None = None
        terrain_site_vec_m: np.ndarray | None = None

        if validated_terrain_options is not None:
            if not LOLA_DEM_LABEL_PATH.is_file():
                raise _SunCalculationResponse(_terrain_data_error(
                    "MISSING_DEM_LABEL",
                    "The configured LOLA DEM label is unavailable.",
                ))
            if not LOLA_DEM_IMAGE_PATH.is_file():
                raise _SunCalculationResponse(_terrain_data_error(
                    "MISSING_DEM_IMAGE",
                    "The configured LOLA DEM image is unavailable.",
                ))
            try:
                with LolaDemReader() as dem:
                    terrain_profile = calculate_terrain_horizon(
                        dem,
                        latitude_deg,
                        None if latitude_deg == -90.0 else norm_lon_deg,
                        max_distance_m=validated_terrain_options.max_distance_m,
                        radial_step_m=validated_terrain_options.radial_step_m,
                        azimuth_step_deg=validated_terrain_options.azimuth_step_deg,
                    )
            except LolaLabelError:
                raise _SunCalculationResponse(_terrain_data_error(
                    "DEM_LABEL_ERROR",
                    "The configured LOLA DEM label is invalid or unreadable.",
                ))
            except LolaImageError:
                raise _SunCalculationResponse(_terrain_data_error(
                    "DEM_IMAGE_ERROR",
                    "The configured LOLA DEM image is invalid or unreadable.",
                ))
            except TerrainHorizonError:
                raise _SunCalculationResponse(_terrain_data_error(
                    "INVALID_SITE_SAMPLE",
                    "The LOLA DEM does not provide a valid elevation at the site.",
                ))
            except LolaDemError:
                raise _SunCalculationResponse(_terrain_data_error(
                    "DEM_READ_ERROR",
                    "The LOLA DEM could not be read while building the horizon profile.",
                ))
            except ValueError:
                raise _SunCalculationResponse(_terrain_data_error(
                    "TERRAIN_PROFILE_ERROR",
                    "The terrain-horizon profile could not be calculated.",
                ))

            (
                terrain_site_up,
                terrain_north,
                terrain_east,
            ) = local_site_frame(
                terrain_profile.site_latitude_deg,
                terrain_profile.site_longitude_deg,
            )
            terrain_site_unit = np.asarray(terrain_site_up, dtype=float)
            terrain_north_u = np.asarray(terrain_north, dtype=float)
            terrain_east_u = np.asarray(terrain_east, dtype=float)
            terrain_site_radius_m = (
                LUNAR_RADIUS_METRES + terrain_profile.site_elevation_m
            )
            terrain_site_vec_m = terrain_site_radius_m * terrain_site_unit

        current_t = t_start

        while current_t <= t_end:
            iso_utc = current_t.strftime("%Y-%m-%dT%H:%M:%SZ")
            et = spice.str2et(iso_utc)

            # Retrieve Sun position relative to Moon center in MOON_ME (km -> metres)
            # Note: Evaluated using light-time and stellar aberration ('LT+S') at Moon center,
            # with topocentric parallax computed geometrically via site_vec_m.
            sun_pos_km, _ = spice.spkpos("SUN", et, LUNAR_REFERENCE_FRAME, "LT+S", "MOON")
            sun_pos_m = np.array(sun_pos_km, dtype=float) * 1000.0

            # Topocentric vector from landing site to Sun
            topo_vec_m = sun_pos_m - site_vec_m
            dist_m = float(np.linalg.norm(topo_vec_m))

            # Solar elevation angle above spherical tangent horizon
            sin_elev = float(np.dot(topo_vec_m, zenith_u) / dist_m)
            sin_elev = max(-1.0, min(1.0, sin_elev))
            elev_deg = math.degrees(math.asin(sin_elev))

            # Azimuth calculation
            if is_exact_pole:
                # Explicit convention at the pole: clockwise from 0° Selenographic Meridian
                u_ref = np.array([1.0, 0.0, 0.0], dtype=float)
                u_ortho = np.array([0.0, 1.0, 0.0], dtype=float)
                az_deg = math.degrees(math.atan2(np.dot(topo_vec_m, u_ortho), np.dot(topo_vec_m, u_ref))) % 360.0
            else:
                east_u = np.array([-math.sin(lon_rad), math.cos(lon_rad), 0.0], dtype=float)
                north_u = np.cross(zenith_u, east_u)
                az_deg = math.degrees(math.atan2(np.dot(topo_vec_m, east_u), np.dot(topo_vec_m, north_u))) % 360.0

            # Solar angular radius
            sin_ang_rad = min(1.0, SOLAR_RADIUS_METRES / dist_m)
            sun_angular_radius_deg = math.degrees(math.asin(sin_ang_rad))

            # Geometric solar-disk horizon classification
            if elev_deg > sun_angular_radius_deg:
                disk_class = "FULL"
                is_illuminated = True
            elif elev_deg >= -sun_angular_radius_deg:
                disk_class = "PARTIAL"
                is_illuminated = True
            else:
                disk_class = "DARK"
                is_illuminated = False

            timeline_point = {
                "timestamp_utc": iso_utc,
                "sun_elevation_deg": round(elev_deg, 4),
                "sun_azimuth_deg": round(az_deg, 4),
                "sun_distance_m": round(dist_m, 2),
                "sun_angular_radius_deg": round(sun_angular_radius_deg, 4),
                "geometric_solar_disk_classification": disk_class,
                "is_geometrically_illuminated": is_illuminated
            }

            if (
                validated_terrain_options is not None
                and terrain_profile is not None
                and terrain_site_unit is not None
                and terrain_north_u is not None
                and terrain_east_u is not None
                and terrain_site_vec_m is not None
            ):
                terrain_topo_vec_m = sun_pos_m - terrain_site_vec_m
                terrain_dist_m = float(np.linalg.norm(terrain_topo_vec_m))
                terrain_sin_elev = float(
                    np.dot(terrain_topo_vec_m, terrain_site_unit)
                    / terrain_dist_m
                )
                terrain_sin_elev = max(-1.0, min(1.0, terrain_sin_elev))
                terrain_elev_deg = math.degrees(math.asin(terrain_sin_elev))
                terrain_az_deg = math.degrees(
                    math.atan2(
                        np.dot(terrain_topo_vec_m, terrain_east_u),
                        np.dot(terrain_topo_vec_m, terrain_north_u),
                    )
                ) % 360.0
                terrain_sun_angular_radius_deg = math.degrees(
                    math.asin(
                        min(1.0, SOLAR_RADIUS_METRES / terrain_dist_m)
                    )
                )
                terrain_visibility: TerrainSunVisibility = (
                    classify_solar_disk_against_terrain(
                        terrain_elev_deg,
                        terrain_az_deg,
                        terrain_sun_angular_radius_deg,
                        terrain_profile,
                        required_coverage_distance_m=(
                            validated_terrain_options.required_coverage_distance_m
                        ),
                        classification_tolerance_deg=(
                            validated_terrain_options.classification_tolerance_deg
                        ),
                        disk_sample_spacing_deg=(
                            validated_terrain_options.disk_sample_spacing_deg
                        ),
                        max_disk_samples=(
                            validated_terrain_options.max_disk_samples
                        ),
                    )
                )
                timeline_point["terrain_sun_visibility"] = {
                    "sun_elevation_deg": round(terrain_elev_deg, 4),
                    "sun_azimuth_deg": round(terrain_az_deg, 4),
                    "sun_distance_m": round(terrain_dist_m, 2),
                    "sun_angular_radius_deg": round(
                        terrain_sun_angular_radius_deg,
                        4,
                    ),
                    "classification": terrain_visibility.classification,
                    "reason": terrain_visibility.reason,
                    "required_coverage_distance_m": (
                        terrain_visibility.required_coverage_distance_m
                    ),
                    "azimuth_footprint_half_width_deg": (
                        terrain_visibility.azimuth_footprint_half_width_deg
                    ),
                    "disk_witness_samples": (
                        terrain_visibility.disk_witness_samples
                    ),
                    "visible_margin_deg": terrain_visibility.visible_margin_deg,
                    "obstructed_margin_deg": (
                        terrain_visibility.obstructed_margin_deg
                    ),
                    "classification_basis": (
                        terrain_visibility.classification_basis
                    ),
                    "physical_terrain_visibility_certified": False,
                }

            timeline.append(timeline_point)

            if delta_step > t_end - current_t:
                break
            current_t += delta_step

    except _SunCalculationResponse as response:
        calculation_result = response.response
    except Exception as exc:
        if use_terrain_horizon:
            calculation_result = {
                "status": "CALCULATION_ERROR",
                "error": (
                    "SPICE or terrain-aware Sun calculation failed; no "
                    "geometric-only fallback was produced."
                ),
                "details": {"code": "TERRAIN_SUN_CALCULATION_ERROR"},
                "data": None,
            }
        else:
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

    elevations = [pt["sun_elevation_deg"] for pt in timeline]
    illuminated_count = sum(1 for pt in timeline if pt["is_geometrically_illuminated"])
    total_steps = len(timeline)

    summary = {
        "total_timesteps": total_steps,
        "mean_solar_elevation_deg": round(float(np.mean(elevations)), 4) if elevations else None,
        "max_solar_elevation_deg": round(float(np.max(elevations)), 4) if elevations else None,
        "min_solar_elevation_deg": round(float(np.min(elevations)), 4) if elevations else None,
        "geometric_illumination_fraction": round(illuminated_count / total_steps, 4) if total_steps > 0 else 0.0,
        "terrain_shadow_analysis": terrain_analysis_status,
        "terrain_shadow_notes": terrain_note,
        "classification_definition": "FULL/PARTIAL/DARK classifies geometric solar-disk elevation relative to the mean spherical horizon. It does not measure physical surface illumination area or solar power flux."
    }
    if terrain_profile is not None:
        summary["terrain_horizon_profile"] = {
            "site_elevation_m": terrain_profile.site_elevation_m,
            "max_distance_m": terrain_profile.max_distance_m,
            "radial_step_m": terrain_profile.radial_step_m,
            "azimuth_step_deg": terrain_profile.azimuth_step_deg,
            "ray_count": len(terrain_profile.rays),
            "complete_ray_count": sum(
                1 for ray in terrain_profile.rays if ray.valid and ray.complete
            ),
            "incomplete_ray_count": sum(
                1 for ray in terrain_profile.rays if not ray.valid or not ray.complete
            ),
            "classification_basis": "SAMPLED_PIECEWISE_LINEAR_HORIZON",
            "physical_terrain_visibility_certified": False,
            "frame_validation_status": FRAME_VALIDATION_STATUS,
            "scientific_note": (
                "Terrain classifications describe only the sampled profile; "
                "continuous terrain visibility is not certified, and MOON_ME "
                "frame alignment remains pending kernel validation."
            ),
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
