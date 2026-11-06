
from pathlib import Path
import json

import numpy as np
import rasterio


ENGINE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = ENGINE_DIR / "results" / "terrain"

ELEVATION_FILE = RESULTS_DIR / "landing_site_elevation.tif"
SUMMARY_FILE = RESULTS_DIR / "terrain_summary.json"

SLOPE_FILE = RESULTS_DIR / "landing_site_slope_validated.tif"
VALIDATION_FILE = RESULTS_DIR / "slope_validation.json"


for file_path in (ELEVATION_FILE, SUMMARY_FILE):
    if not file_path.exists():
        raise FileNotFoundError(f"Required file not found: {file_path}")

with open(SUMMARY_FILE, "r", encoding="utf-8") as file:
    previous_summary = json.load(file)

site_x = previous_summary["landing_site"]["projected_x_metres"]
site_y = previous_summary["landing_site"]["projected_y_metres"]


with rasterio.open(ELEVATION_FILE) as dataset:

    elevation = dataset.read(1).astype(np.float64)
    profile = dataset.profile.copy()

    pixel_x = abs(dataset.transform.a)
    pixel_y = abs(dataset.transform.e)

    rows, cols = elevation.shape

    valid = np.isfinite(elevation)

    print("\nLUNAPILOT - SLOPE VALIDATION")
    print("=" * 55)

    print(f"Elevation dimensions: {cols} x {rows}")
    print(f"Pixel resolution: {pixel_x} x {pixel_y} metres")


    center = elevation[1:-1, 1:-1]
    left = elevation[1:-1, :-2]
    right = elevation[1:-1, 2:]
    upper = elevation[:-2, 1:-1]
    lower = elevation[2:, 1:-1]

    valid_neighbors = (
        valid[1:-1, 1:-1]
        & valid[1:-1, :-2]
        & valid[1:-1, 2:]
        & valid[:-2, 1:-1]
        & valid[2:, 1:-1]
    )

    dz_dx = (right - left) / (2 * pixel_x)
    dz_dy = (lower - upper) / (2 * pixel_y)

    slope_inner = np.degrees(
        np.arctan(np.sqrt(dz_dx**2 + dz_dy**2))
    )

    slope_inner[~valid_neighbors] = np.nan

    slope = np.full(elevation.shape, np.nan, dtype=np.float32)
    slope[1:-1, 1:-1] = slope_inner.astype(np.float32)

    valid_slope = slope[np.isfinite(slope)]

    if valid_slope.size == 0:
        raise ValueError("No valid slope pixels could be calculated.")

    slope_statistics = {
        "minimum_degrees": float(np.min(valid_slope)),
        "maximum_degrees": float(np.max(valid_slope)),
        "mean_degrees": float(np.mean(valid_slope)),
        "median_degrees": float(np.median(valid_slope)),
        "valid_pixels": int(valid_slope.size),
        "total_pixels": int(slope.size),
        "valid_percentage": float(
            valid_slope.size / slope.size * 100
        )
    }

    site_row, site_col = dataset.index(site_x, site_y)

    site_slope = float(slope[site_row, site_col])

    if not np.isfinite(site_slope):
        site_slope = None


    profile.update(
        dtype="float32",
        count=1,
        nodata=np.nan,
        compress="deflate"
    )

    with rasterio.open(SLOPE_FILE, "w", **profile) as output:
        output.write(slope, 1)
        output.set_band_description(
            1,
            "Slope in degrees using valid central differences"
        )


    validation_report = {
        "method": "Central differences using valid centre and four neighbours",
        "pixel_resolution_metres": {
            "x": pixel_x,
            "y": pixel_y
        },
        "landing_site": {
            "row": int(site_row),
            "column": int(site_col),
            "slope_degrees": site_slope
        },
        "slope_statistics": slope_statistics
    }

    with open(VALIDATION_FILE, "w", encoding="utf-8") as file:
        json.dump(validation_report, file, indent=4)


    print("\nVALIDATED SLOPE RESULTS")
    print("-" * 40)

    print(f"Landing-site slope: {site_slope}°")
    print(f"Minimum slope: {slope_statistics['minimum_degrees']:.2f}°")
    print(f"Maximum slope: {slope_statistics['maximum_degrees']:.2f}°")
    print(f"Mean slope: {slope_statistics['mean_degrees']:.2f}°")
    print(f"Median slope: {slope_statistics['median_degrees']:.2f}°")
    print(f"Valid pixels: {slope_statistics['valid_pixels']}")
    print(f"Valid coverage: {slope_statistics['valid_percentage']:.2f}%")

    print("\nSAVED FILES")
    print("-" * 40)
    print(SLOPE_FILE)
    print(VALIDATION_FILE)

    print("\nSlope validation completed successfully.")
