# End-to-end reproducibility pipeline for Starlink Flare Decay analysis

Write-Host "Starting Starlink Flare Decay Pipeline..." -ForegroundColor Cyan

Write-Host "[1/7] Fetching space weather indices..."
python fetch_spaceweather.py

Write-Host "[2/7] Fetching flare events (NASA API)..."
python fetch_flares.py

Write-Host "[3/7] Computing decay rates (with orbital mechanics formalization)..."
python compute_decay.py

Write-Host "[4/7] Aligning windows..."
python align_events.py

Write-Host "[5/7] Running statistical analysis (multivariate regression & sensitivity)..."
python analyze_decay.py

Write-Host "[6/7] Generating scientific figures..."
python visualize_decay.py

Write-Host "[7/7] Generating final case study report..."
python generate_report.py

Write-Host "Done. Final report available at REPORT.md" -ForegroundColor Green
