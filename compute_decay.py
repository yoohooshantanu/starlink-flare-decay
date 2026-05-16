"""
Phase 3 - Compute Decay Rates from TLE History.

Reads TLE records from the SQLite database, computes altitude
from mean motion, and derives rolling decay rates in m/day.
Detects maneuver events (altitude increases).

Output → data/decay_rates.json
"""
import json
import math
import sqlite3
from datetime import datetime

import numpy as np
from scipy import stats

import config


# ── Physics ──────────────────────────────────────────────────────────────────

def mean_motion_to_altitude(mean_motion_rev_day: float) -> float:
    """
    Convert mean motion (revolutions/day) to altitude (km).
    a = (μ / n²)^(1/3)   where n is in rad/s
    altitude = a - R_earth
    """
    if mean_motion_rev_day <= 0:
        return float("nan")

    # Convert rev/day → rad/s
    n_rad_s = mean_motion_rev_day * 2.0 * math.pi / 86400.0

    # Semi-major axis in meters
    a = (config.MU / (n_rad_s ** 2)) ** (1.0 / 3.0)

    # Altitude in km
    altitude_km = (a / 1000.0) - config.R_EARTH
    return altitude_km


# ── Decay Rate Computation ───────────────────────────────────────────────────

def compute_rolling_decay(epochs: list[datetime], altitudes: list[float],
                          window_days: int = config.ROLLING_WINDOW_DAYS
                          ) -> list[dict]:
    """
    Compute rolling linear-regression decay rate over a sliding window.
    Returns list of {date, altitude_km, decay_rate_m_day, is_maneuver}.
    """
    n = len(epochs)
    if n < 2:
        return []

    # Convert epochs to fractional days from first epoch
    t0 = epochs[0]
    days = np.array([(e - t0).total_seconds() / 86400.0 for e in epochs])
    alts = np.array(altitudes)

    results = []

    for i in range(n):
        # Find indices within the rolling window centered at i
        day_i = days[i]
        mask = (days >= day_i - window_days / 2) & (days <= day_i + window_days / 2)
        idx = np.where(mask)[0]

        if len(idx) < 2:
            # Not enough points for regression
            results.append({
                "date": epochs[i].strftime("%Y-%m-%d"),
                "epoch": epochs[i].isoformat(),
                "altitude_km": round(alts[i], 4),
                "decay_rate_m_day": 0.0,
                "is_maneuver": False,
            })
            continue

        # Linear regression: altitude (km) vs time (days)
        slope, _, _, _, _ = stats.linregress(days[idx], alts[idx])

        # slope is km/day → convert to m/day
        decay_m_day = round(slope * 1000.0, 2)

        # Maneuver detection: positive slope > threshold means active boost
        is_maneuver = bool(decay_m_day > config.MANEUVER_THRESHOLD)

        # -- Orbital Mechanics Formalization --
        # a = semi-major axis in meters
        a_m = (alts[i] + config.R_EARTH) * 1000.0
        v_m_s = math.sqrt(config.MU / a_m)
        
        # B = ballistic coefficient (m^2/kg)
        B = config.STARLINK_B 
        
        # Implied Density (kg/m^3)
        implied_density = 0.0
        drag_acceleration = 0.0
        if not is_maneuver and decay_m_day < 0:
            abs_decay = abs(decay_m_day)
            implied_density = abs_decay / (86400.0 * B * math.sqrt(config.MU * a_m))
            drag_acceleration = 0.5 * implied_density * (v_m_s ** 2) * B

        results.append({
            "date": epochs[i].strftime("%Y-%m-%d"),
            "epoch": epochs[i].isoformat(),
            "altitude_km": round(alts[i], 4),
            "decay_rate_m_day": decay_m_day,
            "is_maneuver": is_maneuver,
            "implied_density": float(f"{implied_density:.6e}"),
            "drag_acceleration": float(f"{drag_acceleration:.6e}"),
        })

    return results


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Phase 3 - Computing Decay Rates from TLE History")
    print("=" * 60)

    conn = sqlite3.connect(str(config.TLE_DB))

    # Get all satellites
    cursor = conn.execute("""
        SELECT DISTINCT norad_id, satellite_group, object_name
        FROM tle_records
        ORDER BY satellite_group, norad_id
    """)
    satellites = cursor.fetchall()
    print(f"  Processing {len(satellites)} satellites …\n")

    all_decay_data = []
    maneuver_count = 0
    total_points = 0

    for i, (norad_id, group, name) in enumerate(satellites, 1):
        # Fetch TLE records sorted by epoch
        cursor = conn.execute("""
            SELECT epoch, mean_motion
            FROM tle_records
            WHERE norad_id = ?
            ORDER BY epoch ASC
        """, (norad_id,))
        rows = cursor.fetchall()

        if len(rows) < 3:
            print(f"  [{i}/{len(satellites)}] {name} (#{norad_id}) - too few records ({len(rows)}), skipping")
            continue

        # Parse epochs and compute altitudes
        epochs = []
        altitudes = []
        for epoch_str, mm in rows:
            try:
                # Handle various epoch formats
                for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                            "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                    try:
                        ep = datetime.strptime(epoch_str.rstrip("Z"), fmt)
                        break
                    except ValueError:
                        continue
                else:
                    continue

                alt = mean_motion_to_altitude(mm)
                if not math.isnan(alt) and 100 < alt < 2000:
                    epochs.append(ep)
                    altitudes.append(alt)
            except Exception:
                continue

        if len(epochs) < 3:
            continue

        # Compute decay rates
        decay_series = compute_rolling_decay(epochs, altitudes)

        sat_maneuvers = sum(1 for d in decay_series if d["is_maneuver"])
        maneuver_count += sat_maneuvers
        total_points += len(decay_series)

        # Tag each record
        for d in decay_series:
            d["norad_id"] = norad_id
            d["group"] = group
            d["object_name"] = name

        all_decay_data.extend(decay_series)

        status = f"{len(decay_series)} pts"
        if sat_maneuvers:
            status += f", {sat_maneuvers} maneuvers"
        print(f"  [{i}/{len(satellites)}] {name} (#{norad_id}) - {status}")

    conn.close()

    # Summary
    print(f"\n  Total data points  : {total_points}")
    print(f"  Maneuver flags     : {maneuver_count}")

    # Save
    with open(config.DECAY_FILE, "w") as f:
        json.dump(all_decay_data, f, indent=2)
    print(f"\n  ✓ Saved to {config.DECAY_FILE}")


if __name__ == "__main__":
    main()
