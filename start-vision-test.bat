@echo off
echo ==========================================
echo  Starting ASV Vision Pipeline (Logitech webcam, no Pixhawk)
echo ==========================================
cd /d %~dp0
set CAMERA=1
set ASV_PIXHAWK_ENABLED=false
python vision_test.py --manual-rc --model model/best.pt --camera "%CAMERA%" --invert-steering --bridge-url http://127.0.0.1:8080 --throttle-near-pwm 1540 --throttle-pwm 1560 --throttle-far-pwm 1600 --throttle-hold-s 0.8 --throttle-ramp-pwm-per-s 200 --throttle-steering-boost-pwm 25
pause
