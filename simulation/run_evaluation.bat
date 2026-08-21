@echo off
setlocal
title ASV 10-Gate Course Batch Evaluator
cd /d "%~dp0"

set "ASV_ARENA=%~1"
if not defined ASV_ARENA set "ASV_ARENA=A"
if /I not "%ASV_ARENA%"=="A" if /I not "%ASV_ARENA%"=="B" (
    echo Arena tidak valid: %ASV_ARENA%. Gunakan A atau B.
    exit /b 2
)

echo ========================================================
echo   ASV Arena %ASV_ARENA% 10-Gate Automated Batch Evaluator
echo ========================================================
echo.

python evaluate_batch.py --arena %ASV_ARENA% --duration 300

pause
endlocal
