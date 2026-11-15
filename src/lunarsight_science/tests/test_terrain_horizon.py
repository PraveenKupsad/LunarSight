"""Synthetic tests for terrain-horizon geometry and sample coverage."""

import math
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from lunarsight_science.config import LUNAR_RADIUS_METRES
from lunarsight_science.terrain import (
    ElevationSample,
    OutOfCoverageError,
    TerrainHorizonError,
    calculate_terrain_horizon,
)
from lunarsight_science.terrain.terrain_horizon import (
    _ceil_positive_float_ratio,
    _radial_distance_schedule,
    local_site_frame,
)


class SyntheticDem:
    def __init__(self, elevation_function, error_function=None):
        self.elevation_function = elevation_function
        self.error_function = error_function
        self.calls = []

    def sample_elevation(self, latitude_deg, longitude_deg=None):
        self.calls.append((latitude_deg, longitude_deg))
        if self.error_function is not None:
            error = self.error_function(latitude_deg, longitude_deg)
            if error is not None:
                raise error

        is_site = latitude_deg == -90.0 and longitude_deg is None
        elevation = self.elevation_function(
            latitude_deg,
            longitude_deg,
            is_site,
        )
        if elevation is None:
            return ElevationSample(
                elevation_m=None,
                valid=False,
                status="INVALID_SAMPLE",
                latitude_deg=latitude_deg,
                longitude_deg=longitude_deg,
                row=0.0,
                col=0.0,
                method="synthetic",
            )
        return ElevationSample(
            elevation_m=elevation,
            valid=True,
            status="OK",
            latitude_deg=latitude_deg,
            longitude_deg=longitude_deg,
            row=0.0,
            col=0.0,
            method="synthetic",
        )


class CountingDem:
    def __init__(self):
        self.calls = 0
        self.sample = ElevationSample(
            elevation_m=0.0,
            valid=True,
            status="OK",
            latitude_deg=-90.0,
            longitude_deg=None,
            row=0.0,
            col=0.0,
            method="synthetic",
        )

    def sample_elevation(self, latitude_deg, longitude_deg=None):
        self.calls += 1
        return self.sample


def _profile(dem, **kwargs):
    return calculate_terrain_horizon(
        dem,
        -90.0,
        None,
        max_distance_m=kwargs.get("max_distance_m", 200.0),
        radial_step_m=kwargs.get("radial_step_m", 100.0),
        azimuth_step_deg=kwargs.get("azimuth_step_deg", 360.0),
    )


class TestTerrainHorizon(unittest.TestCase):
    def test_spherical_curvature_matches_equal_height_equation(self):
        dem = SyntheticDem(lambda latitude, longitude, is_site: 0.0)
        profile = _profile(dem)

        first_ray = profile.rays[0]
        central_angle = 100.0 / LUNAR_RADIUS_METRES
        expected = math.degrees(-central_angle / 2.0)
        self.assertAlmostEqual(first_ray.max_elevation_angle_deg, expected, places=9)
        self.assertEqual(first_ray.max_elevation_distance_m, 100.0)
        self.assertTrue(first_ray.complete)

    def test_geometry_includes_unequal_site_and_terrain_elevations(self):
        dem = SyntheticDem(
            lambda latitude, longitude, is_site: 120.0 if is_site else 370.0
        )
        profile = _profile(dem, max_distance_m=100.0)

        gamma = 100.0 / LUNAR_RADIUS_METRES
        expected = math.degrees(
            math.atan2(
                (LUNAR_RADIUS_METRES + 370.0) * math.cos(gamma)
                - (LUNAR_RADIUS_METRES + 120.0),
                (LUNAR_RADIUS_METRES + 370.0) * math.sin(gamma),
            )
        )
        self.assertAlmostEqual(
            profile.rays[0].max_elevation_angle_deg,
            expected,
            places=10,
        )
        self.assertEqual(profile.site_elevation_m, 120.0)

    def test_ridge_raises_only_its_azimuth_ray(self):
        dem = SyntheticDem(
            lambda latitude, longitude, is_site: (
                1000.0 if not is_site and math.isclose(longitude, 0.0) else 0.0
            )
        )
        profile = _profile(dem, azimuth_step_deg=90.0)
        by_azimuth = {ray.azimuth_deg: ray for ray in profile.rays}

        self.assertGreater(by_azimuth[0.0].max_elevation_angle_deg, 0.0)
        for azimuth in (90.0, 180.0, 270.0):
            self.assertLess(by_azimuth[azimuth].max_elevation_angle_deg, 0.0)

    def test_south_pole_zero_and_ninety_degrees_are_plus_x_and_plus_y(self):
        dem = SyntheticDem(lambda latitude, longitude, is_site: 0.0)
        profile = _profile(dem, max_distance_m=100.0, azimuth_step_deg=90.0)

        self.assertEqual(profile.rays[0].azimuth_deg, 0.0)
        self.assertEqual(profile.rays[1].azimuth_deg, 90.0)
        self.assertAlmostEqual(dem.calls[1][1], 0.0, places=10)
        self.assertAlmostEqual(dem.calls[2][1], 90.0, places=10)

    def test_near_south_pole_uses_fixed_axes_at_nonzero_longitude(self):
        dem = SyntheticDem(lambda latitude, longitude, is_site: 0.0)
        profile = calculate_terrain_horizon(
            dem,
            -89.99995,
            90.0,
            max_distance_m=1000.0,
            radial_step_m=1000.0,
            azimuth_step_deg=90.0,
        )

        self.assertAlmostEqual(profile.rays[0].azimuth_deg, 0.0)
        self.assertAlmostEqual(profile.rays[1].azimuth_deg, 90.0)
        self.assertLess(dem.calls[1][1], 1.0)
        self.assertAlmostEqual(dem.calls[2][1], 90.0, places=3)

    def test_shared_site_frame_uses_fixed_basis_at_pole_threshold(self):
        south_up, south_north, south_east = local_site_frame(-90.0, None)
        near_pole_up, near_pole_north, near_pole_east = local_site_frame(
            -89.99995,
            90.0,
        )
        outside_up, outside_north, outside_east = local_site_frame(
            -89.99985,
            90.0,
        )

        self.assertEqual(south_up, (0.0, 0.0, -1.0))
        self.assertEqual(south_north, (1.0, 0.0, 0.0))
        self.assertEqual(south_east, (0.0, 1.0, 0.0))
        self.assertAlmostEqual(near_pole_north[0], 1.0, places=12)
        self.assertAlmostEqual(near_pole_north[1], 0.0, places=12)
        self.assertAlmostEqual(near_pole_east[0], 0.0, places=12)
        self.assertAlmostEqual(near_pole_east[1], 1.0, places=12)

        self.assertAlmostEqual(outside_north[0], 0.0, places=9)
        self.assertAlmostEqual(outside_north[1], 1.0, places=9)
        self.assertAlmostEqual(
            outside_north[2],
            math.cos(math.radians(-89.99985)),
            places=12,
        )
        self.assertAlmostEqual(outside_east[0], -1.0, places=9)
        self.assertAlmostEqual(outside_east[1], 0.0, places=9)
        self.assertAlmostEqual(outside_east[2], 0.0, places=9)

    def test_nonpolar_rays_follow_local_great_circle_bearings(self):
        dem = SyntheticDem(lambda latitude, longitude, is_site: 0.0)
        latitude_deg = -45.0
        longitude_deg = 30.0
        profile = calculate_terrain_horizon(
            dem,
            latitude_deg,
            longitude_deg,
            max_distance_m=1000.0,
            radial_step_m=1000.0,
            azimuth_step_deg=90.0,
        )

        phi = math.radians(latitude_deg)
        lam = math.radians(longitude_deg)
        site_up = (
            math.cos(phi) * math.cos(lam),
            math.cos(phi) * math.sin(lam),
            math.sin(phi),
        )
        north = (
            -math.sin(phi) * math.cos(lam),
            -math.sin(phi) * math.sin(lam),
            math.cos(phi),
        )
        east = (-math.sin(lam), math.cos(lam), 0.0)

        for ray_index, expected_azimuth in ((0, 0.0), (1, 90.0)):
            terrain_latitude, terrain_longitude = dem.calls[ray_index + 1]
            terrain_phi = math.radians(terrain_latitude)
            terrain_lam = math.radians(terrain_longitude)
            terrain_up = (
                math.cos(terrain_phi) * math.cos(terrain_lam),
                math.cos(terrain_phi) * math.sin(terrain_lam),
                math.sin(terrain_phi),
            )
            dot = sum(site_up[i] * terrain_up[i] for i in range(3))
            central_angle = math.acos(max(-1.0, min(1.0, dot)))
            tangent = tuple(
                (terrain_up[i] - math.cos(central_angle) * site_up[i])
                / math.sin(central_angle)
                for i in range(3)
            )
            bearing_north = sum(tangent[i] * north[i] for i in range(3))
            bearing_east = sum(tangent[i] * east[i] for i in range(3))

            if expected_azimuth == 0.0:
                self.assertAlmostEqual(bearing_north, 1.0, places=9)
                self.assertAlmostEqual(bearing_east, 0.0, places=9)
            else:
                self.assertAlmostEqual(bearing_north, 0.0, places=9)
                self.assertAlmostEqual(bearing_east, 1.0, places=9)
            self.assertTrue(profile.rays[ray_index].complete)

    def test_non_divisor_azimuth_step_wraps_without_duplicate_360_ray(self):
        dem = SyntheticDem(lambda latitude, longitude, is_site: 0.0)
        profile = _profile(
            dem,
            max_distance_m=100.0,
            azimuth_step_deg=100.0,
        )
        azimuths = [ray.azimuth_deg for ray in profile.rays]
        wrap_gaps = [
            (azimuths[(index + 1) % len(azimuths)] - azimuths[index]) % 360.0
            for index in range(len(azimuths))
        ]

        self.assertEqual(azimuths, [0.0, 100.0, 200.0, 300.0])
        self.assertTrue(all(0.0 < gap <= 100.0 for gap in wrap_gaps))

    def test_requested_maximum_distance_is_sampled_exactly(self):
        dem = SyntheticDem(lambda latitude, longitude, is_site: 0.0)
        profile = _profile(
            dem,
            max_distance_m=250.0,
            radial_step_m=100.0,
        )
        sampled_distances = [
            LUNAR_RADIUS_METRES * math.radians(latitude + 90.0)
            for latitude, _ in dem.calls[1:]
        ]

        self.assertEqual(len(sampled_distances), 3)
        self.assertAlmostEqual(sampled_distances[-1], 250.0, delta=1e-5)
        self.assertEqual(profile.rays[0].coverage_distance_m, 250.0)
        self.assertTrue(profile.rays[0].complete)

    def test_radial_schedule_handles_rounded_counts_and_unique_endpoint(self):
        cases = (
            (0.9000000000000001, 0.1, 10),
            (85504.2339177386, 28501.411305912865, 4),
        )
        for max_distance, radial_step, expected_count in cases:
            with self.subTest(max_distance=max_distance, radial_step=radial_step):
                sample_count = _ceil_positive_float_ratio(
                    max_distance,
                    radial_step,
                )
                distances = _radial_distance_schedule(
                    max_distance,
                    radial_step,
                    sample_count,
                )

                self.assertEqual(sample_count, expected_count)
                self.assertEqual(len(distances), expected_count)
                self.assertEqual(distances[-1], max_distance)
                self.assertEqual(distances.count(max_distance), 1)
                self.assertTrue(all(distance <= max_distance for distance in distances))
                self.assertTrue(
                    all(
                        earlier < later
                        for earlier, later in zip(distances, distances[1:])
                    )
                )

        first_schedule = _radial_distance_schedule(
            cases[0][0],
            cases[0][1],
            cases[0][2],
        )
        self.assertEqual(first_schedule[-2], 0.9)
        second_schedule = _radial_distance_schedule(
            cases[1][0],
            cases[1][1],
            cases[1][2],
        )
        self.assertEqual(
            second_schedule[-2],
            math.nextafter(cases[1][0], -math.inf),
        )

    def test_rounded_azimuth_count_over_cap_is_rejected_before_sampling(self):
        dem = SyntheticDem(lambda latitude, longitude, is_site: 0.0)
        with self.assertRaisesRegex(ValueError, "exceeding"):
            calculate_terrain_horizon(
                dem,
                -90.0,
                None,
                max_distance_m=28571.0,
                radial_step_m=1.0,
                azimuth_step_deg=10.285714285714285,
            )
        self.assertEqual(dem.calls, [])

    def test_query_cap_includes_site_sample(self):
        dem = CountingDem()
        profile = calculate_terrain_horizon(
            dem,
            -90.0,
            None,
            max_distance_m=999999.0,
            radial_step_m=1.0,
            azimuth_step_deg=360.0,
        )

        self.assertEqual(dem.calls, 1_000_000)
        self.assertEqual(profile.rays[0].samples_attempted, 999_999)
        self.assertTrue(profile.rays[0].complete)

    def test_query_cap_rejects_one_point_above_limit_before_sampling(self):
        dem = CountingDem()
        with self.assertRaisesRegex(ValueError, "exceeding"):
            calculate_terrain_horizon(
                dem,
                -90.0,
                None,
                max_distance_m=1_000_000.0,
                radial_step_m=1.0,
                azimuth_step_deg=360.0,
            )
        self.assertEqual(dem.calls, 0)

    def test_invalid_sample_marks_only_affected_ray_incomplete(self):
        dem = SyntheticDem(
            lambda latitude, longitude, is_site: (
                None
                if not is_site and math.isclose(longitude, 90.0)
                else 0.0
            )
        )
        profile = _profile(dem, azimuth_step_deg=90.0)
        by_azimuth = {ray.azimuth_deg: ray for ray in profile.rays}
        invalid_ray = by_azimuth[90.0]

        self.assertFalse(invalid_ray.valid)
        self.assertFalse(invalid_ray.complete)
        self.assertEqual(invalid_ray.status, "INVALID_SAMPLE")
        self.assertEqual(invalid_ray.coverage_distance_m, 0.0)
        self.assertEqual(invalid_ray.samples_attempted, 1)
        self.assertEqual(invalid_ray.valid_samples, 0)
        self.assertIsNone(invalid_ray.max_elevation_angle_deg)
        self.assertTrue(by_azimuth[0.0].complete)

    def test_invalid_site_elevation_rejects_profile(self):
        dem = SyntheticDem(
            lambda latitude, longitude, is_site: None if is_site else 0.0
        )

        with self.assertRaises(TerrainHorizonError):
            _profile(dem)
        self.assertEqual(len(dem.calls), 1)

    def test_invalid_sample_after_valid_prefix_preserves_partial_coverage(self):
        dem = SyntheticDem(
            lambda latitude, longitude, is_site: (
                None
                if not is_site and latitude > -89.995
                else 0.0
            )
        )
        profile = _profile(
            dem,
            max_distance_m=300.0,
            azimuth_step_deg=90.0,
        )
        invalid_ray = profile.rays[0]

        self.assertFalse(invalid_ray.valid)
        self.assertFalse(invalid_ray.complete)
        self.assertEqual(invalid_ray.status, "INVALID_SAMPLE")
        self.assertEqual(invalid_ray.coverage_distance_m, 100.0)
        self.assertEqual(invalid_ray.samples_attempted, 2)
        self.assertEqual(invalid_ray.valid_samples, 1)
        self.assertIsNotNone(invalid_ray.max_elevation_angle_deg)

    def test_out_of_coverage_marks_ray_incomplete_and_stops_sampling(self):
        def fail_after_first_sample(latitude, longitude):
            if (
                longitude is not None
                and math.isclose(longitude, 0.0)
                and latitude > -89.995
            ):
                return OutOfCoverageError("synthetic coverage edge")
            return None

        dem = SyntheticDem(
            lambda latitude, longitude, is_site: 0.0,
            error_function=fail_after_first_sample,
        )
        profile = _profile(
            dem,
            max_distance_m=300.0,
            azimuth_step_deg=90.0,
        )
        northward = profile.rays[0]

        self.assertFalse(northward.valid)
        self.assertFalse(northward.complete)
        self.assertEqual(northward.status, "OUT_OF_COVERAGE")
        self.assertEqual(northward.coverage_distance_m, 100.0)
        self.assertEqual(northward.samples_attempted, 2)
        self.assertEqual(northward.valid_samples, 1)
        self.assertTrue(profile.rays[1].complete)

    def test_farther_ridge_can_set_the_maximum_horizon_angle(self):
        def elevation(latitude, longitude, is_site):
            if is_site:
                return 0.0
            if -89.994 < latitude < -89.992:
                return 10.0
            return 0.0

        dem = SyntheticDem(elevation)
        profile = _profile(
            dem,
            max_distance_m=300.0,
            azimuth_step_deg=360.0,
        )
        ray = profile.rays[0]

        self.assertEqual(ray.max_elevation_distance_m, 200.0)
        self.assertGreater(ray.max_elevation_angle_deg, 0.0)

    def test_invalid_and_extreme_finite_sampling_parameters_are_rejected(self):
        dem = SyntheticDem(lambda latitude, longitude, is_site: 0.0)
        baseline = {
            "max_distance_m": 200.0,
            "radial_step_m": 100.0,
            "azimuth_step_deg": 360.0,
        }
        cases = (
            ("max_distance_m", 0.0),
            ("max_distance_m", -1.0),
            ("max_distance_m", float("nan")),
            ("max_distance_m", float("inf")),
            ("radial_step_m", 0.0),
            ("radial_step_m", -1.0),
            ("radial_step_m", float("nan")),
            ("radial_step_m", float("inf")),
            ("azimuth_step_deg", 0.0),
            ("azimuth_step_deg", -1.0),
            ("azimuth_step_deg", float("nan")),
            ("azimuth_step_deg", float("inf")),
            ("azimuth_step_deg", 361.0),
        )
        for name, value in cases:
            with self.subTest(name=name, value=value):
                parameters = dict(baseline)
                parameters[name] = value
                with self.assertRaises(ValueError):
                    _profile(dem, **parameters)

        extreme_cases = (
            {
                "max_distance_m": 1e6,
                "radial_step_m": 1e-320,
                "azimuth_step_deg": 360.0,
            },
            {
                "max_distance_m": 1e-300,
                "radial_step_m": 1e-300,
                "azimuth_step_deg": 360.0,
            },
            {
                "max_distance_m": 1e308,
                "radial_step_m": 1.0,
                "azimuth_step_deg": 360.0,
            },
            {
                "max_distance_m": 5e-324,
                "radial_step_m": 1.0,
                "azimuth_step_deg": 360.0,
            },
            {
                "max_distance_m": 100.0,
                "radial_step_m": 100.0,
                "azimuth_step_deg": 5e-324,
            },
            {
                "max_distance_m": 1000.0,
                "radial_step_m": 0.1,
                "azimuth_step_deg": 0.1,
            },
        )
        for parameters in extreme_cases:
            with self.subTest(parameters=parameters):
                with self.assertRaises(ValueError):
                    _profile(dem, **parameters)

        self.assertEqual(dem.calls, [])


if __name__ == "__main__":
    unittest.main()
