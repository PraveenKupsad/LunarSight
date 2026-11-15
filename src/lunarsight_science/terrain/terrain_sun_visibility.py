"""Classify finite solar-disk visibility against a sampled terrain horizon.

FULL, PARTIAL, and OCCULTED describe only the supplied profile's
piecewise-linear, point-sampled model. They do not certify continuous lunar
terrain: 20 m DEM sampling can miss narrow ridges, and finite azimuth rays do
not bound the horizon between them. Callers must derive the required search
distance from a conservative terrain/body model. No visible-disk fraction or
solar power is calculated.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
import math
from numbers import Integral, Real

from .terrain_horizon import TerrainHorizonProfile, TerrainHorizonRay

MAX_DISK_WITNESS_SAMPLES = 100_000
# Operational per-call witness limit, not a scientific sampling recommendation.


@dataclass(frozen=True)
class TerrainSunVisibility:
    """Finite-disk classification of a sampled horizon model, not terrain certification."""

    classification: str
    reason: str | None
    required_coverage_distance_m: float
    azimuth_footprint_half_width_deg: float | None
    disk_witness_samples: int
    visible_margin_deg: float | None
    obstructed_margin_deg: float | None
    classification_basis: str = "SAMPLED_PIECEWISE_LINEAR_HORIZON"
    physical_terrain_visibility_certified: bool = field(
        default=False,
        init=False,
    )


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


def _indeterminate(
    reason: str,
    required_distance: float,
    footprint_half_width: float | None,
    witness_samples: int = 0,
    visible_margin: float | None = None,
    obstructed_margin: float | None = None,
) -> TerrainSunVisibility:
    return TerrainSunVisibility(
        classification="INDETERMINATE",
        reason=reason,
        required_coverage_distance_m=required_distance,
        azimuth_footprint_half_width_deg=footprint_half_width,
        disk_witness_samples=witness_samples,
        visible_margin_deg=visible_margin,
        obstructed_margin_deg=obstructed_margin,
    )


def _sorted_rays(
    profile: TerrainHorizonProfile,
) -> tuple[list[float], list[TerrainHorizonRay]] | None:
    if not profile.rays:
        return None
    try:
        azimuth_step = _finite_real(
            profile.azimuth_step_deg,
            "profile.azimuth_step_deg",
        )
    except ValueError:
        return None
    if not 0.0 < azimuth_step <= 360.0:
        return None

    pairs: list[tuple[float, TerrainHorizonRay]] = []
    for ray in profile.rays:
        try:
            ray_azimuth = _finite_real(ray.azimuth_deg, "ray.azimuth_deg")
        except ValueError:
            return None
        pairs.append((ray_azimuth % 360.0, ray))
    pairs.sort(key=lambda pair: pair[0])

    angles = [pair[0] for pair in pairs]
    rays = [pair[1] for pair in pairs]
    if len(angles) > 1 and any(
        current <= previous
        for previous, current in zip(angles, angles[1:])
    ):
        return None

    for index, start in enumerate(angles):
        end = (
            angles[index + 1]
            if index + 1 < len(angles)
            else angles[0] + 360.0
        )
        gap = end - start
        if gap > azimuth_step and not math.isclose(
            gap,
            azimuth_step,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            return None
    return angles, rays


def _azimuth_footprint(
    elevation_deg: float,
    azimuth_deg: float,
    angular_radius_deg: float,
) -> tuple[float, float | None]:
    if 90.0 - abs(elevation_deg) <= angular_radius_deg:
        return azimuth_deg, None

    elevation_rad = math.radians(elevation_deg)
    radius_rad = math.radians(angular_radius_deg)
    ratio = math.sin(radius_rad) / math.cos(elevation_rad)
    if ratio >= 1.0:
        return azimuth_deg, None
    half_width = math.degrees(math.asin(max(0.0, ratio)))
    return azimuth_deg, half_width


def _intersecting_segments(
    angles: list[float],
    rays: list[TerrainHorizonRay],
    center_azimuth: float,
    footprint_half_width: float | None,
) -> list[tuple[float, float, TerrainHorizonRay, TerrainHorizonRay]]:
    segments: list[tuple[float, float, TerrainHorizonRay, TerrainHorizonRay]] = []
    for index, start in enumerate(angles):
        end = angles[index + 1] if index + 1 < len(angles) else angles[0] + 360.0
        segments.append((start, end, rays[index], rays[(index + 1) % len(rays)]))

    if footprint_half_width is None:
        return segments

    lower = center_azimuth - footprint_half_width
    upper = center_azimuth + footprint_half_width
    intersecting = []
    for segment in segments:
        start, end = segment[0], segment[1]
        if any(
            start + shift <= upper and end + shift >= lower
            for shift in (-360.0, 0.0, 360.0)
        ):
            intersecting.append(segment)
    return intersecting


def _ray_horizon(
    ray: TerrainHorizonRay,
    required_distance: float,
) -> float | None:
    if not ray.valid or not ray.complete or ray.max_elevation_angle_deg is None:
        return None
    try:
        maximum_angle = _finite_real(
            ray.max_elevation_angle_deg,
            "ray.max_elevation_angle_deg",
        )
        requested_distance = _finite_real(
            ray.requested_distance_m,
            "ray.requested_distance_m",
        )
        coverage_distance = _finite_real(
            ray.coverage_distance_m,
            "ray.coverage_distance_m",
        )
    except ValueError:
        return None
    if (
        requested_distance < required_distance
        or coverage_distance < required_distance
    ):
        return None
    return maximum_angle


def _horizon_at_azimuth(
    azimuth_deg: float,
    angles: list[float],
    rays: list[TerrainHorizonRay],
    required_distance: float,
) -> float | None:
    if len(rays) == 1:
        return _ray_horizon(rays[0], required_distance)

    normalized_azimuth = azimuth_deg % 360.0
    index = bisect_right(angles, normalized_azimuth) - 1
    if index < 0:
        index = len(angles) - 1
        normalized_azimuth += 360.0

    next_index = (index + 1) % len(rays)
    start = angles[index]
    end = angles[next_index] if next_index else angles[0] + 360.0
    if normalized_azimuth < start:
        normalized_azimuth += 360.0

    left = _ray_horizon(rays[index], required_distance)
    right = _ray_horizon(rays[next_index], required_distance)
    if left is None or right is None:
        return None
    fraction = (normalized_azimuth - start) / (end - start)
    return left + fraction * (right - left)


def _disk_direction(
    elevation_rad: float,
    azimuth_rad: float,
    angular_offset_rad: float,
    position_angle_rad: float,
) -> tuple[float, float]:
    sin_elevation = math.sin(elevation_rad)
    cos_elevation = math.cos(elevation_rad)
    sin_azimuth = math.sin(azimuth_rad)
    cos_azimuth = math.cos(azimuth_rad)

    center = (
        cos_elevation * cos_azimuth,
        cos_elevation * sin_azimuth,
        sin_elevation,
    )
    elevation_tangent = (
        -sin_elevation * cos_azimuth,
        -sin_elevation * sin_azimuth,
        cos_elevation,
    )
    azimuth_tangent = (-sin_azimuth, cos_azimuth, 0.0)

    cos_offset = math.cos(angular_offset_rad)
    sin_offset = math.sin(angular_offset_rad)
    cos_position = math.cos(position_angle_rad)
    sin_position = math.sin(position_angle_rad)
    direction = tuple(
        cos_offset * center[axis]
        + sin_offset
        * (
            cos_position * elevation_tangent[axis]
            + sin_position * azimuth_tangent[axis]
        )
        for axis in range(3)
    )
    elevation = math.degrees(
        math.asin(max(-1.0, min(1.0, direction[2])))
    )
    azimuth = math.degrees(math.atan2(direction[1], direction[0])) % 360.0
    return elevation, azimuth


def classify_solar_disk_against_terrain(
    sun_center_elevation_deg: float,
    sun_center_azimuth_deg: float,
    sun_angular_radius_deg: float,
    horizon_profile: TerrainHorizonProfile,
    *,
    required_coverage_distance_m: float,
    classification_tolerance_deg: float,
    disk_sample_spacing_deg: float,
    max_disk_samples: int,
) -> TerrainSunVisibility:
    """Classify a finite solar disk against an existing terrain profile.

    FULL and OCCULTED describe only the interpolated profile and use
    conservative elevation extrema for the disk and horizon bounds over every
    intersecting azimuth sector. They do not certify continuous lunar terrain.
    PARTIAL is returned only when sampled directions establish both a visible
    and an obstructed interior in that model. The witness samples cannot
    guarantee detection of a tiny crescent; if they do not establish PARTIAL
    and the conservative bounds do not decide the result, the classifier
    returns INDETERMINATE.

    A caller must supply a search distance justified by a conservative terrain
    or body model. A complete ray only establishes its configured range, never
    terrain beyond it. Incomplete rays, including their partial maxima, are
    never used as definitive horizon values. Azimuth is periodic; at the
    computational South Pole it uses the profile's existing 0°=+X, 90°=+Y
    convention. Classification is relative to the profile's point-sampled
    piecewise-linear azimuth interpolation, not a continuous terrain proof.
    ``max_disk_samples`` is capped by ``MAX_DISK_WITNESS_SAMPLES`` as an
    operational safeguard, not a scientific sampling recommendation.
    """
    elevation = _finite_real(
        sun_center_elevation_deg,
        "sun_center_elevation_deg",
    )
    azimuth = _finite_real(sun_center_azimuth_deg, "sun_center_azimuth_deg") % 360.0
    angular_radius = _finite_real(
        sun_angular_radius_deg,
        "sun_angular_radius_deg",
    )
    required_distance = _finite_real(
        required_coverage_distance_m,
        "required_coverage_distance_m",
    )
    tolerance = _finite_real(
        classification_tolerance_deg,
        "classification_tolerance_deg",
    )
    sample_spacing = _finite_real(
        disk_sample_spacing_deg,
        "disk_sample_spacing_deg",
    )
    if not -90.0 <= elevation <= 90.0:
        raise ValueError("sun_center_elevation_deg must be within [-90, 90].")
    if not 0.0 <= angular_radius < 90.0:
        raise ValueError("sun_angular_radius_deg must be in [0, 90).")
    if required_distance <= 0.0:
        raise ValueError("required_coverage_distance_m must be positive.")
    if not 0.0 < tolerance < 180.0:
        raise ValueError(
            "classification_tolerance_deg must be greater than zero and less "
            "than 180 degrees."
        )
    if not 0.0 < sample_spacing <= 180.0:
        raise ValueError(
            "disk_sample_spacing_deg must be in (0, 180] degrees."
        )
    if (
        isinstance(max_disk_samples, bool)
        or not isinstance(max_disk_samples, Integral)
        or max_disk_samples <= 0
    ):
        raise ValueError("max_disk_samples must be a positive integer.")
    if max_disk_samples > MAX_DISK_WITNESS_SAMPLES:
        raise ValueError(
            f"max_disk_samples cannot exceed the operational limit of "
            f"{MAX_DISK_WITNESS_SAMPLES}."
        )

    try:
        profile_max_distance = _finite_real(
            horizon_profile.max_distance_m,
            "horizon_profile.max_distance_m",
        )
    except ValueError:
        profile_max_distance = float("nan")
    if (
        not math.isfinite(profile_max_distance)
        or profile_max_distance < required_distance
    ):
        return _indeterminate(
            "The horizon profile does not cover the required search distance.",
            required_distance,
            None,
        )

    sorted_profile = _sorted_rays(horizon_profile)
    if sorted_profile is None:
        return _indeterminate(
            "The horizon profile has invalid or incomplete azimuth geometry.",
            required_distance,
            None,
        )
    angles, rays = sorted_profile
    azimuth, footprint_half_width = _azimuth_footprint(
        elevation,
        azimuth,
        angular_radius,
    )
    segments = _intersecting_segments(
        angles,
        rays,
        azimuth,
        footprint_half_width,
    )
    if not segments:
        return _indeterminate(
            "No horizon sectors cover the solar-disk azimuth footprint.",
            required_distance,
            footprint_half_width,
        )

    horizon_values: list[float] = []
    for _, _, left_ray, right_ray in segments:
        left_value = _ray_horizon(left_ray, required_distance)
        right_value = _ray_horizon(right_ray, required_distance)
        if left_value is None or right_value is None:
            return _indeterminate(
                "A required horizon ray is invalid, incomplete, or short of "
                "the required search distance.",
                required_distance,
                footprint_half_width,
            )
        horizon_values.extend((left_value, right_value))

    horizon_minimum = min(horizon_values)
    horizon_maximum = max(horizon_values)
    minimum_disk_elevation = max(-90.0, elevation - angular_radius)
    maximum_disk_elevation = min(90.0, elevation + angular_radius)
    if minimum_disk_elevation - horizon_maximum > tolerance:
        return TerrainSunVisibility(
            classification="FULL",
            reason=None,
            required_coverage_distance_m=required_distance,
            azimuth_footprint_half_width_deg=footprint_half_width,
            disk_witness_samples=0,
            visible_margin_deg=minimum_disk_elevation - horizon_maximum,
            obstructed_margin_deg=None,
        )
    if maximum_disk_elevation - horizon_minimum < -tolerance:
        return TerrainSunVisibility(
            classification="OCCULTED",
            reason=None,
            required_coverage_distance_m=required_distance,
            azimuth_footprint_half_width_deg=footprint_half_width,
            disk_witness_samples=0,
            visible_margin_deg=None,
            obstructed_margin_deg=maximum_disk_elevation - horizon_minimum,
        )

    radial_ratio = angular_radius / sample_spacing
    if not math.isfinite(radial_ratio):
        return _indeterminate(
            "The requested disk witness spacing exceeds the numerical budget.",
            required_distance,
            footprint_half_width,
        )
    radial_count = max(1, math.ceil(radial_ratio))
    elevation_rad = math.radians(elevation)
    azimuth_rad = math.radians(azimuth)
    spacing_rad = math.radians(sample_spacing)
    visible_margin: float | None = None
    obstructed_margin: float | None = None
    witness_samples = 0

    ring_count = 1 if angular_radius == 0.0 else radial_count + 1
    for ring_index in range(ring_count):
        if angular_radius == 0.0 or ring_index == 0:
            offset_rad = 0.0
            position_count = 1
        else:
            offset_index = ring_index
            offset_deg = (
                angular_radius
                if offset_index == ring_count - 1
                else min(offset_index * sample_spacing, angular_radius)
            )
            offset_rad = math.radians(offset_deg)
            circumference = 2.0 * math.pi * math.sin(offset_rad)
            position_ratio = circumference / spacing_rad
            if not math.isfinite(position_ratio):
                return _indeterminate(
                    "The requested disk witness spacing exceeds the numerical budget.",
                    required_distance,
                    footprint_half_width,
                    witness_samples,
                    visible_margin,
                    obstructed_margin,
                )
            position_count = max(1, math.ceil(position_ratio))

        for position_index in range(position_count):
            if witness_samples >= max_disk_samples:
                return _indeterminate(
                    "The disk witness-sample budget was exhausted before "
                    "classification could be established.",
                    required_distance,
                    footprint_half_width,
                    witness_samples,
                    visible_margin,
                    obstructed_margin,
                )
            position_angle = (
                2.0 * math.pi * position_index / position_count
            )
            disk_elevation, disk_azimuth = _disk_direction(
                elevation_rad,
                azimuth_rad,
                offset_rad,
                position_angle,
            )
            disk_horizon = _horizon_at_azimuth(
                disk_azimuth,
                angles,
                rays,
                required_distance,
            )
            witness_samples += 1
            if disk_horizon is None:
                return _indeterminate(
                    "A disk witness intersects an unusable horizon sector.",
                    required_distance,
                    footprint_half_width,
                    witness_samples,
                    visible_margin,
                    obstructed_margin,
                )

            margin = disk_elevation - disk_horizon
            if margin > tolerance:
                visible_margin = (
                    margin
                    if visible_margin is None
                    else max(visible_margin, margin)
                )
            elif margin < -tolerance:
                obstructed_margin = (
                    margin
                    if obstructed_margin is None
                    else min(obstructed_margin, margin)
                )

            if visible_margin is not None and obstructed_margin is not None:
                return TerrainSunVisibility(
                    classification="PARTIAL",
                    reason=None,
                    required_coverage_distance_m=required_distance,
                    azimuth_footprint_half_width_deg=footprint_half_width,
                    disk_witness_samples=witness_samples,
                    visible_margin_deg=visible_margin,
                    obstructed_margin_deg=obstructed_margin,
                )

    return _indeterminate(
        "The conservative bounds and disk witnesses do not establish a "
        "classification at the requested tolerance.",
        required_distance,
        footprint_half_width,
        witness_samples,
        visible_margin,
        obstructed_margin,
    )
