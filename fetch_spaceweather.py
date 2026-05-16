"""
Phase 0 - Fetch Space Weather Indices (Kp, F10.7).

Pulls daily F10.7 solar flux and Kp geomagnetic index data 
from CelesTrak to use as control variables in multivariate regression.
"""
import json
import requests
import pandas as pd
import io
from datetime import datetime
import config

def fetch_celestrak_data():
    """Fetch consolidated space weather data from CelesTrak."""
    url = "https://celestrak.org/SpaceData/SW-Last5Years.csv"
    print(f"  [CelesTrak] Fetching consolidated space weather data...")
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        
        # Use pandas to parse CSV
        df = pd.read_csv(io.StringIO(resp.text))
        
        # Clean column names (CelesTrak often has spaces)
        df.columns = [c.strip() for c in df.columns]
        
        # Map columns: DATE, F10.7_OBS (or F10.7_ADJ), and Kp_SUM (or Kp1-8)
        # CelesTrak columns are usually: DATE, Kp1..Kp8, Kp_SUM, F10.7_OBS, etc.
        combined = {}
        for _, row in df.iterrows():
            date_str = str(row["DATE"]).strip()
            # F10.7_OBS is the actual measured value
            # Kp_SUM is the sum of the 8 daily Kp values (0-72 scale)
            # Note: CelesTrak Kp_SUM is usually 10x the actual value (e.g. 233 means 23.3)
            # but we'll check common formats.
            
            f107 = float(row.get("F10.7_OBS", 100.0))
            kp_sum = float(row.get("KP_SUM", 0.0))
            
            # If KP_SUM is clearly in the 0-800 range, divide by 10 to get 0-80 scale
            if kp_sum > 80:
                kp_sum /= 10.0
                
            combined[date_str] = {
                "kp_sum": kp_sum,
                "f107": f107
            }
        return combined
    except Exception as e:
        print(f"  ERROR: Failed to fetch CelesTrak data: {e}")
        return {}

def main():
    print("=" * 60)
    print("Phase 0 - Fetching Space Weather Indices (CelesTrak)")
    print("=" * 60)
    
    combined = fetch_celestrak_data()
    
    if not combined:
        print("  CRITICAL: No data fetched. Aborting.")
        return

    output_file = config.DATA_DIR / "space_weather.json"
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(combined, f, indent=2)
    print(f"\n  OK Saved {len(combined)} days to {output_file}")

if __name__ == "__main__":
    main()
