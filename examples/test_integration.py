"""
LunarSight - Direct Integration Test Script
"""

import sys
from pathlib import Path
import pprint

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.lunarsight_science.ephemeris.sun_illumination import calculate_sun_illumination
from src.lunarsight_science.ephemeris.earth_visibility import calculate_earth_visibility

print("\nExecuting LunarSight integration test...\n")

sun_data = calculate_sun_illumination(save_image=False)
earth_data = calculate_earth_visibility(save_image=False)

print("=" * 60)
print("SUN DATA OUTPUT DICTIONARY:")
print("=" * 60)
pprint.pprint(sun_data)

print("\n" + "=" * 60)
print("EARTH DATA OUTPUT DICTIONARY:")
print("=" * 60)
pprint.pprint(earth_data)

print("\n" + "=" * 60)
print("VERIFICATION CHECKS:")
print("=" * 60)
print(f"sun_data is dict   : {isinstance(sun_data, dict)}")
print(f"earth_data is dict : {isinstance(earth_data, dict)}")

if isinstance(sun_data, dict) and isinstance(earth_data, dict):
    print("\n[SUCCESS] Both functions executed and returned valid dictionaries.")
