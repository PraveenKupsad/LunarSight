"""
LunarSight - Lunar South Pole Solar Illumination Simulation
============================================================
Calculates terrain slope, aspect, and direct solar illumination across a
LOLA Digital Elevation Model (DEM) using a simulated grazing Sun vector.

DISCLAIMER & SCIENTIFIC NOTICE:
-------------------------------
This module provides a SIMPLIFIED GEOMETRIC SIMULATION of solar illumination
using a fixed Sun azimuth and elevation angle. It does NOT yet incorporate the
real-time, dynamic NASA NAIF SPICE planetary ephemeris (which is implemented in
`sun_position.py`). It is designed for baseline topographic lighting analysis.

Inputs:
- DEM: data/raw/lola/MOON_LRO_NAC_DEM_89S210E_4mp.tif (read-only, not modified)

Outputs:
- Visualization: data/processed/sun_illumination.png
"""

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import numpy as np
import rasterio

# Set non-interactive Agg backend before importing pyplot to prevent GUI pop-ups
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

from ..data_collection.spice_manager import DEFAULT_KERNEL_DIR, REQUIRED_KERNELS

# Define project paths
MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parent.parent.parent
DEM_PATH = PROJECT_ROOT / "data" / "raw" / "lola" / "MOON_LRO_NAC_DEM_89S210E_4mp.tif"
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_IMAGE = OUTPUT_DIR / "sun_illumination.png"


def compute_slope_aspect(elevation: np.ndarray, cell_size_m: float = 100.0) -> tuple[np.ndarray, np.ndarray]:
    """
    Computes slope and aspect angles across the DEM in radians.
    - Slope: Angle between terrain surface normal and the vertical [0, pi/2]
    - Aspect: Azimuth direction that the slope faces [0, 2*pi] (clockwise from North)
    """
    # Gradients along rows (Y / North-South) and columns (X / East-West)
    dz_dy, dz_dx = np.gradient(elevation, cell_size_m, cell_size_m)

    # Slope in radians
    slope = np.arctan(np.sqrt(dz_dx**2 + dz_dy**2))

    # Aspect in radians clockwise from North (dx / -dy)
    aspect = np.arctan2(dz_dx, -dz_dy)
    aspect = np.where(aspect < 0, aspect + 2 * np.pi, aspect)

    return slope, aspect


def compute_cast_shadows(
    elevation: np.ndarray,
    sun_elev_rad: float,
    sun_azimuth_rad: float,
    cell_size_m: float = 100.0
) -> np.ndarray:
    """
    Computes terrain cast shadows (ray-tracing across topography).
    Returns a boolean mask: True = illuminated, False = shadowed by peaks.
    """
    rows, cols = elevation.shape
    illuminated = np.ones((rows, cols), dtype=bool)

    # Unit step in direction toward the Sun
    # Azimuth 0° is North (-dy in image row coordinates), 90° is East (+dx in col coordinates)
    step_x = np.sin(sun_azimuth_rad)
    step_y = -np.cos(sun_azimuth_rad)

    tan_elev = np.tan(sun_elev_rad)
    max_steps = int(min(rows, cols) * 0.8)

    # Ray-trace out from each pixel toward the Sun
    for step in range(1, max_steps):
        dist_m = step * cell_size_m
        min_blocking_z_delta = dist_m * tan_elev

        shift_r = int(round(step * step_y))
        shift_c = int(round(step * step_x))

        # Check ray bounds
        r_start = max(0, -shift_r)
        r_end = min(rows, rows - shift_r)
        c_start = max(0, -shift_c)
        c_end = min(cols, cols - shift_c)

        if r_start >= r_end or c_start >= c_end:
            break

        current_z = elevation[r_start:r_end, c_start:c_end]
        target_r = r_start + shift_r
        target_c = c_start + shift_c
        blocking_z = elevation[target_r:target_r + (r_end - r_start), target_c:target_c + (c_end - c_start)]

        # If terrain in the direction of the Sun is higher than ray altitude, it casts shadow
        blocked = (blocking_z - current_z) > min_blocking_z_delta
        illuminated[r_start:r_end, c_start:c_end] &= ~blocked

    return illuminated


def check_spice_kernels() -> None:
    """Verifies that all required NASA SPICE kernels are present on disk."""
    for kernel_name in REQUIRED_KERNELS:
        kernel_path = DEFAULT_KERNEL_DIR / kernel_name
        if not kernel_path.exists() or kernel_path.stat().st_size == 0:
            raise RuntimeError(
                f"NASA SPICE kernel '{kernel_name}' is missing from {DEFAULT_KERNEL_DIR}.\n"
                f"Run 'python -m src.lunarsight_science.data_collection.spice_manager' to download it."
            )


def calculate_sun_illumination(
    dem_path: Path = DEM_PATH,
    output_path: Path = OUTPUT_IMAGE,
    sun_elevation_deg: float | None = None,
    sun_azimuth_deg: float | None = None,
    utc_time_str: str | None = None,
    save_image: bool = True
) -> dict[str, Any]:
    """
    Calculates lunar surface illumination across the DEM using slope, aspect, and cast shadows.
    By default (when no datetime is provided), it uses the current UTC time and calculates the
    Sun position dynamically using NASA SPICE kernels.

    Returns:
    - dict with pct_illuminated, pct_shadowed, sun_elevation_deg, sun_azimuth_deg, output_image_path.
    """
    # 1. Determine Sun angles: Default to NASA SPICE dynamic calculation
    if sun_elevation_deg is None or sun_azimuth_deg is None:
        # Verify SPICE kernels are present; do not silently simulate
        check_spice_kernels()

        # Default to current UTC time if not specified
        if utc_time_str is None:
            utc_time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        from .sun_position import compute_sun_position
        spice_res = compute_sun_position(utc_time_str, lat_deg=-89.9, lon_deg=0.0)
        sun_elevation_deg = spice_res["solar_elevation_deg"]
        sun_azimuth_deg = spice_res["solar_azimuth_deg"]
        method_desc = f"NASA_SPICE_DYNAMIC ({utc_time_str})"
    else:
        method_desc = f"CUSTOM_VECTOR (Elev={sun_elevation_deg:+.1f}°, Az={sun_azimuth_deg:.1f}°)"

    print("=" * 75)
    print("LUNARSIGHT - LUNAR SOLAR ILLUMINATION ANALYSIS")
    print("=" * 75)
    print(f"Mode: {method_desc}\n")

    if not dem_path.exists():
        raise FileNotFoundError(f"DEM not found at: {dem_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Read DEM in read-only mode
    with rasterio.open(dem_path, "r") as src:
        elevation = src.read(1)
        res_m = abs(src.transform.a)
        width = src.width
        height = src.height

    print(f"Loaded DEM : {dem_path.name} ({width}x{height} pixels, {res_m:.1f} m/pixel)")
    print(f"Sun Direction: Elevation = {sun_elevation_deg:+.2f}°, Azimuth = {sun_azimuth_deg:.1f}°")

    sun_elev_rad = math.radians(sun_elevation_deg)
    sun_azimuth_rad = math.radians(sun_azimuth_deg)

    # 2. Calculate Slope and Aspect
    slope_rad, aspect_rad = compute_slope_aspect(elevation, cell_size_m=res_m)

    # 3. Calculate Direct Solar Incidence (Lambertian Cosine Law)
    # cos(i) = cos(slope) * sin(sun_elev) + sin(slope) * cos(sun_elev) * cos(sun_az - aspect)
    cos_incidence = (
        np.cos(slope_rad) * np.sin(sun_elev_rad) +
        np.sin(slope_rad) * np.cos(sun_elev_rad) * np.cos(sun_azimuth_rad - aspect_rad)
    )

    # Direct slope illumination (0.0 to 1.0)
    direct_illum = np.clip(cos_incidence, 0.0, 1.0)

    # 4. Compute Cast Shadows (terrain ray-tracing)
    print("Computing terrain cast shadows across crater topography...")
    cast_shadow_mask = compute_cast_shadows(elevation, sun_elev_rad, sun_azimuth_rad, cell_size_m=res_m)

    # Combined illumination: zero where blocked by cast shadow
    final_illumination = direct_illum * cast_shadow_mask

    # Calculate statistics
    illuminated_pixels = np.sum(final_illumination > 0.05)
    shadowed_pixels = np.sum(final_illumination <= 0.05)
    total_pixels = final_illumination.size
    pct_illuminated = (illuminated_pixels / total_pixels) * 100.0
    pct_shadowed = (shadowed_pixels / total_pixels) * 100.0

    print(f"\nIllumination Results (Simulated Sun at {sun_elevation_deg:+.1f}°):")
    print(f"  • Illuminated Surface Area : {pct_illuminated:.1f}% (Rim crests & slopes facing Sun)")
    print(f"  • In Deep Shadow (PSRs)    : {pct_shadowed:.1f}% (Crater interior & blocked valleys)")

    # 5. Create Custom Colormap: Dark Blue (Shadowed) to Bright Yellow (Illuminated)
    colors = [
        (0.00, "#050b1e"),  # Deep Navy Dark Blue (0% illumination / total shadow)
        (0.15, "#0b2055"),  # Midnight Blue
        (0.40, "#1f4e99"),  # Intermediate Blue
        (0.70, "#c2c200"),  # Golden Yellow transition
        (1.00, "#ffff00")   # Radiant Bright Yellow (100% direct sunlight)
    ]
    sun_cmap = LinearSegmentedColormap.from_list(
        "LunarSunShadow",
        [(pos, col) for pos, col in colors]
    )

    # 6. Render Map with Matplotlib
    extent_km = [
        -(width * res_m) / 2000.0,
        (width * res_m) / 2000.0,
        -(height * res_m) / 2000.0,
        (height * res_m) / 2000.0
    ]

    fig, ax = plt.subplots(figsize=(10, 8.5), dpi=300)

    im = ax.imshow(
        final_illumination,
        cmap=sun_cmap,
        vmin=0.0,
        vmax=1.0,
        extent=extent_km,
        origin="upper"
    )

    # Colorbar
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Simulated Sunlight Illumination Index [0.0 = Shadow, 1.0 = Full Sun]", fontsize=10, fontweight="bold")
    cbar.set_ticks([0.0, 0.25, 0.5, 0.75, 1.0])
    cbar.set_ticklabels(["0.0 (Dark Shadow)", "0.25", "0.50", "0.75", "1.0 (Bright Sun)"])

    # Sun direction arrow indicator
    arrow_dx = math.sin(sun_azimuth_rad) * 4.0
    arrow_dy = math.cos(sun_azimuth_rad) * 4.0
    ax.arrow(
        -11, -11, arrow_dx, arrow_dy,
        head_width=1.2, head_length=1.5,
        fc="#ffff00", ec="white", width=0.4, alpha=0.9
    )
    ax.text(-11, -13.5, f"Sun Vector\nAz: {sun_azimuth_deg:.0f}° | Elev: {sun_elevation_deg:+.1f}°", color="white", fontsize=8, fontweight="bold")

    # Titles and Subtitles
    ax.set_title(
        "Lunar South Pole - Simulated Solar Sunlight Illumination\n"
        "[SIMPLIFIED SIMULATION - NOT REAL-TIME NASA/SPICE EPHEMERIS]",
        fontsize=12, fontweight="bold", pad=12
    )
    ax.set_xlabel("Polar Stereographic Distance X (km)", fontsize=10)
    ax.set_ylabel("Polar Stereographic Distance Y (km)", fontsize=10)
    ax.grid(color="gray", linestyle=":", linewidth=0.5, alpha=0.4)

    # Status annotations
    ax.text(
        0.02, 0.96,
        f"Illuminated (Bright Yellow): {pct_illuminated:.1f}%\n"
        f"Shadowed (Dark Blue)        : {pct_shadowed:.1f}%",
        transform=ax.transAxes,
        color="white",
        fontsize=9,
        fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#000000", alpha=0.75, edgecolor="#ffff00")
    )

    if save_image:
        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        plt.close(fig)
        print(f"\nSunlight illumination map successfully saved to: {output_path}")
    else:
        plt.close(fig)

    return {
        "status": "SUCCESS",
        "method": method_desc,
        "sun_elevation_deg": round(float(sun_elevation_deg), 3),
        "sun_azimuth_deg": round(float(sun_azimuth_deg), 2),
        "pct_illuminated": round(float(pct_illuminated), 2),
        "pct_shadowed": round(float(pct_shadowed), 2),
        "total_pixels": int(total_pixels),
        "illuminated_pixels": int(illuminated_pixels),
        "shadowed_pixels": int(shadowed_pixels),
        "output_image_path": str(output_path)
    }


# Backwards compatibility alias
simulate_sun_illumination = calculate_sun_illumination


if __name__ == "__main__":
    calculate_sun_illumination(
        DEM_PATH,
        OUTPUT_IMAGE
    )
