@echo off
echo =======================================================
echo  Launching Webots ASV Simulation (KKI2026 Coast Guard)
echo =======================================================
cd /d %~dp0
set WEBOTS_HOME=C:\Program Files\Webots
set WORLD=D:\KKI2\KKI2026\simulation\webots\worlds\kki_pool_arena.wbt

if not exist "%WEBOTS_HOME%\msys64\mingw64\bin\webots.exe" (
    echo Error: Webots not found at %WEBOTS_HOME%
    pause
    exit /b 1
)

echo Opening Webots 3D Viewport in Realtime Mode...
start "" "%WEBOTS_HOME%\msys64\mingw64\bin\webots.exe" --mode=realtime "%WORLD%"
