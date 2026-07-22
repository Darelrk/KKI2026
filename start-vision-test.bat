@echo off
echo ==========================================
echo  Starting ASV Vision Pipeline (Pixhawk Link)
echo ==========================================
cd /d %~dp0
set ENDPOINT=%~1
if "%ENDPOINT%"=="" set ENDPOINT=/dev/ttyACM0
python vision_test.py --model model/best.pt --endpoint %ENDPOINT% --bridge-url http://127.0.0.1:8080
pause
