import time

IMPORT_START = time.perf_counter()

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import rasterio
import spiceypy as sp
from naif_de440 import de440
from naif_leapseconds import leapseconds
from pyproj import Geod, Transformer

IMPORT_END = time.perf_counter()


ENGINE_DIR = Path(__file__).resolve().parents[1]

TERRAIN_PATH = ENGINE_DIR / "data" / "terrain" / "LDEM_80S_80MPP_ADJ.tiff"

MOON_RADIUS = 1737400.0
SEARCH_RADIUS = 50000
SAMPLE_INTERVAL = 80
BEARING_COUNT = 360
STEP_MINUTES = 10

OUTPUT_DECIMALS = 3


def load_spice_kernels():
    kernels = [
        leapseconds,
        de440,
        ENGINE_DIR / "kernels" / "moon_orientation" / "pck00011.tpc",
        ENGINE_DIR / "kernels" / "moon_orientation" / "moon_de440_220930.tf",
        ENGINE_DIR / "kernels" / "moon_orientation" / "moon_pa_de440_200625.bpc",
    ]

    for kernel in kernels:
        kernel_path = Path(kernel)
        if not kernel_path.exists():
            raise FileNotFoundError(f"SPICE kernel not found: {kernel_path}")
        sp.furnsh(str(kernel_path))


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Calculate lunar sunlight and Earth communication visibility."
    )
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    parser.add_argument("--analysis-start", required=True)
    parser.add_argument("--analysis-end", required=True)
    return parser.parse_args()


def validate_inputs(latitude, longitude, analysis_start, analysis_end):
    try:
        start = datetime.fromisoformat(analysis_start)
        end = datetime.fromisoformat(analysis_end)
    except ValueError as error:
        raise ValueError(
            "Dates must use ISO format, for example 2027-01-01T00:00:00."
        ) from error

    if start.tzinfo is not None or end.tzinfo is not None:
        raise ValueError(
            "Dates must be supplied in lunar-site local/UTC-naive ISO format without timezone offsets."
        )

    if not -90 <= latitude <= 90:
        raise ValueError("Latitude must be between -90 and 90 degrees.")

    if not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180 degrees.")

    if start >= end:
        raise ValueError("Analysis end must be after analysis start.")

    if STEP_MINUTES <= 0:
        raise ValueError("STEP_MINUTES must be greater than zero.")

    if SEARCH_RADIUS <= 0 or SAMPLE_INTERVAL <= 0:
        raise ValueError("Terrain search radius and sample interval must be positive.")

    return start, end



def get_site_elevation(latitude, longitude, terrain_path):
    if not terrain_path.exists():
        raise FileNotFoundError(f"Terrain DEM not found: {terrain_path}")

    with rasterio.open(terrain_path) as dem:
        if dem.crs is None or dem.crs.geodetic_crs is None:
            raise ValueError("The terrain DEM does not have a usable coordinate reference system.")

        transformer = Transformer.from_crs(
            dem.crs.geodetic_crs,
            dem.crs,
            always_xy=True,
        )
        x, y = transformer.transform(longitude, latitude)

        col_corner, row_corner = (~dem.transform) * (x, y)
        col_center = col_corner - 0.5
        row_center = row_corner - 0.5

        col0 = int(np.floor(col_center))
        row0 = int(np.floor(row_center))
        col_fraction = col_center - col0
        row_fraction = row_center - row0

        if (
            col0 < 0
            or row0 < 0
            or col0 + 1 >= dem.width
            or row0 + 1 >= dem.height
        ):
            raise ValueError(
                "The selected coordinates are outside the coverage of the current south-polar DEM."
            )

        window = rasterio.windows.Window(col0, row0, 2, 2)
        elevation_window = dem.read(1, window=window, masked=True)

        values = np.asarray(elevation_window.data, dtype=np.float64)
        mask = np.ma.getmaskarray(elevation_window) | ~np.isfinite(values)

        weights = np.array([
            [(1.0 - row_fraction) * (1.0 - col_fraction),
             (1.0 - row_fraction) * col_fraction],
            [row_fraction * (1.0 - col_fraction),
             row_fraction * col_fraction],
        ], dtype=np.float64)

        valid_weights = np.where(mask, 0.0, weights)
        weight_total = float(valid_weights.sum())

        if weight_total <= 0:
            raise ValueError(
                "No valid DEM elevation data is available at the selected coordinates."
            )

        elevation = float(np.sum(np.where(mask, 0.0, values) * valid_weights) / weight_total)

        return elevation


def build_site_vectors(latitude, longitude, elevation, moon_radius):
    latitude_rad = np.radians(latitude)
    longitude_rad = np.radians(longitude)
    site_radius_km = (moon_radius + elevation) / 1000.0

    site_iau = site_radius_km * np.array([
        np.cos(latitude_rad) * np.cos(longitude_rad),
        np.cos(latitude_rad) * np.sin(longitude_rad),
        np.sin(latitude_rad),
    ])

    normal_iau = np.array([
        np.cos(latitude_rad) * np.cos(longitude_rad),
        np.cos(latitude_rad) * np.sin(longitude_rad),
        np.sin(latitude_rad),
    ])

    east_iau = np.array([
        -np.sin(longitude_rad),
        np.cos(longitude_rad),
        0.0,
    ])

    north_iau = np.array([
        -np.sin(latitude_rad) * np.cos(longitude_rad),
        -np.sin(latitude_rad) * np.sin(longitude_rad),
        np.cos(latitude_rad),
    ])

    return site_iau, normal_iau, east_iau, north_iau


def calculate_terrain_horizon(
    latitude,
    longitude,
    elevation,
    moon_radius,
    terrain_path,
    search_radius,
    sample_interval,
    bearing_count,
):
    if not terrain_path.exists():
        raise FileNotFoundError(f"Terrain DEM not found: {terrain_path}")

    distances = np.arange(
        sample_interval,
        search_radius + 1,
        sample_interval,
        dtype=np.float64,
    )

    bearings = np.arange(bearing_count, dtype=np.float64)
    lunar_geod = Geod(a=moon_radius, f=0)

    with rasterio.open(terrain_path) as dem:
        transformer = Transformer.from_crs(
            dem.crs.geodetic_crs,
            dem.crs,
            always_xy=True,
        )

        longitudes, latitudes, _ = lunar_geod.fwd(
            np.full((bearing_count, len(distances)), longitude),
            np.full((bearing_count, len(distances)), latitude),
            np.broadcast_to(
                bearings[:, None],
                (bearing_count, len(distances)),
            ),
            np.broadcast_to(
                distances,
                (bearing_count, len(distances)),
            ),
        )

        xs, ys = transformer.transform(longitudes, latitudes)

        rows, cols = rasterio.transform.rowcol(
            dem.transform,
            xs,
            ys,
        )

        rows = np.asarray(rows).reshape(xs.shape)
        cols = np.asarray(cols).reshape(xs.shape)

        inside = (
            (rows >= 0)
            & (rows < dem.height)
            & (cols >= 0)
            & (cols < dem.width)
        )

        if not np.any(inside):
            raise ValueError("No terrain samples fall inside the DEM.")

        row_min = int(rows[inside].min())
        row_max = int(rows[inside].max())
        col_min = int(cols[inside].min())
        col_max = int(cols[inside].max())

        window = rasterio.windows.Window(
            col_min,
            row_min,
            col_max - col_min + 1,
            row_max - row_min + 1,
        )

        terrain_window = dem.read(1, window=window, masked=True)

        elevations = np.full(xs.shape, np.nan, dtype=np.float64)

        sampled = terrain_window.data[
            rows[inside] - row_min,
            cols[inside] - col_min,
        ]

        sampled_mask = np.ma.getmaskarray(terrain_window)[
            rows[inside] - row_min,
            cols[inside] - col_min,
        ]

        valid_samples = (
            ~sampled_mask
            & np.isfinite(sampled)
        )

        inside_indices = np.where(inside)

        elevations[
            inside_indices[0][valid_samples],
            inside_indices[1][valid_samples],
        ] = sampled[valid_samples]

    observer_radius = moon_radius + elevation
    central_angles = distances / moon_radius
    terrain_radii = moon_radius + elevations

    vertical = (
        terrain_radii * np.cos(central_angles)[None, :]
        - observer_radius
    )

    horizontal = (
        terrain_radii * np.sin(central_angles)[None, :]
    )

    terrain_angles = np.degrees(
        np.arctan2(vertical, horizontal)
    )

    horizon_profile = np.full(bearing_count, np.nan, dtype=np.float64)

    for bearing_index in range(bearing_count):
        valid_angles = terrain_angles[bearing_index][
            np.isfinite(terrain_angles[bearing_index])
        ]

        if valid_angles.size:
            horizon_profile[bearing_index] = np.max(valid_angles)

    if not np.all(np.isfinite(horizon_profile)):
        missing = np.where(~np.isfinite(horizon_profile))[0].tolist()
        raise ValueError(
            f"Terrain horizon is missing for bearings: {missing[:20]}"
        )

    terrain_stats = {
        "maximum_horizon": float(np.max(horizon_profile)),
        "maximum_horizon_azimuth": int(np.argmax(horizon_profile)),
        "valid_directions": int(np.count_nonzero(np.isfinite(horizon_profile))),
        "valid_samples": int(np.count_nonzero(np.isfinite(elevations))),
        "total_samples": int(elevations.size),
    }

    return horizon_profile, terrain_stats


def interpolate_horizon(horizon_profile, azimuth):
    bearing_floor = int(np.floor(azimuth)) % len(horizon_profile)
    bearing_next = (bearing_floor + 1) % len(horizon_profile)
    fraction = azimuth - np.floor(azimuth)

    return float(
        horizon_profile[bearing_floor] * (1.0 - fraction)
        + horizon_profile[bearing_next] * fraction
    )


def calculate_body_elevation_azimuth(
    target_name,
    et,
    site_iau,
    normal_iau,
    east_iau,
    north_iau,
    correction,
):
    rotation = sp.pxform(
        "IAU_MOON",
        "MOON_PA_DE440",
        et,
    )

    site_pa = rotation @ site_iau

    normal_pa = rotation @ normal_iau
    normal_pa /= np.linalg.norm(normal_pa)

    east_pa = rotation @ east_iau
    north_pa = rotation @ north_iau

    target_position_j2000, _ = sp.spkpos(
        target_name,
        et,
        "J2000",
        correction,
        "MOON",
    )

    j2000_to_pa = sp.pxform(
        "J2000",
        "MOON_PA_DE440",
        et,
    )

    target_position = j2000_to_pa @ target_position_j2000

    site_to_target = target_position - site_pa
    target_direction = site_to_target / np.linalg.norm(site_to_target)

    elevation = np.degrees(
        np.arcsin(
            np.clip(
                np.dot(target_direction, normal_pa),
                -1.0,
                1.0,
            )
        )
    )

    target_east = np.dot(target_direction, east_pa)
    target_north = np.dot(target_direction, north_pa)

    azimuth = (
        np.degrees(np.arctan2(target_east, target_north)) % 360.0
    )

    return float(elevation), float(azimuth)


def build_time_intervals(start, end, step_minutes):
    intervals = []
    current = start

    while current < end:
        interval_end = min(
            current + timedelta(minutes=step_minutes),
            end,
        )

        midpoint = current + (interval_end - current) / 2

        intervals.append((current, interval_end, midpoint))
        current = interval_end

    return intervals


def merge_visibility_intervals(intervals, visible_key, visible_label, blocked_label):
    timeline = []

    for interval in intervals:
        status = visible_label if interval[visible_key] else blocked_label
        duration = interval["duration_hours"]

        if timeline and timeline[-1]["status"] == status:
            timeline[-1]["end"] = interval["end"]
            timeline[-1]["duration_hours"] += duration
        else:
            timeline.append({
                "start": interval["start"],
                "end": interval["end"],
                "status": status,
                "duration_hours": duration,
            })

    return timeline


def calculate_sun_analysis(
    intervals,
    horizon_profile,
    site_iau,
    normal_iau,
    east_iau,
    north_iau,
    analysis_start,
    analysis_end,
):
    samples = []

    for interval_start, interval_end, midpoint in intervals:
        et = sp.str2et(midpoint.strftime("%Y-%m-%dT%H:%M:%S"))

        sun_elevation, sun_azimuth = calculate_body_elevation_azimuth(
            "SUN",
            et,
            site_iau,
            normal_iau,
            east_iau,
            north_iau,
            "NONE",
        )

        terrain_horizon = interpolate_horizon(
            horizon_profile,
            sun_azimuth,
        )

        visible = sun_elevation > terrain_horizon
        duration_hours = (
            interval_end - interval_start
        ).total_seconds() / 3600.0

        samples.append({
            "start": interval_start.isoformat(timespec="seconds"),
            "end": interval_end.isoformat(timespec="seconds"),
            "visible": visible,
            "duration_hours": duration_hours,
            "sun_elevation": sun_elevation,
            "sun_azimuth": sun_azimuth,
            "terrain_horizon": terrain_horizon,
            "clearance": sun_elevation - terrain_horizon,
        })

    timeline = merge_visibility_intervals(
        samples,
        "visible",
        "sunlight",
        "dark",
    )

    total_hours = sum(item["duration_hours"] for item in samples)

    sunlight_hours = sum(
        item["duration_hours"]
        for item in samples
        if item["visible"]
    )

    darkness_hours = total_hours - sunlight_hours

    for period in timeline:
        period["duration_hours"] = round(
            period["duration_hours"],
            OUTPUT_DECIMALS,
        )
        period["width_percent"] = round(
            period["duration_hours"] / total_hours * 100.0,
            2,
        )

    elevations = [item["sun_elevation"] for item in samples]

    return {
        "visibility": round(sunlight_hours, OUTPUT_DECIMALS),
        "darkness": round(darkness_hours, OUTPUT_DECIMALS),
        "elevation": round(float(np.mean(elevations)), 4),
        "availability": round(
            sunlight_hours / total_hours * 100.0,
            2,
        ) if total_hours else 0.0,
        "sunlight": {
            "analysis_start": analysis_start,
            "analysis_end": analysis_end,
            "timeline": timeline,
        },
        "validation": {
            "sun_elevation_min": round(min(elevations), 4),
            "sun_elevation_max": round(max(elevations), 4),
            "terrain_horizon_min": round(
                min(item["terrain_horizon"] for item in samples),
                4,
            ),
            "terrain_horizon_max": round(
                max(item["terrain_horizon"] for item in samples),
                4,
            ),
            "clearance_min": round(
                min(item["clearance"] for item in samples),
                4,
            ),
            "clearance_max": round(
                max(item["clearance"] for item in samples),
                4,
            ),
            "sample_count": len(samples),
        },
    }


def calculate_earth_analysis(
    intervals,
    horizon_profile,
    site_iau,
    normal_iau,
    east_iau,
    north_iau,
    analysis_start,
    analysis_end,
):
    samples = []

    for interval_start, interval_end, midpoint in intervals:
        et = sp.str2et(midpoint.strftime("%Y-%m-%dT%H:%M:%S"))

        earth_elevation, earth_azimuth = calculate_body_elevation_azimuth(
            "EARTH",
            et,
            site_iau,
            normal_iau,
            east_iau,
            north_iau,
            "LT+S",
        )

        terrain_horizon = interpolate_horizon(
            horizon_profile,
            earth_azimuth,
        )

        visible = earth_elevation > terrain_horizon
        duration_hours = (
            interval_end - interval_start
        ).total_seconds() / 3600.0

        samples.append({
            "start": interval_start.isoformat(timespec="seconds"),
            "end": interval_end.isoformat(timespec="seconds"),
            "visible": visible,
            "duration_hours": duration_hours,
            "earth_elevation": earth_elevation,
            "earth_azimuth": earth_azimuth,
            "terrain_horizon": terrain_horizon,
        })

    timeline = merge_visibility_intervals(
        samples,
        "visible",
        "visible",
        "blackout",
    )

    total_hours = sum(item["duration_hours"] for item in samples)

    visibility_duration = sum(
        item["duration_hours"]
        for item in samples
        if item["visible"]
    )

    blackout_duration = total_hours - visibility_duration

    comm_windows = []
    blackout_windows = []

    for period in timeline:
        period["duration_hours"] = round(
            period["duration_hours"],
            OUTPUT_DECIMALS,
        )

        if period["status"] == "visible":
            comm_windows.append({
                "start": period["start"],
                "end": period["end"],
                "duration_hours": period["duration_hours"],
            })
        else:
            blackout_windows.append({
                "start": period["start"],
                "end": period["end"],
                "duration_hours": period["duration_hours"],
            })

    earth_elevations = [item["earth_elevation"] for item in samples]

    return {
        "visibility_duration": round(
            visibility_duration,
            OUTPUT_DECIMALS,
        ),
        "blackout_duration": round(
            blackout_duration,
            OUTPUT_DECIMALS,
        ),
        "visibility_percentage": round(
            visibility_duration / total_hours * 100.0,
            2,
        ) if total_hours else 0.0,
        "comm_windows": comm_windows,
        "blackout_windows": blackout_windows,
        "timeline": timeline,
        "analysis_start": analysis_start,
        "analysis_end": analysis_end,
        "communication_duration": round(
            visibility_duration,
            OUTPUT_DECIMALS,
        ),
        "communication_windows_count": len(comm_windows),
        "earth_elevation_min": round(min(earth_elevations), 4),
        "earth_elevation_max": round(max(earth_elevations), 4),
        "sample_count": len(samples),
    }


def main():
    args = parse_arguments()

    start_time, end_time = validate_inputs(
        args.latitude,
        args.longitude,
        args.analysis_start,
        args.analysis_end,
    )

    elevation = get_site_elevation(
        args.latitude,
        args.longitude,
        TERRAIN_PATH,
    )

    if elevation <= -MOON_RADIUS:
        raise ValueError("Landing-site elevation is invalid.")

    load_spice_kernels()

    try:
        site_iau, normal_iau, east_iau, north_iau = build_site_vectors(
            args.latitude,
            args.longitude,
            elevation,
            MOON_RADIUS,
        )

        horizon_profile, terrain_stats = calculate_terrain_horizon(
            args.latitude,
            args.longitude,
            elevation,
            MOON_RADIUS,
            TERRAIN_PATH,
            SEARCH_RADIUS,
            SAMPLE_INTERVAL,
            BEARING_COUNT,
        )

        intervals = build_time_intervals(
            start_time,
            end_time,
            STEP_MINUTES,
        )

        sun_analysis = calculate_sun_analysis(
            intervals,
            horizon_profile,
            site_iau,
            normal_iau,
            east_iau,
            north_iau,
            args.analysis_start,
            args.analysis_end,
        )

        earth_analysis = calculate_earth_analysis(
            intervals,
            horizon_profile,
            site_iau,
            normal_iau,
            east_iau,
            north_iau,
            args.analysis_start,
            args.analysis_end,
        )

        result = {
            "status": "Success",
            "site": {
                "latitude": args.latitude,
                "longitude": args.longitude,
                "elevation": round(elevation, 4),
            },
            "sun_analysis": sun_analysis,
            "earth_analysis": earth_analysis,
            "terrain": {
                "search_radius_m": SEARCH_RADIUS,
                "sample_interval_m": SAMPLE_INTERVAL,
                "maximum_horizon_angle": round(
                    terrain_stats["maximum_horizon"],
                    4,
                ),
                "maximum_horizon_azimuth": terrain_stats[
                    "maximum_horizon_azimuth"
                ],
                "valid_directions": terrain_stats["valid_directions"],
                "valid_samples": terrain_stats["valid_samples"],
                "total_samples": terrain_stats["total_samples"],
            },
        }

        print(json.dumps(result, indent=2, allow_nan=False))

    finally:
        sp.kclear()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        error_result = {
            "status": "Error",
            "message": str(error),
        }
        print(json.dumps(error_result, indent=2))
        raise SystemExit(1)
