@echo off
title Buka Arena Webots KKI 2026
cd /d "%~dp0"

echo ========================================================
echo   Membuka Arena Kolam Webots KKI 2026 (10-Gate Course)
echo ========================================================
echo.

if exist "C:\Program Files\Webots\msys64\mingw64\bin\webots.exe" (
    start "" "C:\Program Files\Webots\msys64\mingw64\bin\webots.exe" "%~dp0webots\worlds\kki_pool_arena.wbt"
) else (
    start "" "%~dp0webots\worlds\kki_pool_arena.wbt"
)
