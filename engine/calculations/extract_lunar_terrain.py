
from pathlib import Path
import argparse
import json
import math

import numpy as np
import rasterio
from rasterio.windows import Window
from rasterio.warp import transform


ENGINE_DIR = Path(__file__).resolve().parent.parent

DEM_FILE = (
    ENGINE_DIR
    / "data"
    / "terrain"
    / "LDEM_80S_80MPP_ADJ.tiff"
)

RESULTS_DIR = ENGINE_DIR / "results" / "terrain"


parser = argparse.ArgumentParser()
parser.add_argument("--latitude", type=float, default=-89.9)
parser.add_argument("--longitude", type=float, default=0.0)

args = parser.parse_args()

LATITUDE = args.latitude
LONGITUDE = args.longitude

if not -90 <= LATITUDE <= -80:
    raise ValueError("Latitude must be within the DEM's approximate coverage (-90 to -80 degrees south).")

if not -180 <= LONGITUDE <= 180:
    raise ValueError("Longitude must be between -180 and 180 degrees.")

AREA_RADIUS_METRES = 5000


if not DEM_FILE.exists():
    raise FileNotFoundError(f"DEM not found: {DEM_FILE}")

RESULTS_DIR.mkdir(parents=True, exist_ok=True)


with rasterio.open(DEM_FILE) as dataset:

    print("\nLUNAPILOT - TERRAIN EXTRACTION")
    print("=" * 55)

    geographic_crs = dataset.crs.geodetic_crs

    x_values, y_values = transform(
        geographic_crs,
        dataset.crs,
        [LONGITUDE],
        [LATITUDE]
    )

    site_x = x_values[0]
    site_y = y_values[0]

    print(f"Landing latitude: {LATITUDE}°")
    print(f"Landing longitude: {LONGITUDE}°")
    print(f"Projected X: {site_x:.3f} m")
    print(f"Projected Y: {site_y:.3f} m")

    if not (
        dataset.bounds.left <= site_x <= dataset.bounds.right
        and dataset.bounds.bottom <= site_y <= dataset.bounds.top
    ):
        raise ValueError("Landing site is outside DEM coverage.")

    site_row, site_col = dataset.index(site_x, site_y)

    print(f"DEM pixel: row {site_row}, column {site_col}")

    pixel_size_x = abs(dataset.transform.a)
    pixel_size_y = abs(dataset.transform.e)

    radius_x = math.ceil(AREA_RADIUS_METRES / pixel_size_x)
    radius_y = math.ceil(AREA_RADIUS_METRES / pixel_size_y)

    window = Window(
        col_off=max(0, site_col - radius_x),
        row_off=max(0, site_row - radius_y),
        width=min(
            dataset.width - max(0, site_col - radius_x),
            2 * radius_x
        ),
        height=min(
            dataset.height - max(0, site_row - radius_y),
            2 * radius_y
        )
    )

    elevation = dataset.read(
        1,
        window=window,
        masked=True
    ).filled(np.nan).astype(np.float32)

    local_transform = dataset.window_transform(window)

    valid = np.isfinite(elevation)

    if not np.any(valid):
        raise ValueError("No valid elevation pixels in extracted area.")


    valid_elevation = elevation[valid]

    minimum_elevation = float(np.min(valid_elevation))
    maximum_elevation = float(np.max(valid_elevation))
    mean_elevation = float(np.mean(valid_elevation))
    median_elevation = float(np.median(valid_elevation))

    site_elevation = float(
        dataset.read(
            1,
            window=Window(site_col, site_row, 1, 1)
        )[0, 0]
    )

    if not np.isfinite(site_elevation):
        site_elevation = None

    filled_elevation = np.where(
        valid,
        elevation,
        mean_elevation
    )

    gradient_y, gradient_x = np.gradient(
        filled_elevation,
        pixel_size_y,
        pixel_size_x
    )

    slope = np.degrees(
        np.arctan(
            np.sqrt(gradient_x ** 2 + gradient_y ** 2)
        )
    ).astype(np.float32)

    slope[~valid] = np.nan

    dem_aspect = np.degrees(
        np.arctan2(-gradient_x, gradient_y)
    )

    aspect = (
        180.0 + LONGITUDE - dem_aspect
    ) % 360

    aspect[slope < 0.01] = np.nan
    aspect[~valid] = np.nan

    valid_slope = slope[np.isfinite(slope)]
    valid_aspect = aspect[np.isfinite(aspect)]

    minimum_slope = float(np.min(valid_slope))
    maximum_slope = float(np.max(valid_slope))
    mean_slope = float(np.mean(valid_slope))
    median_slope = float(np.median(valid_slope))
    minimum_aspect = float(np.min(valid_aspect))
    maximum_aspect = float(np.max(valid_aspect))
    mean_aspect = float(np.mean(valid_aspect))


    output_profile = dataset.profile.copy()

    output_profile.update(
        width=elevation.shape[1],
        height=elevation.shape[0],
        transform=local_transform,
        dtype="float32",
        count=1,
        nodata=np.nan,
        compress="deflate"
    )

    elevation_file = RESULTS_DIR / "landing_site_elevation.tif"
    slope_file = RESULTS_DIR / "landing_site_slope.tif"
    aspect_file = RESULTS_DIR / "landing_site_aspect.tif"

    with rasterio.open(elevation_file, "w", **output_profile) as output:
        output.write(elevation, 1)
        output.set_band_description(1, "Surface elevation in metres")

    with rasterio.open(slope_file, "w", **output_profile) as output:
        output.write(slope, 1)
        output.set_band_description(1, "Terrain slope in degrees")

    with rasterio.open(aspect_file, "w", **output_profile) as output:
        output.write(aspect.astype(np.float32), 1)
        output.set_band_description(1, "Terrain downslope aspect in degrees")

    print(aspect_file)


    summary = {
        "landing_site": {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "projected_x_metres": site_x,
            "projected_y_metres": site_y,
            "elevation_metres": site_elevation
        },
        "extraction": {
            "area_width_pixels": int(elevation.shape[1]),
            "area_height_pixels": int(elevation.shape[0]),
            "pixel_resolution_metres": pixel_size_x,
            "valid_pixels": int(np.count_nonzero(valid))
        },
        "elevation_metres": {
            "minimum": minimum_elevation,
            "maximum": maximum_elevation,
            "mean": mean_elevation,
            "median": median_elevation
        },
        "slope_degrees": {
            "minimum": minimum_slope,
            "maximum": maximum_slope,
            "mean": mean_slope,
            "median": median_slope
        }
    }

    summary_file = RESULTS_DIR / "terrain_summary.json"

    with open(summary_file, "w", encoding="utf-8") as file:
        json.dump(summary, file, indent=4)


    print("\nELEVATION ANALYSIS")
    print("-" * 40)
    print(f"Landing-site elevation: {site_elevation} m")
    print(f"Minimum elevation: {minimum_elevation:.2f} m")
    print(f"Maximum elevation: {maximum_elevation:.2f} m")
    print(f"Mean elevation: {mean_elevation:.2f} m")
    print(f"Median elevation: {median_elevation:.2f} m")

    print("\nSLOPE ANALYSIS")
    print("-" * 40)
    print(f"Minimum slope: {minimum_slope:.2f}°")
    print(f"Maximum slope: {maximum_slope:.2f}°")
    print(f"Mean slope: {mean_slope:.2f}°")
    print(f"Median slope: {median_slope:.2f}°")

    print("\nSAVED FILES")
    print("-" * 40)
    print(elevation_file)
    print(slope_file)
    print(summary_file)

    print("\nTerrain extraction completed successfully.")
