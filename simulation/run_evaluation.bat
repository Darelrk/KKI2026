@echo off
title ASV 10-Gate Course Batch Evaluator
cd /d "%~dp0"

echo ========================================================
echo   ASV 10-Gate Course Automated Batch Evaluator
echo ========================================================
echo.

python evaluate_batch.py

pause
