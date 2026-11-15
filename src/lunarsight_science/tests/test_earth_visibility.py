"""Focused scientific unit tests for calculate_earth_visibility.

Tests error handling, strict input validation (NaN, Inf, explicit UTC timezone),
safety limits on timeline generation, missing-kernel handling, and geometric
visibility classifications.
"""

import unittest
from pathlib import Path
import sys
import math
import tempfile
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from lunarsight_science.config import (
    SPICE_KERNELS_DIR,
    LUNAR_REFERENCE_FRAME,
    LUNAR_RADIUS_METRES,
)
from lunarsight_science.ephemeris.earth_visibility import (
    calculate_earth_visibility,
    check_required_kernels,
    parse_utc_iso_string,
    classify_earth_disk_visibility,
    EARTH_EQUATORIAL_RADIUS_METRES,
)
from lunarsight_science.ephemeris import earth_visibility as earth_module


class TestEarthVisibility(unittest.TestCase):
    """Test suite for Earth visibility ephemeris module."""

    def _run_mocked_calculation(
        self,
        *,
        spice_error=None,
        cleanup_error=None,
    ):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fake_spice = MagicMock()
            fake_spice.namfrm.return_value = 1
            fake_spice.spkpos.return_value = (
                (149_597_870.7, 0.0, 0.0),
                0.0,
            )
            fake_spice.spkpos.side_effect = spice_error
            fake_spice.kclear.side_effect = cleanup_error
            with (
                patch.object(earth_module, "HAS_SPICEYPY", True),
                patch.object(
                    earth_module,
                    "SPICE_KERNELS_DIR",
                    Path(temporary_directory),
                ),
                patch.object(
                    earth_module,
                    "check_required_kernels",
                    return_value={"all_present": True},
                ),
                patch.object(earth_module, "spice", fake_spice),
            ):
                result = calculate_earth_visibility(
                    latitude_deg=-89.44,
                    longitude_deg=222.5,
                    start_time_utc="2027-01-01T00:00:00Z",
                    end_time_utc="2027-01-01T00:00:00Z",
                )
        return result, fake_spice

    def test_missing_kernels_handling(self):
        """When SPICE kernels are not present, calculate_earth_visibility must return

        MISSING_KERNELS status and explicit diagnostic details.
        """
        res = calculate_earth_visibility(
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
        res = calculate_earth_visibility(float("nan"), 100.0, "2027-01-01T00:00:00Z", "2027-01-02T00:00:00Z")
        self.assertEqual(res["status"], "INVALID_INPUT")
        self.assertIn("finite real number", res["error"])

        # Inf longitude
        res = calculate_earth_visibility(-89.0, float("inf"), "2027-01-01T00:00:00Z", "2027-01-02T00:00:00Z")
        self.assertEqual(res["status"], "INVALID_INPUT")
        self.assertIn("finite real number", res["error"])

        # NaN step_hours
        res = calculate_earth_visibility(-89.0, 100.0, "2027-01-01T00:00:00Z", "2027-01-02T00:00:00Z", step_hours=float("nan"))
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
                result = calculate_earth_visibility(**arguments)
                self.assertEqual(result["status"], "INVALID_INPUT")

    def test_sub_microsecond_step_is_rejected_even_for_zero_duration(self):
        result = calculate_earth_visibility(
            latitude_deg=-89.0,
            longitude_deg=10.0,
            start_time_utc="2027-01-01T00:00:00Z",
            end_time_utc="2027-01-01T00:00:00Z",
            step_hours=1e-320,
        )

        self.assertEqual(result["status"], "INVALID_INPUT")
        self.assertIn("one microsecond", result["error"])

    def test_normal_inputs_pass_validation(self):
        result, fake_spice = self._run_mocked_calculation()

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["site"]["longitude_deg"], 222.5)
        fake_spice.spkpos.assert_called_once()

    def test_invalid_latitude_bounds(self):
        """Latitude outside [-90, +90] must return INVALID_INPUT."""
        res = calculate_earth_visibility(
            latitude_deg=-95.0,
            longitude_deg=0.0,
            start_time_utc="2027-01-01T00:00:00Z",
            end_time_utc="2027-01-02T00:00:00Z"
        )
        self.assertEqual(res["status"], "INVALID_INPUT")
        self.assertIn("out of bounds", res["error"])

    def test_naive_timestamp_rejected(self):
        """Timestamps without explicit UTC indicator must be rejected."""
        res = calculate_earth_visibility(
            latitude_deg=-89.0,
            longitude_deg=10.0,
            start_time_utc="2027-01-01T00:00:00",
            end_time_utc="2027-01-02T00:00:00Z"
        )
        self.assertEqual(res["status"], "INVALID_INPUT")
        self.assertIn("explicit known UTC timezone", res["error"])

    def test_unknown_utc_offset_rejected(self):
        """The ISO 8601 '-00:00' unknown offset must not be accepted as UTC."""
        self.assertIsNone(parse_utc_iso_string("2027-01-01T00:00:00-00:00"))

    def test_earth_disk_visibility_classification(self):
        """Earth disk visibility is classified as FULL, PARTIAL, or OCCULTED."""
        cases = (
            (2.0, 1.0, ("FULL", True)),
            (0.0, 1.0, ("PARTIAL", True)),
            (-2.0, 1.0, ("OCCULTED", False)),
        )
        for elevation_deg, angular_radius_deg, expected in cases:
            with self.subTest(elevation_deg=elevation_deg):
                self.assertEqual(
                    classify_earth_disk_visibility(elevation_deg, angular_radius_deg),
                    expected,
                )

    def test_excessive_timesteps_prevented(self):
        """Requesting an excessive number of timesteps (> 8760) must be rejected."""
        res = calculate_earth_visibility(
            latitude_deg=-89.0,
            longitude_deg=10.0,
            start_time_utc="2027-01-01T00:00:00Z",
            end_time_utc="2037-01-01T00:00:00Z",
            step_hours=0.1
        )
        self.assertEqual(res["status"], "INVALID_INPUT")
        self.assertIn("exceeding the safety limit", res["error"])

    def test_earth_physical_radius_constant(self):
        """Earth radius used for angular size matches IAU/WGS84 equatorial radius."""
        self.assertEqual(EARTH_EQUATORIAL_RADIUS_METRES, 6378137.0)

    def test_kernel_checker_distinguishes_categories(self):
        """The kernel checker correctly identifies all 5 distinct kernel categories."""
        fake_empty_dir = PROJECT_ROOT / "non_existent_kernel_dir"
        result = check_required_kernels(fake_empty_dir)
        self.assertFalse(result["all_present"])
        self.assertEqual(len(result["missing_categories"]), 5)
        categories_str = " ".join(result["missing_categories"])
        self.assertIn("BPC", categories_str)
        self.assertIn("FK", categories_str)

    def test_cleanup_failure_after_success_returns_structured_error(self):
        result, fake_spice = self._run_mocked_calculation(
            cleanup_error=RuntimeError("synthetic cleanup failure"),
        )

        self.assertEqual(result["status"], "CALCULATION_ERROR")
        self.assertEqual(result["error"], "SPICE kernel cleanup failed.")
        self.assertEqual(
            result["details"]["code"],
            "SPICE_CLEANUP_ERROR",
        )
        self.assertIsNone(result["data"])
        fake_spice.kclear.assert_called_once()

    def test_cleanup_failure_does_not_replace_calculation_failure(self):
        result, fake_spice = self._run_mocked_calculation(
            spice_error=RuntimeError("primary SPICE calculation failure"),
            cleanup_error=RuntimeError("secondary cleanup failure"),
        )

        self.assertEqual(
            result,
            {
                "status": "CALCULATION_ERROR",
                "error": (
                    "SPICE calculation error: "
                    "primary SPICE calculation failure"
                ),
                "data": None,
            },
        )
        fake_spice.kclear.assert_called_once()


if __name__ == "__main__":
    unittest.main()
