"""
Phase 4 - Align Decay Windows with Flare Events.

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


def window_stats(rates: list[float], altitudes: list[float] = None, 
                 densities: list[float] = None, drags: list[float] = None) -> dict:
    """Compute summary stats for a list of decay rates and optional metrics."""
    if not rates:
        return {"mean": None, "median": None, "std": None, "n": 0}
    
    res = {
        "mean":   round(float(np.mean(rates)), 4),
        "median": round(float(np.median(rates)), 4),
        "std":    round(float(np.std(rates)), 4),
        "n":      len(rates),
    }
    
    if altitudes:
        res["altitude_km"] = round(float(np.mean(altitudes)), 2)
    if densities:
        res["implied_density"] = float(f"{np.mean(densities):.6e}")
    if drags:
        res["drag_acceleration"] = float(f"{np.mean(drags):.6e}")
        
    return res


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Phase 4 - Aligning Decay Windows with Flare Events")
    print("=" * 60)

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

    # Pre-calculate satellite group mapping
    sat_groups = {}
    for nid, dates in sat_decay.items():
        # Get group from any record
        for dlist in dates.values():
            if dlist:
                sat_groups[nid] = dlist[0].get("group", "unknown")
                break
        else:
            sat_groups[nid] = "unknown"

    # Detect overlapping / compound events
    flare_dates = [parse_iso(fl.get("peakTime")) for fl in flares if parse_iso(fl.get("peakTime"))]

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
            window_metrics = defaultdict(lambda: {"rates": [], "altitudes": [], "densities": [], "drags": []})
            for wname, (w_start, w_end) in config.WINDOWS.items():
                for day_offset in range(w_start, w_end + 1):
                    target_date = (peak + timedelta(days=day_offset)).strftime("%Y-%m-%d")
                    if target_date in sat_dates:
                        for rec in sat_dates[target_date]:
                            if not rec.get("is_maneuver", False):
                                window_metrics[wname]["rates"].append(rec["decay_rate_m_day"])
                                window_metrics[wname]["altitudes"].append(rec.get("altitude_km", 0))
                                window_metrics[wname]["densities"].append(rec.get("implied_density", 0))
                                window_metrics[wname]["drags"].append(rec.get("drag_acceleration", 0))

            # Need at least some data in pre-flare and flare windows
            if not window_metrics["pre_flare"]["rates"] or not window_metrics["flare_window"]["rates"]:
                continue

            pre_stats   = window_stats(window_metrics["pre_flare"]["rates"], 
                                     window_metrics["pre_flare"]["altitudes"],
                                     window_metrics["pre_flare"]["densities"],
                                     window_metrics["pre_flare"]["drags"])
            flare_stats = window_stats(window_metrics["flare_window"]["rates"],
                                     window_metrics["flare_window"]["altitudes"],
                                     window_metrics["flare_window"]["densities"],
                                     window_metrics["flare_window"]["drags"])
            cme_stats   = window_stats(window_metrics["cme_window"]["rates"],
                                     window_metrics["cme_window"]["altitudes"],
                                     window_metrics["cme_window"]["densities"],
                                     window_metrics["cme_window"]["drags"])
            rec_stats   = window_stats(window_metrics["recovery"]["rates"],
                                     window_metrics["recovery"]["altitudes"],
                                     window_metrics["recovery"]["densities"],
                                     window_metrics["recovery"]["drags"])

            # Compute decay ratios (flare/pre - values > 1 = more negative = faster decay)
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

            group = sat_groups[norad_id]
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
    print(f"\n  OK Saved to {config.ALIGNED_FILE}")


if __name__ == "__main__":
    main()
