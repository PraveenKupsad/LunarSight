"""Strict, read-only reader for the LDEM_875S_20M_FLOAT PDS3 product."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import DefaultDict, Iterable

import numpy as np
from pyproj import CRS, Transformer
from pyproj.exceptions import ProjError

from .. import config

PRODUCT_ID = "LDEM_875S_20M"
PRODUCT_VERSION_ID = "V2.1"
DATA_SET_ID = "LRO-L-LOLA-4-GDR-V1.0"
IMAGE_FILENAME = "LDEM_875S_20M_FLOAT.IMG"
LABEL_FILENAME = "LDEM_875S_20M_FLOAT.LBL"

ROWS = 7584
COLUMNS = 7584
SAMPLE_BYTES = 4
IMAGE_BYTES = ROWS * COLUMNS * SAMPLE_BYTES
IMAGE_OFFSET_BYTES = 0
RECORD_BYTES = COLUMNS * SAMPLE_BYTES
MAX_WINDOW_PIXELS = 1_000_000

MAP_SCALE_METRES = 20.0
REFERENCE_RADIUS_METRES = 1_737_400.0
LINE_PROJECTION_OFFSET = 3791.5
SAMPLE_PROJECTION_OFFSET = 3791.5
MIN_HEIGHT_KM = -4.379
MAX_HEIGHT_KM = 2.372
# The label reports the derived range to 0.001 km precision.
RANGE_TOLERANCE_KM = 0.0005

QUALITY_NOTE = (
    "The PDS label reports approximately 0.004% erroneous points but does "
    "not document their per-pixel representation or provide a quality mask."
)

_VALUE_KEY_RE = re.compile(r"^\^?[A-Z][A-Z0-9_]*$")
_NUMBER_RE = re.compile(
    r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)"
    r"(?:\s*<([^>]+)>)?$"
)


class LolaDemError(Exception):
    """Base exception for product, label, and sampling errors."""


class LolaLabelError(LolaDemError):
    """The PDS3 label is malformed or does not describe the expected product."""


class LolaImageError(LolaDemError):
    """The detached image is missing or has an invalid size."""


class LolaDataIntegrityError(LolaDemError):
    """A sample violates the product's documented data range."""


class OutOfCoverageError(LolaDemError):
    """A coordinate lies outside the image's projected pixel footprint."""


class InterpolationUnavailableError(LolaDemError):
    """A requested interpolation stencil extends beyond the available pixels."""


@dataclass(frozen=True)
class LolaDemMetadata:
    product_id: str
    product_version_id: str
    data_set_id: str
    rows: int
    columns: int
    sample_type: str
    sample_bits: int
    sample_units: str
    scaling_factor: float
    reference_radius_km: float
    map_scale_m: float
    line_projection_offset: float
    sample_projection_offset: float
    derived_minimum_km: float
    derived_maximum_km: float
    quality_mask_available: bool
    quality_note: str


@dataclass(frozen=True)
class PixelCoordinate:
    row: float
    col: float


@dataclass(frozen=True)
class GeoCoordinate:
    latitude_deg: float
    longitude_deg: float | None


@dataclass(frozen=True)
class TerrainWindow:
    elevation_m: np.ndarray
    valid_mask: np.ndarray
    row_start: int
    col_start: int


@dataclass(frozen=True)
class ElevationSample:
    elevation_m: float | None
    valid: bool
    status: str
    latitude_deg: float
    longitude_deg: float | None
    row: float
    col: float
    method: str


def _pvl_statements(text: str) -> Iterable[str]:
    """Split this product's PDS3 text into statements outside strings/comments."""
    statement: list[str] = []
    quote: str | None = None
    in_comment = False
    brace_depth = 0
    index = 0

    while index < len(text):
        char = text[index]
        next_pair = text[index:index + 2]

        if in_comment:
            if next_pair == "*/":
                in_comment = False
                statement.append(" ")
                index += 2
                continue
            if char == "\n":
                statement.append("\n")
            index += 1
            continue

        if quote is not None:
            statement.append(char)
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    statement.append(text[index + 1])
                    index += 2
                    continue
                quote = None
            index += 1
            continue

        if next_pair == "/*":
            in_comment = True
            statement.append(" ")
            index += 2
            continue

        if char in ("'", '"'):
            quote = char
            statement.append(char)
        elif char == "{":
            brace_depth += 1
            statement.append(char)
        elif char == "}":
            brace_depth -= 1
            if brace_depth < 0:
                raise LolaLabelError("PDS3 label contains an unmatched closing brace.")
            statement.append(char)
        elif char == "\n" and brace_depth == 0:
            value = "".join(statement).strip()
            if value:
                yield value
            statement.clear()
        else:
            statement.append(char)
        index += 1

    if in_comment:
        raise LolaLabelError("PDS3 label contains an unterminated comment.")
    if quote is not None:
        raise LolaLabelError("PDS3 label contains an unterminated quoted value.")
    if brace_depth != 0:
        raise LolaLabelError("PDS3 label contains an unterminated value group.")

    value = "".join(statement).strip()
    if value:
        yield value


def _parse_label_text(text: str) -> dict[tuple[str, ...], dict[str, list[str]]]:
    entries: DefaultDict[tuple[str, ...], DefaultDict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    object_stack: list[str] = []
    saw_end = False

    for statement in _pvl_statements(text):
        if saw_end:
            raise LolaLabelError("PDS3 label contains content after END.")
        if statement.upper() == "END":
            if object_stack:
                raise LolaLabelError("PDS3 label ended before closing all objects.")
            saw_end = True
            continue

        key, separator, raw_value = statement.partition("=")
        key = key.strip().upper()
        raw_value = raw_value.strip()
        if not separator or not _VALUE_KEY_RE.fullmatch(key) or not raw_value:
            raise LolaLabelError(f"Unsupported PDS3 label statement: {statement!r}")

        if key == "OBJECT":
            object_name = _parse_scalar(raw_value).upper()
            if not object_name:
                raise LolaLabelError("PDS3 OBJECT name cannot be empty.")
            object_stack.append(object_name)
        elif key == "END_OBJECT":
            object_name = _parse_scalar(raw_value).upper()
            if not object_stack or object_stack[-1] != object_name:
                raise LolaLabelError(
                    f"PDS3 object closure does not match {object_name!r}."
                )
            object_stack.pop()
        else:
            entries[tuple(object_stack)][key].append(raw_value)

    if not saw_end:
        raise LolaLabelError("PDS3 label is missing END.")
    if object_stack:
        raise LolaLabelError("PDS3 label ended before closing all objects.")

    return {
        scope: dict(values)
        for scope, values in entries.items()
    }


def _parse_scalar(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        raise LolaLabelError("PDS3 value cannot be empty.")
    if value[0] in ("'", '"'):
        quote = value[0]
        if len(value) < 2 or value[-1] != quote:
            raise LolaLabelError(f"Malformed quoted PDS3 value: {raw_value!r}")
        return value[1:-1].replace(quote + quote, quote)
    if any(char in value for char in "{}"):
        raise LolaLabelError(f"Expected scalar PDS3 value, got {raw_value!r}")
    return value


def _required_raw(
    entries: dict[tuple[str, ...], dict[str, list[str]]],
    scope: tuple[str, ...],
    key: str,
) -> str:
    values = entries.get(scope, {}).get(key.upper(), [])
    if len(values) != 1:
        raise LolaLabelError(
            f"Expected exactly one {key} value in {scope or ('label',)}, "
            f"found {len(values)}."
        )
    return values[0]


def _required_string(
    entries: dict[tuple[str, ...], dict[str, list[str]]],
    scope: tuple[str, ...],
    key: str,
) -> str:
    return _parse_scalar(_required_raw(entries, scope, key))


def _required_number(
    entries: dict[tuple[str, ...], dict[str, list[str]]],
    scope: tuple[str, ...],
    key: str,
    *,
    unit: str | None = None,
) -> float:
    raw_value = _required_raw(entries, scope, key)
    match = _NUMBER_RE.fullmatch(raw_value)
    if match is None:
        raise LolaLabelError(f"{key} is not a supported numeric value.")

    raw_number, raw_unit = match.groups()
    if unit is not None and (raw_unit is None or raw_unit.casefold() != unit.casefold()):
        raise LolaLabelError(f"{key} must use the documented {unit} unit.")
    if unit is None and raw_unit is not None:
        raise LolaLabelError(f"{key} unexpectedly specifies a unit.")
    return float(raw_number)


def _expect_string(
    entries: dict[tuple[str, ...], dict[str, list[str]]],
    scope: tuple[str, ...],
    key: str,
    expected: str,
) -> str:
    value = _required_string(entries, scope, key)
    if value.casefold() != expected.casefold():
        raise LolaLabelError(f"{key} must be {expected!r}, found {value!r}.")
    return value


def _expect_number(
    entries: dict[tuple[str, ...], dict[str, list[str]]],
    scope: tuple[str, ...],
    key: str,
    expected: float,
    *,
    unit: str | None = None,
) -> float:
    value = _required_number(entries, scope, key, unit=unit)
    if not math.isclose(value, expected, rel_tol=0.0, abs_tol=1e-9):
        raise LolaLabelError(f"{key} must be {expected}, found {value}.")
    return value


def _validate_label(
    label_path: Path,
    image_path: Path,
) -> LolaDemMetadata:
    try:
        text = label_path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise LolaLabelError(f"Could not read the PDS3 label: {label_path}") from exc

    entries = _parse_label_text(text)
    for scope, values in entries.items():
        for special_key in ("MISSING_CONSTANT", "INVALID_CONSTANT"):
            if special_key in values:
                raise LolaLabelError(
                    f"Unexpected {special_key}; this reader does not assume "
                    "a special-value encoding."
                )

    _expect_string(entries, (), "PDS_VERSION_ID", "PDS3")
    _expect_string(entries, (), "PRODUCT_VERSION_ID", PRODUCT_VERSION_ID)
    _expect_string(entries, (), "PRODUCT_ID", PRODUCT_ID)
    _expect_string(entries, (), "DATA_SET_ID", DATA_SET_ID)

    file_scope = ("UNCOMPRESSED_FILE",)
    image_scope = ("UNCOMPRESSED_FILE", "IMAGE")
    map_scope = ("IMAGE_MAP_PROJECTION",)

    file_name = _expect_string(entries, file_scope, "FILE_NAME", IMAGE_FILENAME)
    image_pointer = _expect_string(entries, file_scope, "^IMAGE", IMAGE_FILENAME)
    _expect_string(entries, file_scope, "RECORD_TYPE", "FIXED_LENGTH")
    if image_path.name.casefold() != file_name.casefold():
        raise LolaLabelError(
            f"Image path must name {file_name}, found {image_path.name}."
        )
    if (
        Path(image_pointer).name != image_pointer
        or "\\" in image_pointer
        or "/" in image_pointer
    ):
        raise LolaLabelError("The detached ^IMAGE pointer must be a basename only.")

    file_records = int(_expect_number(entries, file_scope, "FILE_RECORDS", ROWS))
    record_bytes = int(
        _expect_number(entries, file_scope, "RECORD_BYTES", RECORD_BYTES)
    )
    if file_records * record_bytes != IMAGE_BYTES:
        raise LolaLabelError("PDS3 record dimensions do not match the fixed image size.")

    lines = int(_expect_number(entries, image_scope, "LINES", ROWS))
    line_samples = int(
        _expect_number(entries, image_scope, "LINE_SAMPLES", COLUMNS)
    )
    if (lines, line_samples) != (ROWS, COLUMNS):
        raise LolaLabelError("PDS3 image dimensions do not match the selected product.")

    sample_type = _expect_string(entries, image_scope, "SAMPLE_TYPE", "PC_REAL")
    sample_bits = int(_expect_number(entries, image_scope, "SAMPLE_BITS", 32.0))
    sample_units = _expect_string(entries, image_scope, "UNIT", "KILOMETER")
    scaling_factor = _expect_number(entries, image_scope, "SCALING_FACTOR", 1.0)
    reference_radius_km = _expect_number(
        entries,
        image_scope,
        "OFFSET",
        REFERENCE_RADIUS_METRES / 1000.0,
    )
    derived_minimum_km = _expect_number(
        entries, image_scope, "DERIVED_MINIMUM", MIN_HEIGHT_KM
    )
    derived_maximum_km = _expect_number(
        entries, image_scope, "DERIVED_MAXIMUM", MAX_HEIGHT_KM
    )

    _expect_string(entries, map_scope, "MAP_PROJECTION_TYPE", "POLAR STEREOGRAPHIC")
    _expect_string(entries, map_scope, "KEYWORD_LATITUDE_TYPE", "PLANETOCENTRIC")
    _expect_string(entries, map_scope, "POSITIVE_LONGITUDE_DIRECTION", "EAST")
    _expect_string(entries, map_scope, "COORDINATE_SYSTEM_TYPE", "BODY-FIXED ROTATING")
    _expect_string(
        entries,
        map_scope,
        "COORDINATE_SYSTEM_NAME",
        "MEAN EARTH/POLAR AXIS OF DE421",
    )
    _expect_string(entries, map_scope, "^DATA_SET_MAP_PROJECTION", "DSMAP_POLAR.CAT")

    for axis in ("A", "B", "C"):
        _expect_number(
            entries,
            map_scope,
            f"{axis}_AXIS_RADIUS",
            REFERENCE_RADIUS_METRES / 1000.0,
            unit="km",
        )
    _expect_number(entries, map_scope, "CENTER_LATITUDE", -90.0, unit="deg")
    _expect_number(entries, map_scope, "CENTER_LONGITUDE", 0.0, unit="deg")
    _expect_number(entries, map_scope, "MAP_SCALE", MAP_SCALE_METRES, unit="m/pix")
    line_offset = _expect_number(
        entries,
        map_scope,
        "LINE_PROJECTION_OFFSET",
        LINE_PROJECTION_OFFSET,
        unit="pix",
    )
    sample_offset = _expect_number(
        entries,
        map_scope,
        "SAMPLE_PROJECTION_OFFSET",
        SAMPLE_PROJECTION_OFFSET,
        unit="pix",
    )
    _expect_number(entries, map_scope, "MAP_PROJECTION_ROTATION", 0.0)
    _expect_number(entries, map_scope, "LINE_FIRST_PIXEL", 1.0)
    _expect_number(entries, map_scope, "LINE_LAST_PIXEL", float(ROWS))
    _expect_number(entries, map_scope, "SAMPLE_FIRST_PIXEL", 1.0)
    _expect_number(entries, map_scope, "SAMPLE_LAST_PIXEL", float(COLUMNS))
    _expect_number(entries, map_scope, "MINIMUM_LATITUDE", -90.0, unit="deg")
    _expect_number(entries, map_scope, "MAXIMUM_LATITUDE", -87.5, unit="deg")

    try:
        image_size = image_path.stat().st_size
    except OSError as exc:
        raise LolaImageError(f"Could not stat the detached image: {image_path}") from exc
    expected_image_size = IMAGE_OFFSET_BYTES + IMAGE_BYTES
    if image_size != expected_image_size:
        raise LolaImageError(
            f"Image must be exactly {expected_image_size} bytes, found {image_size}."
        )

    return LolaDemMetadata(
        product_id=PRODUCT_ID,
        product_version_id=PRODUCT_VERSION_ID,
        data_set_id=DATA_SET_ID,
        rows=ROWS,
        columns=COLUMNS,
        sample_type=sample_type,
        sample_bits=sample_bits,
        sample_units=sample_units,
        scaling_factor=scaling_factor,
        reference_radius_km=reference_radius_km,
        map_scale_m=MAP_SCALE_METRES,
        line_projection_offset=line_offset,
        sample_projection_offset=sample_offset,
        derived_minimum_km=derived_minimum_km,
        derived_maximum_km=derived_maximum_km,
        quality_mask_available=False,
        quality_note=QUALITY_NOTE,
    )


def _finite_real(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be a finite real number.")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite real number.") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite real number.")
    return result


def _make_transformers() -> tuple[Transformer, Transformer]:
    radius = f"{REFERENCE_RADIUS_METRES:g}"
    lunar_geographic = CRS.from_proj4(
        f"+proj=longlat +R={radius} +no_defs +type=crs"
    )
    lunar_polar_stereographic = CRS.from_proj4(
        f"+proj=stere +lat_0=-90 +lon_0=0 +k=1 +R={radius} "
        "+units=m +no_defs +type=crs"
    )
    forward = Transformer.from_crs(
        lunar_geographic,
        lunar_polar_stereographic,
        always_xy=True,
    )
    inverse = Transformer.from_crs(
        lunar_polar_stereographic,
        lunar_geographic,
        always_xy=True,
    )
    return forward, inverse


class LolaDemReader:
    """Read windows and interpolated elevations from the fixed LOLA product."""

    def __init__(
        self,
        image_path: str | Path | None = None,
        label_path: str | Path | None = None,
    ) -> None:
        self.image_path = Path(image_path or config.LOLA_DEM_IMAGE_PATH)
        self.label_path = Path(label_path or config.LOLA_DEM_LABEL_PATH)
        if not self.label_path.is_file():
            raise LolaLabelError(f"PDS3 label does not exist: {self.label_path}")
        if not self.image_path.is_file():
            raise LolaImageError(f"Detached image does not exist: {self.image_path}")

        self.metadata = _validate_label(self.label_path, self.image_path)
        self._forward, self._inverse = _make_transformers()
        try:
            self._samples: np.memmap | None = np.memmap(
                self.image_path,
                dtype="<f4",
                mode="r",
                offset=IMAGE_OFFSET_BYTES,
                shape=(ROWS, COLUMNS),
                order="C",
            )
        except (OSError, ValueError) as exc:
            raise LolaImageError(
                f"Could not memory-map the validated LOLA image: {self.image_path}"
            ) from exc
        if self._samples.flags.writeable:
            self.close()
            raise LolaImageError("The LOLA image mapping must be read-only.")

    def __enter__(self) -> LolaDemReader:
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        samples = getattr(self, "_samples", None)
        if samples is None:
            return
        mapping = getattr(samples, "_mmap", None)
        self._samples = None
        if mapping is not None:
            mapping.close()

    def _ensure_open(self) -> np.memmap:
        if self._samples is None:
            raise LolaImageError("The LOLA reader is closed.")
        return self._samples

    def geographic_to_pixel(
        self,
        latitude_deg: float,
        longitude_deg: float | None = None,
    ) -> PixelCoordinate:
        latitude = _finite_real(latitude_deg, "latitude_deg")
        if latitude < -90.0 or latitude > 90.0:
            raise ValueError("latitude_deg must be within [-90, 90].")

        if longitude_deg is None:
            if latitude != -90.0:
                raise ValueError("longitude_deg is required away from the south pole.")
            x = y = 0.0
        else:
            longitude = _finite_real(longitude_deg, "longitude_deg") % 360.0
            if latitude == -90.0:
                x = y = 0.0
            else:
                try:
                    x, y = self._forward.transform(
                        longitude,
                        latitude,
                        errcheck=True,
                    )
                except (ProjError, ValueError) as exc:
                    raise ValueError("Could not project the lunar coordinate.") from exc

        col = SAMPLE_PROJECTION_OFFSET + x / MAP_SCALE_METRES
        row = LINE_PROJECTION_OFFSET - y / MAP_SCALE_METRES
        self._ensure_in_footprint(row, col)
        return PixelCoordinate(row=float(row), col=float(col))

    def pixel_to_geographic(self, row: float, col: float) -> GeoCoordinate:
        row_value = _finite_real(row, "row")
        col_value = _finite_real(col, "col")
        self._ensure_in_footprint(row_value, col_value)

        x = (col_value - SAMPLE_PROJECTION_OFFSET) * MAP_SCALE_METRES
        y = -(row_value - LINE_PROJECTION_OFFSET) * MAP_SCALE_METRES
        if x == 0.0 and y == 0.0:
            return GeoCoordinate(latitude_deg=-90.0, longitude_deg=None)

        try:
            longitude, latitude = self._inverse.transform(x, y, errcheck=True)
        except (ProjError, ValueError) as exc:
            raise ValueError("Could not inverse-project the lunar pixel coordinate.") from exc
        return GeoCoordinate(
            latitude_deg=float(latitude),
            longitude_deg=float(longitude % 360.0),
        )

    @staticmethod
    def _ensure_in_footprint(row: float, col: float) -> None:
        if not (
            -0.5 <= row <= ROWS - 0.5
            and -0.5 <= col <= COLUMNS - 0.5
        ):
            raise OutOfCoverageError(
                "Coordinate lies outside the projected LOLA image footprint."
            )

    def read_window(
        self,
        row_start: int,
        row_stop: int,
        col_start: int,
        col_stop: int,
    ) -> TerrainWindow:
        """Read a 0-based, half-open window containing at most one million cells."""
        samples = self._ensure_open()
        indexes = (row_start, row_stop, col_start, col_stop)
        if any(isinstance(value, (bool, np.bool_)) for value in indexes):
            raise ValueError("Window bounds must be integers, not booleans.")
        if any(not isinstance(value, (int, np.integer)) for value in indexes):
            raise ValueError("Window bounds must be integers.")
        if not (
            0 <= row_start < row_stop <= ROWS
            and 0 <= col_start < col_stop <= COLUMNS
        ):
            raise ValueError("Window must be non-empty and inside the image bounds.")
        if (row_stop - row_start) * (col_stop - col_start) > MAX_WINDOW_PIXELS:
            raise ValueError(
                f"Window cannot exceed {MAX_WINDOW_PIXELS} pixels."
            )

        raw = samples[row_start:row_stop, col_start:col_stop]
        valid_mask = np.isfinite(raw)
        finite_samples = raw[valid_mask]
        minimum = self.metadata.derived_minimum_km - RANGE_TOLERANCE_KM
        maximum = self.metadata.derived_maximum_km + RANGE_TOLERANCE_KM
        if finite_samples.size and (
            np.any(finite_samples < minimum) or np.any(finite_samples > maximum)
        ):
            raise LolaDataIntegrityError(
                "A finite sample falls outside the label's documented range "
                f"with rounding tolerance [{minimum}, {maximum}] km."
            )

        elevation_m = np.asarray(raw, dtype=np.float64) * 1000.0
        valid_mask = np.asarray(valid_mask, dtype=np.bool_)
        elevation_m.setflags(write=False)
        valid_mask.setflags(write=False)
        return TerrainWindow(
            elevation_m=elevation_m,
            valid_mask=valid_mask,
            row_start=int(row_start),
            col_start=int(col_start),
        )

    @staticmethod
    def _axis_bracket(value: float, limit: int, name: str) -> tuple[int, int, float]:
        nearest = round(value)
        if math.isclose(value, nearest, rel_tol=0.0, abs_tol=1e-12):
            index = int(nearest)
            if 0 <= index < limit:
                return index, index, 0.0

        lower = math.floor(value)
        upper = lower + 1
        if lower < 0 or upper >= limit:
            raise InterpolationUnavailableError(
                f"Bilinear interpolation requires in-bounds {name} neighbours."
            )
        return lower, upper, value - lower

    def sample_elevation(
        self,
        latitude_deg: float,
        longitude_deg: float | None = None,
    ) -> ElevationSample:
        coordinate = self.geographic_to_pixel(latitude_deg, longitude_deg)
        row0, row1, row_fraction = self._axis_bracket(
            coordinate.row, ROWS, "row"
        )
        col0, col1, col_fraction = self._axis_bracket(
            coordinate.col, COLUMNS, "column"
        )
        window = self.read_window(
            min(row0, row1),
            max(row0, row1) + 1,
            min(col0, col1),
            max(col0, col1) + 1,
        )

        row_indexes = (row0 - window.row_start, row1 - window.row_start)
        col_indexes = (col0 - window.col_start, col1 - window.col_start)
        values = np.array(
            [
                [
                    window.elevation_m[row_indexes[0], col_indexes[0]],
                    window.elevation_m[row_indexes[0], col_indexes[1]],
                ],
                [
                    window.elevation_m[row_indexes[1], col_indexes[0]],
                    window.elevation_m[row_indexes[1], col_indexes[1]],
                ],
            ],
            dtype=np.float64,
        )
        valid = np.array(
            [
                [
                    window.valid_mask[row_indexes[0], col_indexes[0]],
                    window.valid_mask[row_indexes[0], col_indexes[1]],
                ],
                [
                    window.valid_mask[row_indexes[1], col_indexes[0]],
                    window.valid_mask[row_indexes[1], col_indexes[1]],
                ],
            ],
            dtype=np.bool_,
        )

        normalized_longitude = (
            None
            if latitude_deg == -90.0
            else float(longitude_deg) % 360.0
        )
        if not np.all(valid):
            return ElevationSample(
                elevation_m=None,
                valid=False,
                status="INVALID_SAMPLE",
                latitude_deg=float(latitude_deg),
                longitude_deg=normalized_longitude,
                row=coordinate.row,
                col=coordinate.col,
                method="bilinear",
            )

        upper = (
            values[0, 0] * (1.0 - col_fraction)
            + values[0, 1] * col_fraction
        )
        lower = (
            values[1, 0] * (1.0 - col_fraction)
            + values[1, 1] * col_fraction
        )
        elevation_m = upper * (1.0 - row_fraction) + lower * row_fraction

        return ElevationSample(
            elevation_m=float(elevation_m),
            valid=True,
            status="OK",
            latitude_deg=float(latitude_deg),
            longitude_deg=normalized_longitude,
            row=coordinate.row,
            col=coordinate.col,
            method="bilinear",
        )
