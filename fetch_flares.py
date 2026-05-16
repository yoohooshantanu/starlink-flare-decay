"""
Phase 1 - Fetch Solar Flare Events from NASA DONKI API.

Pulls all M- and X-class flares from START_DATE to END_DATE,
enriches each event with numeric intensity, earth-directed flag,
and linked CME information.

Output -> data/flare_events.json
"""
import json
import re
import time
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

import requests
import config

load_dotenv()
# Priority: .env > config.py > DEMO_KEY
NASA_API_KEY = os.getenv("NASA_API_KEY", getattr(config, "NASA_API_KEY", "DEMO_KEY"))


# -- Helpers ------------------------------------------------------------------

def parse_flare_class(class_type: str) -> tuple[str, float]:
    """
    Parse a GOES flare class string like 'X1.1' or 'M5.3'.
    Returns (letter, numeric_intensity).
    """
    match = re.match(r"([ABCMX])(\d+\.?\d*)", class_type)
    if not match:
        return ("?", 0.0)
    letter = match.group(1)
    value = float(match.group(2))
    if letter == "X":
        return (letter, value * 10.0)   # express on M-scale
    return (letter, value)


def is_above_threshold(class_type: str, min_class: str = config.MIN_FLARE_CLASS) -> bool:
    """Return True if flare class >= min_class."""
    _, intensity = parse_flare_class(class_type)
    _, min_intensity = parse_flare_class(min_class)
    return intensity >= min_intensity


def parse_source_location(loc: str | None) -> tuple[float | None, float | None]:
    """Parse heliographic source location string like 'N24E68'."""
    if not loc:
        return (None, None)
    match = re.match(r"([NS])(\d+)([EW])(\d+)", loc)
    if not match:
        return (None, None)
    lat = float(match.group(2)) * (1 if match.group(1) == "N" else -1)
    lon = float(match.group(4)) * (1 if match.group(3) == "E" else -1)
    return (lat, lon)


def is_earth_directed(loc: str | None) -> bool:
    """True if source is within limit of disk center."""
    _, lon = parse_source_location(loc)
    if lon is None:
        return False
    return abs(lon) <= config.EARTH_DIRECTED_LON_LIMIT


# -- Main Fetch ---------------------------------------------------------------

def fetch_flares() -> list[dict]:
    """
    Query DONKI FLR endpoint in 30-day chunks, filter to M1.0+,
    and return enriched event list.
    """
    base_url = "https://api.nasa.gov/DONKI/FLR"
    all_flares: list[dict] = []

    start = datetime.strptime(config.START_DATE, "%Y-%m-%d")
    end   = datetime.strptime(config.END_DATE,   "%Y-%m-%d")
    today = datetime.utcnow()
    if end > today:
        end = today

    cursor = start
    chunk = 0

    while cursor < end:
        chunk_end = min(cursor + timedelta(days=30), end)
        params = {
            "startDate": cursor.strftime("%Y-%m-%d"),
            "endDate":   chunk_end.strftime("%Y-%m-%d"),
            "api_key":   NASA_API_KEY,
        }
        chunk += 1
        print(f"  [DONKI] chunk {chunk}: {params['startDate']} -> {params['endDate']} ...", end=" ", flush=True)

        data = []
        for attempt in range(5):
            try:
                resp = requests.get(base_url, params=params, timeout=30)
                if resp.status_code == 429:
                    wait = (2 ** attempt) * 10
                    print(f" (Rate limited, waiting {wait}s...) ", end="", flush=True)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                if attempt == 4:
                    print(f" (Failed: {e})")
                    break
                time.sleep(5)
        else:
            cursor = chunk_end + timedelta(days=1)
            continue

        if not isinstance(data, list):
            cursor = chunk_end + timedelta(days=1)
            continue

        kept = 0
        for event in data:
            ct = event.get("classType", "")
            if not is_above_threshold(ct):
                continue

            letter, intensity = parse_flare_class(ct)
            linked_cmes = []
            for le in (event.get("linkedEvents") or []):
                aid = le.get("activityID", "")
                if "CME" in aid:
                    linked_cmes.append(aid)

            enriched = {
                "flrID":            event.get("flrID"),
                "beginTime":        event.get("beginTime"),
                "peakTime":         event.get("peakTime"),
                "endTime":          event.get("endTime"),
                "classType":        ct,
                "classLetter":      letter,
                "numericIntensity": round(intensity, 2),
                "sourceLocation":   event.get("sourceLocation"),
                "earthDirected":    is_earth_directed(event.get("sourceLocation")),
                "hasCME":           len(linked_cmes) > 0,
                "linkedCMEs":       linked_cmes,
                "activeRegion":     event.get("activeRegionNum"),
            }
            all_flares.append(enriched)
            kept += 1

        print(f"{len(data)} raw -> {kept} kept")
        cursor = chunk_end + timedelta(days=1)
        time.sleep(1.0)

    all_flares.sort(key=lambda f: f.get("peakTime", ""))
    return all_flares


def main():
    print("=" * 60)
    print("Phase 1 - Fetching Solar Flare Events from DONKI")
    print("=" * 60)
    print(f"  Date range : {config.START_DATE} -> {config.END_DATE}")
    print(f"  Threshold  : {config.MIN_FLARE_CLASS}+")
    print()

    flares = fetch_flares()

    if not flares:
        print("  WARNING: No flares fetched. Check API key or rate limits.")
        return

    # Save
    config.FLARE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.FLARE_FILE, "w") as f:
        json.dump(flares, f, indent=2)
    print(f"\n  OK Saved to {config.FLARE_FILE}")


if __name__ == "__main__":
    main()
