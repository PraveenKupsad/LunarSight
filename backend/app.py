import math
import sys
from pathlib import Path
from threading import Lock

from flask import Flask, jsonify, request
from flask_cors import CORS

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_PATH = str(PROJECT_ROOT / "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from lunarsight_science.ephemeris.earth_visibility import calculate_earth_visibility
from lunarsight_science.ephemeris.sun_illumination import (
    TerrainSunOptions,
    calculate_sun_illumination,
)

app = Flask(__name__)
CORS(app)

_science_calculation_lock = Lock()

_HTTP_STATUS_BY_RESULT = {
    "SUCCESS": 200,
    "INVALID_INPUT": 400,
    "MISSING_KERNELS": 503,
    "DEPENDENCY_ERROR": 503,
    "FRAME_UNSUPPORTED": 503,
    # DEM data is a server-side dependency; missing or invalid DEM data is 503.
    "TERRAIN_DATA_ERROR": 503,
    "CALCULATION_ERROR": 500,
}

_TERRAIN_OPTION_FIELDS = (
    "max_distance_m",
    "radial_step_m",
    "azimuth_step_deg",
    "required_coverage_distance_m",
    "classification_tolerance_deg",
    "disk_sample_spacing_deg",
    "max_disk_samples",
)


def _validated_science_payload(*, allow_sun_terrain=False):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, (
            jsonify({
                "status": "INVALID_REQUEST",
                "error": "Request body must be a valid JSON object.",
            }),
            400,
        )

    if not allow_sun_terrain and "use_terrain_horizon" in payload:
        return None, (
            jsonify({
                "status": "INVALID_REQUEST",
                "error": "use_terrain_horizon is not supported by this API.",
            }),
            400,
        )

    if not allow_sun_terrain and "terrain_options" in payload:
        return None, (
            jsonify({
                "status": "INVALID_REQUEST",
                "error": "terrain_options is not supported by this API endpoint.",
            }),
            400,
        )

    required_fields = (
        "latitude_deg",
        "longitude_deg",
        "start_time_utc",
        "end_time_utc",
    )
    missing_fields = [field for field in required_fields if field not in payload]
    if missing_fields:
        return None, (
            jsonify({
                "status": "INVALID_REQUEST",
                "error": f"Missing required fields: {', '.join(missing_fields)}.",
            }),
            400,
        )

    return payload, None


def _validated_sun_terrain_options(payload):
    use_terrain_horizon = payload.get("use_terrain_horizon", False)
    if not isinstance(use_terrain_horizon, bool):
        return None, None, (
            jsonify({
                "status": "INVALID_REQUEST",
                "error": "use_terrain_horizon must be a boolean.",
            }),
            400,
        )

    if not use_terrain_horizon:
        if "terrain_options" in payload:
            return None, None, (
                jsonify({
                    "status": "INVALID_REQUEST",
                    "error": (
                        "terrain_options may only be supplied when "
                        "use_terrain_horizon is true."
                    ),
                }),
                400,
            )
        return False, None, None

    if "terrain_options" not in payload:
        return None, None, (
            jsonify({
                "status": "INVALID_REQUEST",
                "error": (
                    "terrain_options is required when "
                    "use_terrain_horizon is true."
                ),
            }),
            400,
        )

    terrain_payload = payload["terrain_options"]
    if not isinstance(terrain_payload, dict):
        return None, None, (
            jsonify({
                "status": "INVALID_REQUEST",
                "error": "terrain_options must be a JSON object.",
            }),
            400,
        )

    missing_fields = [
        field for field in _TERRAIN_OPTION_FIELDS if field not in terrain_payload
    ]
    extra_fields = [
        field for field in terrain_payload if field not in _TERRAIN_OPTION_FIELDS
    ]
    if missing_fields:
        return None, None, (
            jsonify({
                "status": "INVALID_REQUEST",
                "error": (
                    "Missing terrain_options field(s): "
                    f"{', '.join(missing_fields)}."
                ),
            }),
            400,
        )
    if extra_fields:
        return None, None, (
            jsonify({
                "status": "INVALID_REQUEST",
                "error": (
                    "Unknown terrain_options field(s): "
                    f"{', '.join(extra_fields)}."
                ),
            }),
            400,
        )

    for field in _TERRAIN_OPTION_FIELDS:
        value = terrain_payload[field]
        if field == "max_disk_samples":
            if isinstance(value, bool) or not isinstance(value, int):
                return None, None, (
                    jsonify({
                        "status": "INVALID_REQUEST",
                        "error": (
                            "terrain_options.max_disk_samples must be an integer."
                        ),
                    }),
                    400,
                )
            continue

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, None, (
                jsonify({
                    "status": "INVALID_REQUEST",
                    "error": f"terrain_options.{field} must be a finite number.",
                }),
                400,
            )
        try:
            finite_value = math.isfinite(float(value))
        except OverflowError:
            finite_value = False
        if not finite_value:
            return None, None, (
                jsonify({
                    "status": "INVALID_REQUEST",
                    "error": f"terrain_options.{field} must be a finite number.",
                }),
                400,
            )

    return True, TerrainSunOptions(**terrain_payload), None


def _science_result_response(result):
    http_status = _HTTP_STATUS_BY_RESULT.get(result.get("status"), 500)
    safe_result = result
    status = result.get("status")
    details = result.get("details")
    if status == "MISSING_KERNELS" and (
        (isinstance(details, dict) and "kernel_dir" in details)
        or "error" in result
    ):
        safe_result = dict(result)
        safe_result["error"] = "Required SPICE kernels are unavailable."
        details = dict(details) if isinstance(details, dict) else {}
        details.pop("kernel_dir", None)
        safe_result["details"] = details
    elif status == "TERRAIN_DATA_ERROR" and "error" in result:
        safe_result = dict(result)
        safe_result["error"] = "Terrain data is unavailable or invalid."
    elif status == "CALCULATION_ERROR" and "error" in result:
        safe_result = dict(result)
        safe_result["error"] = "An unexpected science calculation error occurred."
    return jsonify(safe_result), http_status


@app.route("/")
def home():
    return jsonify({
        "project": "LunarSight",
        "message": "LunarSight Backend is running!",
        "status": "success"
    })

@app.route("/api/health")
def health():
    return jsonify({
        "status": "healthy"
    })


@app.route("/api/science/sun-illumination", methods=["POST"])
def sun_illumination():
    payload, error_response = _validated_science_payload(
        allow_sun_terrain=True,
    )
    if error_response is not None:
        return error_response

    use_terrain_horizon, terrain_options, error_response = (
        _validated_sun_terrain_options(payload)
    )
    if error_response is not None:
        return error_response

    try:
        with _science_calculation_lock:
            calculation_arguments = {
                "latitude_deg": payload["latitude_deg"],
                "longitude_deg": payload["longitude_deg"],
                "start_time_utc": payload["start_time_utc"],
                "end_time_utc": payload["end_time_utc"],
                "step_hours": payload.get("step_hours", 1.0),
            }
            if use_terrain_horizon:
                result = calculate_sun_illumination(
                    **calculation_arguments,
                    use_terrain_horizon=True,
                    terrain_options=terrain_options,
                )
            else:
                result = calculate_sun_illumination(**calculation_arguments)
    except Exception:
        app.logger.exception("Unexpected sun illumination calculation error.")
        return jsonify({
            "status": "CALCULATION_ERROR",
            "error": "An unexpected science calculation error occurred.",
        }), 500
    return _science_result_response(result)


@app.route("/api/science/earth-visibility", methods=["POST"])
def earth_visibility():
    payload, error_response = _validated_science_payload()
    if error_response is not None:
        return error_response

    try:
        with _science_calculation_lock:
            result = calculate_earth_visibility(
                latitude_deg=payload["latitude_deg"],
                longitude_deg=payload["longitude_deg"],
                start_time_utc=payload["start_time_utc"],
                end_time_utc=payload["end_time_utc"],
                step_hours=payload.get("step_hours", 1.0),
            )
    except Exception:
        app.logger.exception("Unexpected Earth visibility calculation error.")
        return jsonify({
            "status": "CALCULATION_ERROR",
            "error": "An unexpected science calculation error occurred.",
        }), 500
    return _science_result_response(result)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
    