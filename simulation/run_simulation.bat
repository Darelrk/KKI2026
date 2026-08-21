@echo off
setlocal
title ASV Webots Simulation ^& Navigation Runner
cd /d "%~dp0.."

set "ASV_ARENA=%~1"
if not defined ASV_ARENA set "ASV_ARENA=A"
if /I not "%ASV_ARENA%"=="A" if /I not "%ASV_ARENA%"=="B" (
    echo Arena tidak valid: %ASV_ARENA%. Gunakan A atau B.
    exit /b 2
)
rem Mode default dibuat sensor-only supaya pengujian tidak bergantung pada
rem gate_count/marker_count internal Webots. Scorer lama tetap tersedia dengan
rem argumen kedua "scorer".
set "ASV_SENSOR_FLAG=--sensor-only"
set "ASV_MODE=FIXED-COURSE + CV/SENSOR (tanpa scorer Webots)"
if /I "%~2"=="scorer" (
    set "ASV_SENSOR_FLAG="
    set "ASV_MODE=SCORER"
)
if /I "%~2"=="sensor-only" (
    set "ASV_SENSOR_FLAG=--sensor-only"
    set "ASV_MODE=FIXED-COURSE + CV/SENSOR (tanpa scorer Webots)"
)

echo ========================================================
echo   ASV Webots Arena %ASV_ARENA% ^& Vision Navigation Runner
echo   Mode: %ASV_MODE%
echo ========================================================
echo.

rem Jika world belum aktif, buka otomatis. Jika sudah aktif, pakai proses yang ada.
echo [0/3] Memeriksa Webots pada http://127.0.0.1:8889 ...
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8889/status' -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 goto :webots_ready

echo Webots belum aktif, membuka world Arena %ASV_ARENA% ...
call simulation\start_webots.bat %ASV_ARENA%
echo Menunggu controller Webots siap (maks. 30 detik) ...
set /a ASV_WAIT_COUNT=0 >nul

:wait_webots
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8889/status' -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 goto :webots_ready
set /a ASV_WAIT_COUNT+=1 >nul
if %ASV_WAIT_COUNT% GEQ 30 goto :webots_timeout
timeout /t 1 /nobreak >nul
goto :wait_webots

:webots_timeout
echo.
echo ERROR: Controller Webots belum merespons pada port 8889.
echo Pastikan Webots terpasang, world terbuka, dan controller tidak error.
pause
exit /b 3

:webots_ready
echo Webots siap.

echo [1/3] Menjalankan Sim Pixhawk Bridge di latar belakang...
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5762 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if errorlevel 1 (
    start "Sim Pixhawk MAVLink Bridge" python simulation\sim_pixhawk_bridge.py
) else (
    echo Bridge sudah aktif pada TCP 5762, memakai proses yang ada.
)

echo.
echo [2/3] Menunggu 2 detik untuk inisialisasi socket...
timeout /t 2 /nobreak >nul
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Method Post -Uri 'http://127.0.0.1:8889/reset?arena=%ASV_ARENA%' -TimeoutSec 2 ^| Out-Null } catch { }"
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8889/status' -TimeoutSec 2; if ($r.StatusCode -ne 200) { exit 1 } } catch { exit 1 }"
if errorlevel 1 (
    echo.
    echo ERROR: Webots berhenti atau controller tidak lagi merespons.
    pause
    exit /b 3
)

echo.
echo [3/3] Menjalankan Navigasi Vision YOLO (Webots Stream)...
python -m simulation.vision_test --camera http://127.0.0.1:8889/stream_raw.mjpg --model model\best.pt --endpoint tcp:127.0.0.1:5762 --arena %ASV_ARENA% --duration 0 %ASV_SENSOR_FLAG%

pause
endlocal
