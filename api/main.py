import json
from datetime import datetime


def process_sunlight_timeline(data):

    sun_analysis = data["sun_analysis"]
    sunlight_data = sun_analysis["sunlight"]

    # Get the complete analysis period
    analysis_start = datetime.fromisoformat(
        sunlight_data["analysis_start"]
    )

    analysis_end = datetime.fromisoformat(
        sunlight_data["analysis_end"]
    )

    total_hours = (
        analysis_end - analysis_start
    ).total_seconds() / 3600

    sunlight_hours = 0
    darkness_hours = 0

    previous_end = analysis_start

    # Process each timeline interval
    for interval in sunlight_data["timeline"]:

        start = datetime.fromisoformat(interval["start"])
        end = datetime.fromisoformat(interval["end"])

        if start != previous_end:
            raise ValueError("Timeline contains a gap or overlapping interval.")

        if end <= start:
            raise ValueError("Invalid timeline interval.")

        duration = (end - start).total_seconds() / 3600

        if interval["status"] == "sunlight":
            sunlight_hours += duration

        elif interval["status"] == "dark":
            darkness_hours += duration

        else:
            raise ValueError("Unknown sunlight status.")

        # Calculate duration and timeline width
        interval["duration_hours"] = round(duration, 2)

        interval["width_percent"] = round(
            (duration / total_hours) * 100, 2
        )

        previous_end = end

    if previous_end != analysis_end:
        raise ValueError("Timeline does not cover the complete analysis period.")

    # Update summary metrics automatically
    sun_analysis["sunlight_duration"] = round(sunlight_hours, 2)
    sun_analysis["darkness_duration"] = round(darkness_hours, 2)

    sun_analysis["availability"] = round(
        (sunlight_hours / total_hours) * 100, 2
    )

    return data


def process_earth_analysis(data):

    earth = data["earth_analysis"]

    sunlight = data["sun_analysis"]["sunlight"]

    earth["analysis_start"] = sunlight["analysis_start"]
    earth["analysis_end"] = sunlight["analysis_end"]

    analysis_start = datetime.fromisoformat(
        sunlight["analysis_start"]
    )

    analysis_end = datetime.fromisoformat(
        sunlight["analysis_end"]
    )

    total_seconds = (analysis_end - analysis_start).total_seconds()

    if total_seconds <= 0:
        raise ValueError("Invalid Earth analysis period.")

    total_hours = total_seconds / 3600

    comm_windows = earth["comm_windows"]

    communication_hours = 0
    previous_end = None

    for window in comm_windows:

        start = datetime.fromisoformat(window["start"])
        end = datetime.fromisoformat(window["end"])

        if end <= start:
            raise ValueError("Invalid communication window.")

        if start < analysis_start or end > analysis_end:
            raise ValueError("Communication window is outside the analysis period.")

        if previous_end is not None and start < previous_end:
            raise ValueError("Communication windows overlap or are not ordered.")

        duration = (end - start).total_seconds() / 3600

        window["duration_hours"] = round(duration, 2)

        communication_hours += duration

        previous_end = end

    blackout_hours = total_hours - communication_hours

    earth["communication_duration"] = round(communication_hours, 2)

    earth["blackout_duration"] = round(blackout_hours, 2)

    earth["communication_windows_count"] = len(comm_windows)

    return data

json_data = input()

data = json.loads(json_data)
data['status'] = 'Success'

new_data = {
    "sun_analysis": {
        "elevation": 2.6,

        "sunlight": {
            "analysis_start": "2026-11-13T00:00:00",
            "analysis_end": "2026-11-15T00:00:00",

            "timeline": [
                {
                    "start": "2026-11-13T00:00:00",
                    "end": "2026-11-13T05:00:00",
                    "status": "dark"
                },
                {
                    "start": "2026-11-13T05:00:00",
                    "end": "2026-11-13T14:00:00",
                    "status": "sunlight"
                },
                {
                    "start": "2026-11-13T14:00:00",
                    "end": "2026-11-13T20:00:00",
                    "status": "dark"
                },
                {
                    "start": "2026-11-13T20:00:00",
                    "end": "2026-11-14T06:00:00",
                    "status": "sunlight"
                },
                {
                    "start": "2026-11-14T06:00:00",
                    "end": "2026-11-14T11:00:00",
                    "status": "dark"
                },
                {
                    "start": "2026-11-14T11:00:00",
                    "end": "2026-11-14T18:00:00",
                    "status": "sunlight"
                },
                {
                    "start": "2026-11-14T18:00:00",
                    "end": "2026-11-15T00:00:00",
                    "status": "dark"
                }
            ]
        }
    },

    "earth_analysis": {
        "visibility_duration": 18,
        "blackout_duration": 30,
        "visibility_percentage": 37.5,
        "comm_windows": [
            {
                "start": "2026-11-13T00:00:00",
                "end": "2026-11-13T06:00:00",
                "duration_hours": 6
            },
            {
                "start": "2026-11-13T12:00:00",
                "end": "2026-11-14T00:00:00",
                "duration_hours": 12
            }
        ]
    }
}

processed_data = process_sunlight_timeline(new_data)
processed_data = process_earth_analysis(processed_data)

response = {
    "status": "Success",

    "sun_analysis": {
        "visibility": processed_data["sun_analysis"]["sunlight_duration"],
        "darkness": processed_data["sun_analysis"]["darkness_duration"],
        "elevation": processed_data["sun_analysis"]["elevation"],
        "availability": processed_data["sun_analysis"]["availability"],

        "sunlight": processed_data["sun_analysis"]["sunlight"]
    },

    "earth_analysis": processed_data["earth_analysis"]
}

json_data = json.dumps(response)

print(json_data)
