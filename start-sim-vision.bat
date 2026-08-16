@echo off
echo =======================================================
echo  Starting ASV Vision & Control Pipeline (Webots Sim)
echo =======================================================
cd /d %~dp0

set MODEL=D:\KKI2\model\best.pt
set SIM_STREAM_URL=http://127.0.0.1:8889/stream.mjpg
set MAVLINK_TCP=tcp:127.0.0.1:5762
set ASV_PIXHAWK_ENABLED=true
set ASV_PIXHAWK_ENDPOINT=%MAVLINK_TCP%

echo 1. Starting Simulated Pixhawk MAVLink Bridge (TCP 5762)...
start "Sim Pixhawk Bridge" cmd /k "python simulation/sim_pixhawk_bridge.py --tcp-port 5762"
timeout /t 2 >nul

echo 2. Starting ASV Backend Bridge (Port 8080)...
start "Backend Bridge" cmd /k "set ASV_PIXHAWK_ENABLED=true&& set ASV_PIXHAWK_ENDPOINT=%MAVLINK_TCP%&& python -m uvicorn asv_dashboard_backend.main:app --host 0.0.0.0 --port 8080"
timeout /t 2 >nul

echo 3. Starting ASV Vision Pipeline on Webots Camera Stream...
python vision_test.py --model "%MODEL%" --camera "%SIM_STREAM_URL%" --endpoint "%MAVLINK_TCP%" --bridge-url http://127.0.0.1:8080 --throttle-near-pwm 1540 --throttle-pwm 1560 --throttle-far-pwm 1600 --throttle-hold-s 0.8 --throttle-ramp-pwm-per-s 200 --throttle-steering-boost-pwm 25

pause
