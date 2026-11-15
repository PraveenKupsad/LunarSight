"""
NASA NAIF SPICE Kernel Manager for LunarSight
=============================================
Manages downloading, verifying, and loading official NASA NAIF SPICE kernels
for high-precision lunar, solar, and terrestrial ephemeris calculations.

Official NASA Data Source:
https://naif.jpl.nasa.gov/pub/naif/generic_kernels/
"""

import sys
from pathlib import Path
import requests
import spiceypy as spice

# Resolve paths
MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parent.parent.parent
DEFAULT_KERNEL_DIR = PROJECT_ROOT / "data" / "spice_kernels"

# Official NASA NAIF Generic Kernels
# Required for exact lunar orientation, ephemeris, and leapsecond calculations
NAIF_BASE_URL = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels"

REQUIRED_KERNELS = {
    # 1. Leapseconds Kernel (LSK): Converts UTC to Ephemeris Time (ET/TDB)
    "naif0012.tls": f"{NAIF_BASE_URL}/lsk/naif0012.tls",
    
    # 2. Planetary Constants Kernel (PCK): IAU physical constants, radii, rotation
    "pck00010.tpc": f"{NAIF_BASE_URL}/pck/pck00010.tpc",
    
    # 3. High-precision Lunar Orientation (Binary PCK): Principal Axes (PA)
    "moon_pa_de421_1900-2050.bpc": f"{NAIF_BASE_URL}/pck/moon_pa_de421_1900-2050.bpc",

    # 4. Lunar Frames Definition Kernel (FK): Associates MOON_PA & MOON_ME frames
    "moon_080317.tf": f"{NAIF_BASE_URL}/fk/satellites/moon_080317.tf",
    
    # 5. Planetary Ephemeris (SPK): Position vectors for Earth, Moon, Sun (compact DE440s)
    "de440s.bsp": f"{NAIF_BASE_URL}/spk/planets/de440s.bsp"
}


def download_file(url: str, dest_path: Path, chunk_size: int = 1024 * 64) -> Path:
    """
    Downloads a file with streaming to handle large binary kernels cleanly.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
    
    print(f"Connecting to NASA NAIF server: {url}")
    response = requests.get(url, stream=True, timeout=30)
    response.raise_for_status()
    
    total_size = int(response.headers.get("content-length", 0))
    downloaded = 0
    
    with open(temp_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    percent = (downloaded / total_size) * 100
                    mb_downloaded = downloaded / (1024 * 1024)
                    mb_total = total_size / (1024 * 1024)
                    sys.stdout.write(f"\rDownloading {dest_path.name}: {percent:5.1f}% ({mb_downloaded:.2f}/{mb_total:.2f} MB)")
                    sys.stdout.write("")
                    sys.stdout.flush()

    if temp_path.exists():
        temp_path.replace(dest_path)
    print(f"\nSaved successfully: {dest_path.name}")
    return dest_path


def ensure_kernels(kernel_dir: Path = DEFAULT_KERNEL_DIR) -> dict[str, Path]:
    """
    Ensures that all mandatory NASA SPICE kernels are downloaded locally.
    Returns a dictionary of kernel names mapped to their local file paths.
    """
    kernel_dir.mkdir(parents=True, exist_ok=True)
    kernel_paths = {}

    print(f"Checking NASA SPICE kernels in: {kernel_dir}")
    for name, url in REQUIRED_KERNELS.items():
        local_path = kernel_dir / name
        if not local_path.exists() or local_path.stat().st_size == 0:
            print(f"\n[Missing] {name} - Downloading from NASA...")
            download_file(url, local_path)
        else:
            mb = local_path.stat().st_size / (1024 * 1024)
            print(f"  [OK] {name} ({mb:.2f} MB)")
        kernel_paths[name] = local_path
    
    return kernel_paths


def load_kernels(kernel_dir: Path = DEFAULT_KERNEL_DIR) -> None:
    """
    Loads all required NASA SPICE kernels into SPICE memory using furnsh.
    """
    kernel_paths = ensure_kernels(kernel_dir)
    print("\nLoading kernels into SPICE memory...")
    for name, path in kernel_paths.items():
        spice.furnsh(str(path))
    
    count = spice.ktotal("ALL")
    print(f"Successfully loaded {count} kernels into SPICE.")


def unload_kernels() -> None:
    """
    Clears all loaded kernels from SPICE memory.
    """
    spice.kclear()
    print("All SPICE kernels unloaded.")


if __name__ == "__main__":
    print("=" * 60)
    print("LunarSight - NASA NAIF SPICE Kernel Manager")
    print("=" * 60)
    load_kernels()
    unload_kernels()
    print("\nVerification complete: SPICE subsystem is ready for calculations.")
