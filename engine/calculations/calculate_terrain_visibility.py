
from pathlib import Path
import csv
import json
import math
import rasterio


ENGINE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = ENGINE_DIR / "results"
TERRAIN_DIR = RESULTS_DIR / "terrain"

ANGLES_FILE = RESULTS_DIR / "landing_site_angle_analysis.csv"
HORIZON_FILE = TERRAIN_DIR / "terrain_horizon_360.csv"
SITE_FILE = TERRAIN_DIR / "terrain_summary.json"

SLOPE_FILE = TERRAIN_DIR / "landing_site_slope.tif"
ASPECT_FILE = TERRAIN_DIR / "landing_site_aspect.tif"

OUTPUT_DIR = RESULTS_DIR / "visibility"

OUTPUT_CSV = OUTPUT_DIR / "terrain_adjusted_visibility.csv"
OUTPUT_JSON = OUTPUT_DIR / "visibility_summary.json"


for file_path in (ANGLES_FILE, HORIZON_FILE, SITE_FILE, SLOPE_FILE, ASPECT_FILE):
    if not file_path.exists():
        raise FileNotFoundError(f"Required file not found: {file_path}")


OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

with open(SITE_FILE, "r", encoding="utf-8") as file:
    site = json.load(file)["landing_site"]

with open(SITE_FILE, "r", encoding="utf-8") as file:
    site = json.load(file)["landing_site"]


landing_longitude = float(site["longitude"])

site_x = float(site["projected_x_metres"])
site_y = float(site["projected_y_metres"])

with rasterio.open(SLOPE_FILE) as slope_dataset:
    slope_row, slope_col = slope_dataset.index(site_x, site_y)
    site_slope = float(slope_dataset.read(1)[slope_row, slope_col])

with rasterio.open(ASPECT_FILE) as aspect_dataset:
    aspect_row, aspect_col = aspect_dataset.index(site_x, site_y)
    site_aspect = float(aspect_dataset.read(1)[aspect_row, aspect_col])

if not math.isfinite(site_slope) or not math.isfinite(site_aspect):
    raise ValueError("Invalid slope or aspect at the landing site.")


def geographic_to_dem_azimuth(azimuth):
    return (
        180.0 + landing_longitude - float(azimuth)
    ) % 360


horizon_by_azimuth = {}



horizon_by_azimuth = {}

with open(HORIZON_FILE, "r", encoding="utf-8", newline="") as file:
    reader = csv.DictReader(file)

    for row in reader:
        azimuth = int(row["azimuth_degrees"])
        value = row["horizon_elevation_degrees"]

        if value.strip():
            horizon_by_azimuth[azimuth] = float(value)

if len(horizon_by_azimuth) != 360:
    raise ValueError(
        f"Expected 360 valid horizon directions, "
        f"found {len(horizon_by_azimuth)}."
    )



def get_horizon_angle(azimuth):
    azimuth = float(azimuth) % 360

    lower = math.floor(azimuth)
    upper = (lower + 1) % 360

    fraction = azimuth - lower

    lower_angle = horizon_by_azimuth[lower]
    upper_angle = horizon_by_azimuth[upper]

    return (
        lower_angle
        + (upper_angle - lower_angle) * fraction
    )

def calculate_surface_illumination(
    sun_elevation,
    sun_azimuth,
    slope,
    aspect
):
    elevation = math.radians(sun_elevation)
    azimuth = math.radians(sun_azimuth)
    slope_angle = math.radians(slope)
    aspect_angle = math.radians(aspect)

    cosine_incidence = (
        math.sin(elevation) * math.cos(slope_angle)
        - math.cos(elevation) * math.sin(slope_angle)
        * math.cos(azimuth - aspect_angle)
    )

    return max(0.0, cosine_incidence)

results = []

with open(ANGLES_FILE, "r", encoding="utf-8", newline="") as file:
    reader = csv.DictReader(file)

    for row in reader:

        for body in ("sun", "earth"):

            elevation = float(row[f"{body}_elevation_deg"])
            azimuth = float(row[f"{body}_azimuth_deg"])

            dem_azimuth = geographic_to_dem_azimuth(azimuth)

            terrain_horizon = get_horizon_angle(dem_azimuth)

            visibility_margin = elevation - terrain_horizon

            terrain_visible = visibility_margin > 0

            surface_illumination = None
            directly_illuminated = None

            if body == "sun":
                surface_illumination = calculate_surface_illumination(
                    elevation,
                    azimuth,
                    site_slope,
                    site_aspect
                )

                directly_illuminated = (
                    terrain_visible and surface_illumination > 0
                )

            result = {
                "utc": row["utc"],
                "body": body.upper(),
                "elevation_degrees": elevation,
                "azimuth_degrees": azimuth,
                "terrain_horizon_degrees": terrain_horizon,
                "visibility_margin_degrees": visibility_margin,
                "geometric_visibility": row[
                    f"{body}_geometric_visibility"
                ],
                "terrain_visibility": (
                    "VISIBLE" if terrain_visible else "BLOCKED"
                ),
                "surface_illumination_factor": (
                    round(surface_illumination, 6)
                    if surface_illumination is not None else None
                ),
                "surface_illumination_percentage": (
                    round(surface_illumination * 100, 2)
                    if surface_illumination is not None else None
                ),
                "directly_illuminated": (
                    directly_illuminated
                    if directly_illuminated is not None else None
                ),
            }

            results.append(result)



fieldnames = [
    "utc",
    "body",
    "elevation_degrees",
    "azimuth_degrees",
    "terrain_horizon_degrees",
    "visibility_margin_degrees",
    "geometric_visibility",
    "terrain_visibility",
    "surface_illumination_factor",
    "surface_illumination_percentage",
    "directly_illuminated"
]

with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as file:
    writer = csv.DictWriter(file, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(results)



summary = {}

for body in ("SUN", "EARTH"):

    body_results = [
        item for item in results
        if item["body"] == body
    ]

    visible_count = sum(
        item["terrain_visibility"] == "VISIBLE"
        for item in body_results
    )

    blocked_count = len(body_results) - visible_count

    summary[body.lower()] = {
        "total_samples": len(body_results),
        "terrain_visible_samples": visible_count,
        "terrain_blocked_samples": blocked_count,
        "terrain_visibility_percentage": round(
            visible_count / len(body_results) * 100,
            2
        )
    }

sun_results = [
    item for item in results
    if item["body"] == "SUN"
]

illuminated_samples = sum(
    item["directly_illuminated"] is True
    for item in sun_results
)

summary["surface_illumination"] = {
    "total_samples": len(sun_results),
    "illuminated_samples": illuminated_samples,
    "not_illuminated_samples": (
        len(sun_results) - illuminated_samples
    ),
    "illumination_percentage": round(
        illuminated_samples / len(sun_results) * 100,
        2
    )
}

summary["analysis"] = {
    "landing_latitude": site["latitude"],
    "landing_longitude": site["longitude"],
    "terrain_horizon_range_metres": 5000,
    "horizon_directions": 360,
    "azimuth_interpolation": "Linear circular interpolation",
    "coordinate_alignment_assumption": (
        "Geographic azimuth converted to DEM projected "
        "azimuth using the landing-site longitude and "
        "the DEM's south polar stereographic projection."
    ),
    "visibility_definition": (
        "Body centre is visible when its elevation "
        "is greater than the terrain horizon angle"
    )
}

with open(OUTPUT_JSON, "w", encoding="utf-8") as file:
    json.dump(summary, file, indent=4)



print("\nLUNAPILOT - TERRAIN-ADJUSTED VISIBILITY")
print("=" * 55)

for body in ("sun", "earth"):

    data = summary[body]

    print(f"\n{body.upper()} VISIBILITY")
    print("-" * 40)

    print(f"Total samples: {data['total_samples']}")
    print(f"Visible: {data['terrain_visible_samples']}")
    print(f"Blocked: {data['terrain_blocked_samples']}")
    print(
        f"Visibility percentage: "
        f"{data['terrain_visibility_percentage']:.2f}%"
    )


print("\nFIRST TIME SAMPLE")
print("-" * 40)

for item in results[:2]:

    print(f"\n{item['body']}")
    print(f"Elevation: {item['elevation_degrees']:.3f}°")
    print(f"Azimuth: {item['azimuth_degrees']:.3f}°")
    print(
        f"Terrain horizon: "
        f"{item['terrain_horizon_degrees']:.3f}°"
    )
    print(
        f"Visibility margin: "
        f"{item['visibility_margin_degrees']:.3f}°"
    )
    print(f"Result: {item['terrain_visibility']}")


print("\nSAVED FILES")
print("-" * 40)
print(OUTPUT_CSV)
print(OUTPUT_JSON)

print("\nTerrain visibility analysis completed successfully.")
