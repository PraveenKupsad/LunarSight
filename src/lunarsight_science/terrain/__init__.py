"""Terrain-data readers and coordinate utilities."""

from .lola_dem import (
    ElevationSample,
    GeoCoordinate,
    InterpolationUnavailableError,
    LolaDataIntegrityError,
    LolaDemError,
    LolaDemMetadata,
    LolaDemReader,
    LolaImageError,
    LolaLabelError,
    OutOfCoverageError,
    PixelCoordinate,
    TerrainWindow,
)
from .terrain_horizon import (
    TerrainHorizonError,
    TerrainHorizonProfile,
    TerrainHorizonRay,
    calculate_terrain_horizon,
)
from .terrain_sun_visibility import (
    TerrainSunVisibility,
    classify_solar_disk_against_terrain,
)

__all__ = [
    "ElevationSample",
    "GeoCoordinate",
    "InterpolationUnavailableError",
    "LolaDataIntegrityError",
    "LolaDemError",
    "LolaDemMetadata",
    "LolaDemReader",
    "LolaImageError",
    "LolaLabelError",
    "OutOfCoverageError",
    "PixelCoordinate",
    "TerrainWindow",
    "TerrainHorizonError",
    "TerrainHorizonProfile",
    "TerrainHorizonRay",
    "calculate_terrain_horizon",
    "TerrainSunVisibility",
    "classify_solar_disk_against_terrain",
]
