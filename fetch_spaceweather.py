"""
Phase 0 - Fetch Space Weather Indices (Kp, F10.7).

Pulls daily F10.7 solar flux and Kp geomagnetic index data 
to use as control variables in multivariate regression.
"""
import json
import requests
import pandas as pd
from datetime import datetime
import config

def fetch_kp_indices():
    """Fetch Kp index from GFZ Potsdam (ASCII format)."""
    # Using a reliable GFZ mirror for daily Kp
    url = "https://kp.gfz-potsdam.de/app/json/?start=2022-01-01T00%3A00%3A00Z&end=2025-12-31T23%3A59%3A59Z&index=Kp"
    print("  [GFZ] Fetching Kp indices...")
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        # Convert to date-indexed dictionary of daily sums
        df = pd.DataFrame({
            "datetime": pd.to_datetime(data["datetime"]),
            "kp": data["Kp"]
        })
        df["date"] = df["datetime"].dt.strftime("%Y-%m-%d")
        daily_kp = df.groupby("date")["kp"].sum().to_dict()
        return daily_kp
    except Exception as e:
        print(f"  WARNING: Failed to fetch Kp: {e}")
        return {}

def fetch_f107():
    """Fetch F10.7 solar flux from NOAA."""
    url = "https://services.swpc.noaa.gov/json/solar-radio-flux-penticton.json"
    print("  [NOAA] Fetching F10.7 solar flux...")
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        daily_f107 = {}
        for entry in data:
            date = entry["time_tag"][:10]
            daily_f107[date] = float(entry["flux"])
        return daily_f107
    except Exception as e:
        print(f"  WARNING: Failed to fetch F10.7: {e}")
        return {}

def main():
    print("=" * 60)
    print("Phase 0 - Fetching Space Weather Indices")
    print("=" * 60)
    
    kp_data = fetch_kp_indices()
    f107_data = fetch_f107()
    
    # Merge
    combined = {}
    all_dates = set(kp_data.keys()) | set(f107_data.keys())
    for d in sorted(all_dates):
        combined[d] = {
            "kp_sum": kp_data.get(d, 0.0),
            "f107": f107_data.get(d, 100.0) # Default moderate flux
        }
    
    output_file = config.DATA_DIR / "space_weather.json"
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(combined, f, indent=2)
    print(f"\n  OK Saved {len(combined)} days to {output_file}")

if __name__ == "__main__":
    main()
