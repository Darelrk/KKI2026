@echo off
title ASV Webots Simulation & Navigation Runner
cd /d "%~dp0"

echo ========================================================
echo   ASV Webots Simulation & Vision Navigation Runner
echo ========================================================
echo.

echo [1/3] Menjalankan Sim Pixhawk Bridge di latar belakang...
start "Sim Pixhawk MAVLink Bridge" python sim_pixhawk_bridge.py

echo.
echo [2/3] Menunggu 2 detik untuk inisialisasi socket...
timeout /t 2 /nobreak >nul

echo.
echo [3/3] Menjalankan Navigasi Vision YOLO (Webots Stream)...
python vision_test.py --source http://127.0.0.1:8889/stream.mjpg --model model/best.pt --mavlink tcp:127.0.0.1:5762 --sim-mode

pause
