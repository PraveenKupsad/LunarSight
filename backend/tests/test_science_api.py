"""Tests for the Flask science calculation endpoints."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
import unittest
from unittest.mock import patch

from backend import app as app_module


class ScienceApiTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        self.payload = {
            "latitude_deg": -89.44,
            "longitude_deg": 222.5,
            "start_time_utc": "2027-01-01T00:00:00Z",
            "end_time_utc": "2027-01-02T00:00:00Z",
        }

    def test_sun_illumination_forwards_arguments(self):
        expected = {"status": "SUCCESS", "timeline": []}
        with patch.object(
            app_module, "calculate_sun_illumination", return_value=expected
        ) as calculate:
            response = self.client.post(
                "/api/science/sun-illumination",
                json={**self.payload, "step_hours": 2.0},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        calculate.assert_called_once_with(
            latitude_deg=-89.44,
            longitude_deg=222.5,
            start_time_utc="2027-01-01T00:00:00Z",
            end_time_utc="2027-01-02T00:00:00Z",
            step_hours=2.0,
        )

    def test_earth_visibility_forwards_arguments_and_default_step(self):
        expected = {"status": "SUCCESS", "timeline": []}
        with patch.object(
            app_module, "calculate_earth_visibility", return_value=expected
        ) as calculate:
            response = self.client.post(
                "/api/science/earth-visibility",
                json=self.payload,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        calculate.assert_called_once_with(
            latitude_deg=-89.44,
            longitude_deg=222.5,
            start_time_utc="2027-01-01T00:00:00Z",
            end_time_utc="2027-01-02T00:00:00Z",
            step_hours=1.0,
        )

    def test_unexpected_sun_illumination_exception_returns_generic_500(self):
        with patch.object(
            app_module,
            "calculate_sun_illumination",
            side_effect=RuntimeError("internal detail"),
        ):
            response = self.client.post(
                "/api/science/sun-illumination",
                json=self.payload,
            )

        self.assertEqual(response.status_code, 500)
        self.assertTrue(response.is_json)
        self.assertEqual(
            response.get_json(),
            {
                "status": "CALCULATION_ERROR",
                "error": "An unexpected science calculation error occurred.",
            },
        )
        self.assertNotIn("internal detail", response.get_data(as_text=True))

    def test_unexpected_earth_visibility_exception_returns_generic_500(self):
        with patch.object(
            app_module,
            "calculate_earth_visibility",
            side_effect=RuntimeError("internal detail"),
        ):
            response = self.client.post(
                "/api/science/earth-visibility",
                json=self.payload,
            )

        self.assertEqual(response.status_code, 500)
        self.assertTrue(response.is_json)
        self.assertEqual(
            response.get_json(),
            {
                "status": "CALCULATION_ERROR",
                "error": "An unexpected science calculation error occurred.",
            },
        )
        self.assertNotIn("internal detail", response.get_data(as_text=True))

    def test_malformed_json_rejected(self):
        response = self.client.post(
            "/api/science/sun-illumination",
            data="{",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["status"], "INVALID_REQUEST")

    def test_non_object_and_missing_fields_rejected(self):
        non_object_response = self.client.post(
            "/api/science/earth-visibility",
            json=["not", "an", "object"],
        )
        missing_fields_response = self.client.post(
            "/api/science/sun-illumination",
            json={"latitude_deg": -89.0},
        )

        self.assertEqual(non_object_response.status_code, 400)
        self.assertEqual(non_object_response.get_json()["status"], "INVALID_REQUEST")
        self.assertEqual(missing_fields_response.status_code, 400)
        self.assertIn("Missing required fields", missing_fields_response.get_json()["error"])

    def test_invalid_base_numeric_inputs_return_invalid_input_for_both_endpoints(self):
        cases = (
            ("latitude_deg", True),
            ("longitude_deg", False),
            ("step_hours", True),
            ("latitude_deg", 10**400),
            ("longitude_deg", 10**400),
            ("step_hours", 10**400),
            ("longitude_deg", 2**53 + 1),
            ("step_hours", 1e100),
            ("step_hours", 1e-320),
            ("latitude_deg", "not a number"),
        )
        endpoints = (
            "/api/science/sun-illumination",
            "/api/science/earth-visibility",
        )
        for endpoint in endpoints:
            for field, value in cases:
                with self.subTest(endpoint=endpoint, field=field, value=repr(value)):
                    response = self.client.post(
                        endpoint,
                        json={**self.payload, field: value},
                    )

                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.get_json()["status"], "INVALID_INPUT")

    def test_sun_terrain_options_are_forwarded(self):
        terrain_options = {
            "max_distance_m": 12000.0,
            "radial_step_m": 40.0,
            "azimuth_step_deg": 2.5,
            "required_coverage_distance_m": 9000.0,
            "classification_tolerance_deg": 0.02,
            "disk_sample_spacing_deg": 0.1,
            "max_disk_samples": 2500,
        }
        expected = {"status": "SUCCESS", "timeline": []}
        with patch.object(
            app_module, "calculate_sun_illumination", return_value=expected
        ) as calculate:
            response = self.client.post(
                "/api/science/sun-illumination",
                json={
                    **self.payload,
                    "use_terrain_horizon": True,
                    "terrain_options": terrain_options,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        calculate.assert_called_once_with(
            latitude_deg=-89.44,
            longitude_deg=222.5,
            start_time_utc="2027-01-01T00:00:00Z",
            end_time_utc="2027-01-02T00:00:00Z",
            step_hours=1.0,
            use_terrain_horizon=True,
            terrain_options=app_module.TerrainSunOptions(**terrain_options),
        )

    def test_terrain_mode_requires_all_options(self):
        with patch.object(app_module, "calculate_sun_illumination") as calculate:
            response = self.client.post(
                "/api/science/sun-illumination",
                json={**self.payload, "use_terrain_horizon": True},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("terrain_options is required", response.get_json()["error"])
        calculate.assert_not_called()

    def test_terrain_options_must_be_an_object(self):
        with patch.object(app_module, "calculate_sun_illumination") as calculate:
            response = self.client.post(
                "/api/science/sun-illumination",
                json={
                    **self.payload,
                    "use_terrain_horizon": True,
                    "terrain_options": [],
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("JSON object", response.get_json()["error"])
        calculate.assert_not_called()

    def test_missing_terrain_option_fields_are_rejected(self):
        all_fields = {
            "max_distance_m": 12000.0,
            "radial_step_m": 40.0,
            "azimuth_step_deg": 2.5,
            "required_coverage_distance_m": 9000.0,
            "classification_tolerance_deg": 0.02,
            "disk_sample_spacing_deg": 0.1,
            "max_disk_samples": 2500,
        }
        for field in all_fields:
            with self.subTest(field=field):
                terrain_options = dict(all_fields)
                del terrain_options[field]
                with patch.object(
                    app_module, "calculate_sun_illumination"
                ) as calculate:
                    response = self.client.post(
                        "/api/science/sun-illumination",
                        json={
                            **self.payload,
                            "use_terrain_horizon": True,
                            "terrain_options": terrain_options,
                        },
                    )

                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.get_json()["error"])
                calculate.assert_not_called()

    def test_extra_terrain_option_fields_are_rejected(self):
        terrain_options = {
            "max_distance_m": 12000.0,
            "radial_step_m": 40.0,
            "azimuth_step_deg": 2.5,
            "required_coverage_distance_m": 9000.0,
            "classification_tolerance_deg": 0.02,
            "disk_sample_spacing_deg": 0.1,
            "max_disk_samples": 2500,
            "unrecognized": 1,
        }
        with patch.object(app_module, "calculate_sun_illumination") as calculate:
            response = self.client.post(
                "/api/science/sun-illumination",
                json={
                    **self.payload,
                    "use_terrain_horizon": True,
                    "terrain_options": terrain_options,
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("unrecognized", response.get_json()["error"])
        calculate.assert_not_called()

    def test_invalid_terrain_option_types_and_non_finite_values_are_rejected(self):
        valid_options = {
            "max_distance_m": 12000.0,
            "radial_step_m": 40.0,
            "azimuth_step_deg": 2.5,
            "required_coverage_distance_m": 9000.0,
            "classification_tolerance_deg": 0.02,
            "disk_sample_spacing_deg": 0.1,
            "max_disk_samples": 2500,
        }
        invalid_values = (
            ("max_distance_m", "12000"),
            ("radial_step_m", True),
            ("azimuth_step_deg", float("nan")),
            ("required_coverage_distance_m", float("inf")),
            ("classification_tolerance_deg", None),
            ("disk_sample_spacing_deg", False),
            ("max_disk_samples", True),
            ("max_disk_samples", 2500.0),
        )
        for field, value in invalid_values:
            with self.subTest(field=field, value=value):
                terrain_options = dict(valid_options)
                terrain_options[field] = value
                with patch.object(
                    app_module, "calculate_sun_illumination"
                ) as calculate:
                    response = self.client.post(
                        "/api/science/sun-illumination",
                        json={
                            **self.payload,
                            "use_terrain_horizon": True,
                            "terrain_options": terrain_options,
                        },
                    )

                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.get_json()["error"])
                calculate.assert_not_called()

    def test_terrain_options_are_rejected_when_terrain_mode_is_false(self):
        with patch.object(app_module, "calculate_sun_illumination") as calculate:
            response = self.client.post(
                "/api/science/sun-illumination",
                json={
                    **self.payload,
                    "use_terrain_horizon": False,
                    "terrain_options": {},
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("only be supplied", response.get_json()["error"])
        calculate.assert_not_called()

    def test_explicit_false_terrain_mode_preserves_legacy_call(self):
        expected = {"status": "SUCCESS", "timeline": []}
        with patch.object(
            app_module, "calculate_sun_illumination", return_value=expected
        ) as calculate:
            response = self.client.post(
                "/api/science/sun-illumination",
                json={**self.payload, "use_terrain_horizon": False},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        calculate.assert_called_once_with(
            latitude_deg=-89.44,
            longitude_deg=222.5,
            start_time_utc="2027-01-01T00:00:00Z",
            end_time_utc="2027-01-02T00:00:00Z",
            step_hours=1.0,
        )

    def test_earth_endpoint_rejects_terrain_fields(self):
        for terrain_fields in (
            {"use_terrain_horizon": False},
            {"terrain_options": {}},
        ):
            with self.subTest(fields=terrain_fields):
                with patch.object(
                    app_module, "calculate_earth_visibility"
                ) as calculate:
                    response = self.client.post(
                        "/api/science/earth-visibility",
                        json={**self.payload, **terrain_fields},
                    )

                self.assertEqual(response.status_code, 400)
                calculate.assert_not_called()

    def test_terrain_data_error_maps_to_503_without_exposing_path(self):
        result = {
            "status": "TERRAIN_DATA_ERROR",
            "error": r"DEM unavailable at C:\private\dem\site.lbl",
            "details": {"code": "DEM_LABEL_MISSING"},
        }
        with patch.object(
            app_module, "calculate_sun_illumination", return_value=result
        ):
            response = self.client.post(
                "/api/science/sun-illumination",
                json=self.payload,
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json()["error"],
            "Terrain data is unavailable or invalid.",
        )
        self.assertNotIn("private", response.get_data(as_text=True))

    def test_kernel_and_unsupported_frame_errors_map_to_503(self):
        missing_kernels = {
            "status": "MISSING_KERNELS",
            "error": r"Missing kernels in C:\private\spice",
            "details": {"kernel_dir": r"C:\private\spice"},
        }
        with patch.object(
            app_module, "calculate_sun_illumination", return_value=missing_kernels
        ):
            response = self.client.post(
                "/api/science/sun-illumination",
                json=self.payload,
            )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private", response.get_data(as_text=True))
        self.assertNotIn("kernel_dir", response.get_json()["details"])

        unsupported_frame = {
            "status": "FRAME_UNSUPPORTED",
            "error": "Unsupported frame",
        }
        with patch.object(
            app_module, "calculate_sun_illumination", return_value=unsupported_frame
        ):
            response = self.client.post(
                "/api/science/sun-illumination",
                json=self.payload,
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), unsupported_frame)

    def test_structured_calculation_error_does_not_expose_internal_details(self):
        result = {
            "status": "CALCULATION_ERROR",
            "error": r"Failure at C:\private\workspace\secret.log",
        }
        with patch.object(
            app_module, "calculate_sun_illumination", return_value=result
        ):
            response = self.client.post(
                "/api/science/sun-illumination",
                json=self.payload,
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json()["error"],
            "An unexpected science calculation error occurred.",
        )
        self.assertNotIn("private", response.get_data(as_text=True))

    def test_calculation_result_status_mapping(self):
        cases = (
            ("SUCCESS", 200),
            ("INVALID_INPUT", 400),
            ("MISSING_KERNELS", 503),
            ("DEPENDENCY_ERROR", 503),
            ("FRAME_UNSUPPORTED", 503),
            ("TERRAIN_DATA_ERROR", 503),
            ("CALCULATION_ERROR", 500),
        )
        for result_status, expected_http_status in cases:
            with self.subTest(result_status=result_status):
                result = {"status": result_status, "data": None}
                with patch.object(
                    app_module, "calculate_earth_visibility", return_value=result
                ):
                    response = self.client.post(
                        "/api/science/earth-visibility",
                        json=self.payload,
                    )

                self.assertEqual(response.status_code, expected_http_status)
                self.assertEqual(response.get_json(), result)

    def test_existing_health_routes_are_preserved(self):
        root_response = self.client.get("/")
        health_response = self.client.get("/api/health")

        self.assertEqual(root_response.status_code, 200)
        self.assertEqual(root_response.get_json()["project"], "LunarSight")
        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(health_response.get_json(), {"status": "healthy"})

    def test_science_calculations_are_serialized(self):
        first_started = Event()
        second_started = Event()
        second_lock_attempted = Event()
        release_first = Event()
        call_count = 0
        state_lock = Lock()

        class ObservedLock:
            def __init__(self):
                self._lock = Lock()
                self._attempt_count = 0
                self._attempt_lock = Lock()

            def __enter__(self):
                with self._attempt_lock:
                    self._attempt_count += 1
                    if self._attempt_count == 2:
                        second_lock_attempted.set()
                self._lock.acquire()
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                self._lock.release()

        def blocking_calculation(**_kwargs):
            nonlocal call_count
            with state_lock:
                call_count += 1
                current_call = call_count

            if current_call == 1:
                first_started.set()
                if not release_first.wait(timeout=3):
                    raise TimeoutError("Test did not release the first calculation.")
            else:
                second_started.set()
            return {"status": "SUCCESS"}

        def post_sun():
            with app_module.app.test_client() as client:
                return client.post(
                    "/api/science/sun-illumination",
                    json=self.payload,
                )

        def post_earth():
            with app_module.app.test_client() as client:
                return client.post(
                    "/api/science/earth-visibility",
                    json=self.payload,
                )

        with (
            patch.object(app_module, "_science_calculation_lock", ObservedLock()),
            patch.object(
                app_module,
                "calculate_sun_illumination",
                side_effect=blocking_calculation,
            ),
            patch.object(
                app_module,
                "calculate_earth_visibility",
                side_effect=blocking_calculation,
            ),
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                first_future = executor.submit(post_sun)
                self.assertTrue(first_started.wait(timeout=2))
                second_future = executor.submit(post_earth)
                try:
                    self.assertTrue(second_lock_attempted.wait(timeout=2))
                    self.assertFalse(second_started.is_set())
                finally:
                    release_first.set()

                self.assertEqual(first_future.result(timeout=2).status_code, 200)
                self.assertEqual(second_future.result(timeout=2).status_code, 200)
                self.assertTrue(second_started.is_set())


if __name__ == "__main__":
    unittest.main()
