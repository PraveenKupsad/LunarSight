"""Focused scientific unit tests for calculate_sun_illumination.

Tests error handling, strict input validation (NaN, Inf, UTC timezone),
safety limits on timeline generation, and distinct kernel categorization.
"""

import unittest
from pathlib import Path
import sys
import math
import tempfile
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from lunarsight_science.config import (
    SPICE_KERNELS_DIR,
    LUNAR_REFERENCE_FRAME,
    LUNAR_RADIUS_METRES,
)
from lunarsight_science.ephemeris.sun_illumination import (
    TerrainSunOptions,
    calculate_sun_illumination,
    check_required_kernels,
    parse_utc_iso_string,
)
from lunarsight_science.ephemeris import sun_illumination as sun_module
from lunarsight_science.terrain import (
    TerrainHorizonError,
    TerrainHorizonProfile,
    TerrainHorizonRay,
)
from lunarsight_science.terrain.terrain_horizon import local_site_frame


def _terrain_options(**overrides):
    values = {
        "max_distance_m": 100.0,
        "radial_step_m": 100.0,
        "azimuth_step_deg": 90.0,
        "required_coverage_distance_m": 100.0,
        "classification_tolerance_deg": 1e-6,
        "disk_sample_spacing_deg": 0.05,
        "max_disk_samples": 10_000,
    }
    values.update(overrides)
    return TerrainSunOptions(**values)


def _terrain_profile(
    latitude_deg=-90.0,
    longitude_deg=None,
    site_elevation_m=120.0,
    short_azimuths=(),
    max_distance_m=100.0,
    radial_step_m=100.0,
    azimuth_step_deg=90.0,
):
    short_azimuths = set(short_azimuths)
    rays = []
    azimuth_count = math.ceil(360.0 / azimuth_step_deg)
    for ray_index in range(azimuth_count):
        azimuth = ray_index * azimuth_step_deg
        complete = azimuth not in short_azimuths
        rays.append(
            TerrainHorizonRay(
                azimuth_deg=azimuth,
                max_elevation_angle_deg=0.0,
                max_elevation_distance_m=(
                    max_distance_m if complete else max_distance_m / 2.0
                ),
                requested_distance_m=(
                    max_distance_m if complete else max_distance_m / 2.0
                ),
                coverage_distance_m=(
                    max_distance_m if complete else max_distance_m / 2.0
                ),
                samples_attempted=1,
                valid_samples=1,
                valid=complete,
                complete=complete,
                status="COMPLETE" if complete else "OUT_OF_COVERAGE",
                error=None if complete else "synthetic limited ray",
            )
        )
    return TerrainHorizonProfile(
        site_latitude_deg=latitude_deg,
        site_longitude_deg=longitude_deg,
        site_elevation_m=site_elevation_m,
        max_distance_m=max_distance_m,
        radial_step_m=radial_step_m,
        azimuth_step_deg=azimuth_step_deg,
        rays=tuple(rays),
    )


def _run_mocked_sun_calculation(
    *,
    terrain_enabled=True,
    terrain_options=None,
    latitude_deg=-90.0,
    longitude_deg=0.0,
    sun_position_km=(149_597_870.7, 0.0, 0.0),
    profile=None,
    profile_error=None,
    reader_error=None,
    missing_label=False,
    missing_image=False,
    kernels_available=True,
    kernel_error=None,
    supported_frame=True,
    spice_error=None,
    cleanup_error=None,
    start_time_utc="2027-01-01T00:00:00Z",
    end_time_utc="2027-01-01T00:00:00Z",
    step_hours=1.0,
):
    if terrain_options is None and terrain_enabled:
        terrain_options = _terrain_options()
    if profile is None:
        profile = _terrain_profile(
            latitude_deg,
            None if latitude_deg == -90.0 else longitude_deg,
        )

    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        kernel_directory = root / "kernels"
        kernel_directory.mkdir()
        label_path = root / "terrain.lbl"
        image_path = root / "terrain.img"
        if not missing_label:
            label_path.touch()
        if not missing_image:
            image_path.touch()

        fake_spice = MagicMock()
        fake_spice.namfrm.return_value = 1 if supported_frame else 0
        fake_spice.str2et.return_value = 0.0
        fake_spice.spkpos.return_value = (
            np.asarray(sun_position_km, dtype=float),
            0.0,
        )
        fake_spice.spkpos.side_effect = spice_error
        fake_spice.kclear.side_effect = cleanup_error
        fake_reader = MagicMock()
        fake_reader.__enter__.return_value = fake_reader
        profile_error_effect = profile_error
        actual_classifier = sun_module.classify_solar_disk_against_terrain

        with (
            patch.object(sun_module, "HAS_SPICEYPY", True),
            patch.object(sun_module, "SPICE_KERNELS_DIR", kernel_directory),
            patch.object(sun_module, "LOLA_DEM_LABEL_PATH", label_path),
            patch.object(sun_module, "LOLA_DEM_IMAGE_PATH", image_path),
            patch.object(
                sun_module,
                "check_required_kernels",
                side_effect=kernel_error,
                return_value={
                    "all_present": kernels_available,
                    "found_files": [],
                    "missing_categories": [] if kernels_available else ["SPK"],
                },
            ) as kernel_check,
            patch.object(sun_module, "spice", fake_spice, create=True),
            patch.object(
                sun_module,
                "LolaDemReader",
                side_effect=reader_error,
                return_value=fake_reader,
            ) as reader_factory,
            patch.object(
                sun_module,
                "calculate_terrain_horizon",
                side_effect=profile_error_effect,
                return_value=profile,
            ) as profile_calculation,
            patch.object(
                sun_module,
                "classify_solar_disk_against_terrain",
                wraps=actual_classifier,
            ) as classifier,
        ):
            result = calculate_sun_illumination(
                latitude_deg=latitude_deg,
                longitude_deg=longitude_deg,
                start_time_utc=start_time_utc,
                end_time_utc=end_time_utc,
                step_hours=step_hours,
                use_terrain_horizon=terrain_enabled,
                terrain_options=terrain_options,
            )

    return (
        result,
        kernel_check,
        reader_factory,
        profile_calculation,
        classifier,
        fake_spice,
    )


class TestSunIllumination(unittest.TestCase):
    """Test suite for solar illumination ephemeris module."""

    def test_terrain_observer_geometry_and_profile_reuse(self):
        latitude = -45.0
        longitude = 30.0
        sun_position_km = (149_597_870.7, 20_000_000.0, -40_000_000.0)
        options = _terrain_options(
            max_distance_m=240.0,
            radial_step_m=60.0,
            azimuth_step_deg=120.0,
            required_coverage_distance_m=180.0,
            classification_tolerance_deg=0.003,
            disk_sample_spacing_deg=0.07,
            max_disk_samples=4321,
        )
        profile = _terrain_profile(
            latitude,
            longitude,
            site_elevation_m=120.0,
            max_distance_m=240.0,
            radial_step_m=60.0,
            azimuth_step_deg=120.0,
        )
        result, _, reader, profile_call, classifier, _ = (
            _run_mocked_sun_calculation(
                latitude_deg=latitude,
                longitude_deg=longitude,
                sun_position_km=sun_position_km,
                profile=profile,
                terrain_options=options,
                start_time_utc="2027-01-01T00:00:00Z",
                end_time_utc="2027-01-02T00:00:00Z",
                step_hours=24.0,
            )
        )

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(len(result["timeline"]), 2)
        reader.assert_called_once_with()
        profile_call.assert_called_once_with(
            reader.return_value.__enter__.return_value,
            latitude,
            longitude,
            max_distance_m=240.0,
            radial_step_m=60.0,
            azimuth_step_deg=120.0,
        )
        self.assertEqual(classifier.call_count, 2)

        phi = math.radians(latitude)
        lam = math.radians(longitude)
        site_unit = np.asarray(
            (
                math.cos(phi) * math.cos(lam),
                math.cos(phi) * math.sin(lam),
                math.sin(phi),
            )
        )
        site_vector = (LUNAR_RADIUS_METRES + 120.0) * site_unit
        terrain_topocentric = (
            np.asarray(sun_position_km, dtype=float) * 1000.0 - site_vector
        )
        distance = float(np.linalg.norm(terrain_topocentric))
        elevation = math.degrees(
            math.asin(
                float(np.dot(terrain_topocentric, site_unit) / distance)
            )
        )
        _, north, east = local_site_frame(latitude, longitude)
        azimuth = math.degrees(
            math.atan2(
                float(np.dot(terrain_topocentric, east)),
                float(np.dot(terrain_topocentric, north)),
            )
        ) % 360.0
        angular_radius = math.degrees(
            math.asin(sun_module.SOLAR_RADIUS_METRES / distance)
        )

        for classifier_call in classifier.call_args_list:
            self.assertAlmostEqual(classifier_call.args[0], elevation, places=12)
            self.assertAlmostEqual(classifier_call.args[1], azimuth, places=12)
            self.assertAlmostEqual(
                classifier_call.args[2],
                angular_radius,
                places=12,
            )
            self.assertIs(classifier_call.args[3], profile)
            self.assertEqual(
                classifier_call.kwargs["required_coverage_distance_m"],
                180.0,
            )
            self.assertEqual(
                classifier_call.kwargs["classification_tolerance_deg"],
                0.003,
            )
            self.assertEqual(
                classifier_call.kwargs["disk_sample_spacing_deg"],
                0.07,
            )
            self.assertEqual(classifier_call.kwargs["max_disk_samples"], 4321)

        terrain_result = result["timeline"][0]["terrain_sun_visibility"]
        self.assertEqual(
            terrain_result["classification_basis"],
            "SAMPLED_PIECEWISE_LINEAR_HORIZON",
        )
        self.assertFalse(terrain_result["physical_terrain_visibility_certified"])
        self.assertEqual(
            result["summary"]["terrain_horizon_profile"][
                "frame_validation_status"
            ],
            "PENDING_KERNELS",
        )
        self.assertAlmostEqual(
            terrain_result["sun_distance_m"],
            round(distance, 2),
            places=2,
        )

    def test_terrain_azimuth_matches_shared_basis_at_and_around_pole_threshold(self):
        for latitude in (-90.0, -89.99995, -89.99985):
            with self.subTest(latitude=latitude):
                longitude = 90.0
                profile = _terrain_profile(
                    latitude,
                    None if latitude == -90.0 else longitude,
                )
                sun_position_km = (200_000_000.0, 100_000_000.0, 30_000_000.0)
                result, _, _, _, classifier, _ = _run_mocked_sun_calculation(
                    latitude_deg=latitude,
                    longitude_deg=longitude,
                    sun_position_km=sun_position_km,
                    profile=profile,
                )

                site_up, north, east = local_site_frame(
                    latitude,
                    profile.site_longitude_deg,
                )
                site_vector = (
                    LUNAR_RADIUS_METRES + profile.site_elevation_m
                ) * np.asarray(site_up)
                topocentric = (
                    np.asarray(sun_position_km, dtype=float) * 1000.0
                    - site_vector
                )
                expected_azimuth = math.degrees(
                    math.atan2(
                        float(np.dot(topocentric, east)),
                        float(np.dot(topocentric, north)),
                    )
                ) % 360.0

                self.assertEqual(result["status"], "SUCCESS")
                self.assertAlmostEqual(
                    classifier.call_args.args[1],
                    expected_azimuth,
                    places=12,
                )
        self.assertNotAlmostEqual(
            _run_mocked_sun_calculation(
                latitude_deg=-89.99985,
                longitude_deg=90.0,
                sun_position_km=(200_000_000.0, 100_000_000.0, 30_000_000.0),
                profile=_terrain_profile(-89.99985, 90.0),
            )[4].call_args.args[1],
            _run_mocked_sun_calculation(
                latitude_deg=-89.99995,
                longitude_deg=90.0,
                sun_position_km=(200_000_000.0, 100_000_000.0, 30_000_000.0),
                profile=_terrain_profile(-89.99995, 90.0),
            )[4].call_args.args[1],
            places=2,
        )

    def test_terrain_mode_preserves_all_legacy_geometric_outputs(self):
        arguments = {
            "latitude_deg": -89.44,
            "longitude_deg": 222.5,
            "sun_position_km": (149_597_870.7, 20_000_000.0, -40_000_000.0),
            "start_time_utc": "2027-01-01T00:00:00Z",
            "end_time_utc": "2027-01-02T00:00:00Z",
            "step_hours": 24.0,
        }
        legacy, *_ = _run_mocked_sun_calculation(
            **arguments,
            terrain_enabled=False,
        )
        terrain, _, _, profile_call, classifier, _ = (
            _run_mocked_sun_calculation(**arguments)
        )

        self.assertEqual(legacy["status"], terrain["status"])
        for key in ("site", "reference_frame", "kernels_used", "time_range"):
            self.assertEqual(legacy[key], terrain[key])
        for key, value in legacy["summary"].items():
            if key == "terrain_shadow_notes":
                continue
            self.assertEqual(terrain["summary"][key], value)
        for legacy_point, terrain_point in zip(
            legacy["timeline"],
            terrain["timeline"],
        ):
            self.assertEqual(
                legacy_point,
                {
                    key: value
                    for key, value in terrain_point.items()
                    if key != "terrain_sun_visibility"
                },
            )
        self.assertEqual(terrain["summary"]["terrain_shadow_analysis"], "NOT_IMPLEMENTED")
        self.assertIn(
            "separate terrain_sun_visibility",
            terrain["summary"]["terrain_shadow_notes"],
        )
        self.assertEqual(profile_call.call_count, 1)
        self.assertEqual(classifier.call_count, 2)

    def test_incomplete_relevant_ray_produces_indeterminate_terrain_result(self):
        profile = _terrain_profile(short_azimuths=(0.0,))
        result, *_ = _run_mocked_sun_calculation(
            profile=profile,
            sun_position_km=(149_597_870.7, 0.0, -20_000_000.0),
        )

        terrain_result = result["timeline"][0]["terrain_sun_visibility"]
        self.assertEqual(terrain_result["classification"], "INDETERMINATE")
        self.assertIn("incomplete", terrain_result["reason"])
        self.assertFalse(terrain_result["physical_terrain_visibility_certified"])

    def test_terrain_options_are_validated_before_dem_or_spice_work(self):
        options = _terrain_options()
        with self.assertRaises(FrozenInstanceError):
            options.max_distance_m = 200.0

        invalid_options = (
            _terrain_options(radial_step_m=0.0),
            _terrain_options(required_coverage_distance_m=101.0),
            _terrain_options(max_disk_samples=100_001),
        )
        for options in invalid_options:
            with self.subTest(options=options):
                result, kernels, reader, profile, _, spice = (
                    _run_mocked_sun_calculation(terrain_options=options)
                )
                self.assertEqual(result["status"], "INVALID_INPUT")
                kernels.assert_not_called()
                reader.assert_not_called()
                profile.assert_not_called()
                spice.furnsh.assert_not_called()

        no_options = calculate_sun_illumination(
            -90.0,
            0.0,
            "2027-01-01T00:00:00Z",
            "2027-01-01T00:00:00Z",
            use_terrain_horizon=True,
        )
        self.assertEqual(no_options["status"], "INVALID_INPUT")
        self.assertIn("terrain_options is required", no_options["error"])

        disabled_with_options, *_ = _run_mocked_sun_calculation(
            terrain_enabled=False,
            terrain_options=_terrain_options(),
        )
        self.assertEqual(disabled_with_options["status"], "INVALID_INPUT")

    def test_terrain_data_and_spice_failures_are_structured(self):
        missing_label, *_ = _run_mocked_sun_calculation(missing_label=True)
        missing_image, *_ = _run_mocked_sun_calculation(missing_image=True)
        missing_kernels, _, reader, profile, _, _ = _run_mocked_sun_calculation(
            kernels_available=False,
        )
        unsupported_frame, _, reader_frame, profile_frame, _, _ = (
            _run_mocked_sun_calculation(supported_frame=False)
        )
        invalid_site, _, _, profile_error_call, _, _ = _run_mocked_sun_calculation(
            profile_error=TerrainHorizonError("synthetic invalid site sample"),
        )
        unreadable_image, *_ = _run_mocked_sun_calculation(
            reader_error=sun_module.LolaImageError("synthetic image read failure"),
        )

        self.assertEqual(missing_label["details"]["code"], "MISSING_DEM_LABEL")
        self.assertEqual(missing_image["details"]["code"], "MISSING_DEM_IMAGE")
        self.assertEqual(missing_kernels["status"], "MISSING_KERNELS")
        self.assertEqual(unsupported_frame["status"], "FRAME_UNSUPPORTED")
        self.assertEqual(
            unsupported_frame["details"]["code"],
            "FRAME_UNSUPPORTED",
        )
        self.assertEqual(invalid_site["details"]["code"], "INVALID_SITE_SAMPLE")
        self.assertEqual(unreadable_image["details"]["code"], "DEM_IMAGE_ERROR")
        self.assertEqual(missing_kernels["data"], None)
        reader.assert_not_called()
        profile.assert_not_called()
        reader_frame.assert_not_called()
        profile_frame.assert_not_called()
        profile_error_call.assert_called_once()
        for result in (
            missing_label,
            missing_image,
            missing_kernels,
            invalid_site,
            unreadable_image,
        ):
            self.assertNotIn("terrain.lbl", result["error"])
            self.assertNotIn("terrain.img", result["error"])

        spice_failure, *_ = _run_mocked_sun_calculation(
            spice_error=RuntimeError("kernel path should not be exposed"),
        )
        self.assertEqual(spice_failure["status"], "CALCULATION_ERROR")
        self.assertEqual(
            spice_failure["details"]["code"],
            "TERRAIN_SUN_CALCULATION_ERROR",
        )
        self.assertNotIn("kernel path", spice_failure["error"])

    def test_kernel_preflight_exception_is_structured_without_spice_work(self):
        result, kernel_check, reader, profile, _, spice = (
            _run_mocked_sun_calculation(
                kernel_error=OSError("synthetic kernel directory failure"),
            )
        )

        self.assertEqual(result["status"], "CALCULATION_ERROR")
        self.assertEqual(
            result["details"]["code"],
            "SPICE_KERNEL_PREFLIGHT_ERROR",
        )
        self.assertEqual(result["error"], "SPICE kernel preflight failed.")
        kernel_check.assert_called_once()
        reader.assert_not_called()
        profile.assert_not_called()
        spice.furnsh.assert_not_called()
        spice.kclear.assert_not_called()

    def test_cleanup_exception_does_not_escape_or_report_success(self):
        result, _, _, _, _, spice = _run_mocked_sun_calculation(
            cleanup_error=RuntimeError("synthetic cleanup failure"),
        )

        self.assertEqual(result["status"], "CALCULATION_ERROR")
        self.assertEqual(result["details"]["code"], "SPICE_CLEANUP_ERROR")
        self.assertEqual(result["error"], "SPICE kernel cleanup failed.")
        spice.kclear.assert_called_once()

    def test_cleanup_exception_does_not_hide_calculation_failure(self):
        result, _, _, _, _, spice = _run_mocked_sun_calculation(
            terrain_enabled=False,
            spice_error=RuntimeError("primary SPICE calculation failure"),
            cleanup_error=RuntimeError("secondary cleanup failure"),
        )

        self.assertEqual(result["status"], "CALCULATION_ERROR")
        self.assertEqual(
            result["error"],
            "SPICE calculation error: primary SPICE calculation failure",
        )
        self.assertNotIn("cleanup", result["error"].casefold())
        spice.kclear.assert_called_once()

    def test_missing_kernels_handling(self):
        """When SPICE kernels are not populated, calculate_sun_illumination must return

        MISSING_KERNELS status and an explicit diagnostic error message.
        """
        res = calculate_sun_illumination(
            latitude_deg=-89.44,
            longitude_deg=222.5,
            start_time_utc="2027-01-01T00:00:00Z",
            end_time_utc="2027-01-02T00:00:00Z",
            step_hours=2.0
        )
        self.assertEqual(res["status"], "MISSING_KERNELS")
        self.assertIn("Required SPICE kernels are not present", res["error"])
        self.assertIsNone(res["data"])
        self.assertIn("missing_categories", res["details"])
        self.assertTrue(len(res["details"]["missing_categories"]) > 0)

    def test_nan_and_inf_inputs_rejected(self):
        """NaN and infinite values must be strictly rejected."""
        # NaN latitude
        res = calculate_sun_illumination(float("nan"), 100.0, "2027-01-01T00:00:00Z", "2027-01-02T00:00:00Z")
        self.assertEqual(res["status"], "INVALID_INPUT")
        self.assertIn("finite real number", res["error"])

        # Inf longitude
        res = calculate_sun_illumination(-89.0, float("inf"), "2027-01-01T00:00:00Z", "2027-01-02T00:00:00Z")
        self.assertEqual(res["status"], "INVALID_INPUT")
        self.assertIn("finite real number", res["error"])

        # NaN step_hours
        res = calculate_sun_illumination(-89.0, 100.0, "2027-01-01T00:00:00Z", "2027-01-02T00:00:00Z", step_hours=float("nan"))
        self.assertEqual(res["status"], "INVALID_INPUT")
        self.assertIn("finite positive number", res["error"])

    def test_boolean_and_unsafe_numeric_inputs_are_rejected(self):
        base_arguments = {
            "latitude_deg": -89.0,
            "longitude_deg": 10.0,
            "start_time_utc": "2027-01-01T00:00:00Z",
            "end_time_utc": "2027-01-02T00:00:00Z",
            "step_hours": 1.0,
        }
        cases = (
            ("latitude_deg", True),
            ("longitude_deg", False),
            ("step_hours", True),
            ("latitude_deg", 10**400),
            ("longitude_deg", 10**400),
            ("step_hours", 10**400),
            ("longitude_deg", 2**53 + 1),
            ("step_hours", 1e100),
            ("latitude_deg", "not a number"),
        )
        for field, value in cases:
            with self.subTest(field=field, value=repr(value)):
                arguments = dict(base_arguments)
                arguments[field] = value
                result = calculate_sun_illumination(**arguments)
                self.assertEqual(result["status"], "INVALID_INPUT")

    def test_sub_microsecond_step_is_rejected_even_for_zero_duration(self):
        result = calculate_sun_illumination(
            latitude_deg=-89.0,
            longitude_deg=10.0,
            start_time_utc="2027-01-01T00:00:00Z",
            end_time_utc="2027-01-01T00:00:00Z",
            step_hours=1e-320,
        )

        self.assertEqual(result["status"], "INVALID_INPUT")
        self.assertIn("one microsecond", result["error"])

    def test_normal_inputs_pass_validation(self):
        with (
            patch.object(sun_module, "HAS_SPICEYPY", True),
            patch.object(
                sun_module,
                "check_required_kernels",
                return_value={
                    "all_present": False,
                    "found_files": [],
                    "missing_categories": ["SPK"],
                },
            ) as kernel_check,
        ):
            result = calculate_sun_illumination(
                latitude_deg=-89.0,
                longitude_deg=720.0,
                start_time_utc="2027-01-01T00:00:00Z",
                end_time_utc="2027-01-02T00:00:00Z",
                step_hours=1.0,
            )

        self.assertEqual(result["status"], "MISSING_KERNELS")
        kernel_check.assert_called_once()

    def test_invalid_latitude_bounds(self):
        """Latitude outside [-90, +90] must return INVALID_INPUT."""
        res = calculate_sun_illumination(
            latitude_deg=-95.0,
            longitude_deg=0.0,
            start_time_utc="2027-01-01T00:00:00Z",
            end_time_utc="2027-01-02T00:00:00Z"
        )
        self.assertEqual(res["status"], "INVALID_INPUT")
        self.assertIn("out of bounds", res["error"])

    def test_naive_timestamp_rejected(self):
        """Timestamps without explicit UTC indicator must be rejected."""
        # Missing 'Z' or '+00:00'
        res = calculate_sun_illumination(
            latitude_deg=-89.0,
            longitude_deg=10.0,
            start_time_utc="2027-01-01T00:00:00",
            end_time_utc="2027-01-02T00:00:00Z"
        )
        self.assertEqual(res["status"], "INVALID_INPUT")
        self.assertIn("explicit UTC timezone indicator", res["error"])

    def test_excessive_timesteps_prevented(self):
        """Requesting an excessive number of timesteps (> 8760) must be rejected."""
        # 10 years at 1-minute intervals would cause massive memory allocation
        res = calculate_sun_illumination(
            latitude_deg=-89.0,
            longitude_deg=10.0,
            start_time_utc="2027-01-01T00:00:00Z",
            end_time_utc="2037-01-01T00:00:00Z",
            step_hours=0.1
        )
        self.assertEqual(res["status"], "INVALID_INPUT")
        self.assertIn("exceeding the safety limit", res["error"])

    def test_kernel_checker_distinguishes_categories(self):
        """The kernel checker correctly identifies all 5 distinct kernel categories:

        LSK, PCK_TEXT, SPK, BPC, and FK.
        """
        fake_empty_dir = PROJECT_ROOT / "non_existent_kernel_dir"
        result = check_required_kernels(fake_empty_dir)
        self.assertFalse(result["all_present"])
        self.assertEqual(len(result["missing_categories"]), 5)
        # Ensure BPC and FK are distinguished
        categories_str = " ".join(result["missing_categories"])
        self.assertIn("BPC", categories_str)
        self.assertIn("FK", categories_str)


if __name__ == "__main__":
    unittest.main()
