@echo off
setlocal
title Buka Arena Webots KKI 2026
cd /d "%~dp0"

set "ASV_ARENA=%~1"
if not defined ASV_ARENA set "ASV_ARENA=A"
if /I not "%ASV_ARENA%"=="A" if /I not "%ASV_ARENA%"=="B" (
    echo Arena tidak valid: %ASV_ARENA%. Gunakan A atau B.
    exit /b 2
)

echo ========================================================
echo   Membuka Arena %ASV_ARENA% Webots KKI 2026 (10-Gate Course)
echo ========================================================
echo.

if exist "C:\Program Files\Webots\msys64\mingw64\bin\webots.exe" (
    rem realtime membuat world langsung berjalan saat launcher dipakai.
    start "" "C:\Program Files\Webots\msys64\mingw64\bin\webots.exe" --mode=realtime "%~dp0webots\worlds\kki_pool_arena.wbt"
) else (
    start "" "%~dp0webots\worlds\kki_pool_arena.wbt"
)
endlocal
