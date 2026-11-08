# POSANTRA | VERIQ launcher
Set-Location -Path $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Virtual environment not found. Run:" -ForegroundColor Red
    Write-Host "  python -m venv .venv"
    Write-Host "  .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}

Write-Host "POSANTRA | VERIQ - Detect. Investigate. Verify." -ForegroundColor Green
& $py config.py          # prints Tesseract / ExifTool availability honestly
Write-Host ""
Write-Host "Starting VERIQ at http://localhost:8501 (Ctrl+C to stop)"
& $py -m streamlit run app.py --server.address 127.0.0.1