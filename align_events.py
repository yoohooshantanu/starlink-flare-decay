"""
Phase 4 — Align Decay Windows with Flare Events.

For each flare event × each satellite, extracts the mean decay rate
in each analysis window (pre-flare, flare, CME, recovery) and
computes decay ratios.

Output → data/aligned_events.json
"""
import json
from datetime import datetime, timedelta
from collections import defaultdict

import numpy as np

import config


# ── Helpers ──────────────────────────────────────────────────────────────────

def parse_iso(s: str) -> datetime | None:
    """Parse an ISO datetime string."""
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%MZ",
                "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.rstrip("Z"), fmt)
        except ValueError:
            continue
    return None


def window_stats(rates: list[float]) -> dict:
    """Compute summary stats for a list of decay rates."""
    if not rates:
        return {"mean": None, "median": None, "std": None, "n": 0}
    arr = np.array(rates)
    return {
        "mean":   round(float(np.mean(arr)), 4),
        "median": round(float(np.median(arr)), 4),
        "std":    round(float(np.std(arr)), 4),
        "n":      len(rates),
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("═" * 60)
    print("Phase 4 — Aligning Decay Windows with Flare Events")
    print("═" * 60)

    # Load flare events
    with open(config.FLARE_FILE) as f:
        flares = json.load(f)
    print(f"  Loaded {len(flares)} flare events")

    # Load decay rates
    with open(config.DECAY_FILE) as f:
        decay_data = json.load(f)
    print(f"  Loaded {len(decay_data)} decay data points")

    # Index decay data by (norad_id, date)
    # Each satellite gets a dict of date → list of decay records
    sat_decay: dict[int, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for d in decay_data:
        nid = d["norad_id"]
        date_str = d["date"]
        sat_decay[nid][date_str].append(d)

    satellites = list(sat_decay.keys())
    print(f"  Satellites with decay data: {len(satellites)}")

    # Detect overlapping / compound events
    flare_dates = []
    for fl in flares:
        pt = parse_iso(fl.get("peakTime"))
        if pt:
            flare_dates.append(pt)

    # ── Align each flare × satellite ──
    aligned = []
    compound_count = 0

    for fi, flare in enumerate(flares):
        peak = parse_iso(flare.get("peakTime"))
        if not peak:
            continue

        # Check for compound events (another flare within 14 days)
        is_compound = False
        for other_peak in flare_dates:
            if other_peak == peak:
                continue
            gap = abs((other_peak - peak).total_seconds()) / 86400.0
            if gap < 14 and gap > 0:
                is_compound = True
                break

        if is_compound:
            compound_count += 1

        for norad_id in satellites:
            sat_dates = sat_decay[norad_id]

            # Extract rates for each window
            window_rates = {}
            for wname, (w_start, w_end) in config.WINDOWS.items():
                rates = []
                for day_offset in range(w_start, w_end + 1):
                    target_date = (peak + timedelta(days=day_offset)).strftime("%Y-%m-%d")
                    if target_date in sat_dates:
                        for rec in sat_dates[target_date]:
                            if not rec.get("is_maneuver", False):
                                rates.append(rec["decay_rate_m_day"])
                window_rates[wname] = rates

            # Need at least some data in pre-flare and flare windows
            if not window_rates["pre_flare"] or not window_rates["flare_window"]:
                continue

            pre_stats   = window_stats(window_rates["pre_flare"])
            flare_stats = window_stats(window_rates["flare_window"])
            cme_stats   = window_stats(window_rates["cme_window"])
            rec_stats   = window_stats(window_rates["recovery"])

            # Compute decay ratios (flare/pre — values > 1 = more negative = faster decay)
            # Since decay rates are negative, we use absolute values
            pre_abs = abs(pre_stats["mean"]) if pre_stats["mean"] else None
            flare_abs = abs(flare_stats["mean"]) if flare_stats["mean"] else None
            cme_abs = abs(cme_stats["mean"]) if cme_stats["mean"] else None

            decay_ratio_flare = None
            decay_ratio_cme = None
            if pre_abs and pre_abs > 0.01:  # avoid division by near-zero
                if flare_abs is not None:
                    decay_ratio_flare = round(flare_abs / pre_abs, 4)
                if cme_abs is not None:
                    decay_ratio_cme = round(cme_abs / pre_abs, 4)

            # Get satellite group
            group = "unknown"
            for rec in sat_dates.get(list(sat_dates.keys())[0], []):
                group = rec.get("group", "unknown")
                break

            aligned.append({
                "norad_id":          norad_id,
                "group":             group,
                "flare_id":          flare.get("flrID"),
                "flare_class":       flare.get("classType"),
                "class_letter":      flare.get("classLetter"),
                "numeric_intensity": flare.get("numericIntensity"),
                "earth_directed":    flare.get("earthDirected"),
                "has_cme":           flare.get("hasCME"),
                "flare_peak":        flare.get("peakTime"),
                "is_compound":       is_compound,
                "pre_rate":          pre_stats,
                "flare_rate":        flare_stats,
                "cme_rate":          cme_stats,
                "recovery_rate":     rec_stats,
                "decay_ratio_flare": decay_ratio_flare,
                "decay_ratio_cme":   decay_ratio_cme,
            })

    # Summary
    unique_flares = len({a["flare_id"] for a in aligned})
    unique_sats   = len({a["norad_id"] for a in aligned})

    print(f"\n  Aligned records     : {len(aligned)}")
    print(f"  Unique flare events : {unique_flares}")
    print(f"  Unique satellites   : {unique_sats}")
    print(f"  Compound events     : {compound_count}")

    # Save
    with open(config.ALIGNED_FILE, "w") as f:
        json.dump(aligned, f, indent=2)
    print(f"\n  ✓ Saved to {config.ALIGNED_FILE}")


if __name__ == "__main__":
    main()
