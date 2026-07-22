@echo off
echo ==========================================
echo  Starting ASV Vision Pipeline
echo ==========================================
cd /d %~dp0
python vision_test.py --model model/best.pt --endpoint none --bridge-url http://127.0.0.1:8080 %*
pause
