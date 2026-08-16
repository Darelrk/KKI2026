@echo off
echo ==========================================
echo  Starting ASV Backend & Vision Pipeline
echo  Logitech webcam (camera index 1), no Pixhawk
echo ==========================================
cd /d %~dp0
set CAMERA=1
set ASV_PIXHAWK_ENABLED=false
start "Backend Bridge" cmd /k "python -m uvicorn asv_dashboard_backend.main:app --host 0.0.0.0 --port 8080"
timeout /t 2 >nul
python vision_test.py --manual-rc --model model/best.pt --camera "%CAMERA%" --invert-steering --bridge-url http://127.0.0.1:8080 --throttle-near-pwm 1540 --throttle-pwm 1560 --throttle-far-pwm 1600 --throttle-hold-s 0.8 --throttle-ramp-pwm-per-s 200 --throttle-steering-boost-pwm 25
pause
