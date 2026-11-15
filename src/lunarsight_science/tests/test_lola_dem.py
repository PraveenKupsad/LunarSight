"""Tests for the strict LDEM_875S_20M_FLOAT PDS3 reader."""

import math
from pathlib import Path
import struct
import sys
import tempfile
import textwrap
import unittest

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from lunarsight_science.terrain.lola_dem import (
    IMAGE_BYTES,
    IMAGE_FILENAME,
    IMAGE_OFFSET_BYTES,
    LABEL_FILENAME,
    LolaDataIntegrityError,
    LolaDemReader,
    LolaImageError,
    LolaLabelError,
    OutOfCoverageError,
)


VALID_LABEL = textwrap.dedent(
    """\
    PDS_VERSION_ID = "PDS3"
    PRODUCT_VERSION_ID = "V2.1"
    PRODUCT_ID = "LDEM_875S_20M"
    DATA_SET_ID = "LRO-L-LOLA-4-GDR-V1.0"
    MISSION_PHASE_NAME = {"COMMISSIONING",
                          "NOMINAL MISSION"}
    DESCRIPTION = "A multiline description with 'quoted text'
      and more content."

    OBJECT = UNCOMPRESSED_FILE
      FILE_NAME = "LDEM_875S_20M_FLOAT.IMG"
      RECORD_TYPE = FIXED_LENGTH
      FILE_RECORDS = 7584
      RECORD_BYTES = 30336
      ^IMAGE = "LDEM_875S_20M_FLOAT.IMG"
      OBJECT = IMAGE
        NAME = HEIGHT
        LINES = 7584
        LINE_SAMPLES = 7584
        DERIVED_MINIMUM = -4.379
        DERIVED_MAXIMUM = 2.372
        SAMPLE_TYPE = PC_REAL
        SAMPLE_BITS = 32
        UNIT = KILOMETER
        SCALING_FACTOR = 1
        OFFSET = 1737.4
      END_OBJECT = IMAGE
    END_OBJECT = UNCOMPRESSED_FILE

    OBJECT = IMAGE_MAP_PROJECTION
      ^DATA_SET_MAP_PROJECTION = "DSMAP_POLAR.CAT"
      MAP_PROJECTION_TYPE = "POLAR STEREOGRAPHIC"
      KEYWORD_LATITUDE_TYPE = "PLANETOCENTRIC"
      A_AXIS_RADIUS = 1737.4 <km>
      B_AXIS_RADIUS = 1737.4 <km>
      C_AXIS_RADIUS = 1737.4 <km>
      POSITIVE_LONGITUDE_DIRECTION = "EAST"
      CENTER_LATITUDE = -90 <deg>
      CENTER_LONGITUDE = 0 <deg>
      MAP_SCALE = 20 <m/pix>
      MINIMUM_LATITUDE = -90 <deg>
      MAXIMUM_LATITUDE = -87.5 <deg>
      LINE_FIRST_PIXEL = 1
      LINE_LAST_PIXEL = 7584
      SAMPLE_FIRST_PIXEL = 1
      SAMPLE_LAST_PIXEL = 7584
      MAP_PROJECTION_ROTATION = 0.0
      LINE_PROJECTION_OFFSET = 3791.5 <pix>
      SAMPLE_PROJECTION_OFFSET = 3791.5 <pix>
      COORDINATE_SYSTEM_TYPE = "BODY-FIXED ROTATING"
      COORDINATE_SYSTEM_NAME = "MEAN EARTH/POLAR AXIS OF DE421"
    END_OBJECT = IMAGE_MAP_PROJECTION

    /* A comment containing text that resembles an assignment:
       MISSING_CONSTANT = -9999
    */
    END
    """
)


class TestLolaDemReader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temporary_directory = tempfile.TemporaryDirectory()
        cls.directory = Path(cls._temporary_directory.name)
        cls.image_path = cls.directory / IMAGE_FILENAME
        cls.label_path = cls.directory / LABEL_FILENAME
        with cls.image_path.open("wb") as image_file:
            image_file.truncate(IMAGE_BYTES)

    @classmethod
    def tearDownClass(cls):
        cls._temporary_directory.cleanup()

    def setUp(self):
        self.label_path.write_text(VALID_LABEL, encoding="ascii")
        if self.image_path.stat().st_size != IMAGE_BYTES:
            with self.image_path.open("r+b") as image_file:
                image_file.truncate(IMAGE_BYTES)
        reset_locations = (
            (10, 10),
            (10, 11),
            (3791, 3791),
            (3791, 3792),
            (3792, 3791),
            (3792, 3792),
        )
        with self.image_path.open("r+b") as image_file:
            for row, col in reset_locations:
                image_file.seek((row * 7584 + col) * 4)
                image_file.write(b"\x00\x00\x00\x00")
        self.reader = LolaDemReader(self.image_path, self.label_path)

    def tearDown(self):
        self.reader.close()

    def _reopen_with_sample(self, row, col, value):
        self.reader.close()
        with self.image_path.open("r+b") as image_file:
            image_file.seek((row * 7584 + col) * 4)
            image_file.write(struct.pack("<f", value))
        self.reader = LolaDemReader(self.image_path, self.label_path)

    def _replace_label(self, old, new):
        self.reader.close()
        label = self.label_path.read_text(encoding="ascii")
        self.label_path.write_text(label.replace(old, new, 1), encoding="ascii")

    def test_valid_label_opens_read_only_and_exposes_quality_limitation(self):
        self.assertEqual(self.reader.metadata.product_id, "LDEM_875S_20M")
        self.assertEqual(self.reader.metadata.rows, 7584)
        self.assertFalse(self.reader.metadata.quality_mask_available)
        self.assertIn("0.004%", self.reader.metadata.quality_note)
        self.assertFalse(self.reader._samples.flags.writeable)

    def test_official_filename_only_image_pointer_uses_zero_byte_offset(self):
        self.assertEqual(self.reader._samples.offset, IMAGE_OFFSET_BYTES)
        self.assertEqual(IMAGE_OFFSET_BYTES, 0)

    def test_rejects_image_pointer_with_explicit_nonzero_record_or_offset(self):
        for pointer in (
            '^IMAGE = ("LDEM_875S_20M_FLOAT.IMG", 2)',
            '^IMAGE = ("LDEM_875S_20M_FLOAT.IMG", 4 <BYTES>)',
        ):
            with self.subTest(pointer=pointer):
                self._replace_label(
                    '^IMAGE = "LDEM_875S_20M_FLOAT.IMG"',
                    pointer,
                )
                with self.assertRaises(LolaLabelError):
                    LolaDemReader(self.image_path, self.label_path)
                self.label_path.write_text(VALID_LABEL, encoding="ascii")

    def test_parser_handles_multiline_strings_groups_and_comments(self):
        window = self.reader.read_window(0, 2, 0, 3)
        self.assertEqual(window.elevation_m.shape, (2, 3))
        self.assertTrue(np.all(window.valid_mask))

    def test_rejects_wrong_product_and_dimensions(self):
        self._replace_label(
            'PRODUCT_ID = "LDEM_875S_20M"',
            'PRODUCT_ID = "OTHER_PRODUCT"',
        )
        with self.assertRaises(LolaLabelError):
            LolaDemReader(self.image_path, self.label_path)

        self.label_path.write_text(
            VALID_LABEL.replace("LINES = 7584", "LINES = 7583", 1),
            encoding="ascii",
        )
        with self.assertRaises(LolaLabelError):
            LolaDemReader(self.image_path, self.label_path)

    def test_rejects_duplicate_required_fields_and_special_value_encoding(self):
        self._replace_label(
            "SAMPLE_BITS = 32",
            "SAMPLE_BITS = 32\n        SAMPLE_BITS = 32",
        )
        with self.assertRaises(LolaLabelError):
            LolaDemReader(self.image_path, self.label_path)

        self.label_path.write_text(
            VALID_LABEL.replace(
                "SAMPLE_BITS = 32",
                "SAMPLE_BITS = 32\n        MISSING_CONSTANT = -9999",
                1,
            ),
            encoding="ascii",
        )
        with self.assertRaises(LolaLabelError):
            LolaDemReader(self.image_path, self.label_path)

    def test_rejects_wrong_projection_sample_type_and_pointer(self):
        cases = (
            ("SAMPLE_TYPE = PC_REAL", "SAMPLE_TYPE = IEEE_REAL"),
            (
                'MAP_PROJECTION_TYPE = "POLAR STEREOGRAPHIC"',
                'MAP_PROJECTION_TYPE = "EQUIRECTANGULAR"',
            ),
            (
                '^IMAGE = "LDEM_875S_20M_FLOAT.IMG"',
                '^IMAGE = "../LDEM_875S_20M_FLOAT.IMG"',
            ),
        )
        for old, new in cases:
            with self.subTest(new=new):
                self._replace_label(old, new)
                with self.assertRaises(LolaLabelError):
                    LolaDemReader(self.image_path, self.label_path)
                self.label_path.write_text(VALID_LABEL, encoding="ascii")

    def test_rejects_truncated_and_oversized_images(self):
        self.reader.close()
        with self.image_path.open("wb") as image_file:
            image_file.truncate(IMAGE_BYTES - 1)
        with self.assertRaises(LolaImageError):
            LolaDemReader(self.image_path, self.label_path)

        with self.image_path.open("wb") as image_file:
            image_file.truncate(IMAGE_BYTES + 1)
        with self.assertRaises(LolaImageError):
            LolaDemReader(self.image_path, self.label_path)

    def test_window_reads_are_bounded_and_convert_kilometres_to_metres(self):
        self._reopen_with_sample(10, 11, 1.25)
        window = self.reader.read_window(10, 12, 10, 13)
        self.assertEqual(window.elevation_m.shape, (2, 3))
        self.assertEqual(window.row_start, 10)
        self.assertEqual(window.col_start, 10)
        self.assertAlmostEqual(window.elevation_m[0, 1], 1250.0)
        self.assertFalse(window.elevation_m.flags.writeable)
        self.assertFalse(window.valid_mask.flags.writeable)
        with self.assertRaises(ValueError):
            self.reader.read_window(0, 7585, 0, 1)
        with self.assertRaises(ValueError):
            self.reader.read_window(0, 1001, 0, 1000)

    def test_non_finite_samples_are_masked_without_a_sentinel(self):
        self._reopen_with_sample(10, 10, float("nan"))
        window = self.reader.read_window(10, 11, 10, 11)
        self.assertFalse(window.valid_mask[0, 0])
        self.assertTrue(np.isnan(window.elevation_m[0, 0]))

    def test_out_of_range_sample_is_an_integrity_error(self):
        self._reopen_with_sample(10, 10, 10.0)
        with self.assertRaises(LolaDataIntegrityError):
            self.reader.read_window(10, 11, 10, 11)

    def test_bilinear_pole_sample_uses_four_central_pixels(self):
        self.reader.close()
        values = (
            (3791, 3791, 0.1),
            (3791, 3792, 0.2),
            (3792, 3791, 0.3),
            (3792, 3792, 0.4),
        )
        with self.image_path.open("r+b") as image_file:
            for row, col, value in values:
                image_file.seek((row * 7584 + col) * 4)
                image_file.write(struct.pack("<f", value))
        self.reader = LolaDemReader(self.image_path, self.label_path)

        sample = self.reader.sample_elevation(-90.0, None)
        self.assertTrue(sample.valid)
        self.assertIsNone(sample.longitude_deg)
        self.assertAlmostEqual(sample.elevation_m, 250.0, places=4)
        self.assertEqual(sample.method, "bilinear")

    def test_invalid_sample_in_interpolation_stencil_is_reported(self):
        self._reopen_with_sample(3791, 3791, float("inf"))
        sample = self.reader.sample_elevation(-90.0, 0.0)
        self.assertFalse(sample.valid)
        self.assertIsNone(sample.elevation_m)
        self.assertEqual(sample.status, "INVALID_SAMPLE")

    def test_geographic_pixel_round_trips_match_derived_projection_equations(self):
        known_coordinates = (
            (-90.0, None),
            (-89.0, 210.0),
            (-89.5, 90.0),
        )
        for latitude, longitude in known_coordinates:
            with self.subTest(latitude=latitude, longitude=longitude):
                pixel = self.reader.geographic_to_pixel(latitude, longitude)
                geographic = self.reader.pixel_to_geographic(pixel.row, pixel.col)
                self.assertAlmostEqual(geographic.latitude_deg, latitude, places=10)
                if latitude == -90.0:
                    self.assertIsNone(geographic.longitude_deg)
                    self.assertAlmostEqual(pixel.row, 3791.5)
                    self.assertAlmostEqual(pixel.col, 3791.5)
                    continue
                self.assertAlmostEqual(
                    geographic.longitude_deg,
                    longitude % 360.0,
                    places=10,
                )

                rho = 2.0 * 1_737_400.0 * math.tan(
                    math.radians(90.0 - abs(latitude)) / 2.0
                )
                expected_x = rho * math.sin(math.radians(longitude))
                expected_y = rho * math.cos(math.radians(longitude))
                self.assertAlmostEqual(
                    pixel.col,
                    3791.5 + expected_x / 20.0,
                    places=8,
                )
                self.assertAlmostEqual(
                    pixel.row,
                    3791.5 - expected_y / 20.0,
                    places=8,
                )

    def test_pyproj_inverse_matches_direct_pds_pixel_to_ground_equations(self):
        for row, col in ((0.0, 0.0), (3791.0, 3792.0), (5104.572922, 3033.396995)):
            with self.subTest(row=row, col=col):
                x = (col - 3791.5) * 20.0
                y = -(row - 3791.5) * 20.0
                radius = math.hypot(x, y)
                expected_latitude = -90.0 + math.degrees(
                    2.0 * math.atan(0.5 * radius / 1_737_400.0)
                )
                coordinate = self.reader.pixel_to_geographic(row, col)
                self.assertAlmostEqual(
                    coordinate.latitude_deg,
                    expected_latitude,
                    places=10,
                )
                if radius == 0.0:
                    self.assertIsNone(coordinate.longitude_deg)
                else:
                    expected_longitude = math.degrees(math.atan2(x, y)) % 360.0
                    self.assertAlmostEqual(
                        coordinate.longitude_deg,
                        expected_longitude,
                        places=10,
                    )

    def test_out_of_coverage_coordinates_are_not_clamped(self):
        with self.assertRaises(OutOfCoverageError):
            self.reader.geographic_to_pixel(-85.0, 0.0)

    def test_exact_pixel_centre_has_no_half_pixel_shift(self):
        coordinate = self.reader.pixel_to_geographic(0.0, 0.0)
        pixel = self.reader.geographic_to_pixel(
            coordinate.latitude_deg,
            coordinate.longitude_deg,
        )
        self.assertAlmostEqual(pixel.row, 0.0, places=9)
        self.assertAlmostEqual(pixel.col, 0.0, places=9)

    def test_closed_reader_rejects_reads(self):
        self.reader.close()
        with self.assertRaises(LolaImageError):
            self.reader.read_window(0, 1, 0, 1)


if __name__ == "__main__":
    unittest.main()
