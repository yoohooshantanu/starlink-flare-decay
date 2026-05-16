"""
validate_physical.py — Implementation Template for Physical Density Validation.

This script demonstrates how to integrate the NRLMSISE-00 model to compute 
density residuals (Observed vs. Model) for Starlink decay events.

Requirements:
    pip install pymsise
"""
import json
import numpy as np
from datetime import datetime

# NOTE: Placeholder for physical model library
# from pymsise import msis

def get_msise_density(dt, alt_km, lat, lon, f107, f107a, ap):
    """
    Computes theoretical density using NRLMSISE-00.
    
    Args:
        dt: datetime object
        alt_km: altitude in km
        lat, lon: geodetic coordinates
        f107: Daily F10.7 index
        f107a: 81-day average F10.7 index
        ap: geomagnetic ap index
        
    Returns:
        Density in kg/m^3
    """
    # This is where the call to the physical model would happen:
    # output = msis.create_options(f107, f107a, ap)
    # density = msis.run(dt, alt_km, lat, lon, options=output)
    
    # Placeholder implementation:
    # A simple exponential atmosphere as a first-order proxy
    rho0 = 1.0e-12 # kg/m^3 at 500km
    H = 65.0       # scale height in km
    rho = rho0 * np.exp(-(alt_km - 500) / H)
    
    # Scale by solar activity (mock relationship)
    activity_factor = (f107 / 150.0) * (1 + ap / 50.0)
    return rho * activity_factor

def validate_event(event_data):
    """
    Computes the residual between observed decay and model-predicted decay.
    """
    obs_decay = event_data['flare_rate']['mean']
    alt = event_data['altitude']
    
    # Inputs for the model (usually fetched from space_weather.json)
    f107 = event_data.get('f107', 150.0)
    ap = event_data.get('ap', 15.0)
    
    # Compute theoretical density
    rho_model = get_msise_density(datetime.now(), alt, 0, 0, f107, f107, ap)
    
    # Convert density to decay rate (m/day)
    # Using the drag equation: a_dot = -2 * rho * B * sqrt(mu * a)
    B = 0.0746 # m^2/kg
    MU = 3.986e14
    A = (6371 + alt) * 1000
    predicted_decay_accel = -2 * rho_model * B * np.sqrt(MU * A)
    
    # Convert to m/day
    predicted_decay_m_day = abs(predicted_decay_accel) * 86400
    
    residual = obs_decay - predicted_decay_m_day
    ratio = obs_decay / predicted_decay_m_day if predicted_decay_m_day > 0 else 1.0
    
    return {
        "observed": obs_decay,
        "predicted": predicted_decay_m_day,
        "residual": residual,
        "ratio": ratio
    }

if __name__ == "__main__":
    # Mock event data
    event = {
        "flare_rate": {"mean": 13.0},
        "altitude": 550.0,
        "f107": 220.0,
        "ap": 110.0
    }
    
    results = validate_event(event)
    print("--- Physical Validation Results ---")
    print(f"Observed Decay:  {results['observed']:.2f} m/day")
    print(f"Predicted (Model): {results['predicted']:.2f} m/day")
    print(f"Residual:         {results['residual']:.2f} m/day")
    print(f"Density Ratio (Obs/Model): {results['ratio']:.3f}")
