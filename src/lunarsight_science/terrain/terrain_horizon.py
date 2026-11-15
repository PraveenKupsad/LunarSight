"""Local terrain-horizon profiles sampled from a LOLA DEM.

Point sampling at 20 m spacing cannot guarantee detection of every narrow
ridge, especially when a feature falls between radial or azimuth samples.
The one-million-sample ceiling below is an operational safety limit, not a
scientific sampling recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real

from ..config import LUNAR_RADIUS_METRES
from .lola_dem import (
    ElevationSample,
    InterpolationUnavailableError,
    LolaDataIntegrityError,
    LolaDemError,
    LolaDemReader,
    OutOfCoverageError,
)

MAX_HORIZON_SAMPLE_COUNT = 1_000_000
COMPUTATIONAL_POLE_THRESHOLD_DEG = 89.9999


class TerrainHorizonError(LolaDemError):
    """The site elevation needed to build a terrain horizon is unavailable."""


@dataclass(frozen=True)
class TerrainHorizonRay:
    """Maximum sampled terrain angle and data coverage for one azimuth.

    ``complete`` means every scheduled point sample through the requested
    distance succeeded. It does not mean every continuous location or DEM
    raster cell was inspected. An incomplete ray's partial maximum is not a
    definitive horizon.
    """

    azimuth_deg: float
    max_elevation_angle_deg: float | None
    max_elevation_distance_m: float | None
    requested_distance_m: float
    coverage_distance_m: float
    samples_attempted: int
    valid_samples: int
    valid: bool
    complete: bool
    status: str
    error: str | None


@dataclass(frozen=True)
class TerrainHorizonProfile:
    """Immutable horizon rays for one site and one explicit sampling setup."""

    site_latitude_deg: float
    site_longitude_deg: float | None
    site_elevation_m: float
    max_distance_m: float
    radial_step_m: float
    azimuth_step_deg: float
    rays: tuple[TerrainHorizonRay, ...]


def _finite_real(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number.")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be a finite real number.") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite real number.")
    return result


def _ceil_positive_float_ratio(numerator: float, denominator: float) -> int:
    numerator_value, numerator_scale = numerator.as_integer_ratio()
    denominator_value, denominator_scale = denominator.as_integer_ratio()
    quotient, remainder = divmod(
        numerator_value * denominator_scale,
        numerator_scale * denominator_value,
    )
    return quotient + bool(remainder)


def _radial_distance_schedule(
    max_distance_m: float,
    radial_step_m: float,
    sample_count: int,
) -> tuple[float, ...]:
    distances: list[float] = []
    previous_distance = 0.0
    last_interior_distance = math.nextafter(max_distance_m, -math.inf)

    for sample_index in range(1, sample_count):
        distance = sample_index * radial_step_m
        if distance >= max_distance_m:
            distance = last_interior_distance
        if distance <= previous_distance:
            raise ValueError(
                "radial_step_m is too small to represent distinct radial samples."
            )
        distances.append(distance)
        previous_distance = distance

    if max_distance_m <= previous_distance:
        raise ValueError(
            "radial_step_m cannot represent the requested maximum-distance endpoint."
        )
    distances.append(max_distance_m)
    return tuple(distances)


def validate_horizon_sampling_parameters(
    max_distance_m: object,
    radial_step_m: object,
    azimuth_step_deg: object,
) -> tuple[float, float, float, int, int]:
    max_distance = _finite_real(max_distance_m, "max_distance_m")
    radial_step = _finite_real(radial_step_m, "radial_step_m")
    azimuth_step = _finite_real(azimuth_step_deg, "azimuth_step_deg")
    if max_distance <= 0.0:
        raise ValueError("max_distance_m must be positive.")
    if radial_step <= 0.0:
        raise ValueError("radial_step_m must be positive.")
    if not 0.0 < azimuth_step <= 360.0:
        raise ValueError("azimuth_step_deg must be in (0, 360].")

    max_central_angle = max_distance / LUNAR_RADIUS_METRES
    if max_central_angle == 0.0:
        raise ValueError(
            "max_distance_m is too small to represent a nonzero lunar angle."
        )
    if max_central_angle >= math.pi:
        raise ValueError(
            "max_distance_m must be less than the antipodal distance "
            "for a local great-circle ray."
        )
    max_curvature_drop_m = (
        2.0
        * LUNAR_RADIUS_METRES
        * math.sin(max_central_angle / 2.0) ** 2
    )
    if max_curvature_drop_m == 0.0:
        raise ValueError(
            "max_distance_m is too small to represent spherical curvature."
        )

    radial_sample_count = _ceil_positive_float_ratio(max_distance, radial_step)
    azimuth_count = _ceil_positive_float_ratio(360.0, azimuth_step)
    total_sample_count = radial_sample_count * azimuth_count + 1
    if total_sample_count > MAX_HORIZON_SAMPLE_COUNT:
        raise ValueError(
            f"Sampling requires {total_sample_count} point queries, exceeding "
            f"the operational limit of {MAX_HORIZON_SAMPLE_COUNT}."
        )
    return (
        max_distance,
        radial_step,
        azimuth_step,
        radial_sample_count,
        azimuth_count,
    )


def _unit_vector(latitude_rad: float, longitude_rad: float) -> tuple[float, float, float]:
    cos_latitude = math.cos(latitude_rad)
    return (
        cos_latitude * math.cos(longitude_rad),
        cos_latitude * math.sin(longitude_rad),
        math.sin(latitude_rad),
    )


def _dot(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def _normalize(
    vector: tuple[float, float, float],
) -> tuple[float, float, float]:
    magnitude = math.sqrt(_dot(vector, vector))
    if magnitude == 0.0:
        raise ValueError("Could not construct a local tangent direction.")
    return tuple(component / magnitude for component in vector)


def _project_onto_tangent(
    vector: tuple[float, float, float],
    up: tuple[float, float, float],
) -> tuple[float, float, float]:
    projection = _dot(vector, up)
    return tuple(vector[axis] - projection * up[axis] for axis in range(3))


def local_site_frame(
    latitude_deg: float,
    longitude_deg: float | None,
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]:
    """Return site-up, local north, and local east using horizon azimuth conventions."""
    latitude = _finite_real(latitude_deg, "latitude_deg")
    if not -90.0 <= latitude <= 90.0:
        raise ValueError("latitude_deg must be within [-90, 90].")
    if longitude_deg is None:
        if latitude != -90.0:
            raise ValueError(
                "longitude_deg is required except at the exact South Pole."
            )
        longitude_rad = 0.0
    else:
        longitude_rad = math.radians(
            _finite_real(longitude_deg, "longitude_deg") % 360.0
        )

    latitude_rad = math.radians(latitude)
    site_up = (
        (0.0, 0.0, -1.0)
        if latitude == -90.0
        else _unit_vector(latitude_rad, longitude_rad)
    )

    if abs(latitude) >= COMPUTATIONAL_POLE_THRESHOLD_DEG:
        north = _normalize(
            _project_onto_tangent((1.0, 0.0, 0.0), site_up)
        )
        projected_y = _project_onto_tangent((0.0, 1.0, 0.0), site_up)
        east = _normalize(
            tuple(
                projected_y[axis] - _dot(projected_y, north) * north[axis]
                for axis in range(3)
            )
        )
    else:
        north = (
            -math.sin(latitude_rad) * math.cos(longitude_rad),
            -math.sin(latitude_rad) * math.sin(longitude_rad),
            math.cos(latitude_rad),
        )
        east = (-math.sin(longitude_rad), math.cos(longitude_rad), 0.0)
    return site_up, north, east


def _sample_height(sample: ElevationSample) -> float | None:
    if not sample.valid or sample.elevation_m is None:
        return None
    try:
        return _finite_real(sample.elevation_m, "sample elevation")
    except ValueError:
        return None


def _ray_failure(
    azimuth_deg: float,
    max_distance_m: float,
    coverage_distance_m: float,
    samples_attempted: int,
    valid_samples: int,
    status: str,
    error: str,
    max_elevation_angle_deg: float | None,
    max_elevation_distance_m: float | None,
) -> TerrainHorizonRay:
    return TerrainHorizonRay(
        azimuth_deg=azimuth_deg,
        max_elevation_angle_deg=max_elevation_angle_deg,
        max_elevation_distance_m=max_elevation_distance_m,
        requested_distance_m=max_distance_m,
        coverage_distance_m=coverage_distance_m,
        samples_attempted=samples_attempted,
        valid_samples=valid_samples,
        valid=False,
        complete=False,
        status=status,
        error=error,
    )


def calculate_terrain_horizon(
    dem: LolaDemReader,
    site_latitude_deg: float,
    site_longitude_deg: float | None,
    *,
    max_distance_m: float,
    radial_step_m: float,
    azimuth_step_deg: float,
) -> TerrainHorizonProfile:
    """Calculate maximum sampled terrain angles for azimuth rays.

    Azimuth is clockwise from local north toward east, with ray gaps no larger
    than ``azimuth_step_deg``. At the exact South Pole and within the ephemeris
    modules' computational-pole threshold, 0 degrees is +X and 90 degrees is +Y.
    A ray stops at its first invalid or unavailable DEM sample; its valid
    coverage and partial maximum are returned with ``complete=False``. A
    complete ray means all scheduled point samples succeeded, not that every
    continuous location or DEM raster cell was inspected. Its maximum remains
    a point-sampled estimate and may miss narrow ridges.

    The total number of DEM point queries is capped at
    ``MAX_HORIZON_SAMPLE_COUNT`` as an operational resource limit. This cap is
    independent of the DEM's scientific resolution.
    """
    latitude = _finite_real(site_latitude_deg, "site_latitude_deg")
    if not -90.0 <= latitude <= 90.0:
        raise ValueError("site_latitude_deg must be within [-90, 90].")

    if site_longitude_deg is None:
        if latitude != -90.0:
            raise ValueError(
                "site_longitude_deg is required except at the exact South Pole."
            )
        longitude: float | None = None
    else:
        longitude = _finite_real(site_longitude_deg, "site_longitude_deg") % 360.0

    (
        max_distance,
        radial_step,
        azimuth_step,
        radial_sample_count,
        azimuth_count,
    ) = validate_horizon_sampling_parameters(
        max_distance_m,
        radial_step_m,
        azimuth_step_deg,
    )
    radial_distances = _radial_distance_schedule(
        max_distance,
        radial_step,
        radial_sample_count,
    )

    site_up, north, east = local_site_frame(latitude, longitude)

    if latitude == -90.0:
        site_longitude = None
    else:
        site_longitude = longitude

    try:
        site_sample = dem.sample_elevation(latitude, site_longitude)
    except (LolaDemError, ValueError) as exc:
        raise TerrainHorizonError(
            f"Could not sample the terrain elevation at the site: {exc}"
        ) from exc
    site_elevation = _sample_height(site_sample)
    if site_elevation is None:
        raise TerrainHorizonError(
            "The terrain elevation at the site is invalid; no horizon can be computed."
        )

    rays: list[TerrainHorizonRay] = []

    for azimuth_index in range(azimuth_count):
        azimuth = (azimuth_index * azimuth_step) % 360.0
        azimuth_rad = math.radians(azimuth)
        tangent = tuple(
            math.cos(azimuth_rad) * north[axis]
            + math.sin(azimuth_rad) * east[axis]
            for axis in range(3)
        )

        max_angle: float | None = None
        max_angle_distance: float | None = None
        coverage_distance = 0.0
        samples_attempted = 0
        valid_samples = 0
        failure: tuple[str, str] | None = None

        for distance in radial_distances:
            central_angle = distance / LUNAR_RADIUS_METRES
            cos_central = math.cos(central_angle)
            sin_central = math.sin(central_angle)
            terrain_up = tuple(
                cos_central * site_up[axis] + sin_central * tangent[axis]
                for axis in range(3)
            )
            terrain_latitude = math.degrees(
                math.asin(max(-1.0, min(1.0, terrain_up[2])))
            )
            terrain_longitude = math.degrees(
                math.atan2(terrain_up[1], terrain_up[0])
            ) % 360.0

            samples_attempted += 1
            try:
                terrain_sample = dem.sample_elevation(
                    terrain_latitude,
                    terrain_longitude,
                )
            except OutOfCoverageError as exc:
                failure = ("OUT_OF_COVERAGE", str(exc))
                break
            except InterpolationUnavailableError as exc:
                failure = ("INTERPOLATION_UNAVAILABLE", str(exc))
                break
            except LolaDataIntegrityError as exc:
                failure = ("DATA_INTEGRITY_ERROR", str(exc))
                break
            except LolaDemError as exc:
                failure = ("DEM_ERROR", str(exc))
                break
            except ValueError as exc:
                failure = ("SAMPLE_ERROR", str(exc))
                break

            terrain_elevation = _sample_height(terrain_sample)
            if terrain_elevation is None:
                status = terrain_sample.status
                if not status or status.casefold() == "ok":
                    status = "INVALID_SAMPLE"
                failure = (
                    status,
                    f"Invalid terrain sample at {distance:g} m: {status}.",
                )
                break

            terrain_radius = LUNAR_RADIUS_METRES + terrain_elevation
            vertical = (
                terrain_elevation
                - site_elevation
                - 2.0
                * terrain_radius
                * math.sin(central_angle / 2.0) ** 2
            )
            horizontal = terrain_radius * abs(sin_central)
            elevation_angle = math.degrees(math.atan2(vertical, horizontal))

            valid_samples += 1
            coverage_distance = distance
            if max_angle is None or elevation_angle > max_angle:
                max_angle = elevation_angle
                max_angle_distance = distance

        if failure is not None:
            rays.append(
                _ray_failure(
                    azimuth,
                    max_distance,
                    coverage_distance,
                    samples_attempted,
                    valid_samples,
                    failure[0],
                    failure[1],
                    max_angle,
                    max_angle_distance,
                )
            )
        else:
            rays.append(
                TerrainHorizonRay(
                    azimuth_deg=azimuth,
                    max_elevation_angle_deg=max_angle,
                    max_elevation_distance_m=max_angle_distance,
                    requested_distance_m=max_distance,
                    coverage_distance_m=coverage_distance,
                    samples_attempted=samples_attempted,
                    valid_samples=valid_samples,
                    valid=True,
                    complete=True,
                    status="COMPLETE",
                    error=None,
                )
            )

    return TerrainHorizonProfile(
        site_latitude_deg=latitude,
        site_longitude_deg=site_longitude,
        site_elevation_m=site_elevation,
        max_distance_m=max_distance,
        radial_step_m=radial_step,
        azimuth_step_deg=azimuth_step,
        rays=tuple(rays),
    )
