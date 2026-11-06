
from pathlib import Path
import rasterio

# Locate the project and terrain file
engine_directory = Path(__file__).resolve().parent.parent

terrain_file = (
    engine_directory
    / "data"
    / "terrain"
    / "LDEM_80S_80MPP_ADJ.tiff"
)

if not terrain_file.exists():
    raise FileNotFoundError(f"Terrain file not found: {terrain_file}")

# Inspect the GeoTIFF
with rasterio.open(terrain_file) as dataset:

    print("\nLUNAPILOT - LUNAR TERRAIN INSPECTION")
    print("=" * 55)

    print("Filename:", dataset.name)
    print("Dimensions:", dataset.width, "x", dataset.height)
    print("Bands:", dataset.count)
    print("Data type:", dataset.dtypes)
    print("Coordinate reference system:", dataset.crs)
    print("Pixel resolution:", dataset.res)
    print("Bounds:", dataset.bounds)
    print("No-data value:", dataset.nodata)
    print("Coordinate transformation:", dataset.transform)

    print("\nDataset metadata:")
    for key, value in dataset.tags().items():
        print(f"{key}: {value}")

    print("\nElevation band metadata:")
    for key, value in dataset.tags(1).items():
        print(f"{key}: {value}")

    print("\nInspection completed successfully.")
