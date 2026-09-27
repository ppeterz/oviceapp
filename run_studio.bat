@echo off
title O-Voice Studio Server
echo ========================================================
echo           Starting O-Voice Studio Server...
echo ========================================================
echo.
echo Server running at: http://127.0.0.1:8000
echo Press Ctrl+C in this window to stop the server.
echo.
start "" "http://127.0.0.1:8000"
python server.py
pause
