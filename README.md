# LunarSight
Lunar south pole landing site analysis

## LOLA DEM setup

Terrain data support reads the official NASA/PDS LOLA south-polar gridded
product `LDEM_875S_20M_FLOAT` from dataset `LRO-L-LOLA-4-GDR-V1.0`. Obtain the
matching `LDEM_875S_20M_FLOAT.IMG` and `LDEM_875S_20M_FLOAT.LBL` files from the
[PDS Geosciences archive](https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/float_img/).
Place both files in `data/raw/lola/`; the reader validates their product
identifiers, projection metadata, dimensions, and exact image size before
opening the image as a read-only NumPy memory map. The image is approximately
230 MB and is not included in this repository.

The samples are heights in kilometres relative to a 1,737.4 km reference
sphere. The reader reports those heights in metres and does not add the
reference-radius offset. Coordinates use the product's planetocentric,
east-positive lunar spherical polar stereographic projection; Earth CRS
definitions are not used.

The PDS label reports that approximately 0.004% of points were flagged as
erroneous but does not document their per-pixel representation or provide a
quality mask. The reader does not invent a missing-value sentinel or claim
that these points can be identified. This DEM reader alone is not suitable
for certifying landing safety: it does not implement terrain horizons,
hazard detection, or sub-20 m obstacle analysis.
