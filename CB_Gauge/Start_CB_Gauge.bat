@echo off
title CB Gauge Engine

echo ====================================================
echo Starting CB Gauge...
echo ====================================================

:: Open the default web browser (it will wait for the server to spin up)
start http://127.0.0.1:9856

:: Start the Python UI in the foreground so closing this window safely stops the server
python cb_gauge_ui.py

pause
