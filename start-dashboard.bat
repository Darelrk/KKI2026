@echo off
echo ==========================================
echo  Starting Frontend Dashboard
echo ==========================================
cd /d %~dp0
npm run dev --workspace dashboard %*
pause
