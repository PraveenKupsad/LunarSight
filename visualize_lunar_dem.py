"""
LunarSight - Lunar DEM Terrain Visualization
=============================================
Reads the NASA LRO LOLA Lunar South Pole Digital Elevation Model (GeoTIFF)
using Rasterio and generates a publication-quality colored elevation map
with a calibrated elevation colorbar in meters.

Saves output to: data/processed/lunar_terrain.png
Original GeoTIFF is opened in read-only mode and not modified.
"""

from pathlib import Path
import numpy as np
import rasterio

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Define paths
PROJECT_ROOT = Path(__file__).resolve().parent
DEM_PATH = PROJECT_ROOT / "data" / "raw" / "lola" / "MOON_LRO_NAC_DEM_89S210E_4mp.tif"
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_IMAGE = OUTPUT_DIR / "lunar_terrain.png"


def visualize_dem(input_path: Path, output_path: Path) -> None:
    """
    Reads the DEM raster with rasterio and produces a colored terrain map with Matplotlib.
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Input DEM not found at: {input_path}")

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Reading DEM file (read-only): {input_path.name}")
    with rasterio.open(input_path, "r") as src:
        # Read the first band (elevation in meters)
        elevation = src.read(1)
        nodata = src.nodata
        transform = src.transform
        res_x = abs(transform.a)
        res_y = abs(transform.e)
        width = src.width
        height = src.height

    # Mask out nodata values if present
    if nodata is not None:
        valid_mask = elevation != nodata
    else:
        valid_mask = ~np.isnan(elevation)

    valid_elevation = elevation[valid_mask]
    min_elev = float(np.min(valid_elevation))
    max_elev = float(np.max(valid_elevation))
    relief = max_elev - min_elev

    print(f"  • Dimensions : {width} x {height} pixels")
    print(f"  • Resolution : {res_x:.1f} m/pixel")
    print(f"  • Min Height : {min_elev:+.1f} m")
    print(f"  • Max Height : {max_elev:+.1f} m")
    print(f"  • Relief     : {relief:.1f} m")

    # Physical dimensions in kilometers relative to map center
    extent_km = [
        -(width * res_x) / 2000.0,
        (width * res_x) / 2000.0,
        -(height * res_y) / 2000.0,
        (height * res_y) / 2000.0
    ]

    # Plot figure
    plt.figure(figsize=(10, 8), dpi=300)
    
    # Use 'turbo' or 'viridis' or 'terrain' - 'viridis' or 'terrain' provides excellent contrast
    im = plt.imshow(
        elevation,
        cmap="terrain",
        extent=extent_km,
        origin="upper"
    )

    # Colorbar configuration
    cbar = plt.colorbar(im, fraction=0.046, pad=0.04)
    cbar.set_label("Elevation (metres relative to Lunar 1737.4 km Datum)", fontsize=11, fontweight="bold")
    cbar.ax.tick_params(labelsize=10)

    # Labels and Titles
    plt.title(
        "Lunar South Pole Topography - Shackleton Crater Region (89°S)\n"
        f"NASA LRO LOLA Altimetry (Elevation Range: {min_elev:+.0f} m to {max_elev:+.0f} m)",
        fontsize=12,
        fontweight="bold",
        pad=14
    )
    plt.xlabel("Polar Stereographic Distance X (km)", fontsize=11)
    plt.ylabel("Polar Stereographic Distance Y (km)", fontsize=11)
    plt.grid(color="white", linestyle="--", linewidth=0.5, alpha=0.3)

    # Annotate key topographical features
    plt.annotate(
        "Crater Floor\n(Permanently Shadowed Region)",
        xy=(0, 0),
        xytext=(-8, -8),
        color="yellow",
        fontweight="bold",
        fontsize=9,
        arrowprops=dict(facecolor="yellow", shrink=0.05, width=1.5, headwidth=6)
    )

    plt.annotate(
        "Crater Rim Crest\n(Peak Sunlight Exposure)",
        xy=(10.5, 0),
        xytext=(4, 8),
        color="white",
        fontweight="bold",
        fontsize=9,
        arrowprops=dict(facecolor="white", shrink=0.05, width=1.5, headwidth=6)
    )

    plt.tight_layout()

    # Save output image
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Map successfully rendered and saved to: {output_path}")


if __name__ == "__main__":
    visualize_dem(DEM_PATH, OUTPUT_IMAGE)
