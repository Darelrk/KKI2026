@echo off
echo ==========================================
echo  Starting ASV Backend & Vision Pipeline
echo ==========================================
cd /d %~dp0
start "Backend Bridge" cmd /k "python -m uvicorn asv_dashboard_backend.main:app --host 0.0.0.0 --port 8080"
timeout /t 2 >nul
python vision_test.py --model model/best.pt --endpoint none --bridge-url http://127.0.0.1:8080 %*
pause
