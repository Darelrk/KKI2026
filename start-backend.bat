@echo off
echo ==========================================
echo  Starting ASV Dashboard Backend Bridge
echo ==========================================
cd /d %~dp0
python -m uvicorn asv_dashboard_backend.main:app --host 0.0.0.0 --port 8080 %*
pause
