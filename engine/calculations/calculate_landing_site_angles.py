
import argparse
import csv
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import spiceypy as sp
from naif_de440 import de440
from naif_leapseconds import leapseconds


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
ENGINE_DIRECTORY = SCRIPT_DIRECTORY.parent

RESULTS_DIRECTORY = ENGINE_DIRECTORY / "results"
RESULTS_DIRECTORY.mkdir(parents=True, exist_ok=True)

OUTPUT_FILE = RESULTS_DIRECTORY / "landing_site_angle_analysis.csv"

FRAME = "MOON_ME_DE440_ME421"

kernels = [
    leapseconds,
    de440,
    ENGINE_DIRECTORY / "kernels/moon_orientation/pck00011.tpc",
    ENGINE_DIRECTORY / "kernels/moon_orientation/moon_de440_220930.tf",
    ENGINE_DIRECTORY / "kernels/moon_orientation/moon_pa_de440_200625.bpc",
]

MOON_RADIUS_KM = 1737.4

parser = argparse.ArgumentParser(
    description="LunarPilot Sun and Earth position analysis"
)

parser.add_argument("--latitude", type=float, required=True)
parser.add_argument("--longitude", type=float, required=True)
parser.add_argument("--start", required=True)
parser.add_argument("--end", required=True)

args = parser.parse_args()

LATITUDE = args.latitude
LONGITUDE = args.longitude

START_TIME = datetime.fromisoformat(args.start)
END_TIME = datetime.fromisoformat(args.end)

if not -90 <= LATITUDE <= -80:
    raise ValueError("Latitude is outside the approximate DEM coverage.")

if not -180 <= LONGITUDE <= 180:
    raise ValueError("Longitude must be between -180 and 180.")

if START_TIME > END_TIME:
    raise ValueError("Start time cannot be later than end time.")

if START_TIME.tzinfo is not None or END_TIME.tzinfo is not None:
    raise ValueError("Provide UTC date-times without timezone offsets.")

latitude_radians = np.radians(LATITUDE)
longitude_radians = np.radians(LONGITUDE)

site = sp.georec(
    longitude_radians,
    latitude_radians,
    0.0,
    MOON_RADIUS_KM,
    0.0
)

up = site / np.linalg.norm(site)

east = np.array([
    -np.sin(longitude_radians),
    np.cos(longitude_radians),
    0.0
])

north = np.cross(up, east)
north /= np.linalg.norm(north)


def calculate_angles(body, et):

    position, _ = sp.spkpos(
        body,
        et,
        FRAME,
        "NONE",
        "MOON"
    )

    direction = position - site
    direction /= np.linalg.norm(direction)

    elevation = np.degrees(
        np.arcsin(np.clip(np.dot(direction, up), -1.0, 1.0))
    )

    azimuth = np.degrees(
        np.arctan2(
            np.dot(direction, east),
            np.dot(direction, north)
        )
    ) % 360

    visibility = (
        "ABOVE_HORIZON"
        if elevation > 0
        else "BELOW_HORIZON"
    )

    return elevation, azimuth, visibility

try:
    for kernel in kernels:
        sp.furnsh(str(kernel))

    frame_id = sp.namfrm(FRAME)

    if frame_id == 0:
        raise RuntimeError(
            f"Required lunar frame not found: {FRAME}"
        )

    test_et = sp.str2et(START_TIME.strftime("%Y-%m-%dT%H:%M:%S"))

    transformation = sp.pxform(
        FRAME,
        "MOON_PA_DE440",
        test_et
    )

    if not np.all(np.isfinite(transformation)):
        raise RuntimeError("Invalid lunar frame transformation.")

    print("SPICE kernels loaded successfully.")
    print(f"Reference frame: {FRAME}")
    print(f"Frame ID: {frame_id}")
    print("ME-to-PA transformation verified.")


    start_time = START_TIME
    end_time = END_TIME
    sampling_interval_minutes = 10

    results = []

    print("\nLUNAPILOT - SUN AND EARTH ANGLE ANALYSIS")
    print(f"Start UTC: {START_TIME}")
    print(f"End UTC: {END_TIME}")
    print(f"Landing site: {LATITUDE}° latitude, {LONGITUDE}° longitude")
    print(f"Reference frame: {FRAME}")
    print("-" * 75)

    sample_times = []

    current_time = start_time

    while current_time <= end_time:
        sample_times.append(current_time)
        current_time += timedelta(minutes=sampling_interval_minutes)

    if sample_times[-1] != end_time:
        sample_times.append(end_time)


    for current_time in sample_times:

        utc = current_time.strftime("%Y-%m-%dT%H:%M:%S")
        et = sp.str2et(utc)

        sun_elevation, sun_azimuth, sun_visibility = (
            calculate_angles("SUN", et)
        )

        earth_elevation, earth_azimuth, earth_visibility = (
            calculate_angles("EARTH", et)
        )

        result = {
            "utc": utc,
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "reference_frame": FRAME,
            "sun_elevation_deg": round(sun_elevation, 6),
            "sun_azimuth_deg": round(sun_azimuth, 6),
            "sun_geometric_visibility": sun_visibility,
            "earth_elevation_deg": round(earth_elevation, 6),
            "earth_azimuth_deg": round(earth_azimuth, 6),
            "earth_geometric_visibility": earth_visibility,
        }

        results.append(result)

        print(f"\nUTC: {utc}")
        print(
            f"SUN   | Elevation: {sun_elevation:8.3f}° | "
            f"Azimuth: {sun_azimuth:8.3f}° | {sun_visibility}"
        )
        print(
            f"EARTH | Elevation: {earth_elevation:8.3f}° | "
            f"Azimuth: {earth_azimuth:8.3f}° | {earth_visibility}"
        )

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as file:

        writer = csv.DictWriter(
            file,
            fieldnames=results[0].keys()
        )

        writer.writeheader()
        writer.writerows(results)

    print("\n" + "-" * 75)
    print(f"Total measurements: {len(results)}")
    print(f"CSV saved to: {OUTPUT_FILE}")
    print("Analysis completed successfully.")


finally:
    sp.kclear()
