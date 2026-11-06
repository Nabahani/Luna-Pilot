
from pathlib import Path
import csv
import json
import math

import numpy as np
import rasterio


ENGINE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = ENGINE_DIR / "results" / "terrain"

ELEVATION_FILE = RESULTS_DIR / "landing_site_elevation.tif"
SUMMARY_FILE = RESULTS_DIR / "terrain_summary.json"

HORIZON_CSV = RESULTS_DIR / "terrain_horizon_360.csv"
HORIZON_JSON = RESULTS_DIR / "terrain_horizon_summary.json"

MOON_RADIUS_METRES = 1_737_400.0

OBSERVER_HEIGHT_METRES = 2.0
MAX_DISTANCE_METRES = 5000.0

AZIMUTH_STEP_DEGREES = 1


if not ELEVATION_FILE.exists():
    raise FileNotFoundError(f"Elevation raster not found: {ELEVATION_FILE}")

if not SUMMARY_FILE.exists():
    raise FileNotFoundError(f"Terrain summary not found: {SUMMARY_FILE}")

with open(SUMMARY_FILE, "r", encoding="utf-8") as file:
    site_data = json.load(file)

site_x = site_data["landing_site"]["projected_x_metres"]
site_y = site_data["landing_site"]["projected_y_metres"]
site_elevation = site_data["landing_site"]["elevation_metres"]


with rasterio.open(ELEVATION_FILE) as dataset:

    elevation = dataset.read(1)

    pixel_x = abs(dataset.transform.a)
    pixel_y = abs(dataset.transform.e)

    site_row, site_col = dataset.index(site_x, site_y)

    if not (0 <= site_row < dataset.height and
            0 <= site_col < dataset.width):
        raise ValueError("Landing site is outside the extracted raster.")

    print("\nLUNAPILOT - TERRAIN HORIZON ANALYSIS")
    print("=" * 55)

    print(f"Observer height: {OBSERVER_HEIGHT_METRES} m")
    print(f"Maximum distance: {MAX_DISTANCE_METRES:.0f} m")
    print(f"Azimuth interval: {AZIMUTH_STEP_DEGREES} degree")
    print(f"Landing elevation: {site_elevation:.2f} m")

    pixel_step = min(pixel_x, pixel_y)

    distances = np.arange(
        pixel_step,
        MAX_DISTANCE_METRES + 0.001,
        pixel_step
    )

    horizon_records = []


    for azimuth in range(
        0,
        360,
        AZIMUTH_STEP_DEGREES
    ):

        angle = math.radians(azimuth)

        direction_x = math.sin(angle)
        direction_y = math.cos(angle)

        maximum_angle = None
        obstruction_distance = None
        valid_samples = 0

        for distance in distances:

            x = site_x + distance * direction_x
            y = site_y + distance * direction_y

            row, col = dataset.index(x, y)

            if not (
                0 <= row < dataset.height
                and 0 <= col < dataset.width
            ):
                continue

            terrain_elevation = float(elevation[row, col])

            if not math.isfinite(terrain_elevation):
                continue

            curvature_drop = (
                MOON_RADIUS_METRES
                - math.sqrt(
                    MOON_RADIUS_METRES**2 - distance**2
                )
            )

            relative_height = (
                terrain_elevation
                - site_elevation
                - curvature_drop
                - OBSERVER_HEIGHT_METRES
            )

            elevation_angle = math.degrees(
                math.atan2(relative_height, distance)
            )

            valid_samples += 1

            if (
                maximum_angle is None
                or elevation_angle > maximum_angle
            ):
                maximum_angle = elevation_angle
                obstruction_distance = float(distance)

        horizon_records.append({
            "azimuth_degrees": azimuth,
            "horizon_elevation_degrees": maximum_angle,
            "obstruction_distance_metres": obstruction_distance,
            "valid_samples": valid_samples
        })


    valid_horizons = [
        record for record in horizon_records
        if record["horizon_elevation_degrees"] is not None
    ]

    if not valid_horizons:
        raise ValueError("No valid terrain horizon measurements found.")

    horizon_angles = np.array([
        record["horizon_elevation_degrees"]
        for record in valid_horizons
    ])

    minimum_horizon = float(np.min(horizon_angles))
    maximum_horizon = float(np.max(horizon_angles))
    mean_horizon = float(np.mean(horizon_angles))
    median_horizon = float(np.median(horizon_angles))

    highest_direction = valid_horizons[
        int(np.argmax(horizon_angles))
    ]

    lowest_direction = valid_horizons[
        int(np.argmin(horizon_angles))
    ]


    with open(HORIZON_CSV, "w", newline="", encoding="utf-8") as file:

        writer = csv.DictWriter(
            file,
            fieldnames=[
                "azimuth_degrees",
                "horizon_elevation_degrees",
                "obstruction_distance_metres",
                "valid_samples"
            ]
        )

        writer.writeheader()
        writer.writerows(horizon_records)


    horizon_summary = {
        "observer": {
            "latitude": site_data["landing_site"]["latitude"],
            "longitude": site_data["landing_site"]["longitude"],
            "elevation_metres": site_elevation,
            "height_above_surface_metres": OBSERVER_HEIGHT_METRES
        },
        "analysis": {
            "maximum_distance_metres": MAX_DISTANCE_METRES,
            "sampling_interval_metres": float(pixel_step),
            "azimuth_interval_degrees": AZIMUTH_STEP_DEGREES,
            "number_of_directions": len(horizon_records),
            "valid_directions": len(valid_horizons),
            "lunar_curvature_corrected": True
        },
        "horizon_statistics": {
            "minimum_degrees": minimum_horizon,
            "maximum_degrees": maximum_horizon,
            "mean_degrees": mean_horizon,
            "median_degrees": median_horizon
        },
        "highest_horizon_direction": highest_direction,
        "lowest_horizon_direction": lowest_direction
    }

    with open(HORIZON_JSON, "w", encoding="utf-8") as file:
        json.dump(horizon_summary, file, indent=4)


    print("\nHORIZON RESULTS")
    print("-" * 40)

    print(f"Valid directions: {len(valid_horizons)}/360")
    print(f"Minimum horizon: {minimum_horizon:.3f}°")
    print(f"Maximum horizon: {maximum_horizon:.3f}°")
    print(f"Mean horizon: {mean_horizon:.3f}°")
    print(f"Median horizon: {median_horizon:.3f}°")

    print("\nHIGHEST TERRAIN OBSTRUCTION")
    print("-" * 40)

    print(
        f"Azimuth: "
        f"{highest_direction['azimuth_degrees']}°"
    )

    print(
        f"Elevation angle: "
        f"{highest_direction['horizon_elevation_degrees']:.3f}°"
    )

    print(
        f"Distance: "
        f"{highest_direction['obstruction_distance_metres']:.0f} m"
    )

    print("\nSAVED FILES")
    print("-" * 40)
    print(HORIZON_CSV)
    print(HORIZON_JSON)

    print("\nTerrain horizon analysis completed successfully.")
