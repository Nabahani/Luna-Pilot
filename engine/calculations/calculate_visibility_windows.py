
from pathlib import Path
import csv
import json
from datetime import datetime

ENGINE_DIR = Path(__file__).resolve().parents[1]

INPUT_FILE = ENGINE_DIR / "results" / "visibility" / "terrain_adjusted_visibility.csv"

OUTPUT_DIR = ENGINE_DIR / "results" / "visibility"
CSV_OUTPUT = OUTPUT_DIR / "visibility_windows.csv"
JSON_OUTPUT = OUTPUT_DIR / "visibility_windows.json"

SAMPLE_INTERVAL_MINUTES = 10


def extract_windows(body, condition, samples):

    windows = []
    current_window = []

    for row in samples:

        timestamp = datetime.fromisoformat(row["utc"])
        status = row["status"]

        if current_window:

            previous = current_window[-1]

            previous_time = datetime.fromisoformat(
                previous["utc"]
            )

            time_gap = (
                timestamp - previous_time
            ).total_seconds() / 60

            if (
                status != previous["status"]
                or time_gap != SAMPLE_INTERVAL_MINUTES
            ):

                windows.append(
                    create_window(
                        body, condition, current_window
                    )
                )

                current_window = []

        current_window.append(row)

    if current_window:

        windows.append(
            create_window(body, condition, current_window)
        )

    return windows


def create_window(body, condition, samples):

    start_time = datetime.fromisoformat(samples[0]["utc"])
    end_time = datetime.fromisoformat(samples[-1]["utc"])

    duration = (
        end_time - start_time
    ).total_seconds() / 60

    margins = [
        sample["margin"]
        for sample in samples
        if sample["margin"] is not None
    ]

    return {
        "body": body,
        "condition": condition,
        "status": samples[0]["status"],
        "start_utc": samples[0]["utc"],
        "end_utc": samples[-1]["utc"],
        "duration_minutes": duration,
        "sample_count": len(samples),
        "minimum_visibility_margin_degrees": (
            round(min(margins), 6) if margins else None
        )
    }


def calculate_windows():

    with open(
        INPUT_FILE, "r", newline="", encoding="utf-8"
    ) as file:

        reader = csv.DictReader(file)
        rows = list(reader)
        columns = reader.fieldnames or []

    required_columns = {
        "utc",
        "body",
        "terrain_visibility",
        "visibility_margin_degrees",
        "directly_illuminated"
    }

    if not rows or not required_columns.issubset(columns):

        raise ValueError(
            "Input CSV is empty or missing required columns."
        )

    windows = []

    configurations = [
        ("SUN", "TERRAIN_VISIBILITY"),
        ("SUN", "SURFACE_ILLUMINATION"),
        ("EARTH", "TERRAIN_VISIBILITY")
    ]

    for body, condition in configurations:

        body_rows = [
            row for row in rows
            if row["body"].strip().upper() == body
        ]

        body_rows.sort(
            key=lambda row: datetime.fromisoformat(row["utc"])
        )

        samples = []

        for row in body_rows:

            if condition == "TERRAIN_VISIBILITY":

                status = row["terrain_visibility"].strip().upper()

                if status not in ("VISIBLE", "BLOCKED"):
                    raise ValueError(
                        f"Unexpected terrain visibility: {status}"
                    )

                margin = float(
                    row["visibility_margin_degrees"]
                )

            else:

                value = row["directly_illuminated"].strip().lower()

                if value not in ("true", "false"):
                    raise ValueError(
                        f"Unexpected illumination value: {value}"
                    )

                status = (
                    "ILLUMINATED"
                    if value == "true"
                    else "NOT_ILLUMINATED"
                )

                margin = None

            samples.append({
                "utc": row["utc"],
                "status": status,
                "margin": margin
            })

        windows.extend(
            extract_windows(body, condition, samples)
        )

    return windows, len(rows)


def main():

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    windows, total_samples = calculate_windows()

    fieldnames = [
        "body",
        "condition",
        "status",
        "start_utc",
        "end_utc",
        "duration_minutes",
        "sample_count",
        "minimum_visibility_margin_degrees"
    ]

    with open(
        CSV_OUTPUT, "w", newline="", encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file, fieldnames=fieldnames
        )

        writer.writeheader()
        writer.writerows(windows)

    summary = {
        "analysis": {
            "total_samples": total_samples,
            "sampling_interval_minutes": SAMPLE_INTERVAL_MINUTES,
            "conditions_analyzed": [
                "SUN_TERRAIN_VISIBILITY",
                "SUN_SURFACE_ILLUMINATION",
                "EARTH_TERRAIN_VISIBILITY"
            ],
            "window_count": len(windows),
            "duration_definition": (
                "Time between the first and last samples "
                "in each window; actual transition times "
                "are between sampled timestamps."
            )
        },
        "windows": windows
    }

    with open(
        JSON_OUTPUT, "w", encoding="utf-8"
    ) as file:

        json.dump(summary, file, indent=4)

    print("LUNARPILOT - VISIBILITY WINDOW ANALYSIS")
    print("=" * 50)

    print(f"Total input samples: {total_samples}")
    print(f"Total windows: {len(windows)}")

    for body, condition in [
        ("SUN", "TERRAIN_VISIBILITY"),
        ("SUN", "SURFACE_ILLUMINATION"),
        ("EARTH", "TERRAIN_VISIBILITY")
    ]:

        matching = [
            window for window in windows
            if window["body"] == body
            and window["condition"] == condition
        ]

        print(f"\n{body} - {condition}: {len(matching)} windows")

    print("\nSAVED FILES")
    print(CSV_OUTPUT)
    print(JSON_OUTPUT)

    print("\nVisibility window analysis completed successfully.")


if __name__ == "__main__":
    main()
