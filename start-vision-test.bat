@echo off
echo ==========================================
echo  Starting ASV Vision Pipeline (Pixhawk Link)
echo ==========================================
cd /d %~dp0
set ENDPOINT=%~1
if "%ENDPOINT%"=="" set ENDPOINT=COM5
python vision_test.py --model model/best.pt --endpoint "%ENDPOINT%" --invert-steering --bridge-url http://127.0.0.1:8080 --throttle-near-pwm 1540 --throttle-pwm 1560 --throttle-far-pwm 1600 --throttle-hold-s 0.8 --throttle-ramp-pwm-per-s 200 --throttle-steering-boost-pwm 25
pause
