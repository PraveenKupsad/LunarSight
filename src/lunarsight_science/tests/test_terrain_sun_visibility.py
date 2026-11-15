"""Synthetic, SPICE-independent tests for finite solar-disk visibility."""

from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from lunarsight_science.terrain import (
    TerrainHorizonProfile,
    TerrainHorizonRay,
    TerrainSunVisibility,
    classify_solar_disk_against_terrain,
)
from lunarsight_science.terrain.terrain_sun_visibility import (
    MAX_DISK_WITNESS_SAMPLES,
    _horizon_at_azimuth,
    _sorted_rays,
)


def _profile(
    horizon_by_azimuth,
    *,
    max_distance=100.0,
    azimuth_step=90.0,
    incomplete_azimuths=(),
    partial_maximum_deg=90.0,
    coverage_distance=None,
    short_coverage_azimuths=(),
    short_ray_distance=50.0,
):
    incomplete_azimuths = set(incomplete_azimuths)
    short_coverage_azimuths = set(short_coverage_azimuths)
    if coverage_distance is None:
        coverage_distance = max_distance
    rays = []
    for azimuth, maximum_angle in sorted(horizon_by_azimuth.items()):
        complete = azimuth not in incomplete_azimuths
        requested_distance = (
            short_ray_distance
            if azimuth in short_coverage_azimuths
            else max_distance
        )
        ray_coverage = (
            min(coverage_distance, short_ray_distance)
            if azimuth in short_coverage_azimuths
            else coverage_distance
        )
        rays.append(
            TerrainHorizonRay(
                azimuth_deg=azimuth,
                max_elevation_angle_deg=(
                    maximum_angle if complete else partial_maximum_deg
                ),
                max_elevation_distance_m=(
                    requested_distance if complete else None
                ),
                requested_distance_m=requested_distance,
                coverage_distance_m=(
                    ray_coverage if complete else ray_coverage / 2.0
                ),
                samples_attempted=2,
                valid_samples=2 if complete else 1,
                valid=complete,
                complete=complete,
                status="COMPLETE" if complete else "INVALID_SAMPLE",
                error=None if complete else "synthetic partial ray",
            )
        )
    return TerrainHorizonProfile(
        site_latitude_deg=-90.0,
        site_longitude_deg=None,
        site_elevation_m=0.0,
        max_distance_m=max_distance,
        radial_step_m=max_distance / 2.0,
        azimuth_step_deg=azimuth_step,
        rays=tuple(rays),
    )


def _classify(
    profile,
    elevation,
    azimuth=0.0,
    radius=0.25,
    *,
    required_distance=100.0,
    tolerance=1e-6,
    sample_spacing=0.05,
    max_samples=10000,
):
    return classify_solar_disk_against_terrain(
        elevation,
        azimuth,
        radius,
        profile,
        required_coverage_distance_m=required_distance,
        classification_tolerance_deg=tolerance,
        disk_sample_spacing_deg=sample_spacing,
        max_disk_samples=max_samples,
    )


class TestTerrainSunVisibility(unittest.TestCase):
    def test_physical_terrain_certification_cannot_be_enabled_by_constructor(self):
        with self.assertRaises(TypeError):
            TerrainSunVisibility(
                classification="FULL",
                reason=None,
                required_coverage_distance_m=100.0,
                azimuth_footprint_half_width_deg=1.0,
                disk_witness_samples=0,
                visible_margin_deg=1.0,
                obstructed_margin_deg=None,
                physical_terrain_visibility_certified=True,
            )

        result = TerrainSunVisibility(
            classification="FULL",
            reason=None,
            required_coverage_distance_m=100.0,
            azimuth_footprint_half_width_deg=1.0,
            disk_witness_samples=0,
            visible_margin_deg=1.0,
            obstructed_margin_deg=None,
        )
        self.assertFalse(result.physical_terrain_visibility_certified)

    def test_full_partial_and_occulted_classifications(self):
        flat = _profile({0.0: 0.0, 90.0: 0.0, 180.0: 0.0, 270.0: 0.0})
        high_terrain = _profile(
            {0.0: 5.0, 90.0: 5.0, 180.0: 5.0, 270.0: 5.0}
        )

        self.assertEqual(_classify(flat, 2.0).classification, "FULL")
        self.assertEqual(_classify(flat, 0.1).classification, "PARTIAL")
        self.assertEqual(
            _classify(high_terrain, 0.0).classification,
            "OCCULTED",
        )
        self.assertFalse(
            _classify(flat, 2.0).physical_terrain_visibility_certified
        )

    def test_finite_solar_radius_can_change_center_point_result(self):
        flat = _profile({0.0: 0.0, 90.0: 0.0, 180.0: 0.0, 270.0: 0.0})

        point_source = _classify(flat, 0.1, radius=0.0)
        finite_disk = _classify(flat, 0.1, radius=0.2)

        self.assertEqual(point_source.classification, "FULL")
        self.assertEqual(finite_disk.classification, "PARTIAL")

    def test_azimuth_dependent_ridge_blocks_only_part_of_disk(self):
        profile = _profile(
            {
                0.0: 0.4,
                0.1: 0.0,
                90.0: 0.0,
                180.0: 0.0,
                270.0: 0.0,
                359.9: 0.0,
            },
            azimuth_step=90.0,
        )

        result = _classify(
            profile,
            0.15,
            azimuth=0.05,
            radius=0.3,
            sample_spacing=0.05,
        )

        self.assertEqual(result.classification, "PARTIAL")
        self.assertGreater(result.visible_margin_deg, 0.0)
        self.assertLess(result.obstructed_margin_deg, 0.0)

    def test_azimuth_interpolation_wraps_across_zero(self):
        profile = _profile(
            {0.0: 0.0, 90.0: 1.0, 180.0: 1.0, 270.0: 1.0}
        )
        angles, rays = _sorted_rays(profile)
        seam_horizon = _horizon_at_azimuth(359.9, angles, rays, 100.0)

        result = _classify(
            profile,
            0.05,
            azimuth=359.9,
            radius=0.1,
        )

        self.assertAlmostEqual(seam_horizon, 1.0 / 900.0, places=10)
        self.assertEqual(result.classification, "PARTIAL")
        self.assertLessEqual(result.azimuth_footprint_half_width_deg, 1.0)

    def test_south_pole_uses_profile_azimuth_convention(self):
        profile = _profile(
            {
                0.0: 1.0,
                0.1: 1.0,
                89.9: -1.0,
                90.1: -1.0,
                180.0: 1.0,
                270.0: 1.0,
                359.9: 1.0,
            },
            azimuth_step=90.0,
        )

        along_plus_x = _classify(
            profile,
            0.1,
            azimuth=0.0,
            radius=0.05,
        )
        along_plus_y = _classify(
            profile,
            0.1,
            azimuth=90.0,
            radius=0.05,
        )

        self.assertEqual(along_plus_x.classification, "OCCULTED")
        self.assertEqual(along_plus_y.classification, "FULL")

    def test_near_zenith_is_stable_and_uses_all_azimuths(self):
        flat = _profile({0.0: 0.0, 90.0: 0.0, 180.0: 0.0, 270.0: 0.0})
        high_horizon = _profile(
            {
                0.0: 89.8,
                90.0: 89.8,
                180.0: 89.8,
                270.0: 89.8,
            }
        )
        one_incomplete = _profile(
            {0.0: 0.0, 90.0: 0.0, 180.0: 0.0, 270.0: 0.0},
            incomplete_azimuths=(180.0,),
        )

        visible = _classify(flat, 89.9, radius=0.2)
        vector_path = _classify(
            high_horizon,
            89.9,
            radius=0.2,
            sample_spacing=0.05,
        )
        uncertain = _classify(one_incomplete, 89.9, radius=0.2)

        self.assertEqual(visible.classification, "FULL")
        self.assertIsNone(visible.azimuth_footprint_half_width_deg)
        self.assertEqual(vector_path.classification, "PARTIAL")
        self.assertGreater(vector_path.disk_witness_samples, 0)
        self.assertIsNone(vector_path.azimuth_footprint_half_width_deg)
        self.assertEqual(uncertain.classification, "INDETERMINATE")

    def test_tangent_and_near_tangent_cases_are_conservative(self):
        flat = _profile({0.0: 0.0, 90.0: 0.0, 180.0: 0.0, 270.0: 0.0})

        tangent = _classify(flat, 0.25, radius=0.25, tolerance=1e-6)
        just_visible = _classify(flat, 0.2511, radius=0.25, tolerance=1e-4)
        near_tangent = _classify(flat, 0.25005, radius=0.25, tolerance=1e-4)
        just_partial = _classify(flat, 0.249, radius=0.25, tolerance=1e-4)

        self.assertEqual(tangent.classification, "INDETERMINATE")
        self.assertEqual(just_visible.classification, "FULL")
        self.assertEqual(near_tangent.classification, "INDETERMINATE")
        self.assertEqual(just_partial.classification, "PARTIAL")

    def test_incomplete_ray_inside_footprint_is_indeterminate(self):
        profile = _profile(
            {0.0: 0.0, 90.0: 0.0, 180.0: 0.0, 270.0: 0.0},
            incomplete_azimuths=(0.0,),
            partial_maximum_deg=-90.0,
        )

        result = _classify(profile, 10.0, radius=0.2)

        self.assertEqual(result.classification, "INDETERMINATE")
        self.assertIn("incomplete", result.reason)

    def test_incomplete_ray_outside_footprint_does_not_affect_result(self):
        profile = _profile(
            {0.0: 0.0, 90.0: 0.0, 180.0: 0.0, 270.0: 0.0},
            incomplete_azimuths=(180.0,),
        )

        result = _classify(
            profile,
            5.0,
            azimuth=0.0,
            radius=0.2,
        )

        self.assertEqual(result.classification, "FULL")

    def test_insufficient_radial_coverage_is_indeterminate(self):
        profile = _profile(
            {0.0: 0.0, 90.0: 0.0, 180.0: 0.0, 270.0: 0.0},
            max_distance=100.0,
        )

        result = _classify(profile, 10.0, required_distance=200.0)

        self.assertEqual(result.classification, "INDETERMINATE")
        self.assertIn("required search distance", result.reason)

    def test_short_individual_ray_is_indeterminate_despite_profile_maximum(self):
        profile = _profile(
            {0.0: 0.0, 90.0: 0.0, 180.0: 0.0, 270.0: 0.0},
            max_distance=100.0,
            short_coverage_azimuths=(0.0,),
            short_ray_distance=50.0,
        )

        result = _classify(profile, 10.0, required_distance=100.0)

        self.assertEqual(profile.max_distance_m, 100.0)
        self.assertEqual(result.classification, "INDETERMINATE")
        self.assertIn("short of", result.reason)

    def test_incomplete_partial_maximum_is_never_used_as_horizon(self):
        profile = _profile(
            {0.0: 0.0, 90.0: 0.0, 180.0: 0.0, 270.0: 0.0},
            incomplete_azimuths=(0.0,),
            partial_maximum_deg=-90.0,
        )

        result = _classify(profile, 10.0, radius=0.2)

        self.assertEqual(result.classification, "INDETERMINATE")
        self.assertIsNone(result.visible_margin_deg)
        self.assertIsNone(result.obstructed_margin_deg)

    def test_witness_budget_exhaustion_is_indeterminate(self):
        flat = _profile({0.0: 0.0, 90.0: 0.0, 180.0: 0.0, 270.0: 0.0})

        result = _classify(
            flat,
            0.1,
            radius=0.25,
            max_samples=1,
        )

        self.assertEqual(result.classification, "INDETERMINATE")
        self.assertIn("budget", result.reason)

    def test_witness_budget_limit_and_over_limit_validation(self):
        flat = _profile({0.0: 0.0, 90.0: 0.0, 180.0: 0.0, 270.0: 0.0})
        at_limit = _classify(
            flat,
            2.0,
            max_samples=MAX_DISK_WITNESS_SAMPLES,
        )
        self.assertEqual(at_limit.classification, "FULL")
        self.assertEqual(
            MAX_DISK_WITNESS_SAMPLES,
            100_000,
        )
        with self.assertRaisesRegex(ValueError, "operational limit"):
            _classify(
                flat,
                2.0,
                max_samples=MAX_DISK_WITNESS_SAMPLES + 1,
            )

    def test_invalid_and_extreme_tolerance_and_spacing_inputs(self):
        flat = _profile({0.0: 0.0, 90.0: 0.0, 180.0: 0.0, 270.0: 0.0})
        for tolerance in (
            0.0,
            -1e-6,
            float("nan"),
            float("inf"),
            -float("inf"),
            180.0,
            1e308,
        ):
            with self.subTest(tolerance=tolerance):
                with self.assertRaises(ValueError):
                    _classify(flat, 0.1, tolerance=tolerance)

        for spacing in (
            0.0,
            -1e-6,
            float("nan"),
            float("inf"),
            -float("inf"),
            181.0,
            1e308,
        ):
            with self.subTest(spacing=spacing):
                with self.assertRaises(ValueError):
                    _classify(flat, 0.1, sample_spacing=spacing)

        unresolved = _classify(
            flat,
            0.1,
            sample_spacing=5e-324,
        )
        self.assertEqual(unresolved.classification, "INDETERMINATE")
        self.assertIn("spacing", unresolved.reason)

    def test_zero_tolerance_is_rejected_near_tangent(self):
        flat = _profile({0.0: 0.0, 90.0: 0.0, 180.0: 0.0, 270.0: 0.0})
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            _classify(
                flat,
                0.25,
                radius=0.25,
                tolerance=0.0,
            )


if __name__ == "__main__":
    unittest.main()
