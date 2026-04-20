"""
Phase 2 — Fetch TLE History from Space-Track.

Selects a stratified sample of Starlink + control satellites,
downloads their full GP history, and stores it in a SQLite database.

Output → data/tle_history.db
"""
import json
import sqlite3
import time
from datetime import datetime

from spacetrack import SpaceTrackClient
import spacetrack.operators as op

import config


# ── Database Setup ───────────────────────────────────────────────────────────

def init_db(db_path):
    """Create the SQLite database and table if they don't exist."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tle_records (
            norad_id       INTEGER,
            epoch          TEXT,
            mean_motion    REAL,
            eccentricity   REAL,
            inclination    REAL,
            bstar          REAL,
            tle_line1      TEXT,
            tle_line2      TEXT,
            satellite_group TEXT,
            object_name    TEXT,
            PRIMARY KEY (norad_id, epoch)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS satellite_catalog (
            norad_id       INTEGER PRIMARY KEY,
            object_name    TEXT,
            satellite_group TEXT,
            inclination    REAL,
            period         REAL,
            apogee         REAL,
            perigee        REAL
        )
    """)
    conn.commit()
    return conn


def get_fetched_ids(conn):
    """Return set of NORAD IDs that already have TLE data."""
    cursor = conn.execute("SELECT DISTINCT norad_id FROM tle_records")
    return {row[0] for row in cursor.fetchall()}


# ── Satellite Selection ─────────────────────────────────────────────────────

def select_satellites(st: SpaceTrackClient) -> dict[str, list[dict]]:
    """
    Query the satcat to build a stratified satellite sample.
    Returns dict with keys 'shell1', 'shell2', 'control'.
    """
    print("  Querying satellite catalog for Starlink satellites …")

    # Get all Starlink sats (filter client-side — satcat has limited query params)
    starlink_raw = st.satcat(
        object_name=op.like("STARLINK%"),
        current="Y",
        format="json",
    )
    starlink_sats = json.loads(starlink_raw) if isinstance(starlink_raw, str) else starlink_raw

    # Filter out decayed satellites client-side
    starlink_sats = [s for s in starlink_sats if not s.get("DECAY_DATE")]
    print(f"    Found {len(starlink_sats)} active Starlink satellites")

    # Classify by shell using inclination + apogee
    shell1, shell2 = [], []
    for s in starlink_sats:
        try:
            inc = float(s.get("INCLINATION") or 0)
            apogee = float(s.get("APOGEE") or 0)
            perigee = float(s.get("PERIGEE") or 0)
            norad = int(s["NORAD_CAT_ID"])
            launch_date = s.get("LAUNCH", "")
        except (ValueError, TypeError, KeyError):
            continue

        # Only satellites launched before 2024 (enough history)
        if launch_date and launch_date > "2024-01-01":
            continue

        alt_avg = (apogee + perigee) / 2
        if alt_avg == 0:
            continue

        if (config.SHELL1_INC_RANGE[0] <= inc <= config.SHELL1_INC_RANGE[1]
                and config.SHELL1_ALT_RANGE[0] <= alt_avg <= config.SHELL1_ALT_RANGE[1]):
            shell1.append(s)
        elif (config.SHELL2_INC_RANGE[0] <= inc <= config.SHELL2_INC_RANGE[1]
              and config.SHELL2_ALT_RANGE[0] <= alt_avg <= config.SHELL2_ALT_RANGE[1]):
            shell2.append(s)

    print(f"    Shell 1 candidates: {len(shell1)}")
    print(f"    Shell 2 candidates: {len(shell2)}")

    # Sample — take first N sorted by NORAD ID for reproducibility
    shell1.sort(key=lambda s: int(s["NORAD_CAT_ID"]))
    shell2.sort(key=lambda s: int(s["NORAD_CAT_ID"]))

    selected_shell1 = shell1[:config.SHELL1_COUNT]
    selected_shell2 = shell2[:config.SHELL2_COUNT]

    # ── Control group: non-Starlink LEO debris at 500-600 km ──
    print("  Querying control group (non-Starlink LEO objects 500–600 km) …")
    control_raw = st.satcat(
        object_type="DEBRIS",
        current="Y",
        format="json",
    )
    control_sats = json.loads(control_raw) if isinstance(control_raw, str) else control_raw

    # Filter client-side: not decayed, correct altitude/inclination, not Starlink
    filtered_control = []
    for s in control_sats:
        if s.get("DECAY_DATE"):
            continue
        if "STARLINK" in s.get("OBJECT_NAME", "").upper():
            continue
        try:
            apogee = float(s.get("APOGEE") or 0)
            perigee = float(s.get("PERIGEE") or 0)
            inc = float(s.get("INCLINATION") or 0)
        except (ValueError, TypeError):
            continue
        alt_avg = (apogee + perigee) / 2
        if 500 <= alt_avg <= 600 and 50 <= inc <= 55:
            filtered_control.append(s)

    filtered_control.sort(key=lambda s: int(s["NORAD_CAT_ID"]))
    selected_control = filtered_control[:config.CONTROL_COUNT]

    print(f"    Control candidates: {len(filtered_control)}, selected: {len(selected_control)}")

    return {
        "shell1":  selected_shell1,
        "shell2":  selected_shell2,
        "control": selected_control,
    }


# ── TLE Download ─────────────────────────────────────────────────────────────

def fetch_tle_history(st: SpaceTrackClient, conn: sqlite3.Connection,
                      norad_id: int, group: str, name: str):
    """
    Download full GP history for one satellite and insert into DB.
    """
    try:
        data = st.gp_history(
            norad_cat_id=norad_id,
            epoch=op.inclusive_range(config.START_DATE, config.END_DATE),
            orderby="EPOCH asc",
            format="json",
        )
        records = json.loads(data) if isinstance(data, str) else data
    except Exception as e:
        print(f"      ✗ Error fetching {norad_id}: {e}")
        return 0

    rows = []
    for r in records:
        try:
            rows.append((
                norad_id,
                r.get("EPOCH"),
                float(r.get("MEAN_MOTION", 0)),
                float(r.get("ECCENTRICITY", 0)),
                float(r.get("INCLINATION", 0)),
                float(r.get("BSTAR", 0)),
                r.get("TLE_LINE1", ""),
                r.get("TLE_LINE2", ""),
                group,
                name,
            ))
        except (ValueError, TypeError):
            continue

    if rows:
        conn.executemany("""
            INSERT OR IGNORE INTO tle_records
            (norad_id, epoch, mean_motion, eccentricity, inclination,
             bstar, tle_line1, tle_line2, satellite_group, object_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        conn.commit()

    return len(rows)


# ── Entry Point ──────────────────────────────────────────────────────────────

def main():
    print("═" * 60)
    print("Phase 2 — Fetching TLE History from Space-Track")
    print("═" * 60)

    if not config.SPACETRACK_EMAIL or not config.SPACETRACK_PASSWORD:
        print("  ✗ Space-Track credentials not set in .env")
        return

    st = SpaceTrackClient(
        identity=config.SPACETRACK_EMAIL,
        password=config.SPACETRACK_PASSWORD,
    )
    print("  ✓ Authenticated with Space-Track\n")

    conn = init_db(config.TLE_DB)
    fetched_ids = get_fetched_ids(conn)

    # Select satellites
    groups = select_satellites(st)

    # Save catalog
    for group_name, sats in groups.items():
        for s in sats:
            norad = int(s["NORAD_CAT_ID"])
            conn.execute("""
                INSERT OR REPLACE INTO satellite_catalog
                (norad_id, object_name, satellite_group, inclination, period, apogee, perigee)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                norad,
                s.get("OBJECT_NAME", ""),
                group_name,
                float(s.get("INCLINATION", 0)),
                float(s.get("PERIOD", 0)),
                float(s.get("APOGEE", 0)),
                float(s.get("PERIGEE", 0)),
            ))
    conn.commit()

    # Download TLEs for each group
    total_records = 0
    for group_name, sats in groups.items():
        print(f"\n  ── {group_name} ({len(sats)} satellites) ──")
        for i, s in enumerate(sats, 1):
            norad = int(s["NORAD_CAT_ID"])
            name = s.get("OBJECT_NAME", f"NORAD-{norad}")

            if norad in fetched_ids:
                print(f"    [{i}/{len(sats)}] {name} (#{norad}) — already fetched, skipping")
                continue

            print(f"    [{i}/{len(sats)}] {name} (#{norad}) …", end=" ")
            count = fetch_tle_history(st, conn, norad, group_name, name)
            total_records += count
            print(f"{count} records")

            # Small delay to be polite to the API
            time.sleep(0.5)

    # Summary
    cursor = conn.execute("SELECT COUNT(*) FROM tle_records")
    total_in_db = cursor.fetchone()[0]
    cursor = conn.execute("SELECT COUNT(DISTINCT norad_id) FROM tle_records")
    unique_sats = cursor.fetchone()[0]

    print(f"\n  ✓ Database: {total_in_db} TLE records for {unique_sats} satellites")
    print(f"  ✓ Saved to {config.TLE_DB}")

    conn.close()


if __name__ == "__main__":
    main()
